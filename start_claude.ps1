param(
    [switch]$Reconfigure,
    [switch]$CheckOnly,
    [string]$ProjectPath = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

function Find-ClaudeExecutable {
    $installed = Get-Command 'claude.exe' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($installed) { return $installed.Source }
    $standalone = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
    if (Test-Path -LiteralPath $standalone) { return $standalone }
    $candidates = @()
    foreach ($root in @(
        (Join-Path $env:LOCALAPPDATA 'Claude-3p\claude-code'),
        (Join-Path $env:LOCALAPPDATA 'Claude\claude-code')
    )) {
        if (Test-Path -LiteralPath $root) {
            $candidates += Get-ChildItem -LiteralPath $root -Filter 'claude.exe' -File -Recurse -ErrorAction SilentlyContinue
        }
    }
    $selected = $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($selected) { return $selected.FullName }
    throw '没有找到 Claude Code。请先安装 Claude Code CLI。'
}

function Get-ConfiguredValue([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name, 'User')
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    }
    return $value
}

function Read-RequiredText([string]$Prompt, [string]$Default) {
    while ($true) {
        $label = $Prompt
        if (-not [string]::IsNullOrWhiteSpace($Default)) { $label += "（回车沿用：$Default）" }
        $answer = Read-Host $label
        if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $Default }
        if (-not [string]::IsNullOrWhiteSpace($answer)) { return $answer.Trim() }
        Write-Host '此项不能为空，请重新输入。' -ForegroundColor Yellow
    }
}

try {
    $claudeExecutable = Find-ClaudeExecutable
    $baseUrl = Get-ConfiguredValue 'ANTHROPIC_BASE_URL'
    $modelId = Get-ConfiguredValue 'ANTHROPIC_MODEL'
    $credential = Get-ConfiguredValue 'ANTHROPIC_AUTH_TOKEN'
    $credentialVariable = 'ANTHROPIC_AUTH_TOKEN'
    if ([string]::IsNullOrWhiteSpace($credential)) {
        $credential = Get-ConfiguredValue 'ANTHROPIC_API_KEY'
        if (-not [string]::IsNullOrWhiteSpace($credential)) { $credentialVariable = 'ANTHROPIC_API_KEY' }
    }
    if ($CheckOnly) {
        Write-Host "Claude Code：$claudeExecutable"
        Write-Host ('已保存中转地址：' + (-not [string]::IsNullOrWhiteSpace($baseUrl)))
        Write-Host ('已保存模型名：' + (-not [string]::IsNullOrWhiteSpace($modelId)))
        Write-Host ('已保存密钥：' + (-not [string]::IsNullOrWhiteSpace($credential)))
        Write-Host '本次仅检查，不输入、不显示密钥，不修改配置、不调用模型。'
        exit 0
    }
    if (-not (Test-Path -LiteralPath $ProjectPath -PathType Container)) {
        throw '项目目录不存在，请检查 -ProjectPath 参数。'
    }
    if ($Reconfigure -or [string]::IsNullOrWhiteSpace($baseUrl) -or
        [string]::IsNullOrWhiteSpace($modelId) -or [string]::IsNullOrWhiteSpace($credential)) {
        Write-Host '首次配置 Claude Code 中转 API' -ForegroundColor Cyan
        Write-Host '请直接在提示后输入内容，不需要修改脚本。密钥输入时会被遮挡。'
        Write-Host '这些设置将保存到本机 Windows 用户环境变量，以后双击即可启动。'
        while ($true) {
            $baseUrl = Read-RequiredText '中转站 Base URL（按站方 Claude Code 接入说明填写）' $baseUrl
            $parsed = $null
            if ([Uri]::TryCreate($baseUrl, [UriKind]::Absolute, [ref]$parsed) -and
                $parsed.Scheme -eq 'https' -and [string]::IsNullOrEmpty($parsed.UserInfo)) { break }
            Write-Host '请填写有效的 HTTPS 地址，且不要把密钥放进地址。' -ForegroundColor Yellow
            $baseUrl = $null
        }
        $modelId = Read-RequiredText '模型 ID（按中转站提供的名称填写）' $modelId
        $choice = Read-Host '认证方式：1=Bearer（之前成功使用的方式），2=x-api-key；回车选1'
        if ($choice -eq '2') { $credentialVariable = 'ANTHROPIC_API_KEY' }
        else { $credentialVariable = 'ANTHROPIC_AUTH_TOKEN' }
        do {
            $secureKey = Read-Host '请输入 API Key，然后回车' -AsSecureString
            $credential = [System.Net.NetworkCredential]::new('', $secureKey).Password
            if ([string]::IsNullOrWhiteSpace($credential)) { Write-Host '密钥不能为空。' -ForegroundColor Yellow }
        } while ([string]::IsNullOrWhiteSpace($credential))
        $credential = $credential.Trim()
        # Write only the selected authentication method; do not print the key.
        [Environment]::SetEnvironmentVariable('ANTHROPIC_BASE_URL', $baseUrl, 'User')
        [Environment]::SetEnvironmentVariable('ANTHROPIC_MODEL', $modelId, 'User')
        [Environment]::SetEnvironmentVariable($credentialVariable, $credential, 'User')
        # Remember the selected method for this launcher without changing other
        # applications' previously saved credential variables.
        $selectionFile = Join-Path $PSScriptRoot 'claude_auth_method.local.txt'
        [IO.File]::WriteAllText($selectionFile, $credentialVariable)
        Write-Host '配置已保存到本机。实际连接状态请在 Claude Code 中发送一条消息确认。' -ForegroundColor Green
    }
    else {
        $selectionFile = Join-Path $PSScriptRoot 'claude_auth_method.local.txt'
        if (Test-Path -LiteralPath $selectionFile) {
            $selectedMethod = [IO.File]::ReadAllText($selectionFile).Trim()
            if ($selectedMethod -in @('ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY')) {
                $selectedCredential = Get-ConfiguredValue $selectedMethod
                if (-not [string]::IsNullOrWhiteSpace($selectedCredential)) {
                    $credentialVariable = $selectedMethod
                    $credential = $selectedCredential
                }
            }
        }
    }
    [Environment]::SetEnvironmentVariable('ANTHROPIC_BASE_URL', $baseUrl, 'Process')
    [Environment]::SetEnvironmentVariable('ANTHROPIC_MODEL', $modelId, 'Process')
    [Environment]::SetEnvironmentVariable('ANTHROPIC_AUTH_TOKEN', $null, 'Process')
    [Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', $null, 'Process')
    [Environment]::SetEnvironmentVariable($credentialVariable, $credential, 'Process')
    Set-Location -LiteralPath $ProjectPath
    $host.UI.RawUI.WindowTitle = 'Claude Code'
    Write-Host "项目目录：$ProjectPath" -ForegroundColor Cyan
    Write-Host '正在启动 Claude Code 交互界面。首次出现目录信任提示时，请核对目录。'
    & $claudeExecutable --model $modelId
    $cliExit = $LASTEXITCODE
    Write-Host "Claude Code 已退出（退出码 $cliExit）。"
    Read-Host '按回车关闭窗口' | Out-Null
    exit $cliExit
}
catch {
    # Avoid printing raw provider errors or environment values containing keys.
    Write-Host '启动未完成，请检查 CLI、目录和中转配置。' -ForegroundColor Red
    Write-Host $_.Exception.GetType().Name
    if (-not $CheckOnly) { Read-Host '按回车关闭窗口' | Out-Null }
    exit 1
}
