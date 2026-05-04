"""
POST /api/import — Confirma e persiste transações selecionadas pelo usuário.

Fluxo:
  1. Frontend envia lista de transações que o usuário marcou para importar
  2. Backend resolve/cria a Account correspondente
  3. Verifica duplicatas (mesma data + valor + raw_description + account)
  4. Salva as novas transações no banco
  5. Retorna { imported: N, skipped: M }
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..database import get_db
from ..models.transaction import Transaction
from ..models.account import Account
from ..schemas.transaction import ImportRequest, ImportResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Mapeamento: account_key → (name, bank)
_ACCOUNT_META: dict[str, tuple[str, str]] = {
    "nubank_pf":     ("Nubank PF", "Nubank"),
    "nubank_pj":     ("Nubank PJ", "Nubank"),
    "nubank_cartao": ("Cartão Nubank", "Nubank"),
    "itau":          ("Itaú Uniclass", "Itaú"),
    "mercado_pago":  ("Mercado Pago", "Mercado Pago"),
    "b3":            ("B3", "B3"),
}


def _get_or_create_account(db: Session, account_key: str) -> Account:
    """Busca conta existente pelo type ou cria uma nova."""
    account = db.query(Account).filter(Account.type == account_key).first()
    if account:
        return account

    name, bank = _ACCOUNT_META.get(account_key, (account_key, account_key))
    account = Account(name=name, type=account_key, bank=bank)
    db.add(account)
    db.flush()  # garante que o id seja gerado antes do commit
    logger.info("Conta criada automaticamente: %s (%s)", name, account_key)
    return account


@router.post(
    "/import",
    response_model=ImportResponse,
    summary="Importar transações selecionadas",
    description=(
        "Recebe as transações que o usuário marcou para importar no preview, "
        "detecta duplicatas e persiste as novas no banco SQLite."
    ),
)
def import_selected_transactions(
    payload: ImportRequest,
    db: Session = Depends(get_db),
) -> ImportResponse:
    if not payload.transactions:
        raise HTTPException(status_code=400, detail="Nenhuma transação enviada.")

    imported = 0
    skipped = 0

    # Cache de accounts por key (evita N+1 queries)
    account_cache: dict[str, Account] = {}

    for tx in payload.transactions:
        account_key = tx.account

        # Resolve Account
        if account_key not in account_cache:
            account_cache[account_key] = _get_or_create_account(db, account_key)
        account = account_cache[account_key]

        # Verifica duplicata: mesma data + valor + raw_description + account
        duplicate = db.query(Transaction).filter(
            and_(
                Transaction.date == tx.date,
                Transaction.amount == tx.amount,
                Transaction.raw_description == (tx.raw_description or tx.description),
                Transaction.account_id == account.id,
            )
        ).first()

        if duplicate:
            logger.debug("Duplicata ignorada: %s %s %.2f", tx.date, tx.description[:40], tx.amount)
            skipped += 1
            continue

        new_tx = Transaction(
            date=tx.date,
            description=tx.description,
            raw_description=tx.raw_description or tx.description,
            amount=tx.amount,
            account_id=account.id,
            category=tx.category,
            category_group=tx.category_group,
            is_internal_transfer=tx.is_internal_transfer,
            installment_current=tx.installment_current,
            installment_total=tx.installment_total,
            source_file=payload.source_file,
        )
        db.add(new_tx)
        imported += 1

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Erro ao salvar transações no banco")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar no banco: {exc}") from exc

    logger.info(
        "Import concluído: %d importadas, %d duplicatas ignoradas (arquivo: %s)",
        imported, skipped, payload.source_file,
    )
    return ImportResponse(imported=imported, skipped=skipped)
