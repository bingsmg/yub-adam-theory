#!/bin/bash
#
# Daily Adam's Theory Stock Recommendation Pipeline
# Runs via WSL cron — weekdays 23:00 CST
#
# Tries to update latest data first (parallel, ~15 min for 5000+ stocks).
# Falls back to analysis-only if update fails or times out.
# Always pushes results to Feishu.

set -e

PROJECT_DIR="/mnt/e/Projects/ClaudeCodeProjects/yd-project"
PYTHON="$PROJECT_DIR/.venv/Scripts/python.exe"
LOG_DIR="$PROJECT_DIR/output"
TIMESTAMP=$(date +"%Y-%m-%d_%H%M")

exec >> "$LOG_DIR/cron_$TIMESTAMP.log" 2>&1

echo "=========================================="
echo "Adam's Theory Daily Pipeline"
echo "Started at: $(date '+%Y-%m-%d %H:%M:%S CST')"
echo "=========================================="

cd "$PROJECT_DIR"

# Step 1: Update latest data (incremental, parallel for speed)
# Use FETCH_MAX_WORKERS=4: daily update only fetches 1-2 new days per stock,
# so parallel mode is safe and much faster (~15 min vs 4 hours).
echo ""
echo "[Step 1/3] Updating latest trading data..."
START_TIME=$(date +%s)
FETCH_MAX_WORKERS=4 "$PYTHON" scripts/daily_update.py --output both 2>&1 || {
    echo "[WARN] Full update failed or timed out, falling back to analysis-only..."
    "$PYTHON" scripts/daily_update.py --no-update --output both 2>&1
}
ELAPSED=$(($(date +%s) - START_TIME))
echo "[Step 1/3] Done in ${ELAPSED}s"

# Step 2: Notify Feishu (even if update failed, analysis results exist)
echo ""
echo "[Step 2/3] Sending to Feishu..."
"$PYTHON" scripts/notify_feishu.py 2>&1

echo ""
echo "=========================================="
echo "Finished at: $(date '+%Y-%m-%d %H:%M:%S CST')"
echo "=========================================="
