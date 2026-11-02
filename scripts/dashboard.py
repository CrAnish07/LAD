"""Small dependency-free web dashboard for LAD runtime events."""
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "daemon" / "logs"
EVENTS_FILE = LOG_DIR / "dashboard_events.jsonl"
WEB_DIR = ROOT / "frontend"
SETTINGS_FILE = ROOT / "config" / "model_settings.json"
PROVIDER_KEYS = {
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "groq": ("GROQ_API_KEY",),
    "nanogpt": ("NANOGPT_API_KEY",),
    "requesty": ("REQUESTY_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "cloudflare": ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_AUTH_TOKEN"),
}
load_dotenv(ROOT / ".env")


def env_key_set(key):
    value = os.getenv(key, "").strip()
    return bool(value) and not value.lower().startswith("replace_with_")


def model_settings():
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        workers = saved.get("workers") or []
        setup_complete = bool(saved.get("setup_complete"))
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        workers = [item.strip() for item in os.getenv(
            "ANALYSIS_WORKERS", "gemini:gemini-3.8-flash,groq:qwen/qwen3.8-27b"
        ).split(",") if item.strip()]
        setup_complete = False
    log_paths = []
    if SETTINGS_FILE.exists():
        try:
            saved_config = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            log_paths = saved_config.get("log_paths") or []
        except (json.JSONDecodeError, AttributeError):
            pass
    if not log_paths:
        config_file = ROOT / "daemon" / ("config.docker.yaml" if os.getenv("FLUENTD_HOST") == "fluentd" else "config.yaml")
        try:
            config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            configured = config.get("logs_by_os", {})
            import platform
            log_paths = configured.get(platform.system()) or config.get("logs") or []
        except (FileNotFoundError, yaml.YAMLError):
            pass
    providers = []
    for provider, keys in PROVIDER_KEYS.items():
        configured = (
            any(env_key_set(key) for key in keys)
            if provider == "gemini"
            else all(env_key_set(key) for key in keys)
        )
        providers.append({"id": provider, "ready": configured, "missing": [] if configured else list(keys)})
    return {"workers": workers, "providers": providers, "log_paths": log_paths, "saved": SETTINGS_FILE.exists(), "setup_complete": setup_complete}


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
        if path in ("/dashboard", "/dashboard.html") and not model_settings()["setup_complete"]:
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
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
        elif path == "/api/models":
            body = json.dumps(model_settings()).encode()
            content_type = "application/json; charset=utf-8"
        else:
            relative = "setup.html" if path in ("/", "") else "dashboard.html" if path == "/dashboard" else path.lstrip("/")
            target = (WEB_DIR / relative).resolve()
            if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
                self.send_error(404)
                return
            if target == (WEB_DIR / "dashboard.html").resolve() and not model_settings()["setup_complete"]:
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
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

    def do_POST(self):
        if urlparse(self.path).path != "/api/models":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 8192:
                raise ValueError("Invalid request size.")
            payload = json.loads(self.rfile.read(length))
            workers = payload.get("workers")
            if not isinstance(workers, list) or not 1 <= len(workers) <= 5:
                raise ValueError("Choose between one and five model workers.")
            normalized = []
            for worker in workers:
                if not isinstance(worker, str) or ":" not in worker:
                    raise ValueError("Each model must include a provider and model ID.")
                provider, model = worker.split(":", 1)
                if provider not in PROVIDER_KEYS or not re.fullmatch(r"[A-Za-z0-9._/@:+-]{1,160}", model):
                    raise ValueError("That provider or model ID is not supported.")
                if worker not in normalized:
                    normalized.append(worker)
            log_paths = payload.get("log_paths")
            if not isinstance(log_paths, list) or not 1 <= len(log_paths) <= 5:
                raise ValueError("Add at least one log file path.")
            log_paths = list(dict.fromkeys(path.strip() for path in log_paths if isinstance(path, str) and path.strip()))
            if not log_paths or any(not Path(path).is_absolute() or not Path(path).is_file() for path in log_paths):
                raise ValueError("Each log source must be an existing absolute file path visible to LAD.")
            missing = sorted({
                key for worker in normalized
                for key in PROVIDER_KEYS[worker.split(":", 1)[0]]
                if not env_key_set(key)
            })
            if not any(env_key_set(key) for key in PROVIDER_KEYS["gemini"]):
                missing.append("GOOGLE_API_KEY (required for log embeddings)")
            if missing:
                raise ValueError("Add the required key(s) to .env first: " + ", ".join(missing))
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = SETTINGS_FILE.with_suffix(".tmp")
            temporary.write_text(json.dumps({"workers": normalized, "log_paths": log_paths, "setup_complete": True}, indent=2) + "\n", encoding="utf-8")
            temporary.replace(SETTINGS_FILE)
            body = json.dumps({"ok": True, "workers": normalized, "restart_required": True}).encode()
            self.send_response(200)
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode()
            self.send_response(400)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
