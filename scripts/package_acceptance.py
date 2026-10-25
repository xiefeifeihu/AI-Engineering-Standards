#!/usr/bin/env python3
# coding: utf-8
"""Unified Acceptance Evidence ZIP Packager for AI-Engineering-Standards (STD-016 / STD-019 / STD-034).

- Single authoritative acceptance packager for `AI-Engineering-Standards`.
- Manifest-driven packaging: every file listed in `manifest.json` must exist,
  have size > 0 matching `size`, and match `sha256`.
- `manifest.json` must NOT contain the final ZIP's own SHA256.
- Formal `output_directory` is strictly pinned to `.artifacts/packages/`.
- Computes external `<zip_name>.sha256` after ZIP creation and performs real
  extraction + SHA256 verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FORBIDDEN_MANIFEST_ZIP_HASH_KEYS = {
    "zip_sha256",
    "package_sha256",
    "acceptance_zip_sha256",
    "final_zip_sha256",
    "archive_sha256",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_version(version: str | None, repo_root: Path = REPO_ROOT) -> tuple[str, str]:
    if not version:
        v_file = repo_root / "VERSION"
        version = v_file.read_text(encoding="utf-8-sig").strip() if v_file.exists() else "2.5.0"
    clean = str(version).strip()
    raw_ver = clean[1:] if clean.lower().startswith("v") else clean
    return raw_ver, f"v{raw_ver}"


def validate_acceptance_manifest(source_acceptance: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not source_acceptance.exists() or not source_acceptance.is_dir():
        raise FileNotFoundError(f"Acceptance directory not found: {source_acceptance}")
    illegal_zips = [
        z for z in source_acceptance.rglob("*.zip")
        if not (z.parent.name == "traces" and "trace" in z.name.lower())
    ]
    if illegal_zips:
        raise ValueError(f"Forbidden ZIP archive inside acceptance directory: {illegal_zips[0]}")

    manifest_path = source_acceptance / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {source_acceptance}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest_data, dict):
        raise ValueError("manifest.json root must be a JSON object")

    for k in FORBIDDEN_MANIFEST_ZIP_HASH_KEYS:
        if k in manifest_data and manifest_data[k]:
            raise ValueError(f"Manifest must not contain final ZIP SHA256 self-reference key: {k}")

    files_list = manifest_data.get("files")
    if not isinstance(files_list, list) or not files_list:
        raise ValueError("manifest.json must contain a non-empty 'files' list")

    resolved_root = source_acceptance.resolve()
    validated_entries: list[dict[str, Any]] = []
    for idx, entry in enumerate(files_list):
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest 'files[{idx}]' must be an object")
        rel_raw = str(entry.get("path") or "").strip()
        expected_size = entry.get("size")
        expected_sha256 = str(entry.get("sha256") or "").strip()
        if not rel_raw or not isinstance(expected_size, int) or expected_size <= 0 or not SHA256_HEX_RE.match(expected_sha256):
            raise ValueError(f"Invalid manifest entry at index {idx}: {entry}")
        norm_rel = rel_raw.replace("\\", "/").lstrip("/")
        if norm_rel == "manifest.json":
            raise ValueError("Manifest 'files' must not self-reference manifest.json")
        src_file = (source_acceptance / norm_rel).resolve()
        src_file.relative_to(resolved_root)
        if not src_file.exists() or not src_file.is_file():
            raise FileNotFoundError(f"Manifest listed file does not exist: {src_file}")
        actual_size = src_file.stat().st_size
        actual_sha256 = sha256_file(src_file)
        if actual_size != expected_size or actual_sha256.lower() != expected_sha256.lower():
            raise ValueError(f"Integrity mismatch for {norm_rel}: size {actual_size}/{expected_size}, sha256 {actual_sha256}/{expected_sha256}")
        validated_entries.append({
            "path": norm_rel,
            "size": actual_size,
            "sha256": actual_sha256.lower(),
            "abs_path": src_file,
        })
    return manifest_data, validated_entries


def package_acceptance(task_id: str, version: str | None = None, run_id: str | None = None, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    raw_ver, v_ver = normalize_version(version, repo_root)
    run_id = run_id or f"run-{int(time.time())}"
    source_acceptance = repo_root / ".artifacts" / "acceptance" / task_id / v_ver
    manifest_data, validated_entries = validate_acceptance_manifest(source_acceptance)

    pkg_dir = repo_root / ".artifacts" / "packages"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"Acceptance-{task_id}-{v_ver}.zip"
    zip_path = pkg_dir / zip_name
    sha_path = pkg_dir / f"{zip_name}.sha256"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(source_acceptance / "manifest.json", arcname="manifest.json")
        for item in validated_entries:
            zf.write(item["abs_path"], arcname=item["path"])

    zip_sha = sha256_file(zip_path)
    sha_path.write_text(f"{zip_sha}  {zip_name}\n", encoding="utf-8")

    # Real extraction verification
    extract_dir = pkg_dir / f".verify_extract_{int(time.time() * 1000)}_{os.getpid()}"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        for item in validated_entries:
            ext_f = extract_dir / item["path"]
            if not ext_f.exists() or ext_f.stat().st_size != item["size"] or sha256_file(ext_f).lower() != item["sha256"]:
                raise ValueError(f"Extraction verification failed for {item['path']}")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    return {
        "task_id": task_id,
        "version": v_ver,
        "run_id": run_id,
        "zip_path": str(zip_path.relative_to(repo_root)).replace("\\", "/"),
        "sha256_path": str(sha_path.relative_to(repo_root)).replace("\\", "/"),
        "zip_sha256": zip_sha,
        "files_verified": len(validated_entries),
        "status": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Standards Acceptance Evidence ZIP")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--version", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()
    res = package_acceptance(task_id=args.task_id, version=args.version, run_id=args.run_id)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()