import os

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import auth, dashboard, calendars, slots, share, profile

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Calendar Sync")

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(calendars.router)
app.include_router(slots.router)
app.include_router(share.router)
app.include_router(profile.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Redirige vers /auth/login sur 401 pour les requêtes navigateur."""
    if exc.status_code == 401:
        return RedirectResponse(url=f"/auth/login", status_code=302)
    raise exc


@app.get("/")
def root():
    return RedirectResponse(url="/auth/login")


@app.get("/health")
def health():
    return {"status": "ok"}
