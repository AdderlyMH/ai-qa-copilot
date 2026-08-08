from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from ai_qa_copilot_api.auth import AuthBoundary, AuthSettings, TokenValidator


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: Literal["ai-qa-copilot-api"]


def create_app(
    auth_settings: AuthSettings | None = None,
    token_validator: TokenValidator | None = None,
) -> FastAPI:
    """Build the API with authentication initialized during application startup."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        settings = auth_settings or AuthSettings.from_environment()
        application.state.auth_boundary = AuthBoundary(settings, token_validator)
        yield

    application = FastAPI(lifespan=lifespan)

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="ai-qa-copilot-api")

    return application


app = create_app()
