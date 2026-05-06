#!/bin/bash
# Run stock analysis for US stocks
# Usage: ./run_us_hourly.sh [once|loop]
#   once  - run once and exit (default if no args)
#   loop  - run in infinite loop every 60 minutes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
PYTHON_SCRIPT="$SCRIPT_DIR/stock_analysis.py"

MODE="${1:-once}"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

run_analysis() {
    LOG_FILE="$LOG_DIR/us_analysis_$(date +%Y%m%d).log"
    echo "=========================================" | tee -a "$LOG_FILE"
    echo "Running US analysis at $(date)" | tee -a "$LOG_FILE"
    echo "=========================================" | tee -a "$LOG_FILE"

    cd "$SCRIPT_DIR"
    python3 "$PYTHON_SCRIPT" us 2>&1 | tee -a "$LOG_FILE"

    echo "Completed at $(date)" | tee -a "$LOG_FILE"
    echo "" | tee -a "$LOG_FILE"
}

if [ "$MODE" = "loop" ]; then
    echo "Starting US stock analysis hourly loop..."
    while true; do
        run_analysis
        echo "Waiting 1 hour until next run..."
        sleep 3600
    done
else
    # Run once and exit (default)
    run_analysis
    echo ""
    echo "Single run completed. Exiting."
fi
