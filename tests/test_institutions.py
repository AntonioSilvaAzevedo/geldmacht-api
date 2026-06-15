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


class TestInstitutions:
    def test_create_list_and_duplicate(self, client, db):
        user = create_user(db, "inst@test.com", "x", "U")
        h = _auth(user.email)

        r = client.post("/api/institutions", json={"name": "Nubank"}, headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Nubank"
        assert body["account_count"] == 0
        assert body["card_count"] == 0

        r = client.get("/api/institutions", headers=h)
        assert r.status_code == 200
        assert [i["name"] for i in r.json()] == ["Nubank"]

        r = client.post("/api/institutions", json={"name": "Nubank"}, headers=h)
        assert r.status_code == 409

    def test_link_account_and_card_to_institution(self, client, db):
        user = create_user(db, "link@test.com", "x", "U")
        h = _auth(user.email)

        inst_id = client.post("/api/institutions", json={"name": "Itaú"}, headers=h).json()["id"]

        r = client.post(
            "/api/bank-accounts",
            json={"name": "Conta PF", "institution_id": inst_id, "account_type": "checking"},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["institution_id"] == inst_id
        assert r.json()["institution"] == "Itaú"

        r = client.post(
            "/api/cards",
            json={"name": "Cartão", "institution_id": inst_id, "closing_day": 4, "due_day": 13},
            headers=h,
        )
        assert r.status_code == 200
        assert r.json()["institution_id"] == inst_id
        assert r.json()["institution"] == "Itaú"

        r = client.get("/api/institutions", headers=h)
        item = r.json()[0]
        assert item["account_count"] == 1
        assert item["card_count"] == 1

    def test_foreign_institution_404(self, client, db):
        u1 = create_user(db, "u1@test.com", "x", "A")
        u2 = create_user(db, "u2@test.com", "x", "B")
        inst_id = client.post("/api/institutions", json={"name": "BB"}, headers=_auth(u1.email)).json()["id"]

        r = client.post(
            "/api/cards",
            json={"name": "C", "institution_id": inst_id, "closing_day": 1, "due_day": 10},
            headers=_auth(u2.email),
        )
        assert r.status_code == 404
