"""Liens de partage public de disponibilités."""
import secrets
from datetime import datetime, time, timezone, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.availability_link import AvailabilityLink
from app.models.user import User
from app.services.slot_finder import find_common_slots, build_timeline
from app.templates_config import templates

router = APIRouter(prefix="/share", tags=["share"])


# ── Gestion des liens (utilisateur connecté) ──────────────────────────────────

@router.get("/manage", response_class=HTMLResponse)
def manage_links(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    links = db.query(AvailabilityLink).filter_by(user_id=current_user.id, is_active=True).all()
    return templates.TemplateResponse(request, "share_manage.html", {"user": current_user, "links": links})


@router.post("/create")
def create_link(
    label: str = Form("Mes disponibilités"),
    duration_minutes: int = Form(30),
    work_start: str = Form("09:00"),
    work_end: str = Form("18:00"),
    days_ahead: int = Form(14),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token = secrets.token_urlsafe(16)
    link = AvailabilityLink(
        user_id=current_user.id,
        token=token,
        label=label,
        duration_minutes=duration_minutes,
        work_start=work_start,
        work_end=work_end,
        days_ahead=days_ahead,
    )
    db.add(link)
    db.commit()
    return JSONResponse({"ok": True, "token": token})


@router.post("/delete/{token}")
def delete_link(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    link = db.query(AvailabilityLink).filter_by(token=token, user_id=current_user.id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    link.is_active = False
    db.commit()
    return JSONResponse({"ok": True})


# ── Page publique (sans authentification) ─────────────────────────────────────

@router.get("/{token}", response_class=HTMLResponse)
def public_availability(request: Request, token: str, db: Session = Depends(get_db)):
    link = db.query(AvailabilityLink).filter_by(token=token, is_active=True).first()
    if not link:
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré")

    now = datetime.now(timezone.utc)
    date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date_from + timedelta(days=link.days_ahead)

    t_start = time(*map(int, link.work_start.split(":")))
    t_end = time(*map(int, link.work_end.split(":")))

    slots = find_common_slots(
        db=db,
        user_ids=[link.user_id],
        date_from=date_from,
        date_to=date_to,
        duration_minutes=link.duration_minutes,
        work_start=t_start,
        work_end=t_end,
    )

    timeline = build_timeline(
        db=db,
        user_ids=[link.user_id],
        date_from=date_from,
        date_to=date_to,
        slots=slots,
        work_start=t_start,
        work_end=t_end,
    )

    # Axe horaire
    work_start_min = t_start.hour * 60 + t_start.minute
    work_end_min = t_end.hour * 60 + t_end.minute
    work_total = work_end_min - work_start_min
    axis_labels = []
    h = t_start.hour + (1 if t_start.minute > 0 else 0)
    while h * 60 <= work_end_min:
        pct = (h * 60 - work_start_min) / work_total * 100
        axis_labels.append({"label": f"{h:02d}:00", "pct": round(pct, 2)})
        h += 1

    import json
    return templates.TemplateResponse(request, "share_public.html", {
        "link": link,
        "owner_email": link.user.email,
        "slots": slots,
        "slots_count": len(slots),
        "timeline_json": json.dumps(timeline),
        "axis_labels": axis_labels,
    })
