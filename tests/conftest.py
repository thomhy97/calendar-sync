"""Configuration partagée des tests — base de données en mémoire, client HTTP."""
import os
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
os.environ["SECRET_KEY"] = "test-secret-key-32-chars-minimum!!"
os.environ["FERNET_KEY"] = "mNJjm8x5fvgctOLynhHuw16Be0GWkoGXC2MxoWMHrnM="

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

# StaticPool : toutes les connexions partagent la même DB en mémoire
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client(client):
    """Client HTTP déjà connecté avec un compte de test."""
    client.post("/auth/register", data={
        "email": "test@example.com",
        "password": "password123",
        "password_confirm": "password123",
    })
    return client
