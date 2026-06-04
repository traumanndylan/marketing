#!/usr/bin/env bash
set -e
PROJECTS=~/marketing

echo "Generating Queries"
python3 "$PROJECTS/queries/queries.py"

echo ""
echo "Running Scraper"
cd "$PROJECTS/scraper"
podman run --rm \
  -v gmaps-playwright-cache:/opt \
  -v "$(pwd)/queries.txt:/queries.txt:ro" \
  -v "$(pwd)/gmaps-output:/out" \
  docker.io/gosom/google-maps-scraper \
  -input /queries.txt \
  -results /out/results.csv \
  -depth 1 \
  -exit-on-inactivity 3m

echo ""
echo "Post Processing"
python3 "$PROJECTS/postProcessing/main.py"

echo ""
