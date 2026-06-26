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


def _card(client, headers) -> dict:
    return client.post(
        "/api/cards",
        json={"name": "Platinum", "closing_day": 25, "due_day": 5},
        headers=headers,
    ).json()


def _tx(date: str, description: str, amount: float, raw: str | None = None) -> dict:
    return {
        "date": date,
        "description": description,
        "raw_description": raw or description,
        "amount": amount,
        "account": "nubank_cartao",
    }


def _import(client, headers, card_id: int, due_month: str, txs: list[dict]):
    return client.post(
        "/api/import",
        json={
            "source_file": "fatura.pdf",
            "parser_used": "faturacartaonubank",
            "card_id": card_id,
            "reference_month": due_month,
            "import_kind": "credit_card_invoice",
            "transactions": txs,
        },
        headers=headers,
    )


def _invoice_transactions(client, headers, invoice_id: int) -> list[dict]:
    res = client.get(
        f"/api/transactions/invoice?invoice_id={invoice_id}",
        headers=headers,
    )
    assert res.status_code == 200, res.text
    return res.json()["transactions"]


class TestInvoiceReimport:
    def test_reimport_does_not_duplicate_and_adds_new(self, client, db):
        user = create_user(db, "reimp1@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)

        first = _import(client, h, card["id"], "2026-01", [
            _tx("2026-01-05", "Mercado", -50.0, "MERCADO LTDA"),
            _tx("2026-01-08", "Posto", -120.0, "POSTO SHELL"),
        ])
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["imported"] == 2
        assert body["skipped"] == 0
        invoice_id = body["invoice_id"]
        assert invoice_id is not None

        second = _import(client, h, card["id"], "2026-01", [
            _tx("2026-01-05", "Mercado", -50.0, "MERCADO LTDA"),
            _tx("2026-01-08", "Posto", -120.0, "POSTO SHELL"),
            _tx("2026-01-20", "Farmácia", -30.0, "DROGARIA"),
        ])
        assert second.status_code == 200, second.text
        body2 = second.json()
        assert body2["imported"] == 1
        assert body2["skipped"] == 2
        assert body2["invoice_id"] == invoice_id

        txs = _invoice_transactions(client, h, invoice_id)
        assert len(txs) == 3
        raws = sorted(t["raw_description"] for t in txs)
        assert raws == ["DROGARIA", "MERCADO LTDA", "POSTO SHELL"]

    def test_reimport_preserves_user_category_description_and_tags(self, client, db):
        user = create_user(db, "reimp2@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)

        first = _import(client, h, card["id"], "2026-02", [
            _tx("2026-02-05", "Mercado", -80.0, "MERCADO LTDA"),
        ])
        invoice_id = first.json()["invoice_id"]
        tx_id = _invoice_transactions(client, h, invoice_id)[0]["id"]

        cat = client.post(
            "/api/categories",
            json={"name": "Alimentação", "applies_to_credit_card": True},
            headers=h,
        ).json()

        patch = client.patch(
            f"/api/transactions/{tx_id}",
            json={"description": "Mercado renomeado", "category_id": cat["id"]},
            headers=h,
        )
        assert patch.status_code == 200, patch.text

        tags = client.put(
            f"/api/transactions/{tx_id}/tags",
            json={"names": ["casa"]},
            headers=h,
        )
        assert tags.status_code == 200, tags.text

        reimport = _import(client, h, card["id"], "2026-02", [
            _tx("2026-02-05", "Mercado", -80.0, "MERCADO LTDA"),
        ])
        assert reimport.status_code == 200, reimport.text
        assert reimport.json()["imported"] == 0
        assert reimport.json()["skipped"] == 1

        txs = _invoice_transactions(client, h, invoice_id)
        assert len(txs) == 1
        kept = txs[0]
        assert kept["id"] == tx_id
        assert kept["description"] == "Mercado renomeado"
        assert kept["category_id"] == cat["id"]
        assert [t["name"] for t in kept["tags"]] == ["casa"]

    def test_manual_transaction_cannot_attach_to_invoice(self, client, db):
        user = create_user(db, "reimp3@test.com", "x", "U")
        h = _auth(user.email)

        bank = client.post(
            "/api/bank-accounts",
            json={"name": "Conta Corrente", "account_type": "checking"},
            headers=h,
        ).json()

        created = client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": -10.0,
                "transaction_date": "2026-01-10",
                "description": "Compra manual",
                "bank_account_id": bank["id"],
            },
            headers=h,
        )
        assert created.status_code == 200, created.text
        out = created.json()
        assert out["invoice_id"] is None
        assert out["card_id"] is None
        assert out["bank_account_id"] == bank["id"]
