#!/usr/bin/env bash
set -euo pipefail

# === Usage check ===
if [ $# -ne 1 ]; then
  echo "Usage: $0 <seconds>"
  exit 1
fi

DURATION=$1
ROOT_DIR="$(pwd)"
DAEMON_DIR="$ROOT_DIR/daemon"
LOG_PATH="$DAEMON_DIR/logs/data.log"
ETC_DIR="$DAEMON_DIR/etc"

# === 0. Prep fix for docker mount ===
mkdir -p "$ETC_DIR"
cp "$DAEMON_DIR/fluent.conf" "$ETC_DIR/fluent.conf"

# === 1. Stop & remove any old fluentd container ===
if docker ps -a --filter "name=fluentd" --format '{{.Names}}' | grep -q '^fluentd$'; then
  echo "[INFO] Removing existing Fluentd container..."
  docker stop fluentd >/dev/null 2>&1 || true
  docker rm fluentd >/dev/null 2>&1 || true
fi

# === 2. Run docker_run script (patched with UID:GID and correct paths) ===
echo "[INFO] Starting Fluentd container..."
TMP_RUN=$(mktemp)

# Replace paths inside docker_run with absolute daemon paths
sed \
  -e "s|\$(pwd)/logs|$DAEMON_DIR/logs|" \
  -e "s|\$(pwd)/fluent.conf|$DAEMON_DIR/fluent.conf|" \
  -e "s|--user root|--user $(id -u):$(id -g)|" \
  "$DAEMON_DIR/docker_run" > "$TMP_RUN"

bash "$TMP_RUN"
rm -f "$TMP_RUN"

# Give Fluentd a little time to start
sleep 3

# === 3. Ensure Python deps ===
echo "[INFO] Ensuring Python dependencies..."
pip install -q langchain-google-genai || true

# === 4. Run daemon.py ===
echo "[INFO] Starting daemon.py..."
python3 "$DAEMON_DIR/daemon.py" "$DAEMON_DIR/config.yaml" &
DAEMON_PID=$!

# === 5. Run main.py ===
echo "[INFO] Starting main.py..."
python3 "$ROOT_DIR/scripts/main.py" "$DAEMON_DIR/config.yaml" &
MAIN_PID=$!

# === 6. Let everything run for N seconds ===
echo "[INFO] Running for $DURATION seconds..."
sleep "$DURATION"

# === 7. Cleanup: stop processes ===
echo "[INFO] Stopping processes..."
kill $DAEMON_PID $MAIN_PID 2>/dev/null || true

# === 8. Stop & remove Fluentd container ===
echo "[INFO] Stopping Fluentd container..."
docker stop fluentd >/dev/null 2>&1 || true
docker rm fluentd >/dev/null 2>&1 || true

# === 9. Clear logs inside data.log (file or dir) ===
if [ -f "$LOG_PATH" ]; then
  > "$LOG_PATH"
  echo "[INFO] Cleared file: $LOG_PATH"
elif [ -d "$LOG_PATH" ]; then
  rm -rf "$LOG_PATH"/* || sudo rm -rf "$LOG_PATH"/* || true
  echo "[INFO] Cleared directory contents: $LOG_PATH"
else
  echo "[WARN] $LOG_PATH not found"
fi

echo "[INFO] Done."

