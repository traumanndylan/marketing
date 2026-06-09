#!/usr/bin/env bash
set -e
PROJECTS=~/marketing
SCRAPER_DIR="$PROJECTS/scraper"
OUTPUT_DIR="$SCRAPER_DIR/gmaps-output"
RESULTS_FILE="$OUTPUT_DIR/results.csv"
CONTAINER_NAME="gmaps-scraper-run"

echo "Generating Queries"
python3 "$PROJECTS/queries/queries.py"

echo ""
echo "Running Scraper"
cd "$SCRAPER_DIR"

BACKUP_FILE=""
if [ -s "$RESULTS_FILE" ]; then
  BACKUP_FILE="$OUTPUT_DIR/results_backup_$(date +%Y%m%d_%H%M%S).csv"
  cp "$RESULTS_FILE" "$BACKUP_FILE"
  echo "Backed up $(wc -l < "$RESULTS_FILE") lines to $(basename "$BACKUP_FILE")"
fi

podman rm -f "$CONTAINER_NAME" 2>/dev/null || true

cleanup() {
  echo ""
  echo "Caught interrupt — stopping scraper gracefully (30s timeout)..."
  podman stop -t 30 "$CONTAINER_NAME" 2>/dev/null || true
}
trap cleanup INT TERM

podman run \
  --name "$CONTAINER_NAME" \
  -v gmaps-playwright-cache:/opt \
  -v "$(pwd)/queries.txt:/queries.txt:ro" \
  -v "$(pwd)/gmaps-output:/out" \
  docker.io/gosom/google-maps-scraper \
  -input /queries.txt \
  -results /out/results.csv \
  -depth 1 \
  -exit-on-inactivity 3m &

CONTAINER_PID=$!

wait $CONTAINER_PID 2>/dev/null
EXIT_CODE=$?

trap - INT TERM

if [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ] && [ -f "$RESULTS_FILE" ]; then
  NEW_LINES=$(wc -l < "$RESULTS_FILE" 2>/dev/null || echo 0)
  BACKUP_LINES=$(wc -l < "$BACKUP_FILE" 2>/dev/null || echo 0)

  if [ "$NEW_LINES" -gt 1 ]; then
    MERGED="$OUTPUT_DIR/results_merged_$$.csv"
    head -1 "$BACKUP_FILE" > "$MERGED"
    tail -n +2 "$BACKUP_FILE" >> "$MERGED"
    tail -n +2 "$RESULTS_FILE" >> "$MERGED"
    mv "$MERGED" "$RESULTS_FILE"
    echo "Merged results: $BACKUP_LINES backup + $NEW_LINES new → $(wc -l < "$RESULTS_FILE") total lines"
  elif [ "$NEW_LINES" -le 1 ]; then
    cp "$BACKUP_FILE" "$RESULTS_FILE"
    echo "New run produced no results — restored backup ($BACKUP_LINES lines)"
  fi
fi

podman rm -f "$CONTAINER_NAME" 2>/dev/null || true

if [ -f "$RESULTS_FILE" ]; then
  TOTAL=$(wc -l < "$RESULTS_FILE")
  echo ""
  echo "Results file: $RESULTS_FILE ($TOTAL lines)"
fi

if [ "$EXIT_CODE" -eq 0 ]; then
  echo ""
  echo "Post Processing"
  python3 "$PROJECTS/postProcessing/main.py"
else
  echo ""
  echo "Scraper exited with code $EXIT_CODE — skipping post-processing."
  echo "Your results are safely saved. Re-run to continue."
fi

echo ""
