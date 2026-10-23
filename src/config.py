"""集中配置：全部可通过环境变量或 .env 覆盖。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 只在环境变量缺失时补值；shell 里显式 export 的变量优先。
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str) -> str:
    # .env 里留空也按“没配置”处理，避免空模型名一路传到 Ollama。
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


@dataclass(frozen=True)
class Settings:
    # 路径
    data_file: Path = PROJECT_ROOT / "data" / "cases.json"
    persist_dir: Path = PROJECT_ROOT / "storage" / "chroma"
    pending_dir: Path = PROJECT_ROOT / "data" / "pending"

    # 本地模型
    ollama_base_url: str = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    embed_model: str = _env("OLLAMA_EMBED_MODEL", "bge-m3")
    llm_model: str = _env("OLLAMA_LLM_MODEL", "qwen2.5:7b-instruct")
    embedding_provider: str = _env("EMBEDDING_PROVIDER", "ollama")  # ollama | hash

    # 检索
    top_k: int = int(_env("TOP_K", "3"))
    candidate_k: int = int(_env("CANDIDATE_K", "15"))
    score_threshold: float = float(_env("SCORE_THRESHOLD", "0.50"))

    # 切片
    max_chunk_chars: int = int(_env("MAX_CHUNK_CHARS", "600"))
    chunk_overlap: int = int(_env("CHUNK_OVERLAP", "80"))
    max_context_chars: int = int(_env("MAX_CONTEXT_CHARS", "6000"))

    collection_prefix: str = _env("COLLECTION_PREFIX", "log_cases")

    @property
    def collection_name(self) -> str:
        """集合名绑定 embedding 模型，避免不同维度/语义空间写进同一个集合。"""
        model = "hash384" if self.embedding_provider == "hash" else self.embed_model
        raw = f"{self.collection_prefix}_{self.embedding_provider}_{model}"
        # Chroma 要求集合名 3-63 个字符，只允许字母、数字、点、下划线和短横线。
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw).strip("._-").lower()
        slug = slug[:63].rstrip("._-")
        return slug if len(slug) >= 3 else "log_cases_hash"


def get_settings(**overrides: object) -> Settings:
    """返回配置；overrides 用于 CLI 临时覆盖，例如 provider='hash'。"""
    settings = Settings()
    if not overrides:
        return settings
    # Settings 是 frozen，不能直接改字段；复制一份再替换。
    return Settings(
        **{
            **{f: getattr(settings, f) for f in settings.__dataclass_fields__},
            **overrides,
        }
    )
