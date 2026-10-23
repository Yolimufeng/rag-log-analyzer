from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = PROJECT_ROOT / "data" / "cases.json"


@pytest.fixture()
def data_file() -> Path:
    # 固定用仓库里的示例数据，避免测试依赖当前目录。
    return DATA_FILE


@pytest.fixture()
def settings(tmp_path):
    # 每个测试用独立临时目录和 hash 向量，不碰真实的 storage/。
    return get_settings(
        embedding_provider="hash",
        persist_dir=tmp_path / "chroma",
        pending_dir=tmp_path / "pending",
        score_threshold=0.45,
        top_k=3,
    )


@pytest.fixture()
def eval_queries() -> list[dict]:
    path = PROJECT_ROOT / "eval" / "queries.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
