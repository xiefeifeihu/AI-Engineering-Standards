#!/usr/bin/env python3
# coding: utf-8
"""Unified Acceptance Evidence ZIP Packager for AI-Engineering-Standards (STD-016 / STD-019 / STD-020 / STD-034).

- Single authoritative acceptance packager for `AI-Engineering-Standards`.
- Manifest-driven packaging: every file listed in `manifest.json` must exist,
  have size > 0 matching `size`, and match `sha256`.
- Enforces required manifest metadata: `task_id`, `version`, `run_id`, `created_at` (ISO 8601 with timezone), and `files`.
- Uses an explicit recoverable multi-file transaction with a persistent transaction journal
  (`.tx_journal_*.json`) across `manifest.json`, `<zip_name>`, and `<zip_name>.sha256`
  (cross-file updates on OS filesystems are not natively atomic as a group; therefore pre-commit
  backups, staged temp files, per-file `os.replace`, and temp+replace rollback are enforced).
- Formal `output_directory` is strictly pinned to `.artifacts/packages/`.
- Computes external `<zip_name>.sha256` after ZIP creation and performs real
  extraction + SHA256 verification before committing targets.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable
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
    manifest_override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not source_acceptance.exists() or not source_acceptance.is_dir():
        raise FileNotFoundError(f"Acceptance directory not found: {source_acceptance}")
    illegal_zips = [
        z for z in source_acceptance.rglob("*.zip")
        if not (z.parent.name == "traces" and "trace" in z.name.lower())
    ]
    if illegal_zips:
        raise ValueError(f"Forbidden ZIP archive inside acceptance directory: {illegal_zips[0]}")

    if manifest_override is not None:
        manifest_data = manifest_override
    else:
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


def _default_unlink(path: Path) -> None:
    path.unlink()


def _cleanup_single_file(path: Path, do_unlink: Callable[[Path], None], errors: list[str]) -> None:
    if path.exists():
        try:
            do_unlink(path)
        except Exception as exc:
            errors.append(f"Failed to unlink {path}: {exc}")


def _cleanup_dir(dir_path: Path, do_unlink: Callable[[Path], None], errors: list[str]) -> None:
    if not dir_path.exists():
        return
    try:
        for root_dir, dirs, files in os.walk(dir_path, topdown=False):
            r_path = Path(root_dir)
            for fname in files:
                fpath = r_path / fname
                try:
                    do_unlink(fpath)
                except Exception as exc:
                    errors.append(f"Failed to unlink {fpath}: {exc}")
            for dname in dirs:
                dpath = r_path / dname
                try:
                    dpath.rmdir()
                except Exception as exc:
                    errors.append(f"Failed to rmdir {dpath}: {exc}")
        dir_path.rmdir()
    except Exception as exc:
        errors.append(f"Failed to remove dir {dir_path}: {exc}")


def _atomic_restore_file(
    backup_path: Path,
    target_path: Path,
    tmp_restore_path: Path,
    do_replace: Callable[[Path, Path], None],
) -> None:
    """Restore target_path from backup_path using a temp file and atomic replacement."""
    tmp_restore_path.write_bytes(backup_path.read_bytes())
    do_replace(tmp_restore_path, target_path)


def package_acceptance(
    task_id: str,
    version: str | None = None,
    run_id: str | None = None,
    repo_root: Path = REPO_ROOT,
    replace_fn: Callable[[Path, Path], None] | None = None,
    unlink_fn: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Execute recoverable multi-file transaction across manifest.json, ZIP, and .sha256 sidecar."""
    do_replace = replace_fn or os.replace
    do_unlink = unlink_fn or _default_unlink

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

    # Enforce non-silent validation of task_id and version in manifest before transaction starts
    if not manifest_data.get("task_id"):
        raise ValueError("Manifest missing required field: 'task_id'")
    if not manifest_data.get("version"):
        raise ValueError("Manifest missing required field: 'version'")

    if run_id and str(run_id).strip():
        effective_run_id = str(run_id).strip()
    else:
        existing_run_id = manifest_data.get("run_id")
        if isinstance(existing_run_id, str) and existing_run_id.strip():
            effective_run_id = existing_run_id.strip()
        else:
            effective_run_id = f"run-{int(time.time())}"

    pkg_dir = repo_root / ".artifacts" / "packages"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"Acceptance-{task_id}-{v_ver}.zip"
    zip_path = pkg_dir / zip_name
    sha_path = pkg_dir / f"{zip_name}.sha256"

    tx_id = f"{os.getpid()}_{int(time.time() * 1000)}"
    tmp_manifest = manifest_path.with_name(f".tmp_manifest_{tx_id}.json")
    tmp_zip = pkg_dir / f".tmp_{zip_name}_{tx_id}.zip"
    tmp_sha = pkg_dir / f".tmp_{zip_name}_{tx_id}.sha256"
    extract_dir = pkg_dir / f".verify_extract_{tx_id}"

    bak_manifest = manifest_path.with_name(f".bak_manifest_{tx_id}.json")
    bak_zip = pkg_dir / f".bak_{zip_name}_{tx_id}.zip"
    bak_sha = pkg_dir / f".bak_{zip_name}_{tx_id}.sha256"

    rst_manifest = manifest_path.with_name(f".tmp_restore_manifest_{tx_id}.json")
    rst_zip = pkg_dir / f".tmp_restore_{zip_name}_{tx_id}.zip"
    rst_sha = pkg_dir / f".tmp_restore_{zip_name}_{tx_id}.sha256"

    journal_path = pkg_dir / f".tx_journal_{task_id}_{v_ver}_{tx_id}.json"

    orig_manifest_existed = manifest_path.exists()
    orig_zip_existed = zip_path.exists()
    orig_sha_existed = sha_path.exists()

    journal_data: dict[str, Any] = {
        "tx_id": tx_id,
        "task_id": task_id,
        "version": v_ver,
        "run_id": effective_run_id,
        "state": "INITIALIZING",
        "orig_existed": {
            "manifest": orig_manifest_existed,
            "zip": orig_zip_existed,
            "sha": orig_sha_existed,
        },
        "targets": {
            "manifest": str(manifest_path),
            "zip": str(zip_path),
            "sha": str(sha_path),
        },
        "backups": {
            "manifest": str(bak_manifest),
            "zip": str(bak_zip),
            "sha": str(bak_sha),
        },
    }

    def _write_journal(state: str, **extra: Any) -> None:
        journal_data["state"] = state
        journal_data.update(extra)
        journal_path.write_text(json.dumps(journal_data, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        # 1. Back up pre-existing targets before staging/replacing any files
        if orig_manifest_existed:
            bak_manifest.write_bytes(manifest_path.read_bytes())
        if orig_zip_existed:
            bak_zip.write_bytes(zip_path.read_bytes())
        if orig_sha_existed:
            bak_sha.write_bytes(sha_path.read_bytes())
        _write_journal("BACKED_UP")

        # 2. Stage temporary manifest and validate all referenced files before touching targets
        staged_manifest = dict(manifest_data)
        staged_manifest["run_id"] = effective_run_id
        _, validated_entries = validate_acceptance_manifest(
            source_acceptance,
            expected_task_id=task_id,
            expected_version=v_ver,
            expected_run_id=effective_run_id,
            repo_root=repo_root,
            manifest_override=staged_manifest,
        )
        tmp_manifest.write_text(json.dumps(staged_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        # 3. Stage temporary ZIP
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_manifest, arcname="manifest.json")
            for item in validated_entries:
                zf.write(item["abs_path"], arcname=item["path"])

        # 4. Stage temporary Sidecar (.sha256)
        zip_sha = sha256_file(tmp_zip)
        tmp_sha.write_text(f"{zip_sha}  {zip_name}\n", encoding="utf-8")

        # 5. Real extraction + SHA256 verification from temporary ZIP before commit
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(tmp_zip, "r") as zf:
            zf.extractall(extract_dir)
        for item in validated_entries:
            ext_f = extract_dir / item["path"]
            if not ext_f.exists() or ext_f.stat().st_size != item["size"] or sha256_file(ext_f).lower() != item["sha256"]:
                raise ValueError(f"Extraction verification failed for {item['path']}")
        ext_m = extract_dir / "manifest.json"
        if not ext_m.exists() or sha256_file(ext_m).lower() != sha256_file(tmp_manifest).lower():
            raise ValueError("Extraction verification failed for manifest.json")
        verify_cleanup_errs: list[str] = []
        _cleanup_dir(extract_dir, do_unlink, verify_cleanup_errs)
        if verify_cleanup_errs:
            raise RuntimeError(f"TEMP_CLEANUP_FAILED during verification: {verify_cleanup_errs}")

        # 6. Commit all 3 targets via per-file atomic replace within recoverable transaction
        _write_journal("COMMITTING")
        do_replace(tmp_manifest, manifest_path)
        do_replace(tmp_zip, zip_path)
        do_replace(tmp_sha, sha_path)
        _write_journal("COMMITTED")

    except Exception as tx_exc:
        recovery_errors: list[str] = []
        cleanup_errors: list[str] = []

        try:
            _write_journal("ROLLING_BACK", error=str(tx_exc))
        except Exception:
            pass

        # Restore all 3 targets using temporary files and atomic replacement (never raw direct write)
        restore_specs = [
            ("manifest", orig_manifest_existed, bak_manifest, manifest_path, rst_manifest),
            ("zip", orig_zip_existed, bak_zip, zip_path, rst_zip),
            ("sha", orig_sha_existed, bak_sha, sha_path, rst_sha),
        ]
        for label, existed, bak_p, target_p, rst_p in restore_specs:
            try:
                if existed:
                    if not bak_p.exists():
                        raise FileNotFoundError(f"Missing backup file for {label}: {bak_p}")
                    _atomic_restore_file(bak_p, target_p, rst_p, do_replace)
                else:
                    if target_p.exists():
                        do_unlink(target_p)
            except Exception as rec_err:
                recovery_errors.append(f"{label}: {rec_err}")

        # Clean temporary staging / extraction files
        _cleanup_dir(extract_dir, do_unlink, cleanup_errors)
        for t_path in (tmp_manifest, tmp_zip, tmp_sha, rst_manifest, rst_zip, rst_sha):
            _cleanup_single_file(t_path, do_unlink, cleanup_errors)

        if recovery_errors:
            # Preserve backups and journal when recovery failed so manual recovery remains possible
            try:
                _write_journal("RECOVERY_FAILED", recovery_errors=recovery_errors, cleanup_errors=cleanup_errors)
            except Exception:
                pass
            raise RuntimeError(
                f"TRANSACTION_RECOVERY_FAILED: original={tx_exc}; recovery_errors={recovery_errors}; cleanup_errors={cleanup_errors}"
            ) from tx_exc

        # Recovery succeeded: remove backups and journal
        for b_path in (bak_manifest, bak_zip, bak_sha, journal_path):
            _cleanup_single_file(b_path, do_unlink, cleanup_errors)

        if cleanup_errors:
            try:
                _write_journal("ROLLED_BACK_CLEANUP_PENDING", cleanup_errors=cleanup_errors)
            except Exception:
                pass
            raise RuntimeError(
                f"TRANSACTION_ROLLED_BACK_CLEANUP_FAILED: original={tx_exc}; cleanup_errors={cleanup_errors}"
            ) from tx_exc

        raise

    # Post-commit cleanup of backups, any leftover temp files, and journal
    post_cleanup_errors: list[str] = []
    _cleanup_dir(extract_dir, do_unlink, post_cleanup_errors)
    for leftover in (tmp_manifest, tmp_zip, tmp_sha, rst_manifest, rst_zip, rst_sha, bak_manifest, bak_zip, bak_sha, journal_path):
        _cleanup_single_file(leftover, do_unlink, post_cleanup_errors)

    if post_cleanup_errors:
        try:
            _write_journal("COMMITTED_CLEANUP_PENDING", cleanup_errors=post_cleanup_errors)
        except Exception:
            pass
        raise RuntimeError(f"TEMP_CLEANUP_FAILED: {post_cleanup_errors}")

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
