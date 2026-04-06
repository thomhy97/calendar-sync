import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models.calendar_account import CalendarAccount
from app.models.user import User
from app.services import google_calendar, apple_calendar, outlook_calendar
from app.services.crypto import encrypt
from app.templates_config import templates

router = APIRouter(prefix="/calendars", tags=["calendars"])


# ── State OAuth : user_id + token + code_verifier, signé HMAC ────────────────
# Format: "{user_id}:{token}:{code_verifier}:{hmac_sig}"
# Tout est dans le state → aucun cookie ni session requis pendant le redirect.

def _make_state(user_id: int, code_verifier: str) -> str:
    token = secrets.token_urlsafe(16)
    payload = f"{user_id}:{token}:{code_verifier}"
    sig = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_state(state: str) -> tuple[int, str]:
    """Vérifie la signature HMAC. Retourne (user_id, code_verifier)."""
    # On sépare sur le dernier ":" pour isoler la signature (qui est hex, sans ":")
    last_colon = state.rfind(":")
    if last_colon == -1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="État OAuth invalide")
    payload, sig = state[:last_colon], state[last_colon + 1:]
    expected = hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="État OAuth invalide")
    parts = payload.split(":", 2)
    if len(parts) != 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="État OAuth invalide")
    user_id_str, _, code_verifier = parts
    return int(user_id_str), code_verifier


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/connect", response_class=HTMLResponse)
def connect_page(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "connect_calendar.html", {"user": current_user})


# ── Google ────────────────────────────────────────────────────────────────────

@router.get("/google/start")
def google_start(current_user: User = Depends(get_current_user)):
    code_verifier, code_challenge = google_calendar.generate_pkce()
    state = _make_state(current_user.id, code_verifier)
    auth_url = google_calendar.get_auth_url(state, code_challenge)
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
def google_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(url="/calendars/connect?error=google_denied")

    user_id, code_verifier = _verify_state(state)
    token_data = google_calendar.exchange_code(code, code_verifier)

    account = (
        db.query(CalendarAccount)
        .filter_by(user_id=user_id, provider="google", account_email=token_data["account_email"])
        .first()
    )
    if not account:
        account = CalendarAccount(
            user_id=user_id,
            provider="google",
            account_email=token_data["account_email"],
        )
        db.add(account)

    account.access_token = encrypt(token_data["access_token"])
    if token_data.get("refresh_token"):
        account.refresh_token = encrypt(token_data["refresh_token"])
    account.token_expiry = token_data["token_expiry"]
    db.commit()
    db.refresh(account)

    google_calendar.sync_events(account, db)

    return RedirectResponse(url="/dashboard?connected=google")


@router.post("/google/sync/{account_id}")
def google_sync(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.query(CalendarAccount).filter_by(
        id=account_id, user_id=current_user.id, provider="google"
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    count = google_calendar.sync_events(account, db)
    return {"synced": count}


# ── Apple Calendar (CalDAV) ───────────────────────────────────────────────────

@router.get("/apple/connect", response_class=HTMLResponse)
def apple_connect_page(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "connect_apple.html", {"user": current_user, "error": ""})


@router.post("/apple/connect")
def apple_connect(
    request: Request,
    apple_id: str = Form(...),
    app_password: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not apple_calendar.test_connection(apple_id, app_password):
        return templates.TemplateResponse(
            request,
            "connect_apple.html",
            {"user": current_user, "error": "Identifiants iCloud invalides. Vérifiez votre Apple ID et mot de passe d'app."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    account = (
        db.query(CalendarAccount)
        .filter_by(user_id=current_user.id, provider="apple", account_email=apple_id)
        .first()
    )
    if not account:
        account = CalendarAccount(
            user_id=current_user.id,
            provider="apple",
            account_email=apple_id,
        )
        db.add(account)

    # On stocke le mot de passe d'app chiffré dans access_token
    account.access_token = encrypt(app_password)
    account.refresh_token = None
    db.commit()
    db.refresh(account)

    apple_calendar.sync_events(account, db)

    return RedirectResponse(url="/dashboard?connected=apple", status_code=302)


# ── Outlook (Microsoft Graph) ─────────────────────────────────────────────────

@router.get("/outlook/start")
def outlook_start(current_user: User = Depends(get_current_user)):
    state = _make_state(current_user.id, "outlook")
    auth_url = outlook_calendar.get_auth_url(state)
    return RedirectResponse(url=auth_url)


@router.get("/outlook/callback")
def outlook_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(url="/calendars/connect?error=outlook_denied")

    user_id, _ = _verify_state(state)
    token_data = outlook_calendar.exchange_code(code)

    account = (
        db.query(CalendarAccount)
        .filter_by(user_id=user_id, provider="outlook", account_email=token_data["account_email"])
        .first()
    )
    if not account:
        account = CalendarAccount(
            user_id=user_id,
            provider="outlook",
            account_email=token_data["account_email"],
        )
        db.add(account)

    account.access_token = encrypt(token_data["access_token"])
    if token_data.get("refresh_token"):
        account.refresh_token = encrypt(token_data["refresh_token"])
    account.token_expiry = token_data["token_expiry"]
    db.commit()
    db.refresh(account)

    outlook_calendar.sync_events(account, db)
    return RedirectResponse(url="/dashboard?connected=outlook")
