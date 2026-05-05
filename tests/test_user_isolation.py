"""
Testes de isolamento de dados por usuário.

Garante que um usuário nunca vê dados de outro,
mesmo que as transações tenham data/valor/descrição idênticos.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services.auth_service import create_access_token, create_user

# Garante que todos os modelos são registrados no Base.metadata antes do create_all
from app import models as _models  # noqa: F401  (importa Account, Transaction, User)

# ── Banco em memória para testes ──────────────────────────────────────────────
# StaticPool: todas as conexões compartilham o mesmo banco in-memory
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


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Cria e destroi o schema a cada teste (SQLAlchemy 2.x)."""
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


# ── Fixture de transação de teste ─────────────────────────────────────────────
TX_FIXTURE = {
    "source_file": "test.pdf",
    "parser_used": "nubank_pf",
    "transactions": [
        {
            "date":                 "2026-03-15",
            "description":          "Salário",
            "raw_description":      "Salário",
            "amount":               5000.0,
            "account":              "nubank_pf",
            "is_internal_transfer": False,
            "is_payment":           False,
            "installment_current":  None,
            "installment_total":    None,
            "category":             None,
            "category_group":       None,
        }
    ],
}


def _auth_header(email: str) -> dict:
    token = create_access_token({"sub": email})
    return {"Authorization": f"Bearer {token}"}


# ── Testes ────────────────────────────────────────────────────────────────────

class TestUserIsolation:

    def test_unauthenticated_returns_401(self, client):
        """Sem token → 401."""
        res = client.get("/api/transactions")
        assert res.status_code == 401

    def test_user_only_sees_own_transactions(self, client, db):
        """User B não vê transações de User A."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        # User A importa uma transação
        client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))

        # User A vê sua transação
        res_a = client.get("/api/transactions", headers=_auth_header(user_a.email))
        assert res_a.status_code == 200
        assert len(res_a.json()) == 1

        # User B não vê nada
        res_b = client.get("/api/transactions", headers=_auth_header(user_b.email))
        assert res_b.status_code == 200
        assert res_b.json() == []

    def test_each_user_sees_only_own_data(self, client, db):
        """User A e User B importam a mesma transação — cada um vê só a sua."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))
        client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_b.email))

        res_a = client.get("/api/transactions", headers=_auth_header(user_a.email))
        res_b = client.get("/api/transactions", headers=_auth_header(user_b.email))

        assert len(res_a.json()) == 1
        assert len(res_b.json()) == 1

    def test_dashboard_empty_for_new_user(self, client, db):
        """Dashboard de usuário sem dados retorna {}."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        # Só A tem dados
        client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))

        res = client.get("/api/dashboard/monthly", headers=_auth_header(user_b.email))
        assert res.status_code == 200
        assert res.json() == {}

    def test_dashboard_shows_only_own_data(self, client, db):
        """Dashboard de A não inclui dados de B."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        # A tem R$ 5.000, B tem R$ 9.999
        client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))

        tx_b = {**TX_FIXTURE, "transactions": [{**TX_FIXTURE["transactions"][0], "amount": 9999.0}]}
        client.post("/api/import", json=tx_b, headers=_auth_header(user_b.email))

        res_a = client.get("/api/dashboard/monthly", headers=_auth_header(user_a.email))
        data_a = res_a.json()
        assert "2026-03" in data_a
        total_a = data_a["2026-03"]["totalEntradas"]
        assert total_a == pytest.approx(5000.0)  # não inclui os R$ 9.999 de B

    def test_deduplication_is_per_user(self, client, db):
        """Mesma transação importada duas vezes pelo mesmo usuário → skipped na segunda."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")

        r1 = client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))
        r2 = client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))

        assert r1.json()["imported"] == 1
        assert r2.json()["skipped"]  == 1
        assert r2.json()["imported"] == 0

    def test_deduplication_does_not_cross_users(self, client, db):
        """Mesma transação importada por dois usuários distintos → ambos importam (sem conflito)."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        r_a = client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))
        r_b = client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_b.email))

        assert r_a.json()["imported"] == 1
        assert r_b.json()["imported"] == 1  # não foi bloqueado como duplicata

    def test_account_is_isolated_per_user(self, client, db):
        """Contas criadas para User A não são reutilizadas por User B."""
        from app.models.account import Account

        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_a.email))
        client.post("/api/import", json=TX_FIXTURE, headers=_auth_header(user_b.email))

        accounts_a = db.query(Account).filter(Account.user_id == user_a.id).all()
        accounts_b = db.query(Account).filter(Account.user_id == user_b.id).all()

        assert len(accounts_a) == 1
        assert len(accounts_b) == 1
        assert accounts_a[0].id != accounts_b[0].id  # accounts separadas
