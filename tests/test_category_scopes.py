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


class TestGlobalCategories:
    def test_create_without_destination(self, client, db):
        user = create_user(db, "g1@test.com", "x", "U")
        r = client.post("/api/categories", json={"name": "Alimentação", "color": "#FF0000"}, headers=_auth(user.email))
        assert r.status_code == 200
        assert r.json()["name"] == "Alimentação"

    def test_listing_returns_all(self, client, db):
        user = create_user(db, "g2@test.com", "x", "U")
        h = _auth(user.email)
        client.post("/api/categories", json={"name": "A"}, headers=h)
        client.post("/api/categories", json={"name": "B"}, headers=h)
        names = {c["name"] for c in client.get("/api/categories", headers=h).json()}
        assert names == {"A", "B"}
        legacy = {c["name"] for c in client.get("/api/categories?scope=bank", headers=h).json()}
        assert legacy == {"A", "B"}

    def test_global_category_usable_in_bank_tx(self, client, db):
        user = create_user(db, "g3@test.com", "x", "U")
        h = _auth(user.email)
        acc = client.post("/api/bank-accounts", json={"name": "Conta", "account_type": "checking"}, headers=h).json()
        cat = client.post("/api/categories", json={"name": "Mercado"}, headers=h).json()
        r = client.post(
            "/api/transactions",
            json={"transaction_type": "expense", "amount": -50, "transaction_date": "2026-06-01", "description": "X", "bank_account_id": acc["id"], "category_id": cat["id"]},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["category_id"] == cat["id"]
