"""Tests for OFX extrato MVP parser + upload preview."""

from app.parsers.ofx_bank_statement import parse_bank_statement_ofx

MINIMAL_OFX = """OFXHEADER:100
DATA:OFXSGML
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<BANKTRANLIST>
<DTSTART>20260501000000
<DTEND>20260531000000
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260512120000[-3:BRT]
<TRNAMT>-45.90
<FITID>202605120001
<MEMO>IFOOD
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260511141530
<TRNAMT>100.00
<FITID>202605110001
<MEMO>PIX RECEBIDO JOAO
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1000.00
<DTASOF>20260531120000
</LEDGERBAL>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def test_parse_positive_inflow_income_negative_outflow_expense():
    meta, txs = parse_bank_statement_ofx(MINIMAL_OFX.encode("utf-8"))
    assert meta is not None
    assert meta["period_start"] is not None
    assert meta["period_end"] is not None
    assert meta["ledger_balance"] == 1000.00
    assert len(txs) == 2

    debit = next(t for t in txs if t["amount"] < 0)
    assert debit["transaction_type"] == "expense"
    assert debit["amount"] == -45.90
    assert debit["source_reference"] == "202605120001"
    assert debit["metadata"]["fitid"] == "202605120001"
    assert debit["description"]

    credit = next(t for t in txs if t["amount"] > 0)
    assert credit["transaction_type"] == "income"
    assert credit["amount"] == 100.00
    assert credit["source_reference"] == "202605110001"


def test_date_yyyymmdd_only():
    ofx = """<OFX>
<BANKTRANLIST>
<STMTTRN>
<DTPOSTED>20260501
<TRNAMT>10.00
<FITID>a1
<MEMO>X
</STMTTRN>
</BANKTRANLIST></OFX>"""
    meta, txs = parse_bank_statement_ofx(ofx.encode())
    assert len(txs) == 1
    assert txs[0]["date"].isoformat() == "2026-05-01"


def test_invalid_not_ofx():
    try:
        parse_bank_statement_ofx(b"not an ofx file at all")
    except ValueError as e:
        assert "OFX" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_no_transactions_error():
    ofx = """<OFX>
<BANKTRANLIST>
<DTSTART>20260101
</BANKTRANLIST>
</OFX>"""
    try:
        parse_bank_statement_ofx(ofx.encode())
    except ValueError as e:
        assert "transação" in str(e).lower()
    else:
        raise AssertionError("expected ValueError")


NUBANK_XML_STYLE_OFX = """OFXHEADER:100
DATA:OFXSGML
<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>BRL</CURDEF>
<BANKACCTFROM>
<BANKID>0260</BANKID>
<ACCTID>0000000-0</ACCTID>
<ACCTTYPE>CHECKING</ACCTTYPE>
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260401000000[-3:BRT]</DTSTART>
<DTEND>20260403000000[-3:BRT]</DTEND>
<STMTTRN>
<TRNTYPE>DEBIT</TRNTYPE>
<DTPOSTED>20260401000000[-3:BRT]</DTPOSTED>
<TRNAMT>-15.75</TRNAMT>
<FITID>uuid-a</FITID>
<MEMO>Loja exemplo</MEMO>
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT</TRNTYPE>
<DTPOSTED>20260403000000[-3:BRT]</DTPOSTED>
<TRNAMT>120.50</TRNAMT>
<FITID>uuid-b</FITID>
<MEMO>Pix recebido</MEMO>
</STMTTRN>
</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def test_xml_style_closed_tags_same_line():
    meta, txs = parse_bank_statement_ofx(NUBANK_XML_STYLE_OFX.encode("utf-8"))
    assert meta["account_id"] == "0000000-0"
    assert meta["period_start"] is not None
    assert len(txs) == 2
    assert txs[0]["amount"] == -15.75
    assert txs[1]["transaction_type"] == "income"
    assert txs[1]["amount"] == 120.50
    assert txs[1]["source_reference"] == "uuid-b"


def test_multiline_uppercase_tags():
    ofx = """<OFX>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>XFER
<DTPOSTED>20260115120000.000[-3:BRT]
<TRNAMT>250.55
<FITID>abc
<MEMO>Dep
</STMTTRN>
</BANKTRANLIST>
</OFX>
"""
    _, txs = parse_bank_statement_ofx(ofx.encode())
    assert len(txs) == 1
    assert txs[0]["transaction_type"] == "income"
    assert txs[0]["amount"] == 250.55
    assert txs[0]["source_reference"] == "abc"
