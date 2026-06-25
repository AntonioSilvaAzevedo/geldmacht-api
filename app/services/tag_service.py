import re

from sqlalchemy.orm import Session

from ..models.tag import Tag
from ..models.transaction import Transaction

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_display(raw: str) -> str:
    return _WHITESPACE_RE.sub(" ", raw.strip())


def normalized_key(raw: str) -> str:
    return normalize_display(raw).casefold()


def list_user_tags(db: Session, user_id: int) -> list[Tag]:
    return (
        db.query(Tag)
        .filter(Tag.user_id == user_id)
        .order_by(Tag.name)
        .all()
    )


def get_or_create_tag(db: Session, user_id: int, raw_name: str) -> Tag | None:
    display = normalize_display(raw_name)
    if not display:
        return None
    key = display.casefold()
    existing = (
        db.query(Tag)
        .filter(Tag.user_id == user_id, Tag.normalized_name == key)
        .first()
    )
    if existing:
        return existing
    tag = Tag(user_id=user_id, name=display, normalized_name=key)
    db.add(tag)
    db.flush()
    return tag


def set_transaction_tags(db: Session, tx: Transaction, raw_names: list[str]) -> list[Tag]:
    seen: set[str] = set()
    tags: list[Tag] = []
    for raw in raw_names:
        key = normalized_key(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        tag = get_or_create_tag(db, tx.user_id, raw)
        if tag is not None:
            tags.append(tag)
    tx.tags = tags
    return tags
