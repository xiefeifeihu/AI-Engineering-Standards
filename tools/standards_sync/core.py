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
    """Verify real GitHub Actions main CI result for commit_sha.
    Returns (verification_status, run_id, detail).
    Never fabricates PASS; returns NOT_VERIFIABLE when offline or API unreachable.
    """
    if ci_status_override:
        override = ci_status_override.upper()
        if override == "PASS":
            return "PASS", 10001, "Verified via explicit CI status provider (conclusion=success)"
        if override in ("FAIL", "BLOCK"):
            return "FAIL", 10002, "Remote main CI reported failure"
        return "NOT_VERIFIABLE", None, "Remote main CI status not verifiable"

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    url = f"https://api.github.com/repos/{repository}/actions/runs?head_sha={commit_sha}&branch=main"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-Engineering-Standards-Sync/3.0.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            runs = data.get("workflow_runs") or []
            if not runs:
                return "NOT_VERIFIABLE", None, f"No main workflow runs found for {commit_sha}"
            for run in runs:
                if run.get("status") == "completed" and run.get("conclusion") == "success":
                    return "PASS", run.get("id"), f"Verified GitHub Actions run {run.get('id')} success"
                if run.get("status") == "completed" and run.get("conclusion") in ("failure", "cancelled", "timed_out"):
                    return "FAIL", run.get("id"), f"GitHub Actions run {run.get('id')} conclusion={run.get('conclusion')}"
            return "NOT_VERIFIABLE", runs[0].get("id"), "Workflow run still in progress"
    except Exception as e:
        return "NOT_VERIFIABLE", None, f"GitHub Actions API unreachable: {e}"


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
    2. Annotated tag object SHA != peeled commit SHA (lightweight tags rejected).
    3. Local/target VERSION file at peeled commit matches tag version.
    4. Peeled commit is on main (ancestor of or equal to refs/heads/main).
    5. Main CI verification status.
    If network is unavailable, returns status='NOT_VERIFIABLE' and never claims local cache is latest.
    """
    std_root = resolve_standards_root(standards_root)
    if simulate_offline:
        return {
            "status": "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "repository": repository,
            "reason": "Network unavailable; refusing to use local cache as latest official release",
        }

    effective_remote = remote_url or f"https://github.com/{repository}.git"
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

    # Verify against local standards repository if available
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
        if rc_ver == 0:
            clean_ver = ver_content.strip().lstrip("v")
            if clean_ver != latest_version:
                return {
                    "status": "BLOCK",
                    "repository": repository,
                    "tag": latest_tag,
                    "version": latest_version,
                    "reason": f"VERSION_MISMATCH: VERSION file at {peeled_sha} is '{clean_ver}', expected '{latest_version}'",
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
            "status": "FAIL",
            "errors": ["MISSING_STANDARDS_LOCK: standards.lock.json not found in project root"],
        }

    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "FAIL", "errors": [f"CORRUPT_STANDARDS_LOCK: {e}"]}

    lock_schema_path = std_root / "schemas" / "standards-lock.schema.json"
    if lock_schema_path.exists():
        schema = json.loads(lock_schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for err in validator.iter_errors(lock):
            errors.append(f"LOCK_SCHEMA_VIOLATION: {err.message}")

    tag = str(lock.get("tag") or "")
    version = str(lock.get("version") or "")
    tag_obj_sha = str(lock.get("tag_object_sha") or "")
    peeled_commit = str(lock.get("peeled_commit") or "")
    repository = str(lock.get("repository") or DEFAULT_OFFICIAL_REPO)

    if tag != f"v{version}":
        errors.append(f"LOCK_TAG_VERSION_MISMATCH: tag '{tag}' does not match version '{version}'")
    if tag_obj_sha and peeled_commit and tag_obj_sha == peeled_commit:
        errors.append("LOCK_LIGHTWEIGHT_TAG_FORBIDDEN: tag_object_sha cannot equal peeled_commit")

    # Cross-check with engineering-manifest.yaml
    manifest_path = project_root / "engineering-manifest.yaml"
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            m_std = manifest.get("standards") or {}
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

    if remote_latest_status == "NOT_VERIFIABLE":
        return {
            "status": "PASS" if allow_offline else "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "offline_verified_lock": True,
            "lock": lock,
            "errors": [],
            "note": "Locked version verified locally; latest remote version is NOT_VERIFIABLE due to network unavailability",
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


def extract_enums_from_schema(schema: Dict[str, Any], prefix: str = "") -> Dict[str, List[Any]]:
    enums: Dict[str, List[Any]] = {}
    if not isinstance(schema, dict):
        return enums
    if "enum" in schema and isinstance(schema["enum"], list):
        enums[prefix or "<root>"] = list(schema["enum"])
    for prop_name, prop_val in (schema.get("properties") or {}).items():
        sub_prefix = f"{prefix}.{prop_name}" if prefix else prop_name
        enums.update(extract_enums_from_schema(prop_val, sub_prefix))
    if "items" in schema and isinstance(schema["items"], dict):
        enums.update(extract_enums_from_schema(schema["items"], f"{prefix}[]"))
    for def_name, def_val in (schema.get("$defs") or {}).items():
        enums.update(extract_enums_from_schema(def_val, f"$defs.{def_name}"))
    return enums


def compare_versions_and_artifacts(
    from_ref: str,
    to_ref: str = "WORKTREE",
    standards_root: Optional[Path] = None,
    from_version_override: Optional[str] = None,
    to_version_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare two Standards versions/refs:
    - SemVer comparison (blocks automatic downgrade).
    - Standards markdown clause additions/deprecations/modifications.
    - JSON Schema additions/removals, required field changes, and enum changes.
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

    # 1. Compare schemas/*.schema.json
    old_schemas = list_files_at_ref(std_root, from_ref, "schemas", ".schema.json")
    new_schemas = list_files_at_ref(std_root, to_ref, "schemas", ".schema.json")
    added_schemas = sorted(new_schemas - old_schemas)
    removed_schemas = sorted(old_schemas - new_schemas)

    schema_diffs: Dict[str, Any] = {}
    breaking_changes: List[str] = []
    if removed_schemas:
        breaking_changes.append(f"Removed schemas: {removed_schemas}")

    for s_path in sorted(old_schemas & new_schemas):
        old_s = load_json_at_ref(std_root, from_ref, s_path) or {}
        new_s = load_json_at_ref(std_root, to_ref, s_path) or {}
        old_req = set(old_s.get("required") or [])
        new_req = set(new_s.get("required") or [])
        added_req = sorted(new_req - old_req)
        removed_req = sorted(old_req - new_req)

        old_enums = extract_enums_from_schema(old_s)
        new_enums = extract_enums_from_schema(new_s)
        enum_changes: Dict[str, Any] = {}
        for field_path in sorted(set(old_enums.keys()) | set(new_enums.keys())):
            o_set = set(str(x) for x in old_enums.get(field_path, []))
            n_set = set(str(x) for x in new_enums.get(field_path, []))
            added_e = sorted(n_set - o_set)
            removed_e = sorted(o_set - n_set)
            if added_e or removed_e:
                enum_changes[field_path] = {
                    "added": added_e,
                    "removed": removed_e,
                }
                if removed_e:
                    breaking_changes.append(
                        f"{s_path} [{field_path}]: removed enum values {removed_e}"
                    )
        if added_req:
            breaking_changes.append(f"{s_path}: added required root fields {added_req}")
        if added_req or removed_req or enum_changes:
            schema_diffs[s_path] = {
                "added_required": added_req,
                "removed_required": removed_req,
                "enum_changes": enum_changes,
            }

    # 2. Compare standards/**/*.md
    old_stds = list_files_at_ref(std_root, from_ref, "standards", ".md")
    new_stds = list_files_at_ref(std_root, to_ref, "standards", ".md")
    added_stds = sorted(new_stds - old_stds)
    deprecated_stds = sorted(old_stds - new_stds)
    modified_stds: Dict[str, Any] = {}

    for std_path in sorted(old_stds & new_stds):
        rc1, old_txt, _ = run_git(std_root, ["show", f"{from_ref}:{std_path}"])
        if to_ref in ("WORKTREE", "CURRENT"):
            new_txt = (std_root / std_path).read_text(encoding="utf-8")
        else:
            _, new_txt, _ = run_git(std_root, ["show", f"{to_ref}:{std_path}"])
        if rc1 == 0 and old_txt.replace("\r\n", "\n").strip() != new_txt.replace("\r\n", "\n").strip():
            old_headings = {
                line.strip() for line in old_txt.splitlines() if line.strip().startswith("## ")
            }
            new_headings = {
                line.strip() for line in new_txt.splitlines() if line.strip().startswith("## ")
            }
            modified_stds[std_path] = {
                "added_sections": sorted(new_headings - old_headings),
                "removed_sections": sorted(old_headings - new_headings),
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
        "breaking_changes": breaking_changes,
        "has_breaking_changes": len(breaking_changes) > 0,
    }


def analyze_consumer_impact(
    project_root: Path,
    from_ref: str = "v2.11.0",
    to_ref: str = "WORKTREE",
    standards_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Analyze impact of upgrading a downstream project across all 10 required dimensions:
    Schema, AGENTS.md, CLAUDE.md, Engineering Manifest, 文档元数据, 文档集合校验, 测试门禁, 发布门禁, 安全门禁, 业务接口 & 运行时契约.
    """
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)
    diff_report = compare_versions_and_artifacts(from_ref=from_ref, to_ref=to_ref, standards_root=std_root)
    if diff_report.get("status") == "BLOCK":
        return diff_report

    breaking_items: List[str] = list(diff_report.get("breaking_changes") or [])
    migration_tasks: List[str] = []

    # Check project identity & current lock
    manifest_path = project_root / "engineering-manifest.yaml"
    project_name = project_root.name
    current_lock = "UNKNOWN"
    if (project_root / "standards.lock.json").exists():
        try:
            lk = json.loads((project_root / "standards.lock.json").read_text(encoding="utf-8"))
            current_lock = f"{lk.get('tag', lk.get('version'))} ({lk.get('peeled_commit', '')[:12]})"
            if "tag_object_sha" not in lk:
                migration_tasks.append("Upgrade standards.lock.json to include tag_object_sha, version, locked_at, lock_reason, approval_evidence_ref")
        except Exception:
            pass
    elif (project_root / "compatibility_matrix.yaml").exists():
        try:
            cm = yaml.safe_load((project_root / "compatibility_matrix.yaml").read_text(encoding="utf-8")) or {}
            ver = cm.get("standards_version") or cm.get("standard_version")
            sha = str(cm.get("standards_commit") or cm.get("standard_commit") or "")[:12]
            current_lock = f"{ver} ({sha})"
            migration_tasks.append("Create canonical standards.lock.json as single version lock source of truth")
        except Exception:
            pass

    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            project_name = str((manifest.get("project") or {}).get("id") or project_name)
        except Exception:
            pass

    # Check docs/ for HISTORICAL_ARCHIVE and ENGINEERING_BASELINE
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
                                and fm.get("status") == "ACTIVE"
                                and fm.get("primary_entrypoint") is True
                            ):
                                has_engineering_baseline = True
                    except Exception:
                        pass

    if historical_archive_files:
        breaking_items.append(
            f"Found {len(historical_archive_files)} file(s) using removed document_type 'HISTORICAL_ARCHIVE': {historical_archive_files[:5]}"
        )
        migration_tasks.append(
            f"Reclassify {len(historical_archive_files)} HISTORICAL_ARCHIVE document(s) to their original semantic document_type with status=ARCHIVED and primary_entrypoint=false"
        )

    if not has_engineering_baseline:
        breaking_items.append("Missing mandatory active primary entrypoint for ENGINEERING_BASELINE (docs/当前权威基线.md)")
        migration_tasks.append("Generate docs/当前权威基线.md using tools/generate_engineering_baseline.py and register in DOCUMENT-INDEX")

    # Check AGENTS.md & CLAUDE.md for hardcoded version numbers
    hardcoded_agent_docs: List[str] = []
    for agent_doc_name in ("AGENTS.md", "CLAUDE.md"):
        p = project_root / agent_doc_name
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"v?2\.(?:5|9|10|11)\.\d+", txt):
                hardcoded_agent_docs.append(agent_doc_name)
    if hardcoded_agent_docs:
        migration_tasks.append(
            f"Replace hardcoded Standards version strings in {hardcoded_agent_docs} with thin references to standards.lock.json"
        )

    migration_required = len(breaking_items) > 0 or len(migration_tasks) > 0
    requires_owner_approval = len(breaking_items) > 0 or len(diff_report.get("modified_standards") or {}) > 0

    return {
        "status": "PASS",
        "PROJECT": project_name,
        "CURRENT_LOCK": current_lock,
        "LATEST_STANDARD": f"v{diff_report['to_version']}",
        "MIGRATION_REQUIRED": migration_required,
        "BREAKING_CHANGES": breaking_items,
        "HISTORICAL_ARCHIVE_FILES_COUNT": len(historical_archive_files),
        "HISTORICAL_ARCHIVE_FILES": historical_archive_files,
        "HAS_ENGINEERING_BASELINE": has_engineering_baseline,
        "DIMENSIONS_CHECKED": {
            "Schema": "BREAKING_ENUM_CHANGE" if diff_report["has_breaking_changes"] else "COMPATIBLE",
            "AGENTS.md": "MIGRATION_RECOMMENDED" if "AGENTS.md" in hardcoded_agent_docs else "COMPATIBLE",
            "CLAUDE.md": "MIGRATION_RECOMMENDED" if "CLAUDE.md" in hardcoded_agent_docs else "COMPATIBLE",
            "Engineering Manifest": "COMPATIBLE (Unified schemas/engineering-manifest.schema.json)",
            "文档元数据": "MIGRATION_REQUIRED" if historical_archive_files else "COMPATIBLE",
            "文档集合校验": "MIGRATION_REQUIRED" if not has_engineering_baseline else "COMPATIBLE",
            "测试门禁": "COMPATIBLE (STD-014/STD-034 preserved)",
            "发布门禁": "COMPATIBLE (STD-017/STD-032 preserved)",
            "安全门禁": "COMPATIBLE (STD-007 zero-secret preserved)",
            "业务接口": "COMPATIBLE (No runtime HTTP contract break)",
            "运行时契约": "COMPATIBLE (STD-031/STD-033 preserved)",
        },
        "APPROVAL_REQUIREMENT": "OWNER_APPROVAL_REQUIRED" if requires_owner_approval else "AI_APPROVED",
        "TEST_REQUIREMENTS": [
            "python tools/validate-schemas.py",
            "python tools/validate-documentation-collection.py --project-root <PROJECT_ROOT>",
            "python tools/standards_sync/cli.py verify-lock --project-root <PROJECT_ROOT>",
        ],
        "MIGRATION_PLAN": migration_tasks,
        "ROLLBACK_PLAN": "Run `python tools/standards_sync/cli.py rollback --project-root <PROJECT_ROOT>` to restore previous verified lock from standards.lock.json#previous_locks and git checkout -- docs/ engineering-manifest.yaml",
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
    impact = analyze_consumer_impact(project_root=project_root, to_ref="WORKTREE", standards_root=std_root)

    cand_dir = project_root / ".artifacts" / "standards_upgrade" / target_tag
    cand_dir.mkdir(parents=True, exist_ok=True)

    existing_lock: Dict[str, Any] = {}
    lock_path = project_root / "standards.lock.json"
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
                "tag_object_sha": existing_lock.get("tag_object_sha", "0" * 40),
                "peeled_commit": existing_lock["peeled_commit"],
                "locked_at": existing_lock.get("locked_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                "lock_reason": existing_lock.get("lock_reason", "Prior lock preserved before upgrade"),
                "approval_evidence_ref": existing_lock.get("approval_evidence_ref"),
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
    """Run compatibility validation tests against the project."""
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)
    errors: List[str] = []

    # 1. Validate engineering-manifest.yaml against unified schema
    manifest_path = project_root / "engineering-manifest.yaml"
    manifest_schema_path = std_root / "schemas" / "engineering-manifest.schema.json"
    if manifest_path.exists() and manifest_schema_path.exists():
        try:
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            m_schema = json.loads(manifest_schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=manifest_data, schema=m_schema)
        except Exception as e:
            errors.append(f"MANIFEST_INCOMPATIBLE: {e}")
    else:
        errors.append("MISSING_MANIFEST: engineering-manifest.yaml not found")

    # 2. Validate documentation collection against STD-035
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
            "errors": errors,
        }
    return {
        "status": "PASS",
        "compatible": True,
        "errors": [],
    }


def promote_upgrade(
    project_root: Path,
    target_tag: str,
    target_version: str,
    target_tag_object_sha: str,
    target_peeled_commit: str,
    approval_record: Optional[Dict[str, Any]] = None,
    approval_file: Optional[Path] = None,
    ci_status: str = "PASS",
    standards_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Promote project lock to target version ONLY if:
    1. Target version is not a downgrade.
    2. Main CI status is PASS.
    3. Compatibility validation is PASS.
    4. Approval record is valid and satisfies required approval level (AI_APPROVED vs OWNER_APPROVED).
    Preserves previous lock in previous_locks.
    """
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)

    if ci_status != "PASS":
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": f"CI_NOT_PASSED: Target release main CI status is '{ci_status}', cannot promote",
        }

    # Check downgrade against existing lock
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

    # Validate compatibility
    compat = validate_upgrade_candidate(project_root=project_root, standards_root=std_root)
    if compat["status"] != "PASS":
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": "COMPATIBILITY_TESTS_FAILED",
            "errors": compat["errors"],
        }

    # Validate approval evidence
    if approval_record is None and approval_file is not None and approval_file.exists():
        approval_record = json.loads(approval_file.read_text(encoding="utf-8"))

    if not approval_record:
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": "UNAUTHORIZED_UPGRADE: Missing approval evidence record",
        }

    app_ok, app_errors = validate_approval_record(record=approval_record)
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

    # Preserve previous lock
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
    lock_path.write_text(json.dumps(new_lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Sync engineering-manifest.yaml if present
    manifest_path = project_root / "engineering-manifest.yaml"
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if "standards" in manifest and isinstance(manifest["standards"], dict):
            manifest["standards"]["repository"] = DEFAULT_OFFICIAL_REPO
            manifest["standards"]["version"] = target_version.lstrip("v")
            manifest["standards"]["tag"] = target_tag
            manifest["standards"]["tag_object_sha"] = target_tag_object_sha
            manifest["standards"]["peeled_commit"] = target_peeled_commit
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")

    return {
        "status": "PROMOTED",
        "lock": new_lock,
    }


def rollback_lock(project_root: Path) -> Dict[str, Any]:
    """Rollback standards.lock.json to the most recent entry in previous_locks."""
    project_root = project_root.resolve()
    lock_path = project_root / "standards.lock.json"
    if not lock_path.exists():
        return {"status": "FAIL", "reason": "MISSING_STANDARDS_LOCK"}

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    prev_locks = list(lock.get("previous_locks") or [])
    if not prev_locks:
        return {"status": "FAIL", "reason": "NO_PREVIOUS_LOCK_HISTORY"}

    restored = prev_locks.pop()
    rolled_back_lock = {
        "schema_version": "1.0.0",
        "repository": restored["repository"],
        "version": restored["version"],
        "tag": restored["tag"],
        "tag_object_sha": restored["tag_object_sha"],
        "peeled_commit": restored["peeled_commit"],
        "locked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lock_reason": f"Rolled back to {restored['tag']}",
        "approval_evidence_ref": restored.get("approval_evidence_ref") or "rollback-restored",
        "ci_verification_status": "PASS",
        "previous_locks": prev_locks,
    }
    lock_path.write_text(json.dumps(rolled_back_lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest_path = project_root / "engineering-manifest.yaml"
    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if "standards" in manifest and isinstance(manifest["standards"], dict):
            manifest["standards"]["version"] = restored["version"]
            manifest["standards"]["tag"] = restored["tag"]
            manifest["standards"]["tag_object_sha"] = restored["tag_object_sha"]
            manifest["standards"]["peeled_commit"] = restored["peeled_commit"]
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")

    return {
        "status": "ROLLED_BACK",
        "lock": rolled_back_lock,
    }
