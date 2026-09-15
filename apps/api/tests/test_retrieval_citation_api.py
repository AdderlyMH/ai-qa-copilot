from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_qa_copilot_api.auth import AppEnvironment, AuthSettings
from ai_qa_copilot_api.citations import Citation, SourceLocation
from ai_qa_copilot_api.hybrid_retrieval import (
    DEFAULT_HYBRID_CANDIDATE_LIMIT,
    DEFAULT_HYBRID_RESULT_LIMIT,
    FUSION_METHOD,
    HYBRID_RETRIEVAL_VERSION,
    HybridCandidate,
    HybridRetrievalFilters,
    HybridRetrievalResponse,
)
from ai_qa_copilot_api.indexing import EmbeddingConfiguration
from ai_qa_copilot_api.main import create_app
from ai_qa_copilot_api.projects import Base, SqlAlchemyProjectRepository
from ai_qa_copilot_api.retrieval_citation_linkage import (
    RETRIEVAL_CITATION_UNAVAILABLE_DETAIL,
    RetrievalCitationService,
)


NOW = datetime(2026, 9, 15, tzinfo=timezone.utc)


@dataclass
class FakeEmbedder:
    calls: list[tuple[tuple[str, ...], EmbeddingConfiguration]] = field(
        default_factory=list
    )

    def embed(
        self, texts: Sequence[str], configuration: EmbeddingConfiguration
    ) -> Sequence[Sequence[float]]:
        self.calls.append((tuple(texts), configuration))
        return ((0.25, 0.75),)


@dataclass
class FakeRetriever:
    project_id: UUID
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def retrieve(
        self,
        *,
        project_id: UUID,
        query: str,
        query_embedding: tuple[float, ...],
        filters: HybridRetrievalFilters,
        candidate_limit: int = DEFAULT_HYBRID_CANDIDATE_LIMIT,
        result_limit: int = DEFAULT_HYBRID_RESULT_LIMIT,
    ) -> HybridRetrievalResponse:
        self.calls.append(
            (
                project_id,
                query,
                query_embedding,
                filters,
                candidate_limit,
                result_limit,
            )
        )
        candidate = HybridCandidate(
            chunk_id=UUID("00000000-0000-0000-0000-000000000c01"),
            project_id=self.project_id,
            document_version_id=UUID("00000000-0000-0000-0000-000000000c02"),
            source_location_id=UUID("00000000-0000-0000-0000-000000000c03"),
            document_type="markdown",
            chunking_version="chunking-v1",
            ordinal=0,
            normalized_text="REQ-001: Cart IDs are required.",
            lexical_score=0.5,
            lexical_rank=1,
            semantic_distance=0.1,
            semantic_rank=1,
            fusion_score=0.03,
            rank=1,
        )
        return HybridRetrievalResponse(
            retrieval_version=HYBRID_RETRIEVAL_VERSION,
            fusion_method=FUSION_METHOD,
            trace_id=UUID("00000000-0000-0000-0000-000000000c04"),
            query=query,
            project_id=project_id,
            candidates=(candidate,),
        )


class FakeCitations:
    def create_from_selected_candidates(
        self,
        *,
        project_id: UUID,
        retrieval_trace_id: UUID,
        document_chunk_ids: tuple[UUID, ...],
    ) -> tuple[Citation, ...]:
        return tuple(
            Citation(
                id=UUID("00000000-0000-0000-0000-000000000c05"),
                project_id=project_id,
                retrieval_trace_id=retrieval_trace_id,
                document_chunk_id=document_chunk_id,
                document_version_id=UUID("00000000-0000-0000-0000-000000000c02"),
                source_location=SourceLocation(
                    id=UUID("00000000-0000-0000-0000-000000000c03"),
                    location_kind="line_range",
                    heading="Checkout",
                    line_start=2,
                    line_end=2,
                    page_start=None,
                    page_end=None,
                    json_pointer=None,
                ),
                document_type="markdown",
                display_name="requirements.md",
                passage="REQ-001: Cart IDs are required.",
                created_at=NOW,
            )
            for document_chunk_id in document_chunk_ids
        )


def local_bypass_settings() -> AuthSettings:
    return AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )


def test_authorized_retrieval_returns_trace_and_immutable_citation(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retrieval-api.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    projects = SqlAlchemyProjectRepository(sessions)
    project = projects.create(name="Retrieval API", description=None)
    retriever = FakeRetriever(project.id)
    service = RetrievalCitationService(
        retriever=retriever,
        citations=FakeCitations(),
        embedding_adapter=FakeEmbedder(),
    )
    app = create_app(
        local_bypass_settings(),
        project_repository=projects,
        retrieval_citation_service=service,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/projects/{project.id}/retrievals",
            json={
                "query": "  Cart   IDs  ",
                "candidate_limit": 1,
                "result_limit": 1,
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["project_id"] == str(project.id)
    assert payload["query"] == "Cart IDs"
    assert payload["retrieval_trace_id"] == "00000000-0000-0000-0000-000000000c04"
    assert payload["results"][0]["rank"] == 1
    assert payload["results"][0]["citation"]["passage"] == (
        "REQ-001: Cart IDs are required."
    )
    assert UUID(response.headers["X-Correlation-ID"])
    assert retriever.calls[0][0:3] == (project.id, "Cart IDs", (0.25, 0.75))
    engine.dispose()


def test_retrieval_fails_closed_without_composed_service(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'unavailable-retrieval.db'}"
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    projects = SqlAlchemyProjectRepository(sessions)
    project = projects.create(name="Unavailable retrieval", description=None)
    app = create_app(local_bypass_settings(), project_repository=projects)

    with TestClient(app) as client:
        response = client.post(
            f"/projects/{project.id}/retrievals", json={"query": "cart"}
        )

    assert response.status_code == 503
    assert response.json() == {"detail": RETRIEVAL_CITATION_UNAVAILABLE_DETAIL}
    assert UUID(response.headers["X-Correlation-ID"])
    engine.dispose()


def test_retrieval_rejects_unknown_project_before_service_call(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'missing-retrieval.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    projects = SqlAlchemyProjectRepository(sessions)
    known_project = projects.create(name="Known", description=None)
    retriever = FakeRetriever(known_project.id)
    service = RetrievalCitationService(
        retriever=retriever,
        citations=FakeCitations(),
        embedding_adapter=FakeEmbedder(),
    )
    app = create_app(
        local_bypass_settings(),
        project_repository=projects,
        retrieval_citation_service=service,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/projects/{uuid4()}/retrievals", json={"query": "cart"}
        )

    assert response.status_code == 404
    assert retriever.calls == []
    engine.dispose()
