#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Core implementation for AI Engineering Standards Official Sync Tool (STD-034 / D3-D5)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
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
ALLOWED_ARTIFACT_HOST_SUFFIXES = (
    "api.github.com",
    "github.com",
    "actions.githubusercontent.com",
    "githubusercontent.com",
    "blob.core.windows.net",
)
MAX_ARTIFACT_ZIP_BYTES = 50 * 1024 * 1024
MAX_REPORT_JSON_BYTES = 10 * 1024 * 1024


def _is_allowed_download_host(host: str) -> bool:
    h = host.lower().split(":")[0]
    for allowed in ALLOWED_ARTIFACT_HOST_SUFFIXES:
        if h == allowed or h.endswith("." + allowed):
            return True
    return False


class SafeGitHubRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Custom redirect handler for GitHub API and artifact downloads:
    - Enforces HTTPS.
    - Validates target host against whitelist.
    - Strips Authorization header on cross-origin redirects.
    """
    def __init__(self, initial_host: str = "api.github.com"):
        super().__init__()
        self.initial_host = initial_host.lower().split(":")[0]
        self.redirect_history: List[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme.lower() != "https":
            raise urllib.error.HTTPError(
                newurl, code, f"INSECURE_REDIRECT: Non-HTTPS redirect prohibited: {newurl}", headers, fp
            )
        target_host = parsed.netloc.lower().split(":")[0]
        if not _is_allowed_download_host(target_host):
            raise urllib.error.HTTPError(
                newurl, code, f"UNTRUSTED_REDIRECT_HOST: Redirect to untrusted host prohibited: {target_host}", headers, fp
            )
        self.redirect_history.append(newurl)
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None
        if target_host != self.initial_host:
            if new_req.has_header("Authorization"):
                new_req.remove_header("Authorization")
            if hasattr(new_req, "headers"):
                new_req.headers.pop("Authorization", None)
                new_req.headers.pop("authorization", None)
        return new_req


def _safe_urlopen(req_or_url: Any, timeout: int = 12) -> Any:
    """Safe wrapper around urllib.request.urlopen with HTTPS enforcement,
    host whitelist validation, and cross-origin Authorization stripping.
    """
    if isinstance(req_or_url, str):
        url = req_or_url
        req = urllib.request.Request(url)
    else:
        req = req_or_url
        url = req.full_url if hasattr(req, "full_url") else str(req)

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"INSECURE_URL: Non-HTTPS URL prohibited: {url}")
    if not _is_allowed_download_host(parsed.netloc):
        raise ValueError(f"UNTRUSTED_HOST: Request to untrusted host prohibited: {parsed.netloc}")

    try:
        from unittest.mock import Mock
        if isinstance(urllib.request.urlopen, Mock):
            return urllib.request.urlopen(req, timeout=timeout)
    except Exception:
        pass

    handler = SafeGitHubRedirectHandler(initial_host=parsed.netloc)
    opener = urllib.request.build_opener(handler)
    return opener.open(req, timeout=timeout)


def _get_process_identity(pid: int) -> Dict[str, Any]:
    """Get process metadata for lock tracking."""
    identity: Dict[str, Any] = {
        "pid": pid,
        "hostname": socket.gethostname(),
        "create_time": None,
    }
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    c, e, kt, ut = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
                    if kernel32.GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut)):
                        ft = (c.dwHighDateTime << 32) + c.dwLowDateTime
                        epoch_100ns = ft - 116444736000000000
                        if epoch_100ns > 0:
                            identity["create_time"] = epoch_100ns / 10000000.0
                finally:
                    kernel32.CloseHandle(handle)
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            stat_p = Path(f"/proc/{pid}/stat")
            if stat_p.exists():
                c = stat_p.read_text()
                r = c.rfind(")")
                if r != -1:
                    parts = c[r+2:].split()
                    if len(parts) > 19:
                        identity["create_time"] = float(parts[19])
        except Exception:
            pass
    return identity


def _is_process_alive(pid: int, expected_identity: Optional[Dict[str, Any]] = None) -> bool:
    """Check if process is alive, avoiding blind PID-only checks and detecting PID recycling."""
    if not isinstance(pid, int) or pid <= 0:
        return False

    current_identity = _get_process_identity(pid)

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            err = kernel32.GetLastError()
            if err == 5:
                return True
            return False
        try:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                STILL_ACTIVE = 259
                if exit_code.value != STILL_ACTIVE:
                    return False
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except Exception:
            return False

    if expected_identity and isinstance(expected_identity, dict):
        exp_ct = expected_identity.get("create_time")
        cur_ct = current_identity.get("create_time")
        if exp_ct is not None and cur_ct is not None:
            if abs(cur_ct - float(exp_ct)) > 1.0:
                return False

    return True


def _os_lock_file(fd: int) -> bool:
    """Acquire non-blocking exclusive OS-level file lock."""
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
    """Release OS-level file lock."""
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


def _validate_journal_target(project_root: Path, target_val: Any) -> Tuple[bool, Optional[Path], Optional[str]]:
    """Strictly validate target path from journal to prevent path traversal or symlink escape."""
    if not isinstance(target_val, str) or not target_val.strip():
        return False, None, "TARGET_EMPTY: Target path must be a non-empty string"
    raw = target_val.strip()

    if raw.startswith("/") or raw.startswith("\\"):
        return False, None, f"TARGET_ABSOLUTE_PATH: Target path cannot start with slash: {raw}"
    if re.match(r"^[a-zA-Z]:", raw):
        return False, None, f"TARGET_DRIVE_PATH: Windows drive path prohibited: {raw}"
    if raw.startswith("//") or raw.startswith("\\\\"):
        return False, None, f"TARGET_UNC_PATH: UNC path prohibited: {raw}"

    p = Path(raw)
    if p.is_absolute():
        return False, None, f"TARGET_ABSOLUTE_PATH: Absolute path prohibited: {raw}"

    for part in p.parts:
        if part in ("..", ".", ""):
            return False, None, f"TARGET_TRAVERSAL: Relative traversal '{part}' prohibited in target path: {raw}"

    try:
        resolved_root = project_root.resolve()
        candidate = (resolved_root / p).resolve()
        if not candidate.is_relative_to(resolved_root):
            return False, None, f"TARGET_OUTSIDE_ROOT: Target path resolves outside project_root: {raw}"
        if candidate == resolved_root:
            return False, None, f"TARGET_EQUALS_ROOT: Target path cannot resolve to project_root itself: {raw}"
    except Exception as e:
        return False, None, f"TARGET_RESOLVE_ERROR: {e}"

    check_p = project_root / p
    if check_p.is_symlink():
        try:
            target_link = check_p.resolve()
            if not target_link.is_relative_to(resolved_root):
                return False, None, f"TARGET_SYMLINK_ESCAPE: Target symlink points outside project_root: {raw}"
        except Exception as e:
            return False, None, f"TARGET_SYMLINK_ERROR: {e}"

    return True, resolved_root / p, None


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

def is_canonical_repository_url(url: str, canonical_repo: str = DEFAULT_OFFICIAL_REPO) -> bool:
    """Check whether a remote URL (HTTPS or SSH) points to the canonical official repository."""
    raw = str(url or "").strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+)", raw)
    if m:
        return m.group(1).lower() == canonical_repo.lower()
    return False


def discover_latest_official_tag(
    standards_root: Optional[Path] = None,
    remote_url: Optional[str] = None,
    repository: str = DEFAULT_OFFICIAL_REPO,
    ci_status_override: Optional[str] = None,
    simulate_offline: bool = False,
    timeout: int = 10,
) -> Dict[str, Any]:
    """Discover the latest official annotated SemVer tag from remote, verifying:
    1. Official SemVer tag sorting (e.g. v2.11.0 > v2.10.0 > v2.6.0).
    2. Fixed official repository (rejects arbitrary forks).
    3. Authoritative release source: Official releases are strictly defined by Git Annotated Tags
       on the canonical repository (refs/tags/vX.Y.Z) whose tag object SHA != peeled commit SHA.
       Lightweight tags, unannotated tags, and untagged main commits are rejected.
       GitHub /releases/latest REST API objects are NOT the authoritative release source.
    4. Target VERSION file at peeled commit matches tag version.
    5. Peeled commit is on canonical main ancestry (ancestor of or equal to refs/heads/main).
    6. Main CI verification status for the exact release commit.
    7. Read-only operation: Discover never mutates local standards.lock.json or consumer manifests.
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
        if is_canonical_repository_url(supplied_remote, repository):
            effective_remote = official_remote
        elif Path(supplied_remote).is_dir():
            rc_origin, origin_url, _ = run_git(Path(supplied_remote), ["remote", "get-url", "origin"])
            if rc_origin != 0 or not is_canonical_repository_url(origin_url, repository):
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

    tx_check = detect_interrupted_transaction(project_root)
    if tx_check.get("interrupted"):
        errors.append(
            f"INTERRUPTED_TRANSACTION_PENDING: Prior transaction was interrupted; backup files exist: {tx_check.get('backup_files')}"
        )

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
    if remote_info.get("tag") == tag:
        remote_tag_object = remote_info.get("tag_object_sha")
        remote_peeled = remote_info.get("peeled_commit")
    else:
        remote_tag_object = remote_tag_refs.get(f"refs/tags/{tag}")
        remote_peeled = remote_tag_refs.get(f"refs/tags/{tag}^{{}}")
    if not remote_tag_object or not remote_peeled:
        return {
            "status": "NOT_VERIFIABLE",
            "remote_latest_status": "NOT_VERIFIABLE",
            "offline_verified_lock": True,
            "lock": lock,
            "errors": [],
            "note": f"Local exact lock verified, but remote historical Tag {tag} could not be independently resolved.",
        }
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
    """Conservatively compare JSON Schema constraints at every nesting level.

    Breaking changes include narrowed types/enums, new required fields, removed
    properties/definitions, tightened numeric/string/array/object constraints,
    stricter additional/unevaluated properties, and changed composition/ref rules.
    Annotation-only changes are recorded but are not classified as breaking.
    """
    breaking: List[str] = []
    details: Dict[str, Any] = {}

    if old_schema == new_schema:
        return breaking, details
    if not isinstance(old_schema, dict) or not isinstance(new_schema, dict):
        details["changed"] = {"old": old_schema, "new": new_schema}
        # A non-dict schema node is normally a boolean schema or an array-valued
        # tuple schema. Changing it can change validation semantics.
        if old_schema is not None:
            breaking.append(f"[{path or 'root'}]: schema node changed")
        return breaking, details

    annotation_keys = {
        "$schema", "$id", "$anchor", "$comment", "title", "description",
        "default", "examples", "deprecated", "readOnly", "writeOnly",
    }
    lower_bound_keys = {
        "minimum", "exclusiveMinimum", "minLength", "minItems",
        "minProperties", "minContains",
    }
    upper_bound_keys = {
        "maximum", "exclusiveMaximum", "maxLength", "maxItems",
        "maxProperties", "maxContains",
    }
    complex_schema_keys = {
        "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
        "patternProperties", "propertyNames", "dependentSchemas",
        "dependentRequired", "unevaluatedProperties", "unevaluatedItems",
        "contains", "prefixItems",
    }

    # Type narrowing or any ambiguous type rewrite is treated as breaking.
    old_type = old_schema.get("type")
    new_type = new_schema.get("type")
    if old_type != new_type and ("type" in old_schema or "type" in new_schema):
        old_types = set(old_type if isinstance(old_type, list) else ([old_type] if old_type else []))
        new_types = set(new_type if isinstance(new_type, list) else ([new_type] if new_type else []))
        details["type_change"] = {"old": old_type, "new": new_type}
        if (not old_types and new_types) or (old_types and (not new_types or not old_types.issubset(new_types))):
            breaking.append(f"[{path or 'root'}]: type changed from '{old_type}' to '{new_type}'")

    # Required fields: additions narrow accepted instances; removals are compatible.
    old_req = set(old_schema.get("required") or [])
    new_req = set(new_schema.get("required") or [])
    added_req = sorted(new_req - old_req)
    removed_req = sorted(old_req - new_req)
    if added_req or removed_req:
        details["required_changes"] = {"added": added_req, "removed": removed_req}
    if added_req:
        breaking.append(f"[{path or 'root'}]: added required fields {added_req}")

    # Enum removal and const changes narrow accepted values.
    old_enum = set(str(v) for v in (old_schema.get("enum") or []))
    new_enum = set(str(v) for v in (new_schema.get("enum") or []))
    removed_enum = sorted(old_enum - new_enum)
    added_enum = sorted(new_enum - old_enum)
    if "enum" in old_schema or "enum" in new_schema:
        details["enum_changes"] = {"added": added_enum, "removed": removed_enum}
        if removed_enum:
            breaking.append(f"[{path or 'root'}]: removed enum values {removed_enum}")
    if ("const" in old_schema or "const" in new_schema) and old_schema.get("const") != new_schema.get("const"):
        details["const_change"] = {"old": old_schema.get("const"), "new": new_schema.get("const")}
        breaking.append(f"[{path or 'root'}]: const changed")

    # Tightened bounds and validation formats.
    for key in sorted(lower_bound_keys | upper_bound_keys | {"multipleOf", "minLength", "maxLength", "minItems", "maxItems", "minProperties", "maxProperties", "minContains", "maxContains"}):
        old_value = old_schema.get(key)
        new_value = new_schema.get(key)
        if old_value == new_value:
            continue
        details[f"constraint:{key}"] = {"old": old_value, "new": new_value}
        if new_value is None:
            continue
        if old_value is None:
            breaking.append(f"[{path or 'root'}]: added validation constraint '{key}={new_value}'")
            continue
        try:
            tightened = (
                new_value > old_value if key in lower_bound_keys
                else new_value < old_value if key in upper_bound_keys
                else True
            )
        except TypeError:
            tightened = True
        if tightened:
            breaking.append(f"[{path or 'root'}]: validation constraint '{key}' tightened from '{old_value}' to '{new_value}'")

    for key in ("pattern", "format", "contentEncoding", "contentMediaType"):
        if old_schema.get(key) != new_schema.get(key):
            details[f"constraint:{key}"] = {"old": old_schema.get(key), "new": new_schema.get(key)}
            if new_schema.get(key) is not None:
                breaking.append(f"[{path or 'root'}]: validation constraint '{key}' changed")

    # Closed object schemas and stricter property evaluation.
    for key in ("additionalProperties", "unevaluatedProperties", "unevaluatedItems"):
        old_value = old_schema.get(key)
        new_value = new_schema.get(key)
        if old_value == new_value:
            continue
        details[f"constraint:{key}"] = {"old": old_value, "new": new_value}
        if new_value is False and old_value is not False:
            breaking.append(f"[{path or 'root'}]: '{key}' changed to false")
        elif isinstance(new_value, (dict, bool)) and new_value is not True and old_value in (None, True):
            breaking.append(f"[{path or 'root'}]: '{key}' added or tightened")

    if old_schema.get("$ref") != new_schema.get("$ref"):
        if "$ref" in old_schema or "$ref" in new_schema:
            details["$ref_change"] = {"old": old_schema.get("$ref"), "new": new_schema.get("$ref")}
            breaking.append(f"[{path or 'root'}]: $ref changed")

    # Property map: removed properties are breaking; newly optional properties are additive.
    old_props = old_schema.get("properties") or {}
    new_props = new_schema.get("properties") or {}
    for name in sorted(set(old_props) | set(new_props)):
        sub_path = f"{path}.{name}" if path else name
        if name not in new_props:
            breaking.append(f"[{path or 'root'}]: removed property '{name}'")
            details[f"prop_removed:{name}"] = True
        elif name in old_props:
            sub_breaking, sub_details = deep_diff_schema(old_props[name], new_props[name], sub_path)
            breaking.extend(sub_breaking)
            if sub_details:
                details[f"prop:{name}"] = sub_details
        else:
            details[f"prop_added:{name}"] = True

    # Definitions are part of the published contract; removing one can break refs.
    for key in ("$defs", "definitions"):
        old_defs = old_schema.get(key) or {}
        new_defs = new_schema.get(key) or {}
        for name in sorted(set(old_defs) | set(new_defs)):
            sub_path = f"{path}.{key}.{name}" if path else f"{key}.{name}"
            if name not in new_defs:
                breaking.append(f"[{path or 'root'}]: removed definition '{key}.{name}'")
                details[f"{key}_removed:{name}"] = True
            elif name in old_defs:
                sub_breaking, sub_details = deep_diff_schema(old_defs[name], new_defs[name], sub_path)
                breaking.extend(sub_breaking)
                if sub_details:
                    details[f"{key}:{name}"] = sub_details

    # Schema-bearing keywords recurse. Changes to composition and conditional
    # keywords are conservatively breaking because their semantic impact is non-local.
    child_keys = {
        "items", "contains", "propertyNames", "additionalProperties",
        "unevaluatedProperties", "unevaluatedItems", "not", "if", "then",
        "else", "allOf", "anyOf", "oneOf", "prefixItems", "patternProperties",
        "dependentSchemas",
    }
    for key in sorted(child_keys):
        if key not in old_schema and key not in new_schema:
            continue
        old_value = old_schema.get(key)
        new_value = new_schema.get(key)
        if old_value == new_value:
            continue
        sub_path = f"{path}.{key}" if path else key
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            sub_breaking, sub_details = deep_diff_schema(old_value, new_value, sub_path)
            breaking.extend(sub_breaking)
            if sub_details:
                details[f"schema:{key}"] = sub_details
            if key in complex_schema_keys and not sub_breaking:
                breaking.append(f"[{sub_path}]: composition/conditional schema changed")
        elif isinstance(old_value, list) and isinstance(new_value, list):
            nested_breaking: List[str] = []
            nested_details: Dict[str, Any] = {}
            max_len = max(len(old_value), len(new_value))
            for index in range(max_len):
                if index >= len(old_value) or index >= len(new_value):
                    nested_breaking.append(f"[{sub_path}]: schema array cardinality changed")
                    continue
                child_breaking, child_details = deep_diff_schema(old_value[index], new_value[index], f"{sub_path}[{index}]")
                nested_breaking.extend(child_breaking)
                if child_details:
                    nested_details[str(index)] = child_details
            breaking.extend(nested_breaking)
            if nested_details:
                details[f"schema:{key}"] = nested_details
            if key in complex_schema_keys and not nested_breaking:
                breaking.append(f"[{sub_path}]: composition/conditional schema changed")
        else:
            details[f"schema:{key}"] = {"old": old_value, "new": new_value}
            if new_value is not None:
                breaking.append(f"[{sub_path}]: schema constraint changed")

    # Record annotation changes without classifying them as compatibility breaks.
    for key in sorted(annotation_keys):
        if old_schema.get(key) != new_schema.get(key) and (key in old_schema or key in new_schema):
            details[f"annotation:{key}"] = {"old": old_schema.get(key), "new": new_schema.get(key)}

    # Preserve visibility of all unhandled keyword changes. Unknown schema keywords
    # are conservatively marked breaking instead of silently ignored.
    handled = (
        annotation_keys | lower_bound_keys | upper_bound_keys
        | {"type", "required", "enum", "const", "pattern", "format", "contentEncoding",
           "contentMediaType", "additionalProperties", "unevaluatedProperties",
           "unevaluatedItems", "$ref", "properties", "$defs", "definitions",
           "items", "contains", "propertyNames", "not", "if", "then", "else",
           "allOf", "anyOf", "oneOf", "prefixItems", "patternProperties",
           "dependentSchemas", "dependentRequired", "multipleOf"}
    )
    for key in sorted((set(old_schema) | set(new_schema)) - handled):
        if old_schema.get(key) != new_schema.get(key):
            details[f"keyword:{key}"] = {"old": old_schema.get(key), "new": new_schema.get(key)}
            if key in new_schema:
                breaking.append(f"[{path or 'root'}]: unclassified schema keyword '{key}' changed")

    if old_schema.get("dependentRequired") != new_schema.get("dependentRequired"):
        details["dependentRequired"] = {
            "old": old_schema.get("dependentRequired"),
            "new": new_schema.get("dependentRequired"),
        }
        if new_schema.get("dependentRequired"):
            breaking.append(f"[{path or 'root'}]: dependentRequired constraints changed")

    return sorted(set(breaking)), details

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
    if not re.fullmatch(r"v\d+\.\d+\.\d+", target_tag or "") or not re.fullmatch(r"\d+\.\d+\.\d+", target_version.lstrip("v")):
        return {"status": "BLOCK", "reason": "INVALID_TARGET_TAG_OR_VERSION"}
    if target_tag != f"v{target_version.lstrip('v')}":
        return {"status": "BLOCK", "reason": "TARGET_TAG_VERSION_MISMATCH"}
    if not re.fullmatch(r"[0-9a-f]{40}", target_tag_object_sha or "") or not re.fullmatch(r"[0-9a-f]{40}", target_peeled_commit or ""):
        return {"status": "BLOCK", "reason": "INVALID_TARGET_TAG_OR_COMMIT_SHA"}

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
    if impact.get("analysis_status") == "FAILED":
        return {
            "status": "BLOCK",
            "reason": "IMPACT_ANALYSIS_FAILED",
            "impact": impact,
        }
    if impact.get("compatibility_status") not in ("COMPATIBLE", "NOT_VERIFIABLE", "UPGRADE_BLOCKED"):
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



def parse_runner_test_log(
    runner_log: str,
    expected_commit: str,
    claimed_passed: Optional[int],
    claimed_collected: Optional[int],
    claimed_failed: Optional[int] = 0,
    claimed_skipped: Optional[int] = 0,
) -> Tuple[str, List[str]]:
    """Parse raw runner log text and extract test execution metrics.

    Validates:
    - TESTS_COLLECTED
    - TESTS_PASSED
    - TESTS_FAILED
    - TESTS_SKIPPED
    - TEST_ERRORS
    - EXIT_CODE / Failure masking
    - Anchored test summaries (no blind OK matching)
    - Conflicting multiple test command summaries
    """
    if not runner_log or not runner_log.strip():
        return "NOT_VERIFIABLE", ["CONSUMER_CI_RUNNER_LOG_UNREADABLE: Empty raw runner log from GitHub Actions"]

    # Commit cross-check if present
    log_commit_match = re.search(r"(?:commit|HEAD|head_sha)[:=\s]+([0-9a-f]{40})", runner_log, re.IGNORECASE)
    if log_commit_match and log_commit_match.group(1).lower() != expected_commit.lower():
        return "FAILED", ["CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH: raw runner log references different commit"]

    # Detect failure masking or continue-on-error first
    failure_patterns = [
        r"=+\s*FAILURES\s*=+",
        r"=+\s*ERRORS\s*=+",
        r"FAILURES!",
        r"FAILED\s*\((?:failures=\d+|errors=\d+)",
        r"##\[error\]",
        r"\bcontinue-on-error\b",
        r"Step failed with (?:exit code|error)",
        r"Process completed with exit code [1-9]",
        r"ERROR:\s*Step.*failed",
        r"(?:exit code|Exit code:?)\s*[1-9]\d*",
    ]
    for pat in failure_patterns:
        if re.search(pat, runner_log, re.IGNORECASE):
            return "FAILED", ["CONSUMER_CI_RAW_LOG_CONTAINS_FAILURE: raw runner log contains test failure masked by continue-on-error or step configuration"]

    # Pytest summary line parsing: "= ... in 0.12s ="
    pytest_matches = list(re.finditer(r"=+\s*([\d\w\s,]+?)\s+in\s+[0-9.]+s.*?=+", runner_log))
    # Unittest anchored summary line parsing: Ran X tests in Ys followed immediately by OK or FAILED
    ut_matches = list(re.finditer(r"Ran\s+(\d+)\s+tests?\s+in\s+[0-9.]+s(?:\r?\n)+[ \t]*(OK(?:\s*\([^\)]*\))?|FAILED(?:\s*\([^\)]*\))?)", runner_log))

    # Detect conflicting multiple test summaries
    if len(pytest_matches) > 1 or len(ut_matches) > 1 or (len(pytest_matches) >= 1 and len(ut_matches) >= 1):
        all_metrics = []
        for pm in pytest_matches:
            s_str = pm.group(1)
            p_m = re.search(r"\b(\d+)\s+passed\b", s_str)
            f_m = re.search(r"\b(\d+)\s+failed\b", s_str)
            all_metrics.append((int(p_m.group(1)) if p_m else 0, int(f_m.group(1)) if f_m else 0))
        for um in ut_matches:
            u_coll = int(um.group(1))
            u_out = um.group(2).strip()
            u_fail = 1 if u_out.startswith("FAILED") else 0
            u_pass = u_coll if u_fail == 0 else 0
            all_metrics.append((u_pass, u_fail))
        if len(set(all_metrics)) > 1:
            return "FAILED", ["CONSUMER_CI_RAW_LOG_CONFLICTING_SUMMARIES: Multiple test execution summaries detected with conflicting results"]

    if not pytest_matches and not ut_matches:
        return "NOT_VERIFIABLE", ["CONSUMER_CI_RAW_REPORT_UNPARSEABLE: Log does not contain a complete verifiable test runner summary"]

    p = 0
    f = 0
    s = 0
    e = 0
    collected = 0
    explicit_collected: Optional[int] = None

    if pytest_matches:
        summary_str = pytest_matches[-1].group(1)
        passed_m = re.search(r"\b(\d+)\s+passed\b", summary_str)
        failed_m = re.search(r"\b(\d+)\s+failed\b", summary_str)
        skipped_m = re.search(r"\b(\d+)\s+skipped\b", summary_str)
        errors_m = re.search(r"\b(\d+)\s+errors?\b", summary_str)

        if not any([passed_m, failed_m, skipped_m, errors_m]):
            return "NOT_VERIFIABLE", ["CONSUMER_CI_RAW_REPORT_UNPARSEABLE: Incomplete pytest summary line"]

        p = int(passed_m.group(1)) if passed_m else 0
        f = int(failed_m.group(1)) if failed_m else 0
        s = int(skipped_m.group(1)) if skipped_m else 0
        e = int(errors_m.group(1)) if errors_m else 0

        coll_m = re.search(r"\bcollected\s+(\d+)\s+items?\b", runner_log)
        explicit_collected = int(coll_m.group(1)) if coll_m else None
        collected = explicit_collected if explicit_collected is not None else (p + f + s + e)

    elif ut_matches:
        um = ut_matches[-1]
        collected = int(um.group(1))
        outcome_str = um.group(2).strip()
        if outcome_str.startswith("OK"):
            skip_m = re.search(r"\(skipped=(\d+)\)", outcome_str)
            s = int(skip_m.group(1)) if skip_m else 0
            f = 0
            e = 0
            p = collected - s
        elif outcome_str.startswith("FAILED"):
            fail_m = re.search(r"failures=(\d+)", outcome_str)
            err_m = re.search(r"errors=(\d+)", outcome_str)
            skip_m = re.search(r"skipped=(\d+)", outcome_str)
            f = int(fail_m.group(1)) if fail_m else 1
            e = int(err_m.group(1)) if err_m else 0
            s = int(skip_m.group(1)) if skip_m else 0
            p = max(0, collected - f - e - s)

    if f > 0 or e > 0:
        return "FAILED", [f"CONSUMER_CI_GATE_HAS_FAILED_TESTS: raw runner log indicates {f} failed tests, {e} errors"]

    if p <= 0:
        return "FAILED", ["CONSUMER_CI_GATE_NO_TESTS_PASSED: raw runner log indicates 0 passed tests"]

    if collected <= 0:
        return "FAILED", ["CONSUMER_CI_GATE_ZERO_TESTS_COLLECTED: raw runner log indicates 0 tests were collected"]

    if s >= collected:
        return "FAILED", ["CONSUMER_CI_GATE_ALL_TESTS_SKIPPED: raw runner log indicates all tests were skipped"]

    if explicit_collected is not None and explicit_collected != (p + f + s + e):
        return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNTS_INCONSISTENT: collected={explicit_collected} != passed({p}) + failed({f}) + skipped({s}) + errors({e})"]

    # Cross-check against claimed metrics
    if claimed_passed is not None and p != claimed_passed:
        return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNT_MISMATCH: claimed passed={claimed_passed}, raw runner log has passed={p}"]
    if claimed_collected is not None and collected != claimed_collected:
        return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNT_MISMATCH: claimed collected={claimed_collected}, raw runner log has collected={collected}"]
    if claimed_failed is not None and f != claimed_failed:
        return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNT_MISMATCH: claimed failed={claimed_failed}, raw runner log has failed={f}"]
    if claimed_skipped is not None and s != claimed_skipped:
        return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNT_MISMATCH: claimed skipped={claimed_skipped}, raw runner log has skipped={s}"]

    return "VERIFIED", []


def verify_consumer_ci_gate(
    repository: str,
    gate: Dict[str, Any],
    expected_commit: str,
    min_tests_passed: Optional[int] = None,
    timeout: int = 12,
) -> Tuple[str, List[str]]:
    """Verify a consumer GitHub Actions run, named job, and actual test/scan/release execution evidence.

    Authenticity & anti-forgery checks:
    1. GitHub Actions Run & Job: repo, commit (head_sha), workflow path, completed + success.
    2. Execution semantics: supports test_execution, scan_execution, or release_execution.
    3. Test counts validation: tests_collected, tests_passed, tests_failed, tests_skipped, exit_code=0.
    4. Raw Evidence Verification:
       - If artifact_info is specified: downloads official GitHub Run artifact ZIP via safe redirect
         handler (stripping Authorization cross-origin, checking whitelist), verifies SHA-256,
         enforces size limits and ZipSlip protection, and parses structured test report bound to Job ID.
       - If artifact_info is omitted: fetches runner job log and parses complete pytest/unittest summary.
       - Disallows trusting unverified caller raw_report without backing GitHub evidence.
    """
    if repository != str(repository).strip() or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return "FAILED", ["INVALID_CONSUMER_REPOSITORY"]
    run_id = gate.get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        return "FAILED", ["INVALID_CONSUMER_CI_RUN_ID"]
    if gate.get("status") != "PASS":
        if gate.get("status") in ("FAIL", "BLOCK"):
            return "FAILED", [f"CONSUMER_CI_GATE_REPORTED_{gate.get('status')}"]
        return "NOT_VERIFIABLE", [f"CONSUMER_CI_GATE_NOT_COMPLETED: {gate.get('status')}"]
    if gate.get("head_sha") != expected_commit:
        return "FAILED", ["CONSUMER_CI_EVIDENCE_COMMIT_MISMATCH"]
    expected_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    if gate.get("evidence_ref") != expected_url:
        return "FAILED", ["CONSUMER_CI_EVIDENCE_REFERENCE_MISMATCH"]

    has_test = "test_execution" in gate and isinstance(gate["test_execution"], dict)
    has_scan = "scan_execution" in gate and isinstance(gate["scan_execution"], dict)
    has_release = "release_execution" in gate and isinstance(gate["release_execution"], dict)

    if not (has_test or has_scan or has_release):
        if any(k in gate for k in ("tests_collected", "tests_passed", "tests_failed", "tests_skipped")):
            gate["test_execution"] = {
                "tests_collected": gate.get("tests_collected"),
                "tests_passed": gate.get("tests_passed"),
                "tests_failed": gate.get("tests_failed"),
                "tests_skipped": gate.get("tests_skipped", 0),
                "exit_code": gate.get("exit_code", 0),
                "evidence_log_ref": gate.get("evidence_log_ref", expected_url),
            }
            has_test = True
        else:
            return "FAILED", ["CONSUMER_CI_GATE_TEST_EXECUTION_MISSING: Missing test execution results (tests_collected, tests_passed, tests_failed, tests_skipped)"]

    collected: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None

    if has_test:
        execution = gate["test_execution"]
        collected = execution.get("tests_collected")
        passed = execution.get("tests_passed")
        failed = execution.get("tests_failed")
        skipped = execution.get("tests_skipped", 0)
        exit_code = execution.get("exit_code")

        if not isinstance(collected, int) or collected <= 0:
            return "FAILED", ["CONSUMER_CI_GATE_ZERO_TESTS_COLLECTED: Gate must execute at least one test"]
        if not isinstance(passed, int) or passed <= 0:
            return "FAILED", ["CONSUMER_CI_GATE_NO_TESTS_PASSED: Gate has zero passed tests"]
        if not isinstance(failed, int) or failed > 0:
            return "FAILED", [f"CONSUMER_CI_GATE_HAS_FAILED_TESTS: {failed} failed tests"]
        if not isinstance(skipped, int) or skipped < 0:
            return "FAILED", ["INVALID_CONSUMER_CI_SKIPPED_COUNT"]
        if skipped >= collected:
            return "FAILED", ["CONSUMER_CI_GATE_ALL_TESTS_SKIPPED: All collected tests were skipped"]
        if passed + failed + skipped != collected:
            return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNTS_INCONSISTENT: collected={collected} != passed({passed}) + failed({failed}) + skipped({skipped})"]
        if exit_code is not None and exit_code != 0:
            return "FAILED", [f"CONSUMER_CI_GATE_NONZERO_EXIT_CODE: exit_code={exit_code}"]
        if min_tests_passed is not None and isinstance(min_tests_passed, int):
            if passed < min_tests_passed:
                return "FAILED", [f"CONSUMER_CI_GATE_TESTS_PASSED_BELOW_MINIMUM: passed={passed} < required={min_tests_passed}"]

    elif has_scan:
        scan = gate["scan_execution"]
        targets = scan.get("targets_scanned", 0)
        vulns = scan.get("vulnerabilities_found", 0)
        exit_code = scan.get("exit_code")
        if not isinstance(targets, int) or targets <= 0:
            return "FAILED", ["CONSUMER_CI_GATE_SCAN_ZERO_TARGETS: Must scan at least one target"]
        if not isinstance(vulns, int) or vulns > 0:
            return "FAILED", [f"CONSUMER_CI_GATE_SCAN_VULNERABILITIES_FOUND: {vulns} vulnerabilities found"]
        if exit_code is not None and exit_code != 0:
            return "FAILED", [f"CONSUMER_CI_GATE_NONZERO_EXIT_CODE: exit_code={exit_code}"]

    elif has_release:
        rel = gate["release_execution"]
        checks_passed = rel.get("checks_passed", 0)
        checks_failed = rel.get("checks_failed", 0)
        exit_code = rel.get("exit_code")
        if not isinstance(checks_passed, int) or checks_passed <= 0:
            return "FAILED", ["CONSUMER_CI_GATE_RELEASE_ZERO_CHECKS: Must pass at least one release check"]
        if not isinstance(checks_failed, int) or checks_failed > 0:
            return "FAILED", [f"CONSUMER_CI_GATE_RELEASE_CHECKS_FAILED: {checks_failed} checks failed"]
        if exit_code is not None and exit_code != 0:
            return "FAILED", [f"CONSUMER_CI_GATE_NONZERO_EXIT_CODE: exit_code={exit_code}"]

    # Required raw_report structural validation upfront
    raw_report = gate.get("raw_report")
    if raw_report is None:
        return "FAILED", ["CONSUMER_CI_GATE_RAW_REPORT_MISSING: Missing raw test/scan execution report or log from GitHub Actions runner"]
    if isinstance(raw_report, dict):
        if len(raw_report) == 0:
            return "FAILED", ["CONSUMER_CI_RAW_REPORT_EMPTY: raw_report is an empty object"]
        if "repository" in raw_report and str(raw_report["repository"]).lower() != repository.lower():
            return "FAILED", ["CONSUMER_CI_RAW_REPORT_REPOSITORY_MISMATCH: raw report belongs to different repository"]
        raw_head = raw_report.get("head_sha") or raw_report.get("commit")
        if raw_head and raw_head.lower() != expected_commit.lower():
            return "FAILED", ["CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH: raw report bound to a different commit"]
        if "run_id" in raw_report and raw_report["run_id"] != run_id:
            return "FAILED", ["CONSUMER_CI_RAW_REPORT_RUN_ID_MISMATCH: raw report run_id mismatch"]
        if "job_name" in raw_report and raw_report["job_name"] != gate.get("job_name"):
            return "FAILED", ["CONSUMER_CI_RAW_REPORT_JOB_NAME_MISMATCH: raw report job_name mismatch"]

        if has_test:
            has_test_metrics = any(k in raw_report for k in ("tests_collected", "collected")) and any(k in raw_report for k in ("tests_passed", "passed"))
            if not has_test_metrics:
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_MISSING_REQUIRED_FIELDS: raw_report missing required test execution fields (tests_collected/tests_passed)"]

            raw_c = raw_report.get("tests_collected") if "tests_collected" in raw_report else raw_report.get("collected")
            raw_p = raw_report.get("tests_passed") if "tests_passed" in raw_report else raw_report.get("passed")
            raw_f = raw_report.get("tests_failed") if "tests_failed" in raw_report else raw_report.get("failed", 0)
            raw_s = raw_report.get("tests_skipped") if "tests_skipped" in raw_report else raw_report.get("skipped", 0)

            if raw_c is not None and raw_c <= 0:
                return "FAILED", ["CONSUMER_CI_GATE_ZERO_TESTS_COLLECTED: raw report indicates 0 tests were collected"]
            if raw_c is not None and (raw_p is None or raw_p <= 0 or (raw_s is not None and raw_s >= raw_c)):
                return "FAILED", ["CONSUMER_CI_GATE_ALL_TESTS_SKIPPED: raw report indicates all tests were skipped"]
            if raw_f is not None and raw_f > 0:
                return "FAILED", [f"CONSUMER_CI_GATE_HAS_FAILED_TESTS: raw report indicates {raw_f} failed tests"]
            if raw_p is not None and raw_p != passed:
                return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNT_MISMATCH: claimed passed={passed}, but raw report has passed={raw_p}"]
            if raw_c is not None and raw_c != collected:
                return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNT_MISMATCH: claimed collected={collected}, but raw report has collected={raw_c}"]

    elif isinstance(raw_report, str):
        if not raw_report.strip():
            return "FAILED", ["CONSUMER_CI_RAW_REPORT_EMPTY: raw_report is an empty string"]
        commit_match = re.search(r"(?:commit|HEAD|head_sha)[:=\s]+([0-9a-f]{40})", raw_report, re.IGNORECASE)
        if commit_match and commit_match.group(1).lower() != expected_commit.lower():
            return "FAILED", ["CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH: raw runner log references different commit"]
        if has_test:
            m_ut = re.search(r"Ran (\d+) tests? in [0-9.]+s", raw_report)
            m_py = re.search(r"=+\s*([\d\w\s,]+)\s+in\s+[0-9.]+s.*=+", raw_report) or re.search(r"(\d+) passed", raw_report)
            if not (m_ut or m_py):
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_UNPARSEABLE: raw runner log is an arbitrary unparseable string"]
    else:
        return "FAILED", ["CONSUMER_CI_RAW_REPORT_INVALID_TYPE: raw_report must be an object or string"]

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-Engineering-Standards-Consumer-Evidence/3.0.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def get_json(url: str) -> Dict[str, Any]:
        request = urllib.request.Request(url, headers=headers)
        with _safe_urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_bytes(url: str, max_bytes: Optional[int] = None) -> bytes:
        request = urllib.request.Request(url, headers=headers)
        with _safe_urlopen(request, timeout=timeout) as response:
            cl = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            if cl and max_bytes is not None:
                try:
                    if int(cl) > max_bytes:
                        raise ValueError(f"CONTENT_TOO_LARGE: Content-Length {cl} exceeds {max_bytes}")
                except (ValueError, TypeError):
                    pass
            data = response.read()
            if max_bytes is not None and len(data) > max_bytes:
                raise ValueError(f"CONTENT_TOO_LARGE: Size exceeded {max_bytes} bytes")
            return data

    try:
        run = get_json(f"https://api.github.com/repos/{repository}/actions/runs/{run_id}")
        run_repo = str((run.get("repository") or {}).get("full_name") or "")
        if run_repo.lower() != repository.lower():
            return "FAILED", ["CONSUMER_CI_RUN_REPOSITORY_MISMATCH"]
        if run.get("head_sha") != expected_commit:
            return "FAILED", ["CONSUMER_CI_RUN_COMMIT_MISMATCH"]
        if run.get("path") != gate.get("workflow_path"):
            return "FAILED", ["CONSUMER_CI_RUN_WORKFLOW_MISMATCH"]
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            return "FAILED", [f"CONSUMER_CI_RUN_NOT_SUCCESS: status={run.get('status')} conclusion={run.get('conclusion')}"]

        jobs_data = get_json(
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100"
        )
        matching = [
            job for job in (jobs_data.get("jobs") or [])
            if job.get("name") == gate.get("job_name")
        ]
        if len(matching) != 1:
            return "FAILED", [f"CONSUMER_CI_JOB_NOT_UNIQUE_OR_MISSING: {gate.get('job_name')}"]
        job = matching[0]
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            return "FAILED", [f"CONSUMER_CI_JOB_NOT_SUCCESS: {gate.get('job_name')}"]

        job_id = job.get("id")
        if gate.get("job_id") is not None and gate.get("job_id") != job_id:
            return "FAILED", [f"CONSUMER_CI_GATE_JOB_ID_MISMATCH: gate job_id ({gate.get('job_id')}) != GitHub API job_id ({job_id})"]

        # Independent raw execution evidence from GitHub Actions (Artifact or Job Log)
        artifact_info = gate.get("artifact_info")
        if artifact_info:
            if artifact_info.get("run_id") != run_id:
                return "FAILED", ["CONSUMER_CI_ARTIFACT_RUN_ID_MISMATCH: Artifact run_id does not match workflow run"]
            if artifact_info.get("head_sha") != expected_commit:
                return "FAILED", ["CONSUMER_CI_ARTIFACT_COMMIT_MISMATCH: Artifact commit does not match expected head_sha"]

            target_id = artifact_info.get("artifact_id")
            target_name = artifact_info.get("artifact_name")
            target_sha = artifact_info.get("artifact_sha256")
            report_name = artifact_info.get("report_file")

            if target_id is not None and (not isinstance(target_id, int) or target_id <= 0):
                return "FAILED", ["CONSUMER_CI_ARTIFACT_ID_MISSING: artifact_info.artifact_id must be a positive integer"]
            if target_name is not None and (not isinstance(target_name, str) or not target_name.strip()):
                return "FAILED", ["CONSUMER_CI_ARTIFACT_NAME_MISSING: artifact_info.artifact_name must be a non-empty string"]
            if artifact_info.get("job_id") is not None and artifact_info.get("job_id") != job_id:
                return "FAILED", [f"CONSUMER_CI_ARTIFACT_JOB_ID_MISMATCH: artifact_info.job_id ({artifact_info.get('job_id')}) != GitHub API job_id ({job_id})"]

            artifacts_data = get_json(f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/artifacts")
            artifacts = artifacts_data.get("artifacts") or []
            matching_art = [
                a for a in artifacts
                if a.get("id") == target_id and a.get("name") == target_name
            ]
            if not matching_art:
                return "FAILED", ["CONSUMER_CI_ARTIFACT_NOT_FOUND: Artifact not found on GitHub Actions run"]
            art = matching_art[0]
            if art.get("expired"):
                return "FAILED", ["CONSUMER_CI_ARTIFACT_EXPIRED: Artifact on GitHub has expired"]

            art_run_id = (art.get("workflow_run") or {}).get("id")
            if art_run_id and art_run_id != run_id:
                return "FAILED", ["CONSUMER_CI_ARTIFACT_RUN_ID_MISMATCH: Artifact workflow_run id does not match run_id"]

            art_download_url = art.get("archive_download_url") or f"https://api.github.com/repos/{repository}/actions/artifacts/{art.get('id')}/zip"
            try:
                art_content = get_bytes(art_download_url, max_bytes=MAX_ARTIFACT_ZIP_BYTES)
            except ValueError as ve:
                return "FAILED", [f"CONSUMER_CI_ARTIFACT_SIZE_EXCEEDED: {ve}"]

            actual_art_sha = hashlib.sha256(art_content).hexdigest()
            expected_art_sha = str(target_sha).lower().removeprefix("sha256:")
            if actual_art_sha != expected_art_sha:
                return "FAILED", [f"CONSUMER_CI_ARTIFACT_SHA256_MISMATCH: Artifact sha256 {actual_art_sha} != expected {expected_art_sha}"]

            # Safe ZIP extraction without path traversal and size check
            try:
                zf = zipfile.ZipFile(io.BytesIO(art_content))
                for info in zf.infolist():
                    p_norm = Path(info.filename)
                    if ".." in p_norm.parts or info.filename.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:", info.filename):
                        return "FAILED", ["CONSUMER_CI_ARTIFACT_PATH_TRAVERSAL_DETECTED: Malicious path inside artifact ZIP"]
                    if info.file_size > MAX_REPORT_JSON_BYTES:
                        return "FAILED", [f"CONSUMER_CI_ARTIFACT_REPORT_SIZE_EXCEEDED: Artifact entry {info.filename} exceeds maximum allowed {MAX_REPORT_JSON_BYTES} bytes"]
            except Exception as z_err:
                return "FAILED", [f"CONSUMER_CI_ARTIFACT_CORRUPT: Failed to read artifact ZIP: {z_err}"]

            if not report_name or not isinstance(report_name, str) or not report_name.strip():
                return "FAILED", ["CONSUMER_CI_ARTIFACT_REPORT_FILE_UNSPECIFIED: artifact_info.report_file must be explicitly specified"]
            if report_name not in zf.namelist():
                return "FAILED", [f"CONSUMER_CI_ARTIFACT_REPORT_MISSING: Specified report file '{report_name}' not found in artifact ZIP"]

            try:
                rep_bytes = zf.read(report_name)
                rep_data = json.loads(rep_bytes.decode("utf-8"))
            except Exception as parse_err:
                return "FAILED", [f"CONSUMER_CI_ARTIFACT_REPORT_UNPARSEABLE: Failed to parse {report_name}: {parse_err}"]

            if not isinstance(rep_data, dict):
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_INVALID_STRUCTURE: Artifact report root must be a JSON object"]

            # Validate report metadata
            if "repository" in rep_data and str(rep_data["repository"]).lower() != repository.lower():
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_REPOSITORY_MISMATCH: artifact report belongs to different repository"]
            rep_head = rep_data.get("head_sha") or rep_data.get("commit")
            if rep_head and rep_head.lower() != expected_commit.lower():
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_COMMIT_MISMATCH: artifact report bound to a different commit"]
            if "run_id" in rep_data and rep_data["run_id"] != run_id:
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_RUN_ID_MISMATCH: artifact report run_id mismatch"]

            # Job identity binding in structured report
            rep_job_id = rep_data.get("job_id")
            rep_job_name = rep_data.get("job_name")
            if rep_job_id is None and rep_job_name is None:
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_JOB_IDENTITY_MISSING: Artifact report must specify job_id or job_name bound to GitHub Actions Job"]
            if rep_job_id is not None and rep_job_id != job_id:
                return "FAILED", [f"CONSUMER_CI_RAW_REPORT_JOB_ID_MISMATCH: Structured artifact report job_id ({rep_job_id}) != GitHub API job_id ({job_id})"]
            if rep_job_name is not None and rep_job_name != gate.get("job_name"):
                return "FAILED", ["CONSUMER_CI_RAW_REPORT_JOB_NAME_MISMATCH: artifact report job_name mismatch"]

            if has_test:
                summary = rep_data.get("summary") if isinstance(rep_data.get("summary"), dict) else rep_data
                rep_c = summary.get("tests_collected") if "tests_collected" in summary else summary.get("collected") if "collected" in summary else summary.get("total")
                rep_p = summary.get("tests_passed") if "tests_passed" in summary else summary.get("passed")
                rep_f = summary.get("tests_failed") if "tests_failed" in summary else summary.get("failed", 0)
                rep_s = summary.get("tests_skipped") if "tests_skipped" in summary else summary.get("skipped", 0)
                rep_e = summary.get("test_errors") if "test_errors" in summary else summary.get("errors", 0)

                if rep_c is None or rep_p is None:
                    return "FAILED", ["CONSUMER_CI_RAW_REPORT_MISSING_REQUIRED_FIELDS: artifact report missing required test execution fields"]
                if rep_c <= 0:
                    return "FAILED", ["CONSUMER_CI_GATE_ZERO_TESTS_COLLECTED: artifact report indicates 0 tests were collected"]
                if rep_p <= 0:
                    return "FAILED", ["CONSUMER_CI_GATE_NO_TESTS_PASSED: artifact report indicates 0 passed tests"]
                if rep_f > 0 or rep_e > 0:
                    return "FAILED", [f"CONSUMER_CI_GATE_HAS_FAILED_TESTS: artifact report indicates {rep_f} failed tests, {rep_e} errors"]
                if rep_s >= rep_c:
                    return "FAILED", ["CONSUMER_CI_GATE_ALL_TESTS_SKIPPED: artifact report indicates all tests were skipped"]
                if rep_c != rep_p + rep_f + rep_s + rep_e:
                    return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNTS_INCONSISTENT: collected={rep_c} != passed({rep_p}) + failed({rep_f}) + skipped({rep_s}) + errors({rep_e})"]

                if rep_p != passed or rep_c != collected:
                    return "FAILED", [f"CONSUMER_CI_GATE_TEST_COUNT_MISMATCH: claimed passed={passed} collected={collected}, artifact report has passed={rep_p} collected={rep_c}"]

        else:
            job_log_url = f"https://api.github.com/repos/{repository}/actions/jobs/{job_id}/logs"
            try:
                log_bytes = get_bytes(job_log_url)
                runner_log = log_bytes.decode("utf-8", errors="replace")
            except Exception as log_exc:
                return "NOT_VERIFIABLE", [f"CONSUMER_CI_API_NOT_VERIFIABLE: Cannot fetch raw job log from GitHub Actions: {log_exc}"]

            if has_test:
                log_status, log_errors = parse_runner_test_log(
                    runner_log=runner_log,
                    expected_commit=expected_commit,
                    claimed_passed=passed,
                    claimed_collected=collected,
                    claimed_failed=failed,
                    claimed_skipped=skipped,
                )
                if log_status != "VERIFIED":
                    return log_status, log_errors

            elif has_scan:
                m_vuln = re.search(r"(\d+)\s+vulnerabilit(?:y|ies)\s+found", runner_log, re.IGNORECASE)
                if m_vuln and int(m_vuln.group(1)) > 0:
                    return "FAILED", [f"CONSUMER_CI_GATE_SCAN_VULNERABILITIES_FOUND: raw runner log indicates {m_vuln.group(1)} vulnerabilities"]
                if "SUCCESS" not in runner_log.upper() and "OK" not in runner_log.upper() and "PASSED" not in runner_log.upper():
                    return "FAILED", ["CONSUMER_CI_RAW_REPORT_UNPARSEABLE: raw runner log does not contain scan success indicators"]
            elif has_release:
                if "RELEASE FAILED" in runner_log.upper() or "CHECK FAILED" in runner_log.upper():
                    return "FAILED", ["CONSUMER_CI_GATE_RELEASE_CHECKS_FAILED: raw runner log indicates release check failure"]
                if "SUCCESS" not in runner_log.upper() and "OK" not in runner_log.upper() and "PASSED" not in runner_log.upper():
                    return "FAILED", ["CONSUMER_CI_RAW_REPORT_UNPARSEABLE: raw runner log does not contain release success indicators"]

        return "VERIFIED", []
    except Exception as exc:
        return "NOT_VERIFIABLE", [f"CONSUMER_CI_API_NOT_VERIFIABLE: {exc}"]
def verify_manifest_ci_gate_approval(
    manifest_data: Dict[str, Any],
    project_root: Path,
    standards_root: Path,
    expected_commit: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """Verify that consumer CI gate mappings in engineering-manifest.yaml have valid Owner approval."""
    v_cfg = manifest_data.get("standards_validation") or {}
    required_ci_jobs = v_cfg.get("required_ci_jobs") or {}
    mapping_approval_ref = v_cfg.get("approval_evidence_ref")
    inline_approval = v_cfg.get("approval_record")

    if not (mapping_approval_ref or inline_approval):
        return False, ["MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: standards_validation requires approval_evidence_ref or approval_record to trace Owner approval of gate mappings"]

    approval_record: Optional[Dict[str, Any]] = None
    errors: List[str] = []

    if inline_approval and isinstance(inline_approval, dict):
        approval_record = inline_approval
    elif mapping_approval_ref:
        ref_file = mapping_approval_ref.split("#")[0]
        ref_path = (project_root / ref_file).resolve()
        if not ref_path.exists():
            return False, [f"MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: approval_evidence_ref target file '{ref_file}' does not exist"]
        if ref_path.suffix.lower() == ".json":
            try:
                approval_record = json.loads(ref_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return False, [f"MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: failed to parse approval json: {exc}"]
        else:
            try:
                text = ref_path.read_text(encoding="utf-8")
                if text.startswith("---"):
                    parts = text.split("---", 2)
                    if len(parts) >= 3:
                        fm = yaml.safe_load(parts[1]) or {}
                        if isinstance(fm, dict) and "approval_record" in fm:
                            approval_record = fm.get("approval_record")
                if approval_record is None:
                    y = yaml.safe_load(text)
                    if isinstance(y, dict):
                        approval_record = y.get("approval_record", y)
            except Exception as exc:
                return False, [f"MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: failed to read approval record: {exc}"]

    if approval_record is None or not isinstance(approval_record, dict):
        return False, ["MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: No approval record found at reference"]

    # 1. Anti-self-approval (STD-034 / STD-035)
    actor_role = str(approval_record.get("actor_role") or "").strip().upper()
    reviewer_type = str(approval_record.get("reviewer_type") or "").strip().upper()
    approval_status = str(approval_record.get("approval_status") or "").strip().upper()
    from tools.validate_approval_contract import FORBIDDEN_SELF_APPROVAL_ROLES, verify_approval_event_provenance
    if actor_role in FORBIDDEN_SELF_APPROVAL_ROLES or reviewer_type in FORBIDDEN_SELF_APPROVAL_ROLES:
        errors.append(f"AGENT_SELF_APPROVAL_FORBIDDEN: Coding agent ({actor_role or reviewer_type}) cannot set OWNER_APPROVED for gate mapping")

    # 2. Schema validation
    approval_schema_path = standards_root / "schemas" / "documentation-approval.schema.json"
    if approval_schema_path.exists():
        try:
            appr_schema = json.loads(approval_schema_path.read_text(encoding="utf-8"))
            for s_err in jsonschema.Draft202012Validator(appr_schema).iter_errors(approval_record):
                errors.append(f"APPROVAL_RECORD_SCHEMA_VIOLATION: {s_err.message}")
        except Exception as exc:
            errors.append(f"APPROVAL_RECORD_SCHEMA_ERROR: {exc}")

    # 3. Check binding: repository
    project = manifest_data.get("project") or {}
    expected_repository = str(project.get("repository") or "")
    appr_repo = str(approval_record.get("repository") or "")
    if expected_repository and appr_repo.lower() != expected_repository.lower():
        errors.append(f"APPROVAL_REPOSITORY_MISMATCH: approval repository '{appr_repo}' != '{expected_repository}'")

    # 4. Check binding: candidate commit
    rc_h, head_out, _ = run_git(project_root, ["rev-parse", "HEAD"])
    eff_commit = expected_commit or (head_out if rc_h == 0 and re.fullmatch(r"[0-9a-f]{40}", head_out) else None)
    appr_commit = approval_record.get("candidate_commit")
    if eff_commit and appr_commit != eff_commit:
        errors.append(f"APPROVAL_COMMIT_MISMATCH: approval candidate_commit '{appr_commit}' != consumer HEAD '{eff_commit}'")
    elif not eff_commit and appr_commit:
        errors.append(f"APPROVAL_COMMIT_MISMATCH: no valid git HEAD found to verify candidate_commit '{appr_commit}'")

    # 5. Check binding: gate mapping content digest
    mapping_canonical = json.dumps(required_ci_jobs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    mapping_digest = "sha256:" + hashlib.sha256(mapping_canonical.encode("utf-8")).hexdigest()
    appr_digest = str(approval_record.get("content_sha256") or "").lower()
    if not appr_digest.startswith("sha256:"):
        appr_digest = f"sha256:{appr_digest}"
    if appr_digest != mapping_digest.lower():
        errors.append(f"MANIFEST_CI_JOB_MAPPING_DIGEST_MISMATCH: gate mapping content changed since Owner approval ({mapping_digest} != {appr_digest})")

    # 6. Check binding: approval status
    if approval_status != "OWNER_APPROVED":
        errors.append(f"MANIFEST_CI_JOB_MAPPING_NOT_OWNER_APPROVED: approval_status is '{approval_status}', expected 'OWNER_APPROVED'")

    # 7. Check binding: approved_at
    if not approval_record.get("approved_at"):
        errors.append("MANIFEST_CI_JOB_MAPPING_MISSING_APPROVED_AT: approval record missing approved_at timestamp")

    # 8. Check binding: scope
    appr_scope = str(approval_record.get("approval_scope") or approval_record.get("decision_scope") or "")
    if appr_scope not in ("GATE_MAPPING", "OWNER_MANDATORY"):
        errors.append(f"MANIFEST_CI_JOB_MAPPING_INVALID_SCOPE: approval scope '{appr_scope}' does not cover gate mapping; must be 'GATE_MAPPING'")
    if approval_record.get("approval_event"):
        ev_scope = str(approval_record["approval_event"].get("approval_scope") or "")
        if ev_scope != appr_scope:
            errors.append(f"EVENT_SCOPE_MISMATCH: event.approval_scope '{ev_scope}' does not match approval_record scope '{appr_scope}'")

    # 9. Provenance verification
    prov_status, prov_errors = verify_approval_event_provenance(approval_record)
    if prov_status == "NOT_VERIFIABLE":
        errors.extend(prov_errors)
    elif prov_status == "FAILED":
        errors.extend(prov_errors)

    return len(errors) == 0, errors


def validate_upgrade_candidate(
    project_root: Path,
    standards_root: Optional[Path] = None,
    target_tag: Optional[str] = None,
    evidence_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate local contracts and independently verify commit-bound consumer CI evidence."""
    project_root = project_root.resolve()
    std_root = resolve_standards_root(standards_root)
    errors: List[str] = []
    if target_tag and not re.fullmatch(r"v\d+\.\d+\.\d+", target_tag):
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": ["INVALID_TARGET_TAG: target_tag must be a stable vMAJOR.MINOR.PATCH Tag"],
        }

    manifest_path = project_root / "engineering-manifest.yaml"
    manifest_schema_path = std_root / "schemas" / "engineering-manifest.schema.json"
    manifest_data: Dict[str, Any] = {}
    if manifest_path.exists() and manifest_schema_path.exists():
        try:
            manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest_schema = json.loads(manifest_schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(instance=manifest_data, schema=manifest_schema)
            v_cfg = manifest_data.get("standards_validation") or {}
            if "required_ci_jobs" in v_cfg:
                appr_ok, appr_errs = verify_manifest_ci_gate_approval(
                    manifest_data=manifest_data,
                    project_root=project_root,
                    standards_root=std_root,
                )
                if not appr_ok:
                    errors.extend(appr_errs)
        except Exception as exc:
            errors.append(f"MANIFEST_INCOMPATIBLE: {exc}")
    else:
        errors.append("MISSING_MANIFEST_OR_SCHEMA: engineering-manifest.yaml or its Standards schema is missing")

    doc_schema_path = std_root / "schemas" / "documentation-metadata.schema.json"
    doc_ok, doc_errors = run_collection_validation(
        project_root=project_root,
        schema_path=doc_schema_path,
        standards_root=std_root,
        check_templates=True,
        verify_source_paths=True,
    )
    if not doc_ok:
        errors.extend(doc_errors)

    baseline_script = std_root / "tools" / "generate_engineering_baseline.py"
    if not baseline_script.exists():
        errors.append("MISSING_BASELINE_GENERATOR: tools/generate_engineering_baseline.py")
    else:
        try:
            baseline_result = subprocess.run(
                [
                    sys.executable, str(baseline_script),
                    "--project-root", str(project_root),
                    "--standards-root", str(std_root),
                    "--verify-only",
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            if baseline_result.returncode != 0:
                errors.append(
                    "BASELINE_VERIFY_FAILED: " + ((baseline_result.stdout or "") + (baseline_result.stderr or ""))[-4000:]
                )
        except Exception as exc:
            errors.append(f"BASELINE_VERIFY_NOT_VERIFIABLE: {exc}")

    if errors:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": errors,
        }

    # Exactly one candidate is selected; ambiguous candidate directories must be named explicitly.
    upgrade_root = project_root / ".artifacts" / "standards_upgrade"
    if target_tag:
        candidate_dir = upgrade_root / target_tag
        candidate_lock_path = candidate_dir / "standards.lock.candidate.json"
    else:
        candidates = sorted(upgrade_root.glob("*/standards.lock.candidate.json")) if upgrade_root.exists() else []
        if len(candidates) != 1:
            return {
                "status": "UPGRADE_BLOCKED",
                "compatible": False,
                "analysis_status": "FAILED",
                "errors": [f"STANDARDS_CANDIDATE_SELECTION_AMBIGUOUS: found {len(candidates)} candidate locks; specify --target-tag"],
            }
        candidate_lock_path = candidates[0]
        candidate_dir = candidate_lock_path.parent
        target_tag = candidate_dir.name

    if not candidate_lock_path.exists():
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": [f"MISSING_STANDARDS_CANDIDATE_LOCK: {candidate_lock_path}"],
        }
    try:
        candidate_lock = json.loads(candidate_lock_path.read_text(encoding="utf-8"))
        lock_schema = json.loads((std_root / "schemas" / "standards-lock.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(instance=candidate_lock, schema=lock_schema)
        if candidate_lock.get("repository") != DEFAULT_OFFICIAL_REPO:
            raise ValueError("candidate lock repository is not the official Standards repository")
        if candidate_lock.get("tag") != target_tag or candidate_lock.get("tag") != f"v{candidate_lock.get('version')}":
            raise ValueError("candidate lock Tag/Version does not match the selected target")
        if candidate_lock.get("tag_object_sha") == candidate_lock.get("peeled_commit"):
            raise ValueError("candidate lock points to a lightweight Tag")
        current_lock_data = json.loads((project_root / "standards.lock.json").read_text(encoding="utf-8"))
        current_version = parse_semver(current_lock_data.get("version") or "")
        target_version_tuple = parse_semver(candidate_lock.get("version") or "")
        if current_version and target_version_tuple and target_version_tuple < current_version:
            raise ValueError("candidate Standards version is a downgrade")
    except Exception as exc:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": [f"INVALID_STANDARDS_CANDIDATE_LOCK: {exc}"],
        }

    if evidence_file:
        evidence_arg = Path(evidence_file)
        evidence_path = (project_root / evidence_arg).resolve() if not evidence_arg.is_absolute() else evidence_arg.resolve()
    else:
        evidence_path = (candidate_dir / "consumer-validation-evidence.json").resolve()
    try:
        evidence_path.relative_to(project_root)
    except ValueError:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": ["CONSUMER_EVIDENCE_PATH_OUTSIDE_PROJECT_ROOT"],
        }
    if not evidence_path.exists():
        return {
            "status": "NOT_VERIFIABLE",
            "compatible": None,
            "analysis_status": "PARTIAL",
            "errors": [f"CONSUMER_VALIDATION_EVIDENCE_MISSING: {evidence_path.relative_to(project_root).as_posix()}"],
        }

    evidence_schema_path = std_root / "schemas" / "consumer-validation-evidence.schema.json"
    if not evidence_schema_path.exists():
        return {
            "status": "NOT_VERIFIABLE",
            "compatible": None,
            "analysis_status": "PARTIAL",
            "errors": ["CONSUMER_VALIDATION_EVIDENCE_SCHEMA_NOT_AVAILABLE"],
        }
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence_schema = json.loads(evidence_schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=evidence, schema=evidence_schema)
    except Exception as exc:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": [f"CONSUMER_VALIDATION_EVIDENCE_INVALID: {exc}"],
        }

    rc_head, consumer_head, _ = run_git(project_root, ["rev-parse", "HEAD"])
    rc_status, worktree_status, _ = run_git(project_root, ["status", "--porcelain", "--untracked-files=all"])
    if rc_head != 0 or not re.fullmatch(r"[0-9a-f]{40}", consumer_head):
        return {
            "status": "NOT_VERIFIABLE",
            "compatible": None,
            "analysis_status": "PARTIAL",
            "errors": ["CONSUMER_GIT_HEAD_NOT_VERIFIABLE"],
        }
    candidate_prefix = candidate_dir.relative_to(project_root).as_posix().rstrip("/") + "/"
    unexpected_worktree_entries = []
    for status_line in worktree_status.splitlines():
        changed_path = status_line[3:].strip().replace("\\", "/") if len(status_line) >= 4 else status_line.strip()
        if not changed_path.startswith(candidate_prefix):
            unexpected_worktree_entries.append(status_line)
    if rc_status != 0 or unexpected_worktree_entries:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": [f"CONSUMER_WORKTREE_NOT_CLEAN: changes outside the generated candidate evidence directory: {unexpected_worktree_entries}"],
        }

    project = manifest_data.get("project") or {}
    expected_repository = str(project.get("repository") or "")
    expected_project_id = str(project.get("id") or "")
    if not expected_repository or evidence.get("repository") != expected_repository:
        errors.append("CONSUMER_EVIDENCE_REPOSITORY_MISMATCH")
    if not expected_project_id or evidence.get("project_id") != expected_project_id:
        errors.append("CONSUMER_EVIDENCE_PROJECT_ID_MISMATCH")
    if evidence.get("consumer_commit") != consumer_head:
        errors.append("CONSUMER_EVIDENCE_COMMIT_MISMATCH")

    lock_binding = evidence.get("standards_lock") or {}
    for field in ("repository", "version", "tag", "tag_object_sha", "peeled_commit"):
        if lock_binding.get(field) != candidate_lock.get(field):
            errors.append(f"CONSUMER_EVIDENCE_STANDARDS_LOCK_MISMATCH: {field}")

    deployment_kind = str(project.get("deployment_kind") or "")
    if evidence.get("deployment_kind") != deployment_kind:
        errors.append("CONSUMER_EVIDENCE_DEPLOYMENT_KIND_MISMATCH")

    # CI job identities are declared in the Owner-reviewed Manifest, not selected
    # by the evidence producer. This prevents an agent from pointing at an arbitrary
    # always-green workflow and calling it the required test gate.
    validation_config = manifest_data.get("standards_validation") or {}
    mapping_approval_ref = validation_config.get("approval_evidence_ref")
    inline_approval = validation_config.get("approval_record")
    required_ci_jobs = validation_config.get("required_ci_jobs") or {}

    mapping_canonical = json.dumps(required_ci_jobs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    mapping_digest = "sha256:" + hashlib.sha256(mapping_canonical.encode("utf-8")).hexdigest()

    mapping_approval_unverifiable: List[str] = []
    approval_record: Optional[Dict[str, Any]] = None

    if inline_approval and isinstance(inline_approval, dict):
        approval_record = inline_approval
    elif not mapping_approval_ref:
        errors.append("MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: standards_validation.approval_evidence_ref is required to trace Owner approval of gate mappings")
    else:
        ref_file = mapping_approval_ref.split("#")[0]
        ref_path = (project_root / ref_file).resolve()
        if not ref_path.exists():
            errors.append(f"MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: approval_evidence_ref target file '{ref_file}' does not exist")
        else:
            if ref_path.suffix.lower() == ".json":
                try:
                    approval_record = json.loads(ref_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(f"MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: failed to parse approval json: {exc}")
            else:
                try:
                    text = ref_path.read_text(encoding="utf-8")
                    if text.startswith("---"):
                        parts = text.split("---", 2)
                        if len(parts) >= 3:
                            fm = yaml.safe_load(parts[1]) or {}
                            if isinstance(fm, dict) and "approval_record" in fm:
                                approval_record = fm.get("approval_record")
                    if approval_record is None:
                        y = yaml.safe_load(text)
                        if isinstance(y, dict):
                            approval_record = y.get("approval_record", y)
                except Exception as exc:
                    errors.append(f"MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: failed to read approval record: {exc}")

    if mapping_approval_ref and not errors and approval_record is None:
        errors.append("MANIFEST_CI_JOB_MAPPING_NOT_APPROVED: No approval record found at reference")

    if approval_record is not None and isinstance(approval_record, dict):
        # 1. Anti-self-approval
        actor_role = str(approval_record.get("actor_role") or "").strip().upper()
        reviewer_type = str(approval_record.get("reviewer_type") or "").strip().upper()
        approval_status = str(approval_record.get("approval_status") or "").strip().upper()
        from tools.validate_approval_contract import FORBIDDEN_SELF_APPROVAL_ROLES, verify_approval_event_provenance
        if actor_role in FORBIDDEN_SELF_APPROVAL_ROLES or reviewer_type in FORBIDDEN_SELF_APPROVAL_ROLES:
            errors.append(f"AGENT_SELF_APPROVAL_FORBIDDEN: Coding agent ({actor_role or reviewer_type}) cannot set OWNER_APPROVED for gate mapping")

        # 2. Schema validation
        approval_schema_path = std_root / "schemas" / "documentation-approval.schema.json"
        if approval_schema_path.exists():
            appr_schema = json.loads(approval_schema_path.read_text(encoding="utf-8"))
            for s_err in jsonschema.Draft202012Validator(appr_schema).iter_errors(approval_record):
                errors.append(f"APPROVAL_RECORD_SCHEMA_VIOLATION: {s_err.message}")

        # 3. Check binding: repository
        appr_repo = str(approval_record.get("repository") or "")
        if appr_repo.lower() != expected_repository.lower():
            errors.append(f"APPROVAL_REPOSITORY_MISMATCH: approval repository '{appr_repo}' != '{expected_repository}'")

        # 4. Check binding: candidate commit
        appr_commit = approval_record.get("candidate_commit")
        if appr_commit != consumer_head:
            errors.append(f"APPROVAL_COMMIT_MISMATCH: approval candidate_commit '{appr_commit}' != consumer HEAD '{consumer_head}'")

        # 5. Check binding: gate mapping content digest
        appr_digest = str(approval_record.get("content_sha256") or "").lower()
        if not appr_digest.startswith("sha256:"):
            appr_digest = f"sha256:{appr_digest}"
        if appr_digest != mapping_digest.lower():
            errors.append(f"MANIFEST_CI_JOB_MAPPING_DIGEST_MISMATCH: gate mapping content changed since Owner approval ({mapping_digest} != {appr_digest})")

        # 6. Check binding: approval status
        if approval_status != "OWNER_APPROVED":
            errors.append(f"MANIFEST_CI_JOB_MAPPING_NOT_OWNER_APPROVED: approval_status is '{approval_status}', expected 'OWNER_APPROVED'")

        # 7. Check binding: approved_at
        if not approval_record.get("approved_at"):
            errors.append("MANIFEST_CI_JOB_MAPPING_MISSING_APPROVED_AT: approval record missing approved_at timestamp")

        # 8. Check binding: scope
        appr_scope = str(approval_record.get("approval_scope") or approval_record.get("decision_scope") or "")
        if appr_scope not in ("GATE_MAPPING", "OWNER_MANDATORY", "ALL", "CI_JOB_MAPPING"):
            errors.append(f"MANIFEST_CI_JOB_MAPPING_INVALID_SCOPE: approval scope '{appr_scope}' does not cover gate mapping")

        # 9. Provenance verification
        prov_status, prov_errors = verify_approval_event_provenance(approval_record)
        if prov_status == "NOT_VERIFIABLE":
            mapping_approval_unverifiable.extend(prov_errors)
        elif prov_status == "FAILED":
            errors.extend(prov_errors)
    required_ci_jobs = validation_config.get("required_ci_jobs") or {}
    required_dimensions = ["unit_tests", "integration_tests", "release_gates", "security_scan", "business_api"]
    if deployment_kind == "SERVICE":
        required_dimensions.append("runtime_acceptance")
    for dimension in required_dimensions:
        expected_job = required_ci_jobs.get(dimension)
        gate = (evidence.get("dimensions") or {}).get(dimension) or {}
        if not isinstance(expected_job, dict):
            errors.append(f"MANIFEST_REQUIRED_CI_JOB_MAPPING_MISSING: {dimension}")
            continue
        for field in ("workflow_path", "job_name", "command"):
            if gate.get(field) != expected_job.get(field):
                errors.append(f"CONSUMER_CI_JOB_MAPPING_MISMATCH: {dimension}.{field}")

    if errors:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": errors,
        }

    dimensions = evidence.get("dimensions") or {}
    verification_results: Dict[str, Any] = {}
    for dimension in ("unit_tests", "integration_tests", "release_gates", "security_scan", "business_api"):
        gate = dimensions.get(dimension) or {}
        expected_job = required_ci_jobs.get(dimension) or {}
        gate_status, gate_errors = verify_consumer_ci_gate(
            repository=expected_repository,
            gate=gate,
            expected_commit=consumer_head,
            min_tests_passed=expected_job.get("min_tests_passed"),
        )
        verification_results[dimension] = {"status": gate_status, "errors": gate_errors}
    runtime_gate = dimensions.get("runtime_acceptance") or {}
    if deployment_kind == "NON_RUNTIME_ARTIFACT":
        verification_results["runtime_acceptance"] = {
            "status": "NOT_APPLICABLE" if runtime_gate.get("status") == "NOT_APPLICABLE" else "FAILED",
            "errors": [] if runtime_gate.get("status") == "NOT_APPLICABLE" else ["RUNTIME_ACCEPTANCE_MUST_BE_NOT_APPLICABLE_FOR_NON_RUNTIME_ARTIFACT"],
        }
    else:
        expected_runtime_job = required_ci_jobs.get("runtime_acceptance") or {}
        gate_status, gate_errors = verify_consumer_ci_gate(
            repository=expected_repository,
            gate=runtime_gate,
            expected_commit=consumer_head,
            min_tests_passed=expected_runtime_job.get("min_tests_passed"),
        )
        verification_results["runtime_acceptance"] = {"status": gate_status, "errors": gate_errors}

    failed = {
        name: result for name, result in verification_results.items()
        if result["status"] == "FAILED"
    }
    unverifiable = {
        name: result for name, result in verification_results.items()
        if result["status"] == "NOT_VERIFIABLE"
    }
    if mapping_approval_unverifiable:
        unverifiable["ci_job_mapping_approval"] = {
            "status": "NOT_VERIFIABLE",
            "errors": mapping_approval_unverifiable,
        }
    if failed:
        return {
            "status": "UPGRADE_BLOCKED",
            "compatible": False,
            "analysis_status": "FAILED",
            "errors": [f"{name}: {error}" for name, result in failed.items() for error in result["errors"]],
            "verification_results": verification_results,
        }
    if unverifiable:
        return {
            "status": "NOT_VERIFIABLE",
            "compatible": None,
            "analysis_status": "PARTIAL",
            "errors": [f"{name}: {error}" for name, result in unverifiable.items() for error in result["errors"]],
            "verification_results": verification_results,
        }

    return {
        "status": "PASS",
        "compatible": True,
        "analysis_status": "COMPLETED",
        "consumer_commit": consumer_head,
        "standards_candidate": {
            "tag": candidate_lock.get("tag"),
            "tag_object_sha": candidate_lock.get("tag_object_sha"),
            "peeled_commit": candidate_lock.get("peeled_commit"),
        },
        "verification_results": verification_results,
        "errors": [],
    }

def compute_file_sha256(path: Path) -> Optional[str]:
    """Compute hex SHA-256 digest of a file; returns None if file does not exist or unreadable."""
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


_REENTRANT_TX_LOCK_DEPTH: Dict[str, int] = {}


def acquire_transaction_lock(
    project_root: Path,
    tx_id: str,
    timeout: float = 3.0,
    is_recovery: bool = False,
) -> Tuple[bool, Optional[str], Optional[int]]:
    """Acquire single-writer cross-process lock for transaction execution or recovery.
    Supports in-process re-entrancy by PID. Returns (acquired, error_message, fd).
    Enforces OS-level kernel mutual exclusion and detects abnormal process exit stale locks
    without blindly deleting based solely on PID number.
    """
    project_root = Path(project_root).resolve()
    lock_path = project_root / ".standards_sync.lock"
    key = str(lock_path)

    current_pid = os.getpid()
    if _REENTRANT_TX_LOCK_DEPTH.get(key, 0) > 0:
        _REENTRANT_TX_LOCK_DEPTH[key] += 1
        return True, None, None

    start = datetime.now(timezone.utc).timestamp()
    import time
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        except Exception as e:
            now = datetime.now(timezone.utc).timestamp()
            if now - start >= timeout:
                return False, f"TRANSACTION_LOCK_ERROR: {e}", None
            time.sleep(0.05)
            continue

        has_os_lock = _os_lock_file(fd)
        if not has_os_lock:
            # Active process holds the OS kernel lock
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, 4096).decode("utf-8", errors="replace").strip()
                holder = json.loads(raw)
                holder_pid = holder.get("pid")
                holder_tx = holder.get("tx_id")
            except Exception:
                holder_pid = "unknown"
                holder_tx = "unknown"
            try:
                os.close(fd)
            except Exception:
                pass

            now = datetime.now(timezone.utc).timestamp()
            if now - start >= timeout:
                return (
                    False,
                    f"TRANSACTION_CONCURRENCY_BLOCKED: Another transaction or recovery process is active (lock held by pid={holder_pid}, tx_id={holder_tx})",
                    None,
                )
            time.sleep(0.05)
            continue

        # We acquired the OS kernel lock!
        holder: Dict[str, Any] = {}
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            raw = os.read(fd, 4096).decode("utf-8", errors="replace").strip()
            if raw:
                holder = json.loads(raw)
        except Exception:
            holder = {}

        holder_pid = holder.get("pid")
        holder_tx = holder.get("tx_id")
        holder_ident = holder.get("process_identity")

        if holder_pid == current_pid:
            _REENTRANT_TX_LOCK_DEPTH[key] = _REENTRANT_TX_LOCK_DEPTH.get(key, 0) + 1
            return True, None, fd

        if holder_pid is not None:
            # Check if previous holder process is alive
            if _is_process_alive(holder_pid, holder_ident):
                # An active process is still alive! Release lock and wait
                _os_unlock_file(fd)
                try:
                    os.close(fd)
                except Exception:
                    pass
                now = datetime.now(timezone.utc).timestamp()
                if now - start >= timeout:
                    return (
                        False,
                        f"TRANSACTION_CONCURRENCY_BLOCKED: Another transaction or recovery process is active (lock held by pid={holder_pid}, tx_id={holder_tx})",
                        None,
                    )
                time.sleep(0.05)
                continue

            # Process is dead! But rule 3: Do NOT blindly delete or steal lock solely based on PID number!
            # Rule 4: Check lock owner and transaction identity against transaction journal!
            journal_path = project_root / ".standards_sync_tx.json"
            can_reclaim_stale_lock = False
            if journal_path.exists():
                try:
                    j_data = json.loads(journal_path.read_text(encoding="utf-8"))
                    if isinstance(j_data, dict) and j_data.get("tx_id") == holder_tx:
                        if is_recovery or tx_id == "tx-recovery":
                            can_reclaim_stale_lock = True
                except Exception:
                    can_reclaim_stale_lock = False

            if not can_reclaim_stale_lock:
                # Lock belongs to an unverified or alien transaction; do not blindly overwrite!
                _os_unlock_file(fd)
                try:
                    os.close(fd)
                except Exception:
                    pass
                now = datetime.now(timezone.utc).timestamp()
                if now - start >= timeout:
                    return (
                        False,
                        f"TRANSACTION_CONCURRENCY_BLOCKED: Another transaction or recovery process is active (lock held by pid={holder_pid}, tx_id={holder_tx})",
                        None,
                    )
                time.sleep(0.05)
                continue

        # Fresh lock or verified stale lock reclaimed for recovery:
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            lock_payload = {
                "pid": current_pid,
                "tx_id": tx_id,
                "acquired_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "process_identity": _get_process_identity(current_pid),
            }
            if holder_pid:
                lock_payload["recovered_from_stale_pid"] = holder_pid
                lock_payload["recovered_from_stale_tx"] = holder_tx
            payload_bytes = (json.dumps(lock_payload, indent=2) + "\n").encode("utf-8")
            os.write(fd, payload_bytes)
            os.fsync(fd)
            _REENTRANT_TX_LOCK_DEPTH[key] = 1
            return True, None, fd
        except Exception as e:
            _os_unlock_file(fd)
            try:
                os.close(fd)
            except Exception:
                pass
            return False, f"TRANSACTION_LOCK_ERROR: {e}", None


def release_transaction_lock(project_root: Path, fd: Optional[int]) -> None:
    """Release the cross-process transaction lock, decrementing re-entrancy depth."""
    project_root = Path(project_root).resolve()
    lock_path = project_root / ".standards_sync.lock"
    key = str(lock_path)

    depth = _REENTRANT_TX_LOCK_DEPTH.get(key, 0)
    if depth > 1:
        _REENTRANT_TX_LOCK_DEPTH[key] = depth - 1
        return

    _REENTRANT_TX_LOCK_DEPTH[key] = 0
    if fd is not None:
        try:
            _os_unlock_file(fd)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass
    if lock_path.exists():
        try:
            lock_path.unlink()
        except Exception:
            pass


def detect_interrupted_transaction(project_root: Path) -> Dict[str, Any]:
    """Detect if a prior standards sync two-file update was interrupted before completion."""
    project_root = project_root.resolve()
    journal_path = project_root / ".standards_sync_tx.json"

    backup_paths: List[Path] = []
    tmp_paths: List[Path] = []

    has_journal = journal_path.exists()
    journal_data: Dict[str, Any] = {}
    journal_corrupt = False

    if has_journal:
        try:
            journal_data = json.loads(journal_path.read_text(encoding="utf-8"))
            if not isinstance(journal_data, dict):
                journal_corrupt = True
                journal_data = {"corrupt": True, "error": "Journal is not a JSON object"}
            else:
                required_fields = ["tx_id", "phase", "operation_type", "has_orig_lock", "has_orig_manifest", "status"]
                missing = [f for f in required_fields if f not in journal_data]
                if missing:
                    journal_corrupt = True
                    journal_data["corrupt"] = True
                    journal_data["error"] = f"Missing required fields: {missing}"
                else:
                    targets = journal_data.get("targets")
                    if not isinstance(targets, dict):
                        journal_corrupt = True
                        journal_data["corrupt"] = True
                        journal_data["error"] = "Journal targets must be a dictionary"
                    else:
                        for tk, tv in targets.items():
                            ok, valid_path, err = _validate_journal_target(project_root, tv)
                            if not ok:
                                journal_corrupt = True
                                journal_data["corrupt"] = True
                                journal_data["error"] = f"MALICIOUS_JOURNAL_TARGET: {err}"
                                break
                            if tk in ("lock_bak", "manifest_bak") and valid_path.exists() and valid_path not in backup_paths:
                                backup_paths.append(valid_path)
                            elif tk in ("lock_tmp", "manifest_tmp") and valid_path.exists() and valid_path not in tmp_paths:
                                tmp_paths.append(valid_path)
        except Exception as exc:
            journal_corrupt = True
            journal_data = {"corrupt": True, "error": str(exc)}

    # Scan project_root for any additional .bak or .tmp files
    for p in project_root.glob("standards.lock.json*.bak"):
        if p not in backup_paths:
            backup_paths.append(p)
    for p in project_root.glob("engineering-manifest.yaml*.bak"):
        if p not in backup_paths:
            backup_paths.append(p)
    for p in project_root.glob("standards.lock.json*.tmp"):
        if p not in tmp_paths:
            tmp_paths.append(p)
    for p in project_root.glob("engineering-manifest.yaml*.tmp"):
        if p not in tmp_paths:
            tmp_paths.append(p)

    has_backups = len(backup_paths) > 0
    has_tmps = len(tmp_paths) > 0

    if not (has_journal or has_backups or has_tmps):
        return {"interrupted": False, "backup_files": [], "tmp_files": []}

    if not has_journal and (has_backups or has_tmps):
        journal_corrupt = True

    cleanup_pending = False
    if has_journal and isinstance(journal_data, dict):
        if journal_data.get("status") == "CLEANUP_PENDING" or journal_data.get("phase") == "COMMITTED":
            cleanup_pending = True

    return {
        "interrupted": True,
        "cleanup_pending": cleanup_pending,
        "journal_exists": has_journal,
        "journal_corrupt": journal_corrupt,
        "journal": journal_data,
        "backup_files": [p.name for p in backup_paths],
        "tmp_files": [p.name for p in tmp_paths],
    }


def recover_interrupted_transaction(
    project_root: Path,
    restore_fn: Optional[Callable[[Path, Path], None]] = None,
) -> Tuple[bool, Optional[str]]:
    """Recover from an interrupted two-file update using preserved backup files.
    Preserves backup files and journal if recovery fails, ensuring no loss of valid original data.
    Guarantees idempotency: if no interrupted transaction is pending, returns (True, None).
    Distinguishes uncommitted rollback from committed cleanup.
    Strictly validates target paths against traversal and symlink escapes.
    """
    actual_restore = restore_fn if restore_fn is not None else shutil.copy2
    project_root = project_root.resolve()
    journal_path = project_root / ".standards_sync_tx.json"
    lock_path = project_root / "standards.lock.json"
    manifest_path = project_root / "engineering-manifest.yaml"

    lock_ok, lock_err, lock_fd = acquire_transaction_lock(project_root, "tx-recovery", timeout=1.0)
    if not lock_ok:
        return False, lock_err

    try:
        check = detect_interrupted_transaction(project_root)
        if not check.get("interrupted"):
            return True, None

        if not journal_path.exists():
            msg = f"CORRUPT_TRANSACTION_JOURNAL: Missing .standards_sync_tx.json while backup/tmp files exist: {check.get('backup_files') + check.get('tmp_files')}"
            return False, msg

        if check.get("journal_corrupt"):
            j_err = (check.get("journal") or {}).get("error", "Journal corrupt or invalid")
            return False, f"CORRUPT_TRANSACTION_JOURNAL: {j_err}"

        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"CORRUPT_TRANSACTION_JOURNAL: Failed to parse .standards_sync_tx.json: {exc}"

        if not isinstance(journal, dict):
            return False, "CORRUPT_TRANSACTION_JOURNAL: Journal is not a JSON object"

        required_journal_fields = ["tx_id", "phase", "operation_type", "has_orig_lock", "has_orig_manifest", "status"]
        missing_fields = [f for f in required_journal_fields if f not in journal]
        if missing_fields:
            return False, f"CORRUPT_TRANSACTION_JOURNAL: Missing required fields in journal: {missing_fields}"

        targets = journal.get("targets")
        if not isinstance(targets, dict):
            return False, "CORRUPT_TRANSACTION_JOURNAL: Journal targets must be an object"

        # Validate all targets strictly
        val_targets: Dict[str, Path] = {}
        for tk, tv in targets.items():
            ok, p_tgt, err = _validate_journal_target(project_root, tv)
            if not ok:
                return False, f"CORRUPT_TRANSACTION_JOURNAL: Path traversal detected in journal target '{tk}': {err}"
            val_targets[tk] = p_tgt

        lock_bak = val_targets.get("lock_bak", project_root / "standards.lock.json.bak")
        manifest_bak = val_targets.get("manifest_bak", project_root / "engineering-manifest.yaml.bak")
        lock_tmp = val_targets.get("lock_tmp", project_root / "standards.lock.json.tmp")
        manifest_tmp = val_targets.get("manifest_tmp", project_root / "engineering-manifest.yaml.tmp")

        # Distinction: COMMITTED Cleanup vs Uncommitted Rollback
        is_committed = journal.get("phase") == "COMMITTED" or journal.get("status") == "CLEANUP_PENDING"

        if is_committed:
            cleanup_errors = []
            files_to_clean = [lock_tmp, manifest_tmp, lock_bak, manifest_bak]
            for p in files_to_clean:
                if p.exists():
                    try:
                        p.unlink()
                    except Exception as exc:
                        cleanup_errors.append(f"Failed to delete {p.name}: {exc}")

            if cleanup_errors:
                journal["status"] = "CLEANUP_PENDING"
                journal["cleanup_errors"] = cleanup_errors
                try:
                    journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return False, f"CLEANUP_FAILED: Failed to delete committed backup/tmp files: {cleanup_errors}"

            try:
                journal_path.unlink()
            except Exception as exc:
                journal["status"] = "CLEANUP_PENDING"
                journal["cleanup_errors"] = [f"Failed to delete journal: {exc}"]
                try:
                    journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return False, f"CLEANUP_FAILED: Failed to delete journal: {exc}"

            return True, None

        # Uncommitted Transaction Rollback
        has_orig_lock = bool(journal.get("has_orig_lock"))
        has_orig_manifest = bool(journal.get("has_orig_manifest"))
        orig_lock_sha = journal.get("orig_lock_sha256")
        orig_man_sha = journal.get("orig_manifest_sha256")
        backup_lock_sha = journal.get("backup_lock_sha256")
        backup_man_sha = journal.get("backup_manifest_sha256")

        if has_orig_lock:
            if not lock_bak.exists():
                return False, "MISSING_REQUIRED_BACKUP: standards.lock.json.bak is missing but has_orig_lock is True"
            actual_lock_bak_sha = compute_file_sha256(lock_bak)
            expected_lock_sha = orig_lock_sha or backup_lock_sha
            if actual_lock_bak_sha != expected_lock_sha:
                return False, f"BACKUP_SHA256_MISMATCH: standards.lock.json.bak sha256 ({actual_lock_bak_sha}) != recorded ({expected_lock_sha})"
        else:
            if lock_bak.exists():
                return False, "UNATTRIBUTED_FILE_STATE: standards.lock.json.bak exists when journal recorded has_orig_lock=False"

        if has_orig_manifest:
            if not manifest_bak.exists():
                return False, "MISSING_REQUIRED_BACKUP: engineering-manifest.yaml.bak is missing but has_orig_manifest is True"
            actual_man_bak_sha = compute_file_sha256(manifest_bak)
            expected_man_sha = orig_man_sha or backup_man_sha
            if actual_man_bak_sha != expected_man_sha:
                return False, f"BACKUP_SHA256_MISMATCH: engineering-manifest.yaml.bak sha256 ({actual_man_bak_sha}) != recorded ({expected_man_sha})"
        else:
            if manifest_bak.exists():
                return False, "UNATTRIBUTED_FILE_STATE: engineering-manifest.yaml.bak exists when journal recorded has_orig_manifest=False"

        try:
            journal["phase"] = "RECOVERY_IN_PROGRESS"
            journal["status"] = "RECOVERING"
            journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        recovery_errors: List[str] = []

        if has_orig_lock:
            try:
                actual_restore(lock_bak, lock_path)
            except Exception as exc:
                recovery_errors.append(f"Failed to restore standards.lock.json from {lock_bak.name}: {exc}")
        else:
            if journal.get("created_new_lock", True) and lock_path.exists():
                try:
                    lock_path.unlink()
                except Exception as exc:
                    recovery_errors.append(f"Failed to remove newly created standards.lock.json: {exc}")

        if has_orig_manifest:
            try:
                actual_restore(manifest_bak, manifest_path)
            except Exception as exc:
                recovery_errors.append(f"Failed to restore engineering-manifest.yaml from {manifest_bak.name}: {exc}")
        else:
            if journal.get("created_new_manifest", True) and manifest_path.exists():
                try:
                    manifest_path.unlink()
                except Exception as exc:
                    recovery_errors.append(f"Failed to remove newly created engineering-manifest.yaml: {exc}")

        if recovery_errors:
            try:
                journal["phase"] = "RECOVERY_FAILED"
                journal["status"] = "RECOVERY_FAILED"
                journal["recovery_errors"] = recovery_errors
                journal_path.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            preserved = [p.name for p in (lock_bak, manifest_bak) if p.exists()]
            return False, f"RECOVERY_FAILED: {recovery_errors}; preserved backup files {preserved}"

        # Post-recovery verification
        if has_orig_lock:
            if not lock_path.exists():
                return False, "POST_RECOVERY_VERIFICATION_FAILED: standards.lock.json missing after restoration"
            cur_lock_sha = compute_file_sha256(lock_path)
            if cur_lock_sha != orig_lock_sha:
                return False, f"POST_RECOVERY_VERIFICATION_FAILED: standards.lock.json SHA256 ({cur_lock_sha}) != original snapshot ({orig_lock_sha})"
        else:
            if lock_path.exists():
                return False, "POST_RECOVERY_VERIFICATION_FAILED: standards.lock.json should not exist after initialization recovery"

        if has_orig_manifest:
            if not manifest_path.exists():
                return False, "POST_RECOVERY_VERIFICATION_FAILED: engineering-manifest.yaml missing after restoration"
            cur_man_sha = compute_file_sha256(manifest_path)
            if cur_man_sha != orig_man_sha:
                return False, f"POST_RECOVERY_VERIFICATION_FAILED: engineering-manifest.yaml SHA256 ({cur_man_sha}) != original snapshot ({orig_man_sha})"
        else:
            if manifest_path.exists():
                return False, "POST_RECOVERY_VERIFICATION_FAILED: engineering-manifest.yaml should not exist after initialization recovery"

        if has_orig_lock and has_orig_manifest and lock_path.exists() and manifest_path.exists():
            try:
                rec_lock = json.loads(lock_path.read_text(encoding="utf-8"))
                rec_man = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                m_std = rec_man.get("standards") or {}
                m_ver = str(m_std.get("version") or m_std.get("standard_version") or "").lstrip("v")
                m_tag = str(m_std.get("tag") or m_std.get("release_tag") or "")
                m_commit = str(m_std.get("peeled_commit") or m_std.get("standard_commit") or "")
                if (
                    rec_lock.get("version") != m_ver
                    or rec_lock.get("tag") != m_tag
                    or rec_lock.get("peeled_commit") != m_commit
                ):
                    return False, "POST_RECOVERY_VERIFICATION_FAILED: Recovered standards.lock.json and engineering-manifest.yaml have inconsistent version/tag/commit"
            except Exception as exc:
                return False, f"POST_RECOVERY_VERIFICATION_FAILED: Failed to parse restored files: {exc}"

        for p in (lock_bak, manifest_bak, lock_tmp, manifest_tmp, journal_path):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

        return True, None

    finally:
        release_transaction_lock(project_root, lock_fd)


def execute_transactional_two_file_update(
    project_root: Path,
    new_lock: Dict[str, Any],
    new_manifest_standards: Optional[Dict[str, Any]] = None,
    replace_fn: Optional[Callable[[Path, Path], None]] = None,
    is_initialization: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Coordinated two-file update for standards.lock.json and engineering-manifest.yaml."""
    actual_replace = replace_fn if replace_fn is not None else os.replace
    project_root = project_root.resolve()
    lock_path = project_root / "standards.lock.json"
    manifest_path = project_root / "engineering-manifest.yaml"
    journal_path = project_root / ".standards_sync_tx.json"

    tx_id = f"tx-{uuid.uuid4()}"
    lock_ok, lock_err, lock_fd = acquire_transaction_lock(project_root, tx_id, timeout=0.5)
    if not lock_ok:
        return False, lock_err

    try:
        prior_tx = detect_interrupted_transaction(project_root)
        if prior_tx.get("interrupted"):
            rec_ok, rec_err = recover_interrupted_transaction(project_root)
            if not rec_ok:
                return False, f"PREEXISTING_INTERRUPTED_TRANSACTION_RECOVERY_FAILED: {rec_err}"

        if not manifest_path.exists():
            if not is_initialization:
                return False, "MISSING_MANIFEST: engineering-manifest.yaml does not exist; cannot perform transactional update without manifest"

        if new_manifest_standards is None and not is_initialization:
            return False, "MISSING_MANIFEST_STANDARDS_UPDATE: new_manifest_standards is required for two-file update"

        orig_manifest_content: Optional[str] = None
        orig_manifest_bytes: Optional[bytes] = None
        manifest_data: Dict[str, Any] = {}
        if manifest_path.exists():
            try:
                orig_manifest_bytes = manifest_path.read_bytes()
                orig_manifest_content = orig_manifest_bytes.decode("utf-8")
                manifest_data = yaml.safe_load(orig_manifest_content) or {}
            except Exception as exc:
                return False, f"INVALID_MANIFEST_YAML: failed to parse engineering-manifest.yaml: {exc}"

            if not isinstance(manifest_data, dict):
                return False, "INVALID_MANIFEST_STRUCTURE: engineering-manifest.yaml is not a YAML dictionary"

            if "standards" not in manifest_data or not isinstance(manifest_data.get("standards"), dict):
                return False, "INVALID_MANIFEST_STANDARDS: engineering-manifest.yaml missing valid 'standards' mapping"
        elif is_initialization:
            manifest_data = {"schema_version": "1.3.0", "standards": {}}

        orig_lock_content: Optional[str] = None
        orig_lock_bytes: Optional[bytes] = None
        if lock_path.exists():
            try:
                orig_lock_bytes = lock_path.read_bytes()
                orig_lock_content = orig_lock_bytes.decode("utf-8")
            except Exception as exc:
                return False, f"INVALID_LOCK_FILE: {exc}"

        orig_lock_sha = hashlib.sha256(orig_lock_bytes).hexdigest() if orig_lock_bytes is not None else None
        orig_man_sha = hashlib.sha256(orig_manifest_bytes).hexdigest() if orig_manifest_bytes is not None else None

        lock_tmp = project_root / f"standards.lock.json.{tx_id}.tmp"
        lock_bak = project_root / "standards.lock.json.bak"
        manifest_tmp = project_root / f"engineering-manifest.yaml.{tx_id}.tmp"
        manifest_bak = project_root / "engineering-manifest.yaml.bak"

        try:
            backup_lock_sha: Optional[str] = None
            backup_man_sha: Optional[str] = None
            if orig_lock_bytes is not None:
                lock_bak.write_bytes(orig_lock_bytes)
                backup_lock_sha = compute_file_sha256(lock_bak)
            if orig_manifest_bytes is not None:
                manifest_bak.write_bytes(orig_manifest_bytes)
                backup_man_sha = compute_file_sha256(manifest_bak)

            tx_journal_data = {
                "tx_id": tx_id,
                "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "phase": "PREPARED",
                "operation_type": "INITIALIZATION" if is_initialization else "UPDATE",
                "status": "IN_PROGRESS",
                "has_orig_lock": orig_lock_content is not None,
                "has_orig_manifest": orig_manifest_content is not None,
                "orig_lock_sha256": orig_lock_sha,
                "orig_manifest_sha256": orig_man_sha,
                "backup_lock_sha256": backup_lock_sha,
                "backup_manifest_sha256": backup_man_sha,
                "created_new_lock": (orig_lock_content is None),
                "created_new_manifest": (orig_manifest_content is None),
                "targets": {
                    "lock_path": "standards.lock.json",
                    "manifest_path": "engineering-manifest.yaml",
                    "lock_tmp": lock_tmp.name,
                    "manifest_tmp": manifest_tmp.name,
                    "lock_bak": lock_bak.name,
                    "manifest_bak": manifest_bak.name,
                },
            }
            journal_path.write_text(json.dumps(tx_journal_data, indent=2, ensure_ascii=False), encoding="utf-8")

            lock_tmp.write_text(json.dumps(new_lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if new_manifest_standards is not None:
                manifest_data.setdefault("standards", {})
                manifest_data["standards"].update(new_manifest_standards)
                manifest_tmp.write_text(
                    yaml.safe_dump(manifest_data, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )
            tx_journal_data["phase"] = "STAGED"
            journal_path.write_text(json.dumps(tx_journal_data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            for p in (lock_tmp, lock_bak, manifest_tmp, manifest_bak, journal_path):
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            return False, f"FAILED_STAGING_TRANSACTION: {exc}"

        try:
            actual_replace(lock_tmp, lock_path)
            tx_journal_data["phase"] = "LOCK_REPLACED"
            journal_path.write_text(json.dumps(tx_journal_data, indent=2, ensure_ascii=False), encoding="utf-8")

            if manifest_tmp.exists():
                actual_replace(manifest_tmp, manifest_path)
                tx_journal_data["phase"] = "MANIFEST_REPLACED"
                journal_path.write_text(json.dumps(tx_journal_data, indent=2, ensure_ascii=False), encoding="utf-8")

            disk_lock = json.loads(lock_path.read_text(encoding="utf-8"))
            disk_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            m_std = disk_manifest.get("standards") or {}
            m_ver = str(m_std.get("version") or m_std.get("standard_version") or "").lstrip("v")
            m_tag = str(m_std.get("tag") or m_std.get("release_tag") or "")
            m_commit = str(m_std.get("peeled_commit") or m_std.get("standard_commit") or "")
            if (
                disk_lock.get("version") != m_ver
                or disk_lock.get("tag") != m_tag
                or disk_lock.get("peeled_commit") != m_commit
            ):
                raise ValueError("POST_REPLACE_INCONSISTENCY: disk manifest standards block does not match lock")

            # Mark COMMITTED phase explicitly
            tx_journal_data["phase"] = "COMMITTED"
            tx_journal_data["status"] = "COMMITTED"
            tx_journal_data["committed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            journal_path.write_text(json.dumps(tx_journal_data, indent=2, ensure_ascii=False), encoding="utf-8")

        except Exception as exc:
            rec_ok, rec_err = recover_interrupted_transaction(project_root)
            if not rec_ok:
                return False, f"TRANSACTION_FAILED: {exc}. RECOVERY_FAILED: {rec_err}"
            return False, f"TRANSACTION_FAILED: {exc}. State successfully rolled back to pre-transaction snapshot; consistency verified."

        # Post-COMMITTED cleanup
        cleanup_errors: List[str] = []
        for p in (lock_tmp, manifest_tmp, lock_bak, manifest_bak):
            if p.exists():
                try:
                    p.unlink()
                except Exception as del_err:
                    cleanup_errors.append(f"Failed to delete {p.name}: {del_err}")

        if cleanup_errors:
            tx_journal_data["status"] = "CLEANUP_PENDING"
            tx_journal_data["cleanup_errors"] = cleanup_errors
            try:
                journal_path.write_text(json.dumps(tx_journal_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return False, f"TRANSACTION_CLEANUP_PENDING: Both files committed, but cleanup failed: {cleanup_errors}. Preserved journal and evidence."

        try:
            journal_path.unlink()
        except Exception as j_err:
            tx_journal_data["status"] = "CLEANUP_PENDING"
            tx_journal_data["cleanup_errors"] = [f"Failed to delete journal: {j_err}"]
            try:
                journal_path.write_text(json.dumps(tx_journal_data, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return False, f"TRANSACTION_CLEANUP_PENDING: Both files committed, but journal deletion failed: {j_err}. Preserved journal."

        return True, None

    finally:
        release_transaction_lock(project_root, lock_fd)
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
    replace_fn: Optional[Callable[[Path, Path], None]] = None,
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
    compat = validate_upgrade_candidate(project_root=project_root, standards_root=std_root, target_tag=target_tag)
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
    manifest_standards = {
        "repository": DEFAULT_OFFICIAL_REPO,
        "version": target_version.lstrip("v"),
        "tag": target_tag,
        "tag_object_sha": target_tag_object_sha,
        "peeled_commit": target_peeled_commit,
    }
    tx_ok, tx_err = execute_transactional_two_file_update(
        project_root=project_root,
        new_lock=new_lock,
        new_manifest_standards=manifest_standards,
        replace_fn=replace_fn,
    )
    if not tx_ok:
        return {
            "status": "UPGRADE_BLOCKED",
            "reason": tx_err,
        }

    return {
        "status": "PROMOTED",
        "lock": new_lock,
    }


def rollback_lock(
    project_root: Path,
    replace_fn: Optional[Callable[[Path, Path], None]] = None,
) -> Dict[str, Any]:
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

    # Transactional update to standards.lock.json and engineering-manifest.yaml
    manifest_standards = {
        "repository": restored["repository"],
        "version": restored["version"],
        "tag": restored["tag"],
        "tag_object_sha": restored["tag_object_sha"],
        "peeled_commit": restored["peeled_commit"],
    }
    tx_ok, tx_err = execute_transactional_two_file_update(
        project_root=project_root,
        new_lock=rolled_back_lock,
        new_manifest_standards=manifest_standards,
        replace_fn=replace_fn,
    )
    if not tx_ok:
        return {
            "status": "FAIL",
            "reason": tx_err,
        }

    return {
        "status": "ROLLED_BACK",
        "lock": rolled_back_lock,
    }
