"""
Testes do fluxo de release notes / notas de atualização.

Cobre:
- Criar release note via seed
- GET /api/release-notes/pending
- POST /api/release-notes/{id}/mark-seen (idempotente)
- show_modal=false não retorna como pending
- Versão já visualizada não retorna como pending
- Múltiplas versões → mais recente primeiro
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models.release_note import ReleaseNote, UserReleaseNoteView
from app.services.auth_service import create_access_token, create_user

from app import models as _models  # noqa: F401


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _set_db_override():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


@pytest.fixture(autouse=True)
def setup_db(_set_db_override):
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    yield
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _auth(email: str) -> dict:
    token = create_access_token({"sub": email})
    return {"Authorization": f"Bearer {token}"}


def _make_rn(db, version: str, *, show_modal: bool = True, title: str = "Title") -> ReleaseNote:
    rn = ReleaseNote(
        version=version,
        title=title,
        description="desc",
        items_json=json.dumps(["item 1", "item 2"], ensure_ascii=False),
        show_modal=show_modal,
    )
    db.add(rn)
    db.commit()
    db.refresh(rn)
    return rn


class TestReleaseNotesPending:

    def test_returns_latest_when_user_has_not_seen(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn = _make_rn(db, "0.3.0")
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 200
        data = res.json()
        assert data["version"] == "0.3.0"
        assert data["id"] == rn.id
        assert data["items"] == ["item 1", "item 2"]
        assert data["show_modal"] is True

    def test_returns_204_when_no_pending(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 204

    def test_does_not_return_release_with_show_modal_false(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        _make_rn(db, "0.3.1", show_modal=False)
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 204

    def test_skips_already_seen(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn = _make_rn(db, "0.3.0")
        # Marca como visto
        client.post(f"/api/release-notes/{rn.id}/mark-seen", headers=_auth(user.email))
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 204

    def test_returns_most_recent_unseen_when_multiple(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        old = _make_rn(db, "0.2.0", title="old")
        new = _make_rn(db, "0.3.0", title="new")
        # Usa created_at — o segundo criado é mais recente.
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["version"] == "0.3.0"
        assert res.json()["id"] == new.id
        # Se marca a mais recente, retorna a antiga
        client.post(f"/api/release-notes/{new.id}/mark-seen", headers=_auth(user.email))
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json()["id"] == old.id

    def test_isolated_by_user(self, client, db):
        ua = create_user(db, "a@test.com", "x", "A")
        ub = create_user(db, "b@test.com", "x", "B")
        rn = _make_rn(db, "0.3.0")
        client.post(f"/api/release-notes/{rn.id}/mark-seen", headers=_auth(ua.email))
        # ua: já viu
        res = client.get("/api/release-notes/pending", headers=_auth(ua.email))
        assert res.status_code == 204
        # ub: ainda não viu
        res = client.get("/api/release-notes/pending", headers=_auth(ub.email))
        assert res.status_code == 200
        assert res.json()["version"] == "0.3.0"


class TestMarkSeen:

    def test_marks_as_seen(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn = _make_rn(db, "0.3.0")
        res = client.post(f"/api/release-notes/{rn.id}/mark-seen", headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json() == {"success": True, "seen": True}
        # Confirma persistência
        view = db.query(UserReleaseNoteView).filter(
            UserReleaseNoteView.user_id == user.id,
            UserReleaseNoteView.release_note_id == rn.id,
        ).first()
        assert view is not None
        assert view.version == "0.3.0"

    def test_idempotent(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn = _make_rn(db, "0.3.0")
        client.post(f"/api/release-notes/{rn.id}/mark-seen", headers=_auth(user.email))
        # Segunda chamada não duplica nem dá erro
        res = client.post(f"/api/release-notes/{rn.id}/mark-seen", headers=_auth(user.email))
        assert res.status_code == 200
        count = db.query(UserReleaseNoteView).filter(
            UserReleaseNoteView.user_id == user.id,
            UserReleaseNoteView.release_note_id == rn.id,
        ).count()
        assert count == 1

    def test_404_for_missing_release(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.post("/api/release-notes/9999/mark-seen", headers=_auth(user.email))
        assert res.status_code == 404

    def test_requires_auth(self, client, db):
        res = client.get("/api/release-notes/pending")
        assert res.status_code in (401, 403)


class TestSeed:

    def test_seed_is_idempotent(self, db):
        from app.services.release_notes_seed import seed_release_notes
        first = seed_release_notes(db)
        second = seed_release_notes(db)
        # 1ª execução cria, 2ª não cria nada novo
        assert first >= 1
        assert second == 0

    def test_seed_populates_items(self, db):
        from app.services.release_notes_seed import seed_release_notes
        seed_release_notes(db)
        rn = db.query(ReleaseNote).filter(ReleaseNote.version == "0.3.0").first()
        assert rn is not None
        items = json.loads(rn.items_json)
        assert isinstance(items, list)
        assert len(items) >= 1
        # Conteúdo amigável — não deve mencionar termos técnicos comuns.
        joined = " ".join(items).lower()
        for forbidden in ("schema", "migration", "endpoint", "refactor", "card_id", "parent_id"):
            assert forbidden not in joined, f"Termo técnico '{forbidden}' apareceu nos items"
        assert rn.show_modal is True
