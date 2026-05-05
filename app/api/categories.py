from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.category import Category
from ..models.transaction import Transaction
from ..models.user import User
from ..schemas.category import CategoryCreate, CategoryOut, CategoryUpdate, VALID_CATEGORY_SCOPES

router = APIRouter()


def _get_user_category(db: Session, user_id: int, category_id: int) -> Category:
    category = db.query(Category).filter(
        Category.id == category_id,
        Category.user_id == user_id,
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    return category


@router.get("/categories", response_model=list[CategoryOut], summary="Listar categorias")
def list_categories(
    scope: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CategoryOut]:
    query = db.query(Category).filter(Category.user_id == current_user.id)
    if scope:
        if scope not in VALID_CATEGORY_SCOPES:
            raise HTTPException(status_code=422, detail="Escopo de categoria inválido.")
        query = query.filter(Category.scope == scope)
    return query.order_by(Category.name).all()


@router.post("/categories", response_model=CategoryOut, summary="Criar categoria")
def create_category(
    body: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryOut:
    category = Category(
        user_id=current_user.id,
        name=body.name.strip(),
        scope=body.scope,
        color=body.color,
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=CategoryOut, summary="Editar categoria")
def update_category(
    category_id: int,
    body: CategoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryOut:
    category = _get_user_category(db, current_user.id, category_id)
    if body.name is not None:
        category.name = body.name.strip()
    if body.scope is not None:
        category.scope = body.scope
    if body.color is not None:
        category.color = body.color or None
    db.commit()
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", summary="Remover categoria")
def delete_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    category = _get_user_category(db, current_user.id, category_id)
    db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.category_id == category.id,
    ).update({Transaction.category_id: None, Transaction.category: None})
    db.delete(category)
    db.commit()
    return {"deleted": True}
