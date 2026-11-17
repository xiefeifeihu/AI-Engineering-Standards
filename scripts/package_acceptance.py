#!/usr/bin/env python3
# coding: utf-8
"""Unified Acceptance Evidence ZIP Packager for AI-Engineering-Standards (STD-016 / STD-019 / STD-020 / STD-034).

- Single authoritative acceptance packager for `AI-Engineering-Standards`.
- Manifest-driven packaging: every file listed in `manifest.json` must exist,
  have size > 0 matching `size`, and match `sha256`.
- Enforces required manifest metadata: `task_id`, `version`, `run_id`, `created_at` (ISO 8601 with timezone), and `files`.
- Ensures parameter consistency between CLI arguments and manifest data.
- Persists `run_id` into `manifest.json` so the archive contains the authoritative run_id.
- `manifest.json` must NOT contain the final ZIP's own SHA256 or self-reference.
- Formal `output_directory` is strictly pinned to `.artifacts/packages/`.
- Computes external `<zip_name>.sha256` after ZIP creation and performs real
  extraction + SHA256 verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
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
        version = v_file.read_text(encoding="utf-8-sig").strip() if v_file.exists() else "3.0.0"
    clean = str(version).strip()
    raw_ver = clean[1:] if clean.lower().startswith("v") else clean
    return raw_ver, f"v{raw_ver}"


def validate_acceptance_manifest(
    source_acceptance: Path,
    expected_task_id: str | None = None,
    expected_version: str | None = None,
    expected_run_id: str | None = None,
    repo_root: Path = REPO_ROOT,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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

    # Required field: task_id
    task_id = manifest_data.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("Manifest missing required field: 'task_id'")
    if expected_task_id and task_id.strip() != expected_task_id.strip():
        raise ValueError(f"Manifest task_id mismatch: '{task_id}' != expected '{expected_task_id}'")

    # Required field: version
    version = manifest_data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Manifest missing required field: 'version'")
    if expected_version:
        _, exp_v = normalize_version(expected_version, repo_root)
        _, act_v = normalize_version(version, repo_root)
        if exp_v != act_v:
            raise ValueError(f"Manifest version mismatch: '{version}' != expected '{expected_version}'")

    # Required field: run_id
    run_id = manifest_data.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("Manifest missing required field: 'run_id'")
    if expected_run_id and run_id.strip() != expected_run_id.strip():
        raise ValueError(f"Manifest run_id mismatch: '{run_id}' != expected '{expected_run_id}'")

    # Required field: created_at (ISO 8601 with timezone)
    created_at = manifest_data.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("Manifest missing required field: 'created_at'")
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Timezone offset missing")
    except Exception as exc:
        raise ValueError(f"Invalid created_at: must be valid ISO 8601 with timezone ({exc})")

    # Required field: files
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
        if ".." in Path(norm_rel).parts:
            raise ValueError(f"Forbidden path traversal in manifest: '{norm_rel}'")

        src_file = (source_acceptance / norm_rel).resolve()
        try:
            src_file.relative_to(resolved_root)
        except ValueError:
            raise ValueError(f"Path outside acceptance directory: '{norm_rel}'")

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


def package_acceptance(
    task_id: str,
    version: str | None = None,
    run_id: str | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    raw_ver, v_ver = normalize_version(version, repo_root)
    source_acceptance = repo_root / ".artifacts" / "acceptance" / task_id / v_ver
    if not source_acceptance.exists() or not source_acceptance.is_dir():
        raise FileNotFoundError(f"Acceptance directory not found: {source_acceptance}")

    manifest_path = source_acceptance / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {source_acceptance}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest_data, dict):
        raise ValueError("manifest.json root must be a JSON object")

    # run_id resolution and persistence
    if run_id and str(run_id).strip():
        effective_run_id = str(run_id).strip()
    else:
        existing_run_id = manifest_data.get("run_id")
        if isinstance(existing_run_id, str) and existing_run_id.strip():
            effective_run_id = existing_run_id.strip()
        else:
            effective_run_id = f"run-{int(time.time())}"

    manifest_changed = False
    if manifest_data.get("run_id") != effective_run_id:
        manifest_data["run_id"] = effective_run_id
        manifest_changed = True
    if not manifest_data.get("task_id"):
        manifest_data["task_id"] = task_id
        manifest_changed = True
    if not manifest_data.get("version"):
        manifest_data["version"] = v_ver
        manifest_changed = True

    original_manifest_bytes = manifest_path.read_bytes()
    if manifest_changed:
        tmp_manifest = manifest_path.with_suffix(f".tmp_{os.getpid()}_{int(time.time() * 1000)}")
        tmp_manifest.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp_manifest, manifest_path)

    try:
        # Validate manifest and files
        validated_manifest, validated_entries = validate_acceptance_manifest(
            source_acceptance,
            expected_task_id=task_id,
            expected_version=v_ver,
            expected_run_id=effective_run_id,
            repo_root=repo_root,
        )
    except Exception:
        if manifest_changed:
            manifest_path.write_bytes(original_manifest_bytes)
        raise

    pkg_dir = repo_root / ".artifacts" / "packages"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"Acceptance-{task_id}-{v_ver}.zip"
    zip_path = pkg_dir / zip_name
    sha_path = pkg_dir / f"{zip_name}.sha256"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest_path, arcname="manifest.json")
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
        ext_m = extract_dir / "manifest.json"
        if not ext_m.exists() or sha256_file(ext_m).lower() != sha256_file(manifest_path).lower():
            raise ValueError("Extraction verification failed for manifest.json")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    return {
        "task_id": task_id,
        "version": v_ver,
        "run_id": effective_run_id,
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
