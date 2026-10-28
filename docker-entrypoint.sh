#!/bin/sh
set -eu

python /app/daemon/daemon.py /app/daemon/config.docker.yaml &
daemon_pid=$!
python /app/scripts/main.py /app/daemon/config.docker.yaml &
main_pid=$!
python /app/scripts/dashboard.py &
dashboard_pid=$!

shutdown() {
  trap - INT TERM EXIT
  kill -TERM "$daemon_pid" "$main_pid" "$dashboard_pid" 2>/dev/null || true
  wait "$daemon_pid" "$main_pid" "$dashboard_pid" 2>/dev/null || true
}
trap shutdown INT TERM EXIT

while kill -0 "$daemon_pid" 2>/dev/null && \
      kill -0 "$main_pid" 2>/dev/null && \
      kill -0 "$dashboard_pid" 2>/dev/null; do
  sleep 2
done

echo "A LAD service stopped; shutting down the container." >&2
exit 1
