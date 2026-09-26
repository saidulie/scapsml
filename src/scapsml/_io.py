"""Small file helpers that always close what they open.

`read_rows(path)` leaves the handle open until garbage collection.
On Windows an open handle LOCKS the file, so a manifest or dataset left open
by one step can stop a later step -- or SCAPS itself -- from writing it.
Everything in the package reads and writes through these instead.
"""

from __future__ import annotations

import csv
import json


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
