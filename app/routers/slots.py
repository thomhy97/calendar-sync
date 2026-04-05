import json
from datetime import datetime, time, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.services import slot_finder, ics_export
from app.services.google_calendar import sync_events as google_sync
from app.services.apple_calendar import sync_events as apple_sync
from app.models.calendar_account import CalendarAccount
from app.templates_config import templates

router = APIRouter(prefix="/slots", tags=["slots"])

DURATIONS = [
    (30, "30 minutes"),
    (60, "1 heure"),
    (90, "1h30"),
    (120, "2 heures"),
    (180, "3 heures"),
]


@router.get("/find", response_class=HTMLResponse)
def find_page(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        request, "find_slots.html",
        {"user": current_user, "durations": DURATIONS, "slots": None, "error": ""},
    )


@router.post("/find", response_class=HTMLResponse)
def find_slots(
    request: Request,
    emails: str = Form(...),          # emails séparés par virgule
    date_from: str = Form(...),
    date_to: str = Form(...),
    duration: int = Form(...),
    work_start: str = Form("09:00"),
    work_end: str = Form("18:00"),
    include_weekends: bool = Form(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Résolution des utilisateurs par email
    from app.models.user import User as UserModel
    user_ids = [current_user.id]
    unknown_emails = []

    for email in [e.strip() for e in emails.split(",") if e.strip()]:
        user = db.query(UserModel).filter(UserModel.email == email).first()
        if user:
            if user.id not in user_ids:
                user_ids.append(user.id)
        else:
            unknown_emails.append(email)

    if unknown_emails:
        return templates.TemplateResponse(
            request, "find_slots.html",
            {
                "user": current_user,
                "durations": DURATIONS,
                "slots": None,
                "error": f"Utilisateurs introuvables : {', '.join(unknown_emails)}. Ils doivent avoir un compte sur Calendar Sync.",
            },
        )

    # Sync rapide si dernière sync > 15 min
    _sync_if_stale(user_ids, db)

    try:
        dt_from = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=timezone.utc)
        t_start = time(*map(int, work_start.split(":")))
        t_end = time(*map(int, work_end.split(":")))
    except ValueError:
        return templates.TemplateResponse(
            request, "find_slots.html",
            {"user": current_user, "durations": DURATIONS, "slots": None, "error": "Dates invalides."},
        )

    slots = slot_finder.find_common_slots(
        db=db,
        user_ids=user_ids,
        date_from=dt_from,
        date_to=dt_to,
        duration_minutes=duration,
        work_start=t_start,
        work_end=t_end,
        include_weekends=include_weekends,
    )

    duration_label = next((label for val, label in DURATIONS if val == duration), f"{duration} min")

    timeline = slot_finder.build_timeline(
        db=db,
        user_ids=user_ids,
        date_from=dt_from,
        date_to=dt_to,
        slots=slots,
        work_start=t_start,
        work_end=t_end,
    )

    # Marqueurs horaires pour l'axe (toutes les heures)
    from datetime import timedelta
    axis_labels = []
    work_start_min = t_start.hour * 60 + t_start.minute
    work_end_min = t_end.hour * 60 + t_end.minute
    work_total = work_end_min - work_start_min
    h = t_start.hour + (1 if t_start.minute > 0 else 0)
    while h * 60 <= work_end_min:
        pct = (h * 60 - work_start_min) / work_total * 100
        axis_labels.append({"label": f"{h:02d}:00", "pct": round(pct, 2)})
        h += 1

    return templates.TemplateResponse(
        request, "find_slots.html",
        {
            "user": current_user,
            "durations": DURATIONS,
            "slots": slots,
            "slots_count": len(slots),
            "duration_label": duration_label,
            "searched": True,
            "error": "",
            "timeline_json": json.dumps(timeline),
            "axis_labels": axis_labels,
            "form": {
                "emails": emails,
                "date_from": date_from,
                "date_to": date_to,
                "duration": duration,
                "work_start": work_start,
                "work_end": work_end,
                "include_weekends": include_weekends,
            },
        },
    )


@router.get("/export.ics")
def export_ics(
    start: str = Query(...),   # ISO format : 2026-04-07T10:00:00+00:00
    end: str = Query(...),
    title: str = Query("Réunion"),
    current_user: User = Depends(get_current_user),
):
    try:
        dt_start = datetime.fromisoformat(start)
        dt_end = datetime.fromisoformat(end)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Dates invalides")

    content = ics_export.generate_ics(
        start=dt_start,
        end=dt_end,
        title=title,
        organizer_email=current_user.email,
    )

    safe_title = quote(title, safe="")
    filename = f"creneau-{dt_start.strftime('%Y%m%d-%H%M')}.ics"
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _sync_if_stale(user_ids: list[int], db: Session):
    """Resynchronise les calendriers qui n'ont pas été mis à jour depuis 15 min."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(minutes=15)

    accounts = db.query(CalendarAccount).filter(
        CalendarAccount.user_id.in_(user_ids),
    ).all()

    for account in accounts:
        last = account.last_synced
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last and last > threshold:
            continue
        try:
            if account.provider == "google":
                google_sync(account, db)
            elif account.provider == "apple":
                apple_sync(account, db)
        except Exception:
            pass  # On continue même si la sync échoue
