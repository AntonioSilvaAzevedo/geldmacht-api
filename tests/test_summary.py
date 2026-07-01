from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services.auth_service import create_access_token, create_user
from app.services.summary_service import get_financial_summary
from app.models.bank_account import BankAccount
from app.models.credit_card import CreditCard
from app.models.institution import Institution
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


def _bank_account(db, user_id, institution_id=None) -> BankAccount:
    acc = BankAccount(user_id=user_id, name="Conta", institution_id=institution_id)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _bank_tx(db, user_id, account_id, amount, tx_date, internal=False, status="confirmed"):
    tx = Transaction(
        user_id=user_id, date=tx_date, description="Mov", amount=amount,
        bank_account_id=account_id, imported_at=datetime(2026, 5, 10),
        is_internal_transfer=internal, is_payment=False, source="bank_statement_import",
        status=status,
    )
    db.add(tx)
    db.commit()
    return tx


def _card(db, user_id, institution_id=None) -> CreditCard:
    card = CreditCard(
        user_id=user_id, name="Platinum", closing_day=25, due_day=5, institution_id=institution_id
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


def _institution(db, user_id, name="Banco") -> Institution:
    inst = Institution(user_id=user_id, name=name)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _installment_tx(db, user_id, card_id, description, amount, current, total):
    tx = Transaction(
        user_id=user_id, date=date(2026, 5, 10), description=description, amount=amount,
        card_id=card_id, imported_at=datetime(2026, 5, 10),
        is_internal_transfer=False, is_payment=False, source="credit_card_invoice",
        installment_current=current, installment_total=total,
    )
    db.add(tx)
    db.commit()
    return tx


class TestSummaryEndpoint:
    def test_empty_summary(self, client, db):
        user = create_user(db, "s1@test.com", "x", "U")
        res = client.get("/api/summary", headers=_auth(user.email))
        assert res.status_code == 200
        body = res.json()
        assert body["available_balance"] == 0.0
        assert body["monthly_income"] == 0.0
        assert body["monthly_expenses"] == 0.0
        assert body["active_installments_count"] == 0
        assert body["future_committed_amount"] == 0.0
        assert body["period_label"]

    def test_income_and_expenses_current_month(self, client, db):
        user = create_user(db, "s2@test.com", "x", "U")
        acc = _bank_account(db, user.id)
        today = date.today()
        prev_month = today.replace(day=1) - timedelta(days=1)
        _bank_tx(db, user.id, acc.id, 1000.0, today)
        _bank_tx(db, user.id, acc.id, -300.0, today)
        _bank_tx(db, user.id, acc.id, 500.0, today, internal=True)
        _bank_tx(db, user.id, acc.id, -999.0, prev_month)

        body = client.get("/api/summary", headers=_auth(user.email)).json()
        assert body["monthly_income"] == 1000.0
        assert body["monthly_expenses"] == 300.0

    def test_ignored_duplicate_excluded_from_income_and_expenses(self, client, db):
        user = create_user(db, "s4@test.com", "x", "U")
        acc = _bank_account(db, user.id)
        today = date.today()
        _bank_tx(db, user.id, acc.id, 1000.0, today)
        _bank_tx(db, user.id, acc.id, -300.0, today)
        _bank_tx(db, user.id, acc.id, 8500.0, today, status="ignored_duplicate")
        _bank_tx(db, user.id, acc.id, -200.0, today, status="ignored_duplicate")

        body = client.get("/api/summary", headers=_auth(user.email)).json()
        assert body["monthly_income"] == 1000.0
        assert body["monthly_expenses"] == 300.0

    def test_active_installments_and_future(self, client, db):
        user = create_user(db, "s3@test.com", "x", "U")
        card = _card(db, user.id)
        _installment_tx(db, user.id, card.id, "Notebook", -200.0, 2, 6)
        _installment_tx(db, user.id, card.id, "Notebook", -200.0, 3, 6)
        _installment_tx(db, user.id, card.id, "TV", -100.0, 6, 6)

        body = client.get("/api/summary", headers=_auth(user.email)).json()
        assert body["active_installments_count"] == 1
        assert body["future_committed_amount"] == 600.0


class TestSummaryScopedByInstitution:
    def test_scopes_income_and_installments_to_institution(self, client, db):
        user = create_user(db, "s5@test.com", "x", "U")
        inst_a = _institution(db, user.id, "Banco A")
        inst_b = _institution(db, user.id, "Banco B")
        today = date.today()

        acc_a = _bank_account(db, user.id, institution_id=inst_a.id)
        acc_b = _bank_account(db, user.id, institution_id=inst_b.id)
        _bank_tx(db, user.id, acc_a.id, 1000.0, today)
        _bank_tx(db, user.id, acc_b.id, 5000.0, today)

        card_a = _card(db, user.id, institution_id=inst_a.id)
        card_b = _card(db, user.id, institution_id=inst_b.id)
        _installment_tx(db, user.id, card_a.id, "Notebook", -200.0, 2, 6)
        _installment_tx(db, user.id, card_b.id, "Geladeira", -300.0, 1, 10)

        body = client.get(
            f"/api/summary?institution_id={inst_a.id}", headers=_auth(user.email)
        ).json()
        assert body["monthly_income"] == 1000.0
        assert body["active_installments_count"] == 1
        assert body["future_committed_amount"] == 800.0


class TestSummaryService:
    def test_period_label_uses_current_month(self, db):
        user = create_user(db, "s4@test.com", "x", "U")
        result = get_financial_summary(db, user.id, today=date(2026, 6, 15))
        assert result.period_label == "Junho 2026"

    def test_institution_scope_excludes_other_institutions(self, db):
        user = create_user(db, "s6@test.com", "x", "U")
        inst = _institution(db, user.id)
        result = get_financial_summary(db, user.id, institution_id=inst.id)
        assert result.monthly_income == 0.0
        assert result.active_installments_count == 0
