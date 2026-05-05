import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.parsers.fatura_nubank import FaturaCartaoNubankParser


def test_fatura_parser_marks_payment_with_month_name():
    text = """
ANTONIO CARLOS SILVA DE AZEVEDO
FATURA 11 MAR 2026 EMISSÃO E ENVIO 04 MAR 2026
11 FEV Pagamento em 11 FEV −R$ 12.433,41
12 FEV Estorno de "Mercado" −R$ 10,00
13 FEV Compra A R$ 20,00
"""
    transactions = FaturaCartaoNubankParser()._parse_text(text)

    payment = next(tx for tx in transactions if tx["description"] == "Pagamento em 11 FEV")
    estorno = next(tx for tx in transactions if tx["description"].startswith("Estorno"))
    compra = next(tx for tx in transactions if tx["description"] == "Compra A")

    assert payment["amount"] == 12433.41
    assert payment["is_payment"] is True
    assert estorno["is_payment"] is False
    assert compra["is_payment"] is False


def test_fatura_parser_marks_payment_with_numeric_date():
    text = """
ANTONIO CARLOS SILVA DE AZEVEDO
FATURA 11 MAR 2026 EMISSÃO E ENVIO 04 MAR 2026
11 MAR Pagamento recebido em 11/03 −R$ 850,00
"""
    transactions = FaturaCartaoNubankParser()._parse_text(text)

    assert len(transactions) == 1
    assert transactions[0]["description"] == "Pagamento recebido em 11/03"
    assert transactions[0]["amount"] == 850.0
    assert transactions[0]["is_payment"] is True


# ── Testes de extract_invoice_metadata ────────────────────────────────────────

_SAMPLE_PDF_TEXT = """
ANTONIO CARLOS SILVA DE AZEVEDO
Esta é a sua fatura de abril
Data de vencimento: 13 ABR 2026
Período vigente: 04 MAR a 04 ABR
FATURA 13 ABR 2026 EMISSÃO E ENVIO 04 ABR 2026
TRANSAÇÕES DE 04 MAR A 04 ABR
Total a pagar R$ 12.542,08
15 MAR Supermercado R$ 350,00
28 MAR Netflix R$ 55,90
"""


def _make_parser_with_text(text: str) -> FaturaCartaoNubankParser:
    """Cria instância do parser que retorna `text` ao abrir PDF."""
    parser = FaturaCartaoNubankParser()

    mock_page = MagicMock()
    mock_page.extract_text.return_value = text
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]

    with patch("app.parsers.fatura_nubank.pdfplumber.open", return_value=mock_pdf):
        meta = parser.extract_invoice_metadata(b"fake-pdf")

    return meta


def test_extract_invoice_metadata_due_date():
    meta = _make_parser_with_text(_SAMPLE_PDF_TEXT)
    assert meta is not None
    assert meta["due_date"] == "2026-04-13"


def test_extract_invoice_metadata_due_month():
    meta = _make_parser_with_text(_SAMPLE_PDF_TEXT)
    assert meta["due_month"] == "2026-04"


def test_extract_invoice_metadata_cycle_dates():
    meta = _make_parser_with_text(_SAMPLE_PDF_TEXT)
    assert meta["cycle_start_date"] == "2026-03-04"
    assert meta["cycle_end_date"] == "2026-04-04"


def test_extract_invoice_metadata_issue_date():
    meta = _make_parser_with_text(_SAMPLE_PDF_TEXT)
    assert meta["issue_date"] == "2026-04-04"


def test_extract_invoice_metadata_total_amount():
    meta = _make_parser_with_text(_SAMPLE_PDF_TEXT)
    assert meta["total_amount"] == 12542.08


def test_extract_total_amount_prefers_last_total_a_pagar_when_duplicated():
    """Várias linhas 'Total a pagar' — a última da fatura atual costuma ser o valor final."""
    text = """
ANTONIO CARLOS SILVA DE AZEVEDO
Data de vencimento: 11 MAI 2026
FATURA 11 MAI 2026 EMISSÃO E ENVIO 04 MAI 2026
Resumo
Total a pagar R$ 5.951,72
Total de compras de todos os cartões, 04 ABR a 04 MAI R$ 6.258,81
Detalhes
Total a pagar R$ 5.983,28
"""
    meta = _make_parser_with_text(text)
    assert meta is not None
    assert meta["total_amount"] == 5983.28


def test_extract_total_amount_skips_proxima_fatura_block():
    text = """
FATURA 11 MAI 2026 EMISSÃO E ENVIO 04 MAI 2026
Total a pagar R$ 5.983,28

Próxima fatura
Total a pagar R$ 2.500,00
"""
    meta = _make_parser_with_text(text)
    assert meta is not None
    assert meta["total_amount"] == 5983.28


def test_extract_total_amount_fallback_header_no_valor():
    text = """
FATURA 11 MAI 2026 EMISSÃO E ENVIO 04 MAI 2026
Esta é a sua fatura de maio, no valor de R$ 4.321,09
Sem linha total a pagar isolada aqui.
"""
    meta = _make_parser_with_text(text)
    assert meta is not None
    assert meta["total_amount"] == 4321.09


def test_extract_invoice_metadata_label_month():
    meta = _make_parser_with_text(_SAMPLE_PDF_TEXT)
    assert meta["invoice_label_month"] == "abril"


def test_extract_invoice_metadata_source():
    meta = _make_parser_with_text(_SAMPLE_PDF_TEXT)
    assert meta["source"] == "nubank_pdf"


def test_extract_invoice_metadata_year_crossing():
    """Período 04 DEZ a 04 JAN com vencimento JAN/2026 → início em 2025."""
    text = """
ANTONIO CARLOS SILVA DE AZEVEDO
Data de vencimento: 10 JAN 2026
Período vigente: 04 DEZ a 04 JAN
FATURA 10 JAN 2026 EMISSÃO E ENVIO 04 JAN 2026
Total a pagar R$ 5.000,00
"""
    meta = _make_parser_with_text(text)
    assert meta is not None
    assert meta["due_date"] == "2026-01-10"
    assert meta["due_month"] == "2026-01"
    assert meta["cycle_start_date"] == "2025-12-04"
    assert meta["cycle_end_date"] == "2026-01-04"


# ── PDF real em tests/ (fixture local opcional para depara regressão) ─────────

_NUBANK_20260511 = Path(__file__).resolve().parent / "Nubank_2026-05-11.pdf"


@pytest.mark.skipif(
    not _NUBANK_20260511.is_file(),
    reason="Coloque tests/Nubank_2026-05-11.pdf neste diretório para rodar o depara.",
)
def test_nubank_2026_05_11_pdf_de_para():
    """
    Depara o PDF real: total oficial esperado R$ 5.983,28 (último \"Total a pagar\").
    Linha inicial do resumo pode trazer dois valores na mesma linha; deve prevalecer
    o total final da fatura.
    """
    raw = _NUBANK_20260511.read_bytes()
    parser = FaturaCartaoNubankParser()
    meta = parser.extract_invoice_metadata(raw)
    transactions = parser.parse(raw)

    assert meta is not None
    assert meta["total_amount"] == 5983.28
    assert meta["due_month"] == "2026-05"
    assert meta["due_date"] == "2026-05-11"
    assert meta["cycle_start_date"] == "2026-04-04"
    assert meta["cycle_end_date"] == "2026-05-04"
    assert meta["invoice_label_month"] == "maio"
    assert len(transactions) == 76


def test_extract_invoice_metadata_duplicate_total_same_line_then_final_line():
    """
    Caso típico Nubank: primeira linha de resumo com dois valores monetários ligados ao
    total; segunda linha com o total oficial final.
    """
    text = """
FATURA 11 MAI 2026 EMISSÃO E ENVIO 04 MAI 2026
Total a pagar R$ 5.951,72 R$ 6.269,65
Total a pagar R$ 5.983,28
"""
    meta = _make_parser_with_text(text)
    assert meta is not None
    assert meta["total_amount"] == 5983.28
