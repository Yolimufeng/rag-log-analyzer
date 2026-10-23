from __future__ import annotations

import json

from src.handoff import create_ticket
from src.index import count_chunks, ingest
from src.schema import load_cases
from src.search import retrieve


def test_ingest_is_idempotent_and_retrieves_expected_case(settings, data_file):
    cases = load_cases(data_file)
    first = ingest(cases, settings, rebuild=True)
    ingest(cases, settings, rebuild=False)

    assert first.chunks == 25
    assert count_chunks(settings) == 25

    result = retrieve(
        "Back-off restarting failed container payment-api Reason: OOMKilled Exit Code: 137",
        settings,
    )
    assert result.matched
    assert result.accepted[0].case_id == "LOG-0001"
    assert 1 <= len(result.accepted) <= 3
    assert "【根因分析】" in result.accepted[0].context


def test_no_match_creates_human_ticket(settings, data_file):
    cases = load_cases(data_file)
    ingest(cases, settings, rebuild=True)

    query = "公司 VPN 登录提示账号或密码错误，无法连接内网"
    result = retrieve(query, settings)
    assert not result.matched
    assert result.best_score is not None

    ticket = create_ticket(query, result, settings)
    payload = json.loads(ticket.read_text(encoding="utf-8"))
    assert ticket.exists()
    assert payload["status"] == "open"
    assert payload["reason"] == "no_case_above_threshold"
    assert payload["query"] == query
    assert len(payload["candidates"]) == 3


def test_empty_knowledge_base_hands_off(settings):
    result = retrieve("任意日志", settings)
    assert not result.matched
    assert result.candidates == []

    ticket = create_ticket("任意日志", result, settings)
    payload = json.loads(ticket.read_text(encoding="utf-8"))
    assert payload["reason"] == "empty_knowledge_base"
