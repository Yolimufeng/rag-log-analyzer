# 环境安装与配置

这份文档说明项目需要什么环境、怎么装，以及常见报错怎么处理。命令以 Windows PowerShell 为主，macOS / Linux 的差异会单独标出来。

## 1. 环境清单

| 项目 | 最低要求 | 建议 | 开发时使用 |
|---|---|---|---|
| 操作系统 | Windows 10、Ubuntu 20.04、macOS 12 | Windows 11 / Ubuntu 22.04 | Windows 11 |
| Python | 3.10 | 3.11 或 3.12 | 3.11.5 |
| Ollama | 0.5 | 最新稳定版 | 未安装（用 hash 模式验证） |
| Embedding 模型 | `bge-m3` | `bge-m3` | 未拉取 |
| 生成模型 | 任意 Ollama 对话模型 | `qwen2.5:7b-instruct` | 未拉取 |
| 内存 | 8GB | 16GB 以上 | — |
| 显存 | 非必须 | 8GB 以上（7B Q4） | — |
| 磁盘 | 3GB | 10GB 以上 | — |
| 网络 | 能访问 Ollama 本机端口 | — | — |

说明：

- 7B 模型用 CPU 也能跑，但生成速度会慢很多。只做检索、不做生成时，`--no-llm` 不需要生成模型。
- `bge-m3` 约 1.2GB，`qwen2.5:7b-instruct` Q4 量化约 4.7GB，加上向量库和 Python 依赖，留 10GB 比较稳妥。
- Ollama 默认监听 `127.0.0.1:11434`。如果改了地址，同步修改 `.env` 里的 `OLLAMA_BASE_URL`。

## 2. 安装 Ollama

### Windows

方式一，winget：

```powershell
winget install Ollama.Ollama
```

方式二，从 [ollama.com/download](https://ollama.com/download) 下载安装包。

安装完成后，Ollama 通常会随系统启动。也可以手动开一个终端：

```powershell
ollama serve
```

### macOS

```bash
brew install ollama
# 或者下载 https://ollama.com/download/Ollama-darwin.zip
ollama serve
```

### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl enable --now ollama
```

如果没有 systemd，直接前台启动：

```bash
ollama serve
```

### 检查服务

```bash
curl http://127.0.0.1:11434/api/tags
```

返回 JSON 就说明服务正常。浏览器打开 `http://127.0.0.1:11434` 看到 “Ollama is running” 也可以。

如果 `curl` 报连接失败：

- 确认 `ollama serve` 的终端还开着，或者服务已经注册为系统服务。
- 确认端口没有被别的程序占用：Windows 用 `netstat -ano | findstr 11434`，Linux 用 `ss -lntp | grep 11434`。
- 如果改了监听地址，检查防火墙是否放行。

## 3. 拉取模型

```bash
ollama pull bge-m3
ollama pull qwen2.5:7b-instruct
```

确认：

```bash
ollama list
```

应该能看到这两个模型。名字后面的 `:latest` 是 Ollama 自动补的，不影响使用。

如果下载慢：

- 先确认磁盘空间足够。
- 国内网络可以给终端配代理，或者换一个能访问 Ollama 模型仓库的网络。
- 不建议在项目里写死镜像地址，换模型时容易混乱。

低配机器可以把生成模型换成：

```bash
ollama pull qwen2.5:3b-instruct
```

然后修改 `.env`：

```dotenv
OLLAMA_LLM_MODEL=qwen2.5:3b-instruct
```

## 4. 安装 Python 依赖

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

跑测试需要额外装开发依赖：

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

如果激活脚本被 PowerShell 执行策略拦住：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

然后重新激活。也可以不激活，直接用绝对路径：

```powershell
.\.venv\Scripts\python.exe -m src.cli doctor
```

## 5. 配置

复制示例配置：

```powershell
copy .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

配置项：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama 地址 |
| `OLLAMA_EMBED_MODEL` | `bge-m3` | embedding 模型 |
| `OLLAMA_LLM_MODEL` | `qwen2.5:7b-instruct` | 生成模型 |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama` 或 `hash` |
| `TOP_K` | `3` | 最终返回案例数 |
| `CANDIDATE_K` | `15` | 初始召回切片数 |
| `SCORE_THRESHOLD` | `0.50` | 相似度阈值 |
| `MAX_CHUNK_CHARS` | `600` | 单切片最大字符数 |
| `CHUNK_OVERLAP` | `80` | 切片重叠字符数 |
| `MAX_CONTEXT_CHARS` | `6000` | 生成时案例上下文预算 |
| `COLLECTION_PREFIX` | `log_cases` | 集合名前缀 |

`.env` 不要提交到 Git。仓库里的 `.env.example` 只是模板。

## 6. 环境自检

```bash
python -m src.cli doctor
```

正常情况下会输出 Python 版本、依赖版本、Ollama 状态、模型是否齐全、案例文件数量和当前集合的切片数。

常见结果：

- `Ollama：不可用`：服务没启动，或者地址/端口不对。
- `缺少模型：bge-m3`：执行 `ollama pull bge-m3`。
- `知识库：...（0 个切片）`：还没执行 `ingest`，或者 provider/模型换了，集合名变了。
- `数据文件：无法读取`：`data/cases.json` 不存在或 JSON 格式有误。

没有 Ollama 时可以先检查离线模式：

```bash
python -m src.cli doctor --provider hash
```

## 7. 建库与运行

```bash
python -m src.cli ingest
python -m src.cli search --file examples/oom.log
```

首次 `ingest` 会调用 Ollama 生成向量，案例多的时候需要等一会儿。之后再查询会快很多。

如果只想验证代码流程，不装 Ollama：

```bash
python -m src.cli ingest --provider hash
python -m src.cli search --file examples/oom.log --provider hash --no-llm
```

`hash` 模式只做字符 n-gram 哈希，不能理解同义表达，不要用它评估真实效果。

## 8. 阈值校准

不同 embedding 模型的分数分布不一样，`0.50` 只是起点。建议这样做：

1. 从真实工单里挑 30~50 条查询，覆盖不同组件和错误类型。
2. 其中至少 20% 是知识库覆盖不到的问题，`expected_case_ids` 写空数组。
3. 跑一组阈值，记录 Hit@3 和库外问题的误接受情况：

```powershell
foreach ($t in 0.40,0.45,0.50,0.55,0.60,0.65) {
  python -m src.cli eval --threshold $t
}
```

macOS / Linux：

```bash
for t in 0.40 0.45 0.50 0.55 0.60 0.65; do
  python -m src.cli eval --threshold "$t"
done
```

4. 选一个拐点：再提高阈值，Hit@3 明显下降；再降低，错误接受明显增加。
5. 每次批量新增案例后重新跑一遍，阈值可能需要微调。

阈值优先保证“错答少”，再追求“命中多”。错的处置建议比转人工代价高。

## 9. 常见报错

| 报错 | 可能原因 | 处理 |
|---|---|---|
| `Connection refused` / `WinError 10061` | Ollama 没启动、地址或端口不对 | 执行 `ollama serve`，检查 `OLLAMA_BASE_URL` |
| `model "bge-m3" not found` | 模型没拉取 | `ollama pull bge-m3` |
| `failed to connect to chromadb` | Chroma 目录权限或文件被占用 | 关闭占用进程，检查 `storage/` 权限 |
| `Collection expecting embedding with dimension ...` | 换了 embedding 模型但复用了旧集合 | 用新 provider/模型重新 `ingest`，或删除 `storage/chroma` |
| `Relevance scores must be between 0 and 1` | 集合距离函数不是 cosine | 确认集合元数据是 `hnsw:space=cosine`，必要时重建 |
| `No space left on device` | 磁盘满 | 清理 `storage/` 或换磁盘 |
| `ModuleNotFoundError` | 没激活虚拟环境 | 用 `.venv` 里的 Python 执行 |
| `pytest` 找不到 `src` | 不在项目根目录 | `cd rag-log-analyzer` 后重试 |
| 首次查询很慢 | 模型冷启动 | 先跑一次查询预热；或只做检索用 `--no-llm` |

如果报错信息不够，用 `--debug` 看完整堆栈：

```bash
python -m src.cli --debug search --file examples/oom.log
```

注意 `--debug` 是顶层参数，要放在子命令前面。

## 10. 安全注意事项

- 案例里不要保留真实密码、token、身份证、手机号、客户数据。入库前替换成占位符。
- `storage/` 里是向量和原始切片文本，可能包含敏感信息，不要提交到公开仓库。
- `data/pending/` 里的工单包含原始日志，也不要提交。
- Ollama 默认只监听本机。不要在没有鉴权的情况下把 `11434` 暴露到公网。
- 模型生成的命令必须人工确认后执行。这个项目不会自动执行任何操作。

## 11. 已验证范围

开发时在 Windows 11、Python 3.11.5 上验证了：

- 依赖可以安装，`pytest` 5 个测试通过。
- hash 模式可以建库、检索、评测和生成工单。
- 8 条示例案例产生 25 个切片。
- 默认 Ollama 模式下，未启动服务时 `doctor` 会给出明确提示，不会崩溃。

没有验证：

- Ollama 服务端和 `bge-m3` / `qwen2.5` 的真实调用。开发机没装 Ollama。
- GPU 推理速度、显存占用、不同量化版本的差异。
- 大规模案例（上万条）下的建库时间和检索延迟。

这些需要在你自己的机器上用真实数据补测。
