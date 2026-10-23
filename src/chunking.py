"""把结构化案例切成“带上下文头”的检索块。

不是按固定字数硬切，而是先按语义字段分成三类块：
- profile  错误画像：原始报错、现象、环境、标签（负责“像不像”）
- cause    根因分析（负责“为什么”）
- solution 处置步骤 + 验证（负责“怎么修”）
每个块都重复案例头和关键字段，避免切开后失去上下文。
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .schema import LogCase

CHUNK_ORDER = {"profile": 0, "cause": 1, "solution": 2}
CHUNK_LABELS = {"profile": "错误画像", "cause": "根因分析", "solution": "处置步骤"}


def case_header(case: LogCase) -> str:
    # 每个切片都带案例头。这样命中 solution 时，模型仍能看到组件和错误类型。
    return (
        f"案例 {case.case_id}｜{case.title}\n"
        f"组件：{case.component}｜错误类型：{case.error_type}｜级别：{case.severity}"
    )


def _section_body(case: LogCase, chunk_type: str) -> str:
    if chunk_type == "profile":
        env = "；".join(f"{k}={v}" for k, v in case.environment.items()) or "未提供"
        tags = "、".join(case.tags) or "无"
        return (
            f"错误特征：\n{case.error_signature}\n\n"
            f"现象：{case.symptom or '未提供'}\n"
            f"环境：{env}\n"
            f"标签：{tags}"
        )
    if chunk_type == "cause":
        return case.root_cause
    if chunk_type == "solution":
        steps = "\n".join(f"{i}. {step}" for i, step in enumerate(case.resolution, 1))
        verification = f"\n\n验证方式：{case.verification}" if case.verification else ""
        return steps + verification
    raise ValueError(f"未知 chunk_type: {chunk_type}")


def build_documents(
    cases: Iterable[LogCase],
    chunk_size: int = 600,
    chunk_overlap: int = 80,
) -> list[Document]:
    documents: list[Document] = []
    for case in cases:
        header = case_header(case)
        for chunk_type in ("profile", "cause", "solution"):
            label = CHUNK_LABELS[chunk_type]
            body = _section_body(case, chunk_type)
            # 给上下文头留出字符预算，避免“头 + 正文”明显超过 chunk_size。
            body_limit = max(160, chunk_size - len(header) - len(label) - 12)
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=body_limit,
                chunk_overlap=min(chunk_overlap, max(0, body_limit // 4)),
                length_function=len,
                separators=["\n\n", "\n", "。", "；", "，", " ", ""],
            )
            pieces = splitter.split_text(body) or [body]
            for index, piece in enumerate(pieces):
                chunk_id = f"{case.case_id}--{chunk_type}--{index}"
                # Chroma 的 metadata 只收 str/int/float/bool，environment 先转 JSON 字符串。
                metadata = {
                    "case_id": case.case_id,
                    "title": case.title,
                    "error_type": case.error_type,
                    "component": case.component,
                    "severity": case.severity,
                    "chunk_type": chunk_type,
                    "chunk_index": index,
                    "chunk_id": chunk_id,
                    "tags": ", ".join(case.tags),
                    "environment": json.dumps(case.environment, ensure_ascii=False),
                    "source": case.source,
                    "updated_at": case.updated_at,
                }
                documents.append(
                    Document(
                        page_content=f"{header}\n【{label}】\n{piece.strip()}",
                        metadata=metadata,
                    )
                )
    return documents
