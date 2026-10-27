# ingest_apache.py
from pathlib import Path
import re
import time
import uuid
from client import qdrant_client, create_collection
from vectorstore import get_vectorstore
from text_utils import chunk_text

DEFAULT_LOG_FILE = Path(__file__).resolve().parent.parent / "data" / "sample_logs" / "Apache_2k.log"
EMBEDDING_BATCH_SIZE = 50
EMBEDDING_BATCH_INTERVAL_SECONDS = 31
MAX_RATE_LIMIT_ATTEMPTS = 5


def _is_rate_limit_error(error):
    message = str(error).lower()
    return any(marker in message for marker in ("429", "resource_exhausted", "quota exceeded", "rate limit"))


def _retry_delay(error, attempt):
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", str(error), re.IGNORECASE)
    if match:
        return float(match.group(1)) + 2
    return min(30 * (2 ** (attempt - 1)), 300)


def ingest_logs(file_path=DEFAULT_LOG_FILE, collection_name=None):
    client = qdrant_client()
    collection_name = create_collection(client, collection_name)
    vector_store = get_vectorstore(client, collection_name)

    with open(file_path, "r", encoding="utf-8") as f:
        raw_logs = f.read()

    chunks = chunk_text(raw_logs, chunk_size=500, overlap=50)

    texts = [chunk.strip() for chunk in chunks if chunk.strip()]
    source = str(Path(file_path).resolve())
    metadata = [{"source": "historical", "file": source} for _ in texts]
    # Stable IDs make reruns after a quota/network failure idempotent: chunks
    # already written are updated in place instead of duplicated.
    ids = [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}:{index}"))
        for index in range(len(texts))
    ]

    completed = 0
    last_batch_at = None
    for offset in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch_texts = texts[offset:offset + EMBEDDING_BATCH_SIZE]
        batch_metadata = metadata[offset:offset + EMBEDDING_BATCH_SIZE]
        batch_ids = ids[offset:offset + EMBEDDING_BATCH_SIZE]

        if last_batch_at is not None:
            elapsed = time.monotonic() - last_batch_at
            wait = EMBEDDING_BATCH_INTERVAL_SECONDS - elapsed
            if wait > 0:
                print(f"Rate-limit pacing: waiting {wait:.0f}s before the next embedding batch.", flush=True)
                time.sleep(wait)

        for attempt in range(1, MAX_RATE_LIMIT_ATTEMPTS + 1):
            try:
                vector_store.add_texts(
                    batch_texts,
                    metadatas=batch_metadata,
                    ids=batch_ids,
                    batch_size=EMBEDDING_BATCH_SIZE,
                )
                last_batch_at = time.monotonic()
                completed += len(batch_texts)
                print(f"Embedded {completed}/{len(texts)} historical chunks.", flush=True)
                break
            except Exception as exc:
                if not _is_rate_limit_error(exc) or attempt == MAX_RATE_LIMIT_ATTEMPTS:
                    raise
                wait = _retry_delay(exc, attempt)
                print(
                    f"Gemini embedding rate limit reached; retrying batch in {wait:.0f}s "
                    f"(attempt {attempt + 1}/{MAX_RATE_LIMIT_ATTEMPTS}).",
                    flush=True,
                )
                time.sleep(wait)

    print(f"Ingested {len(texts)} log chunks into collection '{collection_name}'")

if __name__ == "__main__":
    ingest_logs()
