# djn_engine/logger.py
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

LOG_DIR = os.getenv("DJN_LOG_DIR", "logs")
LOG_FILE = os.getenv("DJN_LOG_FILE", "djn_runs.jsonl")

def log_run(payload: Dict[str, Any]) -> str:

    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, LOG_FILE)

    record = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        **(payload or {}),
    }

    line = json.dumps(record, ensure_ascii=False, default=str)

    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    return path

def read_last_runs(limit: int = 25) -> list[dict]:

    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, LOG_FILE)
    if not os.path.exists(path):
        return []

    out = []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in reversed(lines[-limit:]):
        line = (line or "").strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue

    return out
