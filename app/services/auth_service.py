from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt
from sqlalchemy.orm import Session

from ..config import settings
from ..models.user import User


# ── Senha ──────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT ────────────────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload["exp"] = expire
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


# ── Usuários ───────────────────────────────────────────────────────────────────

def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def create_user(db: Session, email: str, password: str, name: str = "") -> User:
    user = User(
        email=email,
        name=name or None,
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_google_user(
    db: Session,
    google_id: str,
    email: str,
    name: str,
) -> User:
    # Buscar por google_id primeiro
    user = db.query(User).filter(User.google_id == google_id).first()
    if user:
        return user

    # Buscar por email (conta já existe sem Google)
    user = get_user_by_email(db, email)
    if user:
        user.google_id = google_id
        db.commit()
        return user

    # Criar novo usuário via Google
    user = User(email=email, name=name or None, google_id=google_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
