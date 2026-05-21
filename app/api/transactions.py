from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..models.account import Account
from ..models.bank_account import BankAccount
from ..models.category import Category
from ..models.credit_card import CreditCard
from ..models.invoice import Invoice
from ..models.transaction import Transaction
from ..schemas.transaction import (
    InvoiceTransactionsResponse,
    ManualTransactionCreate,
    TransactionOut,
    TransactionUpdate,
)
from ..services.summary_service import calculate_invoice_summary
from ..services.transaction_serialization import serialize_transaction_out

router = APIRouter()


def _apply_category_patch(
    db: Session,
    current_user: User,
    tx: Transaction,
    category_id: int | None,
) -> None:
    """Atualiza category_id em tx; levanta HTTPException se inválido."""
    if category_id is None:
        return
    if category_id == 0:
        tx.category_id = None
        tx.category = None
        return

    category = db.query(Category).filter(
        Category.id == category_id,
        Category.user_id == current_user.id,
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    if tx.bank_account_id is not None:
        if category.scope != "bank":
            raise HTTPException(
                status_code=400,
                detail="Use uma categoria com escopo conta bancária (bank).",
            )
    elif tx.card_id is not None:
        if category.scope != "credit_card":
            raise HTTPException(
                status_code=400,
                detail="Categoria incompatível com lançamento de cartão.",
            )
        if category.card_id is not None and tx.card_id is not None and category.card_id != tx.card_id:
            raise HTTPException(
                status_code=400,
                detail="Categoria não é aplicável a este cartão.",
            )
    else:
        if category.scope not in ("credit_card", "bank"):
            raise HTTPException(status_code=400, detail="Categoria incompatível com este lançamento.")
        if category.scope == "credit_card" and category.card_id is not None:
            raise HTTPException(
                status_code=400,
                detail="Para lançamentos sem cartão, use categoria global ou escopo conta bancária.",
            )

    tx.category_id = category.id
    tx.category = category.name


def _build_manual_tx(
    body: ManualTransactionCreate,
    current_user: User,
    db: Session,
) -> Transaction:
    """Valida e constrói um Transaction (sem commit)."""
    bacc = (
        db.query(BankAccount)
        .filter(
            BankAccount.id == body.bank_account_id,
            BankAccount.user_id == current_user.id,
        )
        .first()
    )
    if not bacc:
        raise HTTPException(status_code=404, detail=f"Conta bancária {body.bank_account_id} não encontrada.")
    if not bacc.is_active:
        raise HTTPException(status_code=400, detail=f"Conta bancária {bacc.id} está desativada.")

    category = None
    if body.category_id is not None:
        category = db.query(Category).filter(
            Category.id == body.category_id,
            Category.user_id == current_user.id,
            Category.scope == "bank",
        ).first()
        if not category:
            raise HTTPException(status_code=404, detail="Categoria não encontrada ou incompatível.")

    return Transaction(
        user_id=current_user.id,
        date=body.transaction_date,
        description=body.description.strip(),
        raw_description=body.description.strip(),
        amount=body.amount,
        account_id=None,
        card_id=None,
        invoice_id=None,
        bank_account_id=bacc.id,
        category_id=category.id if category else None,
        category=category.name if category else None,
        category_group=None,
        source="manual",
        transaction_type=body.transaction_type,
        notes=body.notes.strip() if body.notes else None,
        source_file=None,
        is_internal_transfer=False,
        is_payment=False,
        installment_current=None,
        installment_total=None,
        reference_month=None,
        billing_month=None,
    )


def _load_tx_out(tx_id: int, user_id: int, db: Session) -> TransactionOut:
    loaded = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.category_ref).joinedload(Category.parent),
        )
        .filter(Transaction.id == tx_id, Transaction.user_id == user_id)
        .first()
    )
    assert loaded is not None
    return serialize_transaction_out(loaded)


@router.post(
    "/transactions",
    response_model=TransactionOut,
    summary="Criar lançamento manual (conta bancária)",
)
def create_manual_transaction(
    body: ManualTransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionOut:
    tx = _build_manual_tx(body, current_user, db)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return _load_tx_out(tx.id, current_user.id, db)


@router.post(
    "/transactions/batch",
    response_model=list[TransactionOut],
    summary="Criar múltiplos lançamentos manuais em lote",
)
def create_manual_transactions_batch(
    body: list[ManualTransactionCreate],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    if not body:
        return []
    txs = [_build_manual_tx(item, current_user, db) for item in body]
    for tx in txs:
        db.add(tx)
    db.commit()
    for tx in txs:
        db.refresh(tx)
    return [_load_tx_out(tx.id, current_user.id, db) for tx in txs]


@router.patch(
    "/transactions/{tx_id}",
    response_model=TransactionOut,
    summary="Atualizar transação",
    description="Edita descrição e/ou categoria de uma transação do usuário autenticado.",
)
def update_transaction(
    tx_id: int,
    body: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TransactionOut:
    tx = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.category_ref).joinedload(Category.parent),
        )
        .filter(
            Transaction.id      == tx_id,
            Transaction.user_id == current_user.id,
        )
        .first()
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Transação não encontrada.")

    # Bloqueia categorização manual de lançamentos sistêmicos.
    # Compras parceladas (installment_total > 1) e pagamentos da fatura (is_payment=True)
    # são classificações sistêmicas — não recebem category_id manual.
    is_systemic = bool(tx.is_payment) or (
        tx.installment_current is not None
        and tx.installment_total is not None
        and tx.installment_total > 1
    )

    if body.description is not None:
        tx.description = body.description.strip()
    if body.category is not None and not is_systemic:
        tx.category = body.category or None
    if body.category_id is not None:
        if is_systemic:
            raise HTTPException(
                status_code=400,
                detail="Este lançamento é sistêmico e não pode ser categorizado manualmente.",
            )
        _apply_category_patch(db, current_user, tx, body.category_id)
    db.commit()
    tx_out = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.category_ref).joinedload(Category.parent),
        )
        .filter(
            Transaction.id == tx_id,
            Transaction.user_id == current_user.id,
        )
        .first()
    )
    assert tx_out is not None
    return serialize_transaction_out(tx_out)


@router.get(
    "/transactions/invoice",
    response_model=InvoiceTransactionsResponse,
    summary="Listar fatura do cartão com resumo",
    description=(
        "Retorna transações de uma fatura. "
        "Prefira invoice_id quando disponível (busca direta). "
        "Fallback: card_id + month (YYYY-MM) — busca por reference_month ou billing_month."
    ),
)
def get_invoice_transactions(
    invoice_id: int | None = Query(None, description="ID da Invoice (prioritário)"),
    month: str | None = Query(None, description="Mês no formato YYYY-MM, ex: 2026-02"),
    card_id: int | None = Query(None, description="ID do cartão cadastrado"),
    limit: int = Query(1000, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvoiceTransactionsResponse:
    base = db.query(Transaction).options(
        joinedload(Transaction.account),
        joinedload(Transaction.bank_account),
        joinedload(Transaction.category_ref).joinedload(Category.parent),
    ).filter(Transaction.user_id == current_user.id)

    # ── Busca por invoice_id (prioritária) ───────────────────────────────────
    if invoice_id is not None:
        invoice = db.query(Invoice).filter(
            Invoice.id      == invoice_id,
            Invoice.user_id == current_user.id,
        ).first()
        if not invoice:
            raise HTTPException(status_code=404, detail="Fatura não encontrada.")
        query = base.filter(Transaction.invoice_id == invoice_id)
        rows = query.order_by(Transaction.date.desc()).limit(limit).all()
        transactions = [serialize_transaction_out(tx) for tx in rows]
        summary = calculate_invoice_summary([tx.model_dump() for tx in transactions])
        return InvoiceTransactionsResponse(transactions=transactions, summary=summary)

    # ── Busca legada por month + card_id ─────────────────────────────────────
    if not month:
        raise HTTPException(status_code=422, detail="Informe invoice_id ou month.")

    if card_id is not None:
        card = db.query(CreditCard).filter(
            CreditCard.id == card_id,
            CreditCard.user_id == current_user.id,
        ).first()
        if not card:
            raise HTTPException(status_code=404, detail="Cartão não encontrado.")
        base = base.filter(Transaction.card_id == card.id)
    else:
        base = base.join(Account).filter(
            Account.type == "nubank_cartao",
            Account.user_id == current_user.id,
        )

    query = base.filter(Transaction.reference_month == month)
    if query.count() == 0:
        legacy_query = base.filter(Transaction.billing_month == month)
        if legacy_query.count() > 0:
            query = legacy_query
        else:
            try:
                year_str, month_str = month.split("-")
                query = base.filter(
                    extract("year",  Transaction.date) == int(year_str),
                    extract("month", Transaction.date) == int(month_str),
                )
            except (ValueError, AttributeError):
                query = base.filter(False)

    rows         = query.order_by(Transaction.date.desc()).limit(limit).all()
    transactions = [serialize_transaction_out(tx) for tx in rows]
    summary      = calculate_invoice_summary([tx.model_dump() for tx in transactions])
    return InvoiceTransactionsResponse(transactions=transactions, summary=summary)


@router.get(
    "/transactions",
    response_model=list[TransactionOut],
    summary="Listar transações do banco",
    description="Filtra por mês (YYYY-MM), categoria ou conta. Retorna apenas dados do usuário autenticado.",
)
def list_transactions(
    current_user: User = Depends(get_current_user),
    month: str | None = Query(None, description="Mês no formato YYYY-MM, ex: 2026-01"),
    category: str | None = Query(None, description="Categoria exata, ex: Alimentação"),
    account: str | None = Query(None, description="Conta, ex: nubank_pf"),
    bank_account_id: int | None = Query(None, description="Filtra por conta bancária cadastrada"),
    transaction_type: str | None = Query(
        None,
        description="Tipo econômico: income ou expense",
    ),
    start_date: str | None = Query(None, description="YYYY-MM-DD — data inicial (inclusive)"),
    end_date: str | None = Query(None, description="YYYY-MM-DD — data final (inclusive)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    query = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.bank_account),
            joinedload(Transaction.category_ref).joinedload(Category.parent),
        )
        .filter(Transaction.user_id == current_user.id)
    )

    if bank_account_id is not None:
        bacc = db.query(BankAccount).filter(
            BankAccount.id == bank_account_id,
            BankAccount.user_id == current_user.id,
        ).first()
        if not bacc:
            raise HTTPException(status_code=404, detail="Conta bancária não encontrada.")
        query = query.filter(
            Transaction.bank_account_id == bank_account_id,
            Transaction.card_id.is_(None),
            Transaction.invoice_id.is_(None),
        )

    if transaction_type:
        tt = transaction_type.strip().lower()
        if tt not in ("income", "expense"):
            raise HTTPException(status_code=422, detail="transaction_type deve ser income ou expense.")
        query = query.filter(Transaction.transaction_type == tt)

    if start_date:
        try:
            d0 = date_type.fromisoformat(start_date.strip())
            query = query.filter(Transaction.date >= d0)
        except ValueError:
            raise HTTPException(status_code=422, detail="start_date inválido; use YYYY-MM-DD.") from None

    if end_date:
        try:
            d1 = date_type.fromisoformat(end_date.strip())
            query = query.filter(Transaction.date <= d1)
        except ValueError:
            raise HTTPException(status_code=422, detail="end_date inválido; use YYYY-MM-DD.") from None

    if month:
        try:
            year_str, month_str = month.split("-")
            query = query.filter(
                extract("year",  Transaction.date) == int(year_str),
                extract("month", Transaction.date) == int(month_str),
            )
        except (ValueError, AttributeError):
            pass

    if category:
        query = query.filter(Transaction.category == category)

    if account:
        query = (
            query.join(Account)
            .filter(
                Account.type    == account,
                Account.user_id == current_user.id,
            )
        )

    rows = query.order_by(Transaction.date.desc()).offset(skip).limit(limit).all()
    return [serialize_transaction_out(tx) for tx in rows]
