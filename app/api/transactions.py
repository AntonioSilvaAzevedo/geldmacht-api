from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..models.account import Account
from ..models.category import Category
from ..models.credit_card import CreditCard
from ..models.invoice import Invoice
from ..models.transaction import Transaction
from ..schemas.transaction import InvoiceTransactionsResponse, TransactionOut, TransactionUpdate
from ..services.summary_service import calculate_invoice_summary

router = APIRouter()


def _serialize_transaction(tx: Transaction) -> TransactionOut:
    out = TransactionOut.model_validate(tx)
    out.account_type = tx.account.type if tx.account else None
    out.category_name = tx.category_ref.name if tx.category_ref else tx.category
    return out


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
        .options(joinedload(Transaction.account))
        .options(joinedload(Transaction.category_ref))
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
        if body.category_id == 0:
            tx.category_id = None
            tx.category = None
        else:
            category = db.query(Category).filter(
                Category.id == body.category_id,
                Category.user_id == current_user.id,
                Category.scope == "credit_card",
            ).first()
            if not category:
                raise HTTPException(status_code=404, detail="Categoria não encontrada.")
            # Categoria deve ser global (card_id=null) ou pertencer ao mesmo cartão da transação.
            if category.card_id is not None and tx.card_id is not None and category.card_id != tx.card_id:
                raise HTTPException(
                    status_code=400,
                    detail="Categoria não é aplicável a este cartão.",
                )
            tx.category_id = category.id
            tx.category = category.name
    db.commit()
    db.refresh(tx)
    return _serialize_transaction(tx)


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
        joinedload(Transaction.category_ref),
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
        transactions = [_serialize_transaction(tx) for tx in rows]
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
    transactions = [_serialize_transaction(tx) for tx in rows]
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
    month:    str | None = Query(None, description="Mês no formato YYYY-MM, ex: 2026-01"),
    category: str | None = Query(None, description="Categoria exata, ex: Alimentação"),
    account:  str | None = Query(None, description="Conta, ex: nubank_pf"),
    skip:  int = Query(0,   ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    query = (
        db.query(Transaction)
        .options(joinedload(Transaction.account), joinedload(Transaction.category_ref))
        .filter(Transaction.user_id == current_user.id)
    )

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
    return [_serialize_transaction(tx) for tx in rows]
