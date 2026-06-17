import importlib.util
from pathlib import Path

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

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "l2m3n4o5p6q7_merge_heads_backfill_institution_id.py"
)
_spec = importlib.util.spec_from_file_location("backfill_migration", _MIGRATION_PATH)
backfill_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_migration)


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


def _run_backfill():
    with engine.begin() as conn:
        backfill_migration._backfill(conn)


class TestInstitutionBackfill:
    def test_backfills_links_from_string(self, client, db):
        user = create_user(db, "bf1@test.com", "x", "U")
        h = _auth(user.email)

        acc1 = client.post("/api/bank-accounts", json={"name": "PF", "institution": "Nubank", "account_type": "checking"}, headers=h).json()
        acc2 = client.post("/api/bank-accounts", json={"name": "PJ", "institution": "Nubank", "account_type": "business"}, headers=h).json()
        card = client.post("/api/cards", json={"name": "Platinum", "institution": "Itaú", "closing_day": 25, "due_day": 5}, headers=h).json()

        assert acc1["institution_id"] is None
        assert card["institution_id"] is None

        _run_backfill()

        institutions = {i["name"]: i["id"] for i in client.get("/api/institutions", headers=h).json()}
        assert set(institutions) == {"Nubank", "Itaú"}

        accounts = {a["id"]: a["institution_id"] for a in client.get("/api/bank-accounts", headers=h).json()}
        assert accounts[acc1["id"]] == institutions["Nubank"]
        assert accounts[acc2["id"]] == institutions["Nubank"]

        cards = {c["id"]: c["institution_id"] for c in client.get("/api/cards", headers=h).json()}
        assert cards[card["id"]] == institutions["Itaú"]

    def test_is_idempotent_and_per_user(self, client, db):
        u1 = create_user(db, "bf2@test.com", "x", "U1")
        u2 = create_user(db, "bf3@test.com", "x", "U2")
        h1, h2 = _auth(u1.email), _auth(u2.email)

        client.post("/api/bank-accounts", json={"name": "A", "institution": "Nubank", "account_type": "checking"}, headers=h1)
        client.post("/api/bank-accounts", json={"name": "B", "institution": "Nubank", "account_type": "checking"}, headers=h2)

        _run_backfill()
        _run_backfill()

        with engine.begin() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM institutions")).scalar()
        assert total == 2

        i1 = client.get("/api/institutions", headers=h1).json()
        i2 = client.get("/api/institutions", headers=h2).json()
        assert len(i1) == 1 and len(i2) == 1
        assert i1[0]["id"] != i2[0]["id"]

    def test_ignores_blank_institution(self, client, db):
        user = create_user(db, "bf4@test.com", "x", "U")
        h = _auth(user.email)
        client.post("/api/bank-accounts", json={"name": "Sem banco", "account_type": "checking"}, headers=h)

        _run_backfill()

        assert client.get("/api/institutions", headers=h).json() == []
        acc = client.get("/api/bank-accounts", headers=h).json()[0]
        assert acc["institution_id"] is None
