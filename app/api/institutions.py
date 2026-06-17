from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.bank_account import BankAccount
from ..models.credit_card import CreditCard
from ..models.institution import Institution
from ..models.user import User
from ..schemas.institution import InstitutionCreate, InstitutionOut
from ..services.institution_service import delete_institution_cascade

router = APIRouter()


def get_owned_institution(db: Session, user_id: int, institution_id: int) -> Institution:
    inst = (
        db.query(Institution)
        .filter(Institution.id == institution_id, Institution.user_id == user_id)
        .first()
    )
    if not inst:
        raise HTTPException(status_code=404, detail="Instituição não encontrada.")
    return inst


def _serialize(inst: Institution, account_count: int, card_count: int) -> InstitutionOut:
    return InstitutionOut(
        id=inst.id,
        user_id=inst.user_id,
        name=inst.name,
        created_at=inst.created_at,
        updated_at=inst.updated_at,
        account_count=int(account_count or 0),
        card_count=int(card_count or 0),
    )


@router.get("/institutions", response_model=list[InstitutionOut], summary="Listar instituições")
def list_institutions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InstitutionOut]:
    rows = (
        db.query(
            Institution,
            func.count(func.distinct(BankAccount.id)).label("account_count"),
            func.count(func.distinct(CreditCard.id)).label("card_count"),
        )
        .outerjoin(BankAccount, BankAccount.institution_id == Institution.id)
        .outerjoin(CreditCard, CreditCard.institution_id == Institution.id)
        .filter(Institution.user_id == current_user.id)
        .group_by(Institution.id)
        .order_by(Institution.name)
        .all()
    )
    return [_serialize(inst, account_count, card_count) for inst, account_count, card_count in rows]


@router.post("/institutions", response_model=InstitutionOut, summary="Criar instituição")
def create_institution(
    body: InstitutionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InstitutionOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Nome da instituição é obrigatório.")
    existing = (
        db.query(Institution)
        .filter(Institution.user_id == current_user.id, Institution.name == name)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Instituição já cadastrada.")
    inst = Institution(user_id=current_user.id, name=name)
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return _serialize(inst, 0, 0)


@router.delete("/institutions/{institution_id}", summary="Excluir instituição e dados vinculados")
def delete_institution(
    institution_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    inst = get_owned_institution(db, current_user.id, institution_id)
    delete_institution_cascade(db, current_user.id, inst)
    return {"deleted": True}
