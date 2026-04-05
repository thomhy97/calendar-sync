"""Intégration Apple Calendar via CalDAV (iCloud)."""
from datetime import datetime, timezone, timedelta

import caldav
from sqlalchemy.orm import Session

from app.models.calendar_account import CalendarAccount
from app.models.event import Event
from app.services.crypto import decrypt

CALDAV_URL = "https://caldav.icloud.com"


def test_connection(apple_id: str, app_password: str) -> bool:
    """Vérifie que les credentials iCloud sont valides."""
    try:
        client = caldav.DAVClient(url=CALDAV_URL, username=apple_id, password=app_password)
        principal = client.principal()
        principal.calendars()
        return True
    except Exception:
        return False


def sync_events(account: CalendarAccount, db: Session) -> int:
    """Synchronise les événements iCloud Calendar. Retourne le nombre d'événements."""
    apple_id = decrypt(account.account_email) if "@" not in account.account_email else account.account_email
    app_password = decrypt(account.access_token)

    client = caldav.DAVClient(url=CALDAV_URL, username=apple_id, password=app_password)
    principal = client.principal()
    calendars = principal.calendars()

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=60)

    db.query(Event).filter(Event.calendar_id == account.id).delete()

    count = 0
    for calendar in calendars:
        try:
            results = calendar.date_search(start=now, end=end, expand=True)
        except Exception:
            continue

        for event in results:
            try:
                vevent = event.vobject_instance.vevent
                start = _to_utc(vevent.dtstart.value)
                end_dt = _to_utc(vevent.dtend.value) if hasattr(vevent, "dtend") else start + timedelta(hours=1)
                is_all_day = not hasattr(vevent.dtstart.value, "hour")

                db.add(Event(
                    calendar_id=account.id,
                    external_event_id=str(vevent.uid.value),
                    start_time=start,
                    end_time=end_dt,
                    is_all_day=is_all_day,
                ))
                count += 1
            except Exception:
                continue

    account.last_synced = now
    db.commit()
    return count


def _to_utc(value) -> datetime:
    """Convertit une date ou datetime en datetime UTC."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    # date simple (all-day)
    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
