# 上传 GitHub

本目录是从本机工作目录中按清单提取的公开源码快照。请以此目录为上传根目录；原来的工作目录继续用于个人运行。

## 已保留

- 最新 `orchestrate.py`，包括实时问答总线、MCP 服务、后台 Claude responder、阶段 JSON 和交流记录。
- 核心自动化测试、任务模板、工具配置模板和 Windows Claude 启动脚本。
- 完全背包待实现示例及其验收测试。
- Python MPC 代码、测试、依赖说明和真实 Claude 审查入口。
- 改为相对路径的 README、架构、启动与验证说明。

`PUBLICATION_SOURCE.json` 记录复制文件的 SHA-256；核心编排、测试及示例 Python 文件按原样提取。

## 已排除

- `runs/`、`.bus/`、`reviews/`：实际提示词、问答、原始响应、代码差异、诊断和本机路径。
- `artifacts/`：生成的仿真图、CSV 和指标。
- `__pycache__/`、字节码、环境目录。
- `tools.local.json`、`claude_auth_method.local.txt`、`review_status.json` 以及其他实际本机配置。
- 旧 `VALIDATION.md` 中的登录状态、个人运行历史链接与桌面路径。
- 原 `flow.png`：其底部仍引用旧 `.bus` / `bus.py` 用法；公开文档改为与当前实现一致的 Mermaid 图。

`.gitignore` 同时排除环境文件、常见凭据文件、密钥文件及新的运行产物。自动模式扫描只是一层检查，不等于能识别所有形式的敏感信息。以后新增文件时，提交前仍应查看 `git diff --cached`。

## 上传

先在 GitHub 创建一个空仓库，在本目录的终端执行以下命令。远程地址替换成自己的仓库地址；这些命令由你执行才会真正上传。

```powershell
git init
git add .
git status --short
git diff --cached --stat
git commit -m "Prepare Codex-Claude orchestrator source"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/codex-claude-orchestrator.git
git push -u origin main
```

如果通过网页上传，请选择本目录里的源码与说明文件，包括 `.gitignore`，不要选择原来的个人运行目录。ZIP 中保留一个完整项目根文件夹，解压后再作为仓库根目录使用。

本次未替作者选择开源许可证。若希望明确授权别人修改和分发，请由作者选择许可证后添加 `LICENSE`。
