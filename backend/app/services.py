"""缫丝盆门槛：标成已缫完须最近一次汤温落在 38～42℃；
浸茧改缫丝中须蒸汽总阀启用且当前口数未满。"""

from app.models import Basin, ValveSetting

MIN_TEMP = 38.0
MAX_TEMP = 42.0


class RuleError(ValueError):
    pass


def latest_temp(basin: Basin) -> float | None:
    if not basin.readings:
        return None
    latest = max(basin.readings, key=lambda r: r.taken_at)
    return latest.water_temp_c


def assert_can_set_status(basin: Basin, new_status: str) -> None:
    allowed = {Basin.STATUS_SOAKING, Basin.STATUS_REELING, Basin.STATUS_REELED}
    if new_status not in allowed:
        raise RuleError(f"无效状态：{new_status}")
    if new_status != Basin.STATUS_REELED:
        return
    temp = latest_temp(basin)
    if temp is None:
        raise RuleError("该盆尚无汤温记录，不能标已缫完")
    if temp < MIN_TEMP or temp > MAX_TEMP:
        raise RuleError(
            f"最近汤温 {temp}℃ 不在 {MIN_TEMP:.0f}～{MAX_TEMP:.0f}℃，不能标已缫完"
        )


def assert_can_enter_reeling(
    basin: Basin, setting: ValveSetting, reeling_count: int
) -> None:
    """浸茧改成缫丝中的总阀门槛。

    调用方必须已用 SELECT … FOR UPDATE 锁住总阀行，并在锁后重新清点
    缫丝中盆数；reeling_count 不含本盆（本盆当前不是缫丝中才会走到这里）。
    """
    if setting.enabled and reeling_count >= setting.max_reeling:
        raise RuleError(
            f"蒸汽总阀口数已满（{reeling_count}/{setting.max_reeling}），"
            "不能再把浸茧改成缫丝中"
        )
