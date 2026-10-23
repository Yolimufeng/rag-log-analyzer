from __future__ import annotations

from src.chunking import build_documents
from src.schema import LogCase, load_cases


def test_build_documents_has_stable_ids_and_headers(data_file):
    cases = load_cases(data_file)
    documents = build_documents(cases)

    assert len(cases) == 8
    assert len(documents) == 25
    assert len({doc.metadata["chunk_id"] for doc in documents}) == len(documents)

    for document in documents:
        assert document.page_content.startswith(f"案例 {document.metadata['case_id']}")
        assert "【" in document.page_content
        assert document.metadata["chunk_type"] in {"profile", "cause", "solution"}


def test_long_solution_is_split_with_context_header():
    case = LogCase(
        case_id="LOG-9999",
        title="超长处置步骤切片测试",
        error_type="Test",
        component="test",
        error_signature="a" * 20,
        root_cause="为了测试长文本切片，这里写一个足够长的根因说明。",
        resolution=[f"第 {i} 步：执行一段足够长的处置命令，确保整体超过切片阈值。" * 6 for i in range(6)],
        verification="验证通过。",
    )
    documents = build_documents([case], chunk_size=400, chunk_overlap=40)
    solution_docs = [doc for doc in documents if doc.metadata["chunk_type"] == "solution"]

    assert len(solution_docs) > 1
    assert all(doc.page_content.startswith("案例 LOG-9999") for doc in solution_docs)
    assert [doc.metadata["chunk_index"] for doc in solution_docs] == list(range(len(solution_docs)))
