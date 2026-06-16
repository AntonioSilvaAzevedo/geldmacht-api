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


class TestManualEligibility:
    def test_no_structure(self, client, db):
        user = create_user(db, "e1@test.com", "x", "U")
        r = client.get("/api/transactions/manual-eligibility", headers=_auth(user.email))
        assert r.status_code == 200
        assert r.json() == {"has_account": False, "has_card": False, "can_launch": False}

    def test_card_only_cannot_launch(self, client, db):
        user = create_user(db, "e2@test.com", "x", "U")
        h = _auth(user.email)
        client.post("/api/cards", json={"name": "C", "closing_day": 4, "due_day": 13}, headers=h)
        r = client.get("/api/transactions/manual-eligibility", headers=h)
        body = r.json()
        assert body == {"has_account": False, "has_card": True, "can_launch": False}

    def test_account_can_launch(self, client, db):
        user = create_user(db, "e3@test.com", "x", "U")
        h = _auth(user.email)
        client.post("/api/bank-accounts", json={"name": "Conta", "account_type": "checking"}, headers=h)
        r = client.get("/api/transactions/manual-eligibility", headers=h)
        body = r.json()
        assert body["has_account"] is True
        assert body["can_launch"] is True
