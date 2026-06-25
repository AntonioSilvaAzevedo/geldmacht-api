import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, literal
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..middleware.auth import get_current_user
from ..models.credit_card import CreditCard
from ..models.invoice import Invoice
from ..models.transaction import Transaction
from ..models.user import User
from ..schemas.credit_card import CreditCardCreate, CreditCardOut, CreditCardUpdate
from ..models.category import Category
from ..schemas.invoice import (
    AnnualInvoiceMonth,
    CardDashboardResponse,
    InvoiceListItem,
    InvoiceMini,
    PredictedInvoiceResponse,
    TopCategoryItem,
)
from ..schemas.transaction import InvoiceDetailResponse
from ..models.recurring_expense import RecurringExpense
from ..schemas.recurring_expense import RecurringExpenseCreate, RecurringExpenseOut
from ..services.institution_service import delete_card_records
from ..services.invoice_projection import (
    annual_card_invoices,
    current_month,
    default_year,
    invoice_net_total_expr,
    predicted_invoice_composition,
)
from ..services.summary_service import calculate_invoice_summary
from ..services.transaction_serialization import serialize_transaction_out
from .institutions import get_owned_institution

router = APIRouter()
logger = logging.getLogger(__name__)

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
    institution_id = None
    institution = body.institution.strip() if body.institution else None
    if body.institution_id is not None:
        inst = get_owned_institution(db, current_user.id, body.institution_id)
        institution_id = inst.id
        institution = inst.name
    card = CreditCard(
        user_id=current_user.id,
        name=body.name.strip(),
        institution=institution,
        institution_id=institution_id,
        closing_day=body.closing_day,
        due_day=body.due_day,
        credit_limit=body.credit_limit,
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
    # credit_limit: None = não altera; 0 = remove; >0 = define.
    if body.credit_limit is not None:
        if body.credit_limit == 0:
            card.credit_limit = None
        else:
            if body.credit_limit < 0:
                raise HTTPException(status_code=422, detail="Limite do cartão deve ser maior que zero.")
            card.credit_limit = float(body.credit_limit)
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
    delete_card_records(db, current_user.id, card)
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

    _net_total = invoice_net_total_expr()
    _expense_count = func.sum(
        case((Transaction.amount < 0, literal(1)), else_=literal(0))
    )

    rows = (
        db.query(
            Invoice,
            _expense_count.label("transactions_count"),
            _net_total.label("computed_total"),
        )
        .outerjoin(Transaction, Transaction.invoice_id == Invoice.id)
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
            computed_total=round(float(invoice.total_amount if invoice.total_amount is not None else (total or 0)), 2),
            transactions_count=int(count or 0),
            label=_label_for_due_month(invoice.due_month),
        ))
    return result


@router.get(
    "/cards/{card_id}/annual-invoices",
    response_model=list[AnnualInvoiceMonth],
    summary="Faturas do ano (reais + previstas)",
    description=(
        "Retorna apenas os meses do ano com fatura real ou previsão "
        "(parcelas futuras), com total e marca de previsto."
    ),
)
def list_annual_card_invoices(
    card_id: int,
    year: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AnnualInvoiceMonth]:
    _get_user_card(db, current_user.id, card_id)
    target_year = year or default_year()
    return annual_card_invoices(db, current_user.id, card_id, target_year)


@router.get(
    "/cards/{card_id}/predicted-invoices/{due_month}",
    response_model=PredictedInvoiceResponse,
    summary="Composição de uma fatura prevista",
    description=(
        "Retorna os itens que compõem a previsão de um mês (parcelas restantes "
        "da fatura real mais recente + assinaturas recorrentes ativas) e o total previsto."
    ),
)
def get_predicted_invoice(
    card_id: int,
    due_month: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PredictedInvoiceResponse:
    _get_user_card(db, current_user.id, card_id)
    composition = predicted_invoice_composition(db, current_user.id, card_id, due_month)
    if composition is None:
        raise HTTPException(status_code=404, detail="Fatura prevista não encontrada para este mês.")
    return composition


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
            joinedload(Transaction.category_ref).joinedload(Category.parent),
        )
        .filter(
            Transaction.invoice_id == invoice_id,
            Transaction.user_id    == current_user.id,
        )
        .order_by(Transaction.date.desc())
        .all()
    )

    with_category_id = sum(1 for tx in transactions_rows if tx.category_id is not None)
    missing_category_ref = sum(
        1
        for tx in transactions_rows
        if tx.category_id is not None and tx.category_ref is None
    )
    logger.info(
        "Invoice detail categories: user_id=%s card_id=%s invoice_id=%s tx_count=%s tx_with_category_id=%s tx_missing_category_ref=%s",
        current_user.id,
        card_id,
        invoice_id,
        len(transactions_rows),
        with_category_id,
        missing_category_ref,
    )
    if missing_category_ref:
        logger.warning(
            "Invoice detail has transactions with category_id but no Category row: user_id=%s card_id=%s invoice_id=%s missing=%s",
            current_user.id,
            card_id,
            invoice_id,
            missing_category_ref,
        )

    transactions_out = [serialize_transaction_out(tx) for tx in transactions_rows]
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
    "/cards/{card_id}/dashboard",
    response_model=CardDashboardResponse,
    summary="Visão geral / dashboard do cartão",
    description=(
        "Retorna métricas agregadas para a página /cartao/[cardId]: "
        "última fatura, média mensal, maior fatura, parcelas futuras, "
        "evolução das faturas, categorias principais e faturas recentes."
    ),
)
def get_card_dashboard(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CardDashboardResponse:
    _get_user_card(db, current_user.id, card_id)

    # 1. Faturas + total computado: sum(|despesas|) - sum(créditos/estornos)
    _dash_net_total = func.coalesce(
        func.sum(
            case(
                (Transaction.amount < 0, func.abs(Transaction.amount)),
                (
                    and_(Transaction.amount > 0, Transaction.is_payment == False),
                    -Transaction.amount,
                ),
                else_=literal(0.0),
            )
        ),
        0.0,
    )

    invoice_rows = (
        db.query(
            Invoice,
            _dash_net_total.label("computed_total"),
        )
        .outerjoin(Transaction, Transaction.invoice_id == Invoice.id)
        .filter(
            Invoice.card_id == card_id,
            Invoice.user_id == current_user.id,
        )
        .group_by(Invoice.id)
        .order_by(Invoice.due_month.desc())
        .all()
    )

    def _to_mini(invoice: Invoice, computed_total: float) -> InvoiceMini:
        return InvoiceMini(
            id=invoice.id,
            due_month=invoice.due_month,
            due_date=invoice.due_date,
            total_amount=invoice.total_amount,
            computed_total=round(float(invoice.total_amount if invoice.total_amount is not None else (computed_total or 0)), 2),
        )

    minis = [_to_mini(inv, total) for inv, total in invoice_rows]
    invoice_count = len(minis)

    # 2. Última fatura
    latest_invoice = minis[0] if minis else None

    # 3. Média mensal — usa total_amount quando existir, senão computed_total
    def _value_of(m: InvoiceMini) -> float:
        return float(m.total_amount if m.total_amount is not None else m.computed_total)

    monthly_average = (
        round(sum(_value_of(m) for m in minis) / invoice_count, 2)
        if invoice_count
        else 0.0
    )

    # 4. Maior fatura
    highest_invoice = max(minis, key=_value_of, default=None) if minis else None

    # 5. Parcelas futuras estimadas (apenas a partir da última fatura)
    future_installments_total = 0.0
    if latest_invoice is not None:
        installment_rows = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == current_user.id,
                Transaction.invoice_id == latest_invoice.id,
                Transaction.amount < 0,
                Transaction.installment_current.isnot(None),
                Transaction.installment_total.isnot(None),
            )
            .all()
        )
        for tx in installment_rows:
            if (
                tx.installment_total is not None
                and tx.installment_current is not None
                and tx.installment_total > 1
            ):
                remaining = tx.installment_total - tx.installment_current
                if remaining > 0:
                    future_installments_total += abs(float(tx.amount)) * remaining
        future_installments_total = round(future_installments_total, 2)

    # 6. Evolução: ordem cronológica crescente (últimas 12)
    invoice_evolution = list(reversed(minis[:12]))

    # 7. Categorias principais a partir das transactions de TODAS as faturas
    top_rows = (
        db.query(
            Transaction.category_id,
            Category.name,
            Category.icon,
            func.sum(func.abs(Transaction.amount)).label("total"),
        )
        .outerjoin(Category, Category.id == Transaction.category_id)
        .filter(
            Transaction.user_id == current_user.id,
            Transaction.card_id == card_id,
            Transaction.amount < 0,
            Transaction.category_id.isnot(None),
        )
        .group_by(Transaction.category_id, Category.name, Category.icon)
        .order_by(func.sum(func.abs(Transaction.amount)).desc())
        .limit(5)
        .all()
    )
    top_categories = [
        TopCategoryItem(
            category_id=row.category_id,
            name=row.name or "Sem nome",
            icon=row.icon,
            total=round(float(row.total or 0), 2),
        )
        for row in top_rows
    ]

    # 8. Faturas recentes (últimas 5)
    recent_invoices = minis[:5]

    return CardDashboardResponse(
        card_id=card_id,
        invoice_count=invoice_count,
        latest_invoice=latest_invoice,
        monthly_average=monthly_average,
        highest_invoice=highest_invoice,
        future_installments_total=future_installments_total,
        invoice_evolution=invoice_evolution,
        top_categories=top_categories,
        recent_invoices=recent_invoices,
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


@router.get(
    "/cards/{card_id}/recurring",
    response_model=list[RecurringExpenseOut],
    summary="Listar assinaturas recorrentes do cartão",
)
def list_card_recurring(
    card_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RecurringExpenseOut]:
    _get_user_card(db, current_user.id, card_id)
    return (
        db.query(RecurringExpense)
        .filter(
            RecurringExpense.card_id == card_id,
            RecurringExpense.user_id == current_user.id,
            RecurringExpense.active.is_(True),
        )
        .order_by(RecurringExpense.description)
        .all()
    )


@router.post(
    "/cards/{card_id}/recurring",
    response_model=RecurringExpenseOut,
    summary="Marcar lançamento como assinatura recorrente",
)
def create_card_recurring(
    card_id: int,
    body: RecurringExpenseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecurringExpenseOut:
    _get_user_card(db, current_user.id, card_id)
    if body.category_id is not None:
        owns_category = db.query(Category).filter(
            Category.id == body.category_id,
            Category.user_id == current_user.id,
        ).first()
        if not owns_category:
            raise HTTPException(status_code=404, detail="Categoria não encontrada.")
    recurring = RecurringExpense(
        user_id=current_user.id,
        card_id=card_id,
        description=body.description.strip(),
        amount=body.amount,
        category_id=body.category_id,
        start_month=body.start_month or current_month(),
        active=True,
    )
    db.add(recurring)
    db.commit()
    db.refresh(recurring)
    return recurring


@router.delete(
    "/cards/{card_id}/recurring/{recurring_id}",
    summary="Remover assinatura recorrente",
)
def delete_card_recurring(
    card_id: int,
    recurring_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    _get_user_card(db, current_user.id, card_id)
    recurring = db.query(RecurringExpense).filter(
        RecurringExpense.id == recurring_id,
        RecurringExpense.card_id == card_id,
        RecurringExpense.user_id == current_user.id,
    ).first()
    if not recurring:
        raise HTTPException(status_code=404, detail="Assinatura não encontrada.")
    db.delete(recurring)
    db.commit()
    return {"deleted": True}
