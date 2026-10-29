"""Reading and writing the JSON dataset. Validation happens on load, not on trust."""

from __future__ import annotations

import json
from pathlib import Path

from .model import FeeRecord, RecordError

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "fees"


def _file_for(country):
    return DATA_DIR / f"{country.lower()}.json"


def load_country(country):
    """Load every record for one ISO-3166 alpha-2 country code."""
    path = _file_for(country)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RecordError(f"{path.name}: expected a JSON list of records")
    records = []
    for i, item in enumerate(raw):
        try:
            records.append(FeeRecord.from_dict(item))
        except RecordError as exc:
            raise RecordError(f"{path.name}[{i}]: {exc}") from None
    return records


def load_all():
    """Load the whole dataset, keyed by slug."""
    out = {}
    if not DATA_DIR.exists():
        return out
    for path in sorted(DATA_DIR.glob("*.json")):
        for record in load_country(path.stem):
            if record.slug in out:
                raise RecordError(f"duplicate slug across files: {record.slug}")
            out[record.slug] = record
    return out


def save_country(country, records):
    """Write one country file atomically, after validating every record."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _file_for(country)
    payload = [r.to_dict() for r in records]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
