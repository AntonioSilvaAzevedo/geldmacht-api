"""
Testes do fluxo de onboarding inicial do usuário.

Cobre:
- GET /onboarding/status (deve_mostrar / já visto).
- POST /onboarding/mark-seen idempotente.
- Isolamento por usuário (cada um marca o próprio).
- Não exibe novamente após marcado.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models.user import User
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


class TestOnboardingStatus:

    def test_new_user_should_see_onboarding(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.get("/api/onboarding/status", headers=_auth(user.email))
        assert res.status_code == 200
        body = res.json()
        assert body["should_show_onboarding"] is True
        assert body["onboarding_key"] == "initial_app_overview"
        assert body["seen_at"] is None

    def test_user_with_seen_does_not_see_onboarding(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        # Marca como visto
        client.post("/api/onboarding/mark-seen", headers=_auth(user.email))
        res = client.get("/api/onboarding/status", headers=_auth(user.email))
        body = res.json()
        assert body["should_show_onboarding"] is False
        assert body["seen_at"] is not None

    def test_requires_authentication(self, client):
        res = client.get("/api/onboarding/status")
        assert res.status_code in (401, 403)


class TestMarkSeen:

    def test_marks_seen_persists_in_db(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.post("/api/onboarding/mark-seen", headers=_auth(user.email))
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["seen_at"] is not None
        # Verifica DB
        db.refresh(user)
        assert user.onboarding_seen_at is not None

    def test_idempotent_keeps_first_timestamp(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        first = client.post("/api/onboarding/mark-seen", headers=_auth(user.email)).json()["seen_at"]
        second = client.post("/api/onboarding/mark-seen", headers=_auth(user.email)).json()["seen_at"]
        # Segunda chamada não atualiza o timestamp original
        assert first == second

    def test_isolated_by_user(self, client, db):
        ua = create_user(db, "a@test.com", "x", "A")
        ub = create_user(db, "b@test.com", "x", "B")
        # ua marca como visto
        client.post("/api/onboarding/mark-seen", headers=_auth(ua.email))
        # ub continua pendente
        res = client.get("/api/onboarding/status", headers=_auth(ub.email))
        assert res.json()["should_show_onboarding"] is True
        # ua já viu
        res = client.get("/api/onboarding/status", headers=_auth(ua.email))
        assert res.json()["should_show_onboarding"] is False
