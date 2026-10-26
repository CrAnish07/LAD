"""Follow Fluentd output and analyze logs with a pool of model workers."""
import glob
import json
import os
import signal
import threading
import time
from collections import deque
from datetime import datetime, timezone

from client import qdrant_client, create_collection
from vectorstore import get_vectorstore
from text_utils import build_context
from rag_chain import get_analyzers
from log_filter import fingerprint, triage


def parse_classification(response):
    """Decode classifier JSON, including JSON wrapped in Markdown fences."""
    text = str(response).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    classification = json.loads(text)
    if not isinstance(classification, dict):
        raise ValueError("Classifier response must be a JSON object")
    return classification


class AnalysisQueue:
    """A shared queue that lets any not-yet-tried model claim a log."""

    def __init__(self, worker_names):
        self.worker_names = tuple(worker_names)
        self.pending = deque()
        self.condition = threading.Condition()
        self.unfinished = 0
        self.stopping = False

    def put(self, task, *, new_task=False):
        with self.condition:
            self.pending.append(task)
            if new_task:
                self.unfinished += 1
            self.condition.notify_all()

    def get(self, worker_name):
        with self.condition:
            while True:
                for index, task in enumerate(self.pending):
                    if worker_name not in task["tried"]:
                        del self.pending[index]
                        return task
                if self.stopping and not self.pending:
                    return None
                self.condition.wait()

    def finish(self):
        with self.condition:
            self.unfinished -= 1
            self.condition.notify_all()

    def wait_until_empty(self):
        with self.condition:
            while self.unfinished:
                self.condition.wait()

    def stop(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()


def main():
    client = qdrant_client()
    collection_name = create_collection(client)
    print(f"Collection created: {collection_name}")
    vector_store = get_vectorstore(client, collection_name)
    analyzers = get_analyzers()
    analysis_queue = AnalysisQueue(analyzers)

    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "daemon", "logs"))
    os.makedirs(log_dir, exist_ok=True)
    dashboard_path = os.path.join(log_dir, "dashboard_events.jsonl")
    append_lock = threading.Lock()
    group_window = max(0.5, float(os.getenv("LOG_GROUP_WINDOW_SECONDS", "5")))
    groups = {}
    log_handles = {}
    waiting_notice_shown = False
    stop_requested = threading.Event()

    def save_event(event, update):
        event.update(update)
        # One append per state update. The dashboard collapses updates by event id.
        with append_lock:
            with open(dashboard_path, "a", encoding="utf-8") as output:
                output.write(json.dumps(event, ensure_ascii=False) + "\n")

    def update_group(events, update):
        for event in events:
            save_event(event, update)

    def worker(worker_name, model, classify):
        while True:
            task = analysis_queue.get(worker_name)
            if task is None:
                return
            task["tried"].add(worker_name)
            update_group(task["events"], {
                "status": "processing",
                "model": model,
                "analysis_source": "llm",
                "models_tried": sorted(task["tried"]),
                "error": None,
            })
            print(f"Analyzing group {task['group_id']} ({task['group_count']} logs) with {worker_name}...", flush=True)
            try:
                raw = classify(task["inputs"])
                classification = parse_classification(raw)
                update_group(task["events"], {
                    "status": "analyzed",
                    "model": model,
                    "analysis_source": "llm",
                    "models_tried": sorted(task["tried"]),
                    "group_count": task["group_count"],
                    "anomaly_detected": bool(classification.get("anomaly_detected", False)),
                    "error_type": classification.get("error_type", "none"),
                    "suggested_fix": classification.get("suggested_fix", "none"),
                    "commands": classification.get("commands", []),
                    "explanation": classification.get("explanation", ""),
                    "confidence": classification.get("confidence", "unknown"),
                    "error": None,
                })
                print(f"Analysis complete: group {task['group_id']} with {worker_name}.", flush=True)
                analysis_queue.finish()
            except Exception as exc:
                remaining_workers = set(analyzers) - task["tried"]
                if remaining_workers:
                    error = f"{worker_name} failed: {exc}"
                    update_group(task["events"], {
                        "status": "queued",
                        "model": None,
                        "analysis_source": "llm",
                        "models_tried": sorted(task["tried"]),
                        "error": error,
                    })
                    print(f"{error}; retrying with another model worker.", flush=True)
                    analysis_queue.put(task)
                else:
                    update_group(task["events"], {
                        "status": "needs_review",
                        "model": "Rules fallback",
                        "analysis_source": "rules_fallback",
                        "models_tried": sorted(task["tried"]),
                        "anomaly_detected": task["triage"]["anomaly"] is True,
                        "error_type": "critical_log" if task["triage"]["severity"] == "critical" else "unclassified_log",
                        "explanation": "All configured model providers failed. Review this grouped log manually. " + task["triage"]["reason"],
                        "error": str(exc),
                    })
                    print(f"All model workers failed for group {task['group_id']}: {exc}", flush=True)
                    analysis_queue.finish()

    def flush_group(key, group):
        groups.pop(key, None)
        events = group["events"]
        decision = triage(group["samples"][0])
        common = {
            "group_id": group["group_id"],
            "group_count": group["count"],
            "analysis_source": "rules",
            "severity": decision["severity"],
            "rule_reason": decision["reason"],
        }
        if decision["route"] == "filter":
            update_group(events, {
                **common,
                "status": "filtered",
                "model": "Rules",
                "anomaly_detected": False,
                "error_type": "none",
                "explanation": f"Filtered as routine ({group['count']} matching log(s)). {decision['reason']}",
                "suggested_fix": "none",
                "commands": [],
            })
            return
        if decision["route"] == "rules":
            update_group(events, {
                **common,
                "status": "analyzed",
                "model": "Rules",
                "anomaly_detected": True,
                "error_type": "log_error",
                "explanation": f"Rule-based detection ({group['count']} matching log(s)). {decision['reason']}",
                "suggested_fix": "Review the matching log entries and affected service.",
                "commands": [],
                "confidence": "medium",
            })
            return

        sample_text = "\n".join(f"- {sample}" for sample in group["samples"][:3])
        query = (
            f"Grouped log event ({group['count']} matching occurrences in {group_window:g}s). "
            f"Severity: {decision['severity']}.\nRepresentative messages:\n{sample_text}"
        )
        context = ""
        # Retrieve only explicitly ingested reference data. Live events must not
        # enter the corpus before analysis, or they can retrieve themselves (or
        # other recent live events) as misleading context.
        # Embedding and retrieval are best-effort. A Gemini embedding quota
        # must not prevent the configured chat model workers from analyzing logs.
        try:
            context = build_context(vector_store.similarity_search_with_score(
                query, k=3, filter={"source": "historical"}
            ))
        except Exception as exc:
            print(f"Context retrieval unavailable for {group['group_id']}: {exc}", flush=True)
        update_group(events, {
            **common,
            "status": "queued",
            "analysis_source": "llm",
            "model": None,
            "anomaly_detected": decision["anomaly"],
            "error_type": "critical_log" if decision["severity"] == "critical" else "unknown",
            "explanation": f"Waiting for model analysis. {decision['reason']}",
            "models_tried": [],
        })
        analysis_queue.put({
            "group_id": group["group_id"],
            "group_count": group["count"],
            "events": events,
            "inputs": {"query": query, "context": context},
            "triage": decision,
            "tried": set(),
        }, new_task=True)

    def flush_expired_groups(force=False):
        now = time.monotonic()
        expired = [
            (key, group) for key, group in list(groups.items())
            if force or now - group["opened_at"] >= group_window
        ]
        for key, group in expired:
            flush_group(key, group)

    threads = []
    for worker_name, (model, classify) in analyzers.items():
        thread = threading.Thread(
            target=worker,
            args=(worker_name, model, classify),
            name=f"analysis-{worker_name}",
        )
        thread.start()
        threads.append(thread)
    print("Analysis workers: " + ", ".join(analyzers), flush=True)

    def request_stop(_signum, _frame):
        stop_requested.set()

    def interrupt_now(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, interrupt_now)

    # Existing output files are historical; files created after startup are
    # tailed from byte zero so Fluentd's first flush is not missed.
    known_files = set(glob.glob(os.path.join(log_dir, "data.log.*.log")))
    try:
        while True:
            for log_file in glob.glob(os.path.join(log_dir, "data.log.*.log")):
                if log_file not in log_handles:
                    handle = open(log_file, "r", encoding="utf-8")
                    if log_file in known_files:
                        handle.seek(0, os.SEEK_END)
                    known_files.add(log_file)
                    log_handles[log_file] = handle
                    print(f"Following Fluentd output: {log_file}")

            if not log_handles and not waiting_notice_shown:
                print("Waiting for Fluentd to write its first log record...")
                waiting_notice_shown = True

            for handle in list(log_handles.values()):
                line = handle.readline()
                while line:
                    line = line.strip()
                    if line:
                        flush_expired_groups()
                        record = {}
                        try:
                            record = json.loads(line)
                            query = record.get("message", line) if isinstance(record, dict) else line
                        except json.JSONDecodeError:
                            query = line
                        metadata = {
                            "file": record.get("file", "unknown") if isinstance(record, dict) else "unknown",
                            "source": "live_log",
                        }
                        event_id = f"{os.path.basename(handle.name)}:{handle.tell()}"
                        event = {
                            "id": event_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "message": query,
                            "file": metadata["file"],
                            "status": "collecting",
                            "model": None,
                            "models_tried": [],
                        }
                        save_event(event, {"status": "collecting"})
                        key = (metadata["file"], fingerprint(query))
                        group = groups.get(key)
                        if group is None:
                            group = {
                                "group_id": event_id,
                                "events": [],
                                "samples": [],
                                "count": 0,
                                "opened_at": time.monotonic(),
                                "file": metadata["file"],
                            }
                            groups[key] = group
                        group["events"].append(event)
                        group["count"] += 1
                        if query not in group["samples"] and len(group["samples"]) < 3:
                            group["samples"].append(query)
                    line = handle.readline()

            flush_expired_groups()

            if stop_requested.is_set() and all(
                os.fstat(handle.fileno()).st_size <= handle.tell()
                for handle in log_handles.values()
            ):
                print("Stop requested; draining queued and active analysis jobs.", flush=True)
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Draining queued and active analysis jobs.", flush=True)
    finally:
        for handle in log_handles.values():
            handle.close()
        flush_expired_groups(force=True)
        analysis_queue.wait_until_empty()
        analysis_queue.stop()
        for thread in threads:
            thread.join()


if __name__ == "__main__":
    main()
