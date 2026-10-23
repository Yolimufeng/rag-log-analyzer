# 打包并上传 GitHub

这份文档按“本地整理 → 建仓 → 推送 → 检查”的顺序写。命令默认在项目根目录 `rag-log-analyzer/` 下执行。

## 1. 上传前先清理

下面这些是本地运行产生的，不应该进仓库：

```text
.venv/
storage/
data/pending/
__pycache__/
.pytest_cache/
.env
```

`.gitignore` 已经覆盖了它们。上传前可以再确认一遍：

```powershell
Get-ChildItem -Force
```

正常情况下应该只看到源码、文档、示例数据和配置文件。

如果你之前跑过 `ingest`，`storage/` 里会有 Chroma 的数据库文件；如果你跑过未命中的查询，`data/pending/` 里会有工单。这两个目录都不要提交。

## 2. 确认 Git 可用

```bash
git --version
```

如果提示找不到命令：

- Windows：安装 [Git for Windows](https://git-scm.com/download/win)，或者用 GitHub Desktop。
- macOS：`brew install git`，或者安装 Xcode Command Line Tools。
- Linux：`sudo apt install git` / `sudo dnf install git`。

没有本地 Git 也可以先用 GitHub 网页的 “Add file → Upload files” 上传，但超过几十个文件时很麻烦，建议还是装 Git。

## 3. 初始化仓库

```bash
cd rag-log-analyzer
git init -b main
git add .
git status
```

`git status` 里不应该出现 `.venv/`、`storage/`、`data/pending/`、`.env`。如果出现了，先检查 `.gitignore`，不要继续提交。

确认没问题后提交：

```bash
git config user.name "你的名字"
git config user.email "你的邮箱"
git commit -m "init: local log RAG with LangChain, ChromaDB and Ollama"
```

这里的 `user.name` 和 `user.email` 只写入当前仓库的 `.git/config`，不会改全局配置。想用全局配置就去掉 `--local` 以外的参数，直接 `git config --global ...`。

## 4. 在 GitHub 创建仓库

1. 打开 [github.com/new](https://github.com/new)。
2. Repository name 填 `rag-log-analyzer`。
3. 选择 Public 或 Private。
4. **不要**勾选 “Add a README file”“Add .gitignore”“Choose a license”，因为本地已经有了。
5. 点 Create repository。

创建完成后，GitHub 会显示仓库地址，例如：

```text
https://github.com/<your-name>/rag-log-analyzer.git
```

## 5. 关联远程仓库并推送

```bash
git remote add origin https://github.com/<your-name>/rag-log-analyzer.git
git push -u origin main
```

如果使用 SSH：

```bash
git remote add origin git@github.com:<your-name>/rag-log-analyzer.git
git push -u origin main
```

第一次用 HTTPS 推送时，GitHub 不再接受账号密码，需要用 Personal Access Token。生成方式：GitHub → Settings → Developer settings → Personal access tokens。不要把 token 写进仓库或截图里。

推送成功后刷新仓库页面，确认 README、LICENSE、`src/`、`data/`、`docs/` 都在。

## 6. 打包成 zip（可选）

项目里带了一个打包脚本，会排除虚拟环境、向量库、工单、缓存和 `.env`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package.ps1
```

默认在项目上一级生成 `rag-log-analyzer.zip`。也可以指定输出路径：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package.ps1 -Output D:\tmp\rag-log-analyzer.zip
```

如果已经提交到 Git，更推荐用 `git archive`，它只会导出被跟踪的文件：

```bash
git archive --format=zip --output ../rag-log-analyzer.zip HEAD
```

压缩完检查一下内容：

```powershell
Expand-Archive "..\rag-log-analyzer.zip" -DestinationPath "$env:TEMP\rag-log-analyzer-check" -Force
Get-ChildItem "$env:TEMP\rag-log-analyzer-check" -Force
```

确认没有 `.venv`、`storage`、`data/pending`、`.env` 再上传。

## 7. 推送后检查

- README 里的命令能不能照着跑。
- `LICENSE` 年份和署名要不要改。
- 仓库里有没有真实日志、内网地址、token、客户数据。
- `storage/` 和 `data/pending/` 是否被忽略。
- GitHub Actions 没配置也没关系，这个项目不依赖 CI。

如果误提交了敏感文件，光删文件不够，还要清理 Git 历史。最简单的做法是删掉远程仓库重建，或者用 `git filter-repo`。不要把 token 留在历史里。

## 8. 常见问题

**`src refspec main does not match any`**

还没有提交。先 `git add .` 和 `git commit`，再推送。

**`remote origin already exists`**

```bash
git remote set-url origin https://github.com/<your-name>/rag-log-analyzer.git
```

**`failed to push some refs`**

远程仓库初始化时带了 README，和本地历史不一致。可以：

```bash
git pull --rebase origin main
git push -u origin main
```

或者删掉远程仓库重建，保持本地为准。

**文件太大**

`storage/` 里的 Chroma 数据库不要提交。GitHub 单文件上限 100MB，超过会拒绝推送。这个项目的源码和示例数据很小，正常不会遇到。

**想改仓库名**

GitHub 仓库设置里改名后，本地更新远程地址：

```bash
git remote set-url origin https://github.com/<your-name>/<new-name>.git
```
