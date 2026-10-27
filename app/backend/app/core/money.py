"""Decimal 解析与格式化（DEC-005）。

- 全链路 Decimal，禁止 float：解析函数遇到 float 直接报错。
- 接口中比率以「百分数字符串」传输（"12.5" 表示 12.5%），后端存小数（0.125）。
- 舍入只发生在显示与导出：ROUND_HALF_UP 保留 2 位。
- 显示：人民币「¥ 1,234.56」，外币「$ 1,234.56 USD」，负数用「−」（U+2212），空值「—」。
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
HUNDRED = Decimal(100)
DASH = "—"
MINUS = "−"

CURRENCY_SYMBOLS = {"CNY": "¥", "USD": "$", "CAD": "C$", "EUR": "€", "GBP": "£"}


class MoneyError(ValueError):
    pass


def to_decimal(value) -> Decimal:
    """把 str / int / Decimal 解析为 Decimal；拒绝 float 与 bool。空串视为 0（清空单元格按 0 保存）。"""
    if isinstance(value, bool) or isinstance(value, float):
        raise MoneyError("金额不允许使用浮点数")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        s = value.strip().replace(",", "").replace(MINUS, "-")
        if s == "":
            return Decimal(0)
        try:
            d = Decimal(s)
        except InvalidOperation as e:
            raise MoneyError(f"不是合法数字：{value}") from e
    else:
        raise MoneyError(f"不支持的数值类型：{type(value).__name__}")
    if not d.is_finite():
        raise MoneyError(f"不是合法数字：{value}")
    return d


def dec_str(value: Decimal | None) -> str | None:
    """接口传输用：Decimal → 定点字符串（不舍入、不用科学计数法）。"""
    if value is None:
        return None
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def percent_to_ratio(value) -> Decimal:
    """百分数字符串 → 小数：'12.5' → Decimal('0.125')。"""
    return to_decimal(value) / HUNDRED


def ratio_to_percent(value: Decimal | None) -> str | None:
    """小数 → 百分数字符串（不舍入）：Decimal('0.123456') → '12.3456'。"""
    if value is None:
        return None
    return dec_str(value * HUNDRED)


def round2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def round_to(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _grouped(value: Decimal, places: int = 2) -> str:
    q = round_to(value, places)
    sign = MINUS if q < 0 else ""
    return f"{sign}{abs(q):,.{places}f}"


def fmt_amount(value: Decimal | None) -> str:
    """千分位 2 位小数：Decimal('-60768') → '−60,768.00'；空值 '—'。"""
    if value is None:
        return DASH
    return _grouped(value)


def fmt_cny(value: Decimal | None) -> str:
    """人民币：'¥ 1,234.56'。"""
    if value is None:
        return DASH
    return f"¥ {_grouped(value)}"


def fmt_foreign(value: Decimal | None, currency: str) -> str:
    """本币：'$ 1,234.56 USD'；人民币同 fmt_cny。"""
    if value is None:
        return DASH
    if currency == "CNY":
        return fmt_cny(value)
    symbol = CURRENCY_SYMBOLS.get(currency, "")
    prefix = f"{symbol} " if symbol else ""
    return f"{prefix}{_grouped(value)} {currency}"


def fmt_percent(ratio: Decimal | None, places: int = 2, signed: bool = False) -> str:
    """小数比率显示为百分比：Decimal('0.16') → '16.00%'；signed 时正数带「+」。"""
    if ratio is None:
        return DASH
    q = round_to(ratio * HUNDRED, places)
    sign = MINUS if q < 0 else ("+" if signed and q > 0 else "")
    return f"{sign}{abs(q):,.{places}f}%"


def fmt_pp(value: Decimal | None, places: int = 2) -> str:
    """百分点数值显示：Decimal('1.6667') → '1.67'。"""
    if value is None:
        return DASH
    q = round_to(value, places)
    sign = MINUS if q < 0 else ""
    return f"{sign}{abs(q):,.{places}f}"
