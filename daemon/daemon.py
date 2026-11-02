# TODO: hadle the keyboard interrupt
# TODO: dedicated comments before every functions
#!/usr/bin/env python3
import yaml
import os
import platform
import sys
import time
import json
from pathlib import Path

from fluent import sender

def load_config(config_path):
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}

    settings_path = Path(__file__).resolve().parent.parent / "config" / "model_settings.json"
    try:
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        if saved.get("setup_complete") and saved.get("log_paths"):
            return saved["log_paths"]
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        pass

    # Prefer paths configured for this OS; keep the old `logs` key as a
    # fallback so existing config files continue to work.
    logs_by_os = data.get("logs_by_os", {})
    operating_system = platform.system()
    if operating_system in logs_by_os:
        print(f"Detected operating system: {operating_system}")
        return logs_by_os[operating_system] or []
    if "logs" in data:
        print(
            f"No log paths configured for {operating_system}; "
            "using the generic 'logs' list."
        )
        return data["logs"] or []
    print(
        f"No log paths configured for operating system {operating_system}. "
        "Add it under 'logs_by_os' in the config file.",
        file=sys.stderr,
    )
    return []

def tail_files(file_paths):
    """Open files at their current end and track their inode for rotation checks."""
    handles = {}
    for path in file_paths:
        try:
            fd = open(path, "r", encoding="utf-8", errors="replace")
            fd.seek(0, os.SEEK_END)  # start at end (like tail -f)
            handles[path] = {
                "fd": fd,
                "inode": os.fstat(fd.fileno()).st_ino,
            }
        except Exception as e:
            print(f"Error opening {path}: {e}", file=sys.stderr)
    return handles

def follow_logs(config_path):
    log_files = load_config(config_path)
    if not log_files:
        print("No log files found in config.")
        return

    # setup fluentd logger (read from config.yaml)
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    fluentd_config = data.get("fluentd", {})
    fluent_sender = sender.FluentSender(
        "myapp",
        host=fluentd_config.get("host", "127.0.0.1"),
        port=int(fluentd_config.get("port", 24224)),
    )

    # Open and watch files
    handles = tail_files(log_files)
    if not handles:
        print("No configured log files could be opened.", file=sys.stderr)
        fluent_sender.close()
        return

    print("Watching logs... (Ctrl+C to exit)", flush=True)
    try:
        while True:
            for path, state in handles.items():
                fd = state["fd"]
                try:
                    path_stat = os.stat(path)
                except FileNotFoundError:
                    continue

                if path_stat.st_ino != state["inode"]:
                    fd.close()
                    fd = open(path, "r", encoding="utf-8", errors="replace")
                    state["fd"] = fd
                    state["inode"] = path_stat.st_ino
                    print(f"Detected log rotation: {path}", flush=True)
                elif path_stat.st_size < fd.tell():
                    fd.seek(0)
                    print(f"Detected log truncation: {path}", flush=True)

                line = fd.readline()
                while line:
                    log_line = line.strip()
                    if log_line:
                        sent = fluent_sender.emit(
                            "log", {"file": path, "message": log_line}
                        )
                        if sent:
                            print(f"Sent to Fluentd: [{path}] {log_line}", flush=True)
                        else:
                            print(
                                f"Failed to send log to Fluentd: {fluent_sender.last_error}",
                                file=sys.stderr,
                                flush=True,
                            )
                            fluent_sender.clear_last_error()
                    line = fd.readline()
            time.sleep(0.25)
    finally:
        fluent_sender.close()
        for state in handles.values():
            state["fd"].close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <config.yaml>")
        sys.exit(1)

    follow_logs(sys.argv[1])
