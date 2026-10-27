"""可注入时钟：业务代码统一用 clock.now()，测试中可 set_now() 推进时间。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


class Clock:
    def __init__(self) -> None:
        self._fixed: datetime | None = None

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else datetime.now(TZ)

    def today(self) -> date:
        return self.now().date()

    def set_now(self, value: datetime | None) -> None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        self._fixed = value


clock = Clock()
