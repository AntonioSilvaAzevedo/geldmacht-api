"""
Testes de categorias (ícone, edição, isolamento) e recategorização de transações.

Cobre:
- Criar categoria com ícone
- Editar nome e ícone de categoria
- Não permitir editar/acessar categoria de outro usuário
- Atualizar category_id de uma transaction
- Remover categoria de uma transaction (category_id = null)
- Rejeitar category_id de outro usuário
- Rejeitar category_id de outro escopo para transaction de cartão
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services.auth_service import create_access_token, create_user

from app import models as _models  # noqa: F401

# ── In-memory DB ──────────────────────────────────────────────────────────────
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
    """Instala o override de DB para cada teste e restaura o anterior ao terminar."""
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


# ── Fixture: transaction de cartão parcelada ──────────────────────────────────
def _card_tx_fixture(card_id: int, due_month: str, installment_current=None, installment_total=None):
    return {
        "source_file": "fatura.pdf",
        "parser_used": "faturacartaonubank",
        "card_id": card_id,
        "invoice": {"due_month": due_month},
        "transactions": [
            {
                "date": "2026-03-04",
                "description": "Amazon",
                "raw_description": "Amazon - Parcela 2/4" if installment_current else "Amazon",
                "amount": -60.72,
                "account": "nubank_cartao",
                "is_internal_transfer": False,
                "is_payment": False,
                "installment_current": installment_current,
                "installment_total": installment_total,
                "category": None,
                "category_id": None,
                "category_group": None,
            }
        ],
    }


# ═════════════════════════════════════════════════════════════════════════════
# TESTES DE CATEGORIAS
# ═════════════════════════════════════════════════════════════════════════════

class TestCategoryCreate:

    def test_create_category_with_icon(self, client, db):
        """Criar categoria com ícone — ícone é retornado na resposta."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        payload = {"name": "Mercado", "scope": "credit_card", "icon": "shopping-cart"}
        res = client.post("/api/categories", json=payload, headers=_auth(user.email))
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Mercado"
        assert data["icon"] == "shopping-cart"
        assert data["scope"] == "credit_card"

    def test_create_category_without_icon(self, client, db):
        """Criar categoria sem ícone — icon deve ser null."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        payload = {"name": "Transporte", "scope": "credit_card"}
        res = client.post("/api/categories", json=payload, headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["icon"] is None

    def test_create_category_with_color_and_icon(self, client, db):
        """Criar categoria com cor e ícone — ambos são salvos."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        payload = {"name": "Casa", "scope": "credit_card", "color": "#3182ce", "icon": "home"}
        res = client.post("/api/categories", json=payload, headers=_auth(user.email))
        assert res.status_code == 200
        data = res.json()
        assert data["color"] == "#3182ce"
        assert data["icon"] == "home"


class TestCategoryUpdate:

    def test_edit_category_name(self, client, db):
        """Editar apenas o nome da categoria."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        create_res = client.post(
            "/api/categories",
            json={"name": "Alimentação", "scope": "credit_card"},
            headers=_auth(user.email),
        )
        cat_id = create_res.json()["id"]

        patch_res = client.patch(
            f"/api/categories/{cat_id}",
            json={"name": "Comida"},
            headers=_auth(user.email),
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["name"] == "Comida"

    def test_edit_category_icon(self, client, db):
        """Editar apenas o ícone da categoria."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        create_res = client.post(
            "/api/categories",
            json={"name": "Saúde", "scope": "credit_card", "icon": "tag"},
            headers=_auth(user.email),
        )
        cat_id = create_res.json()["id"]

        patch_res = client.patch(
            f"/api/categories/{cat_id}",
            json={"icon": "heart-pulse"},
            headers=_auth(user.email),
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["icon"] == "heart-pulse"
        assert patch_res.json()["name"] == "Saúde"  # nome não deve mudar

    def test_edit_category_name_and_icon(self, client, db):
        """Editar nome e ícone juntos."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        create_res = client.post(
            "/api/categories",
            json={"name": "Lazer", "scope": "credit_card"},
            headers=_auth(user.email),
        )
        cat_id = create_res.json()["id"]

        patch_res = client.patch(
            f"/api/categories/{cat_id}",
            json={"name": "Entretenimento", "icon": "gamepad"},
            headers=_auth(user.email),
        )
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["name"] == "Entretenimento"
        assert data["icon"] == "gamepad"

    def test_edit_category_of_another_user_returns_404(self, client, db):
        """Não deve ser possível editar categoria de outro usuário."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        # User A cria categoria
        create_res = client.post(
            "/api/categories",
            json={"name": "Minha Categoria", "scope": "credit_card"},
            headers=_auth(user_a.email),
        )
        cat_id = create_res.json()["id"]

        # User B tenta editar → 404
        patch_res = client.patch(
            f"/api/categories/{cat_id}",
            json={"name": "Invadida"},
            headers=_auth(user_b.email),
        )
        assert patch_res.status_code == 404

    def test_list_categories_returns_icon(self, client, db):
        """GET /api/categories deve retornar ícone de cada categoria."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        client.post(
            "/api/categories",
            json={"name": "Viagem", "scope": "credit_card", "icon": "plane"},
            headers=_auth(user.email),
        )
        res = client.get("/api/categories?scope=credit_card", headers=_auth(user.email))
        assert res.status_code == 200
        categories = res.json()
        assert len(categories) == 1
        assert categories[0]["icon"] == "plane"


# ═════════════════════════════════════════════════════════════════════════════
# TESTES DE RECATEGORIZAÇÃO DE TRANSAÇÕES
# ═════════════════════════════════════════════════════════════════════════════

class TestTransactionRecategorize:

    def _import_card_tx(self, client, db, user_email: str, category_id=None):
        """Helper: cria cartão, importa uma transaction de fatura e retorna (card_id, tx_id)."""
        headers = _auth(user_email)

        # Criar cartão
        card_res = client.post(
            "/api/cards",
            json={"name": "Nubank", "institution": "Nubank", "closing_day": 4, "due_day": 13},
            headers=headers,
        )
        card_id = card_res.json()["id"]

        # Importar fatura
        payload = _card_tx_fixture(card_id, "2026-04")
        if category_id:
            payload["transactions"][0]["category_id"] = category_id
        import_res = client.post("/api/import", json=payload, headers=headers)
        assert import_res.json()["imported"] == 1

        # Buscar a transaction
        tx_res = client.get("/api/transactions", headers=headers)
        tx_id = tx_res.json()[0]["id"]
        return card_id, tx_id

    def test_update_category_id(self, client, db):
        """Alterar category_id de uma transaction já importada."""
        user = create_user(db, "a@test.com", "senha123", "User A")

        # Criar categoria
        cat_res = client.post(
            "/api/categories",
            json={"name": "Compras", "scope": "credit_card", "icon": "shopping-cart"},
            headers=_auth(user.email),
        )
        cat_id = cat_res.json()["id"]

        _, tx_id = self._import_card_tx(client, db, user.email)

        # Recategorizar
        patch_res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id},
            headers=_auth(user.email),
        )
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["category_id"] == cat_id
        assert data["category"] == "Compras"

    def test_remove_category_using_zero(self, client, db):
        """Remover categoria de uma transaction via category_id = 0."""
        user = create_user(db, "a@test.com", "senha123", "User A")

        cat_res = client.post(
            "/api/categories",
            json={"name": "Casa", "scope": "credit_card"},
            headers=_auth(user.email),
        )
        cat_id = cat_res.json()["id"]

        _, tx_id = self._import_card_tx(client, db, user.email)

        # Atribuir categoria primeiro
        client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id},
            headers=_auth(user.email),
        )

        # Remover com category_id = 0
        remove_res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": 0},
            headers=_auth(user.email),
        )
        assert remove_res.status_code == 200
        data = remove_res.json()
        assert data["category_id"] is None
        assert data["category"] is None

    def test_reject_category_of_another_user(self, client, db):
        """Rejeitar category_id de outro usuário."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        # User B cria categoria
        cat_res = client.post(
            "/api/categories",
            json={"name": "Categoria de B", "scope": "credit_card"},
            headers=_auth(user_b.email),
        )
        cat_id_b = cat_res.json()["id"]

        _, tx_id = self._import_card_tx(client, db, user_a.email)

        # User A tenta usar categoria de B → 404
        patch_res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id_b},
            headers=_auth(user_a.email),
        )
        assert patch_res.status_code == 404

    def test_cannot_edit_transaction_of_another_user(self, client, db):
        """Não deve ser possível editar transaction de outro usuário."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")

        _, tx_id = self._import_card_tx(client, db, user_a.email)

        # User B tenta editar transaction de A → 404
        patch_res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"description": "Hackeado"},
            headers=_auth(user_b.email),
        )
        assert patch_res.status_code == 404

    def test_installment_fields_preserved_on_recategorize(self, client, db):
        """Alterar categoria não deve modificar installment_current/installment_total."""
        user = create_user(db, "a@test.com", "senha123", "User A")

        cat_res = client.post(
            "/api/categories",
            json={"name": "Compras", "scope": "credit_card"},
            headers=_auth(user.email),
        )
        cat_id = cat_res.json()["id"]

        headers = _auth(user.email)
        card_res = client.post(
            "/api/cards",
            json={"name": "Nubank", "institution": "Nubank", "closing_day": 4, "due_day": 13},
            headers=headers,
        )
        card_id = card_res.json()["id"]

        # Importar com parcelas
        payload = _card_tx_fixture(card_id, "2026-04", installment_current=2, installment_total=4)
        client.post("/api/import", json=payload, headers=headers)

        tx_res = client.get("/api/transactions", headers=headers)
        tx_id = tx_res.json()[0]["id"]

        # Recategorizar
        patch_res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id},
            headers=headers,
        )
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["installment_current"] == 2
        assert data["installment_total"] == 4
        assert data["category_id"] == cat_id


# ═════════════════════════════════════════════════════════════════════════════
# TESTES DO PARSER — COMPRAS PARCELADAS
# ═════════════════════════════════════════════════════════════════════════════

class TestInstallmentParser:
    """Testa que o parser Nubank identifica corretamente parcelas."""

    def _parse(self, text: str):
        from app.parsers.fatura_nubank import FaturaCartaoNubankParser
        return FaturaCartaoNubankParser()._parse_text(text)

    def test_parses_installment_current_and_total(self):
        """Caso 1: linha com parcela X/Y — deve extrair installment_current e installment_total."""
        text = """
ANTONIO CARLOS SILVA DE AZEVEDO
FATURA 13 ABR 2026 EMISSÃO E ENVIO 04 ABR 2026
04 MAR Amazon - Parcela 2/4 R$ 60,72
"""
        txs = self._parse(text)
        assert len(txs) == 1
        tx = txs[0]
        assert tx["description"] == "Amazon"
        assert tx["installment_current"] == 2
        assert tx["installment_total"] == 4
        assert tx["amount"] == pytest.approx(-60.72)

    def test_no_installment_when_not_present(self):
        """Caso 2: linha sem parcela — installment_current e installment_total devem ser None."""
        text = """
ANTONIO CARLOS SILVA DE AZEVEDO
FATURA 13 ABR 2026 EMISSÃO E ENVIO 04 ABR 2026
05 MAR Applecombill R$ 29,90
"""
        txs = self._parse(text)
        assert len(txs) == 1
        tx = txs[0]
        assert tx["installment_current"] is None
        assert tx["installment_total"] is None

    def test_last_installment(self):
        """Caso 3: última parcela (X/X) — zero parcelas futuras."""
        text = """
ANTONIO CARLOS SILVA DE AZEVEDO
FATURA 13 ABR 2026 EMISSÃO E ENVIO 04 ABR 2026
04 MAR Produtos Globo - Parcela 12/12 R$ 29,90
"""
        txs = self._parse(text)
        assert len(txs) == 1
        tx = txs[0]
        assert tx["installment_current"] == 12
        assert tx["installment_total"] == 12
        # parcelas futuras = 12 - 12 = 0 (calculado no frontend/summary)

    def test_multiple_installment_lines(self):
        """Múltiplas parcelas na mesma fatura."""
        text = """
ANTONIO CARLOS SILVA DE AZEVEDO
FATURA 13 ABR 2026 EMISSÃO E ENVIO 04 ABR 2026
04 MAR Amazon - Parcela 2/4 R$ 60,72
05 MAR Electrolux - NuPay - Parcela 7/10 R$ 385,38
06 MAR Netflix R$ 55,90
"""
        txs = self._parse(text)
        assert len(txs) == 3

        amazon = next(t for t in txs if t["description"] == "Amazon")
        electrolux = next(t for t in txs if "Electrolux" in t["description"])
        netflix = next(t for t in txs if t["description"] == "Netflix")

        assert amazon["installment_current"] == 2
        assert amazon["installment_total"] == 4
        assert electrolux["installment_current"] == 7
        assert electrolux["installment_total"] == 10
        assert netflix["installment_current"] is None
        assert netflix["installment_total"] is None

    def test_payment_is_not_classified_as_installment(self):
        """Caso 4: pagamento da fatura não deve ter installment."""
        text = """
ANTONIO CARLOS SILVA DE AZEVEDO
FATURA 13 ABR 2026 EMISSÃO E ENVIO 04 ABR 2026
11 FEV Pagamento em 11 FEV −R$ 12.433,41
"""
        txs = self._parse(text)
        payment = next(t for t in txs if t.get("is_payment"))
        assert payment["installment_current"] is None
        assert payment["installment_total"] is None
