from __future__ import annotations

from uuid import UUID

import pytest

from ai_qa_copilot_api.indexing import (
    ChunkingConfiguration,
    EmbeddingConfiguration,
    EmbeddingProtocolError,
    FakeEmbeddingAdapter,
    InMemoryChunkEmbeddingStore,
    IndexingService,
    NormalizedSection,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000701")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000702")
LOCATION_ID = UUID("00000000-0000-0000-0000-000000000703")
SECTION_ID = UUID("00000000-0000-0000-0000-000000000704")


def section(
    text: str = "Cart identifiers are required before checkout.",
) -> NormalizedSection:
    return NormalizedSection(
        id=SECTION_ID,
        source_location_id=LOCATION_ID,
        ordinal=0,
        normalized_text=text,
    )


def service_for(
    text: str = "Cart identifiers are required before checkout.",
    *,
    chunking: ChunkingConfiguration = ChunkingConfiguration(),
) -> tuple[IndexingService, FakeEmbeddingAdapter, InMemoryChunkEmbeddingStore]:
    store = InMemoryChunkEmbeddingStore({(PROJECT_ID, VERSION_ID): (section(text),)})
    adapter = FakeEmbeddingAdapter({text: (0.25, 0.75)})
    return IndexingService(store, adapter, chunking=chunking), adapter, store


def test_reprocessing_an_identical_version_uses_cached_embedding_without_cost() -> None:
    service, adapter, store = service_for()

    first = service.index(project_id=PROJECT_ID, document_version_id=VERSION_ID)
    second = service.index(project_id=PROJECT_ID, document_version_id=VERSION_ID)

    assert (first.chunk_count, first.chunks_created, first.embeddings_created) == (
        1,
        1,
        1,
    )
    assert (second.chunk_count, second.chunks_created, second.embeddings_created) == (
        1,
        0,
        0,
    )
    assert second.embedding_cache_hits == 1
    assert adapter.requests == [(section().normalized_text,)]
    assert len(store.attachments) == 1


def test_identical_content_in_a_new_version_reuses_the_project_cache() -> None:
    service, adapter, store = service_for()
    other_version = UUID("00000000-0000-0000-0000-000000000705")
    store._sections[(PROJECT_ID, other_version)] = (
        section(),
    )  # deterministic fixture setup

    service.index(project_id=PROJECT_ID, document_version_id=VERSION_ID)
    result = service.index(project_id=PROJECT_ID, document_version_id=other_version)

    assert result.chunks_created == 1
    assert result.embeddings_created == 0
    assert result.embedding_cache_hits == 1
    assert len(adapter.requests) == 1


def test_chunking_is_bounded_versioned_and_keeps_deterministic_overlap() -> None:
    text = "one two three four five six seven eight"
    configuration = ChunkingConfiguration(
        version="chunking-test-v1", max_characters=13, overlap_characters=7
    )
    store = InMemoryChunkEmbeddingStore({(PROJECT_ID, VERSION_ID): (section(text),)})
    adapter = FakeEmbeddingAdapter(
        {
            "one two three": (1.0,),
            "three four": (2.0,),
            "four five six": (3.0,),
            "six seven": (4.0,),
            "seven eight": (5.0,),
        }
    )
    service = IndexingService(store, adapter, chunking=configuration)

    result = service.index(project_id=PROJECT_ID, document_version_id=VERSION_ID)
    chunks = store.chunks_for_version(
        document_version_id=VERSION_ID, chunking_version="chunking-test-v1"
    )

    assert result.chunk_count == 5
    assert [chunk.normalized_text for chunk in chunks] == [
        "one two three",
        "three four",
        "four five six",
        "six seven",
        "seven eight",
    ]


def test_pipeline_rejects_malformed_provider_vectors_before_attachment() -> None:
    service, adapter, store = service_for()
    adapter._vectors_by_text[section().normalized_text] = (float("nan"),)

    with pytest.raises(EmbeddingProtocolError, match="finite and non-empty"):
        service.index(project_id=PROJECT_ID, document_version_id=VERSION_ID)

    assert store.attachments == {}


def test_configuration_rejects_unsafe_unbounded_chunking() -> None:
    with pytest.raises(ValueError, match="overlap"):
        ChunkingConfiguration(max_characters=10, overlap_characters=10).validate()
    with pytest.raises(ValueError, match="model and version"):
        EmbeddingConfiguration(model="", version="v1").validate()
