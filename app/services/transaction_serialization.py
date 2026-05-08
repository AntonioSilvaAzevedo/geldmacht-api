"""Serialização de Transaction → TransactionOut com dados de categoria hierárquica."""

from app.models.transaction import Transaction
from app.schemas.transaction import TransactionOut


def serialize_transaction_out(tx: Transaction) -> TransactionOut:
    """
    Preenche TransactionOut a partir do ORM, incluindo nome em hierarquia (pai/filha),
    ícone e limite da categoria vinculada quando `category_ref` (e opcionalmente
    `category_ref.parent`) estiver carregado.
    """
    out = TransactionOut.model_validate(tx)
    out.account_type = tx.account.type if tx.account else None

    cref = tx.category_ref
    if cref is not None:
        out.category_name = cref.name
        out.category = cref.name
        out.category_icon = cref.icon
        out.category_parent_id = cref.parent_id
        out.category_invoice_budget_limit = cref.invoice_budget_limit

        parent = cref.parent
        if cref.parent_id is not None and parent is not None:
            out.category_parent_name = parent.name
            out.category_display_label = f"{parent.name} / {cref.name}"
        else:
            out.category_parent_name = None
            out.category_display_label = cref.name
    else:
        out.category_name = tx.category
        out.category_icon = None
        out.category_parent_id = None
        out.category_parent_name = None
        out.category_invoice_budget_limit = None
        out.category_display_label = tx.category

    return out
