"""
POST /api/import — Confirma e persiste transações selecionadas pelo usuário.

Fluxo:
  1. Frontend envia lista de transações marcadas + `import_kind`
  2. `credit_card_invoice` / inferido: card_id + invoice, cria Invoice
  3. `bank_statement`: valida `bank_account_id`, `parser_used=bank_statement_ofx`, categorias `bank`, `source=bank_statement_import`
  4. Dedup: extrato usa `source_reference`/FITID; sem FITID usa fingerprint determinístico; bloqueio de arquivo repetido (SHA256/conta/usuário)
  5. Retorno com contagens e dados de fatura ou lista de transações criadas (extrato)
"""
import logging
import re
from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.bank_account import BankAccount
from ..models.user import User
from ..models.transaction import Transaction
from ..models.import_batch import ImportBatch
from ..models.account import Account
from ..models.category import Category
from ..models.credit_card import CreditCard
from ..models.invoice import Invoice
from ..schemas.transaction import ImportRequest, ImportResponse
from ..services.bank_statement_import import (
    batch_status,
    compute_transaction_fingerprint,
    find_already_imported_batch,
    find_duplicate_bank_statement_tx,
)
from ..services.recurrence_service import sync_recurrence_for_transaction
from ..services.summary_service import calculate_invoice_summary
from ..services.transaction_serialization import serialize_transaction_out

logger = logging.getLogger(__name__)
router = APIRouter()
_REFERENCE_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_FILE_HASH_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")

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


def _import_bank_statement(
    db: Session,
    current_user: User,
    payload: ImportRequest,
) -> ImportResponse:
    if payload.bank_account_id is None:
        raise HTTPException(
            status_code=400,
            detail="bank_account_id é obrigatório para import_kind=bank_statement.",
        )

    if not payload.file_hash or not _FILE_HASH_HEX_RE.fullmatch(payload.file_hash):
        raise HTTPException(
            status_code=400,
            detail="file_hash obrigatório (SHA256 em hex, 64 caracteres), igual ao retornado pelo preview.",
        )
    fh = payload.file_hash.lower()

    if payload.parser_used != "bank_statement_ofx":
        raise HTTPException(
            status_code=400,
            detail="Importação de extrato requer parser_used=bank_statement_ofx (upload OFX).",
        )

    bacc = (
        db.query(BankAccount)
        .filter(
            BankAccount.id == payload.bank_account_id,
            BankAccount.user_id == current_user.id,
        )
        .first()
    )
    if not bacc:
        raise HTTPException(status_code=404, detail="Conta bancária não encontrada.")
    if not bacc.is_active:
        raise HTTPException(status_code=400, detail="Conta bancária está desativada.")

    if (
        find_already_imported_batch(
            db,
            user_id=current_user.id,
            bank_account_id=bacc.id,
            file_hash=fh,
        )
        is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Este arquivo já foi importado para esta conta.",
        )

    from datetime import datetime

    category_cache: dict[int, Category] = {}
    imported = 0
    skipped = 0
    created_ids: list[int] = []

    now = datetime.utcnow()
    batch = ImportBatch(
        user_id=current_user.id,
        bank_account_id=bacc.id,
        import_kind="bank_statement",
        source_type="ofx",
        file_name=(payload.source_file.strip()[:512]) if payload.source_file else "arquivo.ofx",
        file_hash=fh,
        parser_used=payload.parser_used,
        status="failed",
        total_transactions=len(payload.transactions),
        imported_count=0,
        skipped_count=0,
        period_start=payload.period_start,
        period_end=payload.period_end,
        imported_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(batch)
    db.flush()

    for tx in payload.transactions:
        if tx.account != "bank_statement_ofx":
            raise HTTPException(
                status_code=400,
                detail="Transação de extrato inválida: account esperado bank_statement_ofx.",
            )

        inferred_type = tx.transaction_type
        if inferred_type not in ("income", "expense"):
            inferred_type = "income" if tx.amount > 0 else "expense"

        cat = None
        if tx.category_id is not None:
            cid = tx.category_id
            if cid not in category_cache:
                row = db.query(Category).filter(
                    Category.id == cid,
                    Category.user_id == current_user.id,
                ).first()
                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="Categoria não encontrada.",
                    )
                category_cache[cid] = row
            cat = category_cache[cid]

        fit_ref = (tx.source_reference or "").strip() or None
        fingerprint: str | None = None
        if not fit_ref:
            fingerprint = compute_transaction_fingerprint(
                user_id=current_user.id,
                bank_account_id=bacc.id,
                transaction_date=tx.date,
                amount=tx.amount,
                description=tx.description.strip(),
            )

        duplicate = find_duplicate_bank_statement_tx(
            db,
            user_id=current_user.id,
            bank_account_id=bacc.id,
            source_reference=fit_ref,
            fingerprint=fingerprint,
        )

        if duplicate:
            skipped += 1
            continue

        raw_desc = tx.raw_description or tx.description
        new_tx = Transaction(
            user_id=current_user.id,
            date=tx.date,
            description=tx.description.strip(),
            raw_description=raw_desc.strip() if raw_desc else None,
            amount=tx.amount,
            account_id=None,
            card_id=None,
            invoice_id=None,
            bank_account_id=bacc.id,
            category_id=cat.id if cat else None,
            category=cat.name if cat else None,
            category_group=tx.category_group,
            source_file=payload.source_file,
            reference_month=None,
            billing_month=None,
            source="bank_statement_import",
            transaction_type=inferred_type,
            source_reference=fit_ref,
            transaction_fingerprint=fingerprint,
            import_batch_id=batch.id,
            is_internal_transfer=tx.is_internal_transfer,
            is_payment=False,
            installment_current=None,
            installment_total=None,
            notes=None,
        )
        db.add(new_tx)
        imported += 1
        db.flush()
        created_ids.append(new_tx.id)

    finalize = datetime.utcnow()
    batch.imported_count = imported
    batch.skipped_count = skipped
    batch.status = batch_status(imported, skipped)
    batch.imported_at = finalize
    batch.updated_at = finalize

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Erro ao salvar extrato OFX")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar no banco: {exc}") from exc

    if not created_ids:
        return ImportResponse(
            imported=0,
            skipped=skipped,
            bank_account_id=bacc.id,
            transactions=[],
            import_batch_id=batch.id,
        )

    rows = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.category_ref).joinedload(Category.parent),
        )
        .filter(
            Transaction.id.in_(created_ids),
            Transaction.user_id == current_user.id,
        )
        .order_by(Transaction.id.asc())
        .all()
    )
    out_list = [serialize_transaction_out(row) for row in rows]

    logger.info(
        "Import extrato batch=%s: %d importadas, %d ignoradas (%s arquivo=%s conta=%s)",
        batch.id,
        imported,
        skipped,
        current_user.email,
        payload.source_file,
        bacc.id,
    )

    return ImportResponse(
        imported=imported,
        skipped=skipped,
        bank_account_id=bacc.id,
        transactions=out_list,
        import_batch_id=batch.id,
    )


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

    if payload.import_kind == "bank_statement":
        return _import_bank_statement(db, current_user, payload)

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

    if payload.import_kind == "credit_card_invoice" and not is_card_invoice:
        raise HTTPException(
            status_code=400,
            detail="import_kind=credit_card_invoice é incompatível com este arquivo (esperada fatura de cartão).",
        )

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

        # Lançamentos sistêmicos (compras parceladas e pagamento da fatura) não recebem
        # category_id manual. Se o frontend enviar, normalizamos silenciosamente para None.
        is_systemic_tx = bool(tx.is_payment) or (
            tx.installment_current is not None
            and tx.installment_total is not None
            and tx.installment_total > 1
        )
        if is_systemic_tx:
            tx.category_id = None
            tx.category = None

        category = None
        if tx.category_id is not None:
            if tx.category_id not in category_cache:
                category = db.query(Category).filter(
                    Category.id == tx.category_id,
                    Category.user_id == current_user.id,
                ).first()
                if not category:
                    raise HTTPException(status_code=404, detail="Categoria não encontrada.")
                # Categoria deve ser global ou do mesmo cartão da fatura.
                if (
                    category.card_id is not None
                    and card is not None
                    and category.card_id != card.id
                ):
                    raise HTTPException(
                        status_code=400,
                        detail="Categoria não é aplicável a este cartão.",
                    )
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
            if is_card_invoice and invoice is not None:
                if duplicate.invoice_id != invoice.id:
                    logger.info(
                        "Duplicata re-vinculada: tx_id=%s invoice_id %s → %s",
                        duplicate.id, duplicate.invoice_id, invoice.id,
                    )
                    duplicate.invoice_id = invoice.id
                    if duplicate.card_id is None:
                        duplicate.card_id = card.id if card else None
                    imported_transactions.append(tx)
                duplicate_is_systemic = bool(duplicate.is_payment) or (
                    duplicate.installment_total is not None
                    and duplicate.installment_total > 1
                )
                if category is not None and not duplicate_is_systemic:
                    duplicate.category_id = category.id
                    duplicate.category = category.name
            else:
                logger.debug("Duplicata ignorada: %s %s %.2f", tx.date, tx.description[:40], tx.amount)
            skipped += 1
            continue

        if tx.is_payment:
            tx_type = "payment"
        elif tx.amount < 0:
            tx_type = "expense"
        else:
            tx_type = "income"

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
            source               = "pdf_invoice_import" if is_card_invoice else None,
            transaction_type     = tx_type,
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

    if is_card_invoice and invoice is not None:
        invoice_txs = db.query(Transaction).filter(
            Transaction.invoice_id == invoice.id,
            Transaction.user_id == current_user.id,
        ).all()
        for invoice_tx in invoice_txs:
            sync_recurrence_for_transaction(db, invoice_tx)
        db.commit()

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
