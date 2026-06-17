import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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


def _count(table: str) -> int:
    with engine.begin() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()


class TestInstitutionDelete:
    def test_delete_empty_institution(self, client, db):
        user = create_user(db, "del1@test.com", "x", "U")
        h = _auth(user.email)
        inst = client.post("/api/institutions", json={"name": "Vazia"}, headers=h).json()

        r = client.delete(f"/api/institutions/{inst['id']}", headers=h)
        assert r.status_code == 200
        assert r.json() == {"deleted": True}
        assert client.get("/api/institutions", headers=h).json() == []

    def test_delete_cascades_accounts_cards_and_data(self, client, db):
        user = create_user(db, "del2@test.com", "x", "U")
        h = _auth(user.email)
        inst = client.post("/api/institutions", json={"name": "Nubank"}, headers=h).json()
        cat = client.post(
            "/api/categories",
            json={"name": "Mercado", "applies_to_bank": True, "applies_to_credit_card": True},
            headers=h,
        ).json()
        acc = client.post(
            "/api/bank-accounts",
            json={"name": "PF", "account_type": "checking", "institution_id": inst["id"]},
            headers=h,
        ).json()
        client.post(
            "/api/cards",
            json={"name": "Platinum", "closing_day": 25, "due_day": 5, "institution_id": inst["id"]},
            headers=h,
        )
        client.post(
            "/api/transactions",
            json={
                "transaction_type": "expense",
                "amount": -50,
                "transaction_date": "2026-06-01",
                "description": "Compra",
                "bank_account_id": acc["id"],
                "category_id": cat["id"],
            },
            headers=h,
        )

        assert _count("bank_accounts") == 1
        assert _count("credit_cards") == 1
        assert _count("transactions") == 1

        r = client.delete(f"/api/institutions/{inst['id']}", headers=h)
        assert r.status_code == 200

        assert _count("institutions") == 0
        assert _count("bank_accounts") == 0
        assert _count("credit_cards") == 0
        assert _count("transactions") == 0
        assert _count("categories") == 1

        assert client.get("/api/bank-accounts", headers=h).json() == []
        assert client.get("/api/cards", headers=h).json() == []

    def test_delete_not_found(self, client, db):
        user = create_user(db, "del3@test.com", "x", "U")
        r = client.delete("/api/institutions/999", headers=_auth(user.email))
        assert r.status_code == 404

    def test_delete_other_user_forbidden(self, client, db):
        owner = create_user(db, "del4@test.com", "x", "Owner")
        other = create_user(db, "del5@test.com", "x", "Other")
        inst = client.post("/api/institutions", json={"name": "Itaú"}, headers=_auth(owner.email)).json()

        r = client.delete(f"/api/institutions/{inst['id']}", headers=_auth(other.email))
        assert r.status_code == 404
        assert len(client.get("/api/institutions", headers=_auth(owner.email)).json()) == 1
