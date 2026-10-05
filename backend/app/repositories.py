from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Basin, BathReading, Filature, User, ValveSetting


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

    async def count_reeling(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Basin)
            .where(Basin.status == Basin.STATUS_REELING)
        )
        return result.scalar_one()


class ValveRepo:
    """蒸汽总阀单行设置；改态事务靠这把行锁串行化。"""

    SINGLETON_ID = 1
    DEFAULT_MAX = 4

    def __init__(self, session: AsyncSession):
        self.session = session

    def _default(self) -> ValveSetting:
        return ValveSetting(
            id=self.SINGLETON_ID, enabled=False, max_reeling=self.DEFAULT_MAX
        )

    async def get(self) -> ValveSetting | None:
        result = await self.session.execute(
            select(ValveSetting).where(ValveSetting.id == self.SINGLETON_ID)
        )
        return result.scalar_one_or_none()

    async def ensure(self) -> ValveSetting:
        setting = await self.get()
        if setting is None:
            setting = self._default()
            self.session.add(setting)
            await self.session.flush()
        return setting

    async def lock(self) -> ValveSetting:
        # 浸茧→缫丝中都在这一行上排队，第二个事务拿到锁后重新计数，无法超口。
        result = await self.session.execute(
            select(ValveSetting)
            .where(ValveSetting.id == self.SINGLETON_ID)
            .with_for_update()
        )
        setting = result.scalar_one_or_none()
        if setting is None:
            setting = self._default()
            self.session.add(setting)
            await self.session.flush()
        return setting

    async def save(self, setting: ValveSetting) -> None:
        await self.session.commit()
        await self.session.refresh(setting)
