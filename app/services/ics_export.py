"""Génération de fichiers .ics (iCalendar) pour l'export de créneaux."""
import uuid
from datetime import datetime, timezone


def generate_ics(start: datetime, end: datetime, title: str, organizer_email: str) -> str:
    """Retourne le contenu d'un fichier .ics pour un créneau donné."""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid = str(uuid.uuid4())

    start_str = _fmt(start)
    end_str = _fmt(end)

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Calendar Sync//FR\r\n"
        "METHOD:REQUEST\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{now}\r\n"
        f"DTSTART:{start_str}\r\n"
        f"DTEND:{end_str}\r\n"
        f"SUMMARY:{_escape(title)}\r\n"
        f"ORGANIZER:mailto:{organizer_email}\r\n"
        "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def _fmt(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
