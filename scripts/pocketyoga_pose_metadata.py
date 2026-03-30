#!/usr/bin/env python3
"""
Fetch Pocket Yoga pose metadata and produce a local index (CSV/JSON) with
suggested, filesystem-safe filenames like "Mountain_Tadasana".

Note: This script intentionally does NOT download pose images or take screenshots.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


POSES_JSON_URL = "https://pocketyoga.com/poses.json"


@dataclass(frozen=True)
class PoseRecord:
    pose_id: str
    display_name: str | None
    sanskrit_simplified_primary: str | None
    sanskrit_latin_primary: str | None
    category: str | None
    subcategory: str | None
    difficulty: str | None
    pose_url: str
    suggested_filename: str


_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def _title_case_ascii(token: str) -> str:
    token = token.strip()
    if not token:
        return token
    return token[0].upper() + token[1:]


def _sanitize_token(token: str) -> str:
    token = token.strip()
    token = _NON_ALNUM_RE.sub("_", token)
    token = token.strip("_")
    token = re.sub(r"_+", "_", token)
    return token


def _suggested_filename(display_name: str | None, sanskrit_simplified: str | None, pose_id: str) -> str:
    left = _sanitize_token(display_name or pose_id)
    right = _sanitize_token(sanskrit_simplified or "")
    if right:
        right = "_".join(_title_case_ascii(part.lower()) for part in right.split("_") if part)
        base = f"{left}_{right}"
    else:
        base = left
    return base or _sanitize_token(pose_id)


def _unique_filenames(records: list[PoseRecord]) -> list[PoseRecord]:
    used: dict[str, int] = {}
    out: list[PoseRecord] = []
    for r in records:
        name = r.suggested_filename
        if name not in used:
            used[name] = 1
            out.append(r)
            continue
        used[name] += 1
        # Make collisions deterministic and still readable.
        # Example: Mountain_Tadasana_MountainArmsSide
        disambiguated = f"{name}_{_sanitize_token(r.pose_id)}"
        out.append(
            PoseRecord(
                **{
                    **asdict(r),
                    "suggested_filename": disambiguated,
                }
            )
        )
    return out


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (metadata fetch; +https://openai.com) python-urllib",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read().decode(charset, errors="replace")
    return json.loads(raw)


def _load_poses(input_path: str | None) -> list[dict[str, Any]]:
    if input_path:
        p = Path(input_path)
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = _fetch_json(POSES_JSON_URL)
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array at poses.json")
    return [x for x in data if isinstance(x, dict)]


def _first_sanskrit(poses_obj: dict[str, Any]) -> tuple[str | None, str | None]:
    sanskrit = poses_obj.get("sanskrit_names")
    if not isinstance(sanskrit, list) or not sanskrit:
        return None, None
    first = sanskrit[0]
    if not isinstance(first, dict):
        return None, None
    simplified = first.get("simplified")
    latin = first.get("latin")
    return (simplified if isinstance(simplified, str) else None, latin if isinstance(latin, str) else None)


def _iter_records(poses: Iterable[dict[str, Any]]) -> list[PoseRecord]:
    records: list[PoseRecord] = []
    for obj in poses:
        pose_id = obj.get("name")
        if not isinstance(pose_id, str) or not pose_id.strip():
            continue
        display_name = obj.get("display_name")
        display_name = display_name if isinstance(display_name, str) else None
        simplified, latin = _first_sanskrit(obj)

        # The site routes poses at /pose/<pose_id>
        pose_url = f"https://pocketyoga.com/pose/{pose_id}"

        suggested = _suggested_filename(display_name, simplified, pose_id)
        records.append(
            PoseRecord(
                pose_id=pose_id,
                display_name=display_name,
                sanskrit_simplified_primary=simplified,
                sanskrit_latin_primary=latin,
                category=obj.get("category") if isinstance(obj.get("category"), str) else None,
                subcategory=obj.get("subcategory") if isinstance(obj.get("subcategory"), str) else None,
                difficulty=obj.get("difficulty") if isinstance(obj.get("difficulty"), str) else None,
                pose_url=pose_url,
                suggested_filename=suggested,
            )
        )
    return _unique_filenames(records)


def _write_json(out_path: Path, records: list[PoseRecord]) -> None:
    out_path.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(out_path: Path, records: list[PoseRecord]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(records[0]).keys()) if records else [])
        w.writeheader()
        for r in records:
            w.writerow(asdict(r))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", help="Path to a local poses.json (skip network fetch).")
    ap.add_argument("--out-dir", default="data/pocketyoga", help="Output directory (default: data/pocketyoga).")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of records (0 = all).")
    args = ap.parse_args(argv)

    poses = _load_poses(args.input)
    records = _iter_records(poses)
    if args.limit and args.limit > 0:
        records = records[: args.limit]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_json(out_dir / "poses.metadata.json", records)
    if records:
        _write_csv(out_dir / "poses.metadata.csv", records)
    else:
        # Still create an empty CSV with no header.
        (out_dir / "poses.metadata.csv").write_text("", encoding="utf-8")

    sys.stdout.write(f"Wrote {len(records)} records to {out_dir}/poses.metadata.(json|csv)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
