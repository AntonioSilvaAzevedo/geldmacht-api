from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..models.account import Account
from ..models.transaction import Transaction
from ..schemas.transaction import InvoiceTransactionsResponse, TransactionOut
from ..services.summary_service import calculate_invoice_summary

router = APIRouter()


def _serialize_transaction(tx: Transaction) -> TransactionOut:
    out = TransactionOut.model_validate(tx)
    out.account_type = tx.account.type if tx.account else None
    return out


@router.get(
    "/transactions/invoice",
    response_model=InvoiceTransactionsResponse,
    summary="Listar fatura do cartão com resumo",
    description="Retorna transações do cartão Nubank do usuário atual no mês informado.",
)
def get_invoice_transactions(
    month: str = Query(..., description="Mês no formato YYYY-MM, ex: 2026-02"),
    limit: int = Query(1000, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvoiceTransactionsResponse:
    # Base: apenas transações do usuário atual com conta nubank_cartao
    base = (
        db.query(Transaction)
        .options(joinedload(Transaction.account))
        .join(Account)
        .filter(
            Transaction.user_id == current_user.id,
            Account.type        == "nubank_cartao",
            Account.user_id     == current_user.id,
        )
    )

    # Filtra por billing_month; se vazio, fallback por data
    query = base.filter(Transaction.billing_month == month)
    if query.count() == 0:
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
        .options(joinedload(Transaction.account))
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
