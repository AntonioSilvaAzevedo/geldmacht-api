"""Tests for OFX credit-card invoice import (issue #104)."""

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


CC_OFX = """OFXHEADER:100
DATA:OFXSGML
<OFX>
<CREDITCARDMSGSRSV1>
<CCSTMTTRNRS>
<CCSTMTRS>
<CURDEF>BRL</CURDEF>
<CCACCTFROM>
<ACCTID>5555000011112222</ACCTID>
</CCACCTFROM>
<BANKTRANLIST>
<DTSTART>20260401000000[-3:BRT]</DTSTART>
<DTEND>20260430000000[-3:BRT]</DTEND>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20260405000000[-3:BRT]</DTPOSTED>
<TRNAMT>-65.73</TRNAMT>
<FITID>cc-001</FITID>
<MEMO>MERCADO LIVRE</MEMO>
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20260412000000[-3:BRT]</DTPOSTED>
<TRNAMT>-120.00</TRNAMT>
<FITID>cc-002</FITID>
<MEMO>POSTO SHELL</MEMO>
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT</TRNTYPE>
<DTPOSTED>20260420000000[-3:BRT]</DTPOSTED>
<TRNAMT>30.00</TRNAMT>
<FITID>cc-003</FITID>
<MEMO>ESTORNO</MEMO>
</STMTTRN>
</BANKTRANLIST>
</CCSTMTRS>
</CCSTMTTRNRS>
</CREDITCARDMSGSRSV1>
</OFX>
"""


def _upload(client, headers):
    return client.post(
        "/api/upload",
        data={"import_kind": "credit_card_invoice"},
        files={"file": ("fatura.ofx", CC_OFX.encode("utf-8"), "application/x-ofx")},
        headers=headers,
    )


def test_upload_ofx_invoice_preview(client):
    h = _auth(create_user(next(override_get_db()), "ccofx1@test.com", "x", "U").email)
    res = _upload(client, h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["parser_used"] == "credit_card_ofx"
    assert body["import_kind"] == "credit_card_invoice"
    assert body["detected_reference_month"] == "2026-04"
    assert body["total_transactions"] == 3
    assert all(tx["account"] == "credit_card_ofx" for tx in body["transactions"])
    debit = next(tx for tx in body["transactions"] if tx["amount"] == -65.73)
    assert debit["transaction_type"] == "expense"


def test_import_ofx_invoice_persists_linked_to_card(client, db):
    user = create_user(db, "ccofx2@test.com", "x", "U")
    h = _auth(user.email)
    card = _card(client, h)

    preview = _upload(client, h).json()

    res = client.post(
        "/api/import",
        json={
            "source_file": "fatura.ofx",
            "parser_used": "credit_card_ofx",
            "card_id": card["id"],
            "import_kind": "credit_card_invoice",
            "transactions": preview["transactions"],
        },
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 3
    assert body["card_id"] == card["id"]
    assert body["invoice_id"] is not None
    assert body["due_month"] == "2026-04"

    txs = client.get(
        f"/api/transactions/invoice?invoice_id={body['invoice_id']}",
        headers=h,
    ).json()["transactions"]
    assert len(txs) == 3
    assert all(t["source"] == "ofx_invoice_import" for t in txs)


def test_import_ofx_invoice_requires_card(client, db):
    user = create_user(db, "ccofx3@test.com", "x", "U")
    h = _auth(user.email)
    preview = _upload(client, h).json()

    res = client.post(
        "/api/import",
        json={
            "source_file": "fatura.ofx",
            "parser_used": "credit_card_ofx",
            "card_id": None,
            "import_kind": "credit_card_invoice",
            "transactions": preview["transactions"],
        },
        headers=h,
    )
    assert res.status_code == 400, res.text
    assert "art" in res.json()["detail"].lower()
