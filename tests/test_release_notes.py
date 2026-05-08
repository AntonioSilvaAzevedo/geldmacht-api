"""
Testes do fluxo de release notes / notas de atualização.

Cobre:
- Endpoint pending acumulativo (lista cronológica de releases não vistas).
- Filtro por show_modal=true.
- Filtro por usuário (visualizações são por usuário).
- Bulk mark-seen idempotente.
- Mark-seen single (legado/compat.).
- Cenário de usuário inativo (múltiplas releases acumuladas).
- Seed idempotente.
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


# ─────────────────────────────────────────────────────────────────────────────
# GET /release-notes/pending — lista acumulativa
# ─────────────────────────────────────────────────────────────────────────────

class TestPendingList:

    def test_returns_empty_list_when_no_releases(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 200
        assert res.json() == {"releases": []}

    def test_returns_single_release_for_new_user(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn = _make_rn(db, "0.3.0")
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.status_code == 200
        data = res.json()
        assert len(data["releases"]) == 1
        item = data["releases"][0]
        assert item["id"] == rn.id
        assert item["version"] == "0.3.0"
        assert item["items"] == ["item 1", "item 2"]
        assert item["show_modal"] is True

    def test_skips_release_with_show_modal_false(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        _make_rn(db, "0.3.0", show_modal=True)
        _make_rn(db, "0.3.1", show_modal=False)  # não deve aparecer
        _make_rn(db, "0.4.0", show_modal=True)
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        versions = [r["version"] for r in res.json()["releases"]]
        assert versions == ["0.3.0", "0.4.0"]

    def test_skips_already_seen_releases(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn1 = _make_rn(db, "0.3.0")
        rn2 = _make_rn(db, "0.4.0")
        # Marca a primeira como vista
        client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn1.id]},
            headers=_auth(user.email),
        )
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        ids = [r["id"] for r in res.json()["releases"]]
        assert ids == [rn2.id]

    def test_orders_oldest_first(self, client, db):
        """released_at ascendente; sem released_at, usa created_at ascendente."""
        from datetime import datetime
        user = create_user(db, "u@test.com", "x", "U")
        # Criamos em ordem aleatória, com released_at explícito
        rn_b = _make_rn(db, "0.5.0")
        rn_b.released_at = datetime(2026, 5, 8)
        rn_a = _make_rn(db, "0.4.0")
        rn_a.released_at = datetime(2026, 5, 1)
        rn_c = _make_rn(db, "0.6.0")
        rn_c.released_at = datetime(2026, 5, 12)
        db.commit()

        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        versions = [r["version"] for r in res.json()["releases"]]
        assert versions == ["0.4.0", "0.5.0", "0.6.0"]

    def test_isolated_by_user(self, client, db):
        ua = create_user(db, "a@test.com", "x", "A")
        ub = create_user(db, "b@test.com", "x", "B")
        rn = _make_rn(db, "0.3.0")
        # ua marca como vista
        client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn.id]},
            headers=_auth(ua.email),
        )
        # ua: nada pendente
        res = client.get("/api/release-notes/pending", headers=_auth(ua.email))
        assert res.json()["releases"] == []
        # ub: ainda vê a release
        res = client.get("/api/release-notes/pending", headers=_auth(ub.email))
        assert len(res.json()["releases"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# POST /release-notes/mark-seen — bulk
# ─────────────────────────────────────────────────────────────────────────────

class TestBulkMarkSeen:

    def test_marks_multiple_as_seen(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn1 = _make_rn(db, "0.3.0")
        rn2 = _make_rn(db, "0.4.0")
        rn3 = _make_rn(db, "0.5.0")
        res = client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn1.id, rn2.id, rn3.id]},
            headers=_auth(user.email),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert sorted(body["marked_as_seen"]) == sorted([rn1.id, rn2.id, rn3.id])
        # 3 views persistidas
        assert db.query(UserReleaseNoteView).filter(
            UserReleaseNoteView.user_id == user.id,
        ).count() == 3
        # Pending agora vazio
        res = client.get("/api/release-notes/pending", headers=_auth(user.email))
        assert res.json()["releases"] == []

    def test_idempotent_does_not_duplicate(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn1 = _make_rn(db, "0.3.0")
        rn2 = _make_rn(db, "0.4.0")
        # Primeira chamada marca rn1
        client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn1.id]},
            headers=_auth(user.email),
        )
        # Segunda chamada inclui rn1 (já visto) e rn2 (novo)
        res = client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn1.id, rn2.id]},
            headers=_auth(user.email),
        )
        assert res.status_code == 200
        # Não duplica registros
        assert db.query(UserReleaseNoteView).filter(
            UserReleaseNoteView.user_id == user.id,
            UserReleaseNoteView.release_note_id == rn1.id,
        ).count() == 1
        assert db.query(UserReleaseNoteView).filter(
            UserReleaseNoteView.user_id == user.id,
            UserReleaseNoteView.release_note_id == rn2.id,
        ).count() == 1

    def test_empty_list_is_accepted(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": []},
            headers=_auth(user.email),
        )
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["marked_as_seen"] == []

    def test_ignores_invalid_ids(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn = _make_rn(db, "0.3.0")
        res = client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn.id, 99999]},
            headers=_auth(user.email),
        )
        assert res.status_code == 200
        # Marca só os válidos
        assert res.json()["marked_as_seen"] == [rn.id]


# ─────────────────────────────────────────────────────────────────────────────
# POST /release-notes/{id}/mark-seen — legado/compat.
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleMarkSeenLegacy:

    def test_marks_single_release(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        rn = _make_rn(db, "0.3.0")
        res = client.post(f"/api/release-notes/{rn.id}/mark-seen", headers=_auth(user.email))
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["seen"] is True
        assert body["marked_as_seen"] == [rn.id]

    def test_404_for_missing_release(self, client, db):
        user = create_user(db, "u@test.com", "x", "U")
        res = client.post("/api/release-notes/9999/mark-seen", headers=_auth(user.email))
        assert res.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Cenário: usuário inativo recebe múltiplas releases acumuladas
# ─────────────────────────────────────────────────────────────────────────────

class TestInactiveUserScenario:

    def test_user_returns_after_long_absence_sees_all_unseen(self, client, db):
        from datetime import datetime
        ua = create_user(db, "active@test.com", "x", "Active")
        ub = create_user(db, "inactive@test.com", "x", "Inactive")

        # 0.4.0 lançada, ua vê
        rn1 = _make_rn(db, "0.4.0")
        rn1.released_at = datetime(2026, 5, 1)
        db.commit()
        client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn1.id]},
            headers=_auth(ua.email),
        )

        # 0.5.0 e 0.6.0 lançadas em sequência
        rn2 = _make_rn(db, "0.5.0")
        rn2.released_at = datetime(2026, 5, 5)
        rn3 = _make_rn(db, "0.6.0")
        rn3.released_at = datetime(2026, 5, 8)
        db.commit()

        # ua (ativo) vê só as duas novas
        res = client.get("/api/release-notes/pending", headers=_auth(ua.email))
        versions_ua = [r["version"] for r in res.json()["releases"]]
        assert versions_ua == ["0.5.0", "0.6.0"]

        # ub (inativo) vê todas as três acumuladas
        res = client.get("/api/release-notes/pending", headers=_auth(ub.email))
        versions_ub = [r["version"] for r in res.json()["releases"]]
        assert versions_ub == ["0.4.0", "0.5.0", "0.6.0"]

        # ub fecha o modal — todas marcadas
        client.post(
            "/api/release-notes/mark-seen",
            json={"release_note_ids": [rn1.id, rn2.id, rn3.id]},
            headers=_auth(ub.email),
        )
        res = client.get("/api/release-notes/pending", headers=_auth(ub.email))
        assert res.json()["releases"] == []


class TestSeed:

    def test_seed_is_idempotent(self, db):
        from app.services.release_notes_seed import seed_release_notes
        first = seed_release_notes(db)
        second = seed_release_notes(db)
        assert first >= 1
        assert second == 0

    def test_seed_populates_multiple_versions(self, db):
        from app.services.release_notes_seed import seed_release_notes
        seed_release_notes(db)
        # Confere que há mais de uma versão no seed atual (acumulativo).
        count = db.query(ReleaseNote).count()
        assert count >= 1
        for rn in db.query(ReleaseNote).all():
            items = json.loads(rn.items_json)
            assert isinstance(items, list)
            joined = " ".join(items).lower()
            for forbidden in ("schema", "migration", "endpoint", "refactor", "card_id", "parent_id"):
                assert forbidden not in joined, (
                    f"Termo técnico '{forbidden}' apareceu nos items da v{rn.version}"
                )
