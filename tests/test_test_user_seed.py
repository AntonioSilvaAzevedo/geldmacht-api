import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base
from app.models.user import User
from app.services import test_user_seed
from app.services.auth_service import verify_password


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def test_seed_disabled_creates_nothing(monkeypatch, session_factory):
    monkeypatch.setattr(settings, "seed_test_user", False)
    monkeypatch.setattr(test_user_seed, "SessionLocal", session_factory)

    test_user_seed.seed_test_user()

    db = session_factory()
    assert db.query(User).filter_by(email=test_user_seed.TEST_USER_EMAIL).first() is None
    db.close()


def test_seed_enabled_creates_hashed_user_idempotent(monkeypatch, session_factory):
    monkeypatch.setattr(settings, "seed_test_user", True)
    monkeypatch.setattr(test_user_seed, "SessionLocal", session_factory)

    test_user_seed.seed_test_user()
    test_user_seed.seed_test_user()

    db = session_factory()
    users = db.query(User).filter_by(email=test_user_seed.TEST_USER_EMAIL).all()
    assert len(users) == 1
    user = users[0]
    assert user.hashed_password and user.hashed_password != test_user_seed.TEST_USER_PASSWORD
    assert verify_password(test_user_seed.TEST_USER_PASSWORD, user.hashed_password)
    db.close()
