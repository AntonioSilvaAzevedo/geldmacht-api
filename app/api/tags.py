from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.transaction import Transaction
from ..models.user import User
from ..schemas.tag import SetTransactionTagsRequest, TagOut
from ..services.tag_service import list_user_tags, set_transaction_tags

router = APIRouter()


@router.get(
    "/tags",
    response_model=list[TagOut],
    summary="Listar tags do usuário",
    description="Retorna as tags do usuário autenticado, para reuso na seleção de tags de lançamentos.",
)
def get_tags(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TagOut]:
    return list_user_tags(db, current_user.id)


@router.put(
    "/transactions/{transaction_id}/tags",
    response_model=list[TagOut],
    summary="Definir as tags de um lançamento",
    description=(
        "Substitui o conjunto de tags do lançamento pela lista enviada. "
        "Nomes são normalizados (trim, espaços duplicados, case-insensitive) e "
        "tags existentes do usuário são reaproveitadas, sem duplicar."
    ),
)
def put_transaction_tags(
    transaction_id: int,
    body: SetTransactionTagsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TagOut]:
    tx = (
        db.query(Transaction)
        .options(selectinload(Transaction.tags))
        .filter(Transaction.id == transaction_id, Transaction.user_id == current_user.id)
        .first()
    )
    if not tx:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado.")

    tags = set_transaction_tags(db, tx, body.names)
    db.commit()
    return sorted(tags, key=lambda t: t.name.casefold())
