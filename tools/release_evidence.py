#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic Release Evidence Loader & GitHub CI Authenticity Verifier (STD-034 / STD-035).

Single source of truth for release evidence shared by:
- tools/generate_engineering_baseline.py
- tools/generate_handoff.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

try:
    import jsonschema
except ImportError:
    jsonschema = None

REQUIRED_EVIDENCE_FIELDS: Tuple[str, ...] = (
    "repository",
    "version",
    "pr_number",
    "pr_status",
    "main_head",
    "candidate_commit",
    "snapshot_commit",
    "last_verified_ci_commit",
    "push_run_id",
    "push_head_branch",
    "pr_run_id",
    "ci_status",
    "test_count",
    "test_failed",
    "test_skipped",
    "windows_status",
    "ubuntu_status",
    "release_flow_status",
)


def _parse_semver_tuple(ver: str) -> Optional[Tuple[int, int, int]]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", str(ver).strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _infer_expected_version_from_filename(ev_path: Path) -> Optional[Tuple[str, Tuple[int, int, int], int]]:
    """Return (version_str, semver_tuple, priority) for official release evidence filenames, or None."""
    name = ev_path.name
    m = re.match(r"^v(\d+\.\d+\.\d+)\.json$", name)
    if m:
        ver = m.group(1)
        vt = _parse_semver_tuple(ver)
        if vt is not None:
            return ver, vt, 3
        return None
    if name == "std019-final-release.json":
        return "3.0.0", (3, 0, 0), 2
    mr = re.match(r"^v(\d+\.\d+\.\d+)-reissue\.json$", name)
    if mr:
        ver = mr.group(1)
        vt = _parse_semver_tuple(ver)
        if vt is not None:
            return ver, vt, 1
        return None
    return None


def _verify_local_git_tag_consistency(
    project_root: Path,
    release_tag: str,
    expected_tag_object_sha: str,
    expected_peeled_commit: str,
) -> Tuple[str, List[str]]:
    """Fail-closed verification of local Git annotated tag consistency.
    Returns (status, errors) where status is 'PASS', 'FAIL', or 'NOT_VERIFIABLE':
      - Missing .git directory -> NOT_VERIFIABLE
      - Missing local tag ref -> NOT_VERIFIABLE
      - Git timeout or command exception -> NOT_VERIFIABLE
      - Lightweight tag (object type != 'tag') -> FAIL
      - Tag Object SHA mismatch -> FAIL
      - Peeled Commit mismatch -> FAIL
      - Exact annotated tag match -> PASS
    """
    git_marker = project_root / ".git"
    if not git_marker.exists():
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_NO_GIT_REPO: '{project_root}' has no .git directory to verify tag '{release_tag}'"],
        )

    try:
        res_obj = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--verify", "--quiet", f"refs/tags/{release_tag}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_GIT_TIMEOUT: git rev-parse timed out for tag '{release_tag}': {exc}"],
        )
    except Exception as exc:
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_GIT_ERROR: git rev-parse failed for tag '{release_tag}': {exc}"],
        )

    if res_obj.returncode != 0 or not (res_obj.stdout or "").strip():
        stderr_txt = (res_obj.stderr or "").strip()
        if stderr_txt:
            return (
                "NOT_VERIFIABLE",
                [f"RELEASE_EVIDENCE_GIT_ERROR: git rev-parse failed for tag '{release_tag}': {stderr_txt}"],
            )
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_LOCAL_TAG_NOT_FOUND: Local git tag 'refs/tags/{release_tag}' does not exist"],
        )
    found_obj = res_obj.stdout.strip()

    try:
        res_type = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-t", f"refs/tags/{release_tag}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_GIT_TIMEOUT: git cat-file timed out for tag '{release_tag}': {exc}"],
        )
    except Exception as exc:
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_GIT_ERROR: git cat-file failed for tag '{release_tag}': {exc}"],
        )

    if res_type.returncode != 0:
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_GIT_ERROR: git cat-file failed for tag '{release_tag}': {(res_type.stderr or '').strip()}"],
        )
    obj_type = (res_type.stdout or "").strip()
    if obj_type != "tag":
        return (
            "FAIL",
            [
                f"RELEASE_EVIDENCE_LOCAL_TAG_NOT_ANNOTATED: Local git tag '{release_tag}' has object type '{obj_type}' (annotated 'tag' required)"
            ],
        )

    try:
        res_peeled = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--verify", "--quiet", f"refs/tags/{release_tag}^{{commit}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_GIT_TIMEOUT: git peeled rev-parse timed out for tag '{release_tag}': {exc}"],
        )
    except Exception as exc:
        return (
            "NOT_VERIFIABLE",
            [f"RELEASE_EVIDENCE_GIT_ERROR: git peeled rev-parse failed for tag '{release_tag}': {exc}"],
        )

    if res_peeled.returncode != 0:
        stderr_p = (res_peeled.stderr or "").strip()
        if stderr_p:
            return (
                "NOT_VERIFIABLE",
                [f"RELEASE_EVIDENCE_GIT_ERROR: git peeled rev-parse failed for tag '{release_tag}': {stderr_p}"],
            )

    found_peeled = (res_peeled.stdout or "").strip() if res_peeled.returncode == 0 else ""
    errors: List[str] = []
    if found_obj != expected_tag_object_sha:
        errors.append(
            f"RELEASE_EVIDENCE_LOCAL_TAG_OBJECT_MISMATCH: Local git tag '{release_tag}' object '{found_obj}' != evidence '{expected_tag_object_sha}'"
        )
    if not found_peeled or found_peeled != expected_peeled_commit:
        errors.append(
            f"RELEASE_EVIDENCE_LOCAL_TAG_PEELED_MISMATCH: Local git tag '{release_tag}' peeled commit '{found_peeled}' != evidence '{expected_peeled_commit}'"
        )

    if errors:
        return "FAIL", errors
    return "PASS", []


def is_verified_released_evidence(
    project_root: Path,
    ev_path: Path,
    expected_version: Optional[str] = None,
    verify_local_git_tag: bool = True,
) -> Tuple[bool, List[str], Optional[Dict[str, Any]]]:
    """Validate that ev_path is a fully verified official RELEASED evidence file.
    Rejects CANDIDATE, IN_PROGRESS, BLOCKED, corrupt JSON, schema violations,
    filename/version mismatches, invalid/zero/lightweight tag SHAs, or FAIL/NOT_VERIFIABLE local Git tags.
    """
    project_root = Path(project_root).resolve()
    ev_path = Path(ev_path).resolve()
    if not ev_path.is_file():
        return False, [f"RELEASE_EVIDENCE_NOT_FOUND: '{ev_path}' does not exist"], None

    inferred = _infer_expected_version_from_filename(ev_path)
    if expected_version is None and inferred is not None:
        expected_version = inferred[0]

    ok, errs, data = load_release_evidence(project_root, evidence_path=ev_path)
    if not ok or data is None:
        return False, errs or ["RELEASE_EVIDENCE_INVALID"], None

    check_errors: List[str] = []
    flow_status = str(data.get("release_flow_status") or "").strip()
    if flow_status != "RELEASED":
        check_errors.append(
            f"RELEASE_EVIDENCE_NOT_RELEASED: release_flow_status='{flow_status}' (must be 'RELEASED')"
        )

    data_ver = str(data.get("version") or "").strip().lstrip("v")
    if _parse_semver_tuple(data_ver) is None:
        check_errors.append(f"RELEASE_EVIDENCE_INVALID_VERSION: '{data_ver}' is not valid SemVer")
    elif expected_version is not None and data_ver != str(expected_version).strip().lstrip("v"):
        check_errors.append(
            f"RELEASE_EVIDENCE_VERSION_FILENAME_MISMATCH: version='{data_ver}' != expected='{expected_version}' for '{ev_path.name}'"
        )

    rel_tag = str(data.get("release_tag") or "").strip()
    if rel_tag != f"v{data_ver}":
        check_errors.append(
            f"RELEASE_EVIDENCE_TAG_MISMATCH: release_tag='{rel_tag}' != 'v{data_ver}'"
        )

    tag_obj = str(data.get("tag_object_sha") or "").strip()
    peeled = str(data.get("peeled_commit") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tag_obj) or tag_obj == "0" * 40:
        check_errors.append(f"RELEASE_EVIDENCE_INVALID_TAG_OBJECT_SHA: '{tag_obj}'")
    if not re.fullmatch(r"[0-9a-f]{40}", peeled) or peeled == "0" * 40:
        check_errors.append(f"RELEASE_EVIDENCE_INVALID_PEELED_COMMIT: '{peeled}'")
    if tag_obj and peeled and tag_obj == peeled:
        check_errors.append("RELEASE_EVIDENCE_LIGHTWEIGHT_TAG: tag_object_sha must differ from peeled_commit")
    if peeled and data.get("main_head") and peeled != data.get("main_head"):
        check_errors.append(
            f"RELEASE_EVIDENCE_PEELED_MISMATCH: peeled_commit='{peeled}' != main_head='{data.get('main_head')}'"
        )

    if data.get("tag_publish_status") != "PASS":
        check_errors.append(
            f"RELEASE_EVIDENCE_TAG_PUBLISH_NOT_PASS: tag_publish_status='{data.get('tag_publish_status')}'"
        )
    if data.get("ci_status") != "PASS":
        check_errors.append(f"RELEASE_EVIDENCE_CI_NOT_PASS: ci_status='{data.get('ci_status')}'")
    if data.get("windows_status") != "PASS" or data.get("ubuntu_status") != "PASS":
        check_errors.append(
            f"RELEASE_EVIDENCE_PLATFORM_CI_NOT_PASS: windows='{data.get('windows_status')}', ubuntu='{data.get('ubuntu_status')}'"
        )
    if data.get("pr_merged") is not True or not str(data.get("pr_merged_by") or "").strip():
        check_errors.append("RELEASE_EVIDENCE_PR_MERGE_UNVERIFIED: pr_merged=true and pr_merged_by required")

    if not check_errors and verify_local_git_tag:
        tag_st, git_errs = _verify_local_git_tag_consistency(project_root, rel_tag, tag_obj, peeled)
        if tag_st != "PASS":
            check_errors.extend(git_errs or [f"RELEASE_EVIDENCE_LOCAL_TAG_{tag_st}"])

    if check_errors:
        return False, check_errors, None
    return True, [], data


def _find_latest_official_fallback(
    rev_dir: Path,
    max_version: Optional[str] = None,
    project_root: Optional[Path] = None,
    verify_local_git_tag: bool = True,
) -> Optional[Path]:
    """Select the highest SemVer verified RELEASED official evidence file <= max_version safely.
    Never selects CANDIDATE, IN_PROGRESS, BLOCKED, corrupt JSON, schema-invalid, or FAIL/NOT_VERIFIABLE
    tag-checked files, and never mutates historical evidence files.
    """
    if not rev_dir.exists():
        return None
    eff_root = Path(project_root).resolve() if project_root is not None else rev_dir.parent.parent.resolve()
    max_tuple = _parse_semver_tuple(max_version) if max_version else None
    candidates: List[Tuple[Tuple[int, int, int], int, Path]] = []

    for p in sorted(rev_dir.glob("*.json")):
        inferred = _infer_expected_version_from_filename(p)
        if inferred is None:
            continue
        expected_ver, vt, priority = inferred
        if max_tuple is not None and vt > max_tuple:
            continue
        ok, _, _ = is_verified_released_evidence(
            eff_root,
            p,
            expected_version=expected_ver,
            verify_local_git_tag=verify_local_git_tag,
        )
        if not ok:
            continue
        candidates.append((vt, priority, p))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]
    return None


def resolve_release_evidence_path(
    project_root: Path,
    explicit_path: Optional[str | Path] = None,
    version: Optional[str] = None,
    verify_local_git_tag: bool = True,
) -> Path:
    project_root = Path(project_root).resolve()
    if explicit_path:
        p = Path(explicit_path)
        return p.resolve() if p.is_absolute() else (project_root / p).resolve()

    rev_dir = project_root / "docs" / "release-evidence"
    if version is not None:
        ver_str = str(version).lstrip("v")
        # Explicit version requested: check current-version plain file, reissue file, and v3.0.0 std019 file
        plain_candidate = rev_dir / f"v{ver_str}.json"
        if plain_candidate.exists():
            return plain_candidate
        reissue_candidate = rev_dir / f"v{ver_str}-reissue.json"
        if reissue_candidate.exists():
            return reissue_candidate
        if ver_str == "3.0.0":
            final_candidate = rev_dir / "std019-final-release.json"
            if final_candidate.exists():
                return final_candidate
        return reissue_candidate

    # Default selection reads VERSION first; only a fully verified RELEASED evidence file may be selected.
    # On a candidate release branch prior to formal Tag publish, safely fall back to the highest verified
    # RELEASED evidence file <= VERSION (never selecting CANDIDATE, IN_PROGRESS, BLOCKED, or corrupt files).
    version_file = project_root / "VERSION"
    cur_ver: Optional[str] = None
    if version_file.exists():
        raw_ver = version_file.read_text(encoding="utf-8-sig").strip().lstrip("v")
        if _parse_semver_tuple(raw_ver) is not None:
            cur_ver = raw_ver

    if cur_ver:
        cur_plain = rev_dir / f"v{cur_ver}.json"
        if cur_plain.exists() and is_verified_released_evidence(
            project_root, cur_plain, expected_version=cur_ver, verify_local_git_tag=verify_local_git_tag
        )[0]:
            return cur_plain
        if cur_ver == "3.0.0":
            std019 = rev_dir / "std019-final-release.json"
            if std019.exists() and is_verified_released_evidence(
                project_root, std019, expected_version="3.0.0", verify_local_git_tag=verify_local_git_tag
            )[0]:
                return std019
        cur_reissue = rev_dir / f"v{cur_ver}-reissue.json"
        if cur_reissue.exists() and is_verified_released_evidence(
            project_root, cur_reissue, expected_version=cur_ver, verify_local_git_tag=verify_local_git_tag
        )[0]:
            return cur_reissue

        prev_fallback = _find_latest_official_fallback(
            rev_dir,
            max_version=cur_ver,
            project_root=project_root,
            verify_local_git_tag=verify_local_git_tag,
        )
        if prev_fallback is not None:
            return prev_fallback

        return rev_dir / f"v{cur_ver}-no-verified-released-evidence.json"

    any_fallback = _find_latest_official_fallback(
        rev_dir,
        max_version=None,
        project_root=project_root,
        verify_local_git_tag=verify_local_git_tag,
    )
    if any_fallback is not None:
        return any_fallback

    return rev_dir / "no-verified-released-evidence.json"


def load_release_evidence(
    project_root: Path,
    evidence_path: Optional[str | Path] = None,
    version: Optional[str] = None,
) -> Tuple[bool, List[str], Optional[Dict[str, Any]]]:
    project_root = Path(project_root).resolve()
    target_path = resolve_release_evidence_path(project_root, evidence_path, version)

    if not target_path.exists():
        return (
            False,
            [f"RELEASE_EVIDENCE_NOT_FOUND: Evidence file does not exist at '{target_path}'"],
            None,
        )

    try:
        raw_text = target_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception as e:
        return (
            False,
            [f"RELEASE_EVIDENCE_CORRUPT: Failed to parse JSON from '{target_path}': {e}"],
            None,
        )

    if not isinstance(data, dict):
        return (
            False,
            [f"RELEASE_EVIDENCE_CORRUPT: Root object must be a dictionary in '{target_path}'"],
            None,
        )

    errors: List[str] = []
    for field in REQUIRED_EVIDENCE_FIELDS:
        if field not in data:
            errors.append(f"RELEASE_EVIDENCE_MISSING_FIELD: '{field}' is required")
        elif data[field] is None:
            errors.append(f"RELEASE_EVIDENCE_NULL_FIELD: '{field}' cannot be null")

    # Validate commit hashes (reject malformed or all-zero placeholder SHAs)
    for sha_field in (
        "main_head",
        "candidate_commit",
        "snapshot_commit",
        "last_verified_ci_commit",
    ):
        val = str(data.get(sha_field, ""))
        if not re.match(r"^[0-9a-f]{40}$", val) or val == "0" * 40:
            errors.append(
                f"RELEASE_EVIDENCE_INVALID_SHA: '{sha_field}' must be a non-zero 40-hex commit SHA (got '{val}')"
            )

    if "old_tag_deleted" in data and not isinstance(data.get("old_tag_deleted"), bool):
        errors.append(
            f"RELEASE_EVIDENCE_INVALID_TYPE: 'old_tag_deleted' must be a boolean (got {type(data.get('old_tag_deleted')).__name__})"
        )

    old_tag_deleted_flag = data.get("old_tag_deleted") is True
    for sha_field in ("old_tag_object", "old_tag_peeled_commit"):
        raw_val = data.get(sha_field)
        if old_tag_deleted_flag or raw_val is not None:
            val = str(raw_val or "")
            if not re.match(r"^[0-9a-f]{40}$", val) or val == "0" * 40:
                errors.append(
                    f"RELEASE_EVIDENCE_INVALID_SHA: '{sha_field}' must be a non-zero 40-hex commit SHA (got '{val}')"
                )

    raw_bundle = data.get("old_tag_bundle_sha256")
    if old_tag_deleted_flag or raw_bundle is not None:
        bundle_sha = str(raw_bundle or "")
        if not re.match(r"^[0-9a-f]{64}$", bundle_sha) or bundle_sha == "0" * 64:
            errors.append(
                f"RELEASE_EVIDENCE_INVALID_BUNDLE_SHA: 'old_tag_bundle_sha256' must be a non-zero 64-hex SHA (got '{bundle_sha}')"
            )

    push_id = str(data.get("push_run_id", "")).strip()
    if not push_id.isdigit():
        errors.append(f"RELEASE_EVIDENCE_INVALID_RUN_ID: 'push_run_id' must be numeric (got '{push_id}')")

    push_branch = data.get("push_head_branch")
    if not isinstance(push_branch, str) or not push_branch.strip():
        errors.append("RELEASE_EVIDENCE_INVALID_BRANCH: 'push_head_branch' must be a non-empty string")

    pr_id = str(data.get("pr_run_id", "")).strip()
    if not pr_id.isdigit():
        errors.append(f"RELEASE_EVIDENCE_INVALID_RUN_ID: 'pr_run_id' must be numeric (got '{pr_id}')")

    # Additional validation when release_flow_status is RELEASED (STD-034 / STD-035)
    if data.get("release_flow_status") == "RELEASED":
        rel_tag = str(data.get("release_tag", ""))
        ver = str(data.get("version", "")).lstrip("v")
        if rel_tag != f"v{ver}":
            errors.append(f"RELEASE_EVIDENCE_TAG_MISMATCH: 'release_tag' '{rel_tag}' does not match version '{ver}'")

        tag_obj = str(data.get("tag_object_sha", ""))
        peeled = str(data.get("peeled_commit", ""))
        if not re.match(r"^[0-9a-f]{40}$", tag_obj) or tag_obj == "0" * 40:
            errors.append(f"RELEASE_EVIDENCE_INVALID_SHA: 'tag_object_sha' must be a non-zero 40-hex SHA (got '{tag_obj}')")
        if not re.match(r"^[0-9a-f]{40}$", peeled) or peeled == "0" * 40:
            errors.append(f"RELEASE_EVIDENCE_INVALID_SHA: 'peeled_commit' must be a non-zero 40-hex SHA (got '{peeled}')")
        if tag_obj and peeled and tag_obj == peeled:
            errors.append("RELEASE_EVIDENCE_LIGHTWEIGHT_TAG: 'tag_object_sha' must differ from 'peeled_commit' (annotated tag required)")
        if peeled and data.get("main_head") and peeled != data.get("main_head"):
            errors.append(f"RELEASE_EVIDENCE_PEELED_MISMATCH: 'peeled_commit' '{peeled}' != 'main_head' '{data.get('main_head')}'")

        if data.get("tag_publish_status") != "PASS":
            errors.append(f"RELEASE_EVIDENCE_PUBLISH_NOT_PASSED: 'tag_publish_status' must be 'PASS' (got '{data.get('tag_publish_status')}')")
        if data.get("pr_merged") is not True:
            errors.append("RELEASE_EVIDENCE_PR_NOT_MERGED: 'pr_merged' must be True for RELEASED evidence")
        if not data.get("pr_merged_by"):
            errors.append("RELEASE_EVIDENCE_MISSING_FIELD: 'pr_merged_by' is required for RELEASED evidence")

    # Validate against JSON schema (prefer project_root, fallback to bundled Standards schema)
    schema_path = project_root / "schemas" / "release-evidence.schema.json"
    if not schema_path.exists():
        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "release-evidence.schema.json"
    if schema_path.exists() and jsonschema is not None:
        try:
            schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=data, schema=schema_data)
        except jsonschema.ValidationError as ve:
            errors.append(f"RELEASE_EVIDENCE_SCHEMA_VIOLATION: {ve.message}")
        except Exception as e:
            errors.append(f"RELEASE_EVIDENCE_SCHEMA_ERROR: {e}")

    if errors:
        return False, errors, None

    return True, [], data


def _get_github_token() -> Optional[str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and token.strip():
        return token.strip()
    try:
        res = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def _sanitize_error_message(msg: str, token: Optional[str] = None) -> str:
    if token:
        msg = msg.replace(token, "***")
    return re.sub(
        r"ghp_[a-zA-Z0-9]+|ghs_[a-zA-Z0-9]+|bearer\s+[a-zA-Z0-9_.-]+",
        "***",
        msg,
        flags=re.IGNORECASE,
    )


def _query_run_via_api(
    repo: str,
    run_id: str,
    token: Optional[str] = None,
    timeout: int = 10,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    tok = token or _get_github_token()
    if not tok:
        return False, None, "No GitHub token available for API query"

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {tok}",
        "User-Agent": "AI-Engineering-Standards-Verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    run_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}"
    jobs_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs"

    try:
        req = urllib.request.Request(run_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            run_data = json.loads(resp.read().decode("utf-8"))

        req_jobs = urllib.request.Request(jobs_url, headers=headers)
        with urllib.request.urlopen(req_jobs, timeout=timeout) as resp:
            jobs_data = json.loads(resp.read().decode("utf-8"))

        run_data["jobs"] = jobs_data.get("jobs", [])
        return True, run_data, ""
    except Exception as e:
        return False, None, _sanitize_error_message(str(e), tok)


def _query_run_via_gh(
    repo: str,
    run_id: str,
    timeout: int = 10,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    try:
        cmd_run = ["gh", "api", f"repos/{repo}/actions/runs/{run_id}"]
        res_run = subprocess.run(
            cmd_run,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if res_run.returncode != 0 or not res_run.stdout.strip():
            return False, None, _sanitize_error_message(res_run.stderr or "gh api run query failed")

        run_data = json.loads(res_run.stdout)

        cmd_jobs = ["gh", "api", f"repos/{repo}/actions/runs/{run_id}/jobs"]
        res_jobs = subprocess.run(
            cmd_jobs,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if res_jobs.returncode == 0 and res_jobs.stdout.strip():
            jobs_data = json.loads(res_jobs.stdout)
            run_data["jobs"] = jobs_data.get("jobs", [])
        else:
            run_data["jobs"] = []

        return True, run_data, ""
    except Exception as e:
        return False, None, _sanitize_error_message(str(e))


def _query_pr_via_api(
    repo: str,
    pr_number: int | str,
    token: Optional[str] = None,
    timeout: int = 10,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    tok = token or _get_github_token()
    if not tok:
        return False, None, "No GitHub token available for PR API query"

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {tok}",
        "User-Agent": "AI-Engineering-Standards-Verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"

    try:
        req = urllib.request.Request(pr_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            pr_data = json.loads(resp.read().decode("utf-8"))
        return True, pr_data, ""
    except urllib.error.HTTPError as e:
        status_code = e.code
        return False, None, _sanitize_error_message(f"HTTP {status_code}: {e.reason}", tok)
    except Exception as e:
        return False, None, _sanitize_error_message(str(e), tok)


def _query_pr_via_gh(
    repo: str,
    pr_number: int | str,
    timeout: int = 10,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    try:
        cmd_pr = ["gh", "api", f"repos/{repo}/pulls/{pr_number}"]
        res_pr = subprocess.run(
            cmd_pr,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if res_pr.returncode != 0 or not res_pr.stdout.strip():
            return False, None, _sanitize_error_message(res_pr.stderr or "gh api pr query failed")

        pr_data = json.loads(res_pr.stdout)
        return True, pr_data, ""
    except Exception as e:
        return False, None, _sanitize_error_message(str(e))


def verify_git_tag(
    project_root: Path,
    release_tag: str,
    expected_tag_object_sha: str,
    expected_peeled_commit: str,
    simulate_ls_remote: Optional[str] = None,
    simulate_network_error: bool = False,
) -> Tuple[str, List[str]]:
    """Verify annotated tag object SHA and peeled commit SHA remotely against origin,
    with local tag consistency as secondary verification (STD-034 / STD-035).
    Rejects lightweight tags and requires exact SHA matches.
    Returns status: 'PASS', 'FAIL', or 'NOT_VERIFIABLE'.
    """
    if simulate_network_error:
        return (
            "NOT_VERIFIABLE",
            [f"TAG_NETWORK_ERROR: Network/API not accessible when querying git tag '{release_tag}'"],
        )

    # 1. Query remote origin (Primary verification)
    if simulate_ls_remote is not None:
        ls_out = simulate_ls_remote
        rc = 0
        err_msg = ""
    else:
        try:
            res = subprocess.run(
                ["git", "-C", str(project_root), "ls-remote", "origin", f"refs/tags/{release_tag}*"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
            rc = res.returncode
            ls_out = res.stdout or ""
            err_msg = res.stderr or ""
        except Exception as e:
            return (
                "NOT_VERIFIABLE",
                [f"TAG_LOOKUP_ERROR: Failed to query git tag '{release_tag}' from remote: {_sanitize_error_message(str(e))}"],
            )

        if rc != 0:
            return (
                "NOT_VERIFIABLE",
                [f"TAG_LOOKUP_ERROR: ls-remote origin failed for '{release_tag}': {_sanitize_error_message(err_msg or 'command failed')}"],
            )

    errors: List[str] = []
    found_obj: Optional[str] = None
    found_peeled: Optional[str] = None

    for line in ls_out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            if parts[1] == f"refs/tags/{release_tag}":
                found_obj = parts[0]
            elif parts[1] == f"refs/tags/{release_tag}^{{}}":
                found_peeled = parts[0]

    if not found_obj and not found_peeled:
        errors.append(f"TAG_NOT_FOUND: Remote tag '{release_tag}' not found on origin")
    else:
        if not found_obj:
            errors.append(f"TAG_NOT_FOUND: Remote tag object for '{release_tag}' not found")
        elif found_obj != expected_tag_object_sha:
            errors.append(
                f"TAG_OBJECT_MISMATCH: Remote tag object SHA mismatch for '{release_tag}': expected '{expected_tag_object_sha}', got '{found_obj}'"
            )

        if not found_peeled:
            errors.append(
                f"TAG_NOT_ANNOTATED: Remote tag '{release_tag}' is not an annotated tag (missing peeled commit / lightweight tag rejected)"
            )
        else:
            if found_obj and found_obj == found_peeled:
                errors.append(
                    f"TAG_LIGHTWEIGHT_REJECTED: Tag '{release_tag}' object SHA equals peeled commit (annotated tag required)"
                )
            if found_peeled != expected_peeled_commit:
                errors.append(
                    f"TAG_PEELED_MISMATCH: Remote peeled commit mismatch for '{release_tag}': expected '{expected_peeled_commit}', got '{found_peeled}'"
                )

    # 2. Secondary check: local tag if present in workspace
    try:
        res_loc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", f"refs/tags/{release_tag}", f"refs/tags/{release_tag}^{{commit}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if res_loc.returncode == 0:
            lines = [l.strip() for l in res_loc.stdout.splitlines() if l.strip()]
            if len(lines) >= 2:
                loc_obj, loc_peeled = lines[0], lines[1]
                if loc_obj != expected_tag_object_sha:
                    errors.append(
                        f"LOCAL_TAG_OBJECT_MISMATCH: Local tag object SHA mismatch for '{release_tag}': expected '{expected_tag_object_sha}', got '{loc_obj}'"
                    )
                if loc_peeled != expected_peeled_commit:
                    errors.append(
                        f"LOCAL_TAG_PEELED_MISMATCH: Local peeled commit mismatch for '{release_tag}': expected '{expected_peeled_commit}', got '{loc_peeled}'"
                    )
    except Exception:
        pass

    if errors:
        return "FAIL", errors

    return "PASS", []


def verify_single_github_run(
    repo: str,
    run_id: str,
    expected_event: str,
    expected_head_sha: str,
    expected_head_branch: Optional[str] = None,
    expected_pr_number: Optional[int | str] = None,
    expected_base_ref: Optional[str] = None,
    expected_pr_status: Optional[str] = None,
    expected_workflow_path: str = ".github/workflows/standards-ci.yml",
    timeout: int = 10,
    simulate_data: Optional[Dict[str, Any]] = None,
    simulate_pr_data: Optional[Dict[str, Any]] = None,
    simulate_pr_error: Optional[str] = None,
    require_tag_publish: bool = False,
) -> Tuple[str, List[str], Dict[str, Any]]:
    """Verify an individual GitHub Actions run against all authenticity requirements.
    Never outputs tokens. Returns status: 'PASS', 'FAIL', or 'NOT_VERIFIABLE'.
    """
    errors: List[str] = []
    run_meta: Dict[str, Any] = {
        "run_id": str(run_id),
        "expected_event": expected_event,
        "expected_head_sha": expected_head_sha,
        "expected_workflow_path": expected_workflow_path,
    }

    if simulate_data is not None:
        run_data = simulate_data
        ok = True
        err_msg = ""
    else:
        # Priority 1: GitHub REST API
        ok, run_data, err_msg = _query_run_via_api(repo, str(run_id), timeout=timeout)
        # Priority 2: Fallback to gh CLI
        if not ok:
            ok, run_data, err_msg = _query_run_via_gh(repo, str(run_id), timeout=timeout)

    if not ok or run_data is None:
        # Cannot access run (e.g. offline, rate limit, historical run not accessible)
        # Never fake PASS; record NOT_VERIFIABLE
        run_meta["verification_status"] = "NOT_VERIFIABLE"
        run_meta["reason"] = f"GITHUB_CI_NOT_ACCESSIBLE: {_sanitize_error_message(err_msg)}"
        return "NOT_VERIFIABLE", [f"Run {run_id} not accessible: {_sanitize_error_message(err_msg)}"], run_meta

    # 1. Repository full_name binding
    actual_repo: Optional[str] = None
    if isinstance(run_data.get("repository"), dict):
        actual_repo = run_data["repository"].get("full_name")
    elif isinstance(run_data.get("repository"), str):
        actual_repo = run_data["repository"]
    elif run_data.get("repo"):
        actual_repo = str(run_data["repo"])

    run_meta["actual_repository"] = actual_repo
    if not actual_repo:
        errors.append(f"Run {run_id} is missing repository information")
    elif actual_repo != repo:
        errors.append(f"Run {run_id} repository mismatch: expected '{repo}', got '{actual_repo}'")

    # 2. Run ID binding
    actual_run_id = str(run_data.get("id") or run_data.get("databaseId") or "")
    run_meta["actual_run_id"] = actual_run_id
    if not actual_run_id:
        errors.append(f"Run {run_id} is missing run ID")
    elif actual_run_id != str(run_id):
        errors.append(f"Run {run_id} ID mismatch: expected '{run_id}', got '{actual_run_id}'")

    # 3. Event type
    actual_event = run_data.get("event")
    run_meta["actual_event"] = actual_event
    if not actual_event:
        errors.append(f"Run {run_id} is missing event type")
    elif actual_event != expected_event:
        errors.append(f"Run {run_id} event mismatch: expected '{expected_event}', got '{actual_event}'")

    # 4. Workflow path binding (must be .github/workflows/standards-ci.yml)
    actual_path = run_data.get("path") or run_data.get("workflowPath") or run_data.get("workflow_path")
    run_meta["actual_workflow_path"] = actual_path
    if not actual_path:
        errors.append(f"Run {run_id} is missing workflow path")
    elif actual_path != expected_workflow_path:
        errors.append(f"Run {run_id} workflow path mismatch: expected '{expected_workflow_path}', got '{actual_path}'")

    # 5. head_sha binding (must match independent evidence CI Commit; use Run's own head_sha, not dynamic PR head)
    actual_head = run_data.get("headSha") or run_data.get("head_sha")
    run_meta["actual_head_sha"] = actual_head
    if not actual_head:
        errors.append(f"Run {run_id} is missing head SHA")
    elif actual_head != expected_head_sha:
        errors.append(f"Run {run_id} head_sha mismatch: expected '{expected_head_sha}', got '{actual_head}'")

    # 6. Status binding: status=completed
    actual_status = run_data.get("status")
    run_meta["actual_status"] = actual_status
    if actual_status != "completed":
        errors.append(f"Run {run_id} status was '{actual_status}', expected 'completed'")

    # 7. Conclusion binding: conclusion=success
    actual_conclusion = run_data.get("conclusion")
    run_meta["actual_conclusion"] = actual_conclusion
    if actual_conclusion != "success":
        errors.append(f"Run {run_id} conclusion was '{actual_conclusion}', expected 'success'")

    # 8. Ubuntu Job: completed/success
    # 9. Windows Job: completed/success
    jobs = run_data.get("jobs", [])
    ubuntu_job = None
    windows_job = None
    tag_publish_job = None
    for j in jobs:
        name = j.get("name", "").lower()
        if "ubuntu" in name:
            ubuntu_job = j
        elif "windows" in name:
            windows_job = j
        elif "publish standards tag" in name or ("tag" in name and "publish" in name):
            tag_publish_job = j

    if ubuntu_job is None:
        errors.append(f"Run {run_id} is missing Ubuntu validation job")
    else:
        u_status = ubuntu_job.get("status")
        u_concl = ubuntu_job.get("conclusion")
        run_meta["ubuntu_status"] = u_status
        run_meta["ubuntu_conclusion"] = u_concl
        if u_status != "completed":
            errors.append(f"Run {run_id} Ubuntu job status was '{u_status}', expected 'completed'")
        if u_concl != "success":
            errors.append(f"Run {run_id} Ubuntu job conclusion was '{u_concl}', expected 'success'")

    if windows_job is None:
        errors.append(f"Run {run_id} is missing Windows validation job")
    else:
        w_status = windows_job.get("status")
        w_concl = windows_job.get("conclusion")
        run_meta["windows_status"] = w_status
        run_meta["windows_conclusion"] = w_concl
        if w_status != "completed":
            errors.append(f"Run {run_id} Windows job status was '{w_status}', expected 'completed'")
        if w_concl != "success":
            errors.append(f"Run {run_id} Windows job conclusion was '{w_concl}', expected 'success'")

    if require_tag_publish:
        if tag_publish_job is None:
            errors.append(f"Run {run_id} is missing Tag Publish job ('Publish Standards Tag after main CI')")
        else:
            tp_status = tag_publish_job.get("status")
            tp_concl = tag_publish_job.get("conclusion")
            run_meta["tag_publish_status"] = tp_status
            run_meta["tag_publish_conclusion"] = tp_concl
            if tp_status != "completed":
                errors.append(f"Run {run_id} Tag Publish job status was '{tp_status}', expected 'completed'")
            if tp_concl != "success":
                errors.append(f"Run {run_id} Tag Publish job conclusion was '{tp_concl}', expected 'success'")

    # Push Run extra check: head_branch must be target feature branch
    if expected_event == "push" and expected_head_branch is not None:
        actual_head_branch = run_data.get("headBranch") or run_data.get("head_branch")
        run_meta["actual_head_branch"] = actual_head_branch
        if not actual_head_branch:
            errors.append(f"Run {run_id} is missing head_branch")
        elif actual_head_branch != expected_head_branch:
            errors.append(f"Run {run_id} head_branch mismatch: expected '{expected_head_branch}', got '{actual_head_branch}'")

    # PR Run extra checks: PR number, base.ref=main, event=pull_request
    if expected_event == "pull_request":
        prs = run_data.get("pull_requests", [])
        if prs:
            run_meta["pull_requests"] = [p.get("number") for p in prs if isinstance(p, dict)]
            if expected_pr_number is not None:
                matching_pr = None
                for p in prs:
                    if isinstance(p, dict) and str(p.get("number")) == str(expected_pr_number):
                        matching_pr = p
                        break
                if matching_pr is None:
                    found_nums = [p.get("number") for p in prs if isinstance(p, dict)]
                    errors.append(f"Run {run_id} PR number mismatch: expected {expected_pr_number}, found {found_nums}")
                else:
                    if expected_base_ref is not None:
                        base_ref = matching_pr.get("base", {}).get("ref") if isinstance(matching_pr.get("base"), dict) else None
                        run_meta["actual_base_ref"] = base_ref
                        if base_ref != expected_base_ref:
                            errors.append(f"Run {run_id} PR base ref mismatch: expected '{expected_base_ref}', got '{base_ref}'")
            run_meta["pr_fallback_verified"] = False
        else:
            # Fallback path: when historical PR Run is merged, GitHub Actions API may return pull_requests=[].
            # Query GitHub REST API /repos/{owner}/{repo}/pulls/{pr_number} using independent release evidence.
            if expected_pr_number is None:
                errors.append(f"Run {run_id} has no associated pull requests and no expected_pr_number provided for fallback")
            else:
                if simulate_pr_error is not None:
                    pr_ok = False
                    pr_data = None
                    pr_err_msg = simulate_pr_error
                elif simulate_pr_data is not None:
                    pr_ok = True
                    pr_data = simulate_pr_data
                    pr_err_msg = ""
                else:
                    pr_ok, pr_data, pr_err_msg = _query_pr_via_api(repo, str(expected_pr_number), timeout=timeout)
                    if not pr_ok:
                        pr_ok, pr_data, pr_err_msg = _query_pr_via_gh(repo, str(expected_pr_number), timeout=timeout)

                if not pr_ok or pr_data is None:
                    run_meta["verification_status"] = "NOT_VERIFIABLE"
                    run_meta["reason"] = f"PR_API_NOT_ACCESSIBLE: {_sanitize_error_message(pr_err_msg)}"
                    return (
                        "NOT_VERIFIABLE",
                        [f"Run {run_id} PR #{expected_pr_number} API not accessible: {_sanitize_error_message(pr_err_msg)}"],
                        run_meta,
                    )

                # 1. PR number 与 expected_pr_number 一致。
                actual_pr_num = pr_data.get("number")
                run_meta["actual_pr_number"] = actual_pr_num
                run_meta["fallback_pr_number"] = actual_pr_num
                if str(actual_pr_num) != str(expected_pr_number):
                    errors.append(f"Run {run_id} PR number mismatch: expected {expected_pr_number}, got {actual_pr_num}")

                # 2. PR base.ref=main。
                target_base_ref = expected_base_ref or "main"
                actual_pr_base_ref = pr_data.get("base", {}).get("ref") if isinstance(pr_data.get("base"), dict) else None
                run_meta["actual_base_ref"] = actual_pr_base_ref
                if actual_pr_base_ref != target_base_ref:
                    errors.append(f"Run {run_id} PR base ref mismatch: expected '{target_base_ref}', got '{actual_pr_base_ref}'")

                # 3. PR head.ref 与历史 Run head_branch 一致。
                run_head_branch = run_data.get("headBranch") or run_data.get("head_branch")
                actual_pr_head_ref = pr_data.get("head", {}).get("ref") if isinstance(pr_data.get("head"), dict) else None
                run_meta["actual_head_ref"] = actual_pr_head_ref
                if not run_head_branch:
                    errors.append(f"Run {run_id} is missing head_branch for PR fallback verification")
                elif actual_pr_head_ref != run_head_branch:
                    errors.append(f"Run {run_id} PR head.ref mismatch: expected '{run_head_branch}', got '{actual_pr_head_ref}'")

                # 4. PR head.sha 与历史 Run head_sha 一致。
                run_head_sha = run_data.get("headSha") or run_data.get("head_sha")
                actual_pr_head_sha = pr_data.get("head", {}).get("sha") if isinstance(pr_data.get("head"), dict) else None
                run_meta["actual_pr_head_sha"] = actual_pr_head_sha
                if not run_head_sha:
                    errors.append(f"Run {run_id} is missing head_sha for PR fallback verification")
                elif actual_pr_head_sha != run_head_sha:
                    errors.append(f"Run {run_id} PR head.sha mismatch: expected '{run_head_sha}', got '{actual_pr_head_sha}'")

                # 5. PR merged=true（当 release evidence 的 pr_status=MERGED 时）。
                is_merged = pr_data.get("merged")
                run_meta["pr_merged"] = is_merged
                if expected_pr_status == "MERGED":
                    if is_merged is not True:
                        errors.append(f"Run {run_id} PR merged status mismatch: expected merged=True, got {is_merged}")

                # 6. merged_at 非空。
                merged_at = pr_data.get("merged_at")
                run_meta["pr_merged_at"] = merged_at
                if is_merged is True or expected_pr_status == "MERGED":
                    if not merged_at:
                        errors.append(f"Run {run_id} PR merged_at is empty for merged PR")

                run_meta["pull_requests"] = [actual_pr_num] if actual_pr_num is not None else []
                run_meta["pr_fallback_verified"] = True

    if errors:
        run_meta["verification_status"] = "FAIL"
        run_meta["errors"] = errors
        return "FAIL", errors, run_meta

    run_meta["verification_status"] = "PASS"
    return "PASS", [], run_meta


def verify_github_ci_runs(
    evidence: Dict[str, Any],
    project_root: Optional[Path] = None,
    timeout: int = 10,
    simulate_status: Optional[str] = None,
    simulate_data_map: Optional[Dict[str, Any]] = None,
    simulate_pr_data_map: Optional[Dict[str, Any]] = None,
    simulate_pr_error_map: Optional[Dict[str, Any]] = None,
    target_branch: Optional[str] = None,
) -> Tuple[str, List[str], Dict[str, Any]]:
    """Verify both Push Run and PR Run recorded in release evidence.
    Returns (overall_status, errors, details).
    """
    if simulate_status is not None:
        return (
            "FAIL",
            ["SIMULATION_DISALLOWED: Simulated status bypass is not permitted in production verification path"],
            {"reason": "SIMULATION_DISALLOWED"},
        )

    repo = evidence["repository"]
    head_sha = evidence["last_verified_ci_commit"]
    push_id = str(evidence["push_run_id"])
    pr_id = str(evidence["pr_run_id"])
    pr_number = evidence.get("pr_number", 9)

    push_head_branch = evidence.get("push_head_branch")
    if not push_head_branch or not isinstance(push_head_branch, str) or not push_head_branch.strip():
        return (
            "FAIL",
            ["RELEASE_EVIDENCE_MISSING_FIELD: 'push_head_branch' is required in release evidence and cannot be empty"],
            {
                "reason": "MISSING_PUSH_HEAD_BRANCH",
                "push_run": {"verification_status": "FAIL", "errors": ["Missing or empty push_head_branch in release evidence"]},
                "pr_run": {"verification_status": "NOT_RUN"},
                "repository": repo,
                "last_verified_ci_commit": head_sha,
            },
        )

    expected_push_branch = push_head_branch.strip()

    sim_push = simulate_data_map.get(push_id) if simulate_data_map else None
    sim_pr = simulate_data_map.get(pr_id) if simulate_data_map else None

    sim_pr_api = None
    sim_pr_err = None
    if simulate_pr_data_map is not None:
        sim_pr_api = simulate_pr_data_map.get(str(pr_number)) or simulate_pr_data_map.get(pr_number)
    elif simulate_data_map is not None:
        sim_pr_api = simulate_data_map.get(f"pr_{pr_number}") or simulate_data_map.get(f"pull_{pr_number}")
    if simulate_pr_error_map is not None:
        sim_pr_err = simulate_pr_error_map.get(str(pr_number)) or simulate_pr_error_map.get(pr_number)
    elif simulate_data_map is not None:
        sim_pr_err = simulate_data_map.get(f"pr_error_{pr_number}")

    if evidence.get("release_flow_status") == "RELEASED":
        repo_owner = repo.split("/")[0] if "/" in repo else repo
        peeled_commit = str(evidence["peeled_commit"])
        rel_tag = str(evidence["release_tag"])
        tag_obj_sha = str(evidence["tag_object_sha"])

        # =====================================================================
        # Chain C: PR Merge Authenticity & PR API Data Extraction
        # =====================================================================
        pr_merge_errors: List[str] = []
        pr_merge_meta: Dict[str, Any] = {}

        if simulate_pr_error_map is not None and (
            simulate_pr_error_map.get(str(pr_number)) is not None
            or simulate_pr_error_map.get(pr_number) is not None
        ):
            pr_data = None
            pr_ok = False
            pr_err_msg = str(
                simulate_pr_error_map.get(str(pr_number))
                or simulate_pr_error_map.get(pr_number)
            )
        elif simulate_pr_data_map is not None:
            pr_data = simulate_pr_data_map.get(str(pr_number)) or simulate_pr_data_map.get(pr_number)
            pr_ok = pr_data is not None
            pr_err_msg = ""
        elif simulate_data_map is not None:
            pr_data = simulate_data_map.get(f"pr_{pr_number}")
            pr_ok = pr_data is not None
            pr_err_msg = ""
        else:
            pr_ok, pr_data, pr_err_msg = _query_pr_via_api(repo, str(pr_number), timeout=timeout)
            if not pr_ok:
                pr_ok, pr_data, pr_err_msg = _query_pr_via_gh(repo, str(pr_number), timeout=timeout)

        pr_api_st = "OK"
        pr_head_ref = None
        pr_head_sha = None

        if not pr_ok or pr_data is None:
            pr_api_st = "NOT_VERIFIABLE"
            pr_merge_errors.append(f"PR_API_NOT_ACCESSIBLE: {_sanitize_error_message(pr_err_msg)}")
        else:
            # 1. PR number
            actual_pr_num = pr_data.get("number")
            pr_merge_meta["actual_pr_number"] = actual_pr_num
            if actual_pr_num is None:
                pr_merge_errors.append(f"PR_NUMBER_MISSING: PR API response is missing the number for expected PR #{pr_number}")
            elif str(actual_pr_num) != str(pr_number):
                pr_merge_errors.append(f"PR_NUMBER_MISMATCH: PR #{pr_number} != actual #{actual_pr_num}")

            # 2. base.ref must be main
            actual_base_ref = pr_data.get("base", {}).get("ref") if isinstance(pr_data.get("base"), dict) else None
            pr_merge_meta["actual_base_ref"] = actual_base_ref
            if actual_base_ref != "main":
                pr_merge_errors.append(f"PR_BASE_REF_MISMATCH: PR #{pr_number} base.ref is '{actual_base_ref}', expected 'main'")

            # 3. merged=true
            actual_merged = pr_data.get("merged")
            pr_merge_meta["actual_merged"] = actual_merged
            if actual_merged is not True:
                pr_merge_errors.append(f"PR_NOT_MERGED: PR #{pr_number} merged status is {actual_merged}, expected True")

            # 4. merged_at non-empty
            merged_at = pr_data.get("merged_at")
            pr_merge_meta["merged_at"] = merged_at
            if not merged_at:
                pr_merge_errors.append(f"PR_MERGED_AT_EMPTY: PR #{pr_number} merged_at is empty")

            # 5. merge_commit_sha must exist and equal peeled_commit
            actual_merge_sha = pr_data.get("merge_commit_sha") or (
                pr_data.get("mergeCommit", {}).get("oid") if isinstance(pr_data.get("mergeCommit"), dict) else None
            )
            pr_merge_meta["actual_merge_commit_sha"] = actual_merge_sha
            if not actual_merge_sha:
                pr_merge_errors.append(f"PR_MERGE_COMMIT_MISSING: PR #{pr_number} merge_commit_sha is missing")
            elif actual_merge_sha != peeled_commit:
                pr_merge_errors.append(f"PR_MERGE_COMMIT_MISMATCH: PR #{pr_number} merge commit '{actual_merge_sha}' != peeled commit '{peeled_commit}'")

            # 6. merged_by.login must equal repository owner
            actual_merged_by = None
            if isinstance(pr_data.get("merged_by"), dict):
                actual_merged_by = pr_data["merged_by"].get("login")
            elif isinstance(pr_data.get("mergedBy"), dict):
                actual_merged_by = pr_data["mergedBy"].get("login")

            pr_merge_meta["actual_merged_by"] = actual_merged_by
            if not actual_merged_by:
                pr_merge_errors.append(f"PR_MERGED_BY_MISSING: PR #{pr_number} merged_by is missing")
            else:
                if actual_merged_by != repo_owner:
                    pr_merge_errors.append(f"PR_MERGED_BY_NOT_OWNER: PR #{pr_number} merged by '{actual_merged_by}', which is not repository owner '{repo_owner}'")
                exp_merged_by = evidence.get("pr_merged_by")
                if exp_merged_by and actual_merged_by != exp_merged_by:
                    pr_merge_errors.append(f"PR_MERGED_BY_MISMATCH: PR #{pr_number} merged by '{actual_merged_by}', expected '{exp_merged_by}'")

            # Extract PR head.ref and head.sha for Chain B
            if isinstance(pr_data.get("head"), dict):
                pr_head_ref = pr_data["head"].get("ref")
                pr_head_sha = pr_data["head"].get("sha")

        # =====================================================================
        # Chain B: PR CI Run Independent Verification
        # =====================================================================
        pr_ci_errors: List[str] = []
        pr_ci_meta: Dict[str, Any] = {}
        pr_run_id = str(evidence.get("pr_run_id"))
        sim_pr = simulate_data_map.get(pr_run_id) if simulate_data_map else None

        if pr_api_st == "NOT_VERIFIABLE":
            pr_ci_st = "NOT_VERIFIABLE"
        elif not pr_head_sha or not pr_head_ref:
            pr_ci_st = "FAIL"
            pr_ci_errors.append(f"PR_HEAD_INFO_MISSING: PR #{pr_number} head.ref or head.sha missing from PR API data")
        else:
            pr_ci_st, pr_ci_errs, pr_ci_meta = verify_single_github_run(
                repo=repo,
                run_id=pr_run_id,
                expected_event="pull_request",
                expected_head_sha=pr_head_sha,
                expected_head_branch=pr_head_ref,
                expected_pr_number=pr_number,
                expected_base_ref="main",
                expected_workflow_path=".github/workflows/standards-ci.yml",
                timeout=timeout,
                simulate_data=sim_pr,
                simulate_pr_data=pr_data,
                require_tag_publish=False,
            )
            pr_ci_errors.extend(pr_ci_errs)

        # =====================================================================
        # Chain A: Main CI Run Independent Verification
        # =====================================================================
        main_run_id = str(evidence.get("main_ci_run_id") or evidence.get("push_run_id"))
        sim_main = simulate_data_map.get(main_run_id) if simulate_data_map else None

        main_st, main_errs, main_meta = verify_single_github_run(
            repo=repo,
            run_id=main_run_id,
            expected_event="push",
            expected_head_sha=peeled_commit,
            expected_head_branch="main",
            expected_workflow_path=".github/workflows/standards-ci.yml",
            timeout=timeout,
            simulate_data=sim_main,
            require_tag_publish=True,
        )

        # =====================================================================
        # Tag Remote Verification
        # =====================================================================
        root = Path(project_root or ".").resolve()
        sim_ls_remote = simulate_data_map.get("ls_remote") if simulate_data_map else None
        sim_tag_net_err = bool(simulate_data_map.get("tag_network_error")) if simulate_data_map else False

        tag_st, tag_errs = verify_git_tag(
            project_root=root,
            release_tag=rel_tag,
            expected_tag_object_sha=tag_obj_sha,
            expected_peeled_commit=peeled_commit,
            simulate_ls_remote=sim_ls_remote,
            simulate_network_error=sim_tag_net_err,
        )

        chain_c_st = (
            "NOT_VERIFIABLE"
            if pr_api_st == "NOT_VERIFIABLE"
            else ("FAIL" if pr_merge_errors else "PASS")
        )
        all_errors = main_errs + pr_merge_errors + pr_ci_errors + tag_errs
        details = {
            "main_ci_run": main_meta,
            "pr_ci_run": pr_ci_meta,
            "pr_merge": pr_merge_meta,
            "pr_merge_errors": pr_merge_errors,
            "pr_ci_errors": pr_ci_errors,
            "release_tag": rel_tag,
            "tag_object_sha": tag_obj_sha,
            "peeled_commit": peeled_commit,
            "repository": repo,
            "release_flow_status": "RELEASED",
            "tag_publish_verified": (tag_st == "PASS"),
            "tag_verification_status": tag_st,
            "chains": {
                "chain_a_main_ci": main_st,
                "chain_b_pr_ci": pr_ci_st,
                "chain_c_pr_merge": chain_c_st,
                "tag_remote": tag_st,
            },
        }

        # Any explicit FAIL or error condition fails closed
        if main_st == "FAIL" or pr_ci_st == "FAIL" or tag_st == "FAIL" or chain_c_st == "FAIL":
            return "FAIL", all_errors, details

        # If any check was NOT_VERIFIABLE and no explicit FAIL
        if main_st == "NOT_VERIFIABLE" or pr_ci_st == "NOT_VERIFIABLE" or tag_st == "NOT_VERIFIABLE" or chain_c_st == "NOT_VERIFIABLE":
            return "NOT_VERIFIABLE", all_errors, details

        return "PASS", [], details

    push_st, push_errs, push_meta = verify_single_github_run(
        repo=repo,
        run_id=push_id,
        expected_event="push",
        expected_head_sha=head_sha,
        expected_head_branch=expected_push_branch,
        expected_workflow_path=".github/workflows/standards-ci.yml",
        timeout=timeout,
        simulate_data=sim_push,
    )

    pr_st, pr_errs, pr_meta = verify_single_github_run(
        repo=repo,
        run_id=pr_id,
        expected_event="pull_request",
        expected_head_sha=head_sha,
        expected_head_branch=expected_push_branch,
        expected_pr_number=pr_number,
        expected_base_ref="main",
        expected_pr_status=evidence.get("pr_status"),
        expected_workflow_path=".github/workflows/standards-ci.yml",
        timeout=timeout,
        simulate_data=sim_pr,
        simulate_pr_data=sim_pr_api,
        simulate_pr_error=sim_pr_err,
    )

    all_errors = push_errs + pr_errs
    details = {
        "push_run": push_meta,
        "pr_run": pr_meta,
        "last_verified_ci_commit": head_sha,
        "repository": repo,
        "push_head_branch": expected_push_branch,
        "pr_number": pr_number,
        "pr_status": evidence.get("pr_status"),
        "base_ref": "main",
        "pr_fallback_verified": pr_meta.get("pr_fallback_verified", False),
    }

    if push_st == "FAIL" or pr_st == "FAIL":
        return "FAIL", all_errors, details

    if push_st == "NOT_VERIFIABLE" or pr_st == "NOT_VERIFIABLE":
        return "NOT_VERIFIABLE", all_errors, details

    return "PASS", [], details


def _extract_repo_from_pr_payload(pr_data: Dict[str, Any]) -> Optional[str]:
    """Extract 'owner/repo' full_name from a GitHub PR API payload."""
    base = pr_data.get("base")
    if isinstance(base, dict):
        repo_obj = base.get("repo")
        if isinstance(repo_obj, dict) and repo_obj.get("full_name"):
            return str(repo_obj["full_name"]).strip()
    head = pr_data.get("head")
    if isinstance(head, dict):
        repo_obj = head.get("repo")
        if isinstance(repo_obj, dict) and repo_obj.get("full_name"):
            return str(repo_obj["full_name"]).strip()
    for url_key in ("url", "html_url"):
        raw_url = str(pr_data.get(url_key) or "").strip()
        m = re.search(r"github\.com/(?:repos/)?([^/]+/[^/]+)/pulls?/\d+", raw_url)
        if m:
            return m.group(1).strip()
    return None


def _query_compare_via_api_or_gh(
    repo: str,
    base_sha: str,
    head_sha: str,
    timeout: int = 10,
) -> Tuple[bool, Optional[str], str]:
    """Query GitHub Compare API to check commit ancestry when remote head commit is not fetched locally."""
    tok = _get_github_token()
    if tok:
        url = f"https://api.github.com/repos/{repo}/compare/{base_sha}...{head_sha}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {tok}",
            "User-Agent": "AI-Engineering-Standards-Verifier",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return True, str(data.get("status") or "").strip(), ""
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return True, "diverged", "compare 404 (unrelated history)"
        except Exception:
            pass
    try:
        res = subprocess.run(
            ["gh", "api", f"repos/{repo}/compare/{base_sha}...{head_sha}", "--jq", ".status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if res.returncode == 0 and (res.stdout or "").strip():
            return True, res.stdout.strip(), ""
    except Exception as exc:
        return False, None, _sanitize_error_message(str(exc), tok)
    return False, None, "compare API unavailable"


def verify_commit_ancestry(
    project_root: Path,
    ancestor_commit: str,
    descendant_commit: str,
    repository: Optional[str] = None,
    allow_remote_compare: bool = False,
) -> Tuple[str, List[str]]:
    """Verify via Git that ancestor_commit is a real commit and is an ancestor of descendant_commit.
    Uses `git merge-base --is-ancestor <ancestor_commit> <descendant_commit>`.
    Returns ('PASS' | 'FAIL' | 'NOT_VERIFIABLE', errors).
    """
    project_root = Path(project_root).resolve()
    anc = str(ancestor_commit or "").strip()
    desc = str(descendant_commit or "").strip()

    if not re.fullmatch(r"[0-9a-f]{40}", anc) or anc == "0" * 40:
        return "FAIL", [f"CANDIDATE_COMMIT_INVALID: '{anc}' must be a non-zero 40-hex commit SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", desc) or desc == "0" * 40:
        return "FAIL", [f"CANDIDATE_PR_INVALID_HEAD: '{desc}' must be a non-zero 40-hex commit SHA"]

    if not (project_root / ".git").exists():
        return "NOT_VERIFIABLE", [f"GIT_REPO_NOT_FOUND: '{project_root}' has no .git directory to verify commit ancestry"]

    try:
        rc_anc_obj = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-e", f"{anc}^{{commit}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except Exception as exc:
        return "NOT_VERIFIABLE", [f"GIT_ANCESTRY_ERROR: failed inspecting candidate commit '{anc}': {exc}"]

    if rc_anc_obj.returncode != 0:
        return "FAIL", [f"CANDIDATE_COMMIT_NOT_FOUND: candidate_commit '{anc}' does not exist in Git repository"]

    try:
        rc_desc_obj = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-e", f"{desc}^{{commit}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except Exception as exc:
        return "NOT_VERIFIABLE", [f"GIT_ANCESTRY_ERROR: failed inspecting PR head '{desc}': {exc}"]

    if rc_desc_obj.returncode != 0:
        if allow_remote_compare and repository:
            cmp_ok, cmp_status, cmp_err = _query_compare_via_api_or_gh(repository, anc, desc)
            if cmp_ok and cmp_status is not None:
                if cmp_status in ("identical", "ahead"):
                    return "PASS", []
                return "FAIL", [
                    f"CANDIDATE_COMMIT_NOT_ANCESTOR_OF_PR_HEAD: remote compare '{anc}...{desc}' returned status='{cmp_status}'"
                ]
            return "NOT_VERIFIABLE", [
                f"PR_HEAD_COMMIT_NOT_LOCAL_AND_COMPARE_FAILED: PR head '{desc}' is not in local git objects and compare API failed ({cmp_err})"
            ]
        return "NOT_VERIFIABLE", [
            f"PR_HEAD_COMMIT_NOT_IN_LOCAL_GIT: actual PR head '{desc}' does not exist in local Git repository"
        ]

    try:
        rc_merge = subprocess.run(
            ["git", "-C", str(project_root), "merge-base", "--is-ancestor", anc, desc],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except Exception as exc:
        return "NOT_VERIFIABLE", [f"GIT_ANCESTRY_ERROR: merge-base check failed: {exc}"]

    if rc_merge.returncode == 0:
        return "PASS", []
    if rc_merge.returncode == 1:
        return "FAIL", [
            f"CANDIDATE_COMMIT_NOT_ANCESTOR_OF_PR_HEAD: candidate_commit '{anc}' is NOT an ancestor of PR HEAD '{desc}'"
        ]
    return "NOT_VERIFIABLE", [
        f"GIT_ANCESTRY_ERROR: merge-base returned exit_code={rc_merge.returncode}: {(rc_merge.stderr or '').strip()}"
    ]


def load_trusted_github_pr_event(event_path: Optional[str | Path] = None) -> Optional[Dict[str, Any]]:
    """Load GitHub Actions event JSON from GITHUB_EVENT_PATH if available."""
    raw_path = str(event_path or os.environ.get("GITHUB_EVENT_PATH", "")).strip()
    if not raw_path:
        return None
    p = Path(raw_path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def verify_candidate_pr_merge_event(
    pr_event: Dict[str, Any],
    expected_pr_number: int,
    expected_candidate_commit: str,
    expected_owner: str,
    expected_base: str = "main",
    forbidden_historical_merge_commits: Optional[set[str]] = None,
    project_root: Optional[Path] = None,
    repository: Optional[str] = None,
) -> Tuple[bool, List[str], Optional[str], Optional[str]]:
    """Verify a GitHub PR API event before allowing current candidate PR status=MERGED (Rule C).
    Requires merged=true, merged_by==expected_owner, base.ref==expected_base ('main'),
    head.sha valid & candidate_commit is an ancestor of head.sha, and a valid non-historical merge_commit_sha.
    """
    errors: List[str] = []
    if not isinstance(pr_event, dict):
        return False, ["CANDIDATE_PR_MERGE_EVENT_INVALID: PR merge event payload must be an object"], None, None

    ev_num = pr_event.get("number")
    if ev_num is not None and int(ev_num) != int(expected_pr_number):
        errors.append(
            f"CANDIDATE_PR_NUMBER_MISMATCH: PR merge event number={ev_num} != candidate_pr_number={expected_pr_number}"
        )

    if pr_event.get("merged") is not True:
        errors.append("CANDIDATE_PR_NOT_MERGED: GitHub PR API event does not confirm merged=true")

    merged_by_raw = pr_event.get("merged_by")
    if isinstance(merged_by_raw, dict):
        merged_by_login = str(merged_by_raw.get("login") or "").strip()
    else:
        merged_by_login = str(merged_by_raw or "").strip()
    if not merged_by_login:
        errors.append("CANDIDATE_PR_MERGED_BY_MISSING: GitHub PR API event missing merged_by")
    elif merged_by_login != expected_owner:
        errors.append(
            f"CANDIDATE_PR_MERGED_BY_UNAUTHORIZED: merged_by='{merged_by_login}' != expected owner '{expected_owner}'"
        )

    base_raw = pr_event.get("base")
    base_ref = str(base_raw.get("ref") if isinstance(base_raw, dict) else pr_event.get("base_ref") or "").strip()
    if base_ref != expected_base:
        errors.append(
            f"CANDIDATE_PR_BASE_NOT_MAIN: PR merge event base.ref='{base_ref}' != '{expected_base}'"
        )

    head_raw = pr_event.get("head")
    head_sha = str(head_raw.get("sha") if isinstance(head_raw, dict) else pr_event.get("head_sha") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha) or head_sha == "0" * 40:
        errors.append(f"CANDIDATE_PR_INVALID_HEAD: PR merge event head.sha='{head_sha}' is not a non-zero 40-hex SHA")
    elif expected_candidate_commit:
        if project_root is not None and (Path(project_root) / ".git").exists():
            anc_st, anc_errs = verify_commit_ancestry(
                Path(project_root),
                expected_candidate_commit,
                head_sha,
                repository=repository,
                allow_remote_compare=True,
            )
            if anc_st != "PASS" and head_sha != expected_candidate_commit:
                errors.extend(anc_errs or [f"CANDIDATE_PR_HEAD_MISMATCH: head.sha='{head_sha}' != candidate_commit='{expected_candidate_commit}'"])
        elif head_sha != expected_candidate_commit:
            errors.append(
                f"CANDIDATE_PR_HEAD_MISMATCH: PR merge event head.sha='{head_sha}' != candidate_commit='{expected_candidate_commit}'"
            )

    merge_commit_sha = str(pr_event.get("merge_commit_sha") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", merge_commit_sha) or merge_commit_sha == "0" * 40:
        errors.append(
            f"CANDIDATE_PR_INVALID_MERGE_COMMIT: merge_commit_sha='{merge_commit_sha}' must be a non-zero 40-hex SHA"
        )
    elif forbidden_historical_merge_commits and merge_commit_sha in forbidden_historical_merge_commits:
        errors.append(
            f"CANDIDATE_PR_HISTORICAL_MERGE_COMMIT_POLLUTION: merge_commit_sha='{merge_commit_sha}' belongs to a historical release PR"
        )

    if errors:
        return False, errors, None, None
    return True, [], merge_commit_sha, merged_by_login


def verify_live_pr_identity(
    project_root: Path,
    repository: str,
    candidate_pr_number: int,
    candidate_commit: str,
    expected_pr_status: Optional[str] = None,
    expected_pr_draft: Optional[bool] = None,
    expected_base_ref: str = "main",
    expected_owner: Optional[str] = None,
    forbidden_historical_merge_commits: Optional[set[str]] = None,
    require_live: bool = False,
    allow_merged_on_main: bool = True,
    simulate_pr_data: Optional[Dict[str, Any]] = None,
    simulate_pr_error: Optional[str] = None,
    simulate_event_data: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Tuple[str, List[str], Dict[str, Any]]:
    """Shared live PR identity & commit ancestry verifier for BOTH Baseline and Handoff (F13 + F14).

    Verifies:
      1. candidate_commit exists in Git.
      2. Real GitHub PR API (or simulated API response in unit tests) for repository, number, state,
         draft, base.ref, and head.sha; NEVER trusts static self-references when API is unavailable.
      3. On pull_request CI events, reads event pull_request.head.sha (NEVER GITHUB_SHA merge ref).
      4. On push CI events, checks GITHUB_SHA + GitHub PR API.
      5. Verifies `git merge-base --is-ancestor <candidate_commit> <actual_pr_head>`.
      6. If GitHub API unavailable: returns NOT_VERIFIABLE offline, or FAIL (BLOCK) when require_live=True.
    """
    project_root = Path(project_root).resolve()
    eff_owner = (expected_owner or repository.split("/")[0]).strip()
    details: Dict[str, Any] = {
        "repository": repository,
        "candidate_pr_number": candidate_pr_number,
        "candidate_commit": candidate_commit,
        "source": None,
        "pr_head_sha": None,
        "pr_state": None,
        "pr_draft": None,
        "pr_base": None,
        "pr_merged": None,
        "pr_merged_by": None,
        "merge_commit_sha": None,
        "ancestry_status": None,
        "verification_status": "NOT_VERIFIABLE",
    }

    try:
        pr_num_int = int(candidate_pr_number)
    except Exception:
        return "FAIL", [f"CANDIDATE_PR_INVALID_NUMBER: '{candidate_pr_number}' is not an integer"], details
    if pr_num_int < 1:
        return "FAIL", [f"CANDIDATE_PR_INVALID_NUMBER: candidate_pr_number must be >= 1 (got {pr_num_int})"], details

    if not re.fullmatch(r"[0-9a-f]{40}", str(candidate_commit or "")) or candidate_commit == "0" * 40:
        return "FAIL", [f"CANDIDATE_COMMIT_INVALID: '{candidate_commit}' must be a non-zero 40-hex commit SHA"], details

    if (project_root / ".git").exists():
        rc_cand = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-e", f"{candidate_commit}^{{commit}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if rc_cand.returncode != 0:
            return "FAIL", [
                f"CANDIDATE_COMMIT_NOT_FOUND: candidate_commit '{candidate_commit}' does not exist in Git repository"
            ], details

    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    event_data = simulate_event_data if simulate_event_data is not None else load_trusted_github_pr_event()
    event_pr: Optional[Dict[str, Any]] = None
    if isinstance(event_data, dict) and isinstance(event_data.get("pull_request"), dict):
        if simulate_event_data is not None or event_name.startswith("pull_request"):
            event_pr = event_data["pull_request"]
            ev_repo = (event_data.get("repository") or {}).get("full_name") if isinstance(event_data.get("repository"), dict) else None
            if ev_repo and str(ev_repo).strip() != repository:
                return "FAIL", [
                    f"LIVE_PR_EVENT_REPOSITORY_MISMATCH: event repo='{ev_repo}' != '{repository}'"
                ], details

    # Acquire PR API object (fail closed if unavailable in online/strict mode; never fall back to static cache)
    if simulate_pr_error is not None:
        api_ok = False
        api_pr = None
        api_err = simulate_pr_error
    elif simulate_pr_data is not None:
        api_ok = True
        api_pr = simulate_pr_data
        api_err = ""
        details["source"] = "github_pr_api_simulated"
    else:
        api_ok, api_pr, api_err = _query_pr_via_api(repository, pr_num_int, timeout=timeout)
        if api_ok and api_pr is not None:
            details["source"] = "github_rest_api"
        else:
            api_ok, api_pr, gh_err = _query_pr_via_gh(repository, pr_num_int, timeout=timeout)
            if api_ok and api_pr is not None:
                details["source"] = "gh_cli_api"
            else:
                api_err = f"{api_err}; gh fallback: {gh_err}" if api_err else gh_err

    if not api_ok or api_pr is None:
        clean_err = _sanitize_error_message(api_err or "GitHub PR API unavailable")
        details["verification_status"] = "NOT_VERIFIABLE"
        details["reason"] = f"LIVE_PR_API_UNAVAILABLE: {clean_err}"
        if require_live:
            return "FAIL", [
                f"LIVE_PR_API_BLOCKED: Real GitHub PR API unavailable in online/strict CI mode: {clean_err}"
            ], details
        return "NOT_VERIFIABLE", [
            f"LIVE_PR_API_NOT_VERIFIABLE: GitHub PR API unavailable offline: {clean_err}"
        ], details

    errors: List[str] = []

    # 1. Repository binding (Rule F14 requires verifying repository)
    actual_repo = _extract_repo_from_pr_payload(api_pr)
    details["actual_repository"] = actual_repo
    if not actual_repo:
        errors.append("LIVE_PR_REPOSITORY_MISSING: GitHub PR API payload missing repository full_name")
    elif actual_repo != repository:
        errors.append(f"LIVE_PR_REPOSITORY_MISMATCH: expected '{repository}', got '{actual_repo}'")

    # 2. PR Number binding
    actual_num = api_pr.get("number")
    if actual_num is None:
        errors.append("LIVE_PR_NUMBER_MISSING: GitHub PR API payload missing 'number'")
    elif int(actual_num) != pr_num_int:
        errors.append(f"LIVE_PR_NUMBER_MISMATCH: expected PR #{pr_num_int}, got PR #{actual_num}")

    if event_pr is not None and event_pr.get("number") is not None:
        if int(event_pr["number"]) != pr_num_int:
            errors.append(
                f"LIVE_PR_EVENT_NUMBER_MISMATCH: pull_request event number={event_pr['number']} != PR #{pr_num_int}"
            )

    # 3. Base branch binding
    actual_base = str((api_pr.get("base") or {}).get("ref") or "").strip()
    details["pr_base"] = actual_base or None
    if actual_base != expected_base_ref:
        errors.append(
            f"CANDIDATE_PR_BASE_NOT_MAIN: live PR #{pr_num_int} base.ref='{actual_base}' != '{expected_base_ref}'"
        )
    if event_pr is not None:
        ev_base = str((event_pr.get("base") or {}).get("ref") or "").strip()
        if ev_base and ev_base != expected_base_ref:
            errors.append(
                f"CANDIDATE_PR_EVENT_BASE_NOT_MAIN: event pull_request.base.ref='{ev_base}' != '{expected_base_ref}'"
            )

    # 4. Head SHA binding (NEVER use GITHUB_SHA in pull_request workflow as PR head)
    api_head = str((api_pr.get("head") or {}).get("sha") or "").strip()
    ev_head = str((event_pr.get("head") or {}).get("sha") or "").strip() if event_pr is not None else ""
    effective_pr_head = ev_head or api_head
    details["pr_head_sha"] = effective_pr_head or None
    details["api_pr_head_sha"] = api_head or None

    if not re.fullmatch(r"[0-9a-f]{40}", api_head) or api_head == "0" * 40:
        errors.append(f"LIVE_PR_HEAD_INVALID: live PR API head.sha='{api_head}' must be a non-zero 40-hex SHA")
    if event_pr is not None and ev_head:
        if not re.fullmatch(r"[0-9a-f]{40}", ev_head) or ev_head == "0" * 40:
            errors.append(f"LIVE_PR_EVENT_HEAD_INVALID: event pull_request.head.sha='{ev_head}' is invalid")

    # 5. State, draft, and merge provenance checks
    raw_state = str(api_pr.get("state") or "").strip().lower()
    live_merged = api_pr.get("merged") is True
    live_draft = bool(api_pr.get("draft", False))
    details["pr_state"] = raw_state.upper() if raw_state else None
    details["pr_draft"] = live_draft
    details["pr_merged"] = live_merged

    if event_pr is not None and event_pr.get("draft") is not None:
        ev_draft = bool(event_pr.get("draft"))
        if ev_draft != live_draft and expected_pr_draft is not None and ev_draft != expected_pr_draft:
            errors.append(
                f"CANDIDATE_PR_EVENT_DRAFT_MISMATCH: event pull_request.draft={ev_draft} != expected {expected_pr_draft}"
            )

    exp_status_norm = str(expected_pr_status).strip().upper() if expected_pr_status else None
    is_main_push = (
        event_name == "push"
        and os.environ.get("GITHUB_REF", "").strip() == f"refs/heads/{expected_base_ref}"
    )

    if live_merged:
        m_ok, m_errs, m_sha, m_by = verify_candidate_pr_merge_event(
            pr_event=api_pr,
            expected_pr_number=pr_num_int,
            expected_candidate_commit=candidate_commit,
            expected_owner=eff_owner,
            expected_base=expected_base_ref,
            forbidden_historical_merge_commits=forbidden_historical_merge_commits,
            project_root=project_root,
            repository=repository,
        )
        details["merge_commit_sha"] = m_sha
        details["pr_merged_by"] = m_by
        if not m_ok:
            errors.extend(m_errs)
        if exp_status_norm in ("OPEN", "DRAFT") and not (is_main_push and allow_merged_on_main):
            errors.append(
                f"LIVE_PR_STATE_MISMATCH: expected '{exp_status_norm}', but live PR #{pr_num_int} is already MERGED"
            )
    else:
        if exp_status_norm == "MERGED":
            errors.append(
                f"CANDIDATE_PR_NOT_MERGED: static expectation is MERGED, but live PR #{pr_num_int} has merged={live_merged}, state='{raw_state}'"
            )
        if raw_state != "open":
            errors.append(
                f"LIVE_PR_NOT_OPEN: live PR #{pr_num_int} state='{raw_state}' (expected 'open')"
            )
        if exp_status_norm == "DRAFT" and not live_draft:
            errors.append(
                f"CANDIDATE_PR_DRAFT_MISMATCH: expected PR status DRAFT (draft=true), live PR #{pr_num_int} has draft=false"
            )
        if expected_pr_draft is not None and live_draft != expected_pr_draft:
            errors.append(
                f"CANDIDATE_PR_DRAFT_MISMATCH: expected draft={expected_pr_draft}, live PR #{pr_num_int} has draft={live_draft}"
            )

    # 6. Verify candidate_commit is an ancestor of effective PR head (and push GITHUB_SHA on branch push)
    if re.fullmatch(r"[0-9a-f]{40}", effective_pr_head):
        anc_st, anc_errs = verify_commit_ancestry(
            project_root,
            candidate_commit,
            effective_pr_head,
            repository=repository,
            allow_remote_compare=True,
        )
        details["ancestry_status"] = anc_st
        if anc_st == "FAIL":
            errors.extend(anc_errs)
        elif anc_st == "NOT_VERIFIABLE":
            if require_live:
                errors.extend(anc_errs)
            else:
                details["verification_status"] = "NOT_VERIFIABLE"
                return "NOT_VERIFIABLE", errors + anc_errs, details

    if event_name == "push":
        push_sha = os.environ.get("GITHUB_SHA", "").strip()
        push_ref = os.environ.get("GITHUB_REF", "").strip()
        pr_head_ref = str((api_pr.get("head") or {}).get("ref") or "").strip()
        if (
            re.fullmatch(r"[0-9a-f]{40}", push_sha)
            and pr_head_ref
            and push_ref == f"refs/heads/{pr_head_ref}"
        ):
            p_anc_st, p_anc_errs = verify_commit_ancestry(
                project_root,
                candidate_commit,
                push_sha,
                repository=repository,
                allow_remote_compare=False,
            )
            if p_anc_st != "PASS":
                errors.extend(p_anc_errs)

    if errors:
        details["verification_status"] = "FAIL"
        return "FAIL", errors, details

    details["verification_status"] = "PASS"
    return "PASS", [], details


def extract_scoped_markdown(content: str, scope_tag: str) -> Tuple[str, List[str]]:
    """Extract content under the unique markdown heading containing scope_tag."""
    lines = content.splitlines()
    matches = []
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and scope_tag in m.group(2):
            matches.append((idx, len(m.group(1)), line))

    if len(matches) == 0:
        return "", [f"SCOPE_SECTION_MISSING: Scope section '{scope_tag}' not found"]
    if len(matches) > 1:
        return "", [f"DUPLICATE_SCOPE_SECTION: Duplicate scope section '{scope_tag}' found ({len(matches)} occurrences)"]

    start_idx, start_lvl, _ = matches[0]
    scoped_lines: List[str] = []
    for i in range(start_idx, len(lines)):
        m = re.match(r"^(#{1,6})\s+(.*)$", lines[i])
        if m and i > start_idx and len(m.group(1)) <= start_lvl:
            break
        scoped_lines.append(lines[i])
    return "\n".join(scoped_lines), []


def _extract_bullet_line_matches(target_text: str, patterns: List[str]) -> List[str]:
    matches: List[str] = []
    seen_spans: set[Tuple[int, int, int]] = set()
    for line_index, raw_line in enumerate(target_text.splitlines()):
        line = raw_line.strip()
        if not (line.startswith("- **") or line.startswith("**") or line.startswith("- ")):
            continue
        for pat in patterns:
            for match in re.finditer(pat, line):
                s, e = match.span(1)
                key = (line_index, s, e)
                if key in seen_spans:
                    continue
                seen_spans.add(key)
                matches.append(match.group(1))
    return matches


def verify_candidate_pr_section(
    content: str,
    version_str: str,
    repository: str = "xiefeifeihu/AI-Engineering-Standards",
    project_root: Optional[Path] = None,
    historical_merge_commits: Optional[set[str]] = None,
    historical_candidate_commits: Optional[set[str]] = None,
    expected_facts: Optional[Dict[str, Any]] = None,
    verify_live_pr: bool = False,
    require_live_pr: bool = False,
    simulate_pr_data: Optional[Dict[str, Any]] = None,
    simulate_pr_error: Optional[str] = None,
    simulate_event_data: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], Optional[Dict[str, Any]], Optional[str]]:
    """Shared verifier for the CURRENT_CANDIDATE_PR section in both Baseline and Handoff (F13 + F14).

    Returns (errors, live_pr_details, live_pr_status).
      - Static document does NOT require self-referencing `candidate_pr_head`.
      - When `candidate_pr_head` is explicitly provided (in doc or expected_facts), verifies
        `candidate_commit` is an ancestor of `candidate_pr_head` via Git ancestry (NOT equality).
      - When `verify_live_pr=True` and `candidate_pr_number` is present, executes real GitHub PR API
        + ancestry verification via verify_live_pr_identity().
    """
    scope_text, scope_errs = extract_scoped_markdown(content, "CURRENT_CANDIDATE_PR")
    if scope_errs:
        return scope_errs, None, None

    errors: List[str] = []

    def _extract_unique(field_label: str, pattern: str, required: bool = True) -> Optional[str]:
        matches = _extract_bullet_line_matches(scope_text, [pattern])
        if len(matches) == 0:
            if required:
                errors.append(f"CANDIDATE_PR_MISSING_FIELD: '{field_label}' missing from CURRENT_CANDIDATE_PR")
            return None
        if len(matches) > 1:
            errors.append(
                f"CANDIDATE_PR_DUPLICATE_FIELD: '{field_label}' appears {len(matches)} times in CURRENT_CANDIDATE_PR"
            )
            return None
        return matches[0].strip()

    rec_ver = _extract_unique("candidate_version", r"candidate_version[^:：\n]*?[:：]\s*`([^`]+)`")
    rec_pr_num = _extract_unique("candidate_pr_number", r"candidate_pr_number[^:：\n]*?[:：]\s*`([^`]+)`")
    rec_pr_status = _extract_unique("candidate_pr_status", r"candidate_pr_status[^:：\n]*?[:：]\s*`([A-Z_]+)`")
    rec_pr_state = _extract_unique("PR_STATE", r"PR_STATE[^:：\n]*?[:：]\s*`([A-Z_]+)`")
    rec_pr_draft = _extract_unique("PR_DRAFT", r"PR_DRAFT[^:：\n]*?[:：]\s*`(true|false)`")
    rec_pr_head = _extract_unique(
        "candidate_pr_head", r"candidate_pr_head[^:：\n]*?[:：]\s*`([0-9a-f]{40})`", required=False
    )
    rec_pr_base = _extract_unique("candidate_pr_base", r"candidate_pr_base[^:：\n]*?[:：]\s*`([^`]+)`")
    rec_cand_commit = _extract_unique("candidate_commit", r"candidate_commit[^:：\n]*?[:：]\s*`([0-9a-f]{40})`")
    rec_rel_status = _extract_unique("RELEASE_STATUS", r"RELEASE_STATUS[^:：\n]*?[:：]\s*`([A-Z_]+)`")

    if rec_ver is not None and rec_ver != version_str:
        errors.append(
            f"CANDIDATE_PR_VERSION_MISMATCH: committed candidate_version='{rec_ver}' != VERSION='{version_str}'"
        )

    if rec_pr_base is not None and rec_pr_base != "main":
        errors.append(f"CANDIDATE_PR_BASE_NOT_MAIN: committed candidate_pr_base='{rec_pr_base}' != 'main'")

    if rec_pr_status is not None:
        if rec_pr_status not in ("DRAFT", "OPEN", "MERGED", "CLOSED"):
            errors.append(f"CANDIDATE_PR_INVALID_STATUS: committed candidate_pr_status='{rec_pr_status}'")
        elif rec_pr_status == "DRAFT":
            if rec_pr_state != "OPEN":
                errors.append(f"CANDIDATE_PR_STATE_MISMATCH: DRAFT requires PR_STATE='OPEN' (got '{rec_pr_state}')")
            if rec_pr_draft != "true":
                errors.append(f"CANDIDATE_PR_DRAFT_MISMATCH: DRAFT requires PR_DRAFT='true' (got '{rec_pr_draft}')")
            if rec_rel_status != "CANDIDATE":
                errors.append(
                    f"CANDIDATE_PR_RELEASE_STATUS_MISMATCH: DRAFT requires RELEASE_STATUS='CANDIDATE' (got '{rec_rel_status}')"
                )
        elif rec_pr_status == "OPEN":
            if rec_pr_state != "OPEN":
                errors.append(f"CANDIDATE_PR_STATE_MISMATCH: OPEN requires PR_STATE='OPEN' (got '{rec_pr_state}')")
            if rec_rel_status != "CANDIDATE":
                errors.append(
                    f"CANDIDATE_PR_RELEASE_STATUS_MISMATCH: OPEN requires RELEASE_STATUS='CANDIDATE' (got '{rec_rel_status}')"
                )
        elif rec_pr_status == "MERGED":
            if rec_pr_state != "MERGED":
                errors.append(f"CANDIDATE_PR_STATE_MISMATCH: MERGED requires PR_STATE='MERGED' (got '{rec_pr_state}')")
            if rec_pr_draft != "false":
                errors.append(f"CANDIDATE_PR_DRAFT_MISMATCH: MERGED requires PR_DRAFT='false' (got '{rec_pr_draft}')")
            merge_sha = _extract_unique(
                "candidate_pr_merge_commit",
                r"candidate_pr_merge_commit[^:：\n]*?[:：]\s*`([0-9a-f]{40})`",
            )
            _extract_unique(
                "candidate_pr_merged_by",
                r"candidate_pr_merged_by[^:：\n]*?[:：]\s*`([A-Za-z0-9_-]+)`",
            )
            if merge_sha and historical_merge_commits and merge_sha in historical_merge_commits:
                errors.append(
                    f"CANDIDATE_PR_HISTORICAL_MERGE_COMMIT_POLLUTION: committed merge commit '{merge_sha}' is from a historical release PR"
                )

        if rec_pr_status in ("DRAFT", "OPEN"):
            if re.search(r"\bMERGED\b|已合入|candidate_pr_merge_commit", scope_text):
                errors.append(
                    "CANDIDATE_PR_UNMERGED_HAS_MERGED_TEXT: unmerged candidate PR section must not contain MERGED / 已合入 wording"
                )

    if version_str != "3.0.0":
        if rec_pr_num in ("9", "10"):
            errors.append(
                f"CANDIDATE_PR_HISTORICAL_NUMBER_POLLUTION: candidate_pr_number='{rec_pr_num}' is a historical v3.0.0 PR"
            )
        if re.search(r"PR\s*#(9|10)\b", scope_text):
            errors.append(
                "CANDIDATE_PR_HISTORICAL_PR_POLLUTION: CURRENT_CANDIDATE_PR section must not reference historical PR #9 / PR #10"
            )
        if rec_cand_commit and historical_candidate_commits and rec_cand_commit in historical_candidate_commits:
            errors.append(
                f"CANDIDATE_PR_HISTORICAL_COMMIT_POLLUTION: candidate_commit='{rec_cand_commit}' belongs to historical v3.0.0 evidence"
            )
        sec9_top = re.search(r"## 9\. 最近 CI 事实.*?(?=\n### |\n## 10\.|\Z)", content, re.S)
        if sec9_top:
            for line in sec9_top.group(0).splitlines():
                if line.strip().startswith("- **事实说明**"):
                    if re.search(r"PR\s*#(9|10)\b", line):
                        errors.append(
                            "CANDIDATE_PR_HISTORICAL_CI_SUMMARY_POLLUTION: Section 9 summary references historical PR #9 / PR #10"
                        )
                    if rec_pr_status in ("DRAFT", "OPEN") and ("已合入 main" in line or "MERGED" in line):
                        errors.append(
                            "CANDIDATE_PR_UNMERGED_SUMMARY_HAS_MERGED_TEXT: Section 9 summary claims MERGED for unmerged candidate PR"
                        )

    # Verify candidate_commit is a real Git commit (F13 Rule 2)
    if project_root is not None and rec_cand_commit and (project_root / ".git").exists():
        res_obj = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-e", f"{rec_cand_commit}^{{commit}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if res_obj.returncode != 0:
            errors.append(
                f"CANDIDATE_PR_COMMIT_NOT_FOUND: committed candidate_commit '{rec_cand_commit}' does not exist in Git repository"
            )

    # If a PR head is explicitly supplied (in expected_facts or legacy text), validate ancestry (NOT equality)
    explicit_head = (expected_facts or {}).get("candidate_pr_head") or rec_pr_head
    if explicit_head and rec_cand_commit and project_root is not None and (project_root / ".git").exists():
        anc_st, anc_errs = verify_commit_ancestry(
            project_root,
            rec_cand_commit,
            str(explicit_head).strip(),
            repository=repository,
            allow_remote_compare=True,
        )
        if anc_st == "FAIL":
            errors.extend(anc_errs)
        elif anc_st == "NOT_VERIFIABLE" and require_live_pr:
            errors.extend(anc_errs)

    if expected_facts:
        actual_map: Dict[str, Optional[str]] = {
            "candidate_version": rec_ver,
            "candidate_pr_number": rec_pr_num,
            "candidate_pr_status": rec_pr_status,
            "pr_state": rec_pr_state,
            "pr_draft": rec_pr_draft,
            "candidate_pr_base": rec_pr_base,
            "candidate_commit": rec_cand_commit,
            "release_status": rec_rel_status,
        }
        for k, exp_v in expected_facts.items():
            if exp_v is None or k == "candidate_pr_head":
                continue
            exp_str = str(exp_v).lower() if isinstance(exp_v, bool) else str(exp_v).strip()
            act_v = actual_map.get(k)
            if act_v is None:
                errors.append(f"CANDIDATE_PR_EXPECTED_FIELD_MISSING: '{k}' missing (expected '{exp_str}')")
            elif str(act_v).strip() != exp_str:
                errors.append(
                    f"CANDIDATE_PR_EXPECTED_FIELD_MISMATCH: '{k}' committed='{act_v}' != expected='{exp_str}'"
                )

    live_details: Optional[Dict[str, Any]] = None
    live_status: Optional[str] = None
    if verify_live_pr:
        eff_pr_num_str = str((expected_facts or {}).get("candidate_pr_number") or rec_pr_num or "").strip()
        if not eff_pr_num_str.isdigit():
            live_status = "FAIL"
            errors.append(
                f"CANDIDATE_PR_NUMBER_REQUIRED_FOR_LIVE_VERIFY: cannot live-verify PR without valid candidate_pr_number (got '{eff_pr_num_str}')"
            )
        elif rec_cand_commit:
            exp_draft_bool: Optional[bool] = None
            if rec_pr_draft in ("true", "false"):
                exp_draft_bool = rec_pr_draft == "true"
            live_status, live_errs, live_details = verify_live_pr_identity(
                project_root=project_root or Path(".").resolve(),
                repository=repository,
                candidate_pr_number=int(eff_pr_num_str),
                candidate_commit=rec_cand_commit,
                expected_pr_status=rec_pr_status,
                expected_pr_draft=exp_draft_bool,
                expected_base_ref="main",
                forbidden_historical_merge_commits=historical_merge_commits,
                require_live=require_live_pr,
                simulate_pr_data=simulate_pr_data,
                simulate_pr_error=simulate_pr_error,
                simulate_event_data=simulate_event_data,
            )
            if live_status == "FAIL":
                errors.extend(live_errs)
            elif live_status == "NOT_VERIFIABLE" and require_live_pr:
                errors.extend(live_errs)

    return errors, live_details, live_status


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verify release evidence and GitHub CI authenticity")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--evidence", default=None)
    parser.add_argument("--all", action="store_true", help="Verify all release evidence files in docs/release-evidence/")
    parser.add_argument("--check-ci", action="store_true", help="Live verify GitHub CI runs")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if args.evidence:
        target_files = [resolve_release_evidence_path(root, args.evidence)]
    elif args.all:
        rev_dir = root / "docs" / "release-evidence"
        if rev_dir.exists():
            target_files = sorted(rev_dir.glob("*.json"))
        else:
            target_files = [resolve_release_evidence_path(root)]
    else:
        target_files = [resolve_release_evidence_path(root)]

    overall_ok = True
    for ev_path in target_files:
        ok, errors, ev = load_release_evidence(root, ev_path)
        if not ok or ev is None:
            print(f"[FAIL] Release evidence invalid at '{ev_path.name}':")
            for e in errors:
                print(f"  - {e}")
            overall_ok = False
            continue

        print(f"[PASS] Release evidence valid ({ev_path.name}): version={ev['version']}, CI_commit={ev['last_verified_ci_commit'][:8]}")

        if args.check_ci:
            st, ci_errs, details = verify_github_ci_runs(ev, project_root=root)
            print(f"CI Authenticity Status ({ev_path.name}): {st}")
            if ci_errs:
                for e in ci_errs:
                    print(f"  - {e}")
            if st != "PASS":
                overall_ok = False

    if not overall_ok:
        sys.exit(1)
