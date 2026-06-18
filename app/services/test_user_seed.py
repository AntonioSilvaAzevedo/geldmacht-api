import logging

from ..config import settings
from ..database import SessionLocal
from .auth_service import create_user, get_user_by_email

logger = logging.getLogger(__name__)

TEST_USER_EMAIL = "teste@agente.com"
TEST_USER_PASSWORD = "teste@123"
TEST_USER_NAME = "Usuário de Teste"


def seed_test_user() -> None:
    if not settings.seed_test_user:
        return
    db = SessionLocal()
    try:
        if get_user_by_email(db, TEST_USER_EMAIL):
            return
        create_user(db, TEST_USER_EMAIL, TEST_USER_PASSWORD, TEST_USER_NAME)
        logger.info("Usuário de teste criado: %s", TEST_USER_EMAIL)
    finally:
        db.close()
