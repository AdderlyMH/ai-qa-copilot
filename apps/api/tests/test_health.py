from fastapi.testclient import TestClient

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.main import create_app


def test_health() -> None:
    app = create_app(
        AuthSettings(
            app_env=AppEnvironment.LOCAL,
            local_auth_bypass_enabled=False,
            cognito=None,
        )
    )
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-qa-copilot-api",
    }
