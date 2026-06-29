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


BANK_OFX = """OFXHEADER:100
DATA:OFXSGML
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>BRL</CURDEF>
<BANKACCTFROM>
<BANKID>0260</BANKID>
<ACCTID>1234567-8</ACCTID>
<ACCTTYPE>CHECKING</ACCTTYPE>
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260401000000[-3:BRT]</DTSTART>
<DTEND>20260430000000[-3:BRT]</DTEND>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20260405000000[-3:BRT]</DTPOSTED>
<TRNAMT>-50.00</TRNAMT>
<FITID>bk-001</FITID>
<MEMO>SUPERMERCADO</MEMO>
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def _upload(client, headers):
    return client.post(
        "/api/upload",
        data={"import_kind": "credit_card_invoice"},
        files={"file": ("fatura.ofx", CC_OFX.encode("utf-8"), "application/x-ofx")},
        headers=headers,
    )


def _bank_account(client, headers) -> dict:
    return client.post(
        "/api/bank-accounts",
        json={"name": "Conta", "institution": "Nubank", "account_type": "checking", "currency": "BRL"},
        headers=headers,
    ).json()


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


def test_detect_ofx_kind_distinguishes_files():
    from app.parsers.ofx_bank_statement import detect_ofx_kind

    assert detect_ofx_kind(CC_OFX.encode("utf-8")) == "credit_card"
    assert detect_ofx_kind(BANK_OFX.encode("utf-8")) == "bank_statement"


INSTALLMENT_OFX = """OFXHEADER:100
DATA:OFXSGML
<OFX>
<CREDITCARDMSGSRSV1>
<CCSTMTRS>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260604000000[-3:BRT]
<TRNAMT>-85.50
<FITID>x1
<MEMO>Amazon - Parcela 1/10
</STMTTRN>
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260604000000[-3:BRT]
<TRNAMT>-40.90
<FITID>x2
<MEMO>Spotify
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260611000000[-3:BRT]
<TRNAMT>4576.41
<FITID>x3
<MEMO>Pagamento recebido
</STMTTRN>
</BANKTRANLIST>
</CCSTMTRS>
</CREDITCARDMSGSRSV1>
</OFX>"""


def test_invoice_context_detects_installment_and_payment():
    from app.parsers.ofx_bank_statement import parse_bank_statement_ofx

    _, txs = parse_bank_statement_ofx(INSTALLMENT_OFX.encode("utf-8"), invoice_context=True)
    amz = next(t for t in txs if t["amount"] == -85.50)
    assert amz["installment_current"] == 1
    assert amz["installment_total"] == 10
    assert amz["description"] == "Amazon"
    assert amz["is_payment"] is False
    pay = next(t for t in txs if t["is_payment"])
    assert pay["amount"] == 4576.41


def test_extrato_context_ignores_installment_and_payment():
    from app.parsers.ofx_bank_statement import parse_bank_statement_ofx

    _, txs = parse_bank_statement_ofx(INSTALLMENT_OFX.encode("utf-8"), invoice_context=False)
    assert all(t["installment_total"] is None for t in txs)
    assert all(t["is_payment"] is False for t in txs)
    amz = next(t for t in txs if t["amount"] == -85.50)
    assert amz["description"] == "Amazon - Parcela 1/10"


def test_import_ofx_invoice_blocks_category_on_installment(client, db):
    user = create_user(db, "ccofx6@test.com", "x", "U")
    h = _auth(user.email)
    card = _card(client, h)

    preview = client.post(
        "/api/upload",
        data={"import_kind": "credit_card_invoice"},
        files={"file": ("fatura.ofx", INSTALLMENT_OFX.encode("utf-8"), "application/x-ofx")},
        headers=h,
    ).json()

    amz = next(t for t in preview["transactions"] if t["amount"] == -85.50)
    assert amz["installment_current"] == 1 and amz["installment_total"] == 10
    pay = next(t for t in preview["transactions"] if t.get("is_payment"))
    assert pay["amount"] == 4576.41

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
    txs = client.get(
        f"/api/transactions/invoice?invoice_id={res.json()['invoice_id']}",
        headers=h,
    ).json()["transactions"]
    amz_saved = next(t for t in txs if t["amount"] == -85.50)
    assert amz_saved["installment_total"] == 10
    assert amz_saved["category_id"] is None
    pay_saved = next(t for t in txs if t["amount"] == 4576.41)
    assert pay_saved["transaction_type"] == "payment"


def test_upload_bank_ofx_to_invoice_flow_is_blocked(client, db):
    user = create_user(db, "ccofx4@test.com", "x", "U")
    h = _auth(user.email)

    res = client.post(
        "/api/upload",
        data={"import_kind": "credit_card_invoice"},
        files={"file": ("extrato.ofx", BANK_OFX.encode("utf-8"), "application/x-ofx")},
        headers=h,
    )
    assert res.status_code == 422, res.text
    assert "extrato" in res.json()["detail"].lower()


def test_upload_card_ofx_to_statement_flow_is_blocked(client, db):
    user = create_user(db, "ccofx5@test.com", "x", "U")
    h = _auth(user.email)
    acc = _bank_account(client, h)

    res = client.post(
        "/api/upload",
        data={"import_kind": "bank_statement", "bank_account_id": str(acc["id"])},
        files={"file": ("fatura.ofx", CC_OFX.encode("utf-8"), "application/x-ofx")},
        headers=h,
    )
    assert res.status_code == 422, res.text
    assert "fatura" in res.json()["detail"].lower()
