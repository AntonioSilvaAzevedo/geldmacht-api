"""Contas bancárias (CRUD + soft delete) e lançamentos manuais."""

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


class TestBankAccounts:
    def test_crud_and_soft_delete(self, client, db):
        user = create_user(db, "bk@test.com", "x", "U")
        h = _auth(user.email)

        r = client.post(
            "/api/bank-accounts",
            json={
                "name": "Nubank",
                "institution": "Nubank",
                "account_type": "payment",
                "currency": "BRL",
            },
            headers=h,
        )
        assert r.status_code == 200
        aid = r.json()["id"]

        r = client.get("/api/bank-accounts", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = client.patch(
            f"/api/bank-accounts/{aid}",
            json={"name": "Nubank Conta PF"},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Nubank Conta PF"

        r = client.delete(f"/api/bank-accounts/{aid}", headers=h)
        assert r.status_code == 200

        r = client.get("/api/bank-accounts", headers=h)
        assert r.json() == []

        r = client.get("/api/bank-accounts?include_inactive=true", headers=h)
        assert len(r.json()) == 1
        assert r.json()[0]["is_active"] is False

    def test_foreign_user_404(self, client, db):
        u1 = create_user(db, "a1@test.com", "x", "A")
        u2 = create_user(db, "a2@test.com", "x", "B")
        r = client.post(
            "/api/bank-accounts",
            json={"name": "C1", "account_type": "checking"},
            headers=_auth(u1.email),
        )
        aid = r.json()["id"]

        r = client.get(f"/api/bank-accounts/{aid}", headers=_auth(u2.email))
        assert r.status_code == 404


class TestManualTransaction:
    def test_create_manual_income_and_category_scope(self, client, db):
        user = create_user(db, "m1@test.com", "x", "M")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        cat = client.post(
            "/api/categories",
            json={"name": "Salário", "scope": "bank", "icon": "banknote"},
            headers=h,
        ).json()

        r = client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 100.0,
                "transaction_date": "2026-05-11",
                "description": "Teste",
                "bank_account_id": acc["id"],
                "category_id": cat["id"],
            },
            headers=h,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["amount"] == 100.0
        assert data["source"] == "manual"
        assert data["bank_account_id"] == acc["id"]
        assert data["card_id"] is None
        assert data["invoice_id"] is None
        assert data["transaction_type"] == "income"

    def test_expense_must_be_negative(self, client, db):
        user = create_user(db, "m2@test.com", "x", "M")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        r = client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": 45.90,
                "transaction_date": "2026-05-11",
                "description": "Erro",
                "bank_account_id": acc["id"],
            },
            headers=h,
        )
        assert r.status_code == 422

        r = client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": -45.90,
                "transaction_date": "2026-05-11",
                "description": "Ok",
                "bank_account_id": acc["id"],
            },
            headers=h,
        )
        assert r.status_code == 200

    def test_rejects_other_user_bank_account(self, client, db):
        u1 = create_user(db, "o1@test.com", "x", "A")
        u2 = create_user(db, "o2@test.com", "x", "B")
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Outro", "account_type": "checking"},
            headers=_auth(u1.email),
        ).json()

        r = client.post(
            "/api/transactions",
            json={
                "transaction_type": "income",
                "amount": 1.0,
                "transaction_date": "2026-05-11",
                "description": "x",
                "bank_account_id": acc["id"],
            },
            headers=_auth(u2.email),
        )
        assert r.status_code == 404

class TestImportKind:
    _FH = "a" * 64
    _FH_B = "b" * 64

    def test_bank_statement_import_creates_transactions(self, client, db):
        user = create_user(db, "i1@test.com", "x", "I")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        payload = {
            "source_file": "t.ofx",
            "parser_used": "bank_statement_ofx",
            "import_kind": "bank_statement",
            "bank_account_id": acc["id"],
            "file_hash": self._FH,
            "transactions": [
                {
                    "date": "2026-05-01",
                    "description": "Pix",
                    "raw_description": "Pix",
                    "amount": -10.0,
                    "account": "bank_statement_ofx",
                    "transaction_type": "expense",
                    "source_reference": "fit-1",
                    "is_internal_transfer": False,
                    "is_payment": False,
                }
            ],
        }
        r = client.post("/api/import", json=payload, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported"] == 1
        assert body["skipped"] == 0
        assert body["bank_account_id"] == acc["id"]
        assert body["import_batch_id"] is not None
        assert body["transactions"]
        assert body["transactions"][0]["source_reference"] == "fit-1"
        assert body["transactions"][0]["source"] == "bank_statement_import"

    def test_bank_statement_requires_bank_account_id(self, client, db):
        user = create_user(db, "i2@test.com", "x", "I")
        h = _auth(user.email)
        payload = {
            "source_file": "t.ofx",
            "parser_used": "bank_statement_ofx",
            "import_kind": "bank_statement",
            "transactions": [
                {
                    "date": "2026-05-01",
                    "description": "x",
                    "amount": -1.0,
                    "account": "bank_statement_ofx",
                    "is_internal_transfer": False,
                    "is_payment": False,
                }
            ],
        }
        r = client.post("/api/import", json=payload, headers=h)
        assert r.status_code == 400

    def test_bank_statement_rejects_wrong_account_key(self, client, db):
        user = create_user(db, "i3@test.com", "x", "I")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        payload = {
            "source_file": "t.ofx",
            "parser_used": "bank_statement_ofx",
            "import_kind": "bank_statement",
            "bank_account_id": acc["id"],
            "file_hash": "f1" + "0" * 62,
            "transactions": [
                {
                    "date": "2026-05-01",
                    "description": "x",
                    "amount": -1.0,
                    "account": "nubank_pf",
                    "is_internal_transfer": False,
                    "is_payment": False,
                }
            ],
        }
        r = client.post("/api/import", json=payload, headers=h)
        assert r.status_code == 400

    def test_bank_statement_rejects_credit_card_category(self, client, db):
        user = create_user(db, "i3b@test.com", "x", "I")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        cat = client.post(
            "/api/categories",
            json={"name": "CartaoCat", "scope": "credit_card"},
            headers=h,
        ).json()
        payload = {
            "source_file": "t.ofx",
            "parser_used": "bank_statement_ofx",
            "import_kind": "bank_statement",
            "bank_account_id": acc["id"],
            "file_hash": "f2" + "0" * 62,
            "transactions": [
                {
                    "date": "2026-05-01",
                    "description": "x",
                    "amount": -1.0,
                    "account": "bank_statement_ofx",
                    "category_id": cat["id"],
                    "is_internal_transfer": False,
                    "is_payment": False,
                }
            ],
        }
        r = client.post("/api/import", json=payload, headers=h)
        assert r.status_code == 400

    def test_bank_statement_duplicate_fitid_skipped(self, client, db):
        user = create_user(db, "i4@test.com", "x", "I")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        tx = {
            "date": "2026-05-01",
            "description": "x",
            "raw_description": "x",
            "amount": -1.0,
            "account": "bank_statement_ofx",
            "source_reference": "same-id",
            "is_internal_transfer": False,
            "is_payment": False,
        }
        base = {
            "source_file": "t.ofx",
            "parser_used": "bank_statement_ofx",
            "import_kind": "bank_statement",
            "bank_account_id": acc["id"],
            "file_hash": self._FH_B,
            "transactions": [tx],
        }
        r1 = client.post("/api/import", json=base, headers=h)
        assert r1.status_code == 200 and r1.json()["imported"] == 1
        base2 = {**base, "file_hash": "c" * 64}
        r2 = client.post("/api/import", json=base2, headers=h)
        assert r2.status_code == 200
        assert r2.json()["imported"] == 0 and r2.json()["skipped"] == 1

    def test_bank_statement_same_file_hash_returns_409(self, client, db):
        user = create_user(db, "i5@test.com", "x", "I")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        fh = "d" * 64
        tx = {
            "date": "2026-05-01",
            "description": "x",
            "raw_description": "x",
            "amount": -1.0,
            "account": "bank_statement_ofx",
            "source_reference": "u1",
            "is_internal_transfer": False,
            "is_payment": False,
        }
        base = {
            "source_file": "t.ofx",
            "parser_used": "bank_statement_ofx",
            "import_kind": "bank_statement",
            "bank_account_id": acc["id"],
            "file_hash": fh,
            "transactions": [tx],
        }
        assert client.post("/api/import", json=base, headers=h).status_code == 200
        r2 = client.post("/api/import", json=base, headers=h)
        assert r2.status_code == 409

    def test_list_import_batches_for_account(self, client, db):
        user = create_user(db, "i6@test.com", "x", "I")
        h = _auth(user.email)
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "Conta", "account_type": "checking"},
            headers=h,
        ).json()
        payload = {
            "source_file": "t.ofx",
            "parser_used": "bank_statement_ofx",
            "import_kind": "bank_statement",
            "bank_account_id": acc["id"],
            "file_hash": "e" * 64,
            "transactions": [
                {
                    "date": "2026-05-01",
                    "description": "Pix",
                    "raw_description": "Pix",
                    "amount": -10.0,
                    "account": "bank_statement_ofx",
                    "transaction_type": "expense",
                    "source_reference": "z1",
                    "is_internal_transfer": False,
                    "is_payment": False,
                }
            ],
        }
        assert client.post("/api/import", json=payload, headers=h).status_code == 200
        r = client.get(f"/api/bank-accounts/{acc['id']}/import-batches", headers=h)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["file_name"] == "t.ofx"
        assert data[0]["file_hash"] == "e" * 64
