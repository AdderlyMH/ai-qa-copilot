from fastapi.testclient import TestClient

from ai_qa_copilot_api.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-qa-copilot-api",
    }
