#!/bin/sh
echo "[entrypoint] Cleaning stale Chromium lock files..."
find /app/data/sessions -name "SingletonLock" -o -name "SingletonSocket" -o -name "SingletonCookie" 2>/dev/null | xargs rm -f
echo "[entrypoint] Starting OpenWA..."
exec "$@"
