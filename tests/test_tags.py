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


def _tx(db, user_id: int, card_id: int, description: str = "Amazon") -> Transaction:
    inv = Invoice(user_id=user_id, card_id=card_id, due_month="2026-05", total_amount=100.0)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    tx = Transaction(
        user_id=user_id,
        date=date(2026, 5, 10),
        description=description,
        amount=-50.0,
        card_id=card_id,
        invoice_id=inv.id,
        imported_at=datetime(2026, 5, 10),
        is_internal_transfer=False,
        is_payment=False,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx, inv


class TestTags:
    def test_set_tags_creates_and_lists(self, client, db):
        user = create_user(db, "t1@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        tx, _ = _tx(db, user.id, card["id"])

        res = client.put(f"/api/transactions/{tx.id}/tags", json={"names": ["Casa", "Presente"]}, headers=h)
        assert res.status_code == 200
        names = [t["name"] for t in res.json()]
        assert names == ["Casa", "Presente"]

        listed = client.get("/api/tags", headers=h).json()
        assert sorted(t["name"] for t in listed) == ["Casa", "Presente"]

    def test_normalization_dedup(self, client, db):
        user = create_user(db, "t2@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        tx, _ = _tx(db, user.id, card["id"])

        res = client.put(
            f"/api/transactions/{tx.id}/tags",
            json={"names": ["Casa", " casa ", "CASA", "  Casa  Nova "]},
            headers=h,
        )
        body = res.json()
        assert [t["name"] for t in body] == ["Casa", "Casa Nova"]
        assert len(client.get("/api/tags", headers=h).json()) == 2

    def test_reuse_existing_tag_across_transactions(self, client, db):
        user = create_user(db, "t3@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        tx1, _ = _tx(db, user.id, card["id"], "Compra 1")
        tx2, _ = _tx(db, user.id, card["id"], "Compra 2")

        id1 = client.put(f"/api/transactions/{tx1.id}/tags", json={"names": ["Casa"]}, headers=h).json()[0]["id"]
        id2 = client.put(f"/api/transactions/{tx2.id}/tags", json={"names": ["casa"]}, headers=h).json()[0]["id"]
        assert id1 == id2
        assert len(client.get("/api/tags", headers=h).json()) == 1

    def test_remove_all_tags(self, client, db):
        user = create_user(db, "t4@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        tx, _ = _tx(db, user.id, card["id"])

        client.put(f"/api/transactions/{tx.id}/tags", json={"names": ["Casa"]}, headers=h)
        res = client.put(f"/api/transactions/{tx.id}/tags", json={"names": []}, headers=h)
        assert res.status_code == 200
        assert res.json() == []
        # a tag continua existindo para reuso
        assert len(client.get("/api/tags", headers=h).json()) == 1

    def test_tags_returned_in_invoice_detail(self, client, db):
        user = create_user(db, "t5@test.com", "x", "U")
        h = _auth(user.email)
        card = _card(client, h)
        tx, inv = _tx(db, user.id, card["id"])

        client.put(f"/api/transactions/{tx.id}/tags", json={"names": ["Casa"]}, headers=h)
        detail = client.get(f"/api/cards/{card['id']}/invoices/{inv.id}", headers=h).json()
        target = next(t for t in detail["transactions"] if t["id"] == tx.id)
        assert [t["name"] for t in target["tags"]] == ["Casa"]

    def test_user_isolation(self, client, db):
        owner = create_user(db, "owner@test.com", "x", "O")
        other = create_user(db, "other@test.com", "x", "X")
        ho, hx = _auth(owner.email), _auth(other.email)
        card = _card(client, ho)
        tx, _ = _tx(db, owner.id, card["id"])

        client.put(f"/api/transactions/{tx.id}/tags", json={"names": ["Casa"]}, headers=ho)

        # outro usuário não enxerga a tag nem consegue taguear o lançamento alheio
        assert client.get("/api/tags", headers=hx).json() == []
        assert client.put(f"/api/transactions/{tx.id}/tags", json={"names": ["Hack"]}, headers=hx).status_code == 404
