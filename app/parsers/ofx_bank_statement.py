"""
Parser MVP para extratos OFX (conta corrente / visão genérica BANKTRANLIST).

Somente interpretação local — não persiste. Usado quando import_kind=bank_statement no upload.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any


# SGML típico: tag + valor até fim da linha (sem fechamento </TAG>)
_TAG_LINE_RE = re.compile(r"<([A-Za-z0-9_.]+)>\s*([^<\r\n]*?)\s*(?:\r?\n|$)")
# XML (ex.: Nubank OFX): <TAG>valor</TAG> na mesma linha
_XML_PAIR_RE = re.compile(r"<([A-Za-z0-9_.]+)>\s*([^<]*?)\s*</\1>", re.I | re.S)

# Marcadores que distinguem extrato de conta (BANK) de fatura de cartão (CC)
_CC_MARKERS_RE = re.compile(r"(?i)<\s*(?:CREDITCARDMSGSRSV1|CCSTMTRS|CCACCTFROM|CCSTMTTRNRS)\b")
_BANK_MARKERS_RE = re.compile(r"(?i)<\s*(?:BANKMSGSRSV1|STMTRS|BANKACCTFROM)\b")


def _decode_ofx(content: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def detect_ofx_kind(content: bytes) -> str | None:
    """
    Identifica se o OFX é de conta corrente ou cartão de crédito.

    Retorna 'bank_statement', 'credit_card' ou None (ambíguo/desconhecido — não bloqueia).
    """
    if not content:
        return None
    text = _decode_ofx(content)
    has_cc = bool(_CC_MARKERS_RE.search(text))
    has_bank = bool(_BANK_MARKERS_RE.search(text))
    if has_cc and not has_bank:
        return "credit_card"
    if has_bank and not has_cc:
        return "bank_statement"
    return None


def _parse_ofx_date(raw: str | None) -> date | None:
    if not raw:
        return None
    s = raw.strip()
    if "[" in s:
        s = s.split("[", 1)[0].strip()
    s = re.sub(r"\s+", "", s)
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 14:
        y, m, d = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        return date(y, m, d)
    if len(digits) >= 8:
        y, m, d = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        return date(y, m, d)
    return None


def _tags_from_block(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _XML_PAIR_RE.finditer(block):
        out[m.group(1).upper().strip()] = m.group(2).strip()
    for m in _TAG_LINE_RE.finditer(block):
        key = m.group(1).upper().strip()
        if key not in out:
            out[key] = m.group(2).strip()
    return out


def _first_org(text: str) -> str | None:
    m = re.search(r"(?is)<ORG>\s*([^<\r\n]+)", text)
    return m.group(1).strip() if m else None


def _first_bankacctfrom(text: str) -> dict[str, str]:
    m = re.search(r"(?is)<BANKACCTFROM>\s*(.*?)\s*</BANKACCTFROM>", text, re.DOTALL)
    if m:
        return _tags_from_block(m.group(1))
    # SGML sem tag de fechamento: até lista de lançamentos ou fim da conta
    m2 = re.search(
        r"(?is)<BANKACCTFROM>\s*(.*?)(?=<BANKTRANLIST>|</STMTRS>)",
        text,
        re.DOTALL,
    )
    return _tags_from_block(m2.group(1)) if m2 else {}


def _extract_banktranlist(text: str) -> tuple[str | None, str]:
    """Retorna bloco BANKTRANLIST (sem tags externas) ou string vazia."""
    tm = re.search(r"(?is)<BANKTRANLIST>\s*(.*?)(?:</BANKTRANLIST>|(?=<LEDGERBAL>)|(?=<AVAILBAL>)|(?=</STMTRS>)|(?=</STMTTRNRS>)|(?=<STMTTRNRS>))",
                   text,
                   re.DOTALL)
    if tm:
        return tm.group(1), tm.group(0)
    # Alguns OFX são XML com tags fechadas
    xm = re.search(r"(?is)<BANKTRANLIST>(.*?)</BANKTRANLIST>", text, re.DOTALL)
    if xm:
        return xm.group(1), xm.group(0)
    return None, text


def _ledger_balance_amt(full_text: str) -> tuple[float | None, date | None]:
    m = re.search(r"(?is)<LEDGERBAL>\s*(.*?)\s*</LEDGERBAL>", full_text, re.DOTALL)
    if not m:
        m2 = re.search(r"(?is)<LEDGERBAL>\s*(.*?)(?=<[A-Za-z]+\>|$)", full_text, re.DOTALL)
        if not m2:
            return None, None
        block_inner = m2.group(1)
    else:
        block_inner = m.group(1)
    tags = _tags_from_block(block_inner)
    bal_raw = tags.get("BALAMT")
    try:
        bal = float(bal_raw) if bal_raw not in (None, "") else None
    except ValueError:
        bal = None
    dt_raw = tags.get("DTASOF")
    return bal, _parse_ofx_date(dt_raw)


def _split_stmttrns(banktranlist_inner: str) -> list[str]:
    parts = re.split(r"(?is)<STMTTRN>", banktranlist_inner)
    blocks: list[str] = []
    for part in parts[1:]:
        if re.search(r"(?is)</STMTTRN>", part):
            inner = re.split(r"(?is)</STMTTRN>", part, maxsplit=1)[0]
        else:
            inner = part
        blocks.append(inner)
    return blocks


def _description_from_tags(tags: dict[str, str]) -> str:
    name = (tags.get("NAME") or "").strip()
    memo = (tags.get("MEMO") or "").strip()
    check = (tags.get("CHECKNUM") or "").strip()
    if memo and name and memo.upper() != name.upper():
        return f"{name} — {memo}".strip()
    if memo:
        return memo
    if name:
        return name
    if check:
        return f"Cheque {check}"
    return "(sem descrição)"


def _amount_and_type(trnamt_raw: str, trntype: str | None) -> tuple[float, str]:
    try:
        amount = float(str(trnamt_raw).strip().replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Valor TRNAMT inválido: {trnamt_raw!r}") from exc
    if amount > 0:
        tt = "income"
    elif amount < 0:
        tt = "expense"
    else:
        tt = "income" if (trntype or "").upper() in ("CREDIT", "DEP", "DEPOSIT", "INTEREST") else "expense"
    return amount, tt


def parse_bank_statement_ofx(content: bytes) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """
    Extrai metadata do extrato e lista de transações no formato esperado por ParsedTransaction.

    Raises ValueError com mensagem clara se o arquivo não for OFX útil ou não houver lançamentos.
    """
    if not content or not content.strip():
        raise ValueError("Arquivo vazio.")

    text = None
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = content.decode("utf-8", errors="replace")

    if not re.search(r"(?i)OFX|OPEN\s+FINANCIAL\s+EXCHANGE", text[:8000]):
        raise ValueError("Arquivo não parece ser OFX (cabeçalho OFX não encontrado).")

    blist_inner, _ = _extract_banktranlist(text)
    meta_region = blist_inner if blist_inner is not None else text

    stmt_tags = _tags_from_block(meta_region)
    period_start = _parse_ofx_date(stmt_tags.get("DTSTART"))
    period_end = _parse_ofx_date(stmt_tags.get("DTEND"))

    org = _first_org(text)
    bacct = _first_bankacctfrom(text)
    acct_id = (bacct.get("ACCTID") or bacct.get("ACCTNUMBER") or "").strip() or None

    ledger_amt, _ledger_dt = _ledger_balance_amt(text)

    if blist_inner is None:
        blist_inner = text
    stm_blocks = _split_stmttrns(blist_inner)

    if not stm_blocks:
        raise ValueError(
            "Nenhuma transação encontrada neste OFX (tag STMTTRN ausente ou lista vazia)."
        )

    transactions: list[dict[str, Any]] = []
    for block in stm_blocks:
        tags = _tags_from_block(block)
        trnamt = tags.get("TRNAMT")
        if trnamt in (None, ""):
            continue
        d = _parse_ofx_date(tags.get("DTPOSTED") or tags.get("DTUSER") or tags.get("DTAVAIL"))
        if not d:
            raise ValueError(
                "Transação sem data válida (DTPOSTED/DTUSER). Verifique se o OFX está íntegro."
            )

        amount, tx_type = _amount_and_type(trnamt, tags.get("TRNTYPE"))

        raw_desc_parts = []
        for k in ("NAME", "MEMO", "CHECKNUM"):
            if tags.get(k):
                raw_desc_parts.append(tags[k])
        raw_description = " | ".join(raw_desc_parts).strip() or _description_from_tags(tags)
        description = _description_from_tags(tags)

        fitid = (tags.get("FITID") or "").strip() or None
        trtype = (tags.get("TRNTYPE") or "").strip()
        memo_payload: dict[str, Any] = {}
        if trtype:
            memo_payload["ofx_type"] = trtype
        if fitid:
            memo_payload["fitid"] = fitid

        transactions.append(
            {
                "date": d,
                "description": description,
                "raw_description": raw_description,
                "amount": amount,
                "account": "bank_statement_ofx",
                "transaction_type": tx_type,
                "source_reference": fitid,
                "metadata": memo_payload if memo_payload else None,
                "category": None,
                "category_id": None,
                "category_group": None,
                "is_internal_transfer": False,
                "is_payment": False,
                "installment_current": None,
                "installment_total": None,
            }
        )

    if not transactions:
        raise ValueError(
            "Nenhuma transação válida encontrada neste OFX (verifique TRNAMT/DTPOSTED)."
        )

    sum_in = sum(t["amount"] for t in transactions if t["amount"] > 0)
    sum_out = sum(-t["amount"] for t in transactions if t["amount"] < 0)

    statement_metadata = {
        "institution": org,
        "account_id": acct_id,
        "period_start": period_start,
        "period_end": period_end,
        "ledger_balance": ledger_amt,
        "total_inflows": round(sum_in, 2),
        "total_outflows": round(sum_out, 2),
    }

    return statement_metadata, transactions
