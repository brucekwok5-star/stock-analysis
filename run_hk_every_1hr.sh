#!/bin/bash
# Run stock analysis - HK market
# Usage: ./run_hk_every_1hr.sh [once|loop]
#   once  - run once and exit (default if no args)
#   loop  - run in infinite loop every 60 minutes

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

MODE="${1:-once}"

echo "========================================="
echo "  Stock Analysis - HK"
echo "  Mode: $MODE"
echo "  Started: $(date)"
echo "========================================="

run_analysis() {
    echo "Running HK analysis at $(date)..."
    python3 stock_analysis.py hk
    echo "Completed at $(date)"
}

if [ "$MODE" = "loop" ]; then
    # Run immediately then loop every 60 minutes
    run_analysis
    while true; do
        echo ""
        echo "========================================="
        echo "  Next run at: $(date)"
        echo "========================================="
        echo ""
        sleep 3600
        run_analysis
    done
else
    # Run once and exit (default)
    run_analysis
    echo ""
    echo "Single run completed. Exiting."
fi
