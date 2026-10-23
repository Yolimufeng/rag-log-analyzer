"""无可靠命中时的人工介入工单（文件队列，后续可替换成 Jira/飞书/Webhook）。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from .config import Settings
from .search import RetrievalResult


def create_ticket(
    query: str,
    result: RetrievalResult,
    settings: Settings,
    reason: str | None = None,
) -> Path:
    now = datetime.now().astimezone()
    # 哈希只用于避免文件名冲突，不承担安全用途。
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:8]
    ticket_id = f"HT-{now:%Y%m%d-%H%M%S}-{digest}"

    if reason is None:
        reason = "empty_knowledge_base" if not result.candidates else "no_case_above_threshold"

    payload = {
        "schema_version": 1,
        "ticket_id": ticket_id,
        "created_at": now.isoformat(timespec="seconds"),
        "status": "open",
        "reason": reason,
        "query": query[:20000],
        "query_chars": len(query),
        "threshold": result.threshold,
        "best_score": None if result.best_score is None else round(result.best_score, 4),
        # 候选只保留 ID、标题和分数；完整日志在 query 字段里。
        "candidates": [
            {
                "case_id": hit.case_id,
                "title": hit.title,
                "score": round(hit.score, 4),
            }
            for hit in result.candidates
        ],
        "next_action": "人工确认是否为已知问题；若是，请补充为结构化案例并重新入库。",
    }

    settings.pending_dir.mkdir(parents=True, exist_ok=True)
    path = settings.pending_dir / f"{ticket_id}.json"
    # 先写临时文件再替换，避免进程中断时留下半个 JSON。
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path
