from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services.auth_service import create_access_token, create_user
from app.models.invoice import Invoice
from app.models.transaction import Transaction
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


class TestAnnualCardInvoices:
    def test_lists_real_and_predicted_installments(self, client, db):
        user = create_user(db, "ai1@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)

        inv_apr = Invoice(user_id=user.id, card_id=card["id"], due_month="2026-04", total_amount=100.0)
        inv_may = Invoice(user_id=user.id, card_id=card["id"], due_month="2026-05", total_amount=300.0)
        db.add_all([inv_apr, inv_may])
        db.commit()
        db.refresh(inv_apr)
        db.refresh(inv_may)

        db.add(Transaction(
            user_id=user.id, date=date(2026, 5, 10), description="Notebook 1/3",
            amount=-300.0, card_id=card["id"], invoice_id=inv_may.id,
            installment_current=1, installment_total=3,
        ))
        db.commit()

        months = client.get(f"/api/cards/{card['id']}/annual-invoices?year=2026", headers=h).json()
        by_month = {m["due_month"]: m for m in months}

        assert [m["due_month"] for m in months] == ["2026-04", "2026-05", "2026-06", "2026-07"]
        assert by_month["2026-04"]["predicted"] is False
        assert by_month["2026-04"]["invoice_id"] == inv_apr.id
        assert by_month["2026-04"]["total"] == 100.0
        assert by_month["2026-06"]["predicted"] is True
        assert by_month["2026-06"]["invoice_id"] is None
        assert by_month["2026-06"]["total"] == 300.0
        assert by_month["2026-07"]["predicted"] is True
        assert "2026-08" not in by_month

    def test_no_projection_when_installment_complete(self, client, db):
        user = create_user(db, "ai2@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        inv = Invoice(user_id=user.id, card_id=card["id"], due_month="2026-05", total_amount=300.0)
        db.add(inv)
        db.commit()
        db.refresh(inv)
        db.add(Transaction(
            user_id=user.id, date=date(2026, 5, 10), description="Notebook 3/3",
            amount=-300.0, card_id=card["id"], invoice_id=inv.id,
            installment_current=3, installment_total=3,
        ))
        db.commit()

        months = client.get(f"/api/cards/{card['id']}/annual-invoices?year=2026", headers=h).json()
        assert [m["due_month"] for m in months] == ["2026-05"]

    def test_card_without_invoices_returns_empty_list(self, client, db):
        user = create_user(db, "ai4@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)

        res = client.get(f"/api/cards/{card['id']}/annual-invoices?year=2026", headers=h)
        assert res.status_code == 200
        assert res.json() == []

    def test_nonexistent_card_returns_404(self, client, db):
        user = create_user(db, "ai5@test.com", "x", "U")
        h = _auth(user.email)

        res = client.get("/api/cards/999999/annual-invoices", headers=h)
        assert res.status_code == 404

    def test_filters_by_year(self, client, db):
        user = create_user(db, "ai3@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        inv = Invoice(user_id=user.id, card_id=card["id"], due_month="2025-12", total_amount=120.0)
        db.add(inv)
        db.commit()
        db.refresh(inv)
        db.add(Transaction(
            user_id=user.id, date=date(2025, 12, 10), description="Curso 1/4",
            amount=-120.0, card_id=card["id"], invoice_id=inv.id,
            installment_current=1, installment_total=4,
        ))
        db.commit()

        months_2025 = client.get(f"/api/cards/{card['id']}/annual-invoices?year=2025", headers=h).json()
        months_2026 = client.get(f"/api/cards/{card['id']}/annual-invoices?year=2026", headers=h).json()

        assert [m["due_month"] for m in months_2025] == ["2025-12"]
        assert [m["due_month"] for m in months_2026] == ["2026-01", "2026-02", "2026-03"]
        assert all(m["predicted"] for m in months_2026)
