"""Embedding 工厂：真实场景用 Ollama，本地联调可用 hash 向量。"""

from __future__ import annotations

import hashlib

from langchain_core.embeddings import Embeddings

from .config import Settings


class HashEmbeddings(Embeddings):
    """确定性的字符 n-gram 哈希向量，仅用于无 Ollama 时跑通链路。

    它只反映字面重合，不具备语义泛化能力；不要用于真实检索效果评估。
    """

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        # 带符号哈希把 n-gram 映射到固定维度，再归一化。目的是可重复，不是效果。
        vector = [0.0] * self.dim
        normalized = "".join(text.lower().split())
        for n in (2, 3):
            for start in range(max(0, len(normalized) - n + 1)):
                gram = normalized[start : start + n]
                digest = hashlib.blake2b(
                    gram.encode("utf-8"), digest_size=8, person=b"lograg"
                ).digest()
                value = int.from_bytes(digest, "big")
                index = value % self.dim
                vector[index] += 1.0 if value & 1 else -1.0
        norm = sum(value * value for value in vector) ** 0.5
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings(settings: Settings) -> Embeddings:
    provider = settings.embedding_provider.lower()
    if provider == "hash":
        return HashEmbeddings()
    if provider == "ollama":
        # 延迟导入，hash 模式下不需要初始化 Ollama 客户端。
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=settings.embed_model,
            base_url=settings.ollama_base_url,
        )
    raise ValueError(
        f"不支持的 EMBEDDING_PROVIDER={settings.embedding_provider!r}，可选 ollama / hash"
    )
