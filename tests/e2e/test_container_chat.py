"""Quick end-to-end test against the containerized pandas-ai server (port 8001).

Registers a data file + semantic model, then issues a couple of chat queries
to verify the instructor structured-codegen path works (the module that was
missing in the image).
"""
import base64
import json
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8001"
DATA_FILE = Path("run/File (4).xlsx")
SEMANTIC_MODEL = Path("run/semantic_model.json")


def _load_xlsx_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return (
            "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
            + base64.b64encode(f.read()).decode()
        )


def main() -> int:
    semantic = json.loads(SEMANTIC_MODEL.read_text())

    with httpx.Client(timeout=600) as client:
        # --- health ---
        r = client.get(f"{BASE_URL}/health")
        print(f"[health] {r.status_code} {r.json()}")

        # --- register ---
        payload = {
            "base64_data": _load_xlsx_base64(DATA_FILE),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "semantic_model": semantic,
        }
        r = client.post(f"{BASE_URL}/api/register/base64", json=payload, timeout=600)
        print(f"[register] {r.status_code}")
        if r.status_code != 200:
            print(r.text)
            return 1
        conv_id = r.json().get("conversation_id")
        print(f"[conversation_id] {conv_id}")

        # --- chat query ---
        query = "How many rows are in the dataset? List the columns."
        chat = {
            "conversation_id": conv_id,
            "query": query,
            "output_type": "string",
            "column_selection_enabled": True,
            "column_selection_threshold": 30,
            "column_values_budget_ratio": 0.10,
        }
        t0 = time.time()
        r = client.post(f"{BASE_URL}/api/chat", json=chat, timeout=600)
        dt = time.time() - t0
        print(f"[chat] {r.status_code} in {dt:.1f}s")
        if r.status_code != 200:
            print(r.text[:2000])
            return 1
        resp = r.json()
        print(f"[answer] {str(resp)[:1500]}")
        return 0


if __name__ == "__main__":
    sys.exit(main())