"""Tests de l'algorithme de créneaux communs."""
from datetime import datetime, time, timezone, timedelta

import pytest

from app.models.calendar_account import CalendarAccount
from app.models.event import Event
from app.services.slot_finder import find_common_slots, Slot


def _make_account(db, user_id=1) -> CalendarAccount:
    acc = CalendarAccount(
        user_id=user_id,
        provider="google",
        account_email="test@example.com",
        access_token="dummy",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _add_event(db, calendar_id, start: datetime, end: datetime, all_day=False):
    ev = Event(
        calendar_id=calendar_id,
        external_event_id=f"evt-{start.isoformat()}",
        start_time=start,
        end_time=end,
        is_all_day=all_day,
    )
    db.add(ev)
    db.commit()


def _utc(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


WORK_START = time(9, 0)
WORK_END = time(18, 0)


def test_full_day_free(db):
    """Aucun événement → toute la journée est disponible en créneaux de 30 min."""
    acc = _make_account(db)
    slots = find_common_slots(
        db=db,
        user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 6),
        date_to=_utc(2026, 4, 6, 23, 59),
        duration_minutes=30,
        work_start=WORK_START,
        work_end=WORK_END,
    )
    # 9h–18h = 540 min → 18 créneaux de 30 min
    assert len(slots) == 18
    assert slots[0] == Slot(start=_utc(2026, 4, 6, 9, 0), end=_utc(2026, 4, 6, 9, 30))
    assert slots[-1] == Slot(start=_utc(2026, 4, 6, 17, 30), end=_utc(2026, 4, 6, 18, 0))


def test_event_blocks_slots(db):
    """Un événement 10h–11h supprime les créneaux qui chevauchent."""
    acc = _make_account(db)
    _add_event(db, acc.id, _utc(2026, 4, 6, 10, 0), _utc(2026, 4, 6, 11, 0))

    slots = find_common_slots(
        db=db,
        user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 6),
        date_to=_utc(2026, 4, 6, 23, 59),
        duration_minutes=30,
        work_start=WORK_START,
        work_end=WORK_END,
    )
    # 9h–10h = 2 créneaux, 11h–18h = 14 créneaux = 16 total
    assert len(slots) == 16
    starts = [s.start.hour * 60 + s.start.minute for s in slots]
    assert 10 * 60 not in starts
    assert 10 * 60 + 30 not in starts


def test_overlapping_events_merged(db):
    """Deux événements qui se chevauchent sont traités comme un seul bloc."""
    acc = _make_account(db)
    _add_event(db, acc.id, _utc(2026, 4, 6, 10, 0), _utc(2026, 4, 6, 11, 30))
    _add_event(db, acc.id, _utc(2026, 4, 6, 11, 0), _utc(2026, 4, 6, 12, 0))

    slots = find_common_slots(
        db=db,
        user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 6),
        date_to=_utc(2026, 4, 6, 23, 59),
        duration_minutes=30,
        work_start=WORK_START,
        work_end=WORK_END,
    )
    # 9h–10h = 2, 12h–18h = 12 → 14 créneaux
    assert len(slots) == 14


def test_all_day_event_blocks_full_day(db):
    """Un événement journée entière bloque toute la journée."""
    acc = _make_account(db)
    _add_event(db, acc.id, _utc(2026, 4, 6), _utc(2026, 4, 6, 23, 59), all_day=True)

    slots = find_common_slots(
        db=db,
        user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 6),
        date_to=_utc(2026, 4, 6, 23, 59),
        duration_minutes=30,
        work_start=WORK_START,
        work_end=WORK_END,
    )
    assert len(slots) == 0


def test_two_users_intersection(db):
    """Les créneaux libres = intersection des disponibilités des deux utilisateurs."""
    acc1 = _make_account(db, user_id=1)
    acc2 = CalendarAccount(user_id=2, provider="google", account_email="b@x.com", access_token="d")
    db.add(acc2)
    db.commit()
    db.refresh(acc2)

    # User 1 : occupé 9h–12h
    _add_event(db, acc1.id, _utc(2026, 4, 6, 9, 0), _utc(2026, 4, 6, 12, 0))
    # User 2 : occupé 14h–18h
    _add_event(db, acc2.id, _utc(2026, 4, 6, 14, 0), _utc(2026, 4, 6, 18, 0))

    slots = find_common_slots(
        db=db,
        user_ids=[1, 2],
        date_from=_utc(2026, 4, 6),
        date_to=_utc(2026, 4, 6, 23, 59),
        duration_minutes=30,
        work_start=WORK_START,
        work_end=WORK_END,
    )
    # Libre uniquement 12h–14h = 4 créneaux de 30 min
    assert len(slots) == 4
    assert all(12 * 60 <= s.start.hour * 60 + s.start.minute < 14 * 60 for s in slots)


def test_weekend_excluded_by_default(db):
    """Les week-ends sont exclus par défaut."""
    acc = _make_account(db)
    # 2026-04-11 = samedi, 2026-04-12 = dimanche
    slots = find_common_slots(
        db=db,
        user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 11),
        date_to=_utc(2026, 4, 12, 23, 59),
        duration_minutes=30,
        work_start=WORK_START,
        work_end=WORK_END,
        include_weekends=False,
    )
    assert len(slots) == 0


def test_weekend_included_when_requested(db):
    """Les week-ends sont inclus si demandé."""
    acc = _make_account(db)
    slots = find_common_slots(
        db=db,
        user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 11),
        date_to=_utc(2026, 4, 11, 23, 59),
        duration_minutes=30,
        work_start=WORK_START,
        work_end=WORK_END,
        include_weekends=True,
    )
    assert len(slots) == 18


def test_duration_filter(db):
    """Un créneau trop court n'est pas retourné."""
    acc = _make_account(db)
    # Laisse seulement 45 min libres : 9h–9h45
    _add_event(db, acc.id, _utc(2026, 4, 6, 9, 45), _utc(2026, 4, 6, 18, 0))

    slots_30 = find_common_slots(
        db=db, user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 6), date_to=_utc(2026, 4, 6, 23, 59),
        duration_minutes=30, work_start=WORK_START, work_end=WORK_END,
    )
    slots_60 = find_common_slots(
        db=db, user_ids=[acc.user_id],
        date_from=_utc(2026, 4, 6), date_to=_utc(2026, 4, 6, 23, 59),
        duration_minutes=60, work_start=WORK_START, work_end=WORK_END,
    )
    assert len(slots_30) == 1   # 9h–9h30 seulement
    assert len(slots_60) == 0   # pas assez de temps
