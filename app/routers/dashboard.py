from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.calendar_account import CalendarAccount
from app.models.event import Event
from app.models.user import User
from app.services.google_calendar import sync_events as google_sync
from app.services.apple_calendar import sync_events as apple_sync
from app.services.outlook_calendar import sync_events as outlook_sync
from app.templates_config import templates
from sqlalchemy.orm import Session

router = APIRouter(tags=["dashboard"])

PROVIDER_LABELS = {"google": "Google Calendar", "apple": "Apple Calendar", "outlook": "Outlook"}
PROVIDER_ICONS  = {"google": "G", "apple": "🍎", "outlook": "O"}


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    connected: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = (
        db.query(CalendarAccount)
        .filter_by(user_id=current_user.id)
        .all()
    )

    accounts_data = []
    for acc in accounts:
        count = db.query(Event).filter_by(calendar_id=acc.id).count()
        last_sync = acc.last_synced
        if last_sync and last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)

        accounts_data.append({
            "id": acc.id,
            "provider": acc.provider,
            "label": PROVIDER_LABELS.get(acc.provider, acc.provider),
            "icon": PROVIDER_ICONS.get(acc.provider, "?"),
            "email": acc.account_email,
            "event_count": count,
            "last_synced": last_sync,
            "sync_age_min": _minutes_ago(last_sync),
        })

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": current_user,
        "accounts": accounts_data,
        "connected": connected,
    })


@router.post("/dashboard/sync/{account_id}")
def manual_sync(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(CalendarAccount).filter_by(
        id=account_id, user_id=current_user.id
    ).first()
    if not account:
        return JSONResponse({"error": "Compte introuvable"}, status_code=404)
    try:
        if account.provider == "google":
            count = google_sync(account, db)
        elif account.provider == "apple":
            count = apple_sync(account, db)
        elif account.provider == "outlook":
            count = outlook_sync(account, db)
        else:
            return JSONResponse({"error": "Provider non supporté"}, status_code=400)
        return JSONResponse({"synced": count, "ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e), "ok": False}, status_code=500)


@router.post("/dashboard/disconnect/{account_id}")
def disconnect_calendar(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(CalendarAccount).filter_by(
        id=account_id, user_id=current_user.id
    ).first()
    if not account:
        return JSONResponse({"error": "Compte introuvable"}, status_code=404)
    db.delete(account)
    db.commit()
    return JSONResponse({"ok": True})


def _minutes_ago(dt: datetime | None) -> int | None:
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return int((now - dt).total_seconds() / 60)
