#!/bin/bash
# Run stock analysis for US stocks
# Usage: ./run_us_until_8am.sh [once|loop]
#   once  - run once and exit (default if no args)
#   loop  - run every hour until 8am HK next day

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PYTHON_SCRIPT="$SCRIPT_DIR/stock_analysis.py"

MODE="${1:-once}"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

run_analysis() {
    run_count=$1
    timestamp=$(date +%Y%m%d_%H%M%S)
    LOG_FILE="$LOG_DIR/us_analysis_${timestamp}.log"

    echo "========================================" | tee -a "$LOG_FILE"
    echo "Run #$run_count - $(date)" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"

    cd "$SCRIPT_DIR"
    python3 "$PYTHON_SCRIPT" us 2>&1 | tee -a "$LOG_FILE"

    echo "Completed at $(date)" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
}

if [ "$MODE" = "loop" ]; then
    TARGET_HOUR=8

    echo "Starting US stock analysis loop..."
    echo "Will run every hour until $(date -v+1d -v${TARGET_HOUR}H '+%Y-%m-%d %H:%M') HK"

    run_count=0
    while true; do
        current_hour=$(date +%H)
        current_min=$(date +%M)

        if [ "$current_hour" -eq "$TARGET_HOUR" ] && [ "$current_min" -lt 10 ]; then
            echo "Reached target time 8:00 AM HK, stopping."
            break
        fi

        run_count=$((run_count + 1))
        run_analysis $run_count

        if [ "$current_hour" -eq "$TARGET_HOUR" ]; then
            echo "Reached target hour, stopping."
            break
        fi

        echo "Waiting 1 hour until next run..."
        sleep 3600
    done

    echo "Done! Total runs: $run_count"
else
    # Run once and exit (default)
    echo "Running single US analysis..."
    run_analysis 1
    echo ""
    echo "Single run completed. Exiting."
fi
