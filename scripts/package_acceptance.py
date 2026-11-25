#!/usr/bin/env python3
# coding: utf-8
"""Unified Acceptance Evidence ZIP Packager for AI-Engineering-Standards (STD-016 / STD-019 / STD-020 / STD-034).

- Single authoritative acceptance packager for `AI-Engineering-Standards`.
- Strict path security: whitelisted `task_id` (`^[A-Za-z0-9_-]+$`), strict SemVer
  `version` (`^(v)?(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)$`), resolved containment checks
  under `repo_root/.artifacts/acceptance/` and `repo_root/.artifacts/packages/`, and explicit
  symlink rejection across all artifact path components.
- Per-(task_id, version) cross-process OS mutex lock (`msvcrt.locking` / `fcntl.flock`).
- Recoverable multi-file transaction across `manifest.json`, ZIP archive, and `.sha256` sidecar
  using durable pre-commit backups (`flush` + `os.fsync`), atomic journal updates
  (`.tx_journal_*.json` storing controlled relative paths only), extraction SHA-256 verification,
  temp+replace restoration on failure/crash, and startup crash recovery via
  `recover_incomplete_package_transactions()`.
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
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
SEMVER_STRICT_RE = re.compile(r"^(v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

FORBIDDEN_MANIFEST_ZIP_HASH_KEYS = {
    "zip_sha256",
    "package_sha256",
    "acceptance_zip_sha256",
    "final_zip_sha256",
    "archive_sha256",
}

VALID_JOURNAL_STATES = {
    "INITIALIZING",
    "BACKED_UP",
    "COMMITTING",
    "ROLLING_BACK",
    "RECOVERY_FAILED",
    "COMMITTED",
    "COMMITTED_CLEANUP_PENDING",
    "ROLLED_BACK_CLEANUP_PENDING",
}

_PKG_LOCK_DEPTH: dict[str, int] = {}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_task_id(task_id: Any) -> str:
    """Strictly validate task_id using an explicit safe-character whitelist."""
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("Invalid task_id: must be a non-empty string")
    if "\x00" in task_id or "/" in task_id or "\\" in task_id or ".." in task_id or ":" in task_id:
        raise ValueError(f"Forbidden path characters in task_id: {task_id!r}")
    if task_id != task_id.strip() or not TASK_ID_RE.fullmatch(task_id):
        raise ValueError(
            f"Invalid task_id {task_id!r}: only ASCII letters, digits, hyphens, and underscores are allowed"
        )
    return task_id


def _ensure_no_symlink_in_chain(target_path: Path, stop_ancestor: Path) -> None:
    """Reject any symlink along the path from stop_ancestor down to target_path (and target itself)."""
    try:
        resolved_stop = stop_ancestor.resolve(strict=False)
    except Exception as exc:
        raise ValueError(f"Cannot resolve boundary directory {stop_ancestor}: {exc}") from exc

    if stop_ancestor.exists() and stop_ancestor.is_symlink():
        raise ValueError(f"Symlink prohibited at boundary directory: {stop_ancestor}")

    raw_abs = Path(os.path.abspath(str(target_path)))
    stop_abs = Path(os.path.abspath(str(stop_ancestor)))
    base_dir: Path | None = None
    try:
        rel_parts = raw_abs.relative_to(stop_abs).parts
        base_dir = stop_abs
    except ValueError as exc:
        # Handle Windows 8.3 short paths (e.g. RUNNER~1 vs runneradmin) without accepting symlinked ancestors
        for cand in [raw_abs, *raw_abs.parents]:
            try:
                if cand.resolve(strict=False) == resolved_stop:
                    if cand.exists() and cand.is_symlink():
                        raise ValueError(f"Symlink prohibited at boundary directory: {cand}")
                    base_dir = cand
                    rel_parts = raw_abs.relative_to(cand).parts
                    break
            except ValueError:
                raise
            except Exception:
                continue
        if base_dir is None:
            raise ValueError(f"Path outside boundary {stop_ancestor}: {target_path}") from exc

    cur = base_dir
    if cur.exists() and cur.is_symlink():
        raise ValueError(f"Symlink prohibited in path: {cur}")
    for part in rel_parts:
        cur = cur / part
        if cur.exists() and cur.is_symlink():
            raise ValueError(f"Symlink prohibited in controlled artifact path: {cur}")

    resolved_target = target_path.resolve(strict=False)
    try:
        resolved_target.relative_to(resolved_stop)
    except ValueError as exc:
        raise ValueError(f"Resolved path escapes boundary {resolved_stop}: {resolved_target}") from exc


def _resolve_repo_and_boundaries(repo_root: Path) -> tuple[Path, Path, Path, Path]:
    """Resolve repo_root and verify .artifacts/, acceptance/, packages/ boundaries have no symlink escapes."""
    resolved_root = Path(repo_root).resolve(strict=False)
    artifacts_dir = resolved_root / ".artifacts"
    if artifacts_dir.exists() and artifacts_dir.is_symlink():
        raise ValueError(f"Symlink prohibited at artifacts directory: {artifacts_dir}")
    acc_base = artifacts_dir / "acceptance"
    pkg_dir = artifacts_dir / "packages"
    _ensure_no_symlink_in_chain(acc_base, resolved_root)
    _ensure_no_symlink_in_chain(pkg_dir, resolved_root)
    return (
        resolved_root,
        artifacts_dir.resolve(strict=False),
        acc_base.resolve(strict=False),
        pkg_dir.resolve(strict=False),
    )


def normalize_version(version: str | None, repo_root: Path = REPO_ROOT) -> tuple[str, str]:
    """Validate strict SemVer MAJOR.MINOR.PATCH (optionally prefixed with 'v')."""
    if version is None:
        resolved_root = Path(repo_root).resolve(strict=False)
        v_file = resolved_root / "VERSION"
        _ensure_no_symlink_in_chain(v_file, resolved_root)
        if not v_file.exists():
            raise ValueError(f"VERSION file not found in {resolved_root} and no --version provided")
        version = v_file.read_text(encoding="utf-8-sig").strip()

    if not isinstance(version, str) or not version:
        raise ValueError("Invalid version: must be a non-empty SemVer string")
    if "\x00" in version or "/" in version or "\\" in version or ".." in version or ":" in version:
        raise ValueError(f"Forbidden characters in version: {version!r}")
    if version != version.strip():
        raise ValueError(f"Invalid version whitespace: {version!r}")
    m = SEMVER_STRICT_RE.fullmatch(version)
    if not m:
        raise ValueError(
            f"Invalid SemVer version {version!r}: expected MAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH"
        )
    raw_ver = f"{m.group(2)}.{m.group(3)}.{m.group(4)}"
    return raw_ver, f"v{raw_ver}"


def _write_bytes_durable(path: Path, data: bytes) -> None:
    """Write bytes and flush + fsync to disk for crash durability."""
    with path.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _os_lock_file(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b" ")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
    except (OSError, IOError, PermissionError):
        return False


def _os_unlock_file(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
    except Exception:
        pass


def _acquire_package_lock(
    pkg_dir: Path,
    task_id: str,
    v_ver: str,
    tx_id: str,
    timeout: float = 30.0,
) -> tuple[int | None, Path]:
    """Acquire cross-process OS-level exclusive lock for (task_id, v_ver) inside pkg_dir/locks/."""
    locks_dir = pkg_dir / "locks"
    _ensure_no_symlink_in_chain(locks_dir, pkg_dir)
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{task_id}_{v_ver}.lock"
    _ensure_no_symlink_in_chain(lock_path, pkg_dir)
    key = str(lock_path.resolve(strict=False))

    if _PKG_LOCK_DEPTH.get(key, 0) > 0:
        _PKG_LOCK_DEPTH[key] += 1
        return None, lock_path

    start = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        except Exception as exc:
            if time.monotonic() - start >= timeout:
                raise RuntimeError(f"TRANSACTION_LOCK_ERROR: Failed opening {lock_path}: {exc}") from exc
            time.sleep(0.05)
            continue

        if not _os_lock_file(fd):
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, 2048).decode("utf-8", errors="replace").strip()
            except Exception:
                raw = ""
            try:
                os.close(fd)
            except Exception:
                pass
            if time.monotonic() - start >= timeout:
                raise RuntimeError(
                    f"TRANSACTION_CONCURRENCY_BLOCKED: Another packaging or recovery process holds {lock_path.name} ({raw})"
                )
            time.sleep(0.05)
            continue

        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            holder = json.dumps({"pid": os.getpid(), "tx_id": tx_id, "task_id": task_id, "version": v_ver}) + "\n"
            os.write(fd, holder.encode("utf-8"))
            os.fsync(fd)
            _PKG_LOCK_DEPTH[key] = 1
            return fd, lock_path
        except Exception as exc:
            _os_unlock_file(fd)
            try:
                os.close(fd)
            except Exception:
                pass
            raise RuntimeError(f"TRANSACTION_LOCK_ERROR: Failed writing lock metadata: {exc}") from exc


def _release_package_lock(lock_path: Path, fd: int | None) -> None:
    key = str(lock_path.resolve(strict=False))
    depth = _PKG_LOCK_DEPTH.get(key, 0)
    if depth > 1:
        _PKG_LOCK_DEPTH[key] = depth - 1
        return
    _PKG_LOCK_DEPTH[key] = 0
    if fd is not None:
        try:
            os.ftruncate(fd, 0)
            os.fsync(fd)
        except Exception:
            pass
        _os_unlock_file(fd)
        try:
            os.close(fd)
        except Exception:
            pass


def _validate_journal_rel_path(
    rel_val: Any,
    resolved_root: Path,
    expected_parent: Path,
    expected_name: str | None = None,
) -> Path:
    """Strictly validate relative paths read from a transaction journal."""
    if not isinstance(rel_val, str) or not rel_val.strip():
        raise ValueError(f"JOURNAL_INVALID_PATH: Empty or non-string path {rel_val!r}")
    raw = rel_val.strip()
    if "\x00" in raw or raw.startswith("/") or raw.startswith("\\"):
        raise ValueError(f"JOURNAL_ABSOLUTE_PATH_FORBIDDEN: {raw!r}")
    if re.match(r"^[a-zA-Z]:", raw) or raw.startswith("//") or raw.startswith("\\\\"):
        raise ValueError(f"JOURNAL_DRIVE_OR_UNC_FORBIDDEN: {raw!r}")
    p = Path(raw)
    if p.is_absolute():
        raise ValueError(f"JOURNAL_ABSOLUTE_PATH_FORBIDDEN: {raw!r}")
    for part in p.parts:
        if part in ("..", ".", ""):
            raise ValueError(f"JOURNAL_TRAVERSAL_FORBIDDEN: {raw!r}")

    candidate = resolved_root / p
    _ensure_no_symlink_in_chain(candidate, expected_parent)
    resolved_candidate = candidate.resolve(strict=False)
    resolved_parent = expected_parent.resolve(strict=False)
    if resolved_candidate.parent != resolved_parent:
        raise ValueError(
            f"JOURNAL_PATH_BOUNDARY_VIOLATION: {resolved_candidate} not directly under {resolved_parent}"
        )
    if expected_name is not None and resolved_candidate.name != expected_name:
        raise ValueError(
            f"JOURNAL_FILENAME_MISMATCH: expected {expected_name!r}, got {resolved_candidate.name!r}"
        )
    return resolved_candidate


def validate_acceptance_manifest(
    source_acceptance: Path,
    expected_task_id: str | None = None,
    expected_version: str | None = None,
    expected_run_id: str | None = None,
    repo_root: Path = REPO_ROOT,
    manifest_override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved_root, _, acc_base, _ = _resolve_repo_and_boundaries(repo_root)
    if expected_task_id is not None:
        validate_task_id(expected_task_id)
    if expected_version is not None:
        normalize_version(expected_version, resolved_root)

    _ensure_no_symlink_in_chain(source_acceptance, acc_base)
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
        _ensure_no_symlink_in_chain(manifest_path, source_acceptance)
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json not found in {source_acceptance}")
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))

    if not isinstance(manifest_data, dict):
        raise ValueError("manifest.json root must be a JSON object")

    for k in FORBIDDEN_MANIFEST_ZIP_HASH_KEYS:
        if k in manifest_data and manifest_data[k]:
            raise ValueError(f"Manifest must not contain final ZIP SHA256 self-reference key: {k}")

    # Required field: task_id (must also satisfy whitelist format)
    task_id = manifest_data.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("Manifest missing required field: 'task_id'")
    validate_task_id(task_id)
    if expected_task_id and task_id != expected_task_id:
        raise ValueError(f"Manifest task_id mismatch: '{task_id}' != expected '{expected_task_id}'")

    # Required field: version (strict SemVer)
    version = manifest_data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Manifest missing required field: 'version'")
    _, act_v = normalize_version(version, resolved_root)
    if expected_version:
        _, exp_v = normalize_version(expected_version, resolved_root)
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

    resolved_acc = source_acceptance.resolve()
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

        raw_entry_path = source_acceptance / norm_rel
        _ensure_no_symlink_in_chain(raw_entry_path, source_acceptance)
        src_file = raw_entry_path.resolve()
        try:
            src_file.relative_to(resolved_acc)
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
    """Restore target_path from backup_path using a durable temp file and atomic replacement."""
    _write_bytes_durable(tmp_restore_path, backup_path.read_bytes())
    do_replace(tmp_restore_path, target_path)


def _write_journal_atomic(
    journal_path: Path,
    tmp_journal_path: Path,
    journal_data: dict[str, Any],
    do_replace: Callable[[Path, Path], None],
) -> None:
    payload = (json.dumps(journal_data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _write_bytes_durable(tmp_journal_path, payload)
    do_replace(tmp_journal_path, journal_path)


def _recover_single_journal(
    journal_path: Path,
    resolved_root: Path,
    acc_base: Path,
    pkg_dir: Path,
    do_replace: Callable[[Path, Path], None],
    do_unlink: Callable[[Path], None],
    tx_tag: str,
) -> dict[str, Any]:
    """Recover one incomplete transaction from its journal; fail closed on corruption/mismatch."""
    try:
        j_raw = journal_path.read_text(encoding="utf-8")
        jdata = json.loads(j_raw)
        if not isinstance(jdata, dict):
            raise ValueError("Journal root must be a JSON object")
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "reason": f"CORRUPT_JOURNAL: Cannot parse {journal_path.name}: {exc}",
            "journal": journal_path.name,
        }

    req_keys = ("tx_id", "task_id", "version", "run_id", "state", "orig_existed", "orig_sha256", "targets", "backups")
    missing = [k for k in req_keys if k not in jdata]
    if missing:
        return {
            "status": "BLOCKED",
            "reason": f"CORRUPT_JOURNAL: Missing required fields {missing} in {journal_path.name}",
            "journal": journal_path.name,
        }

    state = jdata.get("state")
    if state not in VALID_JOURNAL_STATES:
        return {
            "status": "BLOCKED",
            "reason": f"CORRUPT_JOURNAL: Unknown transaction state {state!r}",
            "journal": journal_path.name,
        }

    try:
        j_task_id = validate_task_id(jdata["task_id"])
        _, j_ver = normalize_version(jdata["version"], resolved_root)
        j_tx_id = str(jdata["tx_id"])
        if not re.fullmatch(r"^[A-Za-z0-9_-]+$", j_tx_id):
            raise ValueError(f"Invalid tx_id in journal: {j_tx_id!r}")
        expected_jname = f".tx_journal_{j_task_id}_{j_ver}.json"
        if journal_path.name != expected_jname:
            raise ValueError(f"Journal filename mismatch: {journal_path.name} != {expected_jname}")

        zip_name = f"Acceptance-{j_task_id}-{j_ver}.zip"
        expected_acc_dir = (acc_base / j_task_id / j_ver).resolve(strict=False)

        targets = jdata["targets"]
        backups = jdata["backups"]
        if not isinstance(targets, dict) or not isinstance(backups, dict):
            raise ValueError("targets and backups must be dicts")

        t_manifest = _validate_journal_rel_path(targets.get("manifest"), resolved_root, expected_acc_dir, "manifest.json")
        t_zip = _validate_journal_rel_path(targets.get("zip"), resolved_root, pkg_dir, zip_name)
        t_sha = _validate_journal_rel_path(targets.get("sha"), resolved_root, pkg_dir, f"{zip_name}.sha256")

        b_manifest = _validate_journal_rel_path(
            backups.get("manifest"), resolved_root, pkg_dir, f".bak_manifest_{j_task_id}_{j_ver}_{j_tx_id}.json"
        )
        b_zip = _validate_journal_rel_path(
            backups.get("zip"), resolved_root, pkg_dir, f".bak_{zip_name}_{j_tx_id}.zip"
        )
        b_sha = _validate_journal_rel_path(
            backups.get("sha"), resolved_root, pkg_dir, f".bak_{zip_name}_{j_tx_id}.sha256"
        )
        has_audit_tx = "audit" in targets or "audit" in backups
        t_audit: Path | None = None
        b_audit: Path | None = None
        if has_audit_tx:
            t_audit = _validate_journal_rel_path(targets.get("audit"), resolved_root, pkg_dir, "overwrite_audit.jsonl")
            b_audit = _validate_journal_rel_path(
                backups.get("audit"), resolved_root, pkg_dir, f".bak_audit_{j_task_id}_{j_ver}_{j_tx_id}.jsonl"
            )
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "reason": f"CORRUPT_OR_MALICIOUS_JOURNAL: {exc}",
            "journal": journal_path.name,
        }

    orig_existed = jdata["orig_existed"]
    orig_sha = jdata["orig_sha256"]
    bak_sha = jdata.get("backup_sha256") or {}
    staged_sha = jdata.get("staged_sha256") or {}

    tmp_journal = pkg_dir / f".tx_journal_tmp_{j_task_id}_{j_ver}_{tx_tag}.json"
    rst_manifest = pkg_dir / f".tmp_restore_manifest_{j_task_id}_{j_ver}_{tx_tag}.json"
    rst_zip = pkg_dir / f".tmp_restore_{zip_name}_{tx_tag}.zip"
    rst_sha = pkg_dir / f".tmp_restore_{zip_name}_{tx_tag}.sha256"
    rst_audit = pkg_dir / f".tmp_restore_audit_{j_task_id}_{j_ver}_{tx_tag}.jsonl"

    if state == "RECOVERY_FAILED":
        return {
            "status": "BLOCKED",
            "state": "RECOVERY_FAILED",
            "reason": "RECOVERY_FAILED: Prior transaction recovery failed; backups and journal preserved for manual intervention",
            "journal": journal_path.name,
        }

    def _clean_tx_artifacts(include_backups_and_journal: bool = True) -> list[str]:
        errs: list[str] = []
        # Clean matching staged/temp artifacts for this task/version/tx
        patterns = [
            f".tmp_manifest_{j_task_id}_{j_ver}_*",
            f".tmp_{zip_name}_*",
            f".tmp_audit_{j_task_id}_{j_ver}_*",
            f".tmp_restore_manifest_{j_task_id}_{j_ver}_*",
            f".tmp_restore_{zip_name}_*",
            f".tmp_restore_audit_{j_task_id}_{j_ver}_*",
            f".tx_journal_tmp_{j_task_id}_{j_ver}_*",
        ]
        for pat in patterns:
            for p in pkg_dir.glob(pat):
                _cleanup_single_file(p, do_unlink, errs)
        for ed in pkg_dir.glob(f".verify_extract_{j_task_id}_{j_ver}_*"):
            _cleanup_dir(ed, do_unlink, errs)
        if include_backups_and_journal:
            to_clean = [b_manifest, b_zip, b_sha, journal_path]
            if b_audit is not None:
                to_clean.append(b_audit)
            for p in to_clean:
                _cleanup_single_file(p, do_unlink, errs)
        return errs

    target_triples: list[tuple[str, Path, Path, Path]] = [
        ("manifest", t_manifest, b_manifest, rst_manifest),
        ("zip", t_zip, b_zip, rst_zip),
        ("sha", t_sha, b_sha, rst_sha),
    ]
    if t_audit is not None and b_audit is not None:
        target_triples.append(("audit", t_audit, b_audit, rst_audit))

    # Case 1: INITIALIZING (crash happened before backups were completed or targets were touched)
    if state == "INITIALIZING":
        for label, t_path, _, _ in target_triples:
            ex = bool(orig_existed.get(label))
            exp_h = orig_sha.get(label)
            if ex:
                if not t_path.exists() or sha256_file(t_path) != exp_h:
                    return {
                        "status": "BLOCKED",
                        "reason": f"INCONSISTENT_INITIALIZING_STATE: {label} modified unexpectedly during INITIALIZING",
                        "journal": journal_path.name,
                    }
            elif t_path.exists():
                return {
                    "status": "BLOCKED",
                    "reason": f"INCONSISTENT_INITIALIZING_STATE: unexpected target {label} exists during INITIALIZING",
                    "journal": journal_path.name,
                }
        errs = _clean_tx_artifacts(include_backups_and_journal=True)
        if errs:
            return {"status": "BLOCKED", "reason": f"RECOVERY_CLEANUP_FAILED: {errs}", "journal": journal_path.name}
        return {"status": "RECOVERED", "action": "CLEANED_INITIALIZING", "journal": journal_path.name}

    # Case 2: COMMITTED / COMMITTED_CLEANUP_PENDING -> verify all committed targets & identities strictly, then clean backups
    if state in ("COMMITTED", "COMMITTED_CLEANUP_PENDING"):
        for label, t_path, _, _ in target_triples:
            exp_h = staged_sha.get(label)
            if not exp_h or not t_path.exists() or sha256_file(t_path) != exp_h:
                return {
                    "status": "BLOCKED",
                    "reason": f"COMMITTED_STATE_MISMATCH: target {label} missing or SHA256 mismatch with journal",
                    "journal": journal_path.name,
                }
        # Also verify sidecar points to exact zip hash
        expected_zip_h = staged_sha.get("zip")
        if f"{expected_zip_h}  {zip_name}" not in t_sha.read_text(encoding="utf-8"):
            return {
                "status": "BLOCKED",
                "reason": "COMMITTED_STATE_MISMATCH: sidecar content does not match committed ZIP SHA256",
                "journal": journal_path.name,
            }
        if jdata.get("overwrite_authorized"):
            if t_audit is None or not t_audit.exists():
                return {
                    "status": "BLOCKED",
                    "reason": "COMMITTED_AUDIT_IDENTITY_MISMATCH: authorized overwrite missing durable audit record",
                    "journal": journal_path.name,
                }
            audit_matched = False
            for a_line in t_audit.read_text(encoding="utf-8").splitlines():
                if not a_line.strip():
                    continue
                try:
                    a_rec = json.loads(a_line)
                except Exception:
                    continue
                if (
                    a_rec.get("tx_id") == j_tx_id
                    and a_rec.get("previous_zip_sha256") == orig_sha.get("zip")
                    and a_rec.get("new_zip_sha256") == staged_sha.get("zip")
                    and a_rec.get("previous_manifest_sha256") == orig_sha.get("manifest")
                    and a_rec.get("new_manifest_sha256") == staged_sha.get("manifest")
                ):
                    audit_matched = True
                    break
            if not audit_matched:
                return {
                    "status": "BLOCKED",
                    "reason": "COMMITTED_AUDIT_IDENTITY_MISMATCH: audit file does not verify original and new file identities",
                    "journal": journal_path.name,
                }
        errs = _clean_tx_artifacts(include_backups_and_journal=True)
        if errs:
            return {"status": "BLOCKED", "reason": f"COMMITTED_CLEANUP_FAILED: {errs}", "journal": journal_path.name}
        return {"status": "RECOVERED", "action": "VERIFIED_COMMITTED_AND_CLEANED", "journal": journal_path.name}

    # Case 3: Uncommitted transaction (BACKED_UP / COMMITTING / ROLLING_BACK / ROLLED_BACK_CLEANUP_PENDING)
    # Verify all required backups exist and match recorded backup_sha256 BEFORE touching any target
    for label, _, b_path, _ in target_triples:
        if orig_existed.get(label):
            exp_bh = bak_sha.get(label) or orig_sha.get(label)
            if not b_path.exists() or not exp_bh or sha256_file(b_path) != exp_bh:
                return {
                    "status": "BLOCKED",
                    "reason": f"BACKUP_MISSING_OR_CORRUPT: Cannot safely restore {label}; backup missing or checksum mismatch",
                    "journal": journal_path.name,
                }

    if state != "ROLLED_BACK_CLEANUP_PENDING":
        try:
            jdata["state"] = "ROLLING_BACK"
            _write_journal_atomic(journal_path, tmp_journal, jdata, do_replace)
        except Exception as exc:
            return {
                "status": "BLOCKED",
                "reason": f"RECOVERY_JOURNAL_WRITE_FAILED: {exc}",
                "journal": journal_path.name,
            }

        rec_errors: list[str] = []
        for label, t_path, b_path, rst_path in target_triples:
            try:
                if orig_existed.get(label):
                    _atomic_restore_file(b_path, t_path, rst_path, do_replace)
                else:
                    if t_path.exists():
                        do_unlink(t_path)
            except Exception as exc:
                rec_errors.append(f"{label}: {exc}")

        if rec_errors:
            try:
                jdata["state"] = "RECOVERY_FAILED"
                jdata["recovery_errors"] = rec_errors
                _write_journal_atomic(journal_path, tmp_journal, jdata, do_replace)
            except Exception:
                pass
            return {
                "status": "BLOCKED",
                "state": "RECOVERY_FAILED",
                "reason": f"RECOVERY_FAILED: {rec_errors}",
                "journal": journal_path.name,
            }

    # Verify post-restore state matches orig_existed & orig_sha256
    for label, t_path, _, _ in target_triples:
        if orig_existed.get(label):
            if not t_path.exists() or sha256_file(t_path) != orig_sha.get(label):
                return {
                    "status": "BLOCKED",
                    "state": "RECOVERY_FAILED",
                    "reason": f"RECOVERY_FAILED: restored {label} checksum mismatch with original",
                    "journal": journal_path.name,
                }
        elif t_path.exists():
            return {
                "status": "BLOCKED",
                "state": "RECOVERY_FAILED",
                "reason": f"RECOVERY_FAILED: {label} still exists after rollback",
                "journal": journal_path.name,
            }

    try:
        jdata["state"] = "ROLLED_BACK_CLEANUP_PENDING"
        _write_journal_atomic(journal_path, tmp_journal, jdata, do_replace)
    except Exception:
        pass

    errs = _clean_tx_artifacts(include_backups_and_journal=True)
    if errs:
        return {
            "status": "BLOCKED",
            "reason": f"ROLLED_BACK_CLEANUP_FAILED: targets restored, cleanup failed: {errs}",
            "journal": journal_path.name,
        }
    return {"status": "RECOVERED", "action": "ROLLED_BACK_TO_ORIGINAL", "journal": journal_path.name}


def recover_incomplete_package_transactions(
    repo_root: Path = REPO_ROOT,
    task_id: str | None = None,
    version: str | None = None,
    replace_fn: Callable[[Path, Path], None] | None = None,
    unlink_fn: Callable[[Path], None] | None = None,
    lock_timeout: float = 15.0,
) -> dict[str, Any]:
    """Startup & standalone crash recovery entry point for incomplete Acceptance packaging transactions."""
    do_replace = replace_fn or os.replace
    do_unlink = unlink_fn or _default_unlink

    resolved_root, _, acc_base, pkg_dir = _resolve_repo_and_boundaries(repo_root)
    if task_id is not None:
        validate_task_id(task_id)
    v_ver: str | None = None
    if version is not None:
        _, v_ver = normalize_version(version, resolved_root)

    if not pkg_dir.exists():
        return {"status": "CLEAN", "recovered": [], "blocked": []}

    tx_tag = f"rec_{os.getpid()}_{int(time.time() * 1000)}"

    if task_id is not None and v_ver is not None:
        lock_fd, lock_path = _acquire_package_lock(pkg_dir, task_id, v_ver, tx_tag, timeout=lock_timeout)
        try:
            journal_path = pkg_dir / f".tx_journal_{task_id}_{v_ver}.json"
            zip_name = f"Acceptance-{task_id}-{v_ver}.zip"
            if journal_path.exists():
                res = _recover_single_journal(journal_path, resolved_root, acc_base, pkg_dir, do_replace, do_unlink, tx_tag)
                if res["status"] == "BLOCKED":
                    return {"status": "BLOCKED", "reason": res["reason"], "recovered": [], "blocked": [res]}
                return {"status": "RECOVERED", "recovered": [res], "blocked": []}

            # No main journal: check for orphan backups / staged files for this task/version
            orphan_baks = (
                list(pkg_dir.glob(f".bak_manifest_{task_id}_{v_ver}_*"))
                + list(pkg_dir.glob(f".bak_{zip_name}_*"))
                + list(pkg_dir.glob(f".bak_audit_{task_id}_{v_ver}_*"))
                + list(pkg_dir.glob(f".tmp_manifest_{task_id}_{v_ver}_*"))
                + list(pkg_dir.glob(f".tmp_{zip_name}_*"))
                + list(pkg_dir.glob(f".tmp_audit_{task_id}_{v_ver}_*"))
                + list(pkg_dir.glob(f".tmp_restore_manifest_{task_id}_{v_ver}_*"))
                + list(pkg_dir.glob(f".tmp_restore_{zip_name}_*"))
                + list(pkg_dir.glob(f".tmp_restore_audit_{task_id}_{v_ver}_*"))
            )
            orphan_jtmps = list(pkg_dir.glob(f".tx_journal_tmp_{task_id}_{v_ver}_*"))
            if orphan_baks:
                return {
                    "status": "BLOCKED",
                    "reason": f"ORPHAN_TRANSACTION_ARTIFACTS_WITHOUT_JOURNAL: {[p.name for p in orphan_baks]}",
                    "recovered": [],
                    "blocked": [{"artifacts": [p.name for p in orphan_baks]}],
                }
            if orphan_jtmps:
                # Initial journal write interrupted BEFORE any backups or staging occurred -> safe cleanup
                c_errs: list[str] = []
                for p in orphan_jtmps:
                    _cleanup_single_file(p, do_unlink, c_errs)
                if c_errs:
                    return {"status": "BLOCKED", "reason": f"CLEANUP_FAILED: {c_errs}", "recovered": [], "blocked": [c_errs]}
                return {"status": "RECOVERED", "recovered": [{"action": "CLEANED_PRE_BACKUP_JOURNAL_TMP"}], "blocked": []}
            return {"status": "CLEAN", "recovered": [], "blocked": []}
        finally:
            _release_package_lock(lock_path, lock_fd)

    # Global scan across .artifacts/packages
    recovered: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    journals = sorted(p for p in pkg_dir.glob(".tx_journal_*.json") if not p.name.startswith(".tx_journal_tmp_"))
    for j_path in journals:
        m = re.fullmatch(r"^\.tx_journal_([A-Za-z0-9_-]+)_(v\d+\.\d+\.\d+)\.json$", j_path.name)
        if not m:
            blocked.append({"status": "BLOCKED", "reason": f"CORRUPT_JOURNAL: Unexpected journal filename {j_path.name}"})
            continue
        jt_id, jv = m.group(1), m.group(2)
        lock_fd, lock_path = _acquire_package_lock(pkg_dir, jt_id, jv, tx_tag, timeout=lock_timeout)
        try:
            if not j_path.exists():
                continue
            res = _recover_single_journal(j_path, resolved_root, acc_base, pkg_dir, do_replace, do_unlink, tx_tag)
            if res["status"] == "BLOCKED":
                blocked.append(res)
            else:
                recovered.append(res)
        finally:
            _release_package_lock(lock_path, lock_fd)

    if not journals:
        # Check for orphan backups / staging files across pkg_dir when no journal exists
        orphans = (
            list(pkg_dir.glob(".bak_*"))
            + list(pkg_dir.glob(".tmp_manifest_*"))
            + list(pkg_dir.glob(".tmp_Acceptance-*"))
            + list(pkg_dir.glob(".tmp_audit_*"))
            + list(pkg_dir.glob(".tmp_restore_*"))
        )
        if orphans:
            blocked.append({
                "status": "BLOCKED",
                "reason": f"ORPHAN_TRANSACTION_ARTIFACTS_WITHOUT_JOURNAL: {[p.name for p in orphans]}",
            })
        else:
            jtmps = list(pkg_dir.glob(".tx_journal_tmp_*"))
            if jtmps:
                c_errs: list[str] = []
                for p in jtmps:
                    _cleanup_single_file(p, do_unlink, c_errs)
                if c_errs:
                    blocked.append({"status": "BLOCKED", "reason": f"CLEANUP_FAILED: {c_errs}"})
                else:
                    recovered.append({"action": "CLEANED_PRE_BACKUP_JOURNAL_TMP"})

    if blocked:
        return {"status": "BLOCKED", "reason": "; ".join(str(b.get("reason", b)) for b in blocked), "recovered": recovered, "blocked": blocked}
    if recovered:
        return {"status": "RECOVERED", "recovered": recovered, "blocked": []}
    return {"status": "CLEAN", "recovered": [], "blocked": []}


def _detect_existing_package_identities(
    pkg_dir: Path,
    zip_name: str,
    zip_path: Path,
    sha_path: Path,
) -> list[str]:
    """Detect existing historical Acceptance ZIP, sidecar, or checksum index entries."""
    identities: list[str] = []
    if zip_path.exists():
        identities.append(zip_name)
    if sha_path.exists():
        identities.append(sha_path.name)

    for sibling in sorted(pkg_dir.glob(f"{zip_name}.*")):
        if sibling.name.startswith(".") or sibling.name == sha_path.name:
            continue
        _ensure_no_symlink_in_chain(sibling, pkg_dir)
        identities.append(sibling.name)

    for index_name in ("CHECKSUMS.txt", "SHA256SUMS", "SHA256SUMS.txt"):
        index_path = pkg_dir / index_name
        if not index_path.exists() or not index_path.is_file():
            continue
        _ensure_no_symlink_in_chain(index_path, pkg_dir)
        try:
            content = index_path.read_text(encoding="utf-8-sig", errors="replace")
        except Exception:
            continue
        for line in content.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            for token in s.split():
                clean_tok = token.lstrip("*")
                if clean_tok in (zip_name, sha_path.name) or Path(clean_tok).name in (zip_name, sha_path.name):
                    identities.append(f"{index_name}:{zip_name}")
                    break
            else:
                continue
            break

    return identities


_FORBIDDEN_OVERWRITE_REASONS = {
    "",
    "explicit_allow_overwrite_flag",
    "--allow-overwrite",
    "allow-overwrite",
    "allow_overwrite",
    "overwrite",
    "default",
    "none",
    "n/a",
    "na",
    "null",
    "tbd",
    "todo",
    "test",
    "reason",
}


def _validate_overwrite_reason(overwrite_reason: str | None) -> str:
    """Validate that an authorized overwrite provides a real, non-empty, non-placeholder audit reason."""
    cleaned = str(overwrite_reason or "").strip()
    if len(cleaned) < 8 or cleaned.lower() in _FORBIDDEN_OVERWRITE_REASONS:
        raise ValueError(
            "ACCEPTANCE_PACKAGE_OVERWRITE_REASON_REQUIRED: Authorized overwrite requires a non-empty real "
            "task/audit reason (--overwrite-reason, min 8 chars, not a default flag label)."
        )
    return cleaned


def _append_overwrite_audit(pkg_dir: Path, record: dict[str, Any]) -> Path:
    """Append an authorized overwrite audit record durably under pkg_dir/overwrite_audit.jsonl."""
    audit_path = pkg_dir / "overwrite_audit.jsonl"
    _ensure_no_symlink_in_chain(audit_path, pkg_dir)
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with audit_path.open("ab") as f:
        f.write(payload)
        f.flush()
        if hasattr(os, "fsync"):
            os.fsync(f.fileno())
    return audit_path


def package_acceptance(
    task_id: str,
    version: str | None = None,
    run_id: str | None = None,
    repo_root: Path = REPO_ROOT,
    replace_fn: Callable[[Path, Path], None] | None = None,
    unlink_fn: Callable[[Path], None] | None = None,
    lock_timeout: float = 30.0,
    allow_overwrite: bool = False,
    overwrite_reason: str | None = None,
    audit_write_fn: Callable[[Path, bytes], None] | None = None,
) -> dict[str, Any]:
    """Execute recoverable, cross-process locked multi-file transaction across manifest.json, ZIP, .sha256 sidecar, and overwrite_audit.jsonl."""
    # Phase 0: Strict pre-flight input & path security validation BEFORE creating ANY directory or file
    validate_task_id(task_id)
    resolved_root, artifacts_dir, acc_base, pkg_dir = _resolve_repo_and_boundaries(repo_root)
    raw_ver, v_ver = normalize_version(version, resolved_root)

    source_acceptance = acc_base / task_id / v_ver
    _ensure_no_symlink_in_chain(source_acceptance, acc_base)
    if not source_acceptance.exists() or not source_acceptance.is_dir():
        raise FileNotFoundError(f"Acceptance directory not found: {source_acceptance}")

    manifest_path = source_acceptance / "manifest.json"
    _ensure_no_symlink_in_chain(manifest_path, source_acceptance)
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in {source_acceptance}")

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest_data, dict):
        raise ValueError("manifest.json root must be a JSON object")

    if not manifest_data.get("task_id"):
        raise ValueError("Manifest missing required field: 'task_id'")
    validate_task_id(manifest_data["task_id"])
    if not manifest_data.get("version"):
        raise ValueError("Manifest missing required field: 'version'")
    normalize_version(manifest_data["version"], resolved_root)

    if run_id and str(run_id).strip():
        effective_run_id = str(run_id).strip()
    else:
        existing_run_id = manifest_data.get("run_id")
        if isinstance(existing_run_id, str) and existing_run_id.strip():
            effective_run_id = existing_run_id.strip()
        else:
            effective_run_id = f"run-{int(time.time())}"

    do_replace = replace_fn or os.replace
    do_unlink = unlink_fn or _default_unlink
    do_audit_write = audit_write_fn or _write_bytes_durable

    # Ensure pkg_dir exists and check boundaries
    _ensure_no_symlink_in_chain(pkg_dir, resolved_root)
    pkg_dir.mkdir(parents=True, exist_ok=True)

    zip_name = f"Acceptance-{task_id}-{v_ver}.zip"
    zip_path = pkg_dir / zip_name
    sha_path = pkg_dir / f"{zip_name}.sha256"
    audit_path = pkg_dir / "overwrite_audit.jsonl"
    _ensure_no_symlink_in_chain(zip_path, pkg_dir)
    _ensure_no_symlink_in_chain(sha_path, pkg_dir)
    _ensure_no_symlink_in_chain(audit_path, pkg_dir)

    tx_id = f"{os.getpid()}_{int(time.time() * 1000)}"
    lock_fd, lock_path = _acquire_package_lock(pkg_dir, task_id, v_ver, tx_id, timeout=lock_timeout)

    try:
        # Step A: Startup crash recovery for any incomplete prior transaction on (task_id, v_ver)
        rec_res = recover_incomplete_package_transactions(
            repo_root=resolved_root,
            task_id=task_id,
            version=v_ver,
            replace_fn=do_replace,
            unlink_fn=do_unlink,
            lock_timeout=lock_timeout,
        )
        if rec_res.get("status") == "BLOCKED":
            raise RuntimeError(f"TRANSACTION_RECOVERY_BLOCKED: {rec_res.get('reason')}")

        # Re-read manifest_path in case startup recovery rolled back manifest.json to original!
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))

        # Enforce historical ZIP / sidecar / checksum identity protection inside transaction lock
        # AFTER crash recovery completes cleanly, BEFORE staging any backup or journal files.
        existing_identities = _detect_existing_package_identities(pkg_dir, zip_name, zip_path, sha_path)
        if existing_identities and not allow_overwrite:
            raise FileExistsError(
                f"ACCEPTANCE_PACKAGE_OVERWRITE_FORBIDDEN: Historical acceptance artifact(s) already exist for "
                f"({task_id}, {v_ver}): {', '.join(existing_identities)}. "
                f"Pass --allow-overwrite only with explicit task authorization."
            )
        overwritten = bool(existing_identities and allow_overwrite)
        effective_overwrite_reason = (
            _validate_overwrite_reason(overwrite_reason)
            if overwritten
            else None
        )

        # All temp, backup, restore, and journal files live inside pkg_dir (.artifacts/packages/)
        tmp_manifest = pkg_dir / f".tmp_manifest_{task_id}_{v_ver}_{tx_id}.json"
        tmp_zip = pkg_dir / f".tmp_{zip_name}_{tx_id}.zip"
        tmp_sha = pkg_dir / f".tmp_{zip_name}_{tx_id}.sha256"
        tmp_audit = pkg_dir / f".tmp_audit_{task_id}_{v_ver}_{tx_id}.jsonl"
        extract_dir = pkg_dir / f".verify_extract_{task_id}_{v_ver}_{tx_id}"

        bak_manifest = pkg_dir / f".bak_manifest_{task_id}_{v_ver}_{tx_id}.json"
        bak_zip = pkg_dir / f".bak_{zip_name}_{tx_id}.zip"
        bak_sha = pkg_dir / f".bak_{zip_name}_{tx_id}.sha256"
        bak_audit = pkg_dir / f".bak_audit_{task_id}_{v_ver}_{tx_id}.jsonl"

        rst_manifest = pkg_dir / f".tmp_restore_manifest_{task_id}_{v_ver}_{tx_id}.json"
        rst_zip = pkg_dir / f".tmp_restore_{zip_name}_{tx_id}.zip"
        rst_sha = pkg_dir / f".tmp_restore_{zip_name}_{tx_id}.sha256"
        rst_audit = pkg_dir / f".tmp_restore_audit_{task_id}_{v_ver}_{tx_id}.jsonl"

        journal_path = pkg_dir / f".tx_journal_{task_id}_{v_ver}.json"
        tmp_journal = pkg_dir / f".tx_journal_tmp_{task_id}_{v_ver}_{tx_id}.json"

        for p_check in (
            tmp_manifest, tmp_zip, tmp_sha, tmp_audit, extract_dir,
            bak_manifest, bak_zip, bak_sha, bak_audit,
            rst_manifest, rst_zip, rst_sha, rst_audit,
            journal_path, tmp_journal,
        ):
            _ensure_no_symlink_in_chain(p_check, pkg_dir)

        orig_manifest_bytes = manifest_path.read_bytes()
        orig_manifest_sha = sha256_bytes(orig_manifest_bytes)
        orig_zip_existed = zip_path.exists()
        orig_zip_bytes = zip_path.read_bytes() if orig_zip_existed else None
        orig_zip_sha = sha256_bytes(orig_zip_bytes) if orig_zip_bytes is not None else None
        orig_sha_existed = sha_path.exists()
        orig_sha_bytes = sha_path.read_bytes() if orig_sha_existed else None
        orig_sha_file_sha = sha256_bytes(orig_sha_bytes) if orig_sha_bytes is not None else None
        orig_audit_existed = audit_path.exists() if overwritten else False
        orig_audit_bytes = audit_path.read_bytes() if (overwritten and orig_audit_existed) else None
        orig_audit_sha = sha256_bytes(orig_audit_bytes) if orig_audit_bytes is not None else None

        rel_targets = {
            "manifest": f".artifacts/acceptance/{task_id}/{v_ver}/manifest.json",
            "zip": f".artifacts/packages/{zip_name}",
            "sha": f".artifacts/packages/{zip_name}.sha256",
        }
        rel_backups = {
            "manifest": f".artifacts/packages/{bak_manifest.name}",
            "zip": f".artifacts/packages/{bak_zip.name}",
            "sha": f".artifacts/packages/{bak_sha.name}",
        }
        orig_existed_map = {
            "manifest": True,
            "zip": orig_zip_existed,
            "sha": orig_sha_existed,
        }
        orig_sha_map = {
            "manifest": orig_manifest_sha,
            "zip": orig_zip_sha,
            "sha": orig_sha_file_sha,
        }
        if overwritten:
            rel_targets["audit"] = ".artifacts/packages/overwrite_audit.jsonl"
            rel_backups["audit"] = f".artifacts/packages/{bak_audit.name}"
            orig_existed_map["audit"] = orig_audit_existed
            orig_sha_map["audit"] = orig_audit_sha

        journal_data: dict[str, Any] = {
            "tx_id": tx_id,
            "task_id": task_id,
            "version": v_ver,
            "run_id": effective_run_id,
            "state": "INITIALIZING",
            "overwrite_authorized": overwritten,
            "overwrite_reason": effective_overwrite_reason,
            "existing_identities": existing_identities,
            "orig_existed": orig_existed_map,
            "orig_sha256": orig_sha_map,
            "backup_sha256": {},
            "staged_sha256": {},
            "targets": rel_targets,
            "backups": rel_backups,
        }

        overwrite_audit: dict[str, Any] | None = None
        staged_audit_bytes: bytes | None = None

        try:
            # 1. Atomically record INITIALIZING journal BEFORE writing backups
            _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)

            # 2. Durable backups (flush + fsync) + record BACKED_UP journal
            _write_bytes_durable(bak_manifest, orig_manifest_bytes)
            bak_hashes: dict[str, str | None] = {
                "manifest": sha256_bytes(orig_manifest_bytes),
                "zip": None,
                "sha": None,
            }
            if orig_zip_bytes is not None:
                _write_bytes_durable(bak_zip, orig_zip_bytes)
                bak_hashes["zip"] = sha256_bytes(orig_zip_bytes)
            if orig_sha_bytes is not None:
                _write_bytes_durable(bak_sha, orig_sha_bytes)
                bak_hashes["sha"] = sha256_bytes(orig_sha_bytes)
            if overwritten:
                bak_hashes["audit"] = None
                if orig_audit_bytes is not None:
                    _write_bytes_durable(bak_audit, orig_audit_bytes)
                    bak_hashes["audit"] = sha256_bytes(orig_audit_bytes)

            journal_data["backup_sha256"] = bak_hashes
            journal_data["state"] = "BACKED_UP"
            _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)

            # 3. Stage temporary manifest & validate all referenced files
            staged_manifest = dict(manifest_data)
            staged_manifest["run_id"] = effective_run_id
            _, validated_entries = validate_acceptance_manifest(
                source_acceptance,
                expected_task_id=task_id,
                expected_version=v_ver,
                expected_run_id=effective_run_id,
                repo_root=resolved_root,
                manifest_override=staged_manifest,
            )
            staged_manifest_bytes = (json.dumps(staged_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            _write_bytes_durable(tmp_manifest, staged_manifest_bytes)

            # 4. Stage temporary ZIP and fsync on writable handle (required on Windows)
            with tmp_zip.open("wb") as f_z:
                with zipfile.ZipFile(f_z, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(tmp_manifest, arcname="manifest.json")
                    for item in validated_entries:
                        zf.write(item["abs_path"], arcname=item["path"])
                f_z.flush()
                if hasattr(os, "fsync"):
                    os.fsync(f_z.fileno())

            # 5. Stage temporary Sidecar (.sha256) durably
            zip_sha = sha256_file(tmp_zip)
            staged_sha_bytes = f"{zip_sha}  {zip_name}\n".encode("utf-8")
            _write_bytes_durable(tmp_sha, staged_sha_bytes)

            # 6. Real extraction + SHA256 verification before committing
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(extract_dir)
            for item in validated_entries:
                ext_f = extract_dir / item["path"]
                if not ext_f.exists() or ext_f.stat().st_size != item["size"] or sha256_file(ext_f).lower() != item["sha256"]:
                    raise ValueError(f"Extraction verification failed for {item['path']}")
            ext_m = extract_dir / "manifest.json"
            if not ext_m.exists() or sha256_file(ext_m).lower() != sha256_bytes(staged_manifest_bytes).lower():
                raise ValueError("Extraction verification failed for manifest.json")
            verify_cleanup_errs: list[str] = []
            _cleanup_dir(extract_dir, do_unlink, verify_cleanup_errs)
            if verify_cleanup_errs:
                raise RuntimeError(f"TEMP_CLEANUP_FAILED during verification: {verify_cleanup_errs}")

            # 6b. Stage overwrite audit record inside transaction boundary BEFORE COMMITTING
            staged_hashes: dict[str, str | None] = {
                "manifest": sha256_bytes(staged_manifest_bytes),
                "zip": zip_sha,
                "sha": sha256_bytes(staged_sha_bytes),
            }
            if overwritten:
                overwrite_audit = {
                    "task_id": task_id,
                    "version": v_ver,
                    "run_id": effective_run_id,
                    "tx_id": tx_id,
                    "overwritten_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "reason": effective_overwrite_reason,
                    "existing_identities": existing_identities,
                    "previous_zip_sha256": orig_zip_sha,
                    "new_zip_sha256": zip_sha,
                    "previous_sha256_sidecar_sha256": orig_sha_file_sha,
                    "new_sha256_sidecar_sha256": sha256_bytes(staged_sha_bytes),
                    "previous_manifest_sha256": orig_manifest_sha,
                    "new_manifest_sha256": sha256_bytes(staged_manifest_bytes),
                    "previous_audit_sha256": orig_audit_sha,
                }
                audit_line = (json.dumps(overwrite_audit, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                prefix_bytes = orig_audit_bytes or b""
                if prefix_bytes and not prefix_bytes.endswith(b"\n"):
                    prefix_bytes += b"\n"
                staged_audit_bytes = prefix_bytes + audit_line
                do_audit_write(tmp_audit, staged_audit_bytes)
                staged_hashes["audit"] = sha256_bytes(staged_audit_bytes)
                journal_data["overwrite_audit"] = overwrite_audit

            # 7. Record staged hashes and transition atomically to COMMITTING
            journal_data["staged_sha256"] = staged_hashes
            journal_data["state"] = "COMMITTING"
            _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)

            # 8. Commit all targets via per-file atomic replacements inside transaction boundary
            do_replace(tmp_manifest, manifest_path)
            do_replace(tmp_zip, zip_path)
            do_replace(tmp_sha, sha_path)
            if overwritten:
                do_replace(tmp_audit, audit_path)

            # 9. Persist COMMITTED journal state atomically
            journal_data["state"] = "COMMITTED"
            _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)

        except Exception as tx_exc:
            recovery_errors: list[str] = []
            cleanup_errors: list[str] = []

            try:
                journal_data["state"] = "ROLLING_BACK"
                journal_data["error"] = str(tx_exc)
                _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)
            except Exception:
                pass

            restore_specs = [
                ("manifest", True, bak_manifest, manifest_path, rst_manifest),
                ("zip", orig_zip_existed, bak_zip, zip_path, rst_zip),
                ("sha", orig_sha_existed, bak_sha, sha_path, rst_sha),
            ]
            if overwritten:
                restore_specs.append(("audit", orig_audit_existed, bak_audit, audit_path, rst_audit))
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

            _cleanup_dir(extract_dir, do_unlink, cleanup_errors)
            for t_path in (tmp_manifest, tmp_zip, tmp_sha, tmp_audit, rst_manifest, rst_zip, rst_sha, rst_audit, tmp_journal):
                _cleanup_single_file(t_path, do_unlink, cleanup_errors)

            if recovery_errors:
                try:
                    journal_data["state"] = "RECOVERY_FAILED"
                    journal_data["recovery_errors"] = recovery_errors
                    journal_data["cleanup_errors"] = cleanup_errors
                    _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)
                except Exception:
                    pass
                _cleanup_single_file(tmp_journal, do_unlink, cleanup_errors)
                raise RuntimeError(
                    f"TRANSACTION_RECOVERY_FAILED: original={tx_exc}; recovery_errors={recovery_errors}; cleanup_errors={cleanup_errors}"
                ) from tx_exc

            try:
                journal_data["state"] = "ROLLED_BACK_CLEANUP_PENDING"
                _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)
            except Exception:
                pass
            _cleanup_single_file(tmp_journal, do_unlink, cleanup_errors)

            for b_path in (bak_manifest, bak_zip, bak_sha, bak_audit, journal_path):
                _cleanup_single_file(b_path, do_unlink, cleanup_errors)

            if cleanup_errors:
                try:
                    journal_data["state"] = "ROLLED_BACK_CLEANUP_PENDING"
                    journal_data["cleanup_errors"] = cleanup_errors
                    _write_journal_atomic(journal_path, tmp_journal, journal_data, do_replace)
                except Exception:
                    pass
                raise RuntimeError(
                    f"TRANSACTION_ROLLED_BACK_CLEANUP_FAILED: original={tx_exc}; cleanup_errors={cleanup_errors}"
                ) from tx_exc

            raise

        # Post-commit cleanup of backups, any leftover temp files, and journal
        post_cleanup_errors: list[str] = []
        _cleanup_dir(extract_dir, do_unlink, post_cleanup_errors)
        for leftover in (
            tmp_manifest, tmp_zip, tmp_sha, tmp_audit,
            rst_manifest, rst_zip, rst_sha, rst_audit,
            tmp_journal, bak_manifest, bak_zip, bak_sha, bak_audit, journal_path,
        ):
            _cleanup_single_file(leftover, do_unlink, post_cleanup_errors)

        if post_cleanup_errors:
            try:
                journal_data["state"] = "COMMITTED_CLEANUP_PENDING"
                journal_data["cleanup_errors"] = post_cleanup_errors
                _write_journal_atomic(journal_path, tmp_journal, journal_data, os.replace)
            except Exception:
                pass
            raise RuntimeError(f"TEMP_CLEANUP_FAILED: {post_cleanup_errors}")

        result_payload: dict[str, Any] = {
            "task_id": task_id,
            "version": v_ver,
            "run_id": effective_run_id,
            "zip_path": str(zip_path.relative_to(resolved_root)).replace("\\", "/"),
            "sha256_path": str(sha_path.relative_to(resolved_root)).replace("\\", "/"),
            "zip_sha256": zip_sha,
            "files_verified": len(validated_entries),
            "overwritten": overwritten,
            "status": "PASS",
        }
        if overwrite_audit is not None:
            result_payload["overwrite_audit"] = overwrite_audit
        return result_payload
    finally:
        _release_package_lock(lock_path, lock_fd)


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Standards Acceptance Evidence ZIP")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--version", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--repo-root", default=None, help="Repository root directory (defaults to script parent)")
    parser.add_argument("--recover", action="store_true", help="Run crash recovery for incomplete packaging transactions")
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        default=False,
        help="Explicitly authorize overwriting an existing historical acceptance package (requires task authorization and --overwrite-reason)",
    )
    parser.add_argument(
        "--overwrite-reason",
        default=None,
        help="Mandatory non-empty audit reason recorded when --allow-overwrite is authorized",
    )
    args = parser.parse_args()
    target_root = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT
    if args.recover:
        res = recover_incomplete_package_transactions(
            repo_root=target_root,
            task_id=args.task_id,
            version=args.version,
        )
    else:
        try:
            res = package_acceptance(
                task_id=args.task_id,
                version=args.version,
                run_id=args.run_id,
                repo_root=target_root,
                allow_overwrite=args.allow_overwrite,
                overwrite_reason=args.overwrite_reason,
            )
        except FileExistsError as exc:
            res = {
                "status": "BLOCKED",
                "code": "ACCEPTANCE_PACKAGE_OVERWRITE_FORBIDDEN",
                "task_id": args.task_id,
                "version": args.version,
                "reason": str(exc),
            }
        except ValueError as exc:
            msg = str(exc)
            if "ACCEPTANCE_PACKAGE_OVERWRITE_REASON_REQUIRED" in msg:
                res = {
                    "status": "BLOCKED",
                    "code": "ACCEPTANCE_PACKAGE_OVERWRITE_REASON_REQUIRED",
                    "task_id": args.task_id,
                    "version": args.version,
                    "reason": msg,
                }
            else:
                raise
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if res.get("status") == "BLOCKED":
        sys.exit(1)


if __name__ == "__main__":
    main()
