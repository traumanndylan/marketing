#!/usr/bin/env bash

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOUR=$(date +%H)
if [ "$HOUR" -lt 9 ] || [ "$HOUR" -ge 18 ]; then
    exit 0
fi

CRON_DIR="$DIR/cron"
mkdir -p "$CRON_DIR"

LAST_RUN_FILE="$CRON_DIR/.last_run"
TODAY=$(date +%Y-%m-%d)

if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN=$(cat "$LAST_RUN_FILE")
    if [ "$LAST_RUN" == "$TODAY" ]; then
        exit 0
    fi
fi

echo "$TODAY" > "$LAST_RUN_FILE"

cd "$DIR" && ./main.sh >> "$CRON_DIR/cron.log" 2>&1
