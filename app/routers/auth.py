import bcrypt

from fastapi import APIRouter, Cookie, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.jwt_handler import create_access_token, create_refresh_token
from app.database import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.templates_config import templates

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 jours en secondes


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _set_auth_cookies(resp: RedirectResponse, user_id: int, db: Session):
    """Pose les cookies access_token (24h) et refresh_token (30j)."""
    access = create_access_token(user_id)
    refresh, expires_at = create_refresh_token()

    db.add(RefreshToken(user_id=user_id, token=refresh, expires_at=expires_at))
    db.commit()

    resp.set_cookie(key="access_token", value=access, httponly=True, samesite="lax", max_age=60 * 60 * 24)
    resp.set_cookie(key="refresh_token", value=refresh, httponly=True, samesite="lax", max_age=REFRESH_COOKIE_MAX_AGE)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Email ou mot de passe incorrect"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    _set_auth_cookies(resp, user.id, db)
    return resp


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": ""})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != password_confirm:
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Les mots de passe ne correspondent pas"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Le mot de passe doit faire au moins 8 caractères"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Cet email est déjà utilisé"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)

    resp = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    _set_auth_cookies(resp, user.id, db)
    return resp


@router.get("/logout")
def logout(
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    # Révoque le refresh token en base
    if refresh_token:
        record = db.query(RefreshToken).filter(RefreshToken.token == refresh_token).first()
        if record:
            db.delete(record)
            db.commit()

    resp = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp
