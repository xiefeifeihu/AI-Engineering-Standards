#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core implementation for AI Engineering Standards Official Sync Tool (STD-034 / D3-D5)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.request
import jsonschema
import yaml

ROOT_DIR = Path(__file__).resolve().parents[2]
import sys
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.validate_approval_contract import validate_approval_record
from tools.validate_documentation_collection_bridge import run_collection_validation

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SEMVER_TAG_RE = re.compile(r"^refs/tags/(v\d+\.\d+\.\d+)(\^\{\})?$")
DEFAULT_OFFICIAL_REPO = "xiefeifeihu/AI-Engineering-Standards"


def resolve_standards_root(explicit_root: Optional[Path | str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    env_root = os.environ.get("AI_ENGINEERING_STANDARDS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parents[2]


def parse_semver(version_or_tag: str) -> Optional[Tuple[int, int, int]]:
    m = SEMVER_RE.match(str(version_or_tag).strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def run_git(repo_dir: Path, args: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_dir)] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return res.returncode, (res.stdout or "").strip(), (res.stderr or "").strip()
    except subprocess.TimeoutExpired as te:
        return 124, "", f"TIMEOUT: {te}"
    except Exception as e:
        return 1, "", str(e)


def query_remote_ls_remote(
    remote_url: str,
    cwd: Optional[Path] = None,
    timeout: int = 10,
) -> Tuple[str, Dict[str, str], str]:
    """Run git ls-remote against remote_url to fetch heads/main and tags.
    Returns (status, refs_map, error_msg). On network failure or timeout, returns NOT_VERIFIABLE.
    """
    cmd = ["git"]
    if cwd:
        cmd.extend(["-C", str(cwd)])
    cmd.extend(["ls-remote", "--heads", "--tags", remote_url])
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if res.returncode != 0:
            return "NOT_VERIFIABLE", {}, (res.stderr or "").strip() or "git ls-remote failed"
        refs: Dict[str, str] = {}
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) == 2:
                sha, ref_name = parts
                refs[ref_name] = sha
        return "PASS", refs, ""
    except subprocess.TimeoutExpired:
        return "NOT_VERIFIABLE", {}, "Network timeout querying remote tags"
    except Exception as e:
        return "NOT_VERIFIABLE", {}, str(e)


def check_remote_main_ci(
    repository: str,
    commit_sha: str,
    ci_status_override: Optional[str] = None,
    timeout: int = 8,
) -> Tuple[str, Optional[int], str]:
    """Verify required GitHub Actions workflow evidence for an exact commit.

    Caller-supplied PASS is never accepted as evidence. Negative overrides exist
    only for deterministic failure-path tests.
    """
    if repository != DEFAULT_OFFICIAL_REPO:
        return "FAIL", None, f"UNOFFICIAL_REPOSITORY_FORBIDDEN: {repository}"
    if not re.fullmatch(r"[0-9a-f]{40}", str(commit_sha or "")):
        return "NOT_VERIFIABLE", None, "Invalid or incomplete commit SHA"

    if ci_status_override:
        override = ci_status_override.upper()
        if override in ("FAIL", "BLOCK"):
            return "FAIL", None, "Negative test override requested"
        if override == "NOT_VERIFIABLE":
            return "NOT_VERIFIABLE", None, "Negative test override requested"
        if override == "PASS":
            return (
                "NOT_VERIFIABLE",
                None,
                "UNTRUSTED_CI_OVERRIDE: Caller-supplied PASS cannot replace GitHub Actions evidence",
            )

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    url = (
        f"https://api.github.com/repos/{repository}/actions/runs"
        f"?head_sha={commit_sha}&branch=main&per_page=100"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-Engineering-Standards-Sync/3.0.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    required_workflows = {".github/workflows/standards-ci.yml"}
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        runs = data.get("workflow_runs") or []
        if not runs:
            return "NOT_VERIFIABLE", None, f"No main workflow runs found for {commit_sha}"

        successful_ids: List[int] = []
        for workflow_path in sorted(required_workflows):
            matching = [run for run in runs if run.get("path") == workflow_path]
            if not matching:
                return (
                    "NOT_VERIFIABLE",
                    None,
                    f"Required workflow '{workflow_path}' has no run for {commit_sha}",
                )
            latest = max(
                matching,
                key=lambda run: (
                    int(run.get("run_attempt") or 1),
                    str(run.get("created_at") or ""),
                ),
            )
            run_id = latest.get("id")
            if latest.get("status") != "completed":
                return "NOT_VERIFIABLE", run_id, f"Required workflow '{workflow_path}' is not completed"
            if latest.get("conclusion") != "success":
                return (
                    "FAIL",
                    run_id,
                    f"Required workflow '{workflow_path}' concluded '{latest.get('conclusion')}'",
                )
            if isinstance(run_id, int):
                successful_ids.append(run_id)

        return (
            "PASS",
            successful_ids[0] if successful_ids else None,
            f"All required main workflows succeeded for {commit_sha}",
        )
    except Exception as exc:
        return "NOT_VERIFIABLE", None, f"GitHub Actions API unreachable: {exc}"

def discover_latest_official_tag(
    standards_root: Optional[Path] = None,
    remote_url: Optional[str] = None,
    repository: str = DEFAULT_OFFICIAL_REPO,
    ci_status_override: Optional[str] = None,
    simulate_offline: bool = False,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Discover the latest official annotated SemVer tag from remote, verifying:
    1. Official SemVer tag sorting.
    2. Fixed official repository (rejects arbitrary forks).
    3. Annotated tag object SHA != peeled commit SHA (lightweight tags rejected).
    4. Local/target VERSION file at peeled commit matches tag version.
    5. Peeled commit is on main (ancestor of or equal to refs/heads/main).
    6. Main CI verification status.
    If network is unavailable or CI is not verifiable, returns status='NOT_VERIFIABLE' and never claims PASS.
    """
    if repository != DEFAULT_OFFICIAL_REPO:
        return {
            "status": "BLOCK",
            "repository": repository,
            "reason": f"UNOFFICIAL_REPOSITORY_FORBIDDEN: Repository '{repository}' != '{DEFAULT_OFFICIAL_REPO}'; arbitrary forks cannot masquerade as official standards source",
        }

    std_root = resolve_standards_root(standards_root)
    if simulate_offline:
        return {
            "status": "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "repository": repository,
            "reason": "Network unavailable; refusing to use local cache as latest official release",
        }

    official_remote = f"https://github.com/{DEFAULT_OFFICIAL_REPO}.git"
    effective_remote = official_remote
    if remote_url:
        supplied_remote = str(remote_url).rstrip("/")
        accepted_remotes = {official_remote, official_remote[:-4]}
        if supplied_remote in accepted_remotes:
            effective_remote = official_remote
        elif Path(supplied_remote).is_dir():
            rc_origin, origin_url, _ = run_git(Path(supplied_remote), ["remote", "get-url", "origin"])
            normalized_origin = origin_url.rstrip("/") if rc_origin == 0 else ""
            if normalized_origin not in accepted_remotes:
                return {
                    "status": "BLOCK",
                    "repository": repository,
                    "reason": "UNOFFICIAL_REMOTE_FORBIDDEN: A local clone is accepted only when its origin is the canonical official repository",
                }
            effective_remote = supplied_remote
        else:
            return {
                "status": "BLOCK",
                "repository": repository,
                "reason": "UNOFFICIAL_REMOTE_FORBIDDEN: Discovery is restricted to the canonical official repository or its verified local clone",
            }
    ls_status, refs, err_msg = query_remote_ls_remote(
        remote_url=effective_remote,
        cwd=std_root if std_root.exists() else None,
        timeout=timeout,
    )
    if ls_status != "PASS":
        return {
            "status": "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "repository": repository,
            "reason": f"Remote discovery failed: {err_msg}",
        }

    remote_main = refs.get("refs/heads/main")
    tag_objects: Dict[str, str] = {}
    peeled_commits: Dict[str, str] = {}

    for ref_name, sha in refs.items():
        m = SEMVER_TAG_RE.match(ref_name)
        if not m:
            continue
        tag_name = m.group(1)
        is_peeled = bool(m.group(2))
        if is_peeled:
            peeled_commits[tag_name] = sha
        else:
            tag_objects[tag_name] = sha

    if not tag_objects:
        return {
            "status": "BLOCK",
            "repository": repository,
            "reason": "NO_OFFICIAL_TAG: No SemVer release tags found on remote; untagged main commits cannot masquerade as official releases",
        }

    sorted_tags = sorted(tag_objects.keys(), key=lambda t: parse_semver(t) or (0, 0, 0), reverse=True)
    latest_tag = sorted_tags[0]
    latest_version = latest_tag.lstrip("v")
    tag_obj_sha = tag_objects[latest_tag]
    peeled_sha = peeled_commits.get(latest_tag)

    # Annotated tag check: must have peeled commit entry and tag_object_sha != peeled_sha
    if not peeled_sha or tag_obj_sha == peeled_sha:
        return {
            "status": "BLOCK",
            "repository": repository,
            "tag": latest_tag,
            "version": latest_version,
            "tag_object_sha": tag_obj_sha,
            "peeled_commit": peeled_sha,
            "reason": f"UNANNOTATED_TAG_FORBIDDEN: Tag '{latest_tag}' is not an annotated tag",
        }

    # A Standards Git checkout is required to verify VERSION at the peeled commit
    # and prove that the release commit is on the official main ancestry.
    if not std_root.exists() or not (std_root / ".git").exists():
        return {
            "status": "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "repository": repository,
            "version": latest_version,
            "tag": latest_tag,
            "tag_object_sha": tag_obj_sha,
            "peeled_commit": peeled_sha,
            "reason": "LOCAL_STANDARDS_GIT_METADATA_UNAVAILABLE: Cannot verify tag VERSION and main ancestry without a Standards Git checkout",
            "tag_refs": {name: sha for name, sha in refs.items() if name.startswith("refs/tags/")},
        }

    # Verify against local standards repository
    if std_root.exists() and (std_root / ".git").exists():
        rc_local_tag, local_tag_obj, _ = run_git(std_root, ["rev-parse", f"refs/tags/{latest_tag}"])
        if rc_local_tag == 0 and local_tag_obj != tag_obj_sha:
            return {
                "status": "BLOCK",
                "repository": repository,
                "tag": latest_tag,
                "reason": f"TAG_OBJECT_DRIFT: Local tag object ({local_tag_obj}) != remote tag object ({tag_obj_sha})",
            }

        rc_local_peeled, local_peeled, _ = run_git(std_root, ["rev-parse", f"refs/tags/{latest_tag}^{{commit}}"])
        if rc_local_peeled == 0 and local_peeled != peeled_sha:
            return {
                "status": "BLOCK",
                "repository": repository,
                "tag": latest_tag,
                "reason": f"PEELED_COMMIT_DRIFT: Local peeled commit ({local_peeled}) != remote peeled commit ({peeled_sha})",
            }

        rc_ver, ver_content, _ = run_git(std_root, ["show", f"{peeled_sha}:VERSION"])
        if rc_ver != 0:
            return {
                "status": "BLOCK",
                "repository": repository,
                "tag": latest_tag,
                "version": latest_version,
                "reason": f"VERSION_FILE_MISSING_AT_TAG: Cannot read VERSION from {peeled_sha}",
            }
        clean_ver = ver_content.strip().lstrip("v")
        if clean_ver != latest_version:
            return {
                "status": "BLOCK",
                "repository": repository,
                "tag": latest_tag,
                "version": latest_version,
                "reason": f"VERSION_MISMATCH: VERSION file at {peeled_sha} is '{clean_ver}', expected '{latest_version}'",
            }

        if not remote_main:
            return {
                "status": "NOT_VERIFIABLE",
                "remote_latest_status": "NOT_VERIFIABLE",
                "repository": repository,
                "tag": latest_tag,
                "version": latest_version,
                "tag_object_sha": tag_obj_sha,
                "peeled_commit": peeled_sha,
                "reason": "REMOTE_MAIN_NOT_FOUND: Cannot verify official main ancestry",
                "tag_refs": {name: sha for name, sha in refs.items() if name.startswith("refs/tags/")},
            }
        if remote_main:
            rc_anc, _, _ = run_git(std_root, ["merge-base", "--is-ancestor", peeled_sha, remote_main])
            if rc_anc != 0:
                return {
                    "status": "BLOCK",
                    "repository": repository,
                    "tag": latest_tag,
                    "peeled_commit": peeled_sha,
                    "remote_main": remote_main,
                    "reason": f"NOT_ON_MAIN_BRANCH: Tag '{latest_tag}' commit {peeled_sha} is not an ancestor of main ({remote_main})",
                }

    ci_status, ci_run_id, ci_detail = check_remote_main_ci(
        repository=repository,
        commit_sha=peeled_sha,
        ci_status_override=ci_status_override,
    )
    if ci_status == "FAIL":
        return {
            "status": "BLOCK",
            "repository": repository,
            "version": latest_version,
            "tag": latest_tag,
            "tag_object_sha": tag_obj_sha,
            "peeled_commit": peeled_sha,
            "ci_verification_status": "FAIL",
            "ci_run_id": ci_run_id,
            "reason": f"MAIN_CI_FAILED: {ci_detail}",
        }
    if ci_status == "NOT_VERIFIABLE":
        return {
            "status": "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "repository": repository,
            "version": latest_version,
            "tag": latest_tag,
            "tag_object_sha": tag_obj_sha,
            "peeled_commit": peeled_sha,
            "ci_verification_status": "NOT_VERIFIABLE",
            "ci_run_id": ci_run_id,
            "reason": f"MAIN_CI_NOT_VERIFIABLE: {ci_detail}",
            "all_tags": sorted_tags,
            "tag_refs": {name: sha for name, sha in refs.items() if name.startswith("refs/tags/")},
        }

    return {
        "status": "PASS",
        "remote_latest_status": "PASS",
        "repository": repository,
        "version": latest_version,
        "tag": latest_tag,
        "tag_object_sha": tag_obj_sha,
        "peeled_commit": peeled_sha,
        "remote_main": remote_main,
        "ci_verification_status": ci_status,
        "ci_run_id": ci_run_id,
        "ci_detail": ci_detail,
        "all_tags": sorted_tags,
        "tag_refs": {name: sha for name, sha in refs.items() if name.startswith("refs/tags/")},
    }


def verify_project_lock(
    project_root: Path,
    standards_root: Optional[Path] = None,
    remote_url: Optional[str] = None,
    allow_offline: bool = True,
    simulate_offline: bool = False,
) -> Dict[str, Any]:
    """Verify project's standards.lock.json, cross-check against engineering-manifest.yaml
    and compatibility_matrix.yaml, and verify Tag object & Peeled Commit integrity.
    """
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)
    errors: List[str] = []

    lock_path = project_root / "standards.lock.json"
    if not lock_path.exists():
        return {
            "status": "BLOCK",
            "errors": ["MISSING_STANDARDS_LOCK: standards.lock.json not found in project root"],
        }

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "BLOCK", "errors": [f"CORRUPT_STANDARDS_LOCK: {e}"]}

    lock_schema_path = std_root / "schemas" / "standards-lock.schema.json"
    if not lock_schema_path.exists():
        errors.append("MISSING_STANDARDS_LOCK_SCHEMA: schemas/standards-lock.schema.json is required")
    else:
        schema = json.loads(lock_schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for err in validator.iter_errors(lock):
            errors.append(f"LOCK_SCHEMA_VIOLATION: {err.message}")

    tag = str(lock.get("tag") or "")
    version = str(lock.get("version") or "")
    tag_obj_sha = str(lock.get("tag_object_sha") or "")
    peeled_commit = str(lock.get("peeled_commit") or "")
    repository = str(lock.get("repository") or DEFAULT_OFFICIAL_REPO)

    if repository != DEFAULT_OFFICIAL_REPO:
        errors.append(
            f"UNOFFICIAL_STANDARDS_REPO_FORBIDDEN: Repository '{repository}' != '{DEFAULT_OFFICIAL_REPO}'; arbitrary forks cannot masquerade as official standards source"
        )

    if tag != f"v{version}":
        errors.append(f"LOCK_TAG_VERSION_MISMATCH: tag '{tag}' does not match version '{version}'")
    if tag_obj_sha and peeled_commit and tag_obj_sha == peeled_commit:
        errors.append("LOCK_LIGHTWEIGHT_TAG_FORBIDDEN: tag_object_sha cannot equal peeled_commit")

    # Cross-check with engineering-manifest.yaml
    manifest_path = project_root / "engineering-manifest.yaml"
    if not manifest_path.exists():
        errors.append("MISSING_MANIFEST_BLOCKED: engineering-manifest.yaml is required")
    else:
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            m_std = manifest.get("standards") or {}
            if not isinstance(m_std, dict) or not m_std:
                errors.append("MISSING_MANIFEST_STANDARDS_BLOCK: engineering-manifest.yaml must contain a standards mapping")
                m_std = {}
            manifest_schema_path = std_root / "schemas" / "engineering-manifest.schema.json"
            if not manifest_schema_path.exists():
                errors.append("MISSING_ENGINEERING_MANIFEST_SCHEMA: schemas/engineering-manifest.schema.json is required")
            else:
                manifest_schema = json.loads(manifest_schema_path.read_text(encoding="utf-8"))
                for schema_error in jsonschema.Draft202012Validator(manifest_schema).iter_errors(manifest):
                    errors.append(f"MANIFEST_SCHEMA_VIOLATION: {schema_error.message}")
            m_ver = str(
                m_std.get("version")
                or m_std.get("standard_version")
                or manifest.get("standards_version")
                or ""
            ).lstrip("v")
            m_tag = str(
                m_std.get("tag")
                or m_std.get("release_tag")
                or manifest.get("standards_tag")
                or ""
            )
            m_commit = str(
                m_std.get("peeled_commit")
                or m_std.get("standard_commit")
                or manifest.get("standards_commit")
                or ""
            )
            m_tag_obj = str(
                m_std.get("tag_object_sha")
                or manifest.get("standards_tag_object")
                or ""
            )
            if m_ver and m_ver != version:
                errors.append(f"MANIFEST_LOCK_VERSION_MISMATCH: manifest has '{m_ver}', lock has '{version}'")
            if m_tag and m_tag != tag:
                errors.append(f"MANIFEST_LOCK_TAG_MISMATCH: manifest has '{m_tag}', lock has '{tag}'")
            if m_commit and m_commit != peeled_commit:
                errors.append(f"MANIFEST_LOCK_COMMIT_MISMATCH: manifest has '{m_commit}', lock has '{peeled_commit}'")
            if m_tag_obj and m_tag_obj != tag_obj_sha:
                errors.append(f"MANIFEST_LOCK_TAG_OBJ_MISMATCH: manifest has '{m_tag_obj}', lock has '{tag_obj_sha}'")
        except Exception as e:
            errors.append(f"MANIFEST_PARSE_ERROR: {e}")

    # Verify against local Standards repository tags
    if std_root.exists() and (std_root / ".git").exists():
        rc_t, actual_tag_obj, _ = run_git(std_root, ["rev-parse", f"refs/tags/{tag}"])
        if rc_t != 0:
            errors.append(f"UNTAGGED_OR_MISSING_TAG: Tag '{tag}' does not exist in Standards repository")
        elif actual_tag_obj != tag_obj_sha:
            errors.append(
                f"TAG_OBJECT_DRIFT_BLOCKED: Locked tag_object_sha ({tag_obj_sha}) != repository tag object ({actual_tag_obj})"
            )

        rc_p, actual_peeled, _ = run_git(std_root, ["rev-parse", f"refs/tags/{tag}^{{commit}}"])
        if rc_p != 0:
            errors.append(f"INVALID_PEELED_COMMIT: Cannot resolve commit for tag '{tag}'")
        elif actual_peeled != peeled_commit:
            errors.append(
                f"PEELED_COMMIT_DRIFT_BLOCKED: Locked peeled_commit ({peeled_commit}) != tag peeled commit ({actual_peeled})"
            )

        rc_v, actual_ver, _ = run_git(std_root, ["show", f"{peeled_commit}:VERSION"])
        if rc_v == 0 and actual_ver.strip().lstrip("v") != version:
            errors.append(
                f"COMMIT_VERSION_MISMATCH: VERSION at {peeled_commit} is '{actual_ver.strip()}', expected '{version}'"
            )

    # Check remote latest status
    remote_info = discover_latest_official_tag(
        standards_root=std_root,
        remote_url=remote_url,
        repository=repository,
        simulate_offline=simulate_offline,
    )
    remote_latest_status = remote_info.get("remote_latest_status", remote_info.get("status", "NOT_VERIFIABLE"))

    if errors:
        return {
            "status": "BLOCK",
            "remote_latest_status": remote_latest_status,
            "lock": lock,
            "errors": errors,
        }

    if remote_info.get("status") == "BLOCK" or remote_latest_status == "BLOCK":
        return {
            "status": "BLOCK",
            "remote_latest_status": "BLOCK",
            "lock": lock,
            "errors": [remote_info.get("reason", "OFFICIAL_STANDARDS_DISCOVERY_BLOCKED")],
        }

    if remote_latest_status == "NOT_VERIFIABLE":
        return {
            "status": "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "offline_verified_lock": True,
            "lock": lock,
            "errors": [],
            "note": "The exact locked Tag/Commit was verified locally, but the latest official release and remote CI could not be verified. Offline use of the existing lock may continue; this result is not a PASS.",
        }

    remote_tag_refs = remote_info.get("tag_refs") or {}
    remote_tag_object = remote_tag_refs.get(f"refs/tags/{tag}")
    remote_peeled = remote_tag_refs.get(f"refs/tags/{tag}^{{}}")
    if remote_tag_object != tag_obj_sha or remote_peeled != peeled_commit:
        return {
            "status": "BLOCK",
            "remote_latest_status": remote_latest_status,
            "lock": lock,
            "errors": [f"REMOTE_LOCK_TAG_MISMATCH: Official remote Tag {tag} does not match the locked tag_object_sha/peeled_commit"],
        }

    is_up_to_date = remote_info.get("tag") == tag and remote_info.get("peeled_commit") == peeled_commit
    return {
        "status": "PASS",
        "remote_latest_status": "PASS",
        "is_up_to_date": is_up_to_date,
        "latest_official_tag": remote_info.get("tag"),
        "latest_official_commit": remote_info.get("peeled_commit"),
        "lock": lock,
        "errors": [],
    }


def load_json_at_ref(std_root: Path, git_ref: Optional[str], rel_path: str) -> Optional[Dict[str, Any]]:
    if git_ref in (None, "WORKTREE", "CURRENT"):
        p = std_root / rel_path
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    rc, out, _ = run_git(std_root, ["show", f"{git_ref}:{rel_path}"])
    if rc != 0:
        return None
    return json.loads(out)


def list_files_at_ref(std_root: Path, git_ref: Optional[str], prefix: str, suffix: str) -> Set[str]:
    if git_ref in (None, "WORKTREE", "CURRENT"):
        base = std_root / prefix
        if not base.exists():
            return set()
        return {
            str(p.relative_to(std_root)).replace("\\", "/")
            for p in base.rglob(f"*{suffix}")
            if p.is_file()
        }
    rc, out, _ = run_git(std_root, ["ls-tree", "-r", "--name-only", str(git_ref), prefix])
    if rc != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip().endswith(suffix)}


def deep_diff_schema(
    old_schema: Any,
    new_schema: Any,
    path: str = "",
) -> Tuple[List[str], Dict[str, Any]]:
    """Recursively diff two JSON schemas across all structural levels:
    - required fields at all object levels
    - type changes
    - enum additions and removals
    - pattern changes
    - additionalProperties changes
    - const changes
    - numeric and string constraints (minLength, maxLength, minItems, maxItems)
    - $ref changes
    Returns (breaking_changes, diff_details).
    """
    breaking: List[str] = []
    details: Dict[str, Any] = {}

    if not isinstance(old_schema, dict) or not isinstance(new_schema, dict):
        if old_schema != new_schema:
            details["changed"] = {"old": old_schema, "new": new_schema}
        return breaking, details

    # 1. Type change
    old_type = old_schema.get("type")
    new_type = new_schema.get("type")
    if old_type and new_type and old_type != new_type:
        msg = f"[{path or 'root'}]: type changed from '{old_type}' to '{new_type}'"
        breaking.append(msg)
        details["type_change"] = {"old": old_type, "new": new_type}

    # 2. Required fields
    old_req = set(old_schema.get("required") or [])
    new_req = set(new_schema.get("required") or [])
    added_req = sorted(new_req - old_req)
    removed_req = sorted(old_req - new_req)
    if added_req:
        breaking.append(f"[{path or 'root'}]: added required fields {added_req}")
        details["added_required"] = added_req
    if removed_req:
        details["removed_required"] = removed_req

    # 3. Enum values
    if "enum" in old_schema or "enum" in new_schema:
        old_enums = set(str(x) for x in (old_schema.get("enum") or []))
        new_enums = set(str(x) for x in (new_schema.get("enum") or []))
        added_e = sorted(new_enums - old_enums)
        removed_e = sorted(old_enums - new_enums)
        if removed_e:
            breaking.append(f"[{path or 'root'}]: removed enum values {removed_e}")
        if added_e or removed_e:
            details["enum_changes"] = {"added": added_e, "removed": removed_e}

    # 4. Pattern change
    old_pat = old_schema.get("pattern")
    new_pat = new_schema.get("pattern")
    if old_pat != new_pat:
        details["pattern_change"] = {"old": old_pat, "new": new_pat}

    # 5. additionalProperties
    old_ap = old_schema.get("additionalProperties")
    new_ap = new_schema.get("additionalProperties")
    if old_ap != new_ap:
        if old_ap is not False and new_ap is False:
            breaking.append(f"[{path or 'root'}]: additionalProperties changed to false (closed schema)")
        details["additionalProperties"] = {"old": old_ap, "new": new_ap}

    # 6. Const change
    if "const" in old_schema or "const" in new_schema:
        if old_schema.get("const") != new_schema.get("const"):
            breaking.append(f"[{path or 'root'}]: const changed from '{old_schema.get('const')}' to '{new_schema.get('const')}'")
            details["const_change"] = {"old": old_schema.get("const"), "new": new_schema.get("const")}

    # 7. $ref change
    if "$ref" in old_schema or "$ref" in new_schema:
        if old_schema.get("$ref") != new_schema.get("$ref"):
            details["$ref_change"] = {"old": old_schema.get("$ref"), "new": new_schema.get("$ref")}

    # Recursively check properties
    old_props = old_schema.get("properties") or {}
    new_props = new_schema.get("properties") or {}
    for p_name in sorted(set(old_props.keys()) | set(new_props.keys())):
        sub_p = f"{path}.{p_name}" if path else p_name
        if p_name in old_props and p_name in new_props:
            sub_b, sub_d = deep_diff_schema(old_props[p_name], new_props[p_name], sub_p)
            breaking.extend(sub_b)
            if sub_d:
                details[f"prop:{p_name}"] = sub_d
        elif p_name in old_props:
            breaking.append(f"[{path or 'root'}]: removed property '{p_name}'")
            details[f"prop_removed:{p_name}"] = True

    # Recursively check items
    if "items" in old_schema and "items" in new_schema:
        sub_b, sub_d = deep_diff_schema(old_schema["items"], new_schema["items"], f"{path}[]")
        breaking.extend(sub_b)
        if sub_d:
            details["items"] = sub_d

    # Recursively check $defs
    old_defs = old_schema.get("$defs") or {}
    new_defs = new_schema.get("$defs") or {}
    for d_name in sorted(set(old_defs.keys()) | set(new_defs.keys())):
        sub_p = f"{path}.$defs.{d_name}" if path else f"$defs.{d_name}"
        if d_name in old_defs and d_name in new_defs:
            sub_b, sub_d = deep_diff_schema(old_defs[d_name], new_defs[d_name], sub_p)
            breaking.extend(sub_b)
            if sub_d:
                details[f"$defs:{d_name}"] = sub_d
        elif d_name in old_defs:
            breaking.append(f"[{path or 'root'}]: removed definition '$defs.{d_name}'")
            details[f"def_removed:{d_name}"] = True

    return breaking, details


def extract_normative_clauses(markdown_text: str) -> Set[str]:
    """Extract normative MUST / MUST NOT / SHALL / REQUIRED clauses from markdown text."""
    clauses: Set[str] = set()
    normative_pattern = re.compile(r"(\b(?:MUST|MUST NOT|SHALL|SHALL NOT|REQUIRED|SHOULD|SHOULD NOT)\b)", re.IGNORECASE)
    for line in markdown_text.splitlines():
        s = line.strip()
        if normative_pattern.search(s) and len(s) > 10:
            cleaned = re.sub(r"^[0-9*#-]+\.?\s*", "", s).strip()
            if cleaned:
                clauses.add(cleaned)
    return clauses


def compare_versions_and_artifacts(
    from_ref: str,
    to_ref: str = "WORKTREE",
    standards_root: Optional[Path] = None,
    from_version_override: Optional[str] = None,
    to_version_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare two Standards versions/refs:
    - SemVer comparison (blocks automatic downgrade).
    - Standards markdown clause additions/deprecations/modifications (MUST/MUST NOT).
    - Deep JSON Schema diff across all levels (required, types, enums, patterns, $ref, additionalProperties).
    """
    std_root = resolve_standards_root(standards_root)

    def get_ver(ref: str, override: Optional[str]) -> str:
        if override:
            return override.lstrip("v")
        if ref in ("WORKTREE", "CURRENT"):
            return (std_root / "VERSION").read_text(encoding="utf-8").strip().lstrip("v")
        rc, out, _ = run_git(std_root, ["show", f"{ref}:VERSION"])
        if rc == 0:
            return out.strip().lstrip("v")
        return ref.lstrip("v")

    from_ver = get_ver(from_ref, from_version_override)
    to_ver = get_ver(to_ref, to_version_override)
    from_sv = parse_semver(from_ver)
    to_sv = parse_semver(to_ver)

    if from_sv and to_sv and to_sv < from_sv:
        return {
            "status": "BLOCK",
            "reason": f"DOWNGRADE_FORBIDDEN: Target version {to_ver} is lower than locked version {from_ver}",
            "from_version": from_ver,
            "to_version": to_ver,
        }

    eff_to_ref = to_ref
    if to_ref not in ("WORKTREE", "CURRENT"):
        rc_t, _, _ = run_git(std_root, ["rev-parse", "--verify", f"{to_ref}^{{commit}}"])
        if rc_t != 0:
            current_v = (std_root / "VERSION").read_text(encoding="utf-8").strip().lstrip("v")
            if to_ref.lstrip("v") == current_v:
                eff_to_ref = "WORKTREE"

    # 1. Compare schemas/*.schema.json with deep diff
    old_schemas = list_files_at_ref(std_root, from_ref, "schemas", ".schema.json")
    new_schemas = list_files_at_ref(std_root, eff_to_ref, "schemas", ".schema.json")
    added_schemas = sorted(new_schemas - old_schemas)
    removed_schemas = sorted(old_schemas - new_schemas)

    schema_diffs: Dict[str, Any] = {}
    breaking_changes: List[str] = []
    if removed_schemas:
        breaking_changes.append(f"Removed schemas: {removed_schemas}")

    for s_path in sorted(old_schemas & new_schemas):
        old_s = load_json_at_ref(std_root, from_ref, s_path) or {}
        new_s = load_json_at_ref(std_root, eff_to_ref, s_path) or {}
        sub_breaking, diff_det = deep_diff_schema(old_s, new_s, path=s_path)
        if sub_breaking:
            breaking_changes.extend(sub_breaking)
        if diff_det:
            schema_diffs[s_path] = diff_det

    # 2. Compare standards/**/*.md with normative clauses
    old_stds = list_files_at_ref(std_root, from_ref, "standards", ".md")
    new_stds = list_files_at_ref(std_root, eff_to_ref, "standards", ".md")
    added_stds = sorted(new_stds - old_stds)
    deprecated_stds = sorted(old_stds - new_stds)
    modified_stds: Dict[str, Any] = {}
    normative_clause_changes: Dict[str, Any] = {}

    for std_path in sorted(old_stds & new_stds):
        rc1, old_txt, _ = run_git(std_root, ["show", f"{from_ref}:{std_path}"])
        if eff_to_ref in ("WORKTREE", "CURRENT"):
            p_f = std_root / std_path
            new_txt = p_f.read_text(encoding="utf-8") if p_f.exists() else ""
            rc2 = 0
        else:
            rc2, new_txt, _ = run_git(std_root, ["show", f"{eff_to_ref}:{std_path}"])

        if rc1 == 0 and rc2 == 0 and old_txt.replace("\r\n", "\n").strip() != new_txt.replace("\r\n", "\n").strip():
            old_headings = {line.strip() for line in old_txt.splitlines() if line.strip().startswith("## ")}
            new_headings = {line.strip() for line in new_txt.splitlines() if line.strip().startswith("## ")}
            modified_stds[std_path] = {
                "added_sections": sorted(new_headings - old_headings),
                "removed_sections": sorted(old_headings - new_headings),
            }

            old_clauses = extract_normative_clauses(old_txt)
            new_clauses = extract_normative_clauses(new_txt)
            added_cl = sorted(new_clauses - old_clauses)
            removed_cl = sorted(old_clauses - new_clauses)
            if added_cl or removed_cl:
                normative_clause_changes[std_path] = {
                    "added_normative_clauses_count": len(added_cl),
                    "removed_normative_clauses_count": len(removed_cl),
                }

    return {
        "status": "PASS",
        "from_ref": from_ref,
        "to_ref": to_ref,
        "from_version": from_ver,
        "to_version": to_ver,
        "added_schemas": added_schemas,
        "removed_schemas": removed_schemas,
        "schema_diffs": schema_diffs,
        "added_standards": added_stds,
        "deprecated_standards": deprecated_stds,
        "modified_standards": modified_stds,
        "normative_clause_changes": normative_clause_changes,
        "breaking_changes": breaking_changes,
        "has_breaking_changes": len(breaking_changes) > 0,
    }


def analyze_consumer_impact(
    project_root: Path,
    from_ref: Optional[str] = None,
    to_ref: str = "WORKTREE",
    standards_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Analyze impact of upgrading a downstream project across all 10 required governance dimensions:
    1. Schema
    2. AGENTS.md
    3. CLAUDE.md
    4. Engineering Manifest
    5. Documentation Metadata
    6. Documentation Collection
    7. Tests
    8. Release Gates
    9. Security
    10. Business API & Runtime Contract

    Outputs structured 8-tuple for each dimension:
      (check_method, input_commit, target_commit, command, executed_at, raw_evidence, exit_code, status)
    Separates analysis_status and compatibility_status. Never statically fabricates COMPATIBLE.
    """
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Read the consumer's exact lock. Never infer or silently fall back to a historical version.
    lock_path = project_root / "standards.lock.json"
    input_commit = "UNKNOWN"
    eff_from = from_ref
    if lock_path.exists():
        try:
            lk = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {
                "status": "BLOCK",
                "analysis_status": "FAILED",
                "compatibility_status": "UPGRADE_BLOCKED",
                "reason": f"CORRUPT_STANDARDS_LOCK: {exc}",
            }
        required_fields = ("repository", "version", "tag", "tag_object_sha", "peeled_commit")
        missing_fields = [field for field in required_fields if not lk.get(field)]
        if missing_fields:
            return {
                "status": "BLOCK",
                "analysis_status": "FAILED",
                "compatibility_status": "UPGRADE_BLOCKED",
                "reason": f"INCOMPLETE_STANDARDS_LOCK: Missing {missing_fields}",
            }
        if lk.get("repository") != DEFAULT_OFFICIAL_REPO:
            return {
                "status": "BLOCK",
                "analysis_status": "FAILED",
                "compatibility_status": "UPGRADE_BLOCKED",
                "reason": "UNOFFICIAL_REPOSITORY_FORBIDDEN",
            }
        input_commit = str(lk["peeled_commit"])
        if not eff_from:
            eff_from = str(lk["tag"])
    elif not eff_from:
        return {
            "status": "BLOCK",
            "analysis_status": "FAILED",
            "compatibility_status": "UPGRADE_BLOCKED",
            "reason": "MISSING_STANDARDS_LOCK: Supply an explicit --from-ref only for a read-only bootstrap assessment; promotion still requires a verified four-tuple lock",
        }

    target_commit = "WORKTREE"
    if to_ref not in ("WORKTREE", "CURRENT"):
        rc_t, t_peeled, _ = run_git(std_root, ["rev-parse", f"{to_ref}^{{commit}}"])
        target_commit = t_peeled if rc_t == 0 else to_ref

    diff_report = compare_versions_and_artifacts(from_ref=eff_from, to_ref=to_ref, standards_root=std_root)
    if diff_report.get("status") == "BLOCK":
        return {
            "status": "BLOCK",
            "analysis_status": "FAILED",
            "compatibility_status": "UPGRADE_BLOCKED",
            "reason": diff_report.get("reason"),
        }

    breaking_items: List[str] = list(diff_report.get("breaking_changes") or [])
    migration_tasks: List[str] = []

    # Check manifest
    manifest_path = project_root / "engineering-manifest.yaml"
    project_name = project_root.name
    manifest_schema_path = std_root / "schemas" / "engineering-manifest.schema.json"
    manifest_valid = False
    manifest_err = "Not executed"
    if manifest_path.exists() and manifest_schema_path.exists():
        try:
            m_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            project_name = str((m_data.get("project") or {}).get("id") or project_name)
            s_data = json.loads(manifest_schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=m_data, schema=s_data)
            manifest_valid = True
            manifest_err = "OK"
        except Exception as e:
            manifest_valid = False
            manifest_err = str(e)
            breaking_items.append(f"Manifest schema validation failure: {e}")

    # Check docs/
    docs_dir = project_root / "docs"
    historical_archive_files: List[str] = []
    has_engineering_baseline = False
    if docs_dir.exists():
        for md_file in sorted(docs_dir.rglob("*.md")):
            try:
                txt = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if txt.startswith("---"):
                parts = txt.split("---", 2)
                if len(parts) >= 3:
                    try:
                        fm = yaml.safe_load(parts[1]) or {}
                        if isinstance(fm, dict):
                            if fm.get("document_type") == "HISTORICAL_ARCHIVE":
                                historical_archive_files.append(
                                    str(md_file.relative_to(project_root)).replace("\\", "/")
                                )
                            if (
                                fm.get("document_type") == "ENGINEERING_BASELINE"
                                and fm.get("status") in ("ACTIVE", "IN_REVIEW")
                                and fm.get("primary_entrypoint") is True
                            ):
                                has_engineering_baseline = True
                    except Exception:
                        pass

    if historical_archive_files:
        breaking_items.append(
            f"Found {len(historical_archive_files)} file(s) using removed document_type 'HISTORICAL_ARCHIVE'"
        )
        migration_tasks.append(
            f"Reclassify {len(historical_archive_files)} HISTORICAL_ARCHIVE document(s) to original semantic document_type with status=ARCHIVED/SUPERSEDED and primary_entrypoint=false"
        )

    if not has_engineering_baseline:
        breaking_items.append("Missing mandatory primary entrypoint for ENGINEERING_BASELINE (docs/当前权威基线.md)")
        migration_tasks.append("Generate docs/当前权威基线.md using tools/generate_engineering_baseline.py and register in DOCUMENT-INDEX")

    # Check mandatory agent entrypoints and version literals in all guidance files.
    required_agent_docs = ("AGENTS.md", "CLAUDE.md")
    guidance_docs = ("AGENTS.md", "CLAUDE.md", "README.md")
    missing_agent_docs: List[str] = []
    hardcoded_agent_docs: List[str] = []
    standards_version_patterns = (
        re.compile(r"(?i)\\bstandards?\\b[^\\r\\n]{0,120}\\bv?\\d+\\.\\d+\\.\\d+\\b"),
        re.compile(r"(?i)\\bv?\\d+\\.\\d+\\.\\d+\\b[^\\r\\n]{0,80}\\bstandards?\\b"),
    )
    for guidance_name in guidance_docs:
        guidance_path = project_root / guidance_name
        if not guidance_path.exists():
            if guidance_name in required_agent_docs:
                missing_agent_docs.append(guidance_name)
            continue
        guidance_text = guidance_path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(guidance_text) for pattern in standards_version_patterns):
            hardcoded_agent_docs.append(guidance_name)

    if missing_agent_docs:
        breaking_items.append(f"Missing mandatory agent guidance entrypoints: {missing_agent_docs}")
        migration_tasks.append(f"Create required agent guidance entrypoints: {missing_agent_docs}")
    if hardcoded_agent_docs:
        migration_tasks.append(
            f"Replace hardcoded Standards version strings in {hardcoded_agent_docs} with thin references to standards.lock.json"
        )

    # Execute documentation collection and baseline verification; do not infer PASS from file presence.
    doc_schema_path = std_root / "schemas" / "documentation-metadata.schema.json"
    doc_collection_ok, doc_collection_errors = run_collection_validation(
        project_root=project_root,
        schema_path=doc_schema_path,
        standards_root=std_root,
        check_templates=True,
        verify_source_paths=True,
    )
    baseline_script = std_root / "tools" / "generate_engineering_baseline.py"
    baseline_exit_code: Optional[int] = None
    baseline_output = "NOT_VERIFIABLE: baseline generator is unavailable"
    if baseline_script.exists():
        try:
            baseline_result = subprocess.run(
                [
                    sys.executable,
                    str(baseline_script),
                    "--project-root",
                    str(project_root),
                    "--standards-root",
                    str(std_root),
                    "--verify-only",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            baseline_exit_code = baseline_result.returncode
            baseline_output = (baseline_result.stdout or "") + (baseline_result.stderr or "")
        except Exception as exc:
            baseline_output = f"NOT_VERIFIABLE: {exc}"

    # Build the 10-dimension structured 8-tuple records.
    schema_compatible = not diff_report.get("breaking_changes") and manifest_valid
    guidance_status = "UPGRADE_BLOCKED" if (missing_agent_docs or hardcoded_agent_docs) else "COMPATIBLE"
    docs_status = "UPGRADE_BLOCKED" if (historical_archive_files or not doc_collection_ok) else "COMPATIBLE"
    baseline_status = (
        "COMPATIBLE" if baseline_exit_code == 0
        else "UPGRADE_BLOCKED" if baseline_exit_code not in (None, 0)
        else "NOT_VERIFIABLE"
    )
    dimensions_checked: Dict[str, Dict[str, Any]] = {
        "Schema": {
            "check_method": "DEEP_SCHEMA_AST_DIFF_AND_MANIFEST_SCHEMA_VALIDATE",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "python tools/standards_sync/cli.py compare",
            "executed_at": now_iso,
            "raw_evidence": f"Standards breaking changes: {len(diff_report['breaking_changes'])}; manifest_schema_valid={manifest_valid}",
            "exit_code": 0 if schema_compatible else 1,
            "status": "COMPATIBLE" if schema_compatible else "UPGRADE_BLOCKED",
        },
        "AGENTS.md": {
            "check_method": "REQUIRED_ENTRYPOINT_AND_STANDARDS_VERSION_SCAN",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "read AGENTS.md and scan Standards version literals",
            "executed_at": now_iso,
            "raw_evidence": f"missing={missing_agent_docs}; hardcoded={hardcoded_agent_docs}",
            "exit_code": 0 if ("AGENTS.md" not in missing_agent_docs and "AGENTS.md" not in hardcoded_agent_docs) else 1,
            "status": "UPGRADE_BLOCKED" if ("AGENTS.md" in missing_agent_docs or "AGENTS.md" in hardcoded_agent_docs) else "COMPATIBLE",
        },
        "CLAUDE.md": {
            "check_method": "REQUIRED_ENTRYPOINT_AND_STANDARDS_VERSION_SCAN",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "read CLAUDE.md and scan Standards version literals",
            "executed_at": now_iso,
            "raw_evidence": f"missing={missing_agent_docs}; hardcoded={hardcoded_agent_docs}",
            "exit_code": 0 if ("CLAUDE.md" not in missing_agent_docs and "CLAUDE.md" not in hardcoded_agent_docs) else 1,
            "status": "UPGRADE_BLOCKED" if ("CLAUDE.md" in missing_agent_docs or "CLAUDE.md" in hardcoded_agent_docs) else "COMPATIBLE",
        },
        "Engineering Manifest": {
            "check_method": "MANIFEST_SCHEMA_VALIDATE",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "jsonschema.validate(instance=manifest, schema=engineering-manifest.schema.json)",
            "executed_at": now_iso,
            "raw_evidence": manifest_err,
            "exit_code": 0 if manifest_valid else 1,
            "status": "COMPATIBLE" if manifest_valid else "UPGRADE_BLOCKED",
        },
        "Documentation Metadata": {
            "check_method": "DOCUMENT_METADATA_AND_REMOVED_ENUM_SCAN",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "python tools/validate-documentation-collection.py",
            "executed_at": now_iso,
            "raw_evidence": f"HISTORICAL_ARCHIVE files={len(historical_archive_files)}; hardcoded_guidance_versions={hardcoded_agent_docs}; collection_errors={doc_collection_errors}",
            "exit_code": 0 if docs_status == "COMPATIBLE" else 1,
            "status": docs_status,
        },
        "Documentation Collection": {
            "check_method": "COLLECTION_AND_BASELINE_VERIFY_ONLY",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "python tools/validate-documentation-collection.py --check-templates --verify-source-paths && python tools/generate_engineering_baseline.py --verify-only",
            "executed_at": now_iso,
            "raw_evidence": f"collection_ok={doc_collection_ok}; collection_errors={doc_collection_errors}; baseline_exit_code={baseline_exit_code}; baseline_output={baseline_output[-4000:]}",
            "exit_code": 0 if docs_status == "COMPATIBLE" and baseline_status == "COMPATIBLE" else (1 if docs_status == "UPGRADE_BLOCKED" or baseline_status == "UPGRADE_BLOCKED" else None),
            "status": "UPGRADE_BLOCKED" if docs_status == "UPGRADE_BLOCKED" or baseline_status == "UPGRADE_BLOCKED" else ("NOT_VERIFIABLE" if baseline_status == "NOT_VERIFIABLE" else "COMPATIBLE"),
        },
        "Tests": {
            "check_method": "UNIT_AND_CONTRACT_TEST_EXECUTION",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "python -m unittest discover -s tests -v",
            "executed_at": now_iso,
            "raw_evidence": "NOT_RUN: This impact analyzer does not execute consumer test suites",
            "exit_code": None,
            "status": "NOT_RUN",
        },
        "Release Gates": {
            "check_method": "RELEASE_STAGE_POLICY_CHECK",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "python -m unittest tests/test_release_approval_contract.py",
            "executed_at": now_iso,
            "raw_evidence": "NOT_RUN: Release gate tests were not executed by this analyzer",
            "exit_code": None,
            "status": "NOT_RUN",
        },
        "Security": {
            "check_method": "STD_007_ZERO_SECRET_SCAN",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "git grep -E '(api[_-]?key|secret|password|private_key)'",
            "executed_at": now_iso,
            "raw_evidence": "NOT_RUN: No secret scan was executed by this analyzer",
            "exit_code": None,
            "status": "NOT_RUN",
        },
        "Business API & Runtime Contract": {
            "check_method": "STD_017_NON_RUNTIME_API_INSPECTION",
            "input_commit": input_commit,
            "target_commit": target_commit,
            "command": "python -m unittest tests/test_two_stage_release_contract.py",
            "executed_at": now_iso,
            "raw_evidence": "NOT_RUN: Business API and runtime tests were not executed by this analyzer",
            "exit_code": None,
            "status": "NOT_RUN",
        },
    }

    has_blocked_dim = any(dim["status"] == "UPGRADE_BLOCKED" for dim in dimensions_checked.values())
    has_unverified_dim = any(
        dim["status"] in ("NOT_RUN", "NOT_VERIFIABLE") for dim in dimensions_checked.values()
    )
    compatibility_status = (
        "UPGRADE_BLOCKED"
        if has_blocked_dim or breaking_items
        else "NOT_VERIFIABLE"
        if has_unverified_dim
        else "COMPATIBLE"
    )
    analysis_status = "PARTIAL" if has_unverified_dim else "COMPLETED"
    overall_status = (
        "BLOCK"
        if compatibility_status == "UPGRADE_BLOCKED"
        else "NOT_VERIFIABLE"
        if compatibility_status == "NOT_VERIFIABLE"
        else "PASS"
    )
    requires_owner_approval = len(breaking_items) > 0 or len(diff_report.get("modified_standards") or {}) > 0

    return {
        "status": overall_status,
        "analysis_status": analysis_status,
        "compatibility_status": compatibility_status,
        "PROJECT": project_name,
        "INPUT_COMMIT": input_commit,
        "TARGET_COMMIT": target_commit,
        "BASELINE_STANDARD": eff_from,
        "TARGET_STANDARD": f"v{diff_report['to_version']}",
        "MIGRATION_REQUIRED": len(breaking_items) > 0 or len(migration_tasks) > 0,
        "BREAKING_CHANGES": breaking_items,
        "HISTORICAL_ARCHIVE_FILES_COUNT": len(historical_archive_files),
        "HISTORICAL_ARCHIVE_FILES": historical_archive_files,
        "HAS_ENGINEERING_BASELINE": has_engineering_baseline,
        "DIMENSIONS_CHECKED": dimensions_checked,
        "APPROVAL_REQUIREMENT": "OWNER_APPROVAL_REQUIRED" if requires_owner_approval else "CHATGPT_REVIEW_REQUIRED",
        "TEST_REQUIREMENTS": [
            "python tools/validate-schemas.py",
            "python tools/validate-documentation-collection.py --project-root <PROJECT_ROOT>",
            "python tools/standards_sync/cli.py verify-lock --project-root <PROJECT_ROOT>",
        ],
        "MIGRATION_PLAN": migration_tasks,
        "ROLLBACK_PLAN": "Run `python tools/standards_sync/cli.py rollback --project-root <PROJECT_ROOT>` to restore the previous verified Standards lock and matching Manifest fields from standards.lock.json#previous_locks. This command does not revert docs/, source code, or unrelated worktree changes; review and revert any migration artifacts separately using a commit-bound, explicitly approved rollback plan.",
    }


def prepare_upgrade_candidate(
    project_root: Path,
    target_tag: str,
    target_version: str,
    target_tag_object_sha: str,
    target_peeled_commit: str,
    standards_root: Optional[Path] = None,
) -> Dict[str, Any]:
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)

    # Determine consumer baseline exclusively from its authoritative lock.
    lock_path = project_root / "standards.lock.json"
    if not lock_path.exists():
        return {"status": "BLOCK", "reason": "MISSING_STANDARDS_LOCK: Cannot infer a consumer baseline"}
    try:
        lk = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "BLOCK", "reason": f"CORRUPT_STANDARDS_LOCK: {exc}"}
    required_lock_fields = ("repository", "version", "tag", "tag_object_sha", "peeled_commit")
    missing_lock_fields = [field for field in required_lock_fields if not lk.get(field)]
    if missing_lock_fields:
        return {
            "status": "BLOCK",
            "reason": f"INCOMPLETE_STANDARDS_LOCK: Missing {missing_lock_fields}",
        }
    from_ref = str(lk["tag"])

    # Analyze consumer impact against explicit target_tag (not default WORKTREE)
    impact = analyze_consumer_impact(
        project_root=project_root,
        from_ref=from_ref,
        to_ref=target_tag,
        standards_root=std_root,
    )
    if impact.get("compatibility_status") == "UPGRADE_BLOCKED" or impact.get("analysis_status") == "FAILED":
        return {
            "status": "BLOCK",
            "reason": "UPGRADE_BLOCKED",
            "impact": impact,
        }
    if impact.get("compatibility_status") not in ("COMPATIBLE", "NOT_VERIFIABLE"):
        return {
            "status": "NOT_VERIFIABLE",
            "reason": "IMPACT_ANALYSIS_INCOMPLETE",
            "impact": impact,
        }
    # Candidate preparation is not approval or promotion. A partial impact
    # report may be saved for review, but the lock cannot be promoted until
    # all required consumer evidence is independently verified.

    cand_dir = project_root / ".artifacts" / "standards_upgrade" / target_tag
    cand_dir.mkdir(parents=True, exist_ok=True)

    existing_lock: Dict[str, Any] = {}
    if lock_path.exists():
        try:
            existing_lock = json.loads(lock_path.read_text(encoding="utf-8"))
        except Exception:
            existing_lock = {}

    prev_locks = list(existing_lock.get("previous_locks") or [])
    if existing_lock.get("tag") and existing_lock.get("peeled_commit"):
        prev_locks.append(
            {
                "repository": existing_lock.get("repository", DEFAULT_OFFICIAL_REPO),
                "version": existing_lock.get("version", existing_lock.get("tag", "").lstrip("v")),
                "tag": existing_lock["tag"],
                "tag_object_sha": existing_lock.get("tag_object_sha"),
                "peeled_commit": existing_lock["peeled_commit"],
                "locked_at": existing_lock.get("locked_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                "lock_reason": existing_lock.get("lock_reason", "Prior lock preserved before upgrade"),
                "approval_evidence_ref": existing_lock.get("approval_evidence_ref"),
                "ci_verification_status": existing_lock.get("ci_verification_status", "NOT_VERIFIABLE"),
            }
        )

    candidate_lock = {
        "schema_version": "1.0.0",
        "repository": DEFAULT_OFFICIAL_REPO,
        "version": target_version.lstrip("v"),
        "tag": target_tag,
        "tag_object_sha": target_tag_object_sha,
        "peeled_commit": target_peeled_commit,
        "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lock_reason": f"Controlled upgrade to {target_tag}",
        "approval_evidence_ref": f".artifacts/standards_upgrade/{target_tag}/approval_evidence.json",
        "previous_locks": prev_locks,
    }

    (cand_dir / "standards.lock.candidate.json").write_text(
        json.dumps(candidate_lock, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (cand_dir / "impact_analysis.json").write_text(
        json.dumps(impact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "CANDIDATE_GENERATED",
        "candidate_dir": str(cand_dir.relative_to(project_root)).replace("\\", "/"),
        "candidate_lock": candidate_lock,
        "impact": impact,
    }


def validate_upgrade_candidate(
    project_root: Path,
    standards_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run available checks and fail closed for consumer gates not actually executed."""
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)
    errors: List[str] = []

    manifest_path = project_root / "engineering-manifest.yaml"
    manifest_schema_path = std_root / "schemas" / "engineering-manifest.schema.json"
    if manifest_path.exists() and manifest_schema_path.exists():
        try:
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            m_schema = json.loads(manifest_schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=manifest_data, schema=m_schema)
        except Exception as exc:
            errors.append(f"MANIFEST_INCOMPATIBLE: {exc}")
    else:
        errors.append("MISSING_MANIFEST: engineering-manifest.yaml not found")

    doc_schema_path = std_root / "schemas" / "documentation-metadata.schema.json"
    doc_ok, doc_errors = run_collection_validation(
        project_root=project_root,
        schema_path=doc_schema_path,
        standards_root=std_root,
    )
    if not doc_ok:
        errors.extend(doc_errors)

    if errors:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": errors,
        }

    return {
        "status": "NOT_VERIFIABLE",
        "compatible": None,
        "analysis_status": "PARTIAL",
        "errors": [
            "REQUIRED_CONSUMER_VALIDATION_NOT_EXECUTED: Manifest and documentation checks passed, but consumer tests, release gates, security, and business/runtime validation have not been executed with commit-bound evidence"
        ],
    }

def promote_upgrade(
    project_root: Path,
    target_tag: str,
    target_version: str,
    target_tag_object_sha: str,
    target_peeled_commit: str,
    approval_record: Optional[Dict[str, Any]] = None,
    approval_file: Optional[Path] = None,
    ci_status: Optional[str] = None,
    standards_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Promote project lock to target version ONLY if:
    1. Target version is not a downgrade.
    2. Target peeled commit matches approval record candidate_commit.
    3. Main CI status is verified PASS (never defaulted or fabricated).
    4. Compatibility validation is PASS.
    5. Approval record is valid and satisfies required approval level (AI_APPROVED vs OWNER_APPROVED).
    Applies transactional write to standards.lock.json and engineering-manifest.yaml.
    Preserves previous lock in previous_locks.
    """
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)

    # 1. Verify CI status from GitHub Actions; caller-supplied PASS is never trusted.
    if ci_status:
        supplied_status = ci_status.upper()
        if supplied_status == "PASS":
            return {
                "status": "UPGRADE_BLOCKED",
                "reason": "UNTRUSTED_CI_OVERRIDE: Caller-supplied PASS cannot authorize promotion",
            }
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": f"CI_NOT_PASSED: Caller-supplied status '{supplied_status}' cannot authorize promotion",
        }

    ci_st, ci_run_id, ci_detail = check_remote_main_ci(DEFAULT_OFFICIAL_REPO, target_peeled_commit)
    if ci_st != "PASS":
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": f"CI_NOT_PASSED: Target release main CI status is '{ci_st}': {ci_detail}",
        }

    if target_tag != f"v{target_version.lstrip('v')}":
        return {"status": "UPGRADE_BLOCKED", "reason": "TARGET_TAG_VERSION_MISMATCH"}
    remote_status, remote_refs, remote_error = query_remote_ls_remote(
        f"https://github.com/{DEFAULT_OFFICIAL_REPO}.git",
        cwd=std_root if std_root.exists() else None,
    )
    if remote_status != "PASS":
        return {"status": "UPGRADE_BLOCKED", "reason": f"TARGET_TAG_NOT_VERIFIABLE: {remote_error}"}
    if (
        remote_refs.get(f"refs/tags/{target_tag}") != target_tag_object_sha
        or remote_refs.get(f"refs/tags/{target_tag}^{{}}") != target_peeled_commit
    ):
        return {"status": "UPGRADE_BLOCKED", "reason": "TARGET_TAG_OBJECT_OR_PEELED_COMMIT_MISMATCH"}
    remote_main = remote_refs.get("refs/heads/main")
    if not remote_main:
        return {"status": "UPGRADE_BLOCKED", "reason": "REMOTE_MAIN_NOT_VERIFIABLE"}
    rc_target, _, _ = run_git(std_root, ["cat-file", "-e", f"{target_peeled_commit}^{{commit}}"])
    if rc_target != 0:
        return {"status": "UPGRADE_BLOCKED", "reason": "TARGET_COMMIT_NOT_AVAILABLE_FOR_ANCESTRY_CHECK"}
    rc_ancestor, _, _ = run_git(std_root, ["merge-base", "--is-ancestor", target_peeled_commit, remote_main])
    if rc_ancestor != 0:
        return {"status": "UPGRADE_BLOCKED", "reason": "TARGET_COMMIT_NOT_ON_OFFICIAL_MAIN_ANCESTRY"}
    rc_version, version_at_target, _ = run_git(std_root, ["show", f"{target_peeled_commit}:VERSION"])
    if rc_version != 0 or version_at_target.strip().lstrip("v") != target_version.lstrip("v"):
        return {"status": "UPGRADE_BLOCKED", "reason": "TARGET_VERSION_FILE_MISMATCH"}

    # 2. Check downgrade against existing lock
    lock_path = project_root / "standards.lock.json"
    existing_lock: Dict[str, Any] = {}
    if lock_path.exists():
        existing_lock = json.loads(lock_path.read_text(encoding="utf-8"))
        cur_sv = parse_semver(existing_lock.get("version") or existing_lock.get("tag") or "0.0.0")
        tgt_sv = parse_semver(target_version)
        if cur_sv and tgt_sv and tgt_sv < cur_sv:
            return {
                "status": "UPGRADE_BLOCKED",
                "reason": f"DOWNGRADE_FORBIDDEN: Cannot downgrade from {existing_lock.get('version')} to {target_version}",
            }

    # 3. Validate approval evidence and reconcile candidate_commit against target_peeled_commit
    if approval_record is None and approval_file is not None and approval_file.exists():
        approval_record = json.loads(approval_file.read_text(encoding="utf-8"))

    if not approval_record:
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": "UNAUTHORIZED_UPGRADE: Missing approval evidence record",
        }

    app_cand_commit = str(approval_record.get("candidate_commit") or "").strip()
    if app_cand_commit != target_peeled_commit:
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": f"APPROVAL_COMMIT_MISMATCH: Approval binds {app_cand_commit}, but target is {target_peeled_commit}",
        }

    app_ok, app_errors = validate_approval_record(record=approval_record, verify_provenance=True)
    if not app_ok:
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": "INVALID_APPROVAL_EVIDENCE",
            "errors": app_errors,
        }

    if approval_record.get("approval_status") not in ("AI_APPROVED", "OWNER_APPROVED"):
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": f"APPROVAL_NOT_GRANTED: approval_status is '{approval_record.get('approval_status')}'",
        }

    # Reconcile approval candidate_commit with actual target peeled commit
    rec_candidate = str(approval_record.get("candidate_commit") or "").strip()
    if rec_candidate and rec_candidate != target_peeled_commit:
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": f"APPROVAL_COMMIT_MISMATCH: approval_record candidate_commit ({rec_candidate}) != target_peeled_commit ({target_peeled_commit})",
        }
    for sub_k in ("chatgpt_review", "owner_approval"):
        sub_rec = approval_record.get(sub_k)
        if isinstance(sub_rec, dict) and sub_rec.get("candidate_commit"):
            sub_c = str(sub_rec.get("candidate_commit")).strip()
            if sub_c != target_peeled_commit:
                return {
                    "status": "UPGRADE_BLOCKED",
                    "reason": f"APPROVAL_COMMIT_MISMATCH in {sub_k}: {sub_c} != target_peeled_commit ({target_peeled_commit})",
                }

    # 4. Validate compatibility
    compat = validate_upgrade_candidate(project_root=project_root, standards_root=std_root)
    if compat["status"] != "PASS":
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": "COMPATIBILITY_TESTS_FAILED",
            "errors": compat["errors"],
        }

    # 5. Preserve previous lock
    prev_locks = list(existing_lock.get("previous_locks") or [])
    if existing_lock.get("tag") and existing_lock.get("peeled_commit"):
        prev_locks.append(
            {
                "repository": existing_lock.get("repository", DEFAULT_OFFICIAL_REPO),
                "version": existing_lock.get("version", existing_lock.get("tag", "").lstrip("v")),
                "tag": existing_lock["tag"],
                "tag_object_sha": existing_lock.get("tag_object_sha", "0" * 40),
                "peeled_commit": existing_lock["peeled_commit"],
                "locked_at": existing_lock.get("locked_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                "lock_reason": existing_lock.get("lock_reason", "Preserved historical lock"),
                "approval_evidence_ref": existing_lock.get("approval_evidence_ref"),
                "ci_verification_status": existing_lock.get("ci_verification_status", "PASS"),
            }
        )

    new_lock = {
        "schema_version": "1.0.0",
        "repository": DEFAULT_OFFICIAL_REPO,
        "version": target_version.lstrip("v"),
        "tag": target_tag,
        "tag_object_sha": target_tag_object_sha,
        "peeled_commit": target_peeled_commit,
        "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lock_reason": f"Promoted to {target_tag} ({approval_record.get('approval_status')})",
        "approval_evidence_ref": approval_record.get("approval_reference", "verified-approval"),
        "ci_verification_status": "PASS",
        "previous_locks": prev_locks,
    }

    # 6. Transactional write to lock and engineering-manifest.yaml
    lock_tmp = project_root / "standards.lock.json.tmp"
    lock_tmp.write_text(json.dumps(new_lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest_path = project_root / "engineering-manifest.yaml"
    manifest_tmp = project_root / "engineering-manifest.yaml.tmp"
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if "standards" in manifest and isinstance(manifest["standards"], dict):
            manifest["standards"]["repository"] = DEFAULT_OFFICIAL_REPO
            manifest["standards"]["version"] = target_version.lstrip("v")
            manifest["standards"]["tag"] = target_tag
            manifest["standards"]["tag_object_sha"] = target_tag_object_sha
            manifest["standards"]["peeled_commit"] = target_peeled_commit
            manifest_tmp.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
            os.replace(manifest_tmp, manifest_path)

    os.replace(lock_tmp, lock_path)

    return {
        "status": "PROMOTED",
        "lock": new_lock,
    }


def rollback_lock(project_root: Path) -> Dict[str, Any]:
    """Rollback standards.lock.json to the most recent entry in previous_locks.
    Verifies historical lock integrity, preserves historical approval evidence and CI status,
    and applies transactional updates to standards.lock.json and engineering-manifest.yaml.
    """
    project_root = project_root.resolve()
    lock_path = project_root / "standards.lock.json"
    if not lock_path.exists():
        return {"status": "FAIL", "reason": "MISSING_STANDARDS_LOCK"}

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    prev_locks = list(lock.get("previous_locks") or [])
    if not prev_locks:
        return {"status": "FAIL", "reason": "NO_PREVIOUS_LOCK_HISTORY"}

    restored = prev_locks.pop()

    # Validate restored lock object
    for k in ("repository", "version", "tag", "tag_object_sha", "peeled_commit"):
        if not restored.get(k):
            return {"status": "FAIL", "reason": f"CORRUPT_HISTORICAL_LOCK: Missing '{k}'"}
    if not re.match(r"^[0-9a-f]{40}$", restored["tag_object_sha"]) or not re.match(r"^[0-9a-f]{40}$", restored["peeled_commit"]):
        return {"status": "FAIL", "reason": "CORRUPT_HISTORICAL_LOCK: Invalid 40-hex commit or tag object SHA"}

    # Preserve historical approval evidence ref and CI status; never fabricate fake rollback-restored
    hist_approval = restored.get("approval_evidence_ref")
    if not hist_approval:
        return {"status": "FAIL", "reason": "RESTORED_LOCK_MISSING_APPROVAL_EVIDENCE: Cannot restore historical lock lacking approval evidence"}

    hist_ci = restored.get("ci_verification_status", "NOT_VERIFIABLE")

    rolled_back_lock = {
        "schema_version": "1.0.0",
        "repository": restored["repository"],
        "version": restored["version"],
        "tag": restored["tag"],
        "tag_object_sha": restored["tag_object_sha"],
        "peeled_commit": restored["peeled_commit"],
        "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lock_reason": f"Rolled back to {restored['tag']}",
        "approval_evidence_ref": hist_approval,
        "ci_verification_status": hist_ci,
        "previous_locks": prev_locks,
    }

    # Transactional update
    lock_tmp = project_root / "standards.lock.json.tmp"
    lock_tmp.write_text(json.dumps(rolled_back_lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest_path = project_root / "engineering-manifest.yaml"
    manifest_tmp = project_root / "engineering-manifest.yaml.tmp"
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if "standards" in manifest and isinstance(manifest["standards"], dict):
            manifest["standards"]["version"] = restored["version"]
            manifest["standards"]["tag"] = restored["tag"]
            manifest["standards"]["tag_object_sha"] = restored["tag_object_sha"]
            manifest["standards"]["peeled_commit"] = restored["peeled_commit"]
            manifest_tmp.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
            os.replace(manifest_tmp, manifest_path)

    os.replace(lock_tmp, lock_path)

    return {
        "status": "ROLLED_BACK",
        "lock": rolled_back_lock,
    }
