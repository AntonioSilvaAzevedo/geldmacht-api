from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.category import Category
from ..models.credit_card import CreditCard
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


def _validate_card_for_user(db: Session, user_id: int, card_id: int | None) -> None:
    """Garante que o card pertence ao usuário (ou é null = todos os cartões)."""
    if card_id is None or card_id == 0:
        return
    card = db.query(CreditCard).filter(
        CreditCard.id == card_id,
        CreditCard.user_id == user_id,
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")


def _validate_parent_for_user(
    db: Session,
    user_id: int,
    parent_id: int | None,
    scope: str,
    card_id: int | None,
    self_id: int | None = None,
) -> Category | None:
    """
    Valida regras da categoria pai:
      - existe e pertence ao usuário;
      - não é subcategoria (sem hierarquia > 1 nível);
      - mesmo scope da subcategoria;
      - card_id da subcategoria deve ser igual ao da pai (ou pai global → sub também global ou específica).
        Recomendação: sub herda card_id da pai; se enviar card_id divergente, rejeitar.
      - não pode apontar para a própria categoria.
    """
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
    if parent.scope != scope:
        raise HTTPException(
            status_code=400,
            detail="Subcategoria deve ter o mesmo escopo da categoria pai.",
        )
    # Regra de card: subcategoria deve respeitar a categoria pai.
    parent_card = parent.card_id
    sub_card = card_id if card_id != 0 else None
    if parent_card is not None and sub_card not in (None, parent_card):
        raise HTTPException(
            status_code=400,
            detail="Subcategoria deve ter o mesmo cartão da categoria pai (ou herdar).",
        )
    return parent


@router.get("/categories", response_model=list[CategoryOut], summary="Listar categorias")
def list_categories(
    scope: str | None = Query(None),
    card_id: int | None = Query(
        None,
        description=(
            "Filtra categorias aplicáveis a um cartão. Quando enviado, retorna "
            "categorias globais (card_id=null) + categorias específicas do cartão."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CategoryOut]:
    query = db.query(Category).filter(Category.user_id == current_user.id)
    if scope:
        if scope not in VALID_CATEGORY_SCOPES:
            raise HTTPException(status_code=422, detail="Escopo de categoria inválido.")
        query = query.filter(Category.scope == scope)
    if card_id is not None:
        # Valida que o cartão é do usuário (404 se for de outro).
        _validate_card_for_user(db, current_user.id, card_id)
        query = query.filter(or_(Category.card_id.is_(None), Category.card_id == card_id))
    # Ordena apenas por nome — o frontend agrupa parents/subs via parent_id.
    # Mantém compatibilidade entre PostgreSQL (produção) e SQLite (testes).
    return query.order_by(Category.name).all()


@router.post("/categories", response_model=CategoryOut, summary="Criar categoria")
def create_category(
    body: CategoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CategoryOut:
    # 0 vindo do frontend = "global / sem pai"; normaliza para None
    card_id = body.card_id if (body.card_id and body.card_id > 0) else None
    parent_id = body.parent_id if (body.parent_id and body.parent_id > 0) else None

    _validate_card_for_user(db, current_user.id, card_id)
    parent = _validate_parent_for_user(db, current_user.id, parent_id, body.scope, card_id)

    # Se a pai tem card específico e a sub não enviou card_id, herda da pai.
    effective_card_id = card_id
    if parent is not None and effective_card_id is None:
        effective_card_id = parent.card_id

    category = Category(
        user_id=current_user.id,
        name=body.name.strip(),
        scope=body.scope,
        color=body.color,
        icon=body.icon,
        card_id=effective_card_id,
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
    if body.scope is not None:
        category.scope = body.scope
    if body.color is not None:
        category.color = body.color or None
    # icon: None means "no change", empty string means "clear icon"
    if body.icon is not None:
        category.icon = body.icon or None

    # card_id: None = não altera; 0 = limpa (global); >0 = define
    if body.card_id is not None:
        new_card_id: int | None = None if body.card_id == 0 else body.card_id
        _validate_card_for_user(db, current_user.id, new_card_id)
        category.card_id = new_card_id
        # Se viraram subcategoria de uma categoria com card específico, manter coerência.
        if category.parent_id is not None and category.parent is not None:
            parent_card = category.parent.card_id
            if parent_card is not None and new_card_id not in (None, parent_card):
                raise HTTPException(
                    status_code=400,
                    detail="Subcategoria deve ter o mesmo cartão da categoria pai (ou herdar).",
                )

    # parent_id: None = não altera; 0 = limpa; >0 = define
    if body.parent_id is not None:
        new_parent_id: int | None = None if body.parent_id == 0 else body.parent_id
        if new_parent_id is None:
            # Vira categoria principal
            category.parent_id = None
        else:
            # Não pode virar subcategoria se já é pai de alguém
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
                db, current_user.id, new_parent_id, category.scope, category.card_id, self_id=category.id,
            )
            category.parent_id = parent.id if parent else None
            # Herda card_id se a pai for específica e a sub não tiver card definido
            if parent and parent.card_id is not None and category.card_id is None:
                category.card_id = parent.card_id

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
