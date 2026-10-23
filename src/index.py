"""ChromaDB 建库与写入。"""

from __future__ import annotations

from dataclasses import dataclass

from chromadb.config import Settings as ChromaClientSettings
from langchain_chroma import Chroma

from .chunking import build_documents
from .config import Settings
from .embeddings import get_embeddings
from .schema import LogCase


@dataclass(frozen=True)
class IngestStats:
    cases: int
    chunks: int
    collection: str
    persist_dir: str


def get_vectorstore(settings: Settings, embeddings=None) -> Chroma:
    settings.persist_dir.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=settings.collection_name,
        embedding_function=embeddings or get_embeddings(settings),
        persist_directory=str(settings.persist_dir),
        # Chroma 默认是 L2；这里固定 cosine，检索分数才和阈值语义一致。
        collection_metadata={"hnsw:space": "cosine"},
        client_settings=ChromaClientSettings(anonymized_telemetry=False),
    )


def ingest(
    cases: list[LogCase],
    settings: Settings,
    rebuild: bool = True,
    batch_size: int = 256,
) -> IngestStats:
    documents = build_documents(
        cases,
        chunk_size=settings.max_chunk_chars,
        chunk_overlap=settings.chunk_overlap,
    )
    embeddings = get_embeddings(settings)
    vectorstore = get_vectorstore(settings, embeddings)

    if rebuild:
        # 全量重建，避免旧案例或旧模型维度的数据残留。
        vectorstore.delete_collection()
        vectorstore = get_vectorstore(settings, embeddings)
    else:
        # 增量写入前先按 case_id 删旧块，保证同一案例重复导入不会叠加。
        case_ids = sorted({case.case_id for case in cases})
        vectorstore.delete(where={"case_id": {"$in": case_ids}})

    ids = [document.metadata["chunk_id"] for document in documents]
    # 案例多时一次写入会很大，分批交给 Chroma。
    for start in range(0, len(documents), batch_size):
        vectorstore.add_documents(
            documents[start : start + batch_size],
            ids=ids[start : start + batch_size],
        )

    return IngestStats(
        cases=len(cases),
        chunks=len(documents),
        collection=settings.collection_name,
        persist_dir=str(settings.persist_dir),
    )


def count_store(vectorstore: Chroma) -> int:
    """用公开 get 接口数切片，避免依赖 Chroma 的私有属性。"""
    return len(vectorstore.get(include=[]).get("ids") or [])


def count_chunks(settings: Settings) -> int:
    return count_store(get_vectorstore(settings))
