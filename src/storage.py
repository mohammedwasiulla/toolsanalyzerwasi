"""
Minimal storage layer. Deliberately just CSV + JSON files on disk -
no database server, no hidden state, so a non-technical reviewer (or
Claude Code / any teammate) can open a file and see exactly what each
agent produced.
"""

import csv
import json
import os
from typing import List, Dict


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def write_csv(rows: List[Dict], path: str):
    if not rows:
        # still create an empty file with no rows so downstream code
        # doesn't crash on "file not found"
        open(path, "w").close()
        return
    fieldnames = list(rows[0].keys())
    ensure_dir(os.path.dirname(path))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # lists/dicts inside a CSV cell get JSON-encoded
            flat = {
                k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                for k, v in row.items()
            }
            writer.writerow(flat)


def read_csv(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            for k, v in list(row.items()):
                if isinstance(v, str) and v.startswith(("[", "{")):
                    try:
                        row[k] = json.loads(v)
                    except json.JSONDecodeError:
                        pass
            rows.append(row)
        return rows


def write_json(obj, path: str):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def read_json(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
