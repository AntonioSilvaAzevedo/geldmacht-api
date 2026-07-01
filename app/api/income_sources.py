"""CRUD de fontes de entrada do usuário (origem de receitas e benefícios)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.bank_account import BankAccount
from ..models.income_source import IncomeSource
from ..models.user import User
from ..schemas.income_source import IncomeSourceCreate, IncomeSourceOut, IncomeSourceUpdate

router = APIRouter()


def _get_owned_income_source(db: Session, user_id: int, income_source_id: int) -> IncomeSource:
    src = (
        db.query(IncomeSource)
        .filter(IncomeSource.id == income_source_id, IncomeSource.user_id == user_id)
        .first()
    )
    if not src:
        raise HTTPException(status_code=404, detail="Fonte de entrada não encontrada.")
    return src


def _validate_default_account(db: Session, user_id: int, account_id: int | None) -> None:
    if account_id is None:
        return
    acc = (
        db.query(BankAccount)
        .filter(BankAccount.id == account_id, BankAccount.user_id == user_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="Conta padrão de recebimento não encontrada.")


@router.get("/income-sources", response_model=list[IncomeSourceOut], summary="Listar fontes de entrada")
def list_income_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[IncomeSourceOut]:
    return (
        db.query(IncomeSource)
        .filter(IncomeSource.user_id == current_user.id)
        .order_by(IncomeSource.name)
        .all()
    )


@router.post("/income-sources", response_model=IncomeSourceOut, summary="Criar fonte de entrada")
def create_income_source(
    body: IncomeSourceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeSourceOut:
    _validate_default_account(db, current_user.id, body.default_account_id)
    src = IncomeSource(
        user_id=current_user.id,
        name=body.name.strip(),
        type=body.type,
        nature=body.nature,
        default_account_id=body.default_account_id,
        expected_amount=body.expected_amount,
        frequency=body.frequency,
        description=body.description.strip() if body.description else None,
        is_active=body.is_active,
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


@router.patch("/income-sources/{income_source_id}", response_model=IncomeSourceOut, summary="Editar fonte de entrada")
def update_income_source(
    income_source_id: int,
    body: IncomeSourceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IncomeSourceOut:
    src = _get_owned_income_source(db, current_user.id, income_source_id)

    if body.name is not None:
        src.name = body.name.strip()
    if body.type is not None:
        src.type = body.type
    if body.nature is not None:
        src.nature = body.nature
    if body.default_account_id is not None:
        _validate_default_account(db, current_user.id, body.default_account_id)
        src.default_account_id = body.default_account_id
    if body.expected_amount is not None:
        src.expected_amount = body.expected_amount
    if body.frequency is not None:
        src.frequency = body.frequency
    if body.description is not None:
        src.description = body.description.strip() or None
    if body.is_active is not None:
        src.is_active = body.is_active

    db.commit()
    db.refresh(src)
    return src


@router.delete("/income-sources/{income_source_id}", summary="Remover fonte de entrada")
def delete_income_source(
    income_source_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    src = _get_owned_income_source(db, current_user.id, income_source_id)
    db.delete(src)
    db.commit()
    return {"deleted": True}
