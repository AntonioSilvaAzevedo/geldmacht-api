from app.services.summary_service import calculate_invoice_summary


def test_summary_excludes_credits_from_total():
    txs = [
        {
            "amount": -100.0,
            "description": "Compra A",
            "installment_current": None,
            "installment_total": None,
        },
        {
            "amount": -50.0,
            "description": "Compra B",
            "installment_current": None,
            "installment_total": None,
        },
        {
            "amount": 30.0,
            "description": "Estorno C",
            "installment_current": None,
            "installment_total": None,
        },
    ]
    s = calculate_invoice_summary(txs)
    assert s.total_invoice == 150.0
    assert s.total_credits == 30.0
    assert s.total_transactions == 3
    assert s.total_expenses == 2
    assert s.total_credits_count == 1


def test_summary_largest_expense():
    txs = [
        {
            "amount": -100.0,
            "description": "Pequeno",
            "installment_current": None,
            "installment_total": None,
        },
        {
            "amount": -500.0,
            "description": "Grande",
            "installment_current": None,
            "installment_total": None,
        },
    ]
    s = calculate_invoice_summary(txs)
    assert s.largest_expense == 500.0
    assert s.largest_expense_description == "Grande"


def test_summary_future_commitment():
    txs = [
        {
            "amount": -100.0,
            "description": "Parcelada",
            "installment_current": 3,
            "installment_total": 12,
        },
    ]
    s = calculate_invoice_summary(txs)
    assert s.future_commitment == 900.0


def test_summary_empty():
    s = calculate_invoice_summary([])
    assert s.total_invoice == 0.0
    assert s.largest_expense == 0.0
    assert s.future_commitment == 0.0
