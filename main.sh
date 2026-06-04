#!/usr/bin/env bash
set -e
PROJECTS=~/marketing
API_URL="http://localhost:2785/api"
API_KEY="dev-admin-key"
SESSION_ID="3b09b399-6e93-4672-8da3-e845b1e7fbe2"

echo "Starting OpenWA"
cd "$PROJECTS/OpenWA"
npm run dev &
OPENWA_PID=$!

echo "Waiting for OpenWA"
MAX_WAIT=60
ELAPSED=0
until curl -sf -H "X-API-Key: $API_KEY" "$API_URL/sessions/$SESSION_ID" > /dev/null 2>&1; do
    if [ $ELAPSED -ge $MAX_WAIT ]; then
        echo "ERROR: OpenWA did not become ready within ${MAX_WAIT}s. Aborting."
        kill $OPENWA_PID 2>/dev/null
        exit 1
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
    echo "Waiting for OpenWA(${ELAPSED}s)"
done

echo ""
echo "Session Verified"
python3 "$PROJECTS/main/main.py"

echo ""
echo "Stopping OpenWA"
kill $OPENWA_PID 2>/dev/null
wait $OPENWA_PID 2>/dev/null || true

echo ""
