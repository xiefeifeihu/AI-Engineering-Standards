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
    "pr_run_id",
    "ci_status",
    "test_count",
    "test_failed",
    "test_skipped",
    "windows_status",
    "ubuntu_status",
    "old_tag_deleted",
    "old_tag_object",
    "old_tag_peeled_commit",
    "old_tag_bundle_sha256",
    "release_flow_status",
)


def resolve_release_evidence_path(
    project_root: Path,
    explicit_path: Optional[str | Path] = None,
    version: Optional[str] = None,
) -> Path:
    project_root = Path(project_root).resolve()
    if explicit_path:
        p = Path(explicit_path)
        return p.resolve() if p.is_absolute() else (project_root / p).resolve()

    ver_str = (version or "3.0.0").lstrip("v")
    candidate = project_root / "docs" / "release-evidence" / f"v{ver_str}-reissue.json"
    if candidate.exists():
        return candidate

    fallback = project_root / "docs" / "release-evidence" / "v3.0.0-reissue.json"
    if fallback.exists():
        return fallback

    # Check any json in release-evidence dir
    rev_dir = project_root / "docs" / "release-evidence"
    if rev_dir.exists():
        json_files = sorted(rev_dir.glob("*.json"))
        if json_files:
            return json_files[0]

    return candidate


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

    # Validate commit hashes
    for sha_field in (
        "main_head",
        "candidate_commit",
        "snapshot_commit",
        "last_verified_ci_commit",
        "old_tag_object",
        "old_tag_peeled_commit",
    ):
        val = str(data.get(sha_field, ""))
        if not re.match(r"^[0-9a-f]{40}$", val):
            errors.append(
                f"RELEASE_EVIDENCE_INVALID_SHA: '{sha_field}' must be a 40-hex commit SHA (got '{val}')"
            )

    bundle_sha = str(data.get("old_tag_bundle_sha256", ""))
    if not re.match(r"^[0-9a-f]{64}$", bundle_sha):
        errors.append(
            f"RELEASE_EVIDENCE_INVALID_BUNDLE_SHA: 'old_tag_bundle_sha256' must be a 64-hex SHA (got '{bundle_sha}')"
        )

    if not isinstance(data.get("old_tag_deleted"), bool):
        errors.append(
            f"RELEASE_EVIDENCE_INVALID_TYPE: 'old_tag_deleted' must be a boolean (got {type(data.get('old_tag_deleted')).__name__})"
        )

    push_id = str(data.get("push_run_id", "")).strip()
    if not push_id.isdigit():
        errors.append(f"RELEASE_EVIDENCE_INVALID_RUN_ID: 'push_run_id' must be numeric (got '{push_id}')")

    pr_id = str(data.get("pr_run_id", "")).strip()
    if not pr_id.isdigit():
        errors.append(f"RELEASE_EVIDENCE_INVALID_RUN_ID: 'pr_run_id' must be numeric (got '{pr_id}')")

    # Validate against JSON schema if present
    schema_path = project_root / "schemas" / "release-evidence.schema.json"
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


def _query_run_via_gh(
    repo: str,
    run_id: str,
    timeout: int = 10,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    try:
        cmd = [
            "gh",
            "run",
            "view",
            str(run_id),
            "--repo",
            repo,
            "--json",
            "name,headSha,event,status,conclusion,workflowDatabaseId,jobs",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if res.returncode == 0 and res.stdout.strip():
            parsed = json.loads(res.stdout)
            return True, parsed, ""
        return False, None, res.stderr or "gh command returned non-zero exit code"
    except Exception as e:
        return False, None, str(e)


def _query_run_via_api(
    repo: str,
    run_id: str,
    token: Optional[str] = None,
    timeout: int = 10,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return False, None, "No GitHub token available for API query"

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "AI-Engineering-Standards-Verifier",
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
        return False, None, str(e)


def verify_single_github_run(
    repo: str,
    run_id: str,
    expected_event: str,
    expected_head_sha: str,
    timeout: int = 10,
    simulate_data: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[str], Dict[str, Any]]:
    """Verify an individual GitHub Actions run against requirements.
    Never outputs tokens. Returns status: 'PASS', 'FAIL', or 'NOT_VERIFIABLE'.
    """
    errors: List[str] = []
    run_meta: Dict[str, Any] = {
        "run_id": str(run_id),
        "event": expected_event,
        "head_sha": expected_head_sha,
    }

    if simulate_data is not None:
        run_data = simulate_data
        ok = True
        err_msg = ""
    else:
        ok, run_data, err_msg = _query_run_via_gh(repo, str(run_id), timeout=timeout)
        if not ok:
            ok, run_data, err_msg = _query_run_via_api(repo, str(run_id), timeout=timeout)

    if not ok or run_data is None:
        # Cannot access run (e.g. offline, rate limit, historical run not accessible)
        # Never fake PASS; record NOT_VERIFIABLE
        run_meta["verification_status"] = "NOT_VERIFIABLE"
        run_meta["reason"] = f"GITHUB_CI_NOT_ACCESSIBLE: {err_msg}"
        return "NOT_VERIFIABLE", [f"Run {run_id} not accessible: {err_msg}"], run_meta

    actual_event = run_data.get("event")
    actual_head = run_data.get("headSha") or run_data.get("head_sha")
    actual_conclusion = run_data.get("conclusion")
    actual_status = run_data.get("status")

    run_meta["actual_event"] = actual_event
    run_meta["actual_head_sha"] = actual_head
    run_meta["actual_conclusion"] = actual_conclusion
    run_meta["actual_status"] = actual_status

    if actual_event != expected_event:
        errors.append(f"Run {run_id} event mismatch: expected '{expected_event}', got '{actual_event}'")

    if actual_head != expected_head_sha:
        errors.append(f"Run {run_id} head_sha mismatch: expected '{expected_head_sha}', got '{actual_head}'")

    if actual_conclusion != "success":
        errors.append(f"Run {run_id} conclusion was '{actual_conclusion}', expected 'success'")

    # Validate Ubuntu and Windows jobs
    jobs = run_data.get("jobs", [])
    ubuntu_job = None
    windows_job = None
    for j in jobs:
        name = j.get("name", "").lower()
        if "ubuntu" in name:
            ubuntu_job = j
        elif "windows" in name:
            windows_job = j

    if ubuntu_job is None:
        errors.append(f"Run {run_id} is missing Ubuntu validation job")
    else:
        u_concl = ubuntu_job.get("conclusion")
        run_meta["ubuntu_conclusion"] = u_concl
        if u_concl != "success":
            errors.append(f"Run {run_id} Ubuntu job conclusion was '{u_concl}', expected 'success'")

    if windows_job is None:
        errors.append(f"Run {run_id} is missing Windows validation job")
    else:
        w_concl = windows_job.get("conclusion")
        run_meta["windows_conclusion"] = w_concl
        if w_concl != "success":
            errors.append(f"Run {run_id} Windows job conclusion was '{w_concl}', expected 'success'")

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
) -> Tuple[str, List[str], Dict[str, Any]]:
    """Verify both Push Run and PR Run recorded in release evidence.
    Returns (overall_status, errors, details).
    """
    if simulate_status in ("PASS", "FAIL", "NOT_VERIFIABLE"):
        if simulate_status == "PASS":
            return "PASS", [], {"push_run": {"status": "PASS"}, "pr_run": {"status": "PASS"}}
        elif simulate_status == "NOT_VERIFIABLE":
            return "NOT_VERIFIABLE", ["SIMULATED_NOT_VERIFIABLE"], {"reason": "SIMULATED_OFFLINE"}
        else:
            return "FAIL", ["SIMULATED_CI_FAILURE"], {"reason": "SIMULATED_FAILURE"}

    repo = evidence["repository"]
    head_sha = evidence["last_verified_ci_commit"]
    push_id = str(evidence["push_run_id"])
    pr_id = str(evidence["pr_run_id"])

    sim_push = simulate_data_map.get(push_id) if simulate_data_map else None
    sim_pr = simulate_data_map.get(pr_id) if simulate_data_map else None

    push_st, push_errs, push_meta = verify_single_github_run(
        repo=repo,
        run_id=push_id,
        expected_event="push",
        expected_head_sha=head_sha,
        timeout=timeout,
        simulate_data=sim_push,
    )

    pr_st, pr_errs, pr_meta = verify_single_github_run(
        repo=repo,
        run_id=pr_id,
        expected_event="pull_request",
        expected_head_sha=head_sha,
        timeout=timeout,
        simulate_data=sim_pr,
    )

    all_errors = push_errs + pr_errs
    details = {
        "push_run": push_meta,
        "pr_run": pr_meta,
        "last_verified_ci_commit": head_sha,
    }

    if push_st == "FAIL" or pr_st == "FAIL":
        return "FAIL", all_errors, details

    if push_st == "NOT_VERIFIABLE" or pr_st == "NOT_VERIFIABLE":
        return "NOT_VERIFIABLE", all_errors, details

    return "PASS", [], details


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Verify release evidence and GitHub CI authenticity")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--evidence", default=None)
    parser.add_argument("--check-ci", action="store_true", help="Live verify GitHub CI runs")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    ok, errors, ev = load_release_evidence(root, args.evidence)
    if not ok or ev is None:
        print("[FAIL] Release evidence invalid:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"[PASS] Release evidence valid: version={ev['version']}, CI_commit={ev['last_verified_ci_commit'][:8]}")

    if args.check_ci:
        st, ci_errs, details = verify_github_ci_runs(ev, project_root=root)
        print(f"CI Authenticity Status: {st}")
        if ci_errs:
            for e in ci_errs:
                print(f"  - {e}")
        if st == "FAIL":
            sys.exit(1)
