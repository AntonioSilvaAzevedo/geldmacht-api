from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import extract

from ..database import get_db
from ..models.account import Account
from ..models.transaction import Transaction
from ..schemas.transaction import TransactionOut

router = APIRouter()


@router.get(
    "/transactions",
    response_model=list[TransactionOut],
    summary="Listar transações do banco",
    description="Filtra por mês (YYYY-MM), categoria ou conta. "
                "Retorna lista vazia enquanto nenhuma importação foi confirmada.",
)
def list_transactions(
    month: str | None = Query(None, description="Mês no formato YYYY-MM, ex: 2026-01"),
    category: str | None = Query(None, description="Categoria exata, ex: Alimentação"),
    account: str | None = Query(None, description="Conta, ex: nubank_pf"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    query = db.query(Transaction).options(joinedload(Transaction.account))

    if month:
        try:
            year_str, month_str = month.split("-")
            query = query.filter(
                extract("year", Transaction.date) == int(year_str),
                extract("month", Transaction.date) == int(month_str),
            )
        except (ValueError, AttributeError):
            pass  # mês inválido — ignora o filtro

    if category:
        query = query.filter(Transaction.category == category)

    if account:
        query = query.join(Account).filter(Account.type == account)

    rows = query.order_by(Transaction.date.desc()).offset(skip).limit(limit).all()

    # Serializar manualmente para incluir account_type
    result = []
    for tx in rows:
        out = TransactionOut.model_validate(tx)
        out.account_type = tx.account.type if tx.account else None
        result.append(out)
    return result
