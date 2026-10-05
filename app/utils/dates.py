from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def now_vn() -> datetime:
    return datetime.now(VN_TZ).replace(tzinfo=None)


def day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(d: datetime) -> datetime:
    return day_start(d).replace(day=1)


def add_months(d: datetime, n: int) -> datetime:
    total = d.year * 12 + d.month - 1 + n
    return d.replace(year=total // 12, month=total % 12 + 1, day=1)


def prev_window(now: datetime, cur_start: datetime, prev_start: datetime):
    return prev_start, min(prev_start + (now - cur_start), cur_start)


def period_windows(now: datetime, period: str):
    if period == "today":
        start = day_start(now)
        prev_start = start - timedelta(days=1)
    elif period == "month":
        start = month_start(now)
        prev_start = add_months(start, -1)
    else:
        days = 7 if period == "7d" else 30
        start = now - timedelta(days=days)
        prev_start = start - timedelta(days=days)
    prev_s, prev_e = prev_window(now, start, prev_start)
    return (start, now), (prev_s, prev_e)


def percent_change(cur, prev) -> float | None:
    if cur is None or not prev:
        return None
    return round((cur - prev) / prev * 100, 1)
