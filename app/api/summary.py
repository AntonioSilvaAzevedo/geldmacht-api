from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.user import User
from ..schemas.summary import FinancialSummary
from ..services.summary_service import get_financial_summary

router = APIRouter()


@router.get(
    "/summary",
    response_model=FinancialSummary,
    summary="Resumo financeiro do mês atual",
    description="Indicadores do mês atual: saldo, receitas, despesas, parcelamentos ativos e futuro comprometido. Com institution_id, escopa às contas e cartões da instituição.",
)
def get_summary(
    institution_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FinancialSummary:
    return get_financial_summary(db, current_user.id, institution_id=institution_id)
