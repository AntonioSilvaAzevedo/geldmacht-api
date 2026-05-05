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
