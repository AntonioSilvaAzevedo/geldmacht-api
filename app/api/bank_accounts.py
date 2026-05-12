"""CRUD de contas bancárias do usuário ( âncora para lançamentos manuais e futuros extratos )."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.bank_account import BankAccount
from ..models.import_batch import ImportBatch
from ..models.user import User
from ..schemas.bank_account import BankAccountCreate, BankAccountOut, BankAccountUpdate
from ..schemas.import_batch import ImportBatchOut

router = APIRouter()


def _get_owned_account(db: Session, user_id: int, account_id: int) -> BankAccount:
    acc = (
        db.query(BankAccount)
        .filter(BankAccount.id == account_id, BankAccount.user_id == user_id)
        .first()
    )
    if not acc:
        raise HTTPException(status_code=404, detail="Conta bancária não encontrada.")
    return acc


@router.get("/bank-accounts", response_model=list[BankAccountOut], summary="Listar contas bancárias")
def list_bank_accounts(
    include_inactive: bool = Query(
        False,
        description="Quando true, inclui contas desativadas (gestão). Padrão: só ativas.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[BankAccountOut]:
    q = db.query(BankAccount).filter(BankAccount.user_id == current_user.id)
    if not include_inactive:
        q = q.filter(BankAccount.is_active.is_(True))
    return q.order_by(BankAccount.name).all()


@router.get(
    "/bank-accounts/{account_id}/import-batches",
    response_model=list[ImportBatchOut],
    summary="Histórico de importações de extrato (OFX) desta conta",
)
def list_bank_account_import_batches(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ImportBatchOut]:
    _get_owned_account(db, current_user.id, account_id)
    rows = (
        db.query(ImportBatch)
        .filter(
            ImportBatch.bank_account_id == account_id,
            ImportBatch.user_id == current_user.id,
        )
        .order_by(ImportBatch.id.desc())
        .all()
    )
    return rows


@router.get("/bank-accounts/{account_id}", response_model=BankAccountOut, summary="Obter conta bancária")
def get_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BankAccountOut:
    return _get_owned_account(db, current_user.id, account_id)


@router.post("/bank-accounts", response_model=BankAccountOut, summary="Criar conta bancária")
def create_bank_account(
    body: BankAccountCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BankAccountOut:
    acc = BankAccount(
        user_id=current_user.id,
        name=body.name.strip(),
        institution=body.institution.strip() if body.institution else None,
        account_type=body.account_type,
        currency=body.currency or "BRL",
        is_active=body.is_active,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@router.patch("/bank-accounts/{account_id}", response_model=BankAccountOut, summary="Editar conta bancária")
def patch_bank_account(
    account_id: int,
    body: BankAccountUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BankAccountOut:
    acc = _get_owned_account(db, current_user.id, account_id)
    if body.name is not None:
        acc.name = body.name.strip()
    if body.institution is not None:
        acc.institution = body.institution.strip() or None
    if body.account_type is not None:
        acc.account_type = body.account_type
    if body.currency is not None:
        acc.currency = body.currency or "BRL"
    if body.is_active is not None:
        acc.is_active = body.is_active
    db.commit()
    db.refresh(acc)
    return acc


@router.delete("/bank-accounts/{account_id}", summary="Desativar conta bancária")
def delete_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Soft delete — preserva transações vinculadas."""
    acc = _get_owned_account(db, current_user.id, account_id)
    acc.is_active = False
    db.commit()
    return {"deleted": True}
