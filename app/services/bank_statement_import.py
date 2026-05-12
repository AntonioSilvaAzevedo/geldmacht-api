"""Lógica centralizada para importação de extrato OFX: hash de ficheiro, fingerprint e dedupe."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date

from sqlalchemy.orm import Session

from ..models.transaction import Transaction

_BANK_STMT_SOURCE = "bank_statement_import"


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_description_for_fingerprint(text: str | None) -> str:
    """Lowercase, trim, remover acentos, espaços repetidos e caracteres não imprimíveis."""
    if not text:
        return ""
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return "".join(c for c in t if c.isprintable() or c == " ")


def compute_transaction_fingerprint(
    *,
    user_id: int,
    bank_account_id: int,
    transaction_date: date,
    amount: float,
    description: str,
    source: str = _BANK_STMT_SOURCE,
) -> str:
    norm = normalize_description_for_fingerprint(description)
    amt = f"{amount:.6f}"
    payload = f"{user_id}|{bank_account_id}|{transaction_date.isoformat()}|{amt}|{norm}|{source}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_duplicate_bank_statement_tx(
    db: Session,
    *,
    user_id: int,
    bank_account_id: int,
    source_reference: str | None,
    fingerprint: str | None,
) -> Transaction | None:
    """
    Prioridade: FITID/source_reference quando truthy; caso contrário fingerprint.
    fingerprint deve ser pré-calculado (ou None quando se usa apenas source_reference).
    """
    ref = source_reference.strip() if source_reference else None
    if ref:
        return (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.bank_account_id == bank_account_id,
                Transaction.source == _BANK_STMT_SOURCE,
                Transaction.source_reference == ref,
            )
            .first()
        )
    if fingerprint:
        return (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.bank_account_id == bank_account_id,
                Transaction.source == _BANK_STMT_SOURCE,
                Transaction.transaction_fingerprint == fingerprint,
            )
            .first()
        )
    return None


def find_already_imported_batch(
    db: Session,
    *,
    user_id: int,
    bank_account_id: int,
    file_hash: str,
):
    """
    Mesmo arquivo (SHA256) já importado para esta conta pelo usuário.
    Retorna o lote mais recente com status concluído.
    """

    from ..models.import_batch import ImportBatch

    return (
        db.query(ImportBatch)
        .filter(
            ImportBatch.user_id == user_id,
            ImportBatch.bank_account_id == bank_account_id,
            ImportBatch.import_kind == "bank_statement",
            ImportBatch.file_hash == file_hash,
            ImportBatch.status.in_(("imported", "partially_imported")),
        )
        .order_by(ImportBatch.id.desc())
        .first()
    )


def batch_status(imported_count: int, skipped_count: int) -> str:
    if imported_count <= 0 and skipped_count <= 0:
        return "failed"
    if skipped_count > 0:
        return "partially_imported"
    return "imported"
