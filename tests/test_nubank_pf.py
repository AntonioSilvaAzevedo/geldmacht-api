"""
Testes do Parser Nubank PF.
Usa fixtures sintéticas — não depende de extratos reais.

Para usar com extratos reais, copie para tests/fixtures/:
    NU_4365066_8_01JAN2026_31JAN2026.pdf
E adicione o teste test_parse_real_file() no final.
"""
import io
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Adiciona backend ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parsers.nubank_pf import NubankPFParser, _parse_amount, _parse_date

# ─── Fixtures ────────────────────────────────────────────────────────────────

FIXTURE_PDF_PATH = Path(__file__).parent / "fixtures" / "nubank_pf_jan2026.pdf"

SAMPLE_TEXT = """
Antonio Carlos Silva de Azevedo
CPF •••.520.120-•• Agência 0001 Conta
4365066-8
01 DE JANEIRO DE 2026 a 31 DE JANEIRO DE 2026 VALORES EM R$

05 JAN 2026 Total de entradas + 12.133,00
Transferência recebida pelo Pix ANTONIO CARLOS SILVA AZEVEDO - ITAÚ UNICLASS 10.899,00
Agência: 502 Conta: 079787-1
CAIXA ECONOMICA FEDERAL FGTS 1.234,00

Total de saídas - 3.273,31
Pagamento de boleto efetuado N N IMOVEIS LTDA 3.273,31

10 JAN 2026 Total de saídas - 3.246,52
Compra no débito BMB*COPEL 246,52
Transferência enviada pelo Pix Antonio Carlos Silva de Azevedo 3.000,00
mercado pago ip (0260) Agência: 1 Conta: 9084085

15 JAN 2026 Total de saídas - 1.058,90
Compra no débito iFood 58,90
Aplicação RDB 1.000,00

20 JAN 2026 Total de saídas - 499,90
Compra de FII HGLG11 312,50
Pagamento de boleto efetuado LIGGA 99,90
Compra no débito Mercadão de Carnes 187,40
"""


def _mock_pdf_from_text(text: str) -> bytes:
    """
    Cria um mock de bytes de PDF que, quando lido via pdfplumber,
    retorna o texto sintético.
    """
    return b"%PDF-1.4 synthetic mock"


def _make_pdfplumber_mock(text: str):
    """Cria um context manager mock que imita pdfplumber com texto fixo."""
    page_mock = MagicMock()
    page_mock.extract_text.return_value = text

    pdf_mock = MagicMock()
    pdf_mock.pages = [page_mock]
    pdf_mock.__enter__ = MagicMock(return_value=pdf_mock)
    pdf_mock.__exit__ = MagicMock(return_value=False)
    return pdf_mock


# ─── Testes de helpers ────────────────────────────────────────────────────────

class TestParseAmount:
    def test_positive_value(self):
        assert _parse_amount("R$ 10.899,00") == pytest.approx(10899.0)

    def test_negative_value(self):
        assert _parse_amount("-R$ 3.273,31") == pytest.approx(-3273.31)

    def test_positive_with_sign(self):
        assert _parse_amount("+R$ 500,00") == pytest.approx(500.0)

    def test_value_with_spaces(self):
        assert _parse_amount("- R$ 246,52") == pytest.approx(-246.52)

    def test_inline_value(self):
        assert _parse_amount("Transferência Recebida R$ 10.899,00") == pytest.approx(10899.0)

    def test_no_value(self):
        assert _parse_amount("Texto sem valor monetário") is None

    def test_cents_only(self):
        assert _parse_amount("R$ 0,50") == pytest.approx(0.5)


class TestParseDate:
    def test_jan(self):
        assert _parse_date("05", "jan", "2026") == date(2026, 1, 5)

    def test_dez(self):
        assert _parse_date("31", "dez", "2025") == date(2025, 12, 31)

    def test_case_insensitive(self):
        assert _parse_date("10", "JAN", "2026") == date(2026, 1, 10)

    def test_full_month(self):
        assert _parse_date("1", "janeiro", "2026") == date(2026, 1, 1)

    def test_invalid_month(self):
        assert _parse_date("01", "xyz", "2026") is None


# ─── Testes do parser (com mock de pdfplumber) ────────────────────────────────

class TestNubankPFParser:
    def setup_method(self):
        self.parser = NubankPFParser()

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_can_parse_nubank_pf(self, mock_pdfplumber):
        """Deve retornar True para extrato com identifiers corretos."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        assert self.parser.can_parse(b"fake pdf bytes") is True

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_cannot_parse_other_bank(self, mock_pdfplumber):
        """Deve retornar False para PDF sem identificadores do Nubank PF."""
        other_bank_text = "Banco do Brasil\nAgência 1234\nConta 99999-9"
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(other_bank_text)
        assert self.parser.can_parse(b"fake pdf bytes") is False

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_can_parse_returns_false_on_error(self, mock_pdfplumber):
        """can_parse não deve lançar exceção — retornar False em caso de erro."""
        mock_pdfplumber.open.side_effect = Exception("PDF corrompido")
        result = self.parser.can_parse(b"invalid content")
        assert result is False

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_returns_transactions(self, mock_pdfplumber):
        """Parser deve retornar lista não vazia para extrato válido."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        assert len(transactions) > 0

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_date_format(self, mock_pdfplumber):
        """Datas devem estar no formato YYYY-MM-DD."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        for tx in transactions:
            date_val = tx["date"]
            # Aceita string ISO ou objeto date
            if isinstance(date_val, str):
                assert len(date_val) == 10, f"Data inválida: {date_val}"
                parts = date_val.split("-")
                assert len(parts) == 3
                assert len(parts[0]) == 4  # ano
            else:
                assert isinstance(date_val, date)

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_amounts_are_numeric(self, mock_pdfplumber):
        """Todos os amounts devem ser numéricos (float)."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        for tx in transactions:
            assert isinstance(tx["amount"], float), f"Amount não é float: {tx['amount']}"

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_identifies_internal_transfer(self, mock_pdfplumber):
        """Transferência para conta própria (Mercado Pago) deve ter is_internal_transfer=True."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        internal = [tx for tx in transactions if tx.get("is_internal_transfer")]
        assert len(internal) >= 1, "Deve identificar ao menos 1 transferência interna"

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_category_is_null(self, mock_pdfplumber):
        """category e category_group devem ser None — categorização é feita no frontend."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        for tx in transactions:
            assert tx["category"] is None, "category deve ser None (sem categorização no backend)"
            assert tx["category_group"] is None, "category_group deve ser None"

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_account_key(self, mock_pdfplumber):
        """Todas as transações devem ter account = 'nubank_pf'."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        for tx in transactions:
            assert tx["account"] == "nubank_pf"

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_entradas_positivas(self, mock_pdfplumber):
        """Transações da seção 'Total de entradas' devem ter amount positivo."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        # FGTS está na seção de entradas do SAMPLE_TEXT (Itaú é conta própria → interno)
        entradas = [tx for tx in transactions if tx["amount"] > 0 and not tx["is_internal_transfer"]]
        assert len(entradas) >= 1, "Deve ter ao menos 1 entrada real positiva não-interna"

    @patch("app.parsers.nubank_pf.pdfplumber")
    def test_parse_saidas_negativas(self, mock_pdfplumber):
        """Pagamentos e compras devem ter amount negativo."""
        mock_pdfplumber.open.return_value = _make_pdfplumber_mock(SAMPLE_TEXT)
        transactions = self.parser.parse(b"fake pdf bytes")
        boletos = [
            tx for tx in transactions
            if "n n imoveis" in tx.get("description", "").lower()
        ]
        assert len(boletos) >= 1
        assert boletos[0]["amount"] < 0, "Boleto deve ser valor negativo"


# ─── Teste com PDF real (opcional — skipa se arquivo não existir) ─────────────

@pytest.mark.skipif(
    not FIXTURE_PDF_PATH.exists(),
    reason=f"Fixture real não encontrada: {FIXTURE_PDF_PATH}. "
           "Execute tests/fixtures/make_nubank_pf_fixture.py para criar.",
)
class TestNubankPFParserWithRealPDF:
    def setup_method(self):
        self.parser = NubankPFParser()
        self.content = FIXTURE_PDF_PATH.read_bytes()

    def test_can_parse_real_pdf(self):
        assert self.parser.can_parse(self.content) is True

    def test_parse_real_pdf_returns_transactions(self):
        transactions = self.parser.parse(self.content)
        assert len(transactions) > 0

    def test_real_pdf_dates_valid(self):
        transactions = self.parser.parse(self.content)
        for tx in transactions:
            d = tx["date"]
            if isinstance(d, str):
                year = int(d[:4])
                assert 2020 <= year <= 2030, f"Ano suspeito: {year}"
