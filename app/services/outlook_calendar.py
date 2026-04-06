"""Intégration Outlook Calendar via Microsoft Graph API."""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models.calendar_account import CalendarAccount
from app.models.event import Event
from app.services.crypto import decrypt, encrypt

AUTHORITY = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}"
SCOPES = ["Calendars.Read", "User.Read", "offline_access"]
GRAPH_URL = "https://graph.microsoft.com/v1.0"


def get_auth_url(state: str) -> str:
    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "response_mode": "query",
    }
    from urllib.parse import urlencode
    return f"{AUTHORITY}/oauth2/v2.0/authorize?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    resp = requests.post(
        f"{AUTHORITY}/oauth2/v2.0/token",
        data={
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.MICROSOFT_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()

    access_token = token["access_token"]
    refresh_token = token.get("refresh_token", "")
    expires_in = token.get("expires_in", 3600)
    expiry = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + expires_in,
        tz=timezone.utc,
    )

    email = _get_user_email(access_token)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": expiry,
        "account_email": email,
    }


def _get_user_email(access_token: str) -> str:
    resp = requests.get(
        f"{GRAPH_URL}/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("mail") or data.get("userPrincipalName", "")


def _refresh_token(account: CalendarAccount) -> str:
    resp = requests.post(
        f"{AUTHORITY}/oauth2/v2.0/token",
        data={
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "refresh_token": decrypt(account.refresh_token),
            "grant_type": "refresh_token",
            "scope": " ".join(SCOPES),
        },
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json()
    access_token = token["access_token"]
    account.access_token = encrypt(access_token)
    if token.get("refresh_token"):
        account.refresh_token = encrypt(token["refresh_token"])
    expires_in = token.get("expires_in", 3600)
    account.token_expiry = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + expires_in, tz=timezone.utc
    )
    return access_token


def _get_valid_token(account: CalendarAccount) -> str:
    expiry = account.token_expiry
    if expiry:
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc) and account.refresh_token:
            return _refresh_token(account)
    return decrypt(account.access_token)


def sync_events(account: CalendarAccount, db: Session) -> int:
    access_token = _get_valid_token(account)
    now = datetime.now(timezone.utc)

    db.query(Event).filter(Event.calendar_id == account.id).delete()

    resp = requests.get(
        f"{GRAPH_URL}/me/calendarView",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "startDateTime": now.isoformat(),
            "endDateTime": now.replace(year=now.year + 1).isoformat(),
            "$select": "start,end,isAllDay,id",
            "$top": 500,
        },
        timeout=15,
    )
    resp.raise_for_status()

    count = 0
    for item in resp.json().get("value", []):
        try:
            is_all_day = item.get("isAllDay", False)
            start = datetime.fromisoformat(item["start"]["dateTime"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(item["end"]["dateTime"].replace("Z", "+00:00"))
            db.add(Event(
                calendar_id=account.id,
                external_event_id=item["id"],
                start_time=start,
                end_time=end,
                is_all_day=is_all_day,
            ))
            count += 1
        except Exception:
            continue

    account.last_synced = now
    db.commit()
    return count
