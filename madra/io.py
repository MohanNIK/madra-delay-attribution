from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import CaseRecord


def read_jsonl(path: str | Path) -> list[dict]:
    rows: list[dict] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


def read_cases(path: str | Path, *, limit: int | None = None) -> list[CaseRecord]:
    rows = read_jsonl(path)
    if limit is not None:
        rows = rows[:limit]
    return [CaseRecord.from_dict(row) for row in rows]


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
