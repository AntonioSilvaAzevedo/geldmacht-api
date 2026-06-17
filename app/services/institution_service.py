from sqlalchemy.orm import Session

from ..models.credit_card import CreditCard
from ..models.import_batch import ImportBatch
from ..models.institution import Institution
from ..models.invoice import Invoice
from ..models.transaction import Transaction


def delete_card_records(db: Session, user_id: int, card: CreditCard) -> None:
    db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.card_id == card.id,
    ).update({"invoice_id": None}, synchronize_session=False)
    db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.card_id == card.id,
    ).delete(synchronize_session=False)
    db.query(Invoice).filter(
        Invoice.user_id == user_id,
        Invoice.card_id == card.id,
    ).delete(synchronize_session=False)
    db.delete(card)


def delete_bank_account_records(db: Session, user_id: int, account_id: int) -> None:
    db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.bank_account_id == account_id,
    ).delete(synchronize_session=False)
    db.query(ImportBatch).filter(
        ImportBatch.user_id == user_id,
        ImportBatch.bank_account_id == account_id,
    ).delete(synchronize_session=False)


def delete_institution_cascade(db: Session, user_id: int, institution: Institution) -> None:
    for card in list(institution.credit_cards):
        delete_card_records(db, user_id, card)

    for account in list(institution.bank_accounts):
        delete_bank_account_records(db, user_id, account.id)
        db.delete(account)

    db.delete(institution)
    db.commit()
