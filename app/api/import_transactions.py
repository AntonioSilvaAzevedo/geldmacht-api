"""
POST /api/import — Confirma e persiste transações selecionadas pelo usuário.

Fluxo:
  1. Frontend envia lista de transações que o usuário marcou para importar
  2. Para faturas de cartão (credit_card), exige card_id + invoice com due_month
  3. Cria entidade Invoice no banco e vincula as transactions ao invoice_id
  4. Verifica duplicatas (mesma data + valor + raw_description + account + user)
  5. Retorna { imported, skipped, invoice_id, card_id, due_month }
"""
import logging
import re
from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..models.transaction import Transaction
from ..models.account import Account
from ..models.category import Category
from ..models.credit_card import CreditCard
from ..models.invoice import Invoice
from ..schemas.transaction import ImportRequest, ImportResponse
from ..services.summary_service import calculate_invoice_summary

logger = logging.getLogger(__name__)
router = APIRouter()
_REFERENCE_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

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
    db.flush()
    logger.info("Conta criada: %s (%s) para user_id=%d", name, account_key, user_id)
    return account


def _parse_date_str(value: str | None) -> date_type | None:
    """Converte string 'YYYY-MM-DD' para date; retorna None em caso de falha."""
    if not value:
        return None
    try:
        return date_type.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _get_or_create_invoice(
    db: Session,
    user_id: int,
    card_id: int,
    due_month: str,
    invoice_payload,  # InvoiceCreate | None
) -> Invoice:
    """
    Busca fatura existente ou cria uma nova para o card_id + due_month.
    Se já existe uma invoice com mesmo user_id + card_id + due_month, reutiliza.
    """
    existing = db.query(Invoice).filter(
        Invoice.user_id   == user_id,
        Invoice.card_id   == card_id,
        Invoice.due_month == due_month,
    ).first()

    if existing:
        # Atualiza campos se a nova importação traz dados mais ricos
        if invoice_payload and invoice_payload.due_date and not existing.due_date:
            existing.due_date = _parse_date_str(invoice_payload.due_date)
        if invoice_payload and invoice_payload.cycle_start_date and not existing.cycle_start_date:
            existing.cycle_start_date = _parse_date_str(invoice_payload.cycle_start_date)
        if invoice_payload and invoice_payload.cycle_end_date and not existing.cycle_end_date:
            existing.cycle_end_date = _parse_date_str(invoice_payload.cycle_end_date)
        if invoice_payload and invoice_payload.total_amount and not existing.total_amount:
            existing.total_amount = invoice_payload.total_amount
        db.flush()
        return existing

    # Cria nova Invoice
    inv_data: dict = {
        "user_id":  user_id,
        "card_id":  card_id,
        "due_month": due_month,
        "raw_reference_month": due_month,
        "source": "legacy",
    }
    if invoice_payload:
        inv_data.update({
            "due_date":         _parse_date_str(invoice_payload.due_date),
            "cycle_start_date": _parse_date_str(invoice_payload.cycle_start_date),
            "cycle_end_date":   _parse_date_str(invoice_payload.cycle_end_date),
            "issue_date":       _parse_date_str(invoice_payload.issue_date),
            "closing_date":     _parse_date_str(invoice_payload.closing_date),
            "total_amount":     invoice_payload.total_amount,
            "source":           invoice_payload.source or "nubank_pdf",
            "raw_reference_month": invoice_payload.raw_reference_month or due_month,
        })

    invoice = Invoice(**inv_data)
    db.add(invoice)
    db.flush()
    logger.info("Invoice criada: id=%s due_month=%s card_id=%s", invoice.id, due_month, card_id)
    return invoice


@router.post(
    "/import",
    response_model=ImportResponse,
    response_model_exclude_none=True,
    summary="Importar transações selecionadas",
    description=(
        "Recebe as transações que o usuário marcou para importar no preview, "
        "detecta duplicatas e persiste as novas no banco vinculadas ao usuário atual. "
        "Para faturas de cartão, cria uma entidade Invoice e vincula invoice_id em cada transação."
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

    is_card_invoice = (
        payload.parser_used == "faturacartaonubank"
        or any(tx.account == "nubank_cartao" for tx in payload.transactions)
    )
    card: CreditCard | None = None
    invoice: Invoice | None = None
    reference_month: str | None = payload.reference_month

    if is_card_invoice:
        if payload.card_id is None:
            raise HTTPException(
                status_code=400,
                detail="Cartão é obrigatório para importação de fatura.",
            )
        card = db.query(CreditCard).filter(
            CreditCard.id == payload.card_id,
            CreditCard.user_id == current_user.id,
        ).first()
        if not card:
            raise HTTPException(status_code=404, detail="Cartão não encontrado.")

        # Determina due_month: prioriza invoice.due_month, fallback para reference_month
        due_month: str | None = None
        if payload.invoice and payload.invoice.due_month:
            due_month = payload.invoice.due_month
        elif reference_month:
            due_month = reference_month
        else:
            # Calcula a partir das datas das transações (fallback legado)
            from collections import Counter
            month_counts = Counter(tx.date.strftime("%Y-%m") for tx in payload.transactions)
            due_month = month_counts.most_common(1)[0][0] if month_counts else None

        if not due_month:
            raise HTTPException(
                status_code=422,
                detail="Mês de pagamento da fatura não identificado. "
                       "Envie invoice.due_month ou reference_month.",
            )
        if not _REFERENCE_MONTH_RE.match(due_month):
            raise HTTPException(status_code=422, detail="due_month deve estar no formato YYYY-MM.")

        reference_month = due_month
        invoice = _get_or_create_invoice(
            db, current_user.id, card.id, due_month, payload.invoice
        )
        logger.info("Fatura referência: due_month=%s invoice_id=%s", due_month, invoice.id)

    # Cache de accounts por key (evita N+1 queries)
    account_cache: dict[str, Account] = {}
    category_cache: dict[int, Category] = {}
    imported_transactions = []

    for tx in payload.transactions:
        account_key = tx.account

        if account_key not in account_cache:
            account_cache[account_key] = _get_or_create_account(
                db, account_key, current_user.id
            )
        account = account_cache[account_key]

        category = None
        if tx.category_id is not None:
            if tx.category_id not in category_cache:
                category = db.query(Category).filter(
                    Category.id == tx.category_id,
                    Category.user_id == current_user.id,
                    Category.scope == "credit_card",
                ).first()
                if not category:
                    raise HTTPException(status_code=404, detail="Categoria não encontrada.")
                category_cache[tx.category_id] = category
            category = category_cache[tx.category_id]

        # Deduplicação por usuário
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
            card_id              = card.id if card else None,
            invoice_id           = invoice.id if invoice else None,
            category_id          = category.id if category else None,
            category             = category.name if category else tx.category,
            category_group       = tx.category_group,
            is_internal_transfer = tx.is_internal_transfer,
            is_payment           = tx.is_payment,
            installment_current  = tx.installment_current,
            installment_total    = tx.installment_total,
            source_file          = payload.source_file,
            reference_month      = reference_month,
            billing_month        = reference_month,
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
        summary = calculate_invoice_summary([tx.model_dump() for tx in imported_transactions])

    return ImportResponse(
        imported=imported,
        skipped=skipped,
        card_id=card.id if card else None,
        invoice_id=invoice.id if invoice else None,
        due_month=reference_month,
        reference_month=reference_month,
        summary=summary,
    )
