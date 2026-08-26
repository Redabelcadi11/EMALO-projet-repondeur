from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 1


@dataclass(frozen=True)
class TourneeWindow:
    label: str
    start: datetime
    end: datetime

    def contains(self, value: datetime | None) -> bool:
        if value is None:
            return False
        return self.start <= value <= self.end


def last_operational_tournee(reference: datetime | None = None) -> TourneeWindow:
    now = reference or datetime.now()
    if now.time() <= time(14, 0):
        start_day = now.date() - timedelta(days=1)
    else:
        start_day = now.date()
    start = datetime.combine(start_day, time(NIGHT_START_HOUR, 0))
    end = datetime.combine(start_day + timedelta(days=1), time(NIGHT_END_HOUR, 0))
    return TourneeWindow(
        label=f"Tournée du {start_day.strftime('%d/%m/%Y')} soir",
        start=start,
        end=end,
    )


def is_night_audio(value: datetime | None) -> bool:
    if value is None:
        return False
    hour = value.hour
    return hour >= NIGHT_START_HOUR or hour <= NIGHT_END_HOUR


def tournee_key(value: datetime | None) -> str:
    if value is None:
        return ""
    day = value.date()
    if value.hour <= NIGHT_END_HOUR:
        day = day - timedelta(days=1)
    return day.isoformat()


def tournee_label_from_key(key: str) -> str:
    try:
        parsed = date.fromisoformat(key)
    except ValueError:
        return ""
    return f"Tournée du {parsed.strftime('%d/%m/%Y')} soir"
