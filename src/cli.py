"""命令行入口：

python -m src.cli ingest
python -m src.cli search "报错日志..."
python -m src.cli eval
python -m src.cli stats
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import PROJECT_ROOT, Settings, get_settings
from .doctor import run_doctor
from .generate import LLMUnavailableError, generate_answer
from .handoff import create_ticket
from .index import count_chunks, count_store, get_vectorstore, ingest
from .schema import load_cases
from .search import CaseHit, RetrievalResult, retrieve

MAX_QUERY_CHARS = 20000  # 防止把超大日志整段塞进 embedding / prompt


def _settings(args: argparse.Namespace) -> Settings:
    # CLI 参数只覆盖当前进程的配置，不改 .env。
    overrides: dict[str, object] = {}
    if getattr(args, "provider", None):
        overrides["embedding_provider"] = args.provider
    if getattr(args, "threshold", None) is not None:
        overrides["score_threshold"] = args.threshold
    if getattr(args, "top_k", None) is not None:
        overrides["top_k"] = args.top_k
    if getattr(args, "data", None) is not None:
        overrides["data_file"] = Path(args.data)
    return get_settings(**overrides)


def _read_query(args: argparse.Namespace) -> str:
    if args.file and args.query:
        raise ValueError("query 和 --file 只能二选一")
    if args.file:
        query = Path(args.file).read_text(encoding="utf-8-sig")
    elif args.query:
        query = args.query
    else:
        raise ValueError("请提供日志文本，或用 --file 指定日志文件")

    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        print(
            f"提示：日志长度 {len(query)} 字符，已截断到 {MAX_QUERY_CHARS} 字符。",
            file=sys.stderr,
        )
        query = query[:MAX_QUERY_CHARS]
    return query


def _print_hits(hits: list[CaseHit], threshold: float, title: str | None = None) -> None:
    print(title or f"命中 {len(hits)} 个案例（阈值 {threshold:.2f}）：")
    for index, hit in enumerate(hits, 1):
        types = ",".join(hit.matched_types) or "-"
        print(f"  {index}. {hit.case_id}  {hit.title}  相似度={hit.score:.3f}  [{types}]")


def _result_payload(result: RetrievalResult) -> dict:
    return {
        "threshold": result.threshold,
        "matched": result.matched,
        "best_score": None if result.best_score is None else round(result.best_score, 4),
        "cases": [
            {
                "case_id": hit.case_id,
                "title": hit.title,
                "score": round(hit.score, 4),
                "matched_chunk_types": hit.matched_types,
            }
            for hit in result.accepted
        ],
    }


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = _settings(args)
    cases = load_cases(settings.data_file)
    stats = ingest(cases, settings, rebuild=not args.append)
    print(f"已导入 {stats.cases} 个案例 / {stats.chunks} 个切片")
    print(f"集合：{stats.collection}")
    print(f"持久化目录：{stats.persist_dir}")
    if settings.embedding_provider == "hash":
        print("注意：当前为 hash 离线向量，仅用于联调，不具备语义检索能力。")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if settings.embedding_provider == "hash":
        print(
            "注意：hash 模式只验证检索管道，分数不具备真实语义判断力。",
            file=sys.stderr,
        )
    query = _read_query(args)
    store = get_vectorstore(settings)
    if count_store(store) == 0:
        print(
            f"知识库为空（{settings.collection_name}）。请先执行："
            f"python -m src.cli ingest --provider {settings.embedding_provider}",
            file=sys.stderr,
        )
        return 1
    result = retrieve(query, settings, vectorstore=store)

    if not result.matched:
        # 没命中就不调用生成模型，先把原始查询和低分候选交给人工。
        ticket = create_ticket(query, result, settings)
        if args.json:
            payload = {
                "status": "handoff",
                "query": query,
                **_result_payload(result),
                "ticket": str(ticket),
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"未找到相似度 ≥ {result.threshold:.2f} 的历史案例，已转人工。")
            if result.best_score is None:
                print("原因：知识库为空或没有候选案例。")
            else:
                print(f"最高相似度：{result.best_score:.3f}（低于阈值）")
                _print_hits(
                    result.candidates,
                    result.threshold,
                    title="低于阈值的候选（仅用于人工参考）：",
                )
            print(f"工单：{ticket}")
        return 2

    if not args.json:
        _print_hits(result.accepted, result.threshold)

    if args.no_llm:
        if args.json:
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "query": query,
                        **_result_payload(result),
                        "answer": None,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("\n=== 检索到的案例（--no-llm，不调用生成模型）===")
            for hit in result.accepted:
                print(f"\n--- {hit.case_id} | {hit.title} | {hit.score:.3f} ---")
                print(hit.context)
        return 0

    answer = generate_answer(query, result.accepted, settings)
    if args.json:
        print(
            json.dumps(
                {
                    "status": "ok",
                    "query": query,
                    **_result_payload(result),
                    "answer": answer,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("\n=== 分析结果 ===")
        print(answer)
    return 0


def _load_eval_queries(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"{path} 中没有评测样本")
    return rows


def cmd_eval(args: argparse.Namespace) -> int:
    settings = _settings(args)
    queries = _load_eval_queries(Path(args.queries))
    store = get_vectorstore(settings)
    if count_store(store) == 0:
        raise ValueError("知识库为空，请先执行 ingest")

    details = []
    hit1 = hit3 = 0
    reciprocal_rank = 0.0
    labeled = 0
    handoff_total = handoff_ok = 0

    # expected_case_ids 为空表示库外问题，评估的是“是否正确转人工”。
    for row in queries:
        query = str(row["query"]).strip()
        expected = [str(case_id) for case_id in row.get("expected_case_ids", [])]
        result = retrieve(query, settings, vectorstore=store)
        ranked_ids = [hit.case_id for hit in result.accepted]

        if expected:
            labeled += 1
            if ranked_ids and ranked_ids[0] in expected:
                hit1 += 1
            if any(case_id in expected for case_id in ranked_ids):
                hit3 += 1
            for rank, case_id in enumerate(ranked_ids, 1):
                if case_id in expected:
                    reciprocal_rank += 1.0 / rank
                    break
            ok = bool(ranked_ids) and ranked_ids[0] in expected
        else:
            handoff_total += 1
            ok = not ranked_ids
            handoff_ok += int(ok)

        details.append(
            {
                "query": query,
                "expected": expected,
                "returned": ranked_ids,
                "best_score": None if result.best_score is None else round(result.best_score, 4),
                "ok": ok,
            }
        )
        if not args.json:
            print(
                f"[{'OK' if ok else 'MISS'}] 期望={expected or ['<转人工>']} "
                f"返回={ranked_ids or ['<转人工>']} best={details[-1]['best_score']}"
            )

    summary = {
        "queries": len(queries),
        "labeled": labeled,
        "hit@1": round(hit1 / labeled, 4) if labeled else None,
        "hit@3": round(hit3 / labeled, 4) if labeled else None,
        "mrr": round(reciprocal_rank / labeled, 4) if labeled else None,
        "handoff_accuracy": round(handoff_ok / handoff_total, 4) if handoff_total else None,
        "threshold": settings.score_threshold,
    }
    if args.json:
        print(json.dumps({"summary": summary, "details": details}, ensure_ascii=False, indent=2))
    else:
        print("\n=== 评测汇总 ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    settings = _settings(args)
    cases = load_cases(settings.data_file)
    chunks = count_chunks(settings)
    print(f"案例数：{len(cases)}")
    print(f"切片数：{chunks}")
    print(f"集合：{settings.collection_name}")
    if settings.embedding_provider == "hash":
        print("Embedding：hash384（离线联调，不具备语义能力）")
    else:
        print(f"Embedding：{settings.embedding_provider} / {settings.embed_model}")
    print(f"生成模型：{settings.llm_model}")
    print(f"阈值：{settings.score_threshold:.2f}；Top-K：{settings.top_k}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    return run_doctor(_settings(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log-rag",
        description="基于 LangChain + ChromaDB + Ollama 的日志案例检索与排障分析",
    )
    parser.add_argument("--debug", action="store_true", help="显示完整异常堆栈")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", type=Path, help="案例 JSON/JSONL 路径")
    common.add_argument("--provider", choices=["ollama", "hash"], help="embedding 提供方")
    common.add_argument("--threshold", type=float, help="相似度阈值 0~1")
    common.add_argument("--top-k", type=int, help="返回案例数，默认 3")
    common.add_argument("--json", action="store_true", help="以 JSON 输出")

    p_ingest = sub.add_parser("ingest", parents=[common], help="切片、向量化并写入 Chroma")
    p_ingest.add_argument("--append", action="store_true", help="增量更新（默认全量重建）")
    p_ingest.set_defaults(func=cmd_ingest)

    p_search = sub.add_parser("search", parents=[common], help="检索并生成排障分析")
    p_search.add_argument("query", nargs="?", help="错误日志文本")
    p_search.add_argument("--file", type=Path, help="从文件读取错误日志")
    p_search.add_argument("--no-llm", action="store_true", help="只检索，不调用生成模型")
    p_search.set_defaults(func=cmd_search)

    p_eval = sub.add_parser("eval", parents=[common], help="用标注集评估检索效果")
    p_eval.add_argument(
        "--queries",
        type=Path,
        default=PROJECT_ROOT / "eval" / "queries.jsonl",
        help="评测集 JSONL",
    )
    p_eval.set_defaults(func=cmd_eval)

    p_stats = sub.add_parser("stats", parents=[common], help="查看知识库统计")
    p_stats.set_defaults(func=cmd_stats)

    p_doctor = sub.add_parser("doctor", parents=[common], help="检查 Ollama、模型和数据")
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LLMUnavailableError as exc:
        # 单独给退出码 3，方便上层区分“模型不可用”和“没检索到”。
        print(f"模型调用失败：{exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        if getattr(args, "debug", False):
            raise
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
