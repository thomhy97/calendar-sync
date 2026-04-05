"""Tests de l'authentification : register, login, logout, protection des routes."""


def test_register_success(client):
    resp = client.post("/auth/register", data={
        "email": "alice@example.com",
        "password": "password123",
        "password_confirm": "password123",
    })
    assert resp.status_code == 200
    # Le cookie JWT est posé sur le 302 de redirect ; TestClient le stocke dans client.cookies
    assert "access_token" in client.cookies


def test_register_duplicate_email(client):
    data = {"email": "alice@example.com", "password": "password123", "password_confirm": "password123"}
    client.post("/auth/register", data=data)
    resp = client.post("/auth/register", data=data)
    assert resp.status_code == 400


def test_register_password_mismatch(client):
    resp = client.post("/auth/register", data={
        "email": "alice@example.com",
        "password": "password123",
        "password_confirm": "different",
    })
    assert resp.status_code == 400


def test_register_password_too_short(client):
    resp = client.post("/auth/register", data={
        "email": "alice@example.com",
        "password": "short",
        "password_confirm": "short",
    })
    assert resp.status_code == 400


def test_login_success(auth_client):
    resp = auth_client.post("/auth/login", data={
        "email": "test@example.com",
        "password": "password123",
    })
    assert resp.status_code == 200
    assert "access_token" in auth_client.cookies


def test_login_wrong_password(auth_client):
    resp = auth_client.post("/auth/login", data={
        "email": "test@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_login_unknown_email(client):
    resp = client.post("/auth/login", data={
        "email": "nobody@example.com",
        "password": "password123",
    })
    assert resp.status_code == 401


def test_dashboard_requires_auth(client):
    resp = client.get("/dashboard", follow_redirects=False)
    # Doit rediriger vers /auth/login
    assert resp.status_code in (302, 307)


def test_dashboard_accessible_when_logged_in(auth_client):
    resp = auth_client.get("/dashboard")
    assert resp.status_code == 200


def test_logout_clears_cookie(auth_client):
    resp = auth_client.get("/auth/logout", follow_redirects=False)
    assert resp.status_code in (302, 307)
    # Le cookie doit être supprimé ou vide
    cookie = resp.cookies.get("access_token", "")
    assert cookie == ""
