# Log Anomaly Detector
Log Anomaly Detector (LAD): Real-time system for semantic log monitoring and anomaly detection using Rust, Python, and Qdrant

# LAD — Log Anomaly Detector

Real-time log monitoring & semantic anomaly detection using Fluentd, Qdrant, and Google Gemini embeddings.

---

LAD helps you continuously monitor log files and detect anomalies (errors, warnings, unusual behavior) by:

- Collecting logs from multiple sources via Fluentd.  
- Buffering them in live log files.  
- Embedding log lines using semantic embeddings (Google Gemini).  
- Storing embeddings in Qdrant vector database.  
- Running similarity search + a prompt chain (RAG) to classify whether a log line is anomalous and suggest context/fix.  

--- 

## Project Structure

```
LAD/
├── daemon/ # Fluentd config, log buffer setup, log file watcher
│ ├── config.yaml
│ ├── fluent.conf
│ ├── docker_run
│ ├── logs/
│ ├── data.log/
│ ├ buffer..log
│ └ buffer..log.meta
│ └ historical logs (rotated)
│ └ daemon.py
├── scripts/ # Core Python scripts
│ ├── client.py
│ ├── vectorstore.py
│ ├── text_utils.py
│ ├── rag_chain.py
│ └ main.py # Anomaly detection loop
├── config/ # Additional configuration if any
├── tests/ # Unit / integration tests
├── Apache_2k.log # Sample logs
├── Windows_2k.log # Sample logs
├── operate.sh # Orchestration script to spin up Fluentd, run main, clean up
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

4. **Configure Fluentd**

   Edit daemon/config.yaml to specify the log paths you want to monitor.
   Fluentd configuration is in daemon/fluent.conf.

5. **Start services**

   ```bash
   ./operate.sh <seconds_to_run>

The script will:

- Start Fluentd (Docker) with correct mounts & user permissions.

- Run daemon.py to tail/forward logs.

- Run main.py to detect anomalies.

- After the duration, stop everything and optionally clear logs.
