@echo off
REM =============================================================================
REM Adam's Theory Daily Pipeline — Windows Task Scheduler Entry Point
REM =============================================================================
REM 用法：
REM   1. 打开"任务计划程序" (taskschd.msc)
REM   2. 创建基本任务 → 触发器：每天 23:00（或你偏好的时间）
REM   3. 操作 → 启动程序：
REM      程序/脚本：E:\Projects\ClaudeCodeProjects\yd-project\scripts\run_daily.bat
REM      起始于：  E:\Projects\ClaudeCodeProjects\yd-project
REM   4. 条件 → 取消勾选"只有在计算机使用交流电源时才启动"
REM
REM 注意：A 股收盘 15:00，数据通常 16:00-17:00 到位，建议 18:00 之后运行。
REM =============================================================================

setlocal enabledelayedexpansion

set "PROJECT_DIR=E:\Projects\ClaudeCodeProjects\yd-project"
set "VENV_PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_DIR%\output\logs"

REM 创建日志目录
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 生成日志文件名：run_daily_2026-06-22_213000.log
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set "DT=%%I"
set "LOG_TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2%_%DT:~8,2%%DT:~10,2%%DT:~12,2%"
set "LOG_FILE=%LOG_DIR%\run_daily_%LOG_TS%.log"

REM 所有输出重定向到日志文件
call :log "============================================"
call :log "  Adam's Theory Daily Pipeline"
call :log "  Started: %DATE% %TIME%"
call :log "============================================"

REM 检查虚拟环境
if not exist "%VENV_PYTHON%" (
    call :log "[ERROR] Python venv not found: %VENV_PYTHON%"
    call :log "  Run: cd %PROJECT_DIR% && python -m venv .venv && .venv\Scripts\pip install -e .[dev]"
    exit /b 1
)

REM 检查 .env 文件
if not exist "%PROJECT_DIR%\.env" (
    call :log "[WARN] .env file not found, using default settings"
    call :log "  Copy .env.example to .env and customize if needed"
)

REM 切换到项目目录
cd /d "%PROJECT_DIR%"

REM ── Step 1: 数据更新 + 分析 ────────────────────────────────────────────
call :log ""
call :log "[Step 1/3] Running daily update + analysis..."
set "START_TIME=%TIME%"

"%VENV_PYTHON%" scripts/daily_update.py --limit 500 --output both --log-level INFO >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

if %EXIT_CODE% neq 0 (
    call :log "[WARN] daily_update.py exited with code %EXIT_CODE%"
    call :log "[FALLBACK] Retrying with --no-update (skip fetch, analyze cached data)..."
    "%VENV_PYTHON%" scripts/daily_update.py --no-update --limit 500 --output both --log-level INFO >> "%LOG_FILE%" 2>&1
    set "EXIT_CODE=%ERRORLEVEL%"
)

call :log "[Step 1/3] Done. Started at %START_TIME%, finished at %TIME%"

REM ── Step 2: 飞书通知 ───────────────────────────────────────────────────
call :log ""
call :log "[Step 2/3] Sending Feishu notification..."

"%VENV_PYTHON%" scripts/notify_feishu.py >> "%LOG_FILE%" 2>&1
set "NOTIFY_CODE=%ERRORLEVEL%"

if %NOTIFY_CODE% neq 0 (
    call :log "[WARN] Feishu notification failed (exit code %NOTIFY_CODE%). Check FEISHU_WEBHOOK_URL in .env"
) else (
    call :log "[OK] Feishu notification sent"
)

REM ── Step 3: 清理旧日志（保留最近 30 天）────────────────────────────────
call :log ""
call :log "[Step 3/3] Cleaning up old logs (keeping last 30 days)..."
forfiles /p "%LOG_DIR%" /m "run_daily_*.log" /d -30 /c "cmd /c del @file" 2>nul
call :log "[OK] Cleanup done"

REM ── 完成 ────────────────────────────────────────────────────────────────
call :log ""
call :log "============================================"
call :log "  Finished: %DATE% %TIME%"
call :log "  Exit code: %EXIT_CODE%"
call :log "  Log: %LOG_FILE%"
call :log "============================================"

exit /b %EXIT_CODE%

REM ── 辅助函数 ────────────────────────────────────────────────────────────
:log
echo [%DATE% %TIME%] %~1
echo [%DATE% %TIME%] %~1 >> "%LOG_FILE%"
goto :eof
