from app.services.bank_movement import (
    CREDIT_CARD_PAYMENT,
    EXPENSE,
    INCOME,
    INTERNAL_TRANSFER,
    classify_movement,
)


def _classify(amount, *, internal=False, payment=False, ttype=None, desc="Lançamento"):
    return classify_movement(
        amount=amount,
        is_internal_transfer=internal,
        is_payment=payment,
        transaction_type=ttype,
        description=desc,
    )


class TestClassifyMovement:
    def test_income_when_positive(self):
        assert _classify(8500.0, desc="Salário") == INCOME

    def test_expense_when_negative(self):
        assert _classify(-1800.0, desc="Aluguel") == EXPENSE

    def test_internal_transfer_flag_wins(self):
        assert _classify(-2000.0, internal=True, desc="Transferência para Itaú") == INTERNAL_TRANSFER
        assert _classify(2000.0, internal=True, desc="Recebido do Itaú") == INTERNAL_TRANSFER

    def test_credit_card_payment_by_flag(self):
        assert _classify(-4576.41, payment=True, desc="qualquer") == CREDIT_CARD_PAYMENT

    def test_credit_card_payment_by_transaction_type(self):
        assert _classify(-100.0, ttype="payment", desc="qualquer") == CREDIT_CARD_PAYMENT

    def test_credit_card_payment_by_description_heuristic(self):
        assert _classify(-4576.41, desc="Pagamento de fatura Nubank") == CREDIT_CARD_PAYMENT
        assert _classify(-1200.0, desc="PGTO FATURA CARTAO") == CREDIT_CARD_PAYMENT

    def test_description_heuristic_ignored_on_income(self):
        assert _classify(500.0, desc="Estorno pagamento de fatura") == INCOME

    def test_internal_transfer_takes_priority_over_payment_text(self):
        assert _classify(-2000.0, internal=True, desc="Pagamento de fatura") == INTERNAL_TRANSFER

    def test_reserve_or_investment_movement_classified_as_internal_transfer(self):
        assert _classify(-500.0, ttype="reserve_or_investment_movement", desc="Aporte caixinha") == INTERNAL_TRANSFER
        assert _classify(500.0, ttype="reserve_or_investment_movement", desc="Resgate caixinha") == INTERNAL_TRANSFER
