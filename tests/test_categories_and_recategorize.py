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
        """Compra parcelada bloqueia recategorização e preserva os campos de parcela.

        Após Feature 1 (bloqueio de categoria em sistêmicos), o PATCH com category_id
        em uma parcelada retorna 400. installment_current/installment_total continuam
        preservados — não são alterados pelo endpoint."""
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

        # Tentar recategorizar — agora bloqueado para sistêmicos
        patch_res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id},
            headers=headers,
        )
        assert patch_res.status_code == 400

        # Os campos de parcela permanecem intactos no banco
        tx_after = client.get("/api/transactions", headers=headers).json()[0]
        assert tx_after["installment_current"] == 2
        assert tx_after["installment_total"] == 4
        assert tx_after["category_id"] is None


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


# ═════════════════════════════════════════════════════════════════════════════
# TESTES DE BLOQUEIO DE CATEGORIA EM LANÇAMENTOS SISTÊMICOS (Feature 1)
# ═════════════════════════════════════════════════════════════════════════════

def _payment_tx_fixture(card_id: int, due_month: str):
    return {
        "source_file": "fatura.pdf",
        "parser_used": "faturacartaonubank",
        "card_id": card_id,
        "invoice": {"due_month": due_month},
        "transactions": [
            {
                "date": "2026-03-11",
                "description": "Pagamento em 11 MAR",
                "raw_description": "Pagamento em 11 MAR",
                "amount": 8615.00,
                "account": "nubank_cartao",
                "is_internal_transfer": False,
                "is_payment": True,
                "installment_current": None,
                "installment_total": None,
                "category": None,
                "category_id": None,
                "category_group": None,
            }
        ],
    }


class TestSystemicCategoryBlock:
    """Compras parceladas e pagamentos da fatura não recebem category_id."""

    def _create_card(self, client, headers):
        res = client.post(
            "/api/cards",
            json={"name": "Nubank", "institution": "Nubank", "closing_day": 4, "due_day": 13},
            headers=headers,
        )
        return res.json()["id"]

    def _create_category(self, client, headers):
        res = client.post(
            "/api/categories",
            json={"name": "Compras", "scope": "credit_card"},
            headers=headers,
        )
        return res.json()["id"]

    def test_import_strips_category_id_from_installment(self, client, db):
        """Compra parcelada com category_id no payload é salva com category_id=null."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)
        cat_id = self._create_category(client, headers)

        payload = _card_tx_fixture(card_id, "2026-04", installment_current=2, installment_total=4)
        payload["transactions"][0]["category_id"] = cat_id  # tenta forçar categoria

        import_res = client.post("/api/import", json=payload, headers=headers)
        assert import_res.status_code == 200

        tx_list = client.get("/api/transactions", headers=headers).json()
        assert len(tx_list) == 1
        assert tx_list[0]["category_id"] is None
        assert tx_list[0]["category"] is None
        # Mas os campos de parcela são preservados
        assert tx_list[0]["installment_current"] == 2
        assert tx_list[0]["installment_total"] == 4

    def test_import_strips_category_id_from_payment(self, client, db):
        """Pagamento da fatura com category_id no payload é salvo com category_id=null."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)
        cat_id = self._create_category(client, headers)

        payload = _payment_tx_fixture(card_id, "2026-04")
        payload["transactions"][0]["category_id"] = cat_id

        import_res = client.post("/api/import", json=payload, headers=headers)
        assert import_res.status_code == 200

        tx_list = client.get("/api/transactions", headers=headers).json()
        assert tx_list[0]["category_id"] is None
        assert tx_list[0]["category"] is None
        assert tx_list[0]["is_payment"] is True

    def test_patch_rejects_category_on_installment(self, client, db):
        """PATCH /api/transactions/{id} rejeita category_id em parcelada."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)
        cat_id = self._create_category(client, headers)

        # Importa parcelada
        payload = _card_tx_fixture(card_id, "2026-04", installment_current=2, installment_total=4)
        client.post("/api/import", json=payload, headers=headers)
        tx_id = client.get("/api/transactions", headers=headers).json()[0]["id"]

        res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id},
            headers=headers,
        )
        assert res.status_code == 400
        assert "sistêmico" in res.json()["detail"].lower()

    def test_patch_rejects_category_on_payment(self, client, db):
        """PATCH /api/transactions/{id} rejeita category_id em pagamento da fatura."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)
        cat_id = self._create_category(client, headers)

        client.post("/api/import", json=_payment_tx_fixture(card_id, "2026-04"), headers=headers)
        tx_id = client.get("/api/transactions", headers=headers).json()[0]["id"]

        res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id},
            headers=headers,
        )
        assert res.status_code == 400

    def test_patch_allows_description_on_installment(self, client, db):
        """PATCH continua permitindo editar descrição em parcelada."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)

        payload = _card_tx_fixture(card_id, "2026-04", installment_current=2, installment_total=4)
        client.post("/api/import", json=payload, headers=headers)
        tx_id = client.get("/api/transactions", headers=headers).json()[0]["id"]

        res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"description": "Amazon Brasil"},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["description"] == "Amazon Brasil"

    def test_single_installment_is_not_systemic(self, client, db):
        """installment_total=1 NÃO é compra parcelada — categoria deve funcionar."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)
        cat_id = self._create_category(client, headers)

        payload = _card_tx_fixture(card_id, "2026-04", installment_current=1, installment_total=1)
        payload["transactions"][0]["category_id"] = cat_id

        client.post("/api/import", json=payload, headers=headers)
        tx_list = client.get("/api/transactions", headers=headers).json()
        assert tx_list[0]["category_id"] == cat_id

    def test_regular_transaction_recategorize_still_works(self, client, db):
        """Lançamento comum continua aceitando recategorização."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)
        cat_id = self._create_category(client, headers)

        payload = _card_tx_fixture(card_id, "2026-04")  # sem parcelas
        client.post("/api/import", json=payload, headers=headers)
        tx_id = client.get("/api/transactions", headers=headers).json()[0]["id"]

        res = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": cat_id},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["category_id"] == cat_id


# ═════════════════════════════════════════════════════════════════════════════
# TESTES DO DASHBOARD DO CARTÃO (Feature 3)
# ═════════════════════════════════════════════════════════════════════════════

class TestCardDashboard:

    def _create_card(self, client, headers):
        res = client.post(
            "/api/cards",
            json={"name": "Nubank", "institution": "Nubank", "closing_day": 4, "due_day": 13},
            headers=headers,
        )
        return res.json()["id"]

    def test_dashboard_empty_when_no_invoices(self, client, db):
        """Dashboard sem faturas retorna estrutura vazia."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)

        res = client.get(f"/api/cards/{card_id}/dashboard", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["card_id"] == card_id
        assert data["invoice_count"] == 0
        assert data["latest_invoice"] is None
        assert data["highest_invoice"] is None
        assert data["monthly_average"] == 0
        assert data["future_installments_total"] == 0
        assert data["recent_invoices"] == []

    def test_dashboard_with_one_invoice(self, client, db):
        """Dashboard agrega corretamente com uma fatura."""
        user = create_user(db, "a@test.com", "senha123", "User A")
        headers = _auth(user.email)
        card_id = self._create_card(client, headers)

        payload = _card_tx_fixture(card_id, "2026-04", installment_current=2, installment_total=4)
        payload["invoice"]["total_amount"] = 1000.0
        client.post("/api/import", json=payload, headers=headers)

        res = client.get(f"/api/cards/{card_id}/dashboard", headers=headers)
        data = res.json()
        assert data["invoice_count"] == 1
        assert data["latest_invoice"]["due_month"] == "2026-04"
        assert data["monthly_average"] == 1000.0
        # Parcelas futuras: 60.72 * (4 - 2) = 121.44
        assert data["future_installments_total"] == 121.44

    def test_dashboard_isolates_by_user(self, client, db):
        """Dashboard de outro usuário retorna 404."""
        user_a = create_user(db, "a@test.com", "senha123", "User A")
        user_b = create_user(db, "b@test.com", "senha123", "User B")
        card_id = self._create_card(client, _auth(user_a.email))

        # User B tenta acessar o cartão de User A
        res = client.get(f"/api/cards/{card_id}/dashboard", headers=_auth(user_b.email))
        assert res.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# TESTES DE EVOLUÇÃO DE CATEGORIAS — card_id, parent_id, invoice_budget_limit
# ═════════════════════════════════════════════════════════════════════════════

class TestCategoryEvolution:
    """Cobre card_id (Feature 2), invoice_budget_limit (Feature 3), parent_id (Feature 4)."""

    def _create_card(self, client, headers, name="Nubank Platinum"):
        res = client.post("/api/cards", json={
            "name": name, "institution": "Nubank", "closing_day": 4, "due_day": 13,
        }, headers=headers)
        assert res.status_code == 200, res.text
        return res.json()["id"]

    # ── Feature 2: card_id ───────────────────────────────────────────────────

    def test_create_global_category_card_id_null(self, client, db):
        """Categoria sem card_id é global (todos os cartões)."""
        user = create_user(db, "u@test.com", "x", "U")
        res = client.post("/api/categories", json={
            "name": "Alimentação", "scope": "credit_card",
        }, headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["card_id"] is None

    def test_create_category_with_specific_card(self, client, db):
        """Categoria pode ser criada para um cartão específico."""
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        cid = self._create_card(client, headers)
        res = client.post("/api/categories", json={
            "name": "Reembolso", "scope": "credit_card", "card_id": cid,
        }, headers=headers)
        assert res.status_code == 200
        assert res.json()["card_id"] == cid

    def test_reject_card_of_another_user(self, client, db):
        """Não pode vincular categoria a cartão de outro usuário."""
        user_a = create_user(db, "a@test.com", "x", "A")
        user_b = create_user(db, "b@test.com", "x", "B")
        cid_a = self._create_card(client, _auth(user_a.email))
        res = client.post("/api/categories", json={
            "name": "Hack", "scope": "credit_card", "card_id": cid_a,
        }, headers=_auth(user_b.email))
        assert res.status_code == 404

    def test_list_filtered_by_card_returns_global_and_card_specific(self, client, db):
        """GET /categories?card_id=N retorna globais + específicas do cartão."""
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        c_a = self._create_card(client, headers, "Cartão A")
        c_b = self._create_card(client, headers, "Cartão B")
        # Global, exclusiva A, exclusiva B
        client.post("/api/categories", json={"name": "Global", "scope": "credit_card"}, headers=headers)
        client.post("/api/categories", json={"name": "OnlyA", "scope": "credit_card", "card_id": c_a}, headers=headers)
        client.post("/api/categories", json={"name": "OnlyB", "scope": "credit_card", "card_id": c_b}, headers=headers)

        res = client.get(f"/api/categories?scope=credit_card&card_id={c_a}", headers=headers)
        assert res.status_code == 200
        names = sorted(c["name"] for c in res.json())
        assert names == ["Global", "OnlyA"]

    def test_update_category_card_id_clear_with_zero(self, client, db):
        """PATCH com card_id=0 limpa o card (vira global)."""
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        cid = self._create_card(client, headers)
        cat = client.post("/api/categories", json={
            "name": "X", "scope": "credit_card", "card_id": cid,
        }, headers=headers).json()
        res = client.patch(f"/api/categories/{cat['id']}", json={"card_id": 0}, headers=headers)
        assert res.status_code == 200
        assert res.json()["card_id"] is None

    # ── Feature 3: invoice_budget_limit ──────────────────────────────────────

    def test_create_with_invoice_budget_limit(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.post("/api/categories", json={
            "name": "Aliment", "scope": "credit_card", "invoice_budget_limit": 1000.0,
        }, headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["invoice_budget_limit"] == 1000.0

    def test_reject_zero_or_negative_budget_on_create(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.post("/api/categories", json={
            "name": "Aliment", "scope": "credit_card", "invoice_budget_limit": 0,
        }, headers=_auth(user.email))
        assert res.status_code == 422

    def test_remove_budget_with_zero_on_update(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        cat = client.post("/api/categories", json={
            "name": "Aliment", "scope": "credit_card", "invoice_budget_limit": 500.0,
        }, headers=_auth(user.email)).json()
        res = client.patch(f"/api/categories/{cat['id']}",
                           json={"invoice_budget_limit": 0}, headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["invoice_budget_limit"] is None

    # ── Feature 4: subcategorias ─────────────────────────────────────────────

    def test_create_subcategory(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        parent = client.post("/api/categories", json={
            "name": "Alimentação", "scope": "credit_card",
        }, headers=headers).json()
        res = client.post("/api/categories", json={
            "name": "Mercado", "scope": "credit_card", "parent_id": parent["id"],
        }, headers=headers)
        assert res.status_code == 200
        assert res.json()["parent_id"] == parent["id"]

    def test_reject_subcategory_of_subcategory(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        parent = client.post("/api/categories", json={"name": "P", "scope": "credit_card"}, headers=headers).json()
        sub = client.post("/api/categories", json={
            "name": "S", "scope": "credit_card", "parent_id": parent["id"],
        }, headers=headers).json()
        res = client.post("/api/categories", json={
            "name": "SS", "scope": "credit_card", "parent_id": sub["id"],
        }, headers=headers)
        assert res.status_code == 400
        assert "subcategoria" in res.json()["detail"].lower()

    def test_reject_parent_of_another_user(self, client, db):
        user_a = create_user(db, "a@test.com", "x", "A")
        user_b = create_user(db, "b@test.com", "x", "B")
        parent = client.post("/api/categories", json={
            "name": "Pa", "scope": "credit_card",
        }, headers=_auth(user_a.email)).json()
        res = client.post("/api/categories", json={
            "name": "Sub", "scope": "credit_card", "parent_id": parent["id"],
        }, headers=_auth(user_b.email))
        assert res.status_code == 404

    def test_subcategory_inherits_parent_card_id(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        cid = self._create_card(client, headers)
        parent = client.post("/api/categories", json={
            "name": "P", "scope": "credit_card", "card_id": cid,
        }, headers=headers).json()
        sub = client.post("/api/categories", json={
            "name": "S", "scope": "credit_card", "parent_id": parent["id"],
        }, headers=headers).json()
        assert sub["card_id"] == cid

    def test_reject_subcategory_card_diff_from_parent(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        c_a = self._create_card(client, headers, "A")
        c_b = self._create_card(client, headers, "B")
        parent = client.post("/api/categories", json={
            "name": "P", "scope": "credit_card", "card_id": c_a,
        }, headers=headers).json()
        res = client.post("/api/categories", json={
            "name": "S", "scope": "credit_card", "parent_id": parent["id"], "card_id": c_b,
        }, headers=headers)
        assert res.status_code == 400

    # ── Feature 5: validação de category_id por card na importação/PATCH ─────

    def test_import_rejects_category_of_other_card(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        c_a = self._create_card(client, headers, "A")
        c_b = self._create_card(client, headers, "B")
        cat_b = client.post("/api/categories", json={
            "name": "OnlyB", "scope": "credit_card", "card_id": c_b,
        }, headers=headers).json()
        # Tenta importar fatura no cartão A com categoria do cartão B
        payload = _card_tx_fixture(c_a, "2026-04")
        payload["transactions"][0]["category_id"] = cat_b["id"]
        res = client.post("/api/import", json=payload, headers=headers)
        assert res.status_code == 400
        assert "cartão" in res.json()["detail"].lower()

    def test_patch_transaction_rejects_category_of_other_card(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        c_a = self._create_card(client, headers, "A")
        c_b = self._create_card(client, headers, "B")
        # Importa transaction comum no cartão A
        res = client.post("/api/import", json=_card_tx_fixture(c_a, "2026-04"), headers=headers)
        assert res.status_code == 200
        tx_id = client.get(
            f"/api/transactions/invoice?invoice_id={res.json()['invoice_id']}",
            headers=headers,
        ).json()["transactions"][0]["id"]
        # Cria categoria exclusiva do cartão B
        cat_b = client.post("/api/categories", json={
            "name": "OnlyB", "scope": "credit_card", "card_id": c_b,
        }, headers=headers).json()
        # PATCH na transaction do cartão A tentando usar categoria do B
        res = client.patch(f"/api/transactions/{tx_id}",
                           json={"category_id": cat_b["id"]}, headers=headers)
        assert res.status_code == 400

    def test_import_accepts_global_category(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        cid = self._create_card(client, headers)
        cat = client.post("/api/categories", json={
            "name": "Aliment", "scope": "credit_card",
        }, headers=headers).json()
        payload = _card_tx_fixture(cid, "2026-04")
        payload["transactions"][0]["category_id"] = cat["id"]
        res = client.post("/api/import", json=payload, headers=headers)
        assert res.status_code == 200

    def test_invoice_detail_transaction_includes_hierarchical_category(self, client, db):
        """GET /cards/{id}/invoices/{invoice_id} enriquece a transação com label pai/filha e limite."""
        user = create_user(db, "u@test.com", "x", "U")
        headers = _auth(user.email)
        cid = self._create_card(client, headers)
        parent = client.post("/api/categories", json={
            "name": "Alimentação", "scope": "credit_card",
        }, headers=headers).json()
        sub = client.post("/api/categories", json={
            "name": "Mercado",
            "scope": "credit_card",
            "parent_id": parent["id"],
            "invoice_budget_limit": 500.0,
            "icon": "shopping-cart",
        }, headers=headers).json()
        payload = _card_tx_fixture(cid, "2026-04")
        payload["transactions"][0]["category_id"] = sub["id"]
        import_res = client.post("/api/import", json=payload, headers=headers)
        assert import_res.status_code == 200
        inv_id = import_res.json()["invoice_id"]
        detail = client.get(f"/api/cards/{cid}/invoices/{inv_id}", headers=headers)
        assert detail.status_code == 200
        tx0 = detail.json()["transactions"][0]
        assert tx0["category_display_label"] == "Alimentação / Mercado"
        assert tx0["category_parent_name"] == "Alimentação"
        assert tx0["category_parent_id"] == parent["id"]
        assert tx0["category_invoice_budget_limit"] == 500.0
        assert tx0["category_icon"] == "shopping-cart"
