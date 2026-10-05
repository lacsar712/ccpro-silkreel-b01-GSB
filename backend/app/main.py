from quart import Quart, g, jsonify, request
from quart.helpers import make_response

from app.db import SessionLocal
from app.models import Basin
from app.repositories import BasinRepo, UserRepo, ValveRepo
from app.security import make_token, parse_token, verify_password
from app.services import RuleError, assert_can_set_status, latest_temp

app = Quart(__name__)


def _bearer() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:]
    return None


@app.before_request
async def load_user():
    g.user = None
    token = _bearer()
    if not token:
        return
    username = parse_token(token)
    if not username:
        return
    async with SessionLocal() as session:
        g.user = await UserRepo(session).by_username(username)


def require_user():
    if g.user is None:
        return jsonify({"detail": "未登录"}), 401
    return None


def require_admin():
    denied = require_user()
    if denied:
        return denied
    if g.user.role != "admin":
        return jsonify({"detail": "仅管理员可操作蒸汽总阀"}), 403
    return None


@app.route("/api/health")
async def health():
    return {"status": "ok", "service": "SilkReel"}


@app.route("/api/auth/login", methods=["POST"])
async def login():
    body = await request.get_json(force=True)
    username = (body or {}).get("username", "")
    password = (body or {}).get("password", "")
    async with SessionLocal() as session:
        user = await UserRepo(session).by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            return jsonify({"detail": "用户名或密码错误"}), 401
        return {
            "access_token": make_token(user.username),
            "user": {"username": user.username, "role": user.role},
        }


@app.route("/api/auth/me")
async def me():
    denied = require_user()
    if denied:
        return denied
    return {"username": g.user.username, "role": g.user.role}


def _basin_json(basin: Basin) -> dict:
    return {
        "id": basin.id,
        "code": basin.code,
        "status": basin.status,
        "ringIndex": basin.ring_index,
        "latestTempC": latest_temp(basin),
        "readingCount": len(basin.readings or []),
    }


@app.route("/api/board")
async def board():
    denied = require_user()
    if denied:
        return denied
    async with SessionLocal() as session:
        mill = await BasinRepo(session).board()
        if mill is None:
            return jsonify({"detail": "尚无缫丝坞"}), 404
        basins = sorted(mill.basins, key=lambda b: b.ring_index)
        return {
            "filature": mill.name,
            "riverside": mill.riverside,
            "basins": [_basin_json(b) for b in basins],
        }


@app.route("/api/basins/<int:basin_id>/readings", methods=["POST"])
async def add_reading(basin_id: int):
    denied = require_user()
    if denied:
        return denied
    body = await request.get_json(force=True)
    try:
        temp = float((body or {}).get("waterTempC"))
    except (TypeError, ValueError):
        return jsonify({"detail": "汤温必须是数字"}), 400
    async with SessionLocal() as session:
        repo = BasinRepo(session)
        basin = await repo.get(basin_id)
        if basin is None:
            return jsonify({"detail": "盆不存在"}), 404
        await repo.add_reading(basin, temp, g.user.username)
        basin = await repo.get(basin_id)
        return _basin_json(basin)


@app.route("/api/basins/<int:basin_id>/status", methods=["POST"])
async def set_status(basin_id: int):
    denied = require_user()
    if denied:
        return denied
    body = await request.get_json(force=True)
    status = (body or {}).get("status", "")
    async with SessionLocal() as session:
        repo = BasinRepo(session)
        basin = await repo.get(basin_id)
        if basin is None:
            return jsonify({"detail": "盆不存在"}), 404
        # 状态合法性、以及标已缫完的汤温门槛在此判定（与总阀无关）。
        try:
            assert_can_set_status(basin, status)
        except RuleError as exc:
            return jsonify({"detail": str(exc)}), 400

        if status == Basin.STATUS_REELING:
            valves = ValveRepo(session)
            # 关键：锁总阀行 → 重读该盆落库状态 → 计数 → 落库，须在同一事务内，
            # 两名工并发改两口浸茧时会在总阀行锁上串行，后到者看到真实口数。
            valve = await valves.lock_for_update()
            current = await repo.current_status(basin_id)
            entering = current != Basin.STATUS_REELING
            if valve.enabled and entering:
                used = await valves.count_reeling()
                if used >= valve.max_reeling:
                    max_reeling = valve.max_reeling
                    await session.rollback()
                    return (
                        jsonify(
                            {
                                "detail": (
                                    f"蒸汽总阀口数已满（已 {used}/{max_reeling} 口缫丝中），"
                                    "不能再改成缫丝中"
                                )
                            }
                        ),
                        400,
                    )
        basin.status = status
        await session.commit()
        basin = await repo.get(basin_id)
        return _basin_json(basin)


def _valve_json(valve, used: int) -> dict:
    return {
        "enabled": valve.enabled,
        "maxReeling": valve.max_reeling,
        "usedReeling": used,
        "full": used >= valve.max_reeling,
    }


@app.route("/api/steam-valve")
async def steam_valve():
    denied = require_user()
    if denied:
        return denied
    async with SessionLocal() as session:
        valves = ValveRepo(session)
        valve = await valves.get()
        used = await valves.count_reeling()
        await session.commit()
        return _valve_json(valve, used)


@app.route("/api/steam-valve", methods=["PUT"])
async def update_steam_valve():
    denied = require_admin()
    if denied:
        return denied
    body = await request.get_json(force=True) or {}
    enabled = body.get("enabled")
    raw_max = body.get("maxReeling")
    if not isinstance(enabled, bool):
        return jsonify({"detail": "必须明确是否启用"}), 400
    # 上限必须是正整数：拒绝布尔、浮点串、零、负数。
    if isinstance(raw_max, bool) or not isinstance(raw_max, int) or raw_max <= 0:
        return jsonify({"detail": "同时缫丝口数上限必须是正整数"}), 400
    async with SessionLocal() as session:
        valves = ValveRepo(session)
        valve = await valves.get()
        await valves.save(valve, enabled, raw_max)
        used = await valves.count_reeling()
        return _valve_json(valve, used)
