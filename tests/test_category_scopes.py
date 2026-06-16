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


class TestCategoryScopes:
    def test_both_appears_in_both_contexts(self, client, db):
        user = create_user(db, "cs1@test.com", "x", "U")
        h = _auth(user.email)

        client.post("/api/categories", json={"name": "Mercado", "applies_to_bank": True, "applies_to_credit_card": True}, headers=h)
        client.post("/api/categories", json={"name": "SoConta", "applies_to_bank": True, "applies_to_credit_card": False}, headers=h)
        client.post("/api/categories", json={"name": "SoCartao", "applies_to_bank": False, "applies_to_credit_card": True}, headers=h)

        bank_names = {c["name"] for c in client.get("/api/categories?scope=bank", headers=h).json()}
        card_names = {c["name"] for c in client.get("/api/categories?scope=credit_card", headers=h).json()}

        assert bank_names == {"Mercado", "SoConta"}
        assert card_names == {"Mercado", "SoCartao"}

    def test_create_requires_destination(self, client, db):
        user = create_user(db, "cs2@test.com", "x", "U")
        r = client.post("/api/categories", json={"name": "X"}, headers=_auth(user.email))
        assert r.status_code == 422

    def test_scope_backcompat(self, client, db):
        user = create_user(db, "cs3@test.com", "x", "U")
        h = _auth(user.email)
        r = client.post("/api/categories", json={"name": "Legacy", "scope": "bank"}, headers=h)
        assert r.status_code == 200
        assert r.json()["applies_to_bank"] is True
        assert r.json()["applies_to_credit_card"] is False

    def test_bank_tx_accepts_both_category(self, client, db):
        user = create_user(db, "cs4@test.com", "x", "U")
        h = _auth(user.email)
        acc = client.post("/api/bank-accounts", json={"name": "Conta", "account_type": "checking"}, headers=h).json()
        both = client.post("/api/categories", json={"name": "Compartilhada", "applies_to_bank": True, "applies_to_credit_card": True}, headers=h).json()
        card_only = client.post("/api/categories", json={"name": "Cartao", "applies_to_bank": False, "applies_to_credit_card": True}, headers=h).json()

        ok = client.post(
            "/api/transactions",
            json={"transaction_type": "expense", "amount": -50, "transaction_date": "2026-06-01", "description": "Mercado", "bank_account_id": acc["id"], "category_id": both["id"]},
            headers=h,
        )
        assert ok.status_code == 200
        assert ok.json()["category_id"] == both["id"]

        bad = client.post(
            "/api/transactions",
            json={"transaction_type": "expense", "amount": -50, "transaction_date": "2026-06-01", "description": "X", "bank_account_id": acc["id"], "category_id": card_only["id"]},
            headers=h,
        )
        assert bad.status_code == 404
