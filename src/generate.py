"""调用本地 Ollama 模型，生成“有依据”的排障分析。"""

from __future__ import annotations

from langchain_ollama import ChatOllama

from .config import Settings
from .search import CaseHit, format_case_context


class LLMUnavailableError(RuntimeError):
    pass


SYSTEM_RULES = """你是资深 SRE 日志排障助手。你必须遵守：
1. 只能依据“历史案例”中的内容回答，不得补充案例中不存在的命令、配置、版本或结论。
2. 区分“案例明确记载的事实”和“你的推断”；推断必须标注“推断”。
3. 每个关键结论后用 [案例 LOG-xxxx] 标注依据。
4. 如果历史案例不足以覆盖用户日志，必须明确写“证据不足，建议人工介入”，不要硬套。
5. 输出简洁、可执行，优先给排障顺序，不要泛泛而谈。"""


def build_prompt(query: str, hits: list[CaseHit], settings: Settings) -> str:
    # 把上下文预算平均分给每个候选案例；至少留 800 字符，避免根因被截没。
    per_case = max(800, settings.max_context_chars // max(1, len(hits)))
    cases_text = "\n\n".join(
        f"### 候选案例 {index}（case_id={hit.case_id}，相似度={hit.score:.3f}）\n"
        f"{format_case_context(hit, max_chars=per_case)}"
        for index, hit in enumerate(hits, 1)
    )
    return f"""{SYSTEM_RULES}

用户提供的错误日志：
<<<LOG
{query}
LOG>>>

检索到的历史案例（仅这些内容可作为依据）：
{cases_text}

请按以下结构输出：
## 1. 匹配结论
最可能对应哪个/哪些案例；列出 2-3 条关键匹配证据（报错文本、组件、退出码等）。
## 2. 根因判断
说明最可能的根因；区分案例事实与推断。
## 3. 处置步骤
按执行顺序给出编号步骤，尽量可直接复制执行；标注依据案例。
## 4. 验证与风险
说明如何验证恢复，以及操作风险/回滚点。
"""


def generate_answer(query: str, hits: list[CaseHit], settings: Settings) -> str:
    if not hits:
        raise ValueError("没有可用的检索结果，不应调用生成模型")

    llm = ChatOllama(
        model=settings.llm_model,
        base_url=settings.ollama_base_url,
        # 排障场景不需要创造性；上下文给到 8k，3 个案例基本够用。
        temperature=0,
        num_ctx=8192,
    )
    try:
        response = llm.invoke(build_prompt(query, hits, settings))
    except Exception as exc:  # 连接失败、模型不存在、超时等
        # LangChain 会把底层 httpx/ollama 异常包一层，这里统一转成 CLI 可读的提示。
        raise LLMUnavailableError(
            f"调用 Ollama 失败（model={settings.llm_model}, base_url={settings.ollama_base_url}）。"
            "请确认 `ollama serve` 已启动且模型已 pull。"
        ) from exc

    content = response.content
    if isinstance(content, list):
        # 某些模型的 content 是 block 列表
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    answer = str(content).strip()
    if not answer:
        raise LLMUnavailableError("Ollama 返回了空内容")
    return answer
