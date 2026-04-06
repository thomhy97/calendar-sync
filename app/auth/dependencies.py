from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.jwt_handler import create_access_token, decode_access_token
from app.database import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User


def get_current_user(
    request: Request,
    response: Response,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(access_token) if access_token else None

    # Access token expiré ou absent — tenter le refresh
    if user_id is None and refresh_token:
        user_id = _try_refresh(refresh_token, response, db)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable",
        )
    return user


def _try_refresh(refresh_token: str, response: Response, db: Session) -> int | None:
    """Valide le refresh token, émet un nouvel access token, retourne l'user_id."""
    now = datetime.now(timezone.utc)
    record = db.query(RefreshToken).filter(RefreshToken.token == refresh_token).first()

    if not record:
        return None

    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires < now:
        db.delete(record)
        db.commit()
        return None

    # Renouvelle l'access token silencieusement
    new_access = create_access_token(record.user_id)
    response.set_cookie(
        key="access_token",
        value=new_access,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24,  # 24h
    )
    return record.user_id
