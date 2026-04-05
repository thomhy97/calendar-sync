"""Algorithme de recherche de créneaux communs entre plusieurs utilisateurs."""
from datetime import datetime, timedelta, timezone, time
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models.event import Event
from app.models.calendar_account import CalendarAccount
from app.models.user import User


class Slot(NamedTuple):
    start: datetime
    end: datetime


def find_common_slots(
    db: Session,
    user_ids: list[int],
    date_from: datetime,
    date_to: datetime,
    duration_minutes: int,
    work_start: time = time(9, 0),
    work_end: time = time(18, 0),
    include_weekends: bool = False,
) -> list[Slot]:
    """
    Retourne les créneaux libres pour tous les utilisateurs donnés.

    - date_from / date_to   : plage de dates à analyser
    - duration_minutes      : durée minimale du créneau souhaité
    - work_start / work_end : horaires de travail à respecter
    - include_weekends      : inclure samedi et dimanche
    """
    busy_periods = _collect_busy_periods(db, user_ids, date_from, date_to)
    slots = []
    current_day = date_from.replace(hour=0, minute=0, second=0, microsecond=0)

    while current_day <= date_to:
        # Filtrer les week-ends si nécessaire
        if not include_weekends and current_day.weekday() >= 5:
            current_day += timedelta(days=1)
            continue

        day_start = current_day.replace(
            hour=work_start.hour, minute=work_start.minute, second=0, microsecond=0
        )
        day_end = current_day.replace(
            hour=work_end.hour, minute=work_end.minute, second=0, microsecond=0
        )

        # Récupère les occupations de ce jour, triées
        day_busy = sorted(
            [p for p in busy_periods if p[0] < day_end and p[1] > day_start],
            key=lambda x: x[0],
        )

        # Fusionne les périodes qui se chevauchent
        merged = _merge_periods(day_busy)

        # Cherche les fenêtres libres entre les occupations
        cursor = day_start
        for busy_start, busy_end in merged:
            if cursor < busy_start:
                free_end = min(busy_start, day_end)
                _add_if_long_enough(slots, cursor, free_end, duration_minutes)
            cursor = max(cursor, busy_end)

        # Fenêtre après la dernière occupation
        if cursor < day_end:
            _add_if_long_enough(slots, cursor, day_end, duration_minutes)

        current_day += timedelta(days=1)

    return slots


def _collect_busy_periods(
    db: Session,
    user_ids: list[int],
    date_from: datetime,
    date_to: datetime,
) -> list[tuple[datetime, datetime]]:
    """Récupère toutes les périodes occupées pour les utilisateurs donnés."""
    calendar_ids = (
        db.query(CalendarAccount.id)
        .filter(CalendarAccount.user_id.in_(user_ids))
        .all()
    )
    calendar_ids = [row[0] for row in calendar_ids]

    if not calendar_ids:
        return []

    events = (
        db.query(Event)
        .filter(
            Event.calendar_id.in_(calendar_ids),
            Event.end_time > date_from,
            Event.start_time < date_to,
        )
        .all()
    )

    periods = []
    for event in events:
        start = _ensure_utc(event.start_time)
        end = _ensure_utc(event.end_time)
        if event.is_all_day:
            # Journée entière = occupe toute la journée
            start = start.replace(hour=0, minute=0, second=0)
            end = end.replace(hour=23, minute=59, second=59)
        periods.append((start, end))

    return periods


def _merge_periods(periods: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Fusionne les périodes qui se chevauchent ou se touchent."""
    if not periods:
        return []
    merged = [periods[0]]
    for start, end in periods[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def build_timeline(
    db: Session,
    user_ids: list[int],
    date_from: datetime,
    date_to: datetime,
    slots: list[Slot],
    work_start: time,
    work_end: time,
) -> list[dict]:
    """
    Construit les données de timeline pour le rendu visuel.
    Retourne une liste de jours avec leurs blocs occupés et créneaux libres (en %).
    """
    busy_periods = _collect_busy_periods(db, user_ids, date_from, date_to)
    work_minutes = (
        work_end.hour * 60 + work_end.minute
        - work_start.hour * 60 - work_start.minute
    )

    # Index des slots par jour
    slots_by_day: dict[str, list[Slot]] = {}
    for slot in slots:
        key = slot.start.strftime("%Y-%m-%d")
        slots_by_day.setdefault(key, []).append(slot)

    timeline = []
    current_day = date_from.replace(hour=0, minute=0, second=0, microsecond=0)

    while current_day <= date_to:
        key = current_day.strftime("%Y-%m-%d")
        day_slots = slots_by_day.get(key, [])
        if not day_slots:
            current_day += timedelta(days=1)
            continue

        day_start_dt = current_day.replace(
            hour=work_start.hour, minute=work_start.minute, second=0, microsecond=0
        )
        day_end_dt = current_day.replace(
            hour=work_end.hour, minute=work_end.minute, second=0, microsecond=0
        )

        # Blocs occupés du jour
        day_busy = sorted(
            [p for p in busy_periods if p[0] < day_end_dt and p[1] > day_start_dt],
            key=lambda x: x[0],
        )
        merged_busy = _merge_periods(day_busy)

        def to_pct(dt: datetime) -> float:
            clamped = max(day_start_dt, min(day_end_dt, dt))
            minutes = (clamped - day_start_dt).total_seconds() / 60
            return round(minutes / work_minutes * 100, 2)

        busy_blocks = []
        for b_start, b_end in merged_busy:
            sp = to_pct(b_start)
            ep = to_pct(b_end)
            if ep > sp:
                busy_blocks.append({
                    "start_pct": sp,
                    "width_pct": ep - sp,
                    "label": f"{b_start.strftime('%H:%M')}–{b_end.strftime('%H:%M')}",
                })

        slot_blocks = []
        for slot in day_slots:
            sp = to_pct(slot.start)
            ep = to_pct(slot.end)
            slot_blocks.append({
                "start_pct": sp,
                "width_pct": ep - sp,
                "label": f"{slot.start.strftime('%H:%M')}–{slot.end.strftime('%H:%M')}",
                "iso_start": slot.start.isoformat(),
                "iso_end": slot.end.isoformat(),
            })

        JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        MOIS = ["jan", "fév", "mar", "avr", "mai", "juin",
                "juil", "août", "sep", "oct", "nov", "déc"]

        timeline.append({
            "date_key": key,
            "label": f"{JOURS[current_day.weekday()]} {current_day.day} {MOIS[current_day.month - 1]}",
            "busy": busy_blocks,
            "slots": slot_blocks,
            "slot_count": len(day_slots),
        })

        current_day += timedelta(days=1)

    return timeline


def _add_if_long_enough(
    slots: list[Slot],
    start: datetime,
    end: datetime,
    duration_minutes: int,
):
    """Découpe la fenêtre libre en créneaux consécutifs de duration_minutes."""
    delta = timedelta(minutes=duration_minutes)
    cursor = start
    while cursor + delta <= end:
        slots.append(Slot(start=cursor, end=cursor + delta))
        cursor += delta


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
