from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.credit_card import CreditCard
from ..models.invoice import Invoice
from ..models.transaction import Transaction
from ..models.user import User
from ..schemas.credit_card import CreditCardCreate, CreditCardOut, CreditCardUpdate
from ..schemas.invoice import InvoiceListItem
from ..schemas.transaction import InvoiceDetailResponse, TransactionOut
from ..services.summary_service import calculate_invoice_summary

router = APIRouter()

_MONTH_LABELS = {
    "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
    "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
    "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro",
}


def _get_user_card(db: Session, user_id: int, card_id: int) -> CreditCard:
    card = db.query(CreditCard).filter(
        CreditCard.id == card_id,
        CreditCard.user_id == user_id,
    ).first()
    if not card:
        raise HTTPException(status_code=404, detail="Cartão não encontrado.")
    return card


def _label_for_due_month(due_month: str) -> str:
    """Gera label legível para o mês de vencimento: 'Vencimento em Abril/2026'."""
    try:
        year, month = due_month.split("-")
        return f"Vencimento em {_MONTH_LABELS.get(month, month)}/{year}"
    except ValueError:
        return due_month


def _serialize_transaction(tx: Transaction) -> TransactionOut:
    out = TransactionOut.model_validate(tx)
    out.account_type = tx.account.type if tx.account else None
    out.category_name = tx.category_ref.name if tx.category_ref else tx.category
    return out


@router.get("/cards", response_model=list[CreditCardOut], summary="Listar cartões")
def list_cards(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CreditCardOut]:
    return db.query(CreditCard).filter(CreditCard.user_id == current_user.id).order_by(CreditCard.name).all()


@router.get("/cards/{card_id}", response_model=CreditCardOut, summary="Buscar cartão")
def get_card(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    return _get_user_card(db, current_user.id, card_id)


@router.post("/cards", response_model=CreditCardOut, summary="Criar cartão")
def create_card(
    body: CreditCardCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    card = CreditCard(
        user_id=current_user.id,
        name=body.name.strip(),
        institution=body.institution.strip() if body.institution else None,
        closing_day=body.closing_day,
        due_day=body.due_day,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return card


@router.patch("/cards/{card_id}", response_model=CreditCardOut, summary="Editar cartão")
def update_card(
    card_id: int,
    body: CreditCardUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreditCardOut:
    card = _get_user_card(db, current_user.id, card_id)
    if body.name is not None:
        card.name = body.name.strip()
    if body.institution is not None:
        card.institution = body.institution.strip() or None
    if body.closing_day is not None:
        card.closing_day = body.closing_day
    if body.due_day is not None:
        card.due_day = body.due_day
    db.commit()
    db.refresh(card)
    return card


@router.delete("/cards/{card_id}", summary="Remover cartão e faturas vinculadas")
def delete_card(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    card = _get_user_card(db, current_user.id, card_id)
    # Limpa invoice_id das transactions antes de excluir invoices (FK SET NULL)
    db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.card_id == card.id,
    ).update({"invoice_id": None}, synchronize_session=False)
    # Exclui transactions do cartão
    db.query(Transaction).filter(
        Transaction.user_id == current_user.id,
        Transaction.card_id == card.id,
    ).delete(synchronize_session=False)
    # Exclui invoices do cartão
    db.query(Invoice).filter(
        Invoice.user_id == current_user.id,
        Invoice.card_id == card.id,
    ).delete(synchronize_session=False)
    db.delete(card)
    db.commit()
    return {"deleted": True}


@router.get(
    "/cards/{card_id}/invoices",
    response_model=list[InvoiceListItem],
    summary="Listar faturas reais do cartão",
    description=(
        "Retorna invoices da tabela Invoice para o cartão informado, "
        "com total calculado a partir das transactions vinculadas."
    ),
)
def list_card_invoices(
    card_id: int,
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InvoiceListItem]:
    _get_user_card(db, current_user.id, card_id)

    # Agrupa total e contagem por invoice
    rows = (
        db.query(
            Invoice,
            func.count(Transaction.id).label("transactions_count"),
            func.sum(func.abs(Transaction.amount)).label("computed_total"),
        )
        .outerjoin(
            Transaction,
            and_(
                Transaction.invoice_id == Invoice.id,
                Transaction.amount < 0,
            ),
        )
        .filter(
            Invoice.card_id == card_id,
            Invoice.user_id == current_user.id,
        )
        .group_by(Invoice.id)
        .order_by(Invoice.due_month.desc())
        .limit(limit)
        .all()
    )

    result: list[InvoiceListItem] = []
    for invoice, count, total in rows:
        result.append(InvoiceListItem(
            id=invoice.id,
            card_id=invoice.card_id,
            due_month=invoice.due_month,
            due_date=invoice.due_date,
            cycle_start_date=invoice.cycle_start_date,
            cycle_end_date=invoice.cycle_end_date,
            total_amount=invoice.total_amount,
            computed_total=round(float(total or 0), 2),
            transactions_count=int(count or 0),
            label=_label_for_due_month(invoice.due_month),
        ))
    return result


@router.get(
    "/cards/{card_id}/invoices/{invoice_id}",
    response_model=InvoiceDetailResponse,
    summary="Detalhes de uma fatura",
    description=(
        "Retorna a fatura com metadados completos (due_date, ciclo, total), "
        "as transactions vinculadas ao invoice_id e o summary calculado."
    ),
)
def get_invoice_detail(
    card_id: int,
    invoice_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceDetailResponse:
    _get_user_card(db, current_user.id, card_id)

    invoice = db.query(Invoice).filter(
        Invoice.id      == invoice_id,
        Invoice.card_id == card_id,
        Invoice.user_id == current_user.id,
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")

    transactions_rows = (
        db.query(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.category_ref),
        )
        .filter(
            Transaction.invoice_id == invoice_id,
            Transaction.user_id    == current_user.id,
        )
        .order_by(Transaction.date.desc())
        .all()
    )

    transactions_out = [_serialize_transaction(tx) for tx in transactions_rows]
    summary = calculate_invoice_summary([tx.model_dump() for tx in transactions_out])

    return InvoiceDetailResponse(
        id=invoice.id,
        card_id=invoice.card_id,
        due_month=invoice.due_month,
        due_date=invoice.due_date,
        cycle_start_date=invoice.cycle_start_date,
        cycle_end_date=invoice.cycle_end_date,
        issue_date=invoice.issue_date,
        closing_date=invoice.closing_date,
        total_amount=invoice.total_amount,
        source=invoice.source,
        raw_reference_month=invoice.raw_reference_month,
        created_at=invoice.created_at,
        transactions=transactions_out,
        summary=summary,
    )


@router.get(
    "/cards/{card_id}/invoices-by-month/{due_month}",
    response_model=InvoiceDetailResponse,
    summary="Fatura do cartão por mês de vencimento",
    description=(
        "Compatibilidade com a rota legada /cartao/[cardId]/[anoMes]. "
        "Busca invoice por user_id + card_id + due_month."
    ),
)
def get_invoice_by_month(
    card_id: int,
    due_month: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceDetailResponse:
    _get_user_card(db, current_user.id, card_id)

    invoice = db.query(Invoice).filter(
        Invoice.card_id   == card_id,
        Invoice.user_id   == current_user.id,
        Invoice.due_month == due_month,
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada para este mês.")

    return get_invoice_detail(card_id, invoice.id, current_user, db)
