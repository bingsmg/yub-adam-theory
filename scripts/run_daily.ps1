<#
.SYNOPSIS
    Adam's Theory 每日推荐管道 — PowerShell 增强版
.DESCRIPTION
    1. 增量更新股票数据
    2. 运行亚当理论检测 + 生成报告
    3. 推送飞书通知
    4. 失败时发送 Windows 通知
.PARAMETER Limit
    分析的股票数量上限 (默认 500)
.PARAMETER SkipUpdate
    跳过数据拉取，仅分析缓存数据
.PARAMETER SendToast
    失败时发送 Windows Toast 通知 (默认 $true)
.EXAMPLE
    .\scripts\run_daily.ps1
    .\scripts\run_daily.ps1 -Limit 200 -SkipUpdate
.NOTES
    配合 Windows 任务计划程序使用：
    操作 → 启动程序：
      程序：powershell.exe
      参数：-ExecutionPolicy Bypass -File "E:\Projects\ClaudeCodeProjects\yd-project\scripts\run_daily.ps1"
      起始于：E:\Projects\ClaudeCodeProjects\yd-project
#>

param(
    [int]$Limit = 500,
    [switch]$SkipUpdate = $false,
    [switch]$SendToast = $true
)

$ErrorActionPreference = "Stop"
$ProjectDir = "E:\Projects\ClaudeCodeProjects\yd-project"
$PythonExe  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogDir     = Join-Path $ProjectDir "output\logs"

# ── 初始化 ────────────────────────────────────────────────────────────────

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogTimestamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "run_daily_$LogTimestamp.log"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Level] $Message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Send-Toast {
    param([string]$Title, [string]$Message)
    if (-not $SendToast) { return }
    try {
        # Windows 10/11 Toast 通知
        Add-Type -AssemblyName System.Windows.Forms
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.BalloonTipTitle = $Title
        $notify.BalloonTipText = $Message
        $notify.Visible = $true
        $notify.ShowBalloonTip(10000)  # 10 秒
        Start-Sleep -Seconds 1
        $notify.Dispose()
    } catch {
        # Toast 发送失败不影响主流程
        Write-Log "Toast notification failed: $_" "WARN"
    }
}

# ── 主流程 ────────────────────────────────────────────────────────────────

Write-Log "============================================"
Write-Log "  Adam's Theory Daily Pipeline (PowerShell)"
Write-Log "  Project: $ProjectDir"
Write-Log "  Limit: $Limit | SkipUpdate: $SkipUpdate"
Write-Log "============================================"

# 检查 Python 环境
if (-not (Test-Path $PythonExe)) {
    $msg = "Python venv not found: $PythonExe"
    Write-Log $msg "ERROR"
    Send-Toast "Adam's Theory ❌" "虚拟环境未找到，请检查路径"
    exit 1
}

# 检查 .env
$envFile = Join-Path $ProjectDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Log ".env not found, using default settings" "WARN"
}

Set-Location $ProjectDir

# 记录开始时间
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# ── Step 1: 数据更新 + 分析 + 飞书通知 ──────────────────────────────────

Write-Log "" "INFO"
Write-Log "[Step 1/2] Running daily update + Feishu notification..." "INFO"

$dailyArgs = @(
    "scripts/daily_update.py",
    "--limit", $Limit,
    "--output", "both",
    "--notify", "feishu",
    "--log-level", "INFO"
)
if ($SkipUpdate) {
    $dailyArgs += "--no-update"
}

try {
    $proc = Start-Process -FilePath $PythonExe -ArgumentList $dailyArgs `
        -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "stdout_$LogTimestamp.txt") `
        -RedirectStandardError (Join-Path $LogDir "stderr_$LogTimestamp.txt")

    if ($proc.ExitCode -ne 0) {
        Write-Log "daily_update.py failed (exit $($proc.ExitCode)), retrying with --no-update..." "WARN"
        $fallbackArgs = @("scripts/daily_update.py", "--no-update", "--limit", $Limit, "--output", "both", "--notify", "feishu", "--log-level", "INFO")
        $proc = Start-Process -FilePath $PythonExe -ArgumentList $fallbackArgs `
            -NoNewWindow -Wait -PassThru
    }

    $exitCode = $proc.ExitCode
    Write-Log "[Step 1/2] Done. Exit code: $exitCode, Elapsed: $([math]::Round($sw.Elapsed.TotalMinutes, 1))min" "INFO"
} catch {
    Write-Log "daily_update.py crashed: $_" "ERROR"
    $exitCode = 99
}

# ── Step 2: 清理 ─────────────────────────────────────────────────────────

Write-Log "" "INFO"
Write-Log "[Step 2/2] Cleaning up old logs (30 days)..." "INFO"
try {
    Get-ChildItem -Path $LogDir -Filter "run_daily_*.log" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
        Remove-Item -Force
    Get-ChildItem -Path $LogDir -Filter "stdout_*.txt" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
        Remove-Item -Force
    Get-ChildItem -Path $LogDir -Filter "stderr_*.txt" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
        Remove-Item -Force
    Write-Log "[OK] Cleanup done" "INFO"
} catch {
    Write-Log "Cleanup error: $_" "WARN"
}

# ── 完成 ──────────────────────────────────────────────────────────────────

$sw.Stop()
Write-Log "" "INFO"
Write-Log "============================================" "INFO"
Write-Log "  Finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" "INFO"
Write-Log "  Exit code: $exitCode" "INFO"
Write-Log "  Duration: $([math]::Round($sw.Elapsed.TotalMinutes, 1)) min" "INFO"
Write-Log "  Log: $LogFile" "INFO"
Write-Log "============================================" "INFO"

# 结果通知
if ($exitCode -eq 0) {
    Send-Toast "Adam's Theory ✅" "每日分析完成 ($([math]::Round($sw.Elapsed.TotalMinutes, 1)) min)"
} else {
    Send-Toast "Adam's Theory ⚠️" "分析异常 (exit $exitCode)，详见日志"
}

exit $exitCode
