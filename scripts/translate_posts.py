#!/usr/bin/env python3
"""Translate Chinese Hugo posts into English counterparts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib import error, request


REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_POSTS = REPO_ROOT / "content" / "posts"
GLOSSARY_FILE = REPO_ROOT / "data" / "translation-glossary.yml"
DEFAULT_MODEL = "gemini-2.5-flash"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate English Hugo posts from Chinese source posts."
    )
    parser.add_argument(
        "--path",
        nargs="*",
        default=[],
        help="Specific Chinese markdown files to translate.",
    )
    parser.add_argument(
        "--changed-from",
        help="Git ref/sha start for changed-file translation mode.",
    )
    parser.add_argument(
        "--changed-to",
        default="HEAD",
        help="Git ref/sha end for changed-file translation mode. Defaults to HEAD.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force translation even if source hash did not change.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print actions; do not write files.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        help=f"Gemini model to use (default: {DEFAULT_MODEL}).",
    )
    return parser.parse_args()


def is_chinese_post(path: Path) -> bool:
    return (
        path.suffix == ".md"
        and path.parent == CONTENT_POSTS
        and not path.name.endswith(".en.md")
    )


def english_path_for(chinese_path: Path) -> Path:
    return chinese_path.with_name(chinese_path.stem + ".en.md")


def split_front_matter(raw: str) -> tuple[str, str]:
    if not raw.startswith("---\n"):
        raise ValueError("Markdown missing YAML front matter start '---'.")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, flags=re.DOTALL)
    if not match:
        raise ValueError("Cannot parse YAML front matter boundaries.")
    return match.group(1), match.group(2)


def parse_front_matter(fm: str) -> dict:
    """A minimal parser for this blog's front matter shape."""
    result: dict = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if re.match(r"^\s", line):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            nested: dict = {}
            i += 1
            while i < len(lines) and re.match(r"^\s{2,}\S", lines[i]):
                nested_line = lines[i].strip()
                if ":" in nested_line:
                    nk, nv = nested_line.split(":", 1)
                    nested[nk.strip()] = nv.strip().strip('"')
                i += 1
            result[key] = nested
            continue
        result[key] = value
        i += 1
    return result


def parse_inline_list(value: str) -> list[str]:
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    if not text:
        return []
    parts = [item.strip() for item in text.split(",")]
    return [p.strip().strip('"').strip("'") for p in parts if p.strip()]


def parse_glossary(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    pairs: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.endswith(":"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        pairs[k.strip().strip('"').strip("'")] = v.strip().strip('"').strip("'")
    return pairs


def source_hash(front_matter: str, body: str) -> str:
    digest = hashlib.sha256((front_matter + "\n---\n" + body).encode("utf-8")).hexdigest()
    return digest


def extract_existing_hash(english_raw: str) -> str | None:
    match = re.search(r"^source_hash:\s*([a-fA-F0-9]{64})\s*$", english_raw, re.MULTILINE)
    return match.group(1) if match else None


def changed_files(changed_from: str, changed_to: str) -> list[Path]:
    cmd = ["git", "diff", "--name-only", changed_from, changed_to]
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Failed to get changed files from git.")
    files = [REPO_ROOT / line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return [f for f in files if is_chinese_post(f)]


def call_gemini_translation(
    model: str,
    title: str,
    description: str,
    tags: list[str],
    categories: list[str],
    body: str,
    glossary: dict[str, str],
) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    glossary_block = "\n".join([f"- {k} => {v}" for k, v in glossary.items()]) or "- (empty)"
    prompt = f"""
You are a professional Chinese-to-English blog translator.
Translate the provided Chinese blog content to natural, fluent English.

Requirements:
1) Preserve Markdown structure exactly (headings, links, images, code fences, lists, blockquotes).
2) Keep all URLs unchanged.
3) Keep factual meaning; do not add or remove sections.
4) Keep names/brands when appropriate (do not over-translate proper nouns).
5) Return ONLY valid JSON with keys:
   - title
   - description
   - tags (array of strings)
   - categories (array of strings)
   - body (translated markdown body)

Term glossary (must prioritize):
{glossary_block}

Chinese input:
TITLE: {title}
DESCRIPTION: {description}
TAGS: {json.dumps(tags, ensure_ascii=False)}
CATEGORIES: {json.dumps(categories, ensure_ascii=False)}
BODY:
{body}
""".strip()

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=120) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini API error: {e.code} {detail}") from e
    except error.URLError as e:
        raise RuntimeError(f"Network error calling Gemini API: {e}") from e

    candidates = response_data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini response missing candidates: {response_data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"Gemini response missing parts: {response_data}")
    output_text = parts[0].get("text", "")
    if not output_text:
        raise RuntimeError("Gemini response does not include text output.")

    try:
        return json.loads(output_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini output is not valid JSON: {output_text}") from e


def quote(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def write_english_post(
    english_file: Path,
    translated: dict,
    source_meta: dict,
    source_sha: str,
    dry_run: bool,
) -> None:
    title = translated.get("title", "").strip()
    description = translated.get("description", "").strip()
    tags = translated.get("tags", [])
    categories = translated.get("categories", [])
    body = translated.get("body", "")
    if not isinstance(tags, list) or not isinstance(categories, list):
        raise RuntimeError("Model output for tags/categories is invalid.")
    if not title or not body:
        raise RuntimeError("Model output missing title or body.")

    url = source_meta.get("url")
    date = source_meta.get("date")
    draft = source_meta.get("draft", "false")
    cover = source_meta.get("cover", {})

    lines: list[str] = ["---"]
    lines.append(f"title: {quote(title)}")
    if url:
        lines.append(f"url: {url}")
    if date:
        lines.append(f"date: {date}")
    if tags:
        tag_text = ", ".join([quote(str(t)) for t in tags])
        lines.append(f"tags: [{tag_text}]")
    if categories:
        cat_text = ", ".join([quote(str(c)) for c in categories])
        lines.append(f"categories: [{cat_text}]")
    if isinstance(cover, dict) and cover:
        lines.append("cover:")
        if "image" in cover:
            lines.append(f'    image: {quote(str(cover["image"]))}')
        if "alt" in cover:
            lines.append(f'    alt: {quote(str(cover["alt"]))}')
        if "relative" in cover:
            val = str(cover["relative"]).lower()
            if val not in {"true", "false"}:
                val = "false"
            lines.append(f"    relative: {val}")
    lines.append(f"draft: {str(draft).lower()}")
    if description:
        lines.append(f"description: {quote(description)}")
    lines.append(f"source_hash: {source_sha}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip() + "\n")
    output = "\n".join(lines)

    if dry_run:
        print(f"[DRY RUN] would write: {english_file.relative_to(REPO_ROOT)}")
        return

    english_file.write_text(output, encoding="utf-8")
    print(f"wrote: {english_file.relative_to(REPO_ROOT)}")


def gather_targets(args: argparse.Namespace) -> list[Path]:
    targets: list[Path] = []
    for item in args.path:
        path = Path(item)
        abs_path = path if path.is_absolute() else (REPO_ROOT / path)
        if abs_path.exists() and is_chinese_post(abs_path):
            targets.append(abs_path)
        else:
            print(f"skip (not a Chinese post): {item}")

    if args.changed_from:
        targets.extend(changed_files(args.changed_from, args.changed_to))

    if not targets and not args.changed_from and not args.path:
        targets = [p for p in CONTENT_POSTS.glob("*.md") if is_chinese_post(p)]

    uniq: dict[str, Path] = {}
    for p in targets:
        uniq[str(p.resolve())] = p
    return list(uniq.values())


def main() -> int:
    args = parse_args()
    glossary = parse_glossary(GLOSSARY_FILE)
    targets = gather_targets(args)

    if not targets:
        print("No Chinese posts selected.")
        return 0

    translated_count = 0
    skipped_count = 0

    for zh_file in targets:
        raw = zh_file.read_text(encoding="utf-8")
        front_matter, body = split_front_matter(raw)
        meta = parse_front_matter(front_matter)

        english_file = english_path_for(zh_file)
        sha = source_hash(front_matter, body)
        if english_file.exists() and not args.force:
            old_hash = extract_existing_hash(english_file.read_text(encoding="utf-8"))
            if old_hash == sha:
                print(f"skip (hash unchanged): {english_file.relative_to(REPO_ROOT)}")
                skipped_count += 1
                continue

        title_zh = str(meta.get("title", "")).strip().strip('"')
        description_zh = str(meta.get("description", "")).strip().strip('"')
        tags_zh = parse_inline_list(str(meta.get("tags", "")))
        categories_zh = parse_inline_list(str(meta.get("categories", "")))

        if args.dry_run:
            print(f"[DRY RUN] would translate: {zh_file.relative_to(REPO_ROOT)}")
            translated_count += 1
            continue

        translated = call_gemini_translation(
            model=args.model,
            title=title_zh,
            description=description_zh,
            tags=tags_zh,
            categories=categories_zh,
            body=body,
            glossary=glossary,
        )
        write_english_post(
            english_file=english_file,
            translated=translated,
            source_meta=meta,
            source_sha=sha,
            dry_run=args.dry_run,
        )
        translated_count += 1

    print(
        f"done: translated={translated_count}, skipped={skipped_count}, total={len(targets)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
