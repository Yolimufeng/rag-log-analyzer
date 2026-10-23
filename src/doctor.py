"""环境自检：Python 包、Ollama 服务、模型、知识库。"""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError, version
from urllib.error import URLError
from urllib.request import urlopen

from .config import Settings
from .index import count_chunks
from .schema import load_cases

PACKAGES = [
    "langchain-core",
    "langchain-text-splitters",
    "langchain-ollama",
    "langchain-chroma",
    "chromadb",
    "pydantic",
]


def _model_present(names: set[str], target: str) -> bool:
    # Ollama 的 /api/tags 返回 name 可能带 :latest，比较时按仓库名匹配。
    if target in names:
        return True
    short = target.split(":")[0]
    return any(name.split(":")[0] == short for name in names)


def check_ollama(settings: Settings) -> tuple[bool, list[str]]:
    # 只做一次轻量 GET，不额外引入 requests 依赖。
    url = settings.ollama_base_url.rstrip("/") + "/api/tags"
    try:
        with urlopen(url, timeout=3) as response:
            payload = json.load(response)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return False, [f"无法连接 {url}：{exc}"]

    names = {str(item.get("name", "")) for item in payload.get("models", [])}
    missing = [
        model
        for model in (settings.embed_model, settings.llm_model)
        if not _model_present(names, model)
    ]
    return True, missing


def run_doctor(settings: Settings) -> int:
    print(f"Python：{sys.version.split()[0]}")
    for package in PACKAGES:
        try:
            print(f"  {package}=={version(package)}")
        except PackageNotFoundError:
            print(f"  {package}=<未安装>")

    exit_code = 0
    if settings.embedding_provider == "hash":
        # hash 模式不碰 Ollama，只检查 Python 环境和数据。
        print("Embedding：hash（离线联调模式，跳过 Ollama 检查）")
    else:
        reachable, missing = check_ollama(settings)
        if not reachable:
            exit_code = 1
            print(f"Ollama：不可用。{missing[0]}")
            print("  启动：ollama serve")
        elif missing:
            exit_code = 1
            print(f"Ollama：服务可用，但缺少模型：{', '.join(missing)}")
            for model in missing:
                print(f"  拉取：ollama pull {model}")
        else:
            print(
                f"Ollama：可用（embed={settings.embed_model}, llm={settings.llm_model}）"
            )

    try:
        cases = load_cases(settings.data_file)
        print(f"数据文件：{settings.data_file}（{len(cases)} 个案例）")
    except Exception as exc:
        exit_code = 1
        print(f"数据文件：无法读取（{exc}）")

    try:
        print(f"知识库：{settings.collection_name}（{count_chunks(settings)} 个切片）")
    except Exception as exc:
        print(f"知识库：尚未初始化（{exc}）")
    return exit_code
