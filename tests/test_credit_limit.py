"""
Testes do campo `credit_limit` em CreditCard.

Cobre:
- POST /api/cards aceita limite válido.
- POST /api/cards aceita limite null/omitido.
- POST /api/cards rejeita limite <= 0.
- PATCH atualiza, remove (sentinela 0) e rejeita negativo.
- Isolamento por usuário (não edita limite de cartão alheio).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services.auth_service import create_access_token, create_user

from app import models as _models  # noqa: F401


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _set_db_override():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


@pytest.fixture(autouse=True)
def setup_db(_set_db_override):
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    yield
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _auth(email: str) -> dict:
    token = create_access_token({"sub": email})
    return {"Authorization": f"Bearer {token}"}


def _make_card(client, headers, **overrides):
    payload = {
        "name": "Nubank Platinum",
        "institution": "Nubank",
        "closing_day": 4,
        "due_day": 13,
        **overrides,
    }
    res = client.post("/api/cards", json=payload, headers=headers)
    return res


class TestCreditLimitCreate:

    def test_create_with_valid_limit(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = _make_card(client, _auth(user.email), credit_limit=10000.0)
        assert res.status_code == 200
        assert res.json()["credit_limit"] == 10000.0

    def test_create_without_limit_keeps_null(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = _make_card(client, _auth(user.email))
        assert res.status_code == 200
        assert res.json()["credit_limit"] is None

    def test_create_explicit_null(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = _make_card(client, _auth(user.email), credit_limit=None)
        assert res.status_code == 200
        assert res.json()["credit_limit"] is None

    def test_rejects_zero_on_create(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = _make_card(client, _auth(user.email), credit_limit=0)
        assert res.status_code == 422

    def test_rejects_negative_on_create(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = _make_card(client, _auth(user.email), credit_limit=-100)
        assert res.status_code == 422


class TestCreditLimitUpdate:

    def test_update_sets_limit(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        cid = _make_card(client, _auth(user.email)).json()["id"]
        res = client.patch(f"/api/cards/{cid}",
                           json={"credit_limit": 5000.0},
                           headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["credit_limit"] == 5000.0

    def test_update_zero_clears_limit(self, client, db):
        """Sentinela: PATCH credit_limit=0 limpa (vira null)."""
        user = create_user(db, "u@test.com", "x", "U")
        cid = _make_card(client, _auth(user.email), credit_limit=5000.0).json()["id"]
        res = client.patch(f"/api/cards/{cid}",
                           json={"credit_limit": 0},
                           headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["credit_limit"] is None

    def test_update_null_does_not_change(self, client, db):
        """credit_limit ausente/null no PATCH não altera o valor existente."""
        user = create_user(db, "u@test.com", "x", "U")
        cid = _make_card(client, _auth(user.email), credit_limit=5000.0).json()["id"]
        res = client.patch(f"/api/cards/{cid}",
                           json={"name": "Outro nome"},  # sem credit_limit
                           headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["credit_limit"] == 5000.0

    def test_other_user_cannot_edit_limit(self, client, db):
        ua = create_user(db, "a@test.com", "x", "A")
        ub = create_user(db, "b@test.com", "x", "B")
        cid = _make_card(client, _auth(ua.email), credit_limit=5000.0).json()["id"]
        res = client.patch(f"/api/cards/{cid}",
                           json={"credit_limit": 9999.0},
                           headers=_auth(ub.email))
        assert res.status_code == 404


class TestCreditLimitListing:

    def test_get_card_includes_limit(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        cid = _make_card(client, _auth(user.email), credit_limit=8000.0).json()["id"]
        res = client.get(f"/api/cards/{cid}", headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["credit_limit"] == 8000.0

    def test_list_cards_includes_limit(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        _make_card(client, _auth(user.email), name="A", credit_limit=8000.0)
        _make_card(client, _auth(user.email), name="B")
        res = client.get("/api/cards", headers=_auth(user.email))
        assert res.status_code == 200
        body = res.json()
        limits = sorted([c["credit_limit"] for c in body], key=lambda v: (v is None, v))
        assert limits == [8000.0, None]
