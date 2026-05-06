#!/bin/bash

# HK stocks to test
STOCKS="700 6869 9992 9988 883 981 3317 3690 568 9926"

# Dates: March 15-30
START_DATE=15
END_DATE=30

# Times: 11:00 and 15:00 HKT
TIMES="11:00 15:00"

cd /Users/jaydensmac/stock-analysis/backtest

for stock in $STOCKS; do
    for day in $(seq $START_DATE $END_DATE); do
        for time in $TIMES; do
            # Format: 2026-03-DD HH:MM
            DT=$(printf "2026-03-%02d %s" $day $time)
            echo "Running backtest: $stock at $DT HKT"
            python3 stock_analysis_backtest.py "$stock" "$DT" -o .
            # Rate limit: 3 seconds between each
            sleep 3
        done
    done
done

echo "All backtests completed!"
