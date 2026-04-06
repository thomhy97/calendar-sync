"""Page de profil utilisateur — changement de mot de passe + suppression compte."""
import bcrypt

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.templates_config import templates

router = APIRouter(prefix="/profile", tags=["profile"])


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


@router.get("", response_class=HTMLResponse)
def profile_page(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "profile.html", {"user": current_user})


@router.post("/change-password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_confirm: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    error = None
    if not verify_password(current_password, current_user.password_hash):
        error = "Mot de passe actuel incorrect"
    elif new_password != new_password_confirm:
        error = "Les nouveaux mots de passe ne correspondent pas"
    elif len(new_password) < 8:
        error = "Le mot de passe doit faire au moins 8 caractères"

    if error:
        return templates.TemplateResponse(
            request, "profile.html",
            {"user": current_user, "password_error": error},
            status_code=400,
        )

    current_user.password_hash = hash_password(new_password)
    db.commit()
    return templates.TemplateResponse(
        request, "profile.html",
        {"user": current_user, "password_success": "Mot de passe mis à jour."},
    )


@router.post("/delete")
def delete_account(
    current_password: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(current_password, current_user.password_hash):
        return JSONResponse({"ok": False, "error": "Mot de passe incorrect"}, status_code=400)

    # Supprime les refresh tokens
    db.query(RefreshToken).filter(RefreshToken.user_id == current_user.id).delete()
    db.delete(current_user)
    db.commit()

    resp = RedirectResponse(url="/auth/login", status_code=302)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp
