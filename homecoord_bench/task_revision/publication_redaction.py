"""Normalize local filesystem references and bind published hashes.

This export helper changes path references and publication metadata only;
experiment inputs, traces, scores, and event payloads are not interpreted.
The manifest records each changed file's pre- and post-normalization SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs/PUBLICATION_REDACTION_MANIFEST_2026-10-06.json"
EVIDENCE_MANIFEST = ROOT / "docs/review_evidence/EVIDENCE_SHA256_MANIFEST_2026-10-06.json"
REVIEW_DEST = "docs/review_evidence/2026-10-01_to_2026-10-06/"
GITHUB_BLOB = "https://github.com/xxc0304/homecoord-bench/blob/main/"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@lru_cache(maxsize=1)
def published_redaction_entries():
    if not MANIFEST.exists():
        return {}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {item["path"]: item for item in manifest.get("changed_files", [])}


def original_source_sha256(relative_path: str) -> str:
    entry = published_redaction_entries().get(relative_path)
    if entry:
        return entry["source_sha256"]
    return sha256((ROOT / relative_path).read_bytes())


def matches_source_sha256(relative_path: str, expected_sha256: str) -> bool:
    actual = sha256((ROOT / relative_path).read_bytes())
    if actual == expected_sha256:
        return True
    entry = published_redaction_entries().get(relative_path)
    return bool(
        entry
        and entry["source_sha256"] == expected_sha256
        and entry["published_sha256"] == actual
    )


def repository_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def normalize(text: str, repo_root: Path, review_root: Path, work_root: Path, source_path: Path):
    replacements = []
    repo_variants = {
        str(repo_root).replace("\\", "/"),
        str(repo_root).replace("/", "\\"),
        str(repo_root).replace("\\", "\\\\"),
    }
    review_variants = {
        str(review_root).replace("\\", "/"),
        str(review_root).replace("/", "\\"),
        str(review_root).replace("\\", "\\\\"),
    }
    work_variants = {
        str(work_root).replace("\\", "/"),
        str(work_root).replace("/", "\\"),
        str(work_root).replace("\\", "\\\\"),
    }

    for value in sorted(review_variants, key=len, reverse=True):
        prefix = re.escape(value.rstrip("/\\"))
        text, count = re.subn(prefix + r"[/\\]+", REVIEW_DEST, text, flags=re.IGNORECASE)
        if count:
            replacements.append({"rule": "external_review_output_path", "count": count})
        text, count = re.subn(prefix + r"(?=[\s\"'`),;.:。]|$)", REVIEW_DEST.rstrip("/"), text, flags=re.IGNORECASE)
        if count:
            replacements.append({"rule": "external_review_output_directory", "count": count})

    for value in sorted(work_variants, key=len, reverse=True):
        prefix = re.escape(value.rstrip("/\\"))
        text, count = re.subn(prefix + r"[/\\]+", REVIEW_DEST + "work/", text, flags=re.IGNORECASE)
        if count:
            replacements.append({"rule": "external_review_script_path", "count": count})
        text, count = re.subn(prefix + r"(?=[\s\"'`),;.:。]|$)", REVIEW_DEST.rstrip("/") + "/work", text, flags=re.IGNORECASE)
        if count:
            replacements.append({"rule": "external_review_script_directory", "count": count})

    for value in sorted(repo_variants, key=len, reverse=True):
        prefix = re.escape(value.rstrip("/\\"))
        repo_replacement = GITHUB_BLOB if source_path.suffix.lower() in {".md", ".markdown"} else ""
        text, count = re.subn(prefix + r"[/\\]+", repo_replacement, text, flags=re.IGNORECASE)
        if count:
            replacements.append({"rule": "local_repository_root", "count": count})
        text, count = re.subn(prefix + r"(?=[\s\"'`),;.:。]|$)", ".", text, flags=re.IGNORECASE)
        if count:
            replacements.append({"rule": "local_repository_directory", "count": count})

    if source_path.suffix.lower() in {".md", ".markdown"}:
        def normalize_github_path(match):
            return match.group(1) + match.group(2).replace("\\", "/")

        text, count = re.subn(
            r"(https://github\.com/xxc0304/homecoord-bench/blob/main/)([^\s)\]>`]+)",
            normalize_github_path,
            text,
        )
        if count:
            replacements.append({"rule": "github_markdown_path_separators", "count": count})
        text, count = re.subn(r"(\.py):(\d+)(?=[)\]])", r"\1#L\2", text)
        if count:
            replacements.append({"rule": "markdown_line_anchor", "count": count})

    python_path = re.compile(
        r"[A-Za-z]:[/\\]Users[/\\][^/\\\s'\"]+[/\\]\.cache[/\\]"
        r"codex-runtimes[/\\]codex-primary-runtime[/\\]dependencies[/\\]"
        r"python[/\\]python\.exe",
        flags=re.IGNORECASE,
    )
    text, count = python_path.subn("python", text)
    if count:
        replacements.append({"rule": "machine_specific_python_runtime", "count": count})

    generic_codex_path = re.compile(
        r"[A-Za-z]:[/\\]{1,2}Users[/\\]{1,2}[^/\\\s'\"]+[/\\]{1,2}Documents[/\\]{1,2}"
        r"Codex[/\\]{1,2}2026-10-01[/\\]{1,2}8-8-1-m02-2-m03[/\\]{1,2}outputs[/\\]{1,2}",
        flags=re.IGNORECASE,
    )
    text, count = generic_codex_path.subn(REVIEW_DEST, text)
    if count:
        replacements.append({"rule": "encoded_external_review_output_path", "count": count})

    return text, replacements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-output-dir",
        required=True,
        help="Original directory containing the independent review outputs copied into docs/review_evidence.",
    )
    parser.add_argument(
        "--review-work-dir",
        required=True,
        help="Original directory containing the independent review scripts copied into docs/review_evidence/work.",
    )
    args = parser.parse_args()
    review_root = Path(args.review_output_dir).resolve()
    work_root = Path(args.review_work_dir).resolve()
    prior = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    prior_entries = {entry["path"]: entry for entry in prior.get("changed_files", [])}
    changed = {}
    for path in repository_files(ROOT):
        try:
            before = path.read_bytes()
            if b"\x00" in before:
                continue
            original = before.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        relative = path.relative_to(ROOT).as_posix()
        previous = prior_entries.get(relative)
        published, replacements = normalize(original, ROOT, review_root, work_root, path)
        if not replacements and not previous:
            continue
        after = published.encode("utf-8")
        if after != before:
            path.write_bytes(after)
        passes = list(previous.get("normalization_passes", [])) if previous else []
        if previous and previous.get("replacements"):
            passes.append(previous["replacements"])
        if replacements:
            passes.append(replacements)
        changed[relative] = {
            "path": relative,
            "source_sha256": previous.get("source_sha256") if previous else sha256(before),
            "published_sha256": sha256(after),
            "normalization_passes": passes,
        }

    for relative, entry in prior_entries.items():
        changed.setdefault(relative, entry)

    payload = {
        "date": "2026-10-06",
        "purpose": "Public-release path and reference normalization; no task, trace, score, or metric formula changed.",
        "review_evidence_destination": REVIEW_DEST.rstrip("/"),
        "changed_file_count": len(changed),
        "changed_files": [changed[k] for k in sorted(changed)],
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    evidence_files = []
    for source_dir, public_dir, prefix in (
        (review_root, ROOT / REVIEW_DEST.rstrip("/"), ""),
        (work_root, ROOT / REVIEW_DEST.rstrip("/") / "work", "work/"),
    ):
        for source in sorted(source_dir.iterdir()):
            if not source.is_file():
                continue
            public = public_dir / source.name
            if not public.is_file():
                raise FileNotFoundError(f"review source was not copied into the release: {source.name}")
            evidence_files.append(
                {
                    "path": f"{REVIEW_DEST}{prefix}{source.name}",
                    "source_sha256": sha256(source.read_bytes()),
                    "published_sha256": sha256(public.read_bytes()),
                    "path_redacted": sha256(source.read_bytes()) != sha256(public.read_bytes()),
                }
            )
    evidence_payload = {
        "date": "2026-10-06",
        "source_scope": "review outputs and audit scripts copied from the October 1-6 review task",
        "file_count": len(evidence_files),
        "files": evidence_files,
    }
    EVIDENCE_MANIFEST.write_text(
        json.dumps(evidence_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"normalized {len(changed)} files; manifest: {MANIFEST.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
