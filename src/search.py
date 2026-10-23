"""检索：先多召回，再按 case_id 聚合，最后取 Top-K 案例。"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_chroma import Chroma

from .chunking import CHUNK_LABELS, CHUNK_ORDER
from .config import Settings
from .index import count_store, get_vectorstore


@dataclass
class CaseHit:
    case_id: str
    title: str
    score: float
    matched_types: list[str] = field(default_factory=list)
    documents: list[Document] = field(default_factory=list)

    @property
    def context(self) -> str:
        """拼成一份紧凑上下文：案例头只出现一次，避免重复浪费 token。"""
        ordered = sorted(
            self.documents,
            key=lambda doc: (
                CHUNK_ORDER.get(str(doc.metadata.get("chunk_type")), 9),
                int(doc.metadata.get("chunk_index", 0)),
            ),
        )
        if not ordered:
            return ""

        metadata = ordered[0].metadata
        header = (
            f"案例 {self.case_id}｜{self.title}\n"
            f"组件：{metadata.get('component', '-')}｜"
            f"错误类型：{metadata.get('error_type', '-')}｜"
            f"级别：{metadata.get('severity', '-')}"
        )
        sections: list[str] = []
        for document in ordered:
            chunk_type = str(document.metadata.get("chunk_type", ""))
            label = CHUNK_LABELS.get(chunk_type, chunk_type or "内容")
            marker = f"【{label}】"
            content = document.page_content
            body = content.split(marker, 1)[1].strip() if marker in content else content.strip()
            sections.append(f"【{label}】\n{body}")
        return f"{header}\n" + "\n\n".join(sections)


@dataclass
class RetrievalResult:
    query: str
    threshold: float
    accepted: list[CaseHit]
    candidates: list[CaseHit]

    @property
    def matched(self) -> bool:
        return bool(self.accepted)

    @property
    def best_score(self) -> float | None:
        return self.candidates[0].score if self.candidates else None


def retrieve(
    query: str,
    settings: Settings,
    vectorstore: Chroma | None = None,
    top_k: int | None = None,
    candidate_k: int | None = None,
    threshold: float | None = None,
) -> RetrievalResult:
    query = query.strip()
    if not query:
        raise ValueError("查询日志不能为空")

    top_k = top_k or settings.top_k
    candidate_k = max(candidate_k or settings.candidate_k, top_k)
    threshold = settings.score_threshold if threshold is None else threshold

    store = vectorstore or get_vectorstore(settings)
    if count_store(store) == 0:
        return RetrievalResult(query=query, threshold=threshold, accepted=[], candidates=[])

    # 先多召回切片。不能直接取 top_k 个切片，因为同一个案例可能占多个名额。
    raw = store.similarity_search_with_relevance_scores(query, k=candidate_k)

    # 一个案例有多个切片：按 case_id 聚合，案例得分取“最高切片得分”。
    best: dict[str, CaseHit] = {}
    for document, score in raw:
        case_id = str(document.metadata["case_id"])
        chunk_type = str(document.metadata.get("chunk_type", ""))
        score = float(score)
        hit = best.get(case_id)
        if hit is None:
            best[case_id] = CaseHit(
                case_id=case_id,
                title=str(document.metadata.get("title", case_id)),
                score=score,
                matched_types=[chunk_type],
            )
        else:
            hit.score = max(hit.score, score)
            if chunk_type not in hit.matched_types:
                hit.matched_types.append(chunk_type)

    ranked = sorted(best.values(), key=lambda hit: hit.score, reverse=True)
    # 分数是 1 - cosine distance，不是概率；阈值需要用自己的评测集校准。
    accepted = [hit for hit in ranked if hit.score >= threshold][:top_k]
    candidates = ranked[: max(top_k, 1)]

    if accepted:
        _attach_full_case(store, accepted)

    return RetrievalResult(
        query=query,
        threshold=threshold,
        accepted=accepted,
        candidates=candidates,
    )


def _attach_full_case(store: Chroma, hits: list[CaseHit]) -> None:
    """Top-K 只用于排序；展示/生成上下文时补齐全案例切片。

    检索只保证某个切片相似，但生成需要完整根因和步骤，否则容易只拿到
    profile 片段，回答里缺处置细节。
    """
    case_ids = [hit.case_id for hit in hits]
    payload = store.get(
        where={"case_id": {"$in": case_ids}},
        include=["documents", "metadatas"],
    )
    documents = payload.get("documents") or []
    metadatas = payload.get("metadatas") or []

    grouped: dict[str, list[Document]] = {}
    for content, metadata in zip(documents, metadatas):
        if not content or not metadata:
            continue
        case_id = str(metadata["case_id"])
        grouped.setdefault(case_id, []).append(
            Document(page_content=content, metadata=metadata)
        )

    for hit in hits:
        hit.documents = grouped.get(hit.case_id, [])


def format_case_context(hit: CaseHit, max_chars: int = 2000) -> str:
    text = hit.context.strip() or "（缺少案例正文）"
    # 单个案例太长时截断，给其他候选案例留出 prompt 预算。
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n……（上下文过长，已截断）"
    return text
