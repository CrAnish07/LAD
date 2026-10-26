# Log Anomaly Detector
Log Anomaly Detector (LAD): Real-time system for semantic log monitoring and anomaly detection using Python, and Qdrant

# LAD — Log Anomaly Detector

Real-time log monitoring and semantic anomaly detection using Fluentd and Qdrant, with configurable parallel Gemini and Groq analysis workers.

![Vector embedding search diagram](docs/assets/vector-embedding-search.webp)

---

LAD helps you continuously monitor log files and detect anomalies (errors, warnings, unusual behavior) by:

- Collecting logs from multiple sources via Fluentd.  
- Buffering them in live log files.  
- Embedding log lines using semantic embeddings (Google Gemini).  
- Storing embeddings in Qdrant vector database.  
- Searching an explicitly ingested historical reference corpus, then running model workers to classify live log lines and suggest context/fixes. Live events are not added to that corpus during analysis.

--- 

## Project Structure

```
LAD/
├── data/
│   └── sample_logs/          # Apache and Windows sample datasets
├── daemon/                   # Fluentd config and log file watcher
│   ├── config.yaml
│   ├── daemon.py
│   ├── docker_run
│   ├── etc/
│   │   └── fluent.conf
│   ├── fluent.conf
│   └── logs/                  # Fluentd buffer and rotated runtime logs
├── docs/
│   └── assets/                # Documentation images
├── scripts/                  # Core Python scripts
│   ├── client.py
│   ├── log_ingestion.py
│   ├── main.py
│   ├── rag_chain.py
│   ├── text_utils.py
│   └── vectorstore.py
├── config/                   # Additional configuration
├── consumer/                 # Consumer application
├── frontend/
│   └── dashboard.html        # Local live dashboard
├── tests/                    # Unit and integration tests
├── operate.sh                # Starts Fluentd and Python processes
├── requirements.txt
└── README.md
```

---


---

## Setup & Installation

1. **Clone the repo**

   ```bash
   git clone https://github.com/CrAnish07/LAD.git
   cd LAD

2. **Create Python virtual environment**
   
   ```bash
   python3 -m venv venv
   source venv/bin/activate

3. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt

4. **Configure Fluentd and log paths**

   Edit `daemon/config.yaml` and set the paths under the matching OS in
   `logs_by_os`. The daemon detects macOS (`Darwin`) or Linux at startup and
   uses that OS's list. The example config watches the Parallels log on macOS
   and `/var/log/syslog` on Linux; replace these with log files present on
   your machine. Linux system logs may require read permissions for your user.
   Fluentd configuration is in daemon/fluent.conf.

   Copy `.env.example` to `.env` and set `GOOGLE_API_KEY` for Gemini embeddings
   and the Gemini analysis worker, and `GROQ_API_KEY` for the Groq analysis
   worker. `ANALYSIS_WORKERS` defaults to one Gemini worker and one Groq worker;
   each configured provider/model pair handles logs concurrently. A failed log
   is retried by each other configured worker at most once. `operate.sh` starts a local Qdrant container automatically
   unless `QDRANT_HOST` is set in the shell or `.env`.

5. **Start services**

   To provide historical context, ingest a reference log dataset into the
   configured `QDRANT_COLLECTION_NAME` first:

   ```bash
   python scripts/log_ingestion.py
   ```

   Live analysis retrieves only records tagged as historical. Existing records
   in Qdrant without that source tag are ignored; re-ingest trusted reference
   data to make it available to retrieval.

   ```bash
   ./operate.sh [seconds_to_run]

The script will:

- Start Fluentd (Docker) with correct mounts & user permissions.

- Run daemon.py to tail/forward logs.

- Run main.py to detect anomalies.

- With a duration, stop after that many seconds. Without one, run until you
  press Ctrl+C. Both shutdown paths stop the services and drain flushed logs.

## Dashboard

Start LAD with `./operate.sh` (or `./operate.sh <seconds>` for a timed run), then
open a second terminal and run:

```bash
venv/bin/python scripts/dashboard.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080) to see analyzed events,
detected anomalies, the recent event stream, and Fluentd/Qdrant reachability.
The dashboard refreshes every three seconds. It reads analysis results from
`daemon/logs/dashboard_events.jsonl`; queued and processing events show the
assigned model, and completed events show the model that produced the result.
Results appear as the pipeline processes new incoming log lines. Set
`DASHBOARD_HOST` and `DASHBOARD_PORT` to change the
local bind address and port.

Before embedding or model analysis, LAD groups matching messages from the same
source for `LOG_GROUP_WINDOW_SECONDS` (default five seconds) and applies local
rules. Routine health/probe/debug logs are marked filtered, common error
patterns are classified by rules, and critical or uncertain groups are sent to
the configured model workers. Every raw log still appears in the dashboard;
group occurrence counts and the analysis source are shown per event. If all
model workers fail, the event is marked `Needs review` with a rules-based
fallback. Gemini is still used for embeddings only for groups routed to model
analysis; if embedding/retrieval is unavailable, chat analysis continues
without retrieved context.

The project overview website is maintained in the separate
[lad-site repository](https://github.com/CrAnish07/lad-site) and can be
published with GitHub Pages from its `main` branch. The live dashboard remains
a local app because it depends on the running LAD processes and `/api/overview`
endpoint.

### Generate demo activity

With Fluentd, Qdrant, and the analysis process running, send a repeatable burst
of 48 synthetic events (including obvious timeout, disk, queue, and service
failure examples) through Fluentd:

```bash
venv/bin/python scripts/demo_load.py
```

The default sends 16 records per burst, with one anomaly example every four
records. The dashboard chart uses two-hour buckets over the last 24 hours, so
the burst appears at the latest end of the chart. Adjust volume or pacing with
`--count`, `--burst-size`, `--burst-gap`, and `--record-delay`. Gemini classifies
each event as the normal pipeline processes it; classification speed depends on
the configured API/model response time.
