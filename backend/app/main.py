from quart import Quart, g, jsonify, request
from quart.helpers import make_response

from app.db import SessionLocal
from app.models import Basin
from app.repositories import BasinRepo, UserRepo, ValveRepo
from app.security import make_token, parse_token, verify_password
from app.services import (
    RuleError,
    assert_can_enter_reeling,
    assert_can_set_status,
    latest_temp,
)

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


def _valve_json(setting, reeling_count: int) -> dict:
    return {
        "enabled": setting.enabled,
        "maxReeling": setting.max_reeling,
        "usedReeling": reeling_count,
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
        # 已用口数直接数当前坞里缫丝中的盆，专页与作业台看到的必须是同一个数。
        used = sum(1 for b in basins if b.status == Basin.STATUS_REELING)
        setting = await ValveRepo(session).get()
        valve = (
            _valve_json(setting, used)
            if setting is not None
            else {"enabled": False, "maxReeling": ValveRepo.DEFAULT_MAX, "usedReeling": used}
        )
        return {
            "filature": mill.name,
            "riverside": mill.riverside,
            "basins": [_basin_json(b) for b in basins],
            "valve": valve,
        }


@app.route("/api/valve")
async def get_valve():
    denied = require_user()
    if denied:
        return denied
    async with SessionLocal() as session:
        repo = ValveRepo(session)
        setting = await repo.ensure()
        used = await BasinRepo(session).count_reeling()
        return _valve_json(setting, used)


@app.route("/api/valve", methods=["PUT"])
async def update_valve():
    denied = require_user()
    if denied:
        return denied
    if g.user.role != "admin":
        return jsonify({"detail": "只有管理员能调蒸汽总阀"}), 403
    body = await request.get_json(force=True)
    enabled = bool((body or {}).get("enabled"))
    raw_max = (body or {}).get("maxReeling")
    if isinstance(raw_max, bool) or not isinstance(raw_max, int) or raw_max < 1:
        return jsonify({"detail": "口数上限必须是正整数"}), 400
    async with SessionLocal() as session:
        repo = ValveRepo(session)
        setting = await repo.ensure()
        setting.enabled = enabled
        setting.max_reeling = raw_max
        await repo.save(setting)
        used = await BasinRepo(session).count_reeling()
        return _valve_json(setting, used)


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
        basin_repo = BasinRepo(session)
        valve_repo = ValveRepo(session)
        try:
            # 汤温、已缫完的旧门槛照旧，不看总阀。
            basin = await basin_repo.get(basin_id)
            if basin is None:
                return jsonify({"detail": "盆不存在"}), 404
            assert_can_set_status(basin, status)

            # 顺着既有抽屉把浸茧改成缫丝中：锁总阀行后再点一次盆数，
            # 两名工交叉改两口时，第二笔在锁后看到的是含第一笔的新数。
            if status == Basin.STATUS_REELING and basin.status != Basin.STATUS_REELING:
                setting = await valve_repo.lock()
                reeling_now = await basin_repo.count_reeling()
                assert_can_enter_reeling(basin, setting, reeling_now)

            basin.status = status
            await session.commit()
        except RuleError as exc:
            await session.rollback()
            return jsonify({"detail": str(exc)}), 400
        basin = await basin_repo.get(basin_id)
        return _basin_json(basin)
