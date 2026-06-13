#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up generated data"

rm -f "$SCRIPT_DIR/backend/db/leads.db"
rm -f "$SCRIPT_DIR/backend/db/results.csv"
rm -rf "$SCRIPT_DIR/scraper/gmaps-output"/*

echo "Cleanup complete"
