# 日志案例 RAG：用本地模型检索历史排障记录

线上报错时，很多问题以前处理过，但记录散在聊天、工单和 Wiki 里，翻起来很慢。这个项目把历史案例整理成结构化数据，用本地 embedding 检索最相似的 Top3，再让本地模型基于这些案例生成排查建议；如果相似度不够，就生成一张人工工单，避免模型硬答。

技术栈：Python 3.10+、LangChain、ChromaDB、Ollama。

## 适合什么场景

- 单机或内网部署，日志和模型都不出本机。
- 案例规模几十到几万条，Chroma 单机够用。
- 给运维/研发做“相似故障检索 + 处置建议”，不自动执行修复。
- 不能接受模型编答案，需要“找不到就转人工”。

不适合：

- 做日志采集、告警平台。这个项目只接收一段日志文本或一个日志文件。
- 自动改配置、自动回滚、自动执行命令。
- 多租户、细粒度权限、高可用。这些要再包一层服务。

## 工作流程

```text
历史日志 / 工单 / Runbook
        │
        ▼
  结构化案例 cases.json
        │  校验、去重、脱敏
        ▼
  profile / cause / solution 三段切片
        │
        ▼
  Ollama bge-m3 生成向量
        │
        ▼
  ChromaDB（cosine）
        ▲
        │ 召回 Top15 切片
  新错误日志 ──> 清洗、截断 ──> bge-m3
        │
        ▼
  按 case_id 聚合，取 Top3
        │
        ▼
  最高分 >= 阈值？
     │是                │否
     ▼                  ▼
  qwen2.5 生成分析     人工工单
```

几个关键点：

- 一条案例拆成 `profile`、`cause`、`solution` 三个切片，而不是按固定字数硬切。`profile` 用来匹配原始报错，`solution` 用来承载处置步骤。
- 检索先召回 15 个切片，再按 `case_id` 聚合。否则同一个案例的 3 个切片可能把 Top3 占满。
- 最高分低于阈值就不调用生成模型。模型总会给出一个答案，这一步是为了挡住明显不相关的案例。
- 工单先落成本地 JSON 文件，方便跑通；后面要接飞书、Jira 或 Webhook，只需要替换 `src/handoff.py` 里的写出逻辑。

## 环境要求

| 项目 | 要求 | 开发时使用 |
|---|---|---|
| 操作系统 | Windows 10/11、Ubuntu 20.04+、macOS 12+ | Windows 11 |
| Python | 3.10 ~ 3.12 | 3.11.5 |
| Ollama | 0.5+ | 开发机未安装，使用离线模式验证 |
| Embedding 模型 | `bge-m3`（约 1.2GB） | 未拉取 |
| 生成模型 | `qwen2.5:7b-instruct`（约 4.7GB） | 未拉取 |
| 内存 | 7B 模型 CPU 推理建议 16GB 以上 | — |
| 显存 | 7B 模型 Q4 量化建议 8GB 以上 | — |
| 磁盘 | 至少 5GB（模型 + 向量库） | — |
| 端口 | 默认 `11434`（Ollama） | — |

依赖版本见 `requirements.txt`。开发时实际安装的是：

```text
langchain-core 0.3.86
langchain-text-splitters 0.3.11
langchain-ollama 0.3.10
langchain-chroma 0.2.6
chromadb 1.5.9
pydantic 2.14.1
```

更细的安装步骤、不同系统的命令和常见报错，放在 [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)。

## 快速开始

### 1. 安装 Ollama 和模型

Windows：

```powershell
winget install Ollama.Ollama
ollama serve
ollama pull bge-m3
ollama pull qwen2.5:7b-instruct
```

macOS / Linux：

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
ollama pull bge-m3
ollama pull qwen2.5:7b-instruct
```

确认服务在跑：

```bash
curl http://127.0.0.1:11434/api/tags
```

### 2. 安装 Python 依赖

```powershell
git clone <your-repo-url>
cd rag-log-analyzer
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

macOS / Linux 把最后两行换成：

```bash
source .venv/bin/activate
cp .env.example .env
```

先跑一次环境检查：

```bash
python -m src.cli doctor
```

`doctor` 会检查 Python 包、Ollama 是否可连、模型是否已拉取、案例文件和当前知识库切片数。缺什么它会直接给出 `ollama pull` 命令。

### 3. 建库并查询

```bash
python -m src.cli ingest
python -m src.cli search --file examples/oom.log
```

`ingest` 默认全量重建集合。改了案例后重新执行即可；只想更新某几条案例时用 `--append`。

### 4. 没有 Ollama 时先跑通链路

`hash` 模式用一个确定性的字符 n-gram 哈希向量代替 `bge-m3`，不需要模型，但**没有语义能力**，只适合验证代码流程：

```bash
python -m src.cli doctor --provider hash
python -m src.cli ingest --provider hash
python -m src.cli search --file examples/oom.log --provider hash --no-llm
python -m src.cli eval --provider hash --threshold 0.45
```

它只能匹配字面重合，同义改写的查询会漏。真实效果要以 `bge-m3` 为准。

## 数据格式

案例文件是 `data/cases.json`，顶层是数组，也可以写成 `{"cases": [...]}`。一条案例的字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `case_id` | 是 | 稳定唯一 ID，例如 `LOG-0001` |
| `title` | 是 | 一句话描述问题 |
| `error_type` | 是 | 错误分类，例如 `OOMKilled`、`Deadlock`、`502` |
| `component` | 是 | 所属组件，例如 `kubernetes`、`nginx`、`mysql` |
| `severity` | 否 | `low` / `medium` / `high` / `critical`，默认 `medium` |
| `error_signature` | 是 | 最典型的原始报错，保留错误码、退出码和关键堆栈 |
| `symptom` | 否 | 现象、影响范围、触发规律 |
| `environment` | 否 | 版本、运行时、部署方式等键值对 |
| `root_cause` | 是 | 已验证的根因，不要写“可能是” |
| `resolution` | 是 | 按执行顺序排列的处置步骤，至少一条 |
| `verification` | 否 | 怎么确认已经恢复 |
| `tags` | 否 | 标签，方便后续过滤 |
| `source` | 否 | 来源，默认 `manual` |
| `updated_at` | 否 | 更新时间，字符串即可 |

示例：

```json
{
  "case_id": "LOG-0001",
  "title": "Kubernetes Pod 因内存超限反复 OOMKilled",
  "error_type": "OOMKilled",
  "component": "kubernetes",
  "severity": "critical",
  "error_signature": "Reason: OOMKilled\nExit Code: 137",
  "symptom": "Pod 每 10-30 分钟重启一次，节点整体内存仍有富余。",
  "environment": {"runtime": "containerd 1.7"},
  "root_cause": "memory limit 512Mi 小于应用峰值 700Mi，触发 cgroup OOM。",
  "resolution": [
    "kubectl describe pod <pod> -n <ns>，确认 OOMKilled 和 Exit Code 137。",
    "把 limits.memory 调到 1Gi，滚动发布。"
  ],
  "verification": "观察 2 小时无重启。",
  "tags": ["k8s", "oom"],
  "source": "manual",
  "updated_at": "2025-06-12"
}
```

整理数据时注意几件事：

- 一条案例只写一个问题，不要把 OOM、磁盘满、证书过期混在一起。
- `error_signature` 尽量复制原始报错，不要改写成自然语言。
- `resolution` 每一步只做一件事，按顺序排。
- 入库前把 token、密码、手机号、内网 IP 这类信息替换掉。
- 同一个 `case_id` 重复导入时，程序会先删旧切片再写入，不会产生重复。

## 实现说明

### 切片

`src/chunking.py` 负责把案例拆成三段。每个切片都带同一个案例头：

```text
案例 LOG-0001｜Kubernetes Pod 因内存超限反复 OOMKilled
组件：kubernetes｜错误类型：OOMKilled｜级别：critical
【错误画像】
...
```

这样 `solution` 被切成多段后，仍然知道它属于哪个案例。默认切片长度 600 字符、重叠 80 字符；只有某个字段本身超长时才二次切分。

每个切片写入 Chroma 的 metadata 包括 `case_id`、`title`、`error_type`、`component`、`severity`、`chunk_type`、`chunk_index`、`chunk_id`、`tags`、`environment`、`source`、`updated_at`。`case_id` 用于聚合，`chunk_type` 用于拼接上下文。

### 检索与阈值

`src/search.py` 的流程：

1. 查询向量化。
2. 召回 `CANDIDATE_K`（默认 15）个切片。
3. 按 `case_id` 聚合，案例得分取最高切片得分。
4. 过滤掉低于 `SCORE_THRESHOLD` 的案例。
5. 按得分排序，最多返回 `TOP_K`（默认 3）个案例。
6. 用 `case_id` 把入选案例的所有切片取回来，按 `profile -> cause -> solution` 排序，作为生成上下文。

在 cosine 集合上，LangChain 返回的 relevance 是 `1 - cosine_distance`，**不是概率**。0.5 只是示例起点；不同 embedding 模型、不同日志分布的分数完全不同。上线前用自己的 30~50 条标注查询扫一遍阈值，具体做法见 [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md#8-阈值校准)。

### 生成

`src/generate.py` 用 `ChatOllama` 调本地模型，`temperature=0`，`num_ctx=8192`。Prompt 里限制了几件事：

- 只能使用检索到的案例。
- 推断要标注“推断”。
- 关键结论要带 `[案例 LOG-xxxx]`。
- 案例不够时写“证据不足，建议人工介入”。

模型输出固定四段：匹配结论、根因判断、处置步骤、验证与风险。它不会执行任何命令，命令需要人工确认。

不想调模型时加 `--no-llm`，只打印检索结果：

```bash
python -m src.cli search --file examples/oom.log --no-llm
```

### 人工工单

没有合格案例时，`src/handoff.py` 会在 `data/pending/` 下写一个 JSON 文件，同时在命令行返回退出码 `2`：

```json
{
  "ticket_id": "HT-20260612-111407-a1b2c3d4",
  "status": "open",
  "reason": "no_case_above_threshold",
  "query": "公司 VPN 登录提示账号或密码错误",
  "threshold": 0.5,
  "best_score": 0.32,
  "candidates": [
    {"case_id": "LOG-0004", "title": "Redis 内存达到 maxmemory 拒绝写入", "score": 0.32}
  ]
}
```

工单里保留低分候选，是给人工参考，不是机器结论。人工处理完把新案例补进 `data/cases.json`，执行 `python -m src.cli ingest --append`，再把这次查询加到 `eval/queries.jsonl`，防止后续回归。

退出码：

| 退出码 | 含义 |
|---|---|
| `0` | 命中并成功输出 |
| `2` | 未命中，已生成工单 |
| `3` | Ollama 或生成模型调用失败 |
| `1` | 参数、数据、检索等其他错误 |

## 配置

所有配置都可以通过 `.env` 或环境变量覆盖，默认值在 `src/config.py`。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama 服务地址 |
| `OLLAMA_EMBED_MODEL` | `bge-m3` | embedding 模型 |
| `OLLAMA_LLM_MODEL` | `qwen2.5:7b-instruct` | 生成模型 |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` 或 `hash` |
| `TOP_K` | `3` | 返回案例数 |
| `CANDIDATE_K` | `15` | 初始召回切片数 |
| `SCORE_THRESHOLD` | `0.50` | 相似度阈值 |
| `MAX_CHUNK_CHARS` | `600` | 单切片最大字符数 |
| `CHUNK_OVERLAP` | `80` | 切片重叠字符数 |
| `MAX_CONTEXT_CHARS` | `6000` | 生成时案例上下文总预算 |
| `COLLECTION_PREFIX` | `log_cases` | 集合名前缀 |

集合名会自动拼上 provider 和模型名，例如 `log_cases_ollama_bge-m3`。换 embedding 模型会落到新集合，避免维度不一致。

## 评测

评测集在 `eval/queries.jsonl`，每行一个 JSON：

```json
{"query": "upstream prematurely closed connection ... 502", "expected_case_ids": ["LOG-0002"]}
```

`expected_case_ids` 为空数组表示这个问题在知识库里没有答案，应该转人工。

运行：

```bash
python -m src.cli eval
```

输出每条查询的期望、实际返回和最高分，最后汇总 Hit@1、Hit@3、MRR 和转人工准确率。

示例数据在 hash 模式下的结果（仅验证流程，不代表 `bge-m3` 效果）：

| 阈值 | Hit@1 | Hit@3 | MRR | 转人工准确率 |
|---|---|---|---|---|
| 0.40 | 0.90 | 0.90 | 0.90 | 1.00 |
| 0.45 | 0.90 | 0.90 | 0.90 | 1.00 |
| 0.50 | 0.90 | 0.90 | 0.90 | 1.00 |
| 0.55 | 0.90 | 0.90 | 0.90 | 1.00 |
| 0.60 | 0.80 | 0.80 | 0.80 | 1.00 |
| 0.65 | 0.70 | 0.70 | 0.70 | 1.00 |

漏掉的那条是“容器退出码 137，Pod 反复重启”这种同义改写，hash 模式匹配不到，换 `bge-m3` 后会好一些。

跑测试：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

测试全部使用 hash 向量和临时目录，不会碰真实的 `storage/`，也不需要 Ollama。

## 目录结构

```text
rag-log-analyzer/
├─ data/
│  ├─ cases.json              # 示例案例
│  └─ pending/                # 自动生成的人工工单
├─ docs/
│  ├─ ENVIRONMENT.md          # 环境安装、配置、阈值校准、排错
│  └─ GITHUB_UPLOAD.md        # 上传 GitHub 的步骤
├─ eval/
│  └─ queries.jsonl           # 评测查询
├─ examples/
│  └─ oom.log                 # 示例错误日志
├─ scripts/
│  └─ package.ps1             # 生成干净 zip 的脚本
├─ src/
│  ├─ config.py               # 配置
│  ├─ schema.py               # 数据结构和校验
│  ├─ chunking.py             # 三段切片
│  ├─ embeddings.py           # Ollama / hash embedding
│  ├─ index.py                # Chroma 读写
│  ├─ search.py               # 召回、聚合、Top3
│  ├─ handoff.py              # 人工工单
│  ├─ generate.py             # 本地模型生成
│  ├─ doctor.py               # 环境自检
│  └─ cli.py                  # 命令行入口
├─ tests/
├─ .env.example
├─ requirements.txt
├─ requirements-dev.txt
├─ pyproject.toml
├─ LICENSE
└─ README.md
```

## 已验证与限制

开发时在 Windows 11 + Python 3.11.5 上跑过：

- 8 条示例案例切成 25 个切片，写入 Chroma 成功。
- OOM 日志命中 `LOG-0001`。
- VPN 库外问题最高分约 0.32，低于阈值，生成工单，退出码 2。
- hash 模式跑 12 条评测，阈值 0.40~0.55 时 Hit@3 为 0.90，库外问题转人工准确率为 1.00。
- `pytest -q` 通过 5 个测试。

没有在这个环境里验证的部分：

- Ollama 真实端到端。开发机没装 Ollama，`bge-m3` 和 `qwen2.5` 的实际调用没有跑过。
- 真实案例上的分数分布和生成质量。示例只有 8 条案例，只能用来验证流程。

已知限制：

- 单机文件型 Chroma，没有并发写入控制。
- 没有日志采集、解析和模板化，长日志只做截断。
- 没有混合检索和 rerank，纯向量召回。
- 生成结果需要人工复核，不能直接当操作手册。
- 没有鉴权，别直接暴露到公网。

## 上传 GitHub

仓库里已经准备好 `.gitignore`、`LICENSE` 和示例配置。上传前建议先看 [docs/GITHUB_UPLOAD.md](docs/GITHUB_UPLOAD.md)，里面包括清理生成物、初始化仓库、创建远程仓库和推送的命令。

简单说，不要提交这些：

```text
.venv/
storage/
data/pending/
__pycache__/
.pytest_cache/
.env
```

`storage/` 是本地向量库，`data/pending/` 是运行产生的工单，都不应该进仓库。

如果不想用 Git，可以运行 `scripts/package.ps1` 生成一个干净的 zip：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package.ps1
```

## License

MIT，见 [LICENSE](LICENSE)。
