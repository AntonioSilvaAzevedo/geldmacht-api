from datetime import date, datetime

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
from app.models.recurring_expense import RecurringExpense
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


def _expense_tx(db, user_id, card_id, due_month="2026-05", description="Netflix", amount=-39.90):
    inv = Invoice(user_id=user_id, card_id=card_id, due_month=due_month, total_amount=abs(amount))
    db.add(inv)
    db.commit()
    db.refresh(inv)
    tx = Transaction(
        user_id=user_id, date=date(2026, 5, 10), description=description, amount=amount,
        card_id=card_id, invoice_id=inv.id, imported_at=datetime(2026, 5, 10),
        is_internal_transfer=False, is_payment=False, source="pdf_invoice_import",
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx, inv


class TestRecorrentesSuggestion:
    def test_suggestion_listed_then_hidden_after_accept(self, client, db):
        user = create_user(db, "r1@test.com", "x", "U")
        h = _auth(user.email)

        sugg = client.get("/api/categories/suggestions", headers=h).json()
        assert any(s["key"] == "recorrentes" for s in sugg)

        created = client.post("/api/categories/suggestions/recorrentes", headers=h).json()
        assert created["name"] == "Recorrentes"
        assert created["system_key"] == "recorrentes"
        assert created["scope"] == "global"

        again = client.post("/api/categories/suggestions/recorrentes", headers=h).json()
        assert again["id"] == created["id"]
        cats = [c for c in client.get("/api/categories", headers=h).json() if c["system_key"] == "recorrentes"]
        assert len(cats) == 1

        assert all(s["key"] != "recorrentes" for s in client.get("/api/categories/suggestions", headers=h).json())


class TestRecorrentesRecurrence:
    def _setup(self, client, db):
        user = create_user(db, "r2@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        rec_cat = client.post("/api/categories/suggestions/recorrentes", headers=h).json()
        tx, inv = _expense_tx(db, user.id, card["id"])
        return user, h, card, rec_cat, tx, inv

    def test_categorizing_creates_recurrence(self, client, db):
        user, h, card, rec_cat, tx, inv = self._setup(client, db)

        res = client.patch(f"/api/transactions/{tx.id}", json={"category_id": rec_cat["id"]}, headers=h)
        assert res.status_code == 200

        rec = db.query(RecurringExpense).filter(RecurringExpense.source_transaction_id == tx.id).first()
        assert rec is not None
        assert rec.start_month == "2026-05"
        assert rec.end_month == "2027-05"
        assert round(rec.amount, 2) == 39.90
        assert rec.active is True

    def test_projection_includes_recurrence_within_12_months(self, client, db):
        user, h, card, rec_cat, tx, inv = self._setup(client, db)
        client.patch(f"/api/transactions/{tx.id}", json={"category_id": rec_cat["id"]}, headers=h)

        months_2026 = {m["due_month"]: m for m in client.get(f"/api/cards/{card['id']}/annual-invoices?year=2026", headers=h).json()}
        assert "2026-06" in months_2026
        assert months_2026["2026-06"]["predicted"] is True
        assert round(months_2026["2026-06"]["total"], 2) == 39.90

        months_2027 = {m["due_month"] for m in client.get(f"/api/cards/{card['id']}/annual-invoices?year=2027", headers=h).json()}
        assert "2027-05" in months_2027
        assert "2027-06" not in months_2027

    def test_uncategorizing_removes_recurrence(self, client, db):
        user, h, card, rec_cat, tx, inv = self._setup(client, db)
        client.patch(f"/api/transactions/{tx.id}", json={"category_id": rec_cat["id"]}, headers=h)
        assert db.query(RecurringExpense).filter(RecurringExpense.source_transaction_id == tx.id).count() == 1

        client.patch(f"/api/transactions/{tx.id}", json={"category_id": 0}, headers=h)
        assert db.query(RecurringExpense).filter(RecurringExpense.source_transaction_id == tx.id).count() == 0

    def test_predicted_composition_lists_recurrence(self, client, db):
        user, h, card, rec_cat, tx, inv = self._setup(client, db)
        client.patch(f"/api/transactions/{tx.id}", json={"category_id": rec_cat["id"]}, headers=h)

        comp = client.get(f"/api/cards/{card['id']}/predicted-invoices/2026-06", headers=h).json()
        recurring = [it for it in comp["items"] if it["origin"] == "recurring"]
        assert any(it["description"] == "Netflix" for it in recurring)
