"""Classificação econômica de movimentações de conta corrente (Extrato Inteligente).

Diferencia movimentação bancária de impacto financeiro real, para que transferências
internas e pagamentos de fatura não inflem receitas/despesas:

- ``income``               — dinheiro novo entrando (receita real)
- ``expense``              — saída real (consumo/serviço/obrigação)
- ``internal_transfer``    — entre contas/reservas/investimentos do próprio usuário
- ``credit_card_payment``  — pagamento de fatura de cartão (gasto real já está no cartão)
"""
import re

INCOME = "income"
EXPENSE = "expense"
INTERNAL_TRANSFER = "internal_transfer"
CREDIT_CARD_PAYMENT = "credit_card_payment"

_CARD_PAYMENT_RE = re.compile(
    r"pagamento\s+(de\s+)?(fatura|cart[aã]o)|fatura\s+.*cart[aã]o|pgto\s+.*fatura",
    re.IGNORECASE,
)


def classify_movement(
    amount: float,
    is_internal_transfer: bool,
    is_payment: bool,
    transaction_type: str | None,
    description: str | None,
) -> str:
    if is_internal_transfer:
        return INTERNAL_TRANSFER
    if is_payment or transaction_type == "payment":
        return CREDIT_CARD_PAYMENT
    if amount < 0 and description and _CARD_PAYMENT_RE.search(description):
        return CREDIT_CARD_PAYMENT
    if amount > 0:
        return INCOME
    return EXPENSE
