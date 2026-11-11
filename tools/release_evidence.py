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

    push_branch = data.get("push_head_branch")
    if not isinstance(push_branch, str) or not push_branch.strip():
        errors.append("RELEASE_EVIDENCE_INVALID_BRANCH: 'push_head_branch' must be a non-empty string")

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
    for j in jobs:
        name = j.get("name", "").lower()
        if "ubuntu" in name:
            ubuntu_job = j
        elif "windows" in name:
            windows_job = j

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
        if st != "PASS":
            sys.exit(1)
