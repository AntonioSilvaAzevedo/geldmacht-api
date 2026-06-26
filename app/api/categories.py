from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.category import Category
from ..models.transaction import Transaction
from ..models.user import User
from ..schemas.category import CategoryCreate, CategoryOut, CategorySuggestion, CategoryUpdate
from ..services.recurrence_service import SYSTEM_SUGGESTIONS

router = APIRouter()


def _get_user_category(db: Session, user_id: int, category_id: int) -> Category:
    category = db.query(Category).filter(
        Category.id == category_id,
        Category.user_id == user_id,
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    return category


def _validate_parent_for_user(
    db: Session,
    user_id: int,
    parent_id: int | None,
    self_id: int | None = None,
) -> Category | None:
    if parent_id is None or parent_id == 0:
        return None
    if self_id is not None and parent_id == self_id:
        raise HTTPException(status_code=400, detail="Categoria não pode ser pai dela mesma.")

    parent = db.query(Category).filter(
        Category.id == parent_id,
        Category.user_id == user_id,
    ).first()
    if not parent:
        raise HTTPException(status_code=404, detail="Categoria pai não encontrada.")
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Não é permitido criar subcategoria de subcategoria.",
        )
    return parent


@router.get("/categories", response_model=list[CategoryOut], summary="Listar categorias")
def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CategoryOut]:
    return (
        db.query(Category)
        .filter(Category.user_id == current_user.id)
        .order_by(Category.name)
        .all()
    )


@router.get(
    "/categories/suggestions",
    response_model=list[CategorySuggestion],
    summary="Categorias sugeridas pelo sistema ainda não usadas pelo usuário",
)
def list_category_suggestions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CategorySuggestion]:
    existing_keys = {
        row[0]
        for row in db.query(Category.system_key)
        .filter(Category.user_id == current_user.id, Category.system_key.isnot(None))
        .all()
    }
    return [CategorySuggestion(**s) for s in SYSTEM_SUGGESTIONS if s["key"] not in existing_keys]


@router.post(
    "/categories/suggestions/{key}",
    response_model=CategoryOut,
    summary="Ativar uma categoria sugerida (idempotente)",
)
def accept_category_suggestion(
    key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryOut:
    suggestion = next((s for s in SYSTEM_SUGGESTIONS if s["key"] == key), None)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Sugestão não encontrada.")

    existing = (
        db.query(Category)
        .filter(Category.user_id == current_user.id, Category.system_key == key)
        .first()
    )
    if existing:
        return existing

    category = Category(
        user_id=current_user.id,
        name=suggestion["name"],
        scope="global",
        system_key=key,
        applies_to_bank=True,
        applies_to_credit_card=True,
        icon=suggestion.get("icon"),
    )
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.post("/categories", response_model=CategoryOut, summary="Criar categoria")
def create_category(
    body: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryOut:
    parent_id = body.parent_id if (body.parent_id and body.parent_id > 0) else None
    parent = _validate_parent_for_user(db, current_user.id, parent_id)

    category = Category(
        user_id=current_user.id,
        name=body.name.strip(),
        scope=body.scope or "global",
        applies_to_bank=True,
        applies_to_credit_card=True,
        color=body.color,
        icon=body.icon,
        card_id=None,
        parent_id=parent.id if parent else None,
        invoice_budget_limit=body.invoice_budget_limit,
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
    if body.color is not None:
        category.color = body.color or None
    # icon: None means "no change", empty string means "clear icon"
    if body.icon is not None:
        category.icon = body.icon or None

    # parent_id: None = não altera; 0 = limpa; >0 = define
    if body.parent_id is not None:
        new_parent_id: int | None = None if body.parent_id == 0 else body.parent_id
        if new_parent_id is None:
            category.parent_id = None
        else:
            has_children = db.query(Category).filter(
                Category.parent_id == category.id,
                Category.user_id == current_user.id,
            ).count() > 0
            if has_children:
                raise HTTPException(
                    status_code=400,
                    detail="Categoria possui subcategorias e não pode virar subcategoria.",
                )
            parent = _validate_parent_for_user(
                db, current_user.id, new_parent_id, self_id=category.id,
            )
            category.parent_id = parent.id if parent else None

    # invoice_budget_limit: None = não altera; 0 = remove; >0 = define
    if body.invoice_budget_limit is not None:
        if body.invoice_budget_limit == 0:
            category.invoice_budget_limit = None
        else:
            if body.invoice_budget_limit < 0:
                raise HTTPException(status_code=422, detail="Limite deve ser maior que zero.")
            category.invoice_budget_limit = float(body.invoice_budget_limit)

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
    # IDs a desvincular: a própria categoria + todas suas subcategorias
    sub_ids = [
        c.id for c in db.query(Category).filter(
            Category.parent_id == category.id,
            Category.user_id == current_user.id,
        ).all()
    ]
    affected_ids = [category.id] + sub_ids
    db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.category_id.in_(affected_ids),
    ).update({Transaction.category_id: None, Transaction.category: None}, synchronize_session=False)
    db.delete(category)  # cascade remove subcategorias via FK
    db.commit()
    return {"deleted": True}
