"""Issue #114 — fontes de entrada, conta principal e regras de cálculo (benefício/reserva)."""

from datetime import date

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


def _create_account(client, headers, **overrides) -> dict:
    body = {"name": "Conta", "account_type": "checking"}
    body.update(overrides)
    return client.post("/api/bank-accounts", json=body, headers=headers).json()


def _create_income_source(client, headers, **overrides) -> dict:
    body = {"name": "Salário CLT", "type": "clt", "nature": "cash_income"}
    body.update(overrides)
    return client.post("/api/income-sources", json=body, headers=headers).json()


class TestBankAccountIsMain:
    def test_setting_main_unsets_other_accounts(self, client, db):
        user = create_user(db, "im1@test.com", "x", "U")
        h = _auth(user.email)
        acc1 = _create_account(client, h, name="Conta 1", is_main=True)
        acc2 = _create_account(client, h, name="Conta 2")

        assert acc1["is_main"] is True

        r = client.patch(f"/api/bank-accounts/{acc2['id']}", json={"is_main": True}, headers=h)
        assert r.status_code == 200
        assert r.json()["is_main"] is True

        acc1_reloaded = client.get(f"/api/bank-accounts/{acc1['id']}", headers=h).json()
        assert acc1_reloaded["is_main"] is False

    def test_new_account_type_values_accepted(self, client, db):
        user = create_user(db, "im2@test.com", "x", "U")
        h = _auth(user.email)
        for account_type in ("benefit", "reserve", "cash"):
            r = client.post(
                "/api/bank-accounts",
                json={"name": account_type, "account_type": account_type},
                headers=h,
            )
            assert r.status_code == 200, r.text
            assert r.json()["account_type"] == account_type


class TestIncomeSourcesCrud:
    def test_create_list_update_delete(self, client, db):
        user = create_user(db, "is1@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        src = _create_income_source(
            client, h, name="Salário CLT", type="clt", nature="cash_income", default_account_id=acc["id"]
        )
        assert src["default_account_id"] == acc["id"]
        assert src["is_active"] is True

        r = client.get("/api/income-sources", headers=h)
        assert len(r.json()) == 1

        r = client.patch(
            f"/api/income-sources/{src['id']}",
            json={"name": "Salário CLT Atualizado", "is_active": False},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Salário CLT Atualizado"
        assert r.json()["is_active"] is False

        r = client.delete(f"/api/income-sources/{src['id']}", headers=h)
        assert r.status_code == 200
        assert client.get("/api/income-sources", headers=h).json() == []

    def test_invalid_type_and_nature_rejected(self, client, db):
        user = create_user(db, "is2@test.com", "x", "U")
        h = _auth(user.email)
        r = client.post(
            "/api/income-sources",
            json={"name": "X", "type": "invalid", "nature": "cash_income"},
            headers=h,
        )
        assert r.status_code == 422

        r = client.post(
            "/api/income-sources",
            json={"name": "X", "type": "clt", "nature": "invalid"},
            headers=h,
        )
        assert r.status_code == 422

    def test_foreign_user_404(self, client, db):
        u1 = create_user(db, "is3@test.com", "x", "A")
        u2 = create_user(db, "is4@test.com", "x", "B")
        src = _create_income_source(client, _auth(u1.email))

        r = client.patch(f"/api/income-sources/{src['id']}", json={"name": "hack"}, headers=_auth(u2.email))
        assert r.status_code == 404
        r = client.delete(f"/api/income-sources/{src['id']}", headers=_auth(u2.email))
        assert r.status_code == 404

    def test_default_account_must_belong_to_user(self, client, db):
        u1 = create_user(db, "is5@test.com", "x", "A")
        u2 = create_user(db, "is6@test.com", "x", "B")
        acc = _create_account(client, _auth(u1.email))

        r = client.post(
            "/api/income-sources",
            json={"name": "X", "type": "clt", "nature": "cash_income", "default_account_id": acc["id"]},
            headers=_auth(u2.email),
        )
        assert r.status_code == 404

    def test_delete_income_source_nullifies_linked_transaction(self, client, db):
        user = create_user(db, "is7@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)
        src = _create_income_source(client, h)

        tx = client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 100.0,
                "transaction_date": "2026-06-10",
                "description": "Salário",
                "bank_account_id": acc["id"],
                "income_source_id": src["id"],
            },
            headers=h,
        ).json()
        assert tx["income_source_id"] == src["id"]
        assert tx["income_source_name"] == src["name"]

        assert client.delete(f"/api/income-sources/{src['id']}", headers=h).status_code == 200

        r = client.get("/api/transactions", headers=h).json()
        assert r[0]["income_source_id"] is None


class TestManualTransactionIncomeSourceAndReserve:
    def test_manual_transaction_with_income_source(self, client, db):
        user = create_user(db, "mt1@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)
        src = _create_income_source(client, h, nature="restricted_benefit", type="benefit")

        r = client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 900.0,
                "transaction_date": "2026-06-10",
                "description": "VA",
                "bank_account_id": acc["id"],
                "income_source_id": src["id"],
            },
            headers=h,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["income_source_id"] == src["id"]
        assert data["income_source_nature"] == "restricted_benefit"

    def test_reserve_or_investment_flag_overrides_transaction_type(self, client, db):
        user = create_user(db, "mt2@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        r = client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": -500.0,
                "transaction_date": "2026-06-10",
                "description": "Aporte caixinha",
                "bank_account_id": acc["id"],
                "is_reserve_or_investment": True,
            },
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["transaction_type"] == "reserve_or_investment_movement"

    def test_rejects_other_user_income_source(self, client, db):
        u1 = create_user(db, "mt3@test.com", "x", "A")
        u2 = create_user(db, "mt4@test.com", "x", "B")
        acc = _create_account(client, _auth(u2.email))
        src = _create_income_source(client, _auth(u1.email))

        r = client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 100.0,
                "transaction_date": "2026-06-10",
                "description": "x",
                "bank_account_id": acc["id"],
                "income_source_id": src["id"],
            },
            headers=_auth(u2.email),
        )
        assert r.status_code == 404

    def test_patch_transaction_income_source(self, client, db):
        user = create_user(db, "mt5@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)
        src = _create_income_source(client, h)
        tx = client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 100.0,
                "transaction_date": "2026-06-10",
                "description": "x",
                "bank_account_id": acc["id"],
            },
            headers=h,
        ).json()
        assert tx["income_source_id"] is None

        r = client.patch(f"/api/transactions/{tx['id']}", json={"income_source_id": src["id"]}, headers=h)
        assert r.status_code == 200
        assert r.json()["income_source_id"] == src["id"]

        r = client.patch(f"/api/transactions/{tx['id']}", json={"income_source_id": 0}, headers=h)
        assert r.status_code == 200
        assert r.json()["income_source_id"] is None


class TestSummaryCalcRules:
    def test_benefit_excluded_from_income_and_shown_separately(self, client, db):
        user = create_user(db, "sc1@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)
        benefit_src = _create_income_source(client, h, name="VA", type="benefit", nature="restricted_benefit")

        today = date.today().isoformat()
        client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 8500.0,
                "transaction_date": today,
                "description": "Salário",
                "bank_account_id": acc["id"],
            },
            headers=h,
        )
        client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 900.0,
                "transaction_date": today,
                "description": "VA",
                "bank_account_id": acc["id"],
                "income_source_id": benefit_src["id"],
            },
            headers=h,
        )

        body = client.get("/api/summary", headers=h).json()
        assert body["monthly_income"] == 8500.0
        assert body["monthly_benefits"] == 900.0

    def test_reserve_or_investment_excluded_from_income_and_expenses(self, client, db):
        user = create_user(db, "sc2@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        today = date.today().isoformat()
        client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": -500.0,
                "transaction_date": today,
                "description": "Aporte",
                "bank_account_id": acc["id"],
                "is_reserve_or_investment": True,
            },
            headers=h,
        )
        client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": -100.0,
                "transaction_date": today,
                "description": "Mercado",
                "bank_account_id": acc["id"],
            },
            headers=h,
        )

        body = client.get("/api/summary", headers=h).json()
        assert body["monthly_expenses"] == 100.0
        assert body["monthly_income"] == 0.0
        assert body["monthly_benefits"] == 0.0
