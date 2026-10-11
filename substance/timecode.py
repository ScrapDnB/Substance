"""Integer milliseconds internally; explicit centisecond rounding for ASS."""
from decimal import Decimal, ROUND_HALF_UP
import re


def parse_time(value: str) -> int:
    value = value.strip().replace(",", ".")
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?", value)
    if not match:
        raise ValueError("Таймкод: ЧЧ:ММ:СС.мс или ММ:СС.мс")
    hours, minutes, seconds, fraction = match.groups()
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise ValueError("Минуты и секунды должны быть меньше 60")
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int((fraction or "").ljust(3, "0"))


def format_time(ms: int, *, ass: bool = False, srt: bool = False) -> str:
    ms = max(0, int(ms))
    if ass:
        ms = ((ms + 5) // 10) * 10
    seconds, fraction = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if ass:
        return f"{hours}:{minutes:02}:{seconds:02}.{fraction // 10:02}"
    return f"{hours:02}:{minutes:02}:{seconds:02}{',' if srt else '.'}{fraction:03}"


def frame_time(ms: int, fps: float) -> int:
    if not 1 <= fps <= 120:
        raise ValueError("FPS должен быть в диапазоне 1–120")
    frame = (Decimal(ms) * Decimal(str(fps)) / 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int((frame * 1000 / Decimal(str(fps))).quantize(Decimal(1), rounding=ROUND_HALF_UP))
