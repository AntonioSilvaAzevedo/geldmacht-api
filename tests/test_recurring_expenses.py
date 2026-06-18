import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services.auth_service import create_access_token, create_user
from app.models.invoice import Invoice
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


def _card(client, headers) -> dict:
    return client.post(
        "/api/cards",
        json={"name": "Platinum", "closing_day": 25, "due_day": 5},
        headers=headers,
    ).json()


class TestRecurringExpenses:
    def test_create_list_delete(self, client, db):
        user = create_user(db, "re1@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)

        created = client.post(
            f"/api/cards/{card['id']}/recurring",
            json={"description": "Netflix", "amount": 39.9, "start_month": "2026-05"},
            headers=h,
        )
        assert created.status_code == 200
        sub = created.json()
        assert sub["active"] is True
        assert sub["start_month"] == "2026-05"
        assert sub["amount"] == 39.9

        listed = client.get(f"/api/cards/{card['id']}/recurring", headers=h).json()
        assert len(listed) == 1

        deleted = client.delete(f"/api/cards/{card['id']}/recurring/{sub['id']}", headers=h)
        assert deleted.status_code == 200
        assert client.get(f"/api/cards/{card['id']}/recurring", headers=h).json() == []

    def test_projected_in_annual(self, client, db):
        user = create_user(db, "re2@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        inv = Invoice(user_id=user.id, card_id=card["id"], due_month="2026-05", total_amount=100.0)
        db.add(inv)
        db.commit()

        client.post(
            f"/api/cards/{card['id']}/recurring",
            json={"description": "Netflix", "amount": 39.9, "start_month": "2026-05"},
            headers=h,
        )

        months = client.get(f"/api/cards/{card['id']}/annual-invoices?year=2026", headers=h).json()
        by_month = {m["due_month"]: m for m in months}

        assert by_month["2026-05"]["predicted"] is False
        predicted = [m["due_month"] for m in months if m["predicted"]]
        assert predicted == ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]
        assert by_month["2026-06"]["total"] == 39.9
        assert by_month["2026-12"]["total"] == 39.9

    def test_delete_other_user_forbidden(self, client, db):
        owner = create_user(db, "re3@test.com", "x", "Owner")
        other = create_user(db, "re4@test.com", "x", "Other")
        card = _card(client, _auth(owner.email))
        sub = client.post(
            f"/api/cards/{card['id']}/recurring",
            json={"description": "Spotify", "amount": 21.9},
            headers=_auth(owner.email),
        ).json()

        r = client.delete(f"/api/cards/{card['id']}/recurring/{sub['id']}", headers=_auth(other.email))
        assert r.status_code == 404
        assert len(client.get(f"/api/cards/{card['id']}/recurring", headers=_auth(owner.email)).json()) == 1
