"""日志案例的数据结构、加载与校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["low", "medium", "high", "critical"]


class LogCase(BaseModel):
    """一条“错误日志 -> 根因 -> 解决办法”的结构化案例。"""

    # 多写字段时直接报错，方便发现 cases.json 里的拼写问题；要扩展就显式加字段。
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    case_id: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="稳定唯一 ID，例如 LOG-0001",
    )
    title: str = Field(min_length=4, max_length=120)
    error_type: str = Field(min_length=1, max_length=80, description="如 OOMKilled / Deadlock / 502")
    component: str = Field(min_length=1, max_length=80, description="如 kubernetes / nginx / mysql")
    severity: Severity = "medium"
    error_signature: str = Field(min_length=10, description="最典型的原始报错文本，可多行")
    symptom: str = ""
    environment: dict[str, str] = Field(default_factory=dict)
    root_cause: str = Field(min_length=5)
    resolution: list[str] = Field(min_length=1, description="按执行顺序排列的处置步骤")
    verification: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str = "manual"
    updated_at: str = ""

    @field_validator("resolution")
    @classmethod
    def _clean_resolution(cls, steps: list[str]) -> list[str]:
        cleaned = [step.strip() for step in steps if step and step.strip()]
        if not cleaned:
            raise ValueError("resolution 至少需要一个非空步骤")
        return cleaned

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, tags: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for tag in tags:
            tag = tag.strip()
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                result.append(tag)
        return result

    @field_validator("environment")
    @classmethod
    def _stringify_env(cls, env: dict[str, Any]) -> dict[str, str]:
        return {str(k): str(v) for k, v in env.items()}


def load_cases(path: Path) -> list[LogCase]:
    """支持 JSON 数组、{"cases": [...]} 包装，以及 JSONL。"""
    # utf-8-sig 兼容 Windows/Excel 导出时带的 BOM。
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        payload = json.loads(text)
        rows = payload.get("cases", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON 顶层必须是数组，或包含 cases 数组的对象")

    cases = [LogCase.model_validate(row) for row in rows]
    if not cases:
        raise ValueError(f"{path} 中没有案例")

    seen: set[str] = set()
    duplicates: set[str] = set()
    # 重复 ID 会让增量更新互相覆盖，入库前直接拒绝。
    for case in cases:
        if case.case_id in seen:
            duplicates.add(case.case_id)
        seen.add(case.case_id)
    if duplicates:
        raise ValueError(f"case_id 重复：{', '.join(sorted(duplicates))}")
    return cases
