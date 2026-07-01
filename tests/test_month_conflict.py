"""Issue #103 — conflito entre lançamentos manuais e importação de extrato na conta corrente."""

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


def _create_account(client, headers) -> int:
    r = client.post(
        "/api/bank-accounts",
        json={"name": "Conta", "account_type": "checking"},
        headers=headers,
    )
    return r.json()["id"]


def _manual(client, headers, account_id, date_str, affects_summary=None):
    body = {
        "transaction_type": "income",
        "amount": 100.0,
        "transaction_date": date_str,
        "description": "Manual",
        "bank_account_id": account_id,
    }
    if affects_summary is not None:
        body["affects_summary"] = affects_summary
    return client.post("/api/transactions", json=body, headers=headers)


def _import_statement(client, headers, account_id, file_hash, date_str, amount=-10.0):
    payload = {
        "source_file": "t.ofx",
        "parser_used": "bank_statement_ofx",
        "import_kind": "bank_statement",
        "bank_account_id": account_id,
        "file_hash": file_hash,
        "transactions": [
            {
                "date": date_str,
                "description": "Extrato",
                "raw_description": "Extrato",
                "amount": amount,
                "account": "bank_statement_ofx",
                "source_reference": file_hash[:16],
                "is_internal_transfer": False,
                "is_payment": False,
            }
        ],
    }
    return client.post("/api/import", json=payload, headers=headers)


class TestMonthStatus:
    def test_empty_month(self, client, db):
        user = create_user(db, "mc1@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        r = client.get(f"/api/bank-accounts/{acc}/month-status?month=2026-06", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "has_manual": False,
            "has_imported": False,
            "manual_after_import": False,
            "can_import_statement": True,
            "needs_impact_confirmation": False,
        }

    def test_manual_only_blocks_import(self, client, db):
        user = create_user(db, "mc2@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        assert _manual(client, h, acc, "2026-06-10").status_code == 200

        status = client.get(f"/api/bank-accounts/{acc}/month-status?month=2026-06", headers=h).json()
        assert status["has_manual"] is True
        assert status["can_import_statement"] is False

        r = _import_statement(client, h, acc, "a" * 64, "2026-06-15")
        assert r.status_code == 409

    def test_imported_only_allows_manual_with_confirmation_flag(self, client, db):
        user = create_user(db, "mc3@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        assert _import_statement(client, h, acc, "b" * 64, "2026-06-05").status_code == 200

        status = client.get(f"/api/bank-accounts/{acc}/month-status?month=2026-06", headers=h).json()
        assert status["has_imported"] is True
        assert status["needs_impact_confirmation"] is True
        assert status["can_import_statement"] is True

        r = _manual(client, h, acc, "2026-06-20", affects_summary=False)
        assert r.status_code == 200
        assert r.json()["affects_summary"] is False

    def test_manual_after_import_blocks_new_import(self, client, db):
        user = create_user(db, "mc4@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        assert _import_statement(client, h, acc, "c" * 64, "2026-06-05").status_code == 200
        assert _manual(client, h, acc, "2026-06-20").status_code == 200

        status = client.get(f"/api/bank-accounts/{acc}/month-status?month=2026-06", headers=h).json()
        assert status["manual_after_import"] is True

        r = _import_statement(client, h, acc, "d" * 64, "2026-06-25")
        assert r.status_code == 409


class TestClearMonth:
    def test_clear_month_deletes_and_unblocks_import(self, client, db):
        user = create_user(db, "mc5@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        assert _manual(client, h, acc, "2026-06-10").status_code == 200
        assert _import_statement(client, h, acc, "e" * 64, "2026-06-15").status_code == 409

        r = client.delete(f"/api/bank-accounts/{acc}/transactions?month=2026-06", headers=h)
        assert r.status_code == 200
        assert r.json()["deleted"] == 1

        status = client.get(f"/api/bank-accounts/{acc}/month-status?month=2026-06", headers=h).json()
        assert status == {
            "has_manual": False,
            "has_imported": False,
            "manual_after_import": False,
            "can_import_statement": True,
            "needs_impact_confirmation": False,
        }

        assert _import_statement(client, h, acc, "f" * 64, "2026-06-15").status_code == 200

    def test_clear_month_only_affects_owner(self, client, db):
        u1 = create_user(db, "mc6@test.com", "x", "A")
        u2 = create_user(db, "mc7@test.com", "x", "B")
        acc = _create_account(client, _auth(u1.email))

        r = client.delete(
            f"/api/bank-accounts/{acc}/transactions?month=2026-06",
            headers=_auth(u2.email),
        )
        assert r.status_code == 404


class TestAffectsSummaryImpact:
    def test_affects_summary_false_excluded_from_totals(self, client, db):
        user = create_user(db, "mc8@test.com", "x", "U")
        h = _auth(user.email)
        acc = _create_account(client, h)

        today = date.today().isoformat()
        assert _manual(client, h, acc, today, affects_summary=True).status_code == 200
        assert _manual(client, h, acc, today, affects_summary=False).status_code == 200

        body = client.get("/api/summary", headers=h).json()
        assert body["monthly_income"] == 100.0
