"""Small dependency-free web dashboard for LAD runtime events."""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "daemon" / "logs"
EVENTS_FILE = LOG_DIR / "dashboard_events.jsonl"
WEB_DIR = ROOT / "frontend"


def service_status():
    """Report local Fluentd and Qdrant TCP reachability and configured inputs."""
    def reachable(host, port):
        try:
            with socket.create_connection((host, port), timeout=0.6):
                return True
        except OSError:
            return False

    return {
        "fluentd": reachable(os.getenv("FLUENTD_HOST", "127.0.0.1"), int(os.getenv("FLUENTD_PORT", "24224"))),
        "qdrant": reachable(os.getenv("QDRANT_HOST", "127.0.0.1").replace("http://", "").replace("https://", "").split(":")[0], int(os.getenv("QDRANT_PORT", "6333"))),
    }


def read_events():
    """Collapse append-only event updates to the latest state for each log line."""
    events = {}
    try:
        with EVENTS_FILE.open(encoding="utf-8") as source:
            for line in source:
                try:
                    event = json.loads(line)
                    events[event["id"]] = event
                except (json.JSONDecodeError, KeyError):
                    continue
    except FileNotFoundError:
        pass
    return sorted(events.values(), key=lambda item: item.get("timestamp", ""), reverse=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/overview":
            events = read_events()
            payload = {
                "events": events[:250],
                "total": len(events),
                "analyzed": sum(
                    1 for event in events
                    if event.get("status") in ("analyzed", "filtered", "needs_review")
                ),
                "anomalies": sum(
                    1 for event in events
                    if event.get("status") == "analyzed" and event.get("anomaly_detected")
                ),
                "processing": sum(
                    1 for event in events
                    if event.get("status") in ("collecting", "queued", "processing")
                ),
                "services": service_status(),
            }
            body = json.dumps(payload).encode()
            content_type = "application/json; charset=utf-8"
        else:
            relative = "dashboard.html" if path in ("/", "") else path.lstrip("/")
            target = (WEB_DIR / relative).resolve()
            if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
                self.send_error(404)
                return
            try:
                body = target.read_bytes()
            except (FileNotFoundError, IsADirectoryError):
                self.send_error(404)
                return
            content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "text/plain; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"LAD dashboard: http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
