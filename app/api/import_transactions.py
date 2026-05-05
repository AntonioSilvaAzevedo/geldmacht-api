"""
POST /api/import — Confirma e persiste transações selecionadas pelo usuário.

Fluxo:
  1. Frontend envia lista de transações que o usuário marcou para importar
  2. Backend resolve/cria a Account do usuário atual
  3. Verifica duplicatas (mesma data + valor + raw_description + account + user)
  4. Salva as novas transações no banco vinculadas ao usuário
  5. Retorna { imported: N, skipped: M }
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..models.transaction import Transaction
from ..models.account import Account
from ..schemas.transaction import ImportRequest, ImportResponse
from ..services.summary_service import calculate_invoice_summary

logger = logging.getLogger(__name__)
router = APIRouter()

# Mapeamento: account_key → (name, bank)
_ACCOUNT_META: dict[str, tuple[str, str]] = {
    "nubank_pf":     ("Nubank PF",     "Nubank"),
    "nubank_pj":     ("Nubank PJ",     "Nubank"),
    "nubank_cartao": ("Cartão Nubank", "Nubank"),
    "itau":          ("Itaú Uniclass", "Itaú"),
    "mercado_pago":  ("Mercado Pago",  "Mercado Pago"),
    "b3":            ("B3",            "B3"),
}


def _get_or_create_account(db: Session, account_key: str, user_id: int) -> Account:
    """Busca conta do usuário pelo type ou cria uma nova vinculada ao usuário."""
    account = db.query(Account).filter(
        Account.type    == account_key,
        Account.user_id == user_id,
    ).first()

    if account:
        return account

    name, bank = _ACCOUNT_META.get(account_key, (account_key, account_key))
    account = Account(name=name, type=account_key, bank=bank, user_id=user_id)
    db.add(account)
    db.flush()  # garante que o id seja gerado antes do commit
    logger.info("Conta criada: %s (%s) para user_id=%d", name, account_key, user_id)
    return account


@router.post(
    "/import",
    response_model=ImportResponse,
    response_model_exclude_none=True,
    summary="Importar transações selecionadas",
    description=(
        "Recebe as transações que o usuário marcou para importar no preview, "
        "detecta duplicatas e persiste as novas no banco vinculadas ao usuário atual."
    ),
)
def import_selected_transactions(
    payload: ImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImportResponse:
    if not payload.transactions:
        raise HTTPException(status_code=400, detail="Nenhuma transação enviada.")

    imported = 0
    skipped  = 0

    # Detecta billing_month para faturas de cartão
    is_card_invoice = (
        payload.parser_used == "faturacartaonubank"
        or any(tx.account == "nubank_cartao" for tx in payload.transactions)
    )
    billing_month: str | None = None
    if is_card_invoice:
        from collections import Counter
        month_counts  = Counter(tx.date.strftime("%Y-%m") for tx in payload.transactions)
        billing_month = month_counts.most_common(1)[0][0] if month_counts else None
        logger.info("billing_month detectado: %s", billing_month)

    # Cache de accounts por key (evita N+1 queries)
    account_cache: dict[str, Account] = {}
    imported_transactions = []

    for tx in payload.transactions:
        account_key = tx.account

        # Resolve Account do usuário atual
        if account_key not in account_cache:
            account_cache[account_key] = _get_or_create_account(
                db, account_key, current_user.id
            )
        account = account_cache[account_key]

        # Deduplicação: considera apenas transações do mesmo usuário
        duplicate = db.query(Transaction).filter(
            and_(
                Transaction.user_id         == current_user.id,
                Transaction.date            == tx.date,
                Transaction.amount          == tx.amount,
                Transaction.raw_description == (tx.raw_description or tx.description),
                Transaction.account_id      == account.id,
            )
        ).first()

        if duplicate:
            logger.debug("Duplicata ignorada: %s %s %.2f", tx.date, tx.description[:40], tx.amount)
            skipped += 1
            continue

        new_tx = Transaction(
            user_id              = current_user.id,
            date                 = tx.date,
            description          = tx.description,
            raw_description      = tx.raw_description or tx.description,
            amount               = tx.amount,
            account_id           = account.id,
            category             = tx.category,
            category_group       = tx.category_group,
            is_internal_transfer = tx.is_internal_transfer,
            is_payment           = tx.is_payment,
            installment_current  = tx.installment_current,
            installment_total    = tx.installment_total,
            source_file          = payload.source_file,
            billing_month        = billing_month,
        )
        db.add(new_tx)
        imported += 1
        imported_transactions.append(tx)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Erro ao salvar transações no banco")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar no banco: {exc}") from exc

    logger.info(
        "Import concluído: %d importadas, %d duplicatas ignoradas (user=%s, arquivo=%s)",
        imported, skipped, current_user.email, payload.source_file,
    )

    summary = None
    if is_card_invoice:
        summary = calculate_invoice_summary([
            tx.model_dump() for tx in imported_transactions
        ])

    return ImportResponse(imported=imported, skipped=skipped, summary=summary)
