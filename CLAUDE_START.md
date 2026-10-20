# Windows：启动独立 Claude Code 交互界面

在本项目根目录打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_claude.ps1
```

首次会提示输入中转站 Base URL、模型 ID、认证方式和 API Key。密钥输入会被遮挡；配置保存在本机 Windows 用户环境变量，认证方式名称写入已被忽略的 `claude_auth_method.local.txt`，实际密钥不写入项目文件。

程序查找 PATH、用户原生安装目录及常见桌面版附带的 Claude Code CLI，然后在本项目目录启动交互界面。桌面版更新后也会重新发现路径。

重新配置或指定其他项目：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_claude.ps1 -Reconfigure
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_claude.ps1 -ProjectPath "D:\projects\your-project"
```

只检查程序和配置是否存在，不修改用户环境、不显示密钥、不调用模型：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_claude.ps1 -CheckOnly
```

“存在凭据”不代表中转站实际接受请求。进入 Claude Code 后可以发送“只回复 OK”验证连通性。

这个交互界面独立于自动编排。若想启动自动任务，回到 PowerShell 执行 README 中的 `python orchestrate.py run ...`。
