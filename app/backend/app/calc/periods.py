"""月份工具：库中月份统一存为当月 1 日（DATE）；接口用 'YYYY-MM'。"""
import calendar
from datetime import date


def parse_month(value: str) -> date:
    """'2027-03' → date(2027, 3, 1)；格式不符抛 ValueError。"""
    parts = value.strip().split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError(f"月份格式应为 YYYY-MM：{value}")
    year, month = int(parts[0]), int(parts[1])
    return date(year, month, 1)


def fmt_month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, n: int) -> date:
    """加 n 个月；日超出目标月天数时取目标月最后一天（2024-02-29 + 12 → 2025-02-28）。"""
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def months_between(start: date, end: date) -> int:
    """end 所在月相对 start 所在月相差的月数（同月为 0）。"""
    return (end.year - start.year) * 12 + (end.month - start.month)


def quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def year_months(year: int) -> list[date]:
    return [date(year, m, 1) for m in range(1, 13)]
