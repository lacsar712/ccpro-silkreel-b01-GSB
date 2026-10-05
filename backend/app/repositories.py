from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Basin, BathReading, Filature, SteamValve, User


class UserRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def by_username(self, username: str) -> User | None:
        result = await self.session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


class BasinRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def board(self) -> Filature | None:
        result = await self.session.execute(
            select(Filature).options(
                selectinload(Filature.basins).selectinload(Basin.readings)
            )
        )
        return result.scalars().first()

    async def get(self, basin_id: int) -> Basin | None:
        result = await self.session.execute(
            select(Basin)
            .options(selectinload(Basin.readings))
            .where(Basin.id == basin_id)
        )
        return result.scalar_one_or_none()

    async def add_reading(self, basin: Basin, temp_c: float, operator: str) -> BathReading:
        row = BathReading(basin=basin, water_temp_c=temp_c, operator=operator)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def save_status(self, basin: Basin, status: str) -> None:
        basin.status = status
        await self.session.commit()

    async def current_status(self, basin_id: int) -> str | None:
        """事务内最新落库状态（拿到总阀行锁后再读，避免并发误判）。"""
        result = await self.session.execute(
            select(Basin.status).where(Basin.id == basin_id)
        )
        return result.scalar_one_or_none()


class ValveRepo:
    """蒸汽总阀单例（id 恒为 1）。"""

    SINGLETON_ID = 1
    DEFAULT_MAX = 3

    def __init__(self, session: AsyncSession):
        self.session = session

    def _new(self) -> SteamValve:
        return SteamValve(
            id=self.SINGLETON_ID, enabled=True, max_reeling=self.DEFAULT_MAX
        )

    async def get(self) -> SteamValve:
        result = await self.session.execute(
            select(SteamValve).where(SteamValve.id == self.SINGLETON_ID)
        )
        valve = result.scalar_one_or_none()
        if valve is None:
            valve = self._new()
            self.session.add(valve)
            await self.session.flush()
        return valve

    async def lock_for_update(self) -> SteamValve:
        """锁住总阀行，让并发的『改成缫丝中』在此串行后再计数。"""
        result = await self.session.execute(
            select(SteamValve)
            .where(SteamValve.id == self.SINGLETON_ID)
            .with_for_update()
        )
        valve = result.scalar_one_or_none()
        if valve is None:
            valve = self._new()
            self.session.add(valve)
            await self.session.flush()
        return valve

    async def count_reeling(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Basin)
            .where(Basin.status == Basin.STATUS_REELING)
        )
        return int(result.scalar_one())

    async def save(self, valve: SteamValve, enabled: bool, max_reeling: int) -> None:
        valve.enabled = enabled
        valve.max_reeling = max_reeling
        await self.session.commit()
