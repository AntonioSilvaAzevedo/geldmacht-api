from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@app.get("/api/__boom_test__")
def _boom():
    raise RuntimeError("boom")


client = TestClient(app, raise_server_exceptions=False)


def test_unhandled_error_returns_json_500_with_cors_header():
    origin = settings.cors_origins.split(",")[0].strip()
    res = client.get("/api/__boom_test__", headers={"Origin": origin})

    assert res.status_code == 500
    assert res.json() == {"detail": "Erro interno do servidor."}
    assert res.headers.get("access-control-allow-origin") == origin
