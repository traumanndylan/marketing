#!/usr/bin/env bash
set -e
PROJECTS=~/marketing
SCRAPER_DIR="$PROJECTS/scraper"
OUTPUT_DIR="$SCRAPER_DIR/gmaps-output"
RESULTS_FILE="$OUTPUT_DIR/results.csv"
QUERIES_CSV="$SCRAPER_DIR/queries.csv"
CONTAINER_NAME="gmaps-scraper"

TEMP_QUERIES="$SCRAPER_DIR/temp_queries.txt"
TEMP_RESULTS="$OUTPUT_DIR/temp_city_results.csv"

SECONDS=0

echo "Generating Queries..."
python3 "$PROJECTS/queries/queries.py"

if [ ! -f "$QUERIES_CSV" ]; then
  echo "The file $QUERIES_CSV was not generated. Aborting."
  exit 1
fi

TOTAL_CITIES=$(python3 -c "import csv,sys; f=open(sys.argv[1],'r',encoding='utf-8'); r=csv.reader(f); next(r,None); print(len(set(row[0] for row in r if row)))" "$QUERIES_CSV" 2>/dev/null || echo 1)
PROCESSED_CITIES=0

draw_progress_bar() {
  local current=$1
  local total=$2
  local city_name=$3
  local length=40
  
  if [ "$total" -eq 0 ]; then total=1; fi
  
  local percent=$((current * 100 / total))
  local filled=$((current * length / total))
  local empty=$((length - filled))
  
  local bar=""
  [ "$filled" -gt 0 ] && bar=$(printf "%${filled}s" | tr ' ' '█')
  local spaces=""
  [ "$empty" -gt 0 ] && spaces=$(printf "%${empty}s" | tr ' ' '░')
  
  local GREEN="\033[32m"
  local CYAN="\033[36m"
  local RESET="\033[0m"
  
  printf "\r\033[K${CYAN}==> Scraping:${RESET} [${GREEN}%s${RESET}%s] %d%% (%d/%d) | Current: %s" "$bar" "$spaces" "$percent" "$current" "$total" "$city_name"
}

echo ""
echo "Running Scraper"
cd "$SCRAPER_DIR"
mkdir -p "$OUTPUT_DIR"

if [ -s "$RESULTS_FILE" ]; then
  BACKUP_FILE="$OUTPUT_DIR/results_backup_$(date +%Y%m%d_%H%M%S).csv"
  cp "$RESULTS_FILE" "$BACKUP_FILE"
  echo "Backed up $(wc -l < "$RESULTS_FILE") lines to $(basename "$BACKUP_FILE")"
  rm -f "$RESULTS_FILE" 
fi

podman rm -f "$CONTAINER_NAME" 2>/dev/null || true

INTERRUPTED=0
cleanup() {
  echo ""
  echo "Caught interrupt — stopping scraper gracefully..."
  podman stop -t 15 "$CONTAINER_NAME" 2>/dev/null || true
  INTERRUPTED=1
}
trap cleanup INT TERM

OVERALL_EXIT=0

process_city() {
  if [ $INTERRUPTED -eq 1 ]; then return; fi
  
  draw_progress_bar "$PROCESSED_CITIES" "$TOTAL_CITIES" "$CURRENT_CITY"

  rm -f "$TEMP_RESULTS"
  set +e
  
  podman run \
    --name "$CONTAINER_NAME" \
    -v gmaps-playwright-cache:/opt \
    -v "$TEMP_QUERIES:/queries.txt:ro" \
    -v "$OUTPUT_DIR:/out" \
    docker.io/gosom/google-maps-scraper \
    -input /queries.txt \
    -results /out/temp_city_results.csv \
    -depth 1 \
    -fast-mode \
    -geo "$CURRENT_LAT,$CURRENT_LON" \
    -radius "$CURRENT_RADIUS" \
    -c 8 \
    -exit-on-inactivity 3m >/dev/null 2>&1 &
    
  CONTAINER_PID=$!
  wait $CONTAINER_PID 2>/dev/null
  CURRENT_EXIT=$?
  set -e

  if [ $CURRENT_EXIT -ne 0 ] && [ $INTERRUPTED -eq 0 ]; then
     echo "" 
     echo "The container exited with code $CURRENT_EXIT in $CURRENT_CITY"
     OVERALL_EXIT=$CURRENT_EXIT
  fi

  if [ -f "$TEMP_RESULTS" ]; then
     if [ ! -f "$RESULTS_FILE" ]; then
        head -n 1 "$TEMP_RESULTS" > "$RESULTS_FILE"
     fi
     tail -n +2 "$TEMP_RESULTS" >> "$RESULTS_FILE"
  fi

  podman rm -f "$CONTAINER_NAME" 2>/dev/null || true
  
  PROCESSED_CITIES=$((PROCESSED_CITIES + 1))
  draw_progress_bar "$PROCESSED_CITIES" "$TOTAL_CITIES" "$CURRENT_CITY"
}

CURRENT_CITY=""

echo ""
draw_progress_bar 0 "$TOTAL_CITIES" "Initializing..."

while IFS='|' read -r CITY LAT LON RADIUS QUERY; do
  if [ $INTERRUPTED -eq 1 ]; then break; fi
  
  CITY=$(echo "$CITY" | tr -d '\r')
  QUERY=$(echo "$QUERY" | tr -d '\r')

  if [ "$CITY" != "$CURRENT_CITY" ]; then
      if [ -n "$CURRENT_CITY" ]; then
          process_city
      fi
      
      CURRENT_CITY="$CITY"
      CURRENT_LAT="$LAT"
      CURRENT_LON="$LON"
      CURRENT_RADIUS="$RADIUS"
      > "$TEMP_QUERIES" 
  fi
  
  echo "$QUERY" - "$TEMP_QUERIES"

done < <(python3 -c 'import csv,sys; [print("|".join(row)) for row in csv.reader(open(sys.argv[1]))]' "$QUERIES_CSV" | tail -n +2)

if [ -n "$CURRENT_CITY" ] && [ $INTERRUPTED -eq 0 ]; then
   process_city
fi

echo "" 

trap - INT TERM

rm -f "$TEMP_QUERIES"
rm -f "$TEMP_RESULTS"

if [ -f "$RESULTS_FILE" ]; then
  TOTAL=$(wc -l < "$RESULTS_FILE" | tr -d ' ')
  echo ""
  echo "Master File: $RESULTS_FILE - $TOTAL lines."
fi

if [ "$OVERALL_EXIT" -eq 0 ] && [ $INTERRUPTED -eq 0 ]; then
  echo ""
  echo "Post Processing"
  python3 "$PROJECTS/postProcessing/main.py"
else
  echo ""
  echo "Scraper finished with interruptions or errors. Skipping Post-Processing."
fi

DURATION=$SECONDS
MINUTES=$((DURATION / 60))
REMAINDER_SECONDS=$((DURATION % 60))

echo ""
if [ $MINUTES -gt 0 ]; then
  echo "Total Execution Time: $MINUTES minute(s) and $REMAINDER_SECONDS second(s)."
else
  echo "Total Execution Time: $DURATION second(s)."
fi
echo ""