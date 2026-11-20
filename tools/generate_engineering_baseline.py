#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic Generator & Validator for STD-035 ENGINEERING_BASELINE (docs/当前权威基线.md)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple
import jsonschema
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.validate_approval_contract import (
    compute_canonical_document_sha256,
    compute_markdown_body_sha256,
)
from tools.release_evidence import (
    _query_pr_via_api,
    _query_pr_via_gh,
    load_release_evidence,
    resolve_release_evidence_path,
    verify_candidate_pr_merge_event,
    verify_candidate_pr_section,
    verify_commit_ancestry,
    verify_live_pr_identity,
)

REQUIRED_SOURCE_TYPES: Tuple[str, ...] = (
    "PROJECT_BLUEPRINT",
    "PRODUCT_BASELINE",
    "SYSTEM_ARCHITECTURE",
    "TECHNICAL_DESIGN",
    "API_CONTRACT",
    "DECISION_RECORD",
    "PROTOTYPE_UX",
    "TEST_ACCEPTANCE",
    "RELEASE_OPERATIONS",
    "DOCUMENT_INDEX",
    "CROSS_SESSION_HANDOFF",
)

VALID_VERIFICATION_STATUSES = {
    "PASS",
    "FAIL",
    "BLOCK",
    "NOT_RUN",
    "NOT_VERIFIABLE",
    "STALE",
}


def resolve_standards_root(explicit_root: Optional[str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    env_root = os.environ.get("AI_ENGINEERING_STANDARDS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


def extract_frontmatter_and_body(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    normalized = content.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None, normalized
    parts = normalized.split("---\n", 2)
    if len(parts) < 3:
        return None, normalized
    try:
        fm = yaml.safe_load(parts[1])
        return (fm if isinstance(fm, dict) else None), parts[2]
    except Exception:
        return None, normalized


def extract_bullet_items(body: str, max_items: int = 8) -> List[str]:
    items: List[str] = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")) and len(s) > 4:
            cleaned = re.sub(r"^[-*]\s+(\[[xX ]\]\s+)?", "", s).strip()
            if cleaned and not cleaned.startswith("<!--"):
                items.append(cleaned)
                if len(items) >= max_items:
                    break
    return items


def extract_adrs_from_decision_record(body: str, source_ref: str) -> List[Dict[str, Any]]:
    adrs: List[Dict[str, Any]] = []
    lines = body.splitlines()
    in_table = False
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            continue
        cols = [c.strip() for c in s.split("|")[1:-1]]
        if len(cols) < 4:
            continue
        if "决策编号" in cols[0] or "---" in cols[0]:
            in_table = True
            continue
        if in_table:
            raw_id = cols[0]
            m_id = re.search(r"D\d+", raw_id)
            if not m_id:
                continue
            dec_id = m_id.group(0)
            title = re.sub(r"[`*]", "", cols[1]).strip()
            status_match = re.search(r"(OWNER_APPROVED|AI_APPROVED)", cols[3])
            if status_match:
                approval_st = status_match.group(1)
            else:
                continue
            adrs.append({
                "decision_id": dec_id,
                "title": title,
                "approval_status": approval_st,
                "source_ref": source_ref,
            })
    return adrs


def compute_deterministic_baseline_sha256(payload: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 of baseline payload excluding time fields (observed_at, verified_at)."""
    def strip_time_fields(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: strip_time_fields(v)
                for k, v in sorted(obj.items())
                if k not in (
                    "observed_at",
                    "verified_at",
                    "content_sha256",
                    "git_snapshot_observed_at",
                    "observed_time",
                    "snapshot_observed_at",
                )
            }
        if isinstance(obj, list):
            return [strip_time_fields(x) for x in obj]
        return obj

    canonical_bytes = json.dumps(
        strip_time_fields(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical_bytes).hexdigest()


def run_git(project_root: Path, args: List[str], timeout: int = 5) -> Tuple[int, str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(project_root)] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return res.returncode, (res.stdout or "").strip()
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT: {e}"
    except Exception as e:
        return 128, f"GIT_EXECUTION_NOT_VERIFIABLE: {e}"


def query_remote_main_head(project_root: Path, timeout: int = 8) -> str:
    """Live query remote origin refs/heads/main. Never fallback to local cached refs/remotes/origin/main."""
    try:
        res = subprocess.run(
            ["git", "-C", str(project_root), "ls-remote", "origin", "refs/heads/main"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if res.returncode == 0 and res.stdout:
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "refs/heads/main":
                    sha = parts[0].strip()
                    if len(sha) == 40 and re.match(r"^[0-9a-f]{40}$", sha):
                        return sha
        return "NOT_VERIFIABLE"
    except Exception:
        return "NOT_VERIFIABLE"


def extract_scope_content(content: str, scope_tag: str) -> Tuple[str, List[str]]:
    """Extract content under markdown headings corresponding to scope_tag.
    Enforces scope uniqueness:
      - Exactly 1 scope heading containing scope_tag must be present.
      - 0 matches -> SCOPE_SECTION_MISSING error.
      - >1 matches -> DUPLICATE_SCOPE_SECTION error.
    """
    lines = content.splitlines()
    matches = []
    for idx, line in enumerate(lines):
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m and scope_tag in m.group(2):
            matches.append((idx, len(m.group(1)), line))

    if len(matches) == 0:
        return "", [f"SCOPE_SECTION_MISSING: Scope section '{scope_tag}' not found in baseline document"]
    if len(matches) > 1:
        return "", [f"DUPLICATE_SCOPE_SECTION: Duplicate scope section '{scope_tag}' found in baseline document ({len(matches)} occurrences)"]

    start_idx, start_lvl, _ = matches[0]
    scoped_lines: List[str] = []
    for i in range(start_idx, len(lines)):
        m = re.match(r'^(#{1,6})\s+(.*)$', lines[i])
        if m and i > start_idx and len(m.group(1)) <= start_lvl:
            break
        scoped_lines.append(lines[i])

    return "\n".join(scoped_lines), []



def resolve_snapshot_branch_name(project_root: Path) -> str:
    rc, branch = run_git(project_root, ["branch", "--show-current"])
    if rc == 0 and branch and branch != "HEAD":
        return branch
    for key in ("GITHUB_HEAD_REF", "GITHUB_REF_NAME"):
        value = os.environ.get(key, "").strip()
        if value and value != "HEAD":
            return value
    ref = os.environ.get("GITHUB_REF", "").strip()
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/"):]
    return "HEAD"


def resolve_snapshot_branch_tip(project_root: Path) -> str:
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if event_path and Path(event_path).is_file():
        try:
            event_data = json.loads(Path(event_path).read_text(encoding="utf-8"))
            pull_request = event_data.get("pull_request")
            if isinstance(pull_request, dict):
                head_data = pull_request.get("head")
                head_sha = head_data.get("sha") if isinstance(head_data, dict) else None
                if isinstance(head_sha, str) and re.fullmatch(r"[0-9a-f]{40}", head_sha):
                    rc_exists, _ = run_git(project_root, ["cat-file", "-e", f"{head_sha}^{{commit}}"])
                    if rc_exists == 0:
                        return head_sha
        except Exception:
            pass
    github_sha = os.environ.get("GITHUB_SHA", "").strip()
    if re.fullmatch(r"[0-9a-f]{40}", github_sha):
        rc_exists, _ = run_git(project_root, ["cat-file", "-e", f"{github_sha}^{{commit}}"])
        if rc_exists == 0:
            return github_sha
    rc, head = run_git(project_root, ["rev-parse", "HEAD"])
    return head if rc == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else ""


def verify_git_snapshot_facts(
    project_root: Path,
    content: str,
    document_kind: str,
) -> List[str]:
    """Verify recorded Git facts against the exact branch history at captured_at.

    local_head is a time-bound snapshot. It must equal the latest commit on the
    current PR/push branch whose committer date is not later than captured_at.
    """
    errors: List[str] = []
    if document_kind == "baseline":
        manifest_path = project_root / "engineering-manifest.yaml"
        project_id = ""
        if manifest_path.is_file():
            try:
                manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                project_id = str((manifest_data.get("project") or {}).get("id") or "")
            except Exception:
                project_id = ""

        identity_match = re.search(
            r"## 8\. Git 分支及 Commit 身份.*?(?=\n## 9\.)",
            content,
            re.S,
        )
        if not identity_match:
            return ["BASELINE_GIT_SNAPSHOT_SECTION_MISSING: Git identity section not found"]
        identity_text = identity_match.group(0)

        if project_id == "ai-engineering-standards":
            sec9_match = re.search(
                r"## 9\. 最近 CI 事实.*?(?=\n### |\n## 10\.|\Z)",
                content,
                re.S,
            )
            sec9_head = sec9_match.group(0) if sec9_match else ""
            scope_text = sec9_head
            captured_matches = re.findall(
                r"Git 快照观测时间.*?\x60(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\x60",
                sec9_head,
            )
            if not captured_matches:
                scope_text, scope_errors = extract_scope_content(
                    content, "Std-019 正式发布收口事实与治理追踪"
                )
                if scope_errors:
                    return [f"BASELINE_GIT_SNAPSHOT_CAPTURE_SCOPE_INVALID: {e}" for e in scope_errors]
                captured_matches = re.findall(
                    r"Git 快照观测时间.*?\x60(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\x60",
                    scope_text,
                )
            remote_pattern = r"远端 main \(\x60remote_main_head\x60\)\*\*：\x60([0-9a-f]{40})\x60"
        else:
            scope_text = ""
            captured_matches = re.findall(
                r"Git 快照观测时间.*?\x60(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\x60",
                content,
            ) or re.findall(
                r"## 17\. 核验时间 \(\x60verified_at\x60\)\n- \x60(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\x60",
                content,
            )
            remote_pattern = r"远端 main \(\x60remote_main_head\x60\)\*\*：\x60([0-9a-f]{40}|NOT_VERIFIABLE)\x60"
        prefix = "BASELINE"
    elif document_kind == "handoff":
        identity_text = content.split("## 2. 当前 Standards 锁定", 1)[0]
        captured_matches = re.findall(
            r"^CAPTURED_AT=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)$",
            identity_text,
            re.M,
        )
        remote_pattern = r"远端 main \(\x60remote_head\x60\)\*\*：\x60([0-9a-f]{40})\x60"
        prefix = "HANDOFF"
    else:
        return [f"GIT_SNAPSHOT_UNSUPPORTED_DOCUMENT_KIND: {document_kind}"]

    def one(pattern: str, label: str) -> Optional[str]:
        matches = re.findall(pattern, identity_text)
        if len(matches) != 1:
            errors.append(
                f"{prefix}_GIT_SNAPSHOT_FIELD_CARDINALITY: {label} expected exactly one value, found {len(matches)}"
            )
            return None
        return matches[0]

    recorded_branch = one(
        r"当前分支 \(\x60branch\x60\)\*\*：\x60([^\x60]+)\x60",
        "branch",
    )
    recorded_local_head = one(
        r"本地 HEAD \(\x60local_head\x60\)\*\*：\x60([0-9a-f]{40})\x60",
        "local_head",
    )
    recorded_remote_head = one(remote_pattern, "remote_main_head")
    recorded_worktree_clean = one(
        r"工作区干净状态 \(\x60worktree_clean\x60\)\*\*：\x60(true|false)\x60",
        "worktree_clean",
    )

    if len(captured_matches) != 1:
        errors.append(
            f"{prefix}_GIT_SNAPSHOT_CAPTURE_TIME_CARDINALITY: expected exactly one capture timestamp, found {len(captured_matches)}"
        )
        captured_at = None
    else:
        captured_at = captured_matches[0]

    is_historical = False
    if document_kind == "baseline":
        if "RELEASE_STATUS=RELEASED" in scope_text or "PR10=MERGED" in scope_text:
            is_historical = True
    elif document_kind == "handoff":
        if re.search(r"^STATUS=COMPLETED$", identity_text, re.M):
            is_historical = True

    if recorded_worktree_clean not in ("true", "false"):
        errors.append(f"{prefix}_GIT_SNAPSHOT_WORKTREE_STATE_INVALID: expected true/false")

    remote_main_head = query_remote_main_head(project_root)
    if remote_main_head == "NOT_VERIFIABLE":
        errors.append(f"{prefix}_GIT_SNAPSHOT_REMOTE_MAIN_NOT_VERIFIABLE: origin/main could not be queried")

    branch_tip = resolve_snapshot_branch_tip(project_root)
    if not branch_tip:
        errors.append(f"{prefix}_GIT_SNAPSHOT_BRANCH_TIP_NOT_VERIFIABLE: current branch tip unavailable")

    expected_branch = resolve_snapshot_branch_name(project_root)
    # A historical marker alone cannot exempt an old snapshot from freshness checks.
    # The recorded local_head must be present in the current branch or official main history.
    is_ancestor = bool(recorded_local_head and branch_tip and recorded_local_head == branch_tip)
    ancestry_unverifiable = False
    ancestry_details: List[str] = []

    if recorded_local_head and branch_tip and not is_ancestor:
        rc_anc, anc_err = run_git(
            project_root,
            ["merge-base", "--is-ancestor", recorded_local_head, branch_tip],
            timeout=8,
        )
        if rc_anc == 0:
            is_ancestor = True
        elif rc_anc not in (1,):
            ancestry_unverifiable = True
            ancestry_details.append(f"current branch ancestry exit_code={rc_anc}: {anc_err}")

    if not is_ancestor and recorded_local_head and remote_main_head != "NOT_VERIFIABLE":
        if recorded_local_head == remote_main_head:
            is_ancestor = True
        else:
            rc_anc_remote, remote_anc_err = run_git(
                project_root,
                ["merge-base", "--is-ancestor", recorded_local_head, remote_main_head],
                timeout=8,
            )
            if rc_anc_remote == 0:
                is_ancestor = True
            elif rc_anc_remote not in (1,):
                ancestry_unverifiable = True
                ancestry_details.append(f"official main ancestry exit_code={rc_anc_remote}: {remote_anc_err}")

    historical_snapshot_verified = is_historical and is_ancestor
    if is_historical and not is_ancestor:
        if ancestry_unverifiable or not recorded_local_head or not branch_tip or remote_main_head == "NOT_VERIFIABLE":
            detail = "; ".join(ancestry_details) or "required Git history/object data is unavailable"
            errors.append(
                f"{prefix}_GIT_SNAPSHOT_HISTORICAL_ANCESTRY_NOT_VERIFIABLE: cannot prove historical local_head ancestry ({detail})"
            )
        else:
            errors.append(
                f"{prefix}_GIT_SNAPSHOT_HISTORICAL_ANCESTRY_MISMATCH: recorded local_head '{recorded_local_head}' is not an ancestor of the current branch or official main"
            )

    if (
        recorded_branch is not None
        and expected_branch not in ("HEAD", "main")
        and recorded_branch != expected_branch
        and not historical_snapshot_verified
    ):
        errors.append(
            f"{prefix}_GIT_SNAPSHOT_BRANCH_MISMATCH: recorded '{recorded_branch}', live branch '{expected_branch}'"
        )

    if captured_at:
        try:
            captured_dt = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            if captured_dt.tzinfo is None:
                raise ValueError("timezone missing")
            age_seconds = (datetime.now(timezone.utc) - captured_dt).total_seconds()
            if age_seconds < -300:
                errors.append(
                    f"{prefix}_GIT_SNAPSHOT_STALE: captured_at '{captured_at}' is in the future"
                )
            elif not historical_snapshot_verified and age_seconds > 24 * 60 * 60:
                errors.append(
                    f"{prefix}_GIT_SNAPSHOT_STALE: captured_at '{captured_at}' is outside the 24-hour validity window"
                )
        except Exception as exc:
            errors.append(f"{prefix}_GIT_SNAPSHOT_CAPTURE_TIME_INVALID: {exc}")

        if branch_tip:
            rc, expected_capture_head = run_git(
                project_root,
                ["log", "-1", "--format=%H", f"--before={captured_at}", branch_tip],
                timeout=8,
            )
            if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}", expected_capture_head):
                errors.append(
                    f"{prefix}_GIT_SNAPSHOT_CAPTURE_COMMIT_NOT_VERIFIABLE: could not resolve branch history at '{captured_at}'"
                )
            elif recorded_local_head is not None and recorded_local_head != expected_capture_head:
                errors.append(
                    f"{prefix}_GIT_SNAPSHOT_LOCAL_HEAD_MISMATCH: recorded '{recorded_local_head}', expected '{expected_capture_head}' from branch history at '{captured_at}'"
                )

        # origin/main may advance after the snapshot (for example, when this PR merges).
        # Follow first-parent mainline history so PR branch commits are never misattributed to origin/main.
        if remote_main_head != "NOT_VERIFIABLE" and captured_at:
            rc, expected_remote_at_capture = run_git(
                project_root,
                ["log", "-1", "--first-parent", "--format=%H", f"--before={captured_at}", remote_main_head],
                timeout=8,
            )
            if rc != 0 or not re.fullmatch(r"[0-9a-f]{40}", expected_remote_at_capture):
                errors.append(
                    f"{prefix}_GIT_SNAPSHOT_REMOTE_MAIN_AT_CAPTURE_NOT_VERIFIABLE: could not resolve origin/main at '{captured_at}'"
                )
            elif recorded_remote_head is not None and recorded_remote_head != expected_remote_at_capture:
                errors.append(
                    f"{prefix}_GIT_SNAPSHOT_REMOTE_MAIN_MISMATCH: recorded '{recorded_remote_head}', origin/main at capture '{expected_remote_at_capture}'"
                )

    return errors


def extract_line_field_matches(target_text: str, patterns: List[str]) -> List[str]:
    matches: List[str] = []
    seen_capture_spans: set[Tuple[int, int, int]] = set()
    for line_index, raw_line in enumerate(target_text.splitlines()):
        line = raw_line.strip()
        if not (line.startswith("- **") or line.startswith("**") or line.startswith("- PR9_") or line.startswith("PR9_") or line.startswith("- ")):
            continue
        for pat in patterns:
            for match in re.finditer(pat, line):
                start, end = match.span(1)
                capture_key = (line_index, start, end)
                if capture_key in seen_capture_spans:
                    continue
                seen_capture_spans.add(capture_key)
                matches.append(match.group(1))
    return matches

def verify_scoped_field(
    target_text: str,
    field_name: str,
    patterns: List[str],
    expected_val: Any,
    scope_name: str,
) -> List[str]:
    matches = extract_line_field_matches(target_text, patterns)
    if len(matches) == 0:
        return [f"MISSING_FIELD: {field_name} missing from scope '{scope_name}' (expected '{expected_val}')"]
    if len(matches) > 1:
        distinct = sorted(list(set(matches)))
        if len(distinct) > 1:
            return [f"DUPLICATE_FIELD: {field_name} has conflicting values {distinct} in scope '{scope_name}'"]
        return [f"DUPLICATE_FIELD: {field_name} appears multiple times ({len(matches)} occurrences) in scope '{scope_name}'"]
    actual = matches[0]
    if field_name == "old_tag_deleted":
        if actual.lower() != str(expected_val).lower():
            return [f"{field_name} committed='{actual}' != expected='{expected_val}' in scope '{scope_name}'"]
    else:
        if str(actual).strip() != str(expected_val).strip():
            return [f"{field_name} committed='{actual}' != expected='{expected_val}' in scope '{scope_name}'"]
    return []


def verify_baseline_semantic_facts(
    content: str,
    expected_facts: Dict[str, Any],
    scope: Optional[str] = None,
) -> List[str]:
    """Verify semantic facts inside committed docs/当前权威基线.md body.
    When scope is provided, enforces:
      1. Scope section uniqueness (exactly 1 canonical section, no duplicates, no missing).
      2. Field uniqueness (exactly 1 occurrence per required field, duplicate fields or conflicts FAIL).
      3. Semantic fact value equality against independent release evidence.
    """
    if scope:
        target_text, scope_errs = extract_scope_content(content, scope)
        if scope_errs:
            return scope_errs

        field_rules: Dict[str, List[str]] = {
            "task_id": [r'(?:task_id|任务编号)[^:：\n]*?[:：]\s*`([A-Za-z0-9_-]+)`'],
            "candidate_commit": [r'(?:candidate_commit|代码候选 Commit|当前工程候选 Commit|当前候选 Commit|发布候选 Commit)[^:：\n]*?[:：]\s*`([0-9a-f]{40})`'],
            "snapshot_commit": [r'(?:snapshot_commit|文档快照 Commit|本地 HEAD)[^:：\n]*?[:：]\s*`([0-9a-f]{40})`'],
            "last_verified_ci_commit": [r'(?:last_verified_ci_commit|已验证 CI Commit|最新已验证 CI Commit)[^:：\n]*?[:：]\s*`([0-9a-f]{40})`'],
            "push_run_id": [r'Push Run ID[^:：\n]*?[:：]\s*`([0-9]+)`', r'Run ID \(`run_id`\)[^:：\n]*?[:：]\s*`([0-9]+)`', r'Main CI Run ID[^:：\n]*?[:：]\s*`([0-9]+)`'],
            "pr_run_id": [r'PR Run ID[^:：\n]*?[:：]\s*`([0-9]+)`'],
            "ci_status": [r'(?:verification_status|核验状态)[^:：\n]*?[:：]\s*`([A-Z_]+)`'],
            "test_count": [r'(?:测试用例数|通过 / 失败用例数)[^:：\n]*?[:：]\s*`(\d+)\s+tests', r'(?:通过 / 失败用例数)[^:：\n]*?[:：]\s*`(\d+)\s*/', r'测试用例数[^:：\n]*?[:：]\s*`(\d+)`'],
            "pr_number": [r'(?:PR 编号|pr_number|PR 编号与状态)[^:：\n]*?[:：]\s*(?:PR\s*#)?`?(\d+)`?'],
            "pr_status": [r'状态[：:]\s*`([A-Za-z_]+)`', r'pr_status[^:：\n]*?[:：]\s*`([A-Za-z_]+)`', r'PR 状态[^:：\n]*?[:：]\s*`([A-Za-z_]+)`'],
            "main_head": [r'(?:main_head|主干 HEAD|发布时 main HEAD)[^:：\n]*?[:：]\s*`([0-9a-f]{40})`'],
            "release_flow_status": [r'发布流程状态[^:：\n]*?[:：]\s*`([A-Za-z_]+)`'],
            "old_tag_deleted": [r'OLD_TAG_DELETED=(true|false)', r'old_tag_deleted[^:：\n]*?[:：]\s*`(true|false)`'],
            "release_tag": [r'(?:release_tag|正式发布 Tag|正式 Tag|发布 Tag)[^:：\n]*?[:：]\s*`([A-Za-z0-9_.-]+)`'],
            "tag_object_sha": [r'(?:tag_object_sha|Tag Object SHA|Tag Object)[^:：\n]*?[:：]\s*`([0-9a-f]{40})`'],
            "peeled_commit": [r'(?:peeled_commit|Peeled Commit|Peeled Commit SHA)[^:：\n]*?[:：]\s*`([0-9a-f]{40})`'],
            "tag_publish_status": [r'(?:tag_publish_status|Tag 发布状态|Tag 发布 Job 状态)[^:：\n]*?[:：]\s*`([A-Z_]+)`'],
            "pr_merged_by": [r'(?:pr_merged_by|合并者|PR 合并者)[^:：\n]*?[:：]\s*`?([A-Za-z0-9_-]+)`?'],
        }

        mismatches: List[str] = []
        field_aliases = {
            "ci_run_id": "push_run_id",
            "ci_commit": "last_verified_ci_commit",
            "main_ci_run_id": "push_run_id",
        }
        for fld, exp_val in expected_facts.items():
            if exp_val is None:
                continue
            canonical_field = field_aliases.get(fld, fld)
            if canonical_field not in field_rules:
                mismatches.append(
                    f"UNSUPPORTED_EXPECTED_FIELD: '{fld}' has no scoped verifier for scope '{scope}'"
                )
                continue
            mismatches.extend(
                verify_scoped_field(target_text, canonical_field, field_rules[canonical_field], exp_val, scope)
            )
        return mismatches

    target_text = content

    mismatches: List[str] = []

    # 1. candidate_commit
    exp_cand = expected_facts.get("candidate_commit")
    if exp_cand:
        m_cand = (
            re.search(r'代码候选 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'当前候选 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'当前工程候选 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'PR9 发布候选 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'candidate_commit.*?`([0-9a-f]{40})`', target_text)
        )
        if not m_cand:
            mismatches.append(f"candidate_commit missing from baseline text (expected '{exp_cand}')")
        elif m_cand.group(1) != exp_cand:
            mismatches.append(f"candidate_commit committed='{m_cand.group(1)}' != expected='{exp_cand}'")

    # 2. snapshot_commit
    exp_snap = expected_facts.get("snapshot_commit")
    if exp_snap:
        m_snap = (
            re.search(r'当前文档快照 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'PR9 文档快照 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'文档快照 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'本地 HEAD \(`local_head`\)\*\*：`([0-9a-f]{40})`', target_text)
            or re.search(r'snapshot_commit.*?`([0-9a-f]{40})`', target_text)
        )
        if not m_snap:
            mismatches.append(f"snapshot_commit missing from baseline text (expected '{exp_snap}')")
        elif m_snap.group(1) != exp_snap:
            mismatches.append(f"snapshot_commit committed='{m_snap.group(1)}' != expected='{exp_snap}'")

    # 3. last_verified_ci_commit
    exp_ci_commit = expected_facts.get("last_verified_ci_commit") or expected_facts.get("ci_commit")
    if exp_ci_commit:
        m_ci = (
            re.search(r'最新已验证 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'PR9 最近一次已验证 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'最近一次已验证 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'最近一次已经验证的 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'last_verified_ci_commit.*?`([0-9a-f]{40})`', target_text)
        )
        if not m_ci:
            mismatches.append(f"last_verified_ci_commit missing from baseline text (expected '{exp_ci_commit}')")
        elif m_ci.group(1) != exp_ci_commit:
            mismatches.append(f"last_verified_ci_commit committed='{m_ci.group(1)}' != expected='{exp_ci_commit}'")

    # 4. CI Run ID / push_run_id
    exp_run_id = expected_facts.get("ci_run_id") or expected_facts.get("push_run_id")
    if exp_run_id:
        str_run_id = str(exp_run_id)
        m_run = (
            re.search(r'Push Run ID\*\*：`([0-9]+)`', target_text)
            or re.search(r'最近一次已经验证的 CI Commit.*?Run\s+(\d+)', target_text)
            or re.search(r'PR CI 已通过 \(Run:\s+(\d+)', target_text)
            or re.search(r'Run\s+(\d+)\s+Push', target_text)
            or re.search(r'Run\s+(\d+)', target_text)
        )
        if m_run and m_run.group(1) != str_run_id:
            mismatches.append(f"ci_run_id committed='{m_run.group(1)}' != expected='{str_run_id}'")
        elif str_run_id not in target_text:
            mismatches.append(f"ci_run_id '{str_run_id}' not found in baseline text")

    # 4b. PR Run ID
    exp_pr_run = expected_facts.get("pr_run_id")
    if exp_pr_run:
        str_pr_run = str(exp_pr_run)
        m_pr_run = (
            re.search(r'PR Run ID\*\*：`([0-9]+)`', target_text)
            or re.search(r'Run\s+(\d+)\s+PR', target_text)
        )
        if not m_pr_run:
            mismatches.append(f"pr_run_id missing from baseline text (expected '{str_pr_run}')")
        elif m_pr_run.group(1) != str_pr_run:
            mismatches.append(f"pr_run_id committed='{m_pr_run.group(1)}' != expected='{str_pr_run}'")

    # 5. CI Commit
    if exp_ci_commit:
        m_ci_com = (
            re.search(r'最新已验证 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'最近一次已经验证的 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'最近一次已验证 CI Commit.*?`([0-9a-f]{40})`', target_text)
        )
        if m_ci_com and m_ci_com.group(1) != exp_ci_commit:
            mismatches.append(f"ci_commit committed='{m_ci_com.group(1)}' != expected='{exp_ci_commit}'")

    # 6. CI verification_status
    exp_st = expected_facts.get("ci_status")
    if exp_st:
        m_st = (
            re.search(r'核验状态 \(`verification_status`\)\*\*：`([A-Z_]+)`', target_text)
            or re.search(
                r'## 9\. 最近 CI 事实[^\n]*\n-\s*\*\*核验状态 \(`verification_status`\)\*\*：`([A-Z_]+)`',
                target_text,
            )
        )
        if not m_st:
            mismatches.append(f"ci verification_status missing from baseline text (expected '{exp_st}')")
        elif m_st.group(1) != exp_st:
            mismatches.append(f"ci verification_status committed='{m_st.group(1)}' != expected='{exp_st}'")

    # 7. TEST_COUNT
    exp_tests = expected_facts.get("test_count") or expected_facts.get("test_passed")
    if exp_tests is not None:
        m_tests = (
            re.search(r'测试用例数\*\*：`(\d+)\s+tests\s+PASS`', target_text)
            or re.search(r'(\d+)\s+tests\s+PASS', target_text)
            or re.search(r'(\d+)\s+tests', target_text)
        )
        if not m_tests:
            mismatches.append(f"test count missing from baseline text (expected {exp_tests})")
        elif int(m_tests.group(1)) != int(exp_tests):
            mismatches.append(f"test count committed={m_tests.group(1)} != expected={exp_tests}")

    # 8. PR 状态
    exp_pr_st = expected_facts.get("pr_status")
    if exp_pr_st:
        m_pr_st = (
            re.search(r'PR #\d+（状态：`([A-Za-z_]+)`）', target_text)
            or re.search(r'PR 状态.*?`([A-Za-z_]+)`', target_text)
            or re.search(r'状态：`([A-Za-z_]+)`', target_text)
        )
        if not m_pr_st and exp_pr_st not in target_text:
            mismatches.append(f"pr_status '{exp_pr_st}' not found in baseline text")
        elif m_pr_st and m_pr_st.group(1) != exp_pr_st:
            mismatches.append(f"pr_status committed='{m_pr_st.group(1)}' != expected='{exp_pr_st}'")

    # 8b. main_head
    exp_main = expected_facts.get("main_head")
    if exp_main:
        m_main = (
            re.search(r'主干 HEAD \(`main_head`\)\*\*：`([0-9a-f]{40})`', target_text)
            or re.search(r'main_head=([0-9a-f]{40})', target_text)
            or re.search(r'Merge Commit:\s*`([0-9a-f]{8,40})`', target_text)
        )
        if not m_main:
            mismatches.append(f"main_head missing from baseline text (expected '{exp_main}')")
        elif not exp_main.startswith(m_main.group(1)) and m_main.group(1) != exp_main:
            mismatches.append(f"main_head committed='{m_main.group(1)}' != expected='{exp_main}'")

    # 9. release_flow_status
    exp_rf_st = expected_facts.get("release_flow_status")
    if exp_rf_st:
        if exp_rf_st not in target_text and "待执行发布流程" not in target_text:
            mismatches.append(f"release_flow_status '{exp_rf_st}' not found in baseline text")

    # 10. OLD_TAG_DELETED
    exp_ot_del = expected_facts.get("old_tag_deleted")
    if exp_ot_del is not None:
        expected_str = str(exp_ot_del).lower()
        m_ot = (
            re.search(r'OLD_TAG_DELETED=(true|false)', target_text)
            or re.search(r'旧 Tag 删除状态.*?`(true|false)`', target_text)
        )
        if not m_ot:
            mismatches.append(f"OLD_TAG_DELETED missing from baseline text (expected '{expected_str}')")
        elif m_ot.group(1) != expected_str:
            mismatches.append(f"OLD_TAG_DELETED committed='{m_ot.group(1)}' != expected='{expected_str}'")

    return mismatches


def verify_current_candidate_pr_facts(
    content: str,
    version_str: str,
    repository: str = "xiefeifeihu/AI-Engineering-Standards",
    project_root: Optional[Path] = None,
    historical_merge_commits: Optional[set[str]] = None,
    historical_candidate_commits: Optional[set[str]] = None,
    expected_facts: Optional[Dict[str, Any]] = None,
    verify_live_pr: bool = False,
    require_live_pr: bool = False,
    is_current_version_released: bool = False,
    simulate_pr_data: Optional[Dict[str, Any]] = None,
    simulate_pr_error: Optional[str] = None,
    simulate_event_data: Optional[Dict[str, Any]] = None,
    return_details: bool = False,
):
    """Delegate CURRENT_CANDIDATE_PR verification to the shared F13+F14 contract in release_evidence."""
    errs, live_details, live_status = verify_candidate_pr_section(
        content=content,
        version_str=version_str,
        repository=repository,
        project_root=project_root,
        historical_merge_commits=historical_merge_commits,
        historical_candidate_commits=historical_candidate_commits,
        expected_facts=expected_facts,
        verify_live_pr=verify_live_pr,
        require_live_pr=require_live_pr,
        is_current_version_released=is_current_version_released,
        simulate_pr_data=simulate_pr_data,
        simulate_pr_error=simulate_pr_error,
        simulate_event_data=simulate_event_data,
    )
    if return_details:
        return errs, live_details, live_status
    return errs


def build_engineering_baseline(
    project_root: Path,
    standards_root: Optional[Path] = None,
    observed_at: Optional[str] = None,
    source_commit_override: Optional[str] = None,
    candidate_commit_override: Optional[str] = None,
    snapshot_commit_override: Optional[str] = None,
    last_verified_ci_commit: Optional[str] = None,
    ci_commit: Optional[str] = None,
    ci_status: Optional[str] = None,
    ci_run_id: Optional[str] = None,
    push_run_id: Optional[str] = None,
    pr_run_id: Optional[str] = None,
    test_count: Optional[int] = None,
    pr_status: Optional[str] = None,
    pr_number: Optional[int] = None,
    candidate_pr_number: Optional[int] = None,
    candidate_pr_status: Optional[str] = None,
    candidate_pr_head: Optional[str] = None,
    candidate_pr_base: Optional[str] = None,
    candidate_pr_draft: Optional[bool] = None,
    candidate_pr_merge_event: Optional[Dict[str, Any]] = None,
    expected_repo_owner: Optional[str] = None,
    old_tag_deleted: bool = True,
    ci_evidence_ref: Optional[str] = None,
    ci_summary: Optional[str] = None,
    pending_verifications: Optional[str] = None,
    historical_ci_runs: Optional[List[str]] = None,
    release_evidence_path: Optional[str] = None,
    release_evidence: Optional[Dict[str, Any]] = None,
    snapshot_evidence_path: Optional[str] = None,
    final_evidence_path: Optional[str] = None,
    ci_fact_override: Optional[Dict[str, Any]] = None,
    build_fact_override: Optional[Dict[str, Any]] = None,
    runtime_fact_override: Optional[Dict[str, Any]] = None,
    test_fact_override: Optional[Dict[str, Any]] = None,
    allow_offline: bool = True,
) -> Tuple[bool, List[str], Optional[Dict[str, Any]], Optional[str]]:
    """Build deterministic engineering baseline JSON and Markdown from authoritative sources.
    Fails closed if any source conflict or missing authoritative input is detected.
    """
    errors: List[str] = []
    project_root = project_root.resolve()
    std_root = resolve_standards_root(str(standards_root) if standards_root else None)

    # Normalize timestamps and load existing baseline facts to avoid non-deterministic loops
    committed_baseline = project_root / "docs" / "当前权威基线.md"
    existing_facts: Dict[str, Any] = {}
    if committed_baseline.exists():
        try:
            ex_txt = committed_baseline.read_text(encoding="utf-8")
            m_obs = re.search(r'verified_at:\s*"([^"]+)"', ex_txt) or re.search(
                r'## 17\. 核验时间.*?\n-\s*`?([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z)`?',
                ex_txt,
            )
            if m_obs:
                existing_facts["observed_at"] = m_obs.group(1).strip()
            m_st = re.search(
                r'## 9\. 最近 CI 事实[^\n]*\n-\s*\*\*核验状态 \(`verification_status`\)\*\*：`([A-Z_]+)`',
                ex_txt,
            )
            if m_st:
                existing_facts["ci_status"] = m_st.group(1).strip()
            m_cand = re.search(r'代码候选 Commit.*?`([0-9a-f]{40})`', ex_txt) or re.search(
                r'当前候选 Commit.*?`([0-9a-f]{40})`', ex_txt
            )
            if m_cand:
                existing_facts["candidate_commit"] = m_cand.group(1).strip()
            m_ci = re.search(r'最近一次已验证 CI Commit.*?`([0-9a-f]{40})`', ex_txt) or re.search(
                r'最近一次已经验证的 CI Commit.*?`([0-9a-f]{40})`', ex_txt
            )
            if m_ci:
                existing_facts["last_verified_ci_commit"] = m_ci.group(1).strip()
            m_snap = re.search(r'文档快照 Commit.*?`([0-9a-f]{40})`', ex_txt)
            if m_snap:
                existing_facts["snapshot_commit"] = m_snap.group(1).strip()
            m_run = re.search(r'最近一次已经验证的 CI Commit.*?Run\s+(\d+)', ex_txt) or re.search(
                r'PR CI 已通过 \(Run:\s+(\d+)', ex_txt
            )
            if m_run:
                existing_facts["ci_run_id"] = m_run.group(1).strip()
            m_push = re.search(r'Run\s+(\d+)\s+Push', ex_txt)
            if m_push:
                existing_facts["push_run_id"] = m_push.group(1).strip()
            m_pr = re.search(r'Run\s+(\d+)\s+PR', ex_txt)
            if m_pr:
                existing_facts["pr_run_id"] = m_pr.group(1).strip()
        except Exception:
            pass

    now_iso = (
        observed_at
        or existing_facts.get("observed_at")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    today_date = now_iso[:10]

    # 1. Load engineering-manifest.yaml
    manifest_path = project_root / "engineering-manifest.yaml"
    if not manifest_path.exists():
        return False, ["BASELINE_CONFLICT_MISSING_MANIFEST: engineering-manifest.yaml does not exist"], None, None
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return False, [f"BASELINE_CONFLICT_CORRUPT_MANIFEST: {e}"], None, None

    proj_info = manifest.get("project") or {}
    project_id = str(proj_info.get("id") or "").strip()
    project_name = str(proj_info.get("name") or "").strip()
    project_purpose = str(proj_info.get("purpose") or "").strip()
    repository = str(proj_info.get("repository") or "xiefeifeihu/AI-Engineering-Standards").strip()
    deployment_kind = str(proj_info.get("deployment_kind") or "SERVICE").strip()
    release_profile = str(proj_info.get("release_profile") or "PERSONAL_LOCAL").strip()
    applicability_map = proj_info.get("document_type_applicability") or {}

    if not project_id or not project_name:
        errors.append("BASELINE_CONFLICT_INVALID_PROJECT_IDENTITY: project.id and project.name are required")

    # 2. Load VERSION
    version_path = project_root / "VERSION"
    if not version_path.exists():
        errors.append("BASELINE_CONFLICT_MISSING_VERSION: VERSION file is missing")
        version_str = "0.0.0"
    else:
        version_str = version_path.read_text(encoding="utf-8").strip().lstrip("v")
        if not re.match(r"^\d+\.\d+\.\d+$", version_str):
            errors.append(f"BASELINE_CONFLICT_INVALID_VERSION: '{version_str}' is not valid SemVer")

    # 3. Load and cross-check standards.lock.json vs engineering-manifest.yaml
    lock_path = project_root / "standards.lock.json"
    if not lock_path.exists():
        return False, ["BASELINE_CONFLICT_MISSING_STANDARDS_LOCK: standards.lock.json is missing"], None, None
    try:
        lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [f"BASELINE_CONFLICT_CORRUPT_STANDARDS_LOCK: {e}"], None, None

    required_lock_keys = ["repository", "version", "tag", "tag_object_sha", "peeled_commit"]
    for k in required_lock_keys:
        if not lock_data.get(k):
            errors.append(f"BASELINE_CONFLICT_INVALID_STANDARDS_LOCK: standards.lock.json missing '{k}'")

    manifest_std = manifest.get("standards") or {}
    if lock_data and manifest_std:
        m_ver = str(manifest_std.get("version") or manifest_std.get("standard_version") or "").lstrip("v")
        m_tag = str(manifest_std.get("tag") or manifest_std.get("release_tag") or "")
        m_commit = str(manifest_std.get("peeled_commit") or manifest_std.get("standard_commit") or "")
        if m_ver and m_ver != lock_data.get("version"):
            errors.append(
                f"BASELINE_CONFLICT_STANDARDS_VERSION: standards.lock.json ({lock_data.get('version')}) != engineering-manifest.yaml ({m_ver})"
            )
        if m_tag and m_tag != lock_data.get("tag"):
            errors.append(
                f"BASELINE_CONFLICT_STANDARDS_TAG: standards.lock.json ({lock_data.get('tag')}) != engineering-manifest.yaml ({m_tag})"
            )
        if m_commit and m_commit != lock_data.get("peeled_commit"):
            errors.append(
                f"BASELINE_CONFLICT_STANDARDS_COMMIT: standards.lock.json ({lock_data.get('peeled_commit')}) != engineering-manifest.yaml ({m_commit})"
            )

    # 4. Collect Git identity facts
    rc_head, git_head = run_git(project_root, ["rev-parse", "HEAD"])
    local_head = git_head if rc_head == 0 and re.fullmatch(r"[0-9a-f]{40}", git_head) else "NOT_VERIFIABLE"
    if source_commit_override:
        if not re.match(r"^[0-9a-f]{40}$", source_commit_override):
            errors.append(f"BASELINE_CONFLICT_INVALID_COMMIT: source_commit_override '{source_commit_override}' is not 40-hex SHA")
        source_commit = source_commit_override
    elif rc_head == 0 and re.match(r"^[0-9a-f]{40}$", git_head):
        source_commit = git_head
    else:
        errors.append("BASELINE_CONFLICT_INVALID_COMMIT: Local Git HEAD is not a valid 40-character SHA")
        source_commit = ""

    branch_name = resolve_snapshot_branch_name(project_root)
    rc_status, git_status_out = run_git(project_root, ["status", "--porcelain"])
    worktree_clean = (len(git_status_out.strip()) == 0) if rc_status == 0 else None

    # Live query remote main - never fallback to local cache
    remote_main_head = query_remote_main_head(project_root)

    # 5. Scan docs/ and locate authoritative document sources
    docs_dir = project_root / "docs"
    if not docs_dir.exists():
        return False, ["BASELINE_CONFLICT_MISSING_DOCS: docs/ directory does not exist"], None, None

    active_docs_by_type: Dict[str, List[Tuple[Path, Dict[str, Any], str]]] = {}
    for md_file in sorted(docs_dir.rglob("*.md")):
        if any(part in ("archive", "99-历史归档", "历史档案") for part in md_file.relative_to(project_root).parts):
            continue
        text = md_file.read_text(encoding="utf-8")
        fm, body = extract_frontmatter_and_body(text)
        if not fm:
            continue
        dtype = str(fm.get("document_type") or "")
        primary = bool(fm.get("primary_entrypoint", False))
        doc_proj_id = str(fm.get("project_id") or "")
        if project_id and doc_proj_id and doc_proj_id != project_id:
            errors.append(
                f"BASELINE_CONFLICT_PROJECT_ID: {md_file.relative_to(project_root)} has project_id='{doc_proj_id}' != '{project_id}'"
            )
        if primary and dtype != "ENGINEERING_BASELINE":
            active_docs_by_type.setdefault(dtype, []).append((md_file, fm, body))

    source_docs: Dict[str, Tuple[Path, Dict[str, Any], str]] = {}
    for req_type in REQUIRED_SOURCE_TYPES:
        app_rule = applicability_map.get(req_type)
        if isinstance(app_rule, dict) and app_rule.get("applicable") is False:
            continue
        candidates = active_docs_by_type.get(req_type, [])
        active_candidates = [c for c in candidates if c[1].get("status") == "ACTIVE"]
        review_candidates = [c for c in candidates if c[1].get("status") in ("IN_REVIEW", "CANDIDATE")]
        if len(candidates) == 0:
            errors.append(f"BASELINE_CONFLICT_MISSING_SOURCE_DOC: Required active source document '{req_type}' is missing")
        elif len(active_candidates) == 1:
            source_docs[req_type] = active_candidates[0]
        elif len(active_candidates) > 1:
            paths = [str(c[0].relative_to(project_root)).replace("\\", "/") for c in active_candidates]
            errors.append(f"BASELINE_CONFLICT_MULTIPLE_SOURCE_DOCS: Multiple active primary entrypoints for '{req_type}': {paths}")
        elif len(review_candidates) == 1:
            source_docs[req_type] = review_candidates[0]
        elif len(review_candidates) > 1:
            paths = [str(c[0].relative_to(project_root)).replace("\\", "/") for c in review_candidates]
            errors.append(f"BASELINE_CONFLICT_MULTIPLE_SOURCE_DOCS: Multiple review primary entrypoints for '{req_type}': {paths}")
        else:
            paths = [str(c[0].relative_to(project_root)).replace("\\", "/") for c in candidates]
            errors.append(f"BASELINE_CONFLICT_MULTIPLE_SOURCE_DOCS: Ambiguous candidates for '{req_type}': {paths}")

    doc_source_commits = {
        str(info[1].get("source_commit")).strip()
        for info in source_docs.values()
        if info[1].get("source_commit")
    }
    if len(doc_source_commits) > 1:
        errors.append(
            f"BASELINE_CONFLICT_SOURCE_COMMIT_MISMATCH: Source documents declare conflicting source_commit values: {sorted(doc_source_commits)}"
        )
    elif len(doc_source_commits) == 1 and not source_commit_override:
        source_commit = next(iter(doc_source_commits))

    # A declared source_commit must be a real commit in this repository and
    # must contain every source document used to build the baseline.
    if source_commit:
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            errors.append(f"BASELINE_CONFLICT_INVALID_SOURCE_COMMIT: '{source_commit}' is not a full 40-hex SHA")
        else:
            rc_source, _ = run_git(project_root, ["cat-file", "-e", f"{source_commit}^{{commit}}"])
            if rc_source != 0:
                errors.append(f"BASELINE_CONFLICT_SOURCE_COMMIT_NOT_FOUND: {source_commit}")
            for source_type, (source_path, _, _) in source_docs.items():
                rel_path = source_path.relative_to(project_root).as_posix()
                rc_path, _ = run_git(project_root, ["cat-file", "-e", f"{source_commit}:{rel_path}"])
                if rc_path != 0:
                    errors.append(
                        f"BASELINE_CONFLICT_SOURCE_PATH_NOT_IN_COMMIT: {source_type} path '{rel_path}' does not exist at {source_commit}"
                    )
            if rc_head == 0 and re.fullmatch(r"[0-9a-f]{40}", git_head):
                rc_ancestor, _ = run_git(project_root, ["merge-base", "--is-ancestor", source_commit, git_head])
                if rc_ancestor != 0:
                    errors.append(
                        f"BASELINE_CONFLICT_SOURCE_COMMIT_NOT_ANCESTOR: {source_commit} is not an ancestor of current HEAD {git_head}"
                    )

    if errors:
        return False, errors, None, None

    def rel_doc(dtype: str) -> str:
        return str(source_docs[dtype][0].relative_to(project_root)).replace("\\", "/")

    def doc_id_of(dtype: str) -> str:
        return str(source_docs[dtype][1].get("document_id"))

    def doc_ver_of(dtype: str) -> str:
        return str(source_docs[dtype][1].get("document_version"))

    # Load release evidence if available
    evidence_data: Optional[Dict[str, Any]] = release_evidence
    if snapshot_evidence_path:
        snap_ok, snap_errors, _ = load_release_evidence(project_root, snapshot_evidence_path)
        if not snap_ok:
            errors.extend([f"BASELINE_SNAPSHOT_EVIDENCE_INVALID: {e}" for e in snap_errors])
    if release_evidence_path and final_evidence_path:
        pr9_ok, pr9_errors, _ = load_release_evidence(project_root, release_evidence_path)
        if not pr9_ok:
            errors.extend([f"BASELINE_HISTORICAL_RELEASE_EVIDENCE_INVALID: {e}" for e in pr9_errors])
    if final_evidence_path:
        final_ok, final_errors, final_loaded = load_release_evidence(project_root, final_evidence_path)
        if not final_ok or final_loaded is None:
            errors.extend([f"BASELINE_FINAL_RELEASE_EVIDENCE_INVALID: {e}" for e in final_errors])
        else:
            evidence_data = final_loaded
    elif evidence_data is None:
        ev_ok, ev_errors, ev_loaded = load_release_evidence(project_root, release_evidence_path)
        if ev_ok and ev_loaded:
            evidence_data = ev_loaded
        elif release_evidence_path:
            errors.extend([f"BASELINE_RELEASE_EVIDENCE_INVALID: {e}" for e in ev_errors])

    # Extract capabilities, boundaries, contracts, ADRs from authoritative sources
    pb_items = extract_bullet_items(source_docs["PRODUCT_BASELINE"][2], max_items=8) or [
        str(source_docs["PRODUCT_BASELINE"][1].get("change_summary") or "权威产品基线核心能力")
    ]
    arch_items = extract_bullet_items(source_docs["SYSTEM_ARCHITECTURE"][2], max_items=6) or [
        "系统架构与组件边界参见权威架构文档"
    ]
    api_items = extract_bullet_items(source_docs["API_CONTRACT"][2], max_items=6) or [
        "接口与 Schema 契约参见权威 API 契约文档"
    ]
    adr_items = extract_adrs_from_decision_record(source_docs["DECISION_RECORD"][2], rel_doc("DECISION_RECORD"))

    # Separate historical release evidence from current candidate PR facts (STD-034 / STD-035).
    # Historical evidence for an older released version (e.g. v3.0.0 std019) MUST NEVER overwrite
    # current candidate PR metadata (candidate_pr_number, candidate_pr_status, candidate_commit, merge_commit).
    is_current_version_released = bool(
        evidence_data
        and str(evidence_data.get("version", "")).lstrip("v") == version_str
        and evidence_data.get("release_flow_status") == "RELEASED"
    )
    current_ver_evidence: Optional[Dict[str, Any]] = evidence_data if is_current_version_released else None

    # Collect known historical merge commits so they can NEVER pollute the current candidate PR
    historical_merge_commits: set[str] = set()
    if not is_current_version_released:
        if evidence_data:
            for hk in ("main_head", "peeled_commit"):
                hv = str(evidence_data.get(hk) or "").strip()
                if re.fullmatch(r"[0-9a-f]{40}", hv):
                    historical_merge_commits.add(hv)
        for hist_name in ("v3.0.0-reissue.json", "std018-current-snapshot.json", "std019-final-release.json"):
            hp = project_root / "docs" / "release-evidence" / hist_name
            if hp.is_file():
                try:
                    hdata = json.loads(hp.read_text(encoding="utf-8"))
                    for hk in ("main_head", "peeled_commit"):
                        hv = str(hdata.get(hk) or "").strip()
                        if re.fullmatch(r"[0-9a-f]{40}", hv):
                            historical_merge_commits.add(hv)
                except Exception:
                    pass

    # Dynamic facts with mandatory 6 provenance fields (decoupled from historical v3.0.0 evidence)
    code_candidate_commit = (
        candidate_commit_override
        or (current_ver_evidence.get("candidate_commit") if current_ver_evidence else None)
        or (local_head if local_head != "NOT_VERIFIABLE" else source_commit)
    )
    snapshot_commit = (
        snapshot_commit_override
        or (local_head if local_head != "NOT_VERIFIABLE" else None)
        or (current_ver_evidence.get("snapshot_commit") if current_ver_evidence else None)
        or source_commit
    )
    verified_ci = (
        last_verified_ci_commit
        or ci_commit
        or (current_ver_evidence.get("last_verified_ci_commit") if current_ver_evidence else None)
        or code_candidate_commit
    )
    effective_ci_status = (
        ci_status
        or (current_ver_evidence.get("ci_status") if current_ver_evidence else None)
        or "NOT_VERIFIABLE"
    )
    effective_push_run = (
        push_run_id
        or (current_ver_evidence.get("push_run_id") if current_ver_evidence else None)
    )
    effective_pr_run = (
        pr_run_id
        or (current_ver_evidence.get("pr_run_id") if current_ver_evidence else None)
    )
    effective_run_id = (
        ci_run_id
        or effective_push_run
    )

    # Current Candidate PR Identity (strictly decoupled from historical PR #9 / PR #10 / std019)
    eff_cand_pr_number: Optional[int] = (
        candidate_pr_number if candidate_pr_number is not None else pr_number
    )
    if eff_cand_pr_number is not None and int(eff_cand_pr_number) < 1:
        errors.append(
            f"CANDIDATE_PR_INVALID_NUMBER: candidate_pr_number must be >= 1 (got '{eff_cand_pr_number}')"
        )

    raw_cand_pr_status = (
        candidate_pr_status if candidate_pr_status is not None else pr_status
    )
    if raw_cand_pr_status is not None:
        effective_pr_status = str(raw_cand_pr_status).strip().upper()
        if effective_pr_status not in ("DRAFT", "OPEN", "MERGED", "CLOSED"):
            errors.append(
                f"CANDIDATE_PR_INVALID_STATUS: candidate_pr_status '{effective_pr_status}' must be DRAFT, OPEN, MERGED, or CLOSED"
            )
    else:
        effective_pr_status = "DRAFT"

    # Validate candidate_commit is a real Git commit (F13 Rule 2)
    if (project_root / ".git").exists():
        if not re.fullmatch(r"[0-9a-f]{40}", str(code_candidate_commit or "")) or code_candidate_commit == "0" * 40:
            errors.append(
                f"CANDIDATE_COMMIT_INVALID: candidate_commit '{code_candidate_commit}' must be a non-zero 40-hex SHA"
            )
        else:
            rc_cand_obj, _ = run_git(project_root, ["cat-file", "-e", f"{code_candidate_commit}^{{commit}}"])
            if rc_cand_obj != 0:
                errors.append(
                    f"CANDIDATE_COMMIT_NOT_FOUND: candidate_commit '{code_candidate_commit}' does not exist in Git repository"
                )

    # Candidate PR Head validation (F13): when explicitly supplied, verify candidate_commit is an ancestor
    # of candidate_pr_head via `git merge-base --is-ancestor` (NEVER require static equality with PR HEAD).
    if candidate_pr_head is not None:
        eff_cand_pr_head = str(candidate_pr_head).strip()
        anc_st, anc_errs = verify_commit_ancestry(
            project_root,
            code_candidate_commit,
            eff_cand_pr_head,
            repository=repository,
            allow_remote_compare=not allow_offline,
        )
        if anc_st == "FAIL":
            errors.extend(anc_errs)
        elif anc_st == "NOT_VERIFIABLE" and not allow_offline:
            errors.extend(anc_errs)

    # Candidate PR Base validation: must target official 'main'
    eff_cand_pr_base = str(candidate_pr_base).strip() if candidate_pr_base is not None else "main"
    if eff_cand_pr_base != "main":
        errors.append(
            f"CANDIDATE_PR_BASE_NOT_MAIN: candidate_pr_base '{eff_cand_pr_base}' must be 'main'"
        )

    # Candidate PR Merge Provenance Gate: MERGED is ONLY allowed when backed by a verified GitHub PR merge event
    verified_merge_commit: Optional[str] = None
    verified_merged_by: Optional[str] = None
    eff_owner = (expected_repo_owner or repository.split("/")[0]).strip()
    if effective_pr_status == "MERGED":
        if eff_cand_pr_number is None:
            errors.append(
                "CANDIDATE_PR_NUMBER_REQUIRED_FOR_MERGED: candidate_pr_number is required to verify MERGED status"
            )
        else:
            pr_ev_obj = candidate_pr_merge_event
            if pr_ev_obj is None and not allow_offline:
                ok_api, api_pr_data, _ = _query_pr_via_api(repository, eff_cand_pr_number)
                if ok_api and api_pr_data:
                    pr_ev_obj = api_pr_data
                else:
                    ok_gh, gh_pr_data, _ = _query_pr_via_gh(repository, eff_cand_pr_number)
                    if ok_gh and gh_pr_data:
                        pr_ev_obj = gh_pr_data
            if pr_ev_obj is None:
                errors.append(
                    "CANDIDATE_PR_MERGE_NOT_VERIFIED: Cannot mark current candidate PR as MERGED without verified GitHub PR merge event (merged=true, merged_by=owner, base=main, head.sha>=candidate_commit)"
                )
            else:
                m_ok, m_errs, m_sha, m_by = verify_candidate_pr_merge_event(
                    pr_event=pr_ev_obj,
                    expected_pr_number=eff_cand_pr_number,
                    expected_candidate_commit=code_candidate_commit,
                    expected_owner=eff_owner,
                    expected_base="main",
                    forbidden_historical_merge_commits=historical_merge_commits,
                    project_root=project_root,
                    repository=repository,
                )
                if not m_ok:
                    errors.extend(m_errs)
                else:
                    verified_merge_commit = m_sha
                    verified_merged_by = m_by

    if effective_pr_status == "DRAFT":
        if candidate_pr_draft is False:
            errors.append(
                "CANDIDATE_PR_DRAFT_CONFLICT: candidate_pr_status='DRAFT' conflicts with candidate_pr_draft=False"
            )
        pr_state_str = "OPEN"
        pr_draft_bool = True
        release_status_str = "CANDIDATE"
    elif effective_pr_status == "OPEN":
        pr_state_str = "OPEN"
        pr_draft_bool = bool(candidate_pr_draft) if candidate_pr_draft is not None else False
        release_status_str = "CANDIDATE"
    elif effective_pr_status == "MERGED":
        pr_state_str = "MERGED"
        pr_draft_bool = False
        release_status_str = "RELEASED" if is_current_version_released else "MERGED_PENDING_TAG"
    else:
        pr_state_str = "CLOSED"
        pr_draft_bool = False
        release_status_str = "BLOCKED"

    pr_label = f"PR #{eff_cand_pr_number}" if eff_cand_pr_number is not None else "当前候选 PR"

    if pending_verifications is not None:
        pending_text = pending_verifications
    elif effective_pr_status == "MERGED" and is_current_version_released:
        pending_text = f"正式版本 v{version_str} 已发布并完成核验。"
    elif effective_pr_status == "MERGED" and verified_merge_commit:
        if effective_ci_status == "PASS":
            pending_text = (
                f"{pr_label} 已由 {verified_merged_by} 合入 main（Merge Commit: {verified_merge_commit[:8]}）；"
                f"当前待修复 PR 合入 main 且 main CI 双平台全绿后由官方工作流自动签发 v{version_str} Annotated Tag。"
            )
        else:
            pending_text = (
                f"{pr_label} 已由 {verified_merged_by} 合入 main（Merge Commit: {verified_merge_commit[:8]}）；"
                f"当前快照 ({code_candidate_commit[:8]}) 待推送到 GitHub Actions 远端触发双平台真实 CI 实测并合入 main 后签发 v{version_str} Tag（实测前保持 NOT_VERIFIABLE）。"
            )
    elif effective_ci_status == "PASS":
        pending_text = f"{pr_label} CI 已通过，等待 ChatGPT 独立复核与唯一 Owner 批准合入 main，由 main CI 自动签发 v{version_str} Annotated Tag。"
    else:
        pending_text = f"当前候选 Commit ({code_candidate_commit[:8]}) 待推送到 GitHub Actions 远端触发 Windows/Ubuntu 双平台真实 CI 完整运行；实测完成前严格保持 NOT_VERIFIABLE，严禁本地伪造 PASS"

    default_historical_runs = [
        "Run 42169418901 (Push @ 4041b1d, conclusion: success, Windows/Ubuntu PASS)",
        "Run 42169424617 (PR #8 @ 4041b1d, conclusion: success, Windows/Ubuntu PASS)",
        "Run 42177850321 (Push @ a7a0177, conclusion: success, Windows/Ubuntu PASS)",
        "Run 42177858136 (PR #8 @ a7a0177, conclusion: success, Windows/Ubuntu PASS)",
        "Run 42553441590 (Push @ a43ef57, conclusion: success, Windows/Ubuntu PASS)",
        "Run 42553446392 (PR #8 @ a43ef57, conclusion: success, Windows/Ubuntu PASS)",
        "Run 42571376296 (Push @ 96d1b4a, conclusion: success, Windows/Ubuntu PASS, 188 tests)",
        "Run 42571381569 (PR #8 @ 96d1b4a, conclusion: success, Windows/Ubuntu PASS, 188 tests)",
        "Run 42583709325 (Push @ e7b80fe, conclusion: success, Windows/Ubuntu PASS, 207 tests)",
        "Run 42583717591 (PR #8 @ e7b80fe, conclusion: success, Windows/Ubuntu PASS, 207 tests)",
        "Run 42747292971 (Push @ c52f97a, conclusion: success, Windows/Ubuntu PASS, 215 tests)",
        "Run 42760791748 (PR #9 @ c52f97a, conclusion: success, Windows/Ubuntu PASS, 215 tests)",
        "Run 42763704495 (Push @ 60a03bc, conclusion: success, Windows/Ubuntu PASS, 216 tests)",
        "Run 42763710456 (PR #9 @ 60a03bc, conclusion: success, Windows/Ubuntu PASS, 216 tests)",
        "Run 42772211734 (Push @ e187b49, conclusion: success, Windows/Ubuntu PASS, 216 tests)",
        "Run 42772217074 (PR #9 @ e187b49, conclusion: success, Windows/Ubuntu PASS, 216 tests)",
        "Run 42783497089 (Push @ 4538b8b, conclusion: success, Windows/Ubuntu PASS, 216 tests)",
        "Run 42783504258 (PR #9 @ 4538b8b, conclusion: success, Windows/Ubuntu PASS, 216 tests)",
        "Run 42800374434 (Push @ 70f7554, conclusion: success, Windows/Ubuntu PASS, 217 tests)",
        "Run 42800383714 (PR #9 @ 70f7554, conclusion: success, Windows/Ubuntu PASS, 217 tests)",
        "Run 42835602231 (Push @ 18a71b9, conclusion: success, Windows/Ubuntu PASS, 218 tests)",
        "Run 42835611644 (PR #9 @ 18a71b9, conclusion: success, Windows/Ubuntu PASS, 218 tests)",
        "Run 42843755347 (Push @ 3361148, conclusion: success, Windows/Ubuntu PASS, 219 tests)",
        "Run 42843964061 (PR #9 @ 3361148, conclusion: success, Windows/Ubuntu PASS, 219 tests)",
    ]
    hist_runs = historical_ci_runs or default_historical_runs

    candidate_pr_meta: Dict[str, Any] = {
        "candidate_version": version_str,
        "candidate_pr_number": eff_cand_pr_number,
        "candidate_pr_status": effective_pr_status,
        "pr_state": pr_state_str,
        "pr_draft": pr_draft_bool,
        "candidate_pr_base": eff_cand_pr_base,
        "candidate_commit": code_candidate_commit,
        "live_pr_head_source": "GITHUB_PR_API_REQUIRED",
        "ci_runtime_record": "GITHUB_STEP_SUMMARY",
        "observed_at": now_iso,
        "release_status": release_status_str,
    }
    if verified_merge_commit:
        candidate_pr_meta["merge_commit_sha"] = verified_merge_commit
    if verified_merged_by:
        candidate_pr_meta["merged_by"] = verified_merged_by

    ci_details: Dict[str, Any] = {
        "source_commit": source_commit,
        "git_snapshot_observed_at": now_iso,
        "last_verified_ci_commit": verified_ci,
        "candidate_commit": code_candidate_commit,
        "snapshot_commit": snapshot_commit,
        "pending_verifications": pending_text,
        "historical_ci_runs": hist_runs,
        "snapshot_status": "FRESH",
        "snapshot_validity_hours": 24,
        "workflow": "standards-ci.yml",
        "candidate_pr": candidate_pr_meta,
    }
    if effective_run_id:
        ci_details["run_id"] = int(effective_run_id) if str(effective_run_id).isdigit() else effective_run_id
    if effective_push_run:
        ci_details["push_run_id"] = int(effective_push_run) if str(effective_push_run).isdigit() else effective_push_run
    if effective_pr_run:
        ci_details["pr_run_id"] = int(effective_pr_run) if str(effective_pr_run).isdigit() else effective_pr_run
    if ci_commit:
        ci_details["ci_commit"] = ci_commit

    effective_test_count = test_count if test_count is not None else (current_ver_evidence.get("test_count") if current_ver_evidence else None)
    test_count_clause = f", {effective_test_count} tests" if effective_test_count is not None else ""
    if ci_summary:
        summary_text = ci_summary
    elif effective_ci_status == "PASS":
        if effective_push_run and effective_pr_run:
            run_lbl = f"{effective_push_run} Push / {effective_pr_run} {pr_label}"
        elif effective_run_id:
            run_lbl = str(effective_run_id)
        else:
            run_lbl = pr_label
        if effective_pr_status == "MERGED" and verified_merge_commit and verified_merged_by:
            summary_text = (
                f"{pr_label} CI 已通过 (Run: {run_lbl} 双平台 PASS{test_count_clause})，"
                f"{pr_label} 已由 {verified_merged_by} 合入 main (Merge Commit: {verified_merge_commit})"
            )
        else:
            summary_text = (
                f"{pr_label} CI 已通过 (Run: {run_lbl} 双平台 PASS{test_count_clause})，"
                f"当前处于 {pr_state_str} / {release_status_str} 状态，等待 ChatGPT 独立复核与 Owner 批准合入 main"
            )
    else:
        ci_ref_note = ""
        if effective_push_run and effective_pr_run:
            ci_ref_note = f"；最近已验证 {pr_label} CI: Push Run {effective_push_run} / PR Run {effective_pr_run} @ {verified_ci[:8]}"
        summary_text = (
            f"当前候选 {pr_label} (Commit {code_candidate_commit[:8]}) 远端 GitHub Actions CI 待推送后由远端 Runner 实测"
            f"（执行前保持 NOT_VERIFIABLE{ci_ref_note}）"
        )

    ci_fact: Dict[str, Any] = ci_fact_override or {
        "repository": repository,
        "source_path": ".github/workflows/standards-ci.yml",
        "source_commit": source_commit,
        "evidence_ref": ci_evidence_ref or ".github/workflows/standards-ci.yml",
        "observed_at": now_iso,
        "verification_status": effective_ci_status,
        "summary": summary_text,
        "details": ci_details,
    }

    if deployment_kind == "NON_RUNTIME_ARTIFACT":
        build_fact = build_fact_override or {
            "repository": repository,
            "source_path": "VERSION",
            "source_commit": source_commit,
            "evidence_ref": "VERSION",
            "observed_at": now_iso,
            "verification_status": "NOT_RUN",
            "summary": "非运行时规范制品库声明 NON_RUNTIME_ARTIFACT，无独立编译构建步骤，按 STD-017/STD-032 记录 NOT_RUN",
            "details": {"deployment_kind": "NON_RUNTIME_ARTIFACT", "version": version_str},
        }
    else:
        build_fact = build_fact_override or {
            "repository": repository,
            "source_path": "VERSION",
            "source_commit": source_commit,
            "evidence_ref": "VERSION",
            "observed_at": now_iso,
            "verification_status": "NOT_VERIFIABLE",
            "summary": "运行态制品构建事实待环境核验",
            "details": {"deployment_kind": deployment_kind, "version": version_str},
        }

    runtime_fact: Dict[str, Any] = runtime_fact_override or (
        {
            "repository": repository,
            "source_path": "engineering-manifest.yaml",
            "source_commit": source_commit,
            "evidence_ref": "engineering-manifest.yaml",
            "observed_at": now_iso,
            "verification_status": "NOT_RUN",
            "summary": "NON_RUNTIME_ARTIFACT 规范仓库无常驻在线 HTTP 容器服务，按 STD-017/STD-032 不伪造在线服务探针",
            "details": {"deployment_kind": "NON_RUNTIME_ARTIFACT"},
        }
        if deployment_kind == "NON_RUNTIME_ARTIFACT"
        else {
            "repository": repository,
            "source_path": "engineering-manifest.yaml",
            "source_commit": source_commit,
            "evidence_ref": "engineering-manifest.yaml",
            "observed_at": now_iso,
            "verification_status": "NOT_VERIFIABLE",
            "summary": "运行态探针需在受控目标环境实测核验",
            "details": {"deployment_kind": deployment_kind},
        }
    )

    default_test_log = project_root / ".artifacts" / "test_results.txt"
    if test_fact_override:
        test_fact = test_fact_override
    elif default_test_log.exists():
        test_fact = {
            "repository": repository,
            "source_path": rel_doc("TEST_ACCEPTANCE") if "TEST_ACCEPTANCE" in source_docs else "docs/TEST-ACCEPTANCE.md",
            "source_commit": source_commit,
            "evidence_ref": ".artifacts/test_results.txt",
            "observed_at": now_iso,
            "verification_status": "NOT_VERIFIABLE",
            "summary": "检测到文本测试日志，但未验证结构化结果、退出码、目标 Commit 与证据摘要；不得据此判定 PASS",
            "details": {"test_log": ".artifacts/test_results.txt", "reason": "UNVERIFIED_TEXT_LOG"},
        }
    else:
        test_fact = {
            "repository": repository,
            "source_path": rel_doc("TEST_ACCEPTANCE") if "TEST_ACCEPTANCE" in source_docs else "docs/TEST-ACCEPTANCE.md",
            "source_commit": source_commit,
            "evidence_ref": rel_doc("TEST_ACCEPTANCE") if "TEST_ACCEPTANCE" in source_docs else "docs/TEST-ACCEPTANCE.md",
            "observed_at": now_iso,
            "verification_status": "NOT_RUN",
            "summary": "未检测到本地测试执行原始日志文件（.artifacts/test_results.txt），按铁律 G 记录 NOT_RUN，禁止伪造 PASS",
            "details": {"test_entrypoint": "python -m unittest discover -s tests -v"},
        }

    for label, fact in (
        ("recent_ci_facts", ci_fact),
        ("recent_build_facts", build_fact),
        ("runtime_verification_facts", runtime_fact),
        ("test_and_acceptance_facts", test_fact),
    ):
        st = fact.get("verification_status")
        ev = str(fact.get("evidence_ref") or "").strip()
        if st not in VALID_VERIFICATION_STATUSES:
            errors.append(f"BASELINE_INVALID_FACT_STATUS [{label}]: '{st}'")
        if st == "PASS":
            if not ev or ev in ("NONE", "N/A", "NOT_RUN", "null"):
                errors.append(f"BASELINE_PASS_WITHOUT_EVIDENCE [{label}]: PASS requires non-empty evidence_ref")
            elif not (project_root / ev).exists():
                errors.append(f"BASELINE_MISSING_EVIDENCE_FILE [{label}]: evidence_ref '{ev}' does not exist")

    if errors:
        return False, errors, None, None

    baseline_payload: Dict[str, Any] = {
        "schema_version": "1.0.0",
        "project_identity": {
            "project_id": project_id,
            "name": project_name,
            "repository": repository,
            "purpose": project_purpose,
            "deployment_kind": deployment_kind,
            "release_profile": release_profile,
            "source_doc_ref": rel_doc("PROJECT_BLUEPRINT"),
        },
        "product_version": {
            "version": version_str,
            "release_tag": f"v{version_str}",
            "source_path": "VERSION",
            "source_commit": source_commit,
        },
        "product_capabilities": {
            "source_doc_ref": rel_doc("PRODUCT_BASELINE"),
            "document_id": doc_id_of("PRODUCT_BASELINE"),
            "document_version": doc_ver_of("PRODUCT_BASELINE"),
            "capabilities": pb_items,
        },
        "architecture_boundaries": {
            "architecture_doc_ref": rel_doc("SYSTEM_ARCHITECTURE"),
            "technical_design_doc_ref": rel_doc("TECHNICAL_DESIGN"),
            "owned_resources": [
                "standards/** (STD-001 ~ STD-035)",
                "schemas/*.schema.json",
                "tools/standards_sync/ & tools/validate-*.py",
                "templates/documentation/",
            ]
            if project_id == "ai-engineering-standards"
            else arch_items,
            "read_only_boundaries": [
                "AI-Engineering-Hub (Read-Only Reference)",
                "AI-KB (Read-Only Reference)",
                "vtip-platform-catalog (Read-Only Reference)",
                "vtip-ai-sidecar (Read-Only Reference)",
            ],
        },
        "api_contract_entrypoints": {
            "source_doc_ref": rel_doc("API_CONTRACT"),
            "document_id": doc_id_of("API_CONTRACT"),
            "contracts": api_items,
        },
        "approved_adrs": {
            "source_doc_ref": rel_doc("DECISION_RECORD"),
            "document_id": doc_id_of("DECISION_RECORD"),
            "decisions": adr_items,
        },
        "standards_lock": {
            "repository": str(lock_data.get("repository")),
            "version": str(lock_data.get("version")),
            "tag": str(lock_data.get("tag")),
            "tag_object_sha": str(lock_data.get("tag_object_sha")),
            "peeled_commit": str(lock_data.get("peeled_commit")),
            "source_path": "standards.lock.json",
            "verification_status": "NOT_VERIFIABLE",
        },
        "git_identity": {
            "branch": branch_name,
            "local_head": local_head,
            "remote_main_head": remote_main_head,
            "worktree_clean": worktree_clean,
            "verification_status": "PASS" if rc_head == 0 and rc_status == 0 else "NOT_VERIFIABLE",
        },
        "recent_ci_facts": ci_fact,
        "recent_build_facts": build_fact,
        "runtime_verification_facts": runtime_fact,
        "test_and_acceptance_facts": test_fact,
        "open_issues": [
            {
                "issue_id": "AIHUB-FIRST-CONSUMER-PILOT-001",
                "summary": "AI-Hub 是首个消费端试点，待 Standards 正式发布后由 AI-Hub Owner 独立批准并执行；AI-KB、VTIP、SideCar 不在本轮范围",
                "status": "DEFERRED",
            }
        ],
        "pending_approvals": [
            {
                "item_id": "PR-REVIEW-STANDARDS-V3-001",
                "summary": "等待 Draft PR 阶段由 ChatGPT 独立读取 GitHub PR Diff 审核并由 Owner 批准合入 main",
                "required_approver": "OWNER",
                "status": "OWNER_APPROVAL_REQUIRED",
            }
        ],
        "evidence_sources": [
            ci_fact,
            build_fact,
            runtime_fact,
            test_fact,
        ],
        "source_commit": source_commit,
        "verified_at": now_iso,
        "content_sha256": "",
    }

    content_sha = compute_deterministic_baseline_sha256(baseline_payload)
    baseline_payload["content_sha256"] = content_sha

    # Validate against engineering-baseline.schema.json
    baseline_schema_path = std_root / "schemas" / "engineering-baseline.schema.json"
    if baseline_schema_path.exists():
        b_schema = json.loads(baseline_schema_path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(instance=baseline_payload, schema=b_schema)
        except jsonschema.ValidationError as ve:
            return False, [f"BASELINE_SCHEMA_VIOLATION: {ve.message}"], None, None

    # Determine baseline status & approval status based on source documents
    # Generation never grants approval; a separate trusted review event is required.
    baseline_status = "IN_REVIEW"
    baseline_approval_status = "IN_REVIEW"

    # Render deterministic Markdown for docs/当前权威基线.md
    cap_bullets = "\n".join(f"- {c}" for c in baseline_payload["product_capabilities"]["capabilities"])
    owned_bullets = "\n".join(f"- 属主资源：`{r}`" for r in baseline_payload["architecture_boundaries"]["owned_resources"])
    ro_bullets = "\n".join(f"- 只读边界：`{r}`" for r in baseline_payload["architecture_boundaries"]["read_only_boundaries"])
    api_bullets = "\n".join(f"- {c}" for c in baseline_payload["api_contract_entrypoints"]["contracts"])
    adr_rows = (
        "\n".join(
            f"| `{d['decision_id']}` | {d['title']} | `{d['approval_status']}` | [`{d['source_ref']}`](./{Path(d['source_ref']).name}) |"
            for d in baseline_payload["approved_adrs"]["decisions"]
        )
        if baseline_payload["approved_adrs"]["decisions"]
        else "| - | 暂无批准 ADR | - | - |"
    )
    ev_rows = "\n".join(
        f"| `{ev['repository']}` | `{ev['source_path']}` | `{ev['source_commit']}` | `{ev['evidence_ref']}` | `{ev['observed_at']}` | `{ev['verification_status']}` |"
        for ev in baseline_payload["evidence_sources"]
    )
    issue_rows = "\n".join(
        f"| `{iss['issue_id']}` | {iss['summary']} | `{iss['status']}` |"
        for iss in baseline_payload["open_issues"]
    )
    approval_rows = "\n".join(
        f"| `{ap['item_id']}` | {ap['summary']} | `{ap['required_approver']}` | `{ap['status']}` |"
        for ap in baseline_payload["pending_approvals"]
    )

    doc_prefix = project_id.upper().replace("_", "-")
    md_lines = [
        "---",
        f'document_id: "DOC-{doc_prefix}-ENGINEERING-BASELINE-001"',
        f'document_version: "{version_str}"',
        f'project_id: "{project_id}"',
        'document_type: "ENGINEERING_BASELINE"',
        f'status: "{baseline_status}"',
        f'applies_to_release: "v{version_str}"',
        f'last_updated: "{today_date}"',
        "supersedes: null",
        'change_summary: "基于11类正式文档与10项实时工程事实确定性生成当前权威基线综合视图"',
        "history_reference: null",
        "primary_entrypoint: true",
        f'source_commit: "{source_commit}"',
        f'content_sha256: "{content_sha}"',
        'approval_scope: "AI_APPROVABLE"',
        f'approval_status: "{baseline_approval_status}"',
        "---",
        "",
        f"# 当前权威基线 ({project_name} Engineering Baseline)",
        "",
        "> **权威视图声明 (`STD-035` §4)**：本文件（`docs/当前权威基线.md`）是由 `tools/generate_engineering_baseline.py` 自动生成的工程正式资料和实时核验事实综合视图。本文件**不是**第二套产品规格、**不是**第二套架构文档、**不是**第二套接口定义，也**不是**人工随意编辑的汇总报告；所有条目严格引用原始权威资料并区分已核实事实与待审批事项。",
        "",
        "## 1. 工程身份与定位 (`project_identity`)",
        f"- **工程标识 (`project_id`)**：`{project_id}`",
        f"- **工程名称 (`name`)**：{project_name}",
        f"- **代码仓库 (`repository`)**：`{repository}`",
        f"- **工程定位 (`purpose`)**：{project_purpose}",
        f"- **制品/部署形态 (`deployment_kind`)**：`{deployment_kind}`",
        f"- **发布治理档位 (`release_profile`)**：`{release_profile}`",
        f"- **权威蓝图入口**：[`{rel_doc('PROJECT_BLUEPRINT')}`](./{Path(rel_doc('PROJECT_BLUEPRINT')).name}) (`{doc_id_of('PROJECT_BLUEPRINT')}`)",
        "",
        "## 2. 当前产品版本 (`product_version`)",
        f"- **当前版本 (`VERSION`)**：`{version_str}`",
    ]
    std_active_ev: Optional[Dict[str, Any]] = None
    std_pr9_ev: Optional[Dict[str, Any]] = None
    std_snap_ev: Optional[Dict[str, Any]] = None
    std_019_ev: Optional[Dict[str, Any]] = None
    if project_id == "ai-engineering-standards" and (project_root / "docs" / "release-evidence").exists():
        _ok_a, _, _ev_a = load_release_evidence(
            project_root, resolve_release_evidence_path(project_root)
        )
        if _ok_a and _ev_a:
            std_active_ev = _ev_a
        _p_pr9 = project_root / "docs" / "release-evidence" / "v3.0.0-reissue.json"
        if _p_pr9.exists():
            _ok_p, _, _ev_p = load_release_evidence(project_root, _p_pr9)
            if _ok_p:
                std_pr9_ev = _ev_p
        _p_snap = project_root / "docs" / "release-evidence" / "std018-current-snapshot.json"
        if _p_snap.exists():
            _ok_s, _, _ev_s = load_release_evidence(project_root, _p_snap)
            if _ok_s:
                std_snap_ev = _ev_s
        _p_019 = project_root / "docs" / "release-evidence" / "std019-final-release.json"
        if _p_019.exists():
            _ok_19, _, _ev_19 = load_release_evidence(project_root, _p_019)
            if _ok_19:
                std_019_ev = _ev_19

    if (
        std_active_ev
        and str(std_active_ev.get("version", "")).lstrip("v") == version_str
        and std_active_ev.get("release_flow_status") == "RELEASED"
    ):
        md_lines.extend([
            f"- **正式发布标签 (`release_tag`)**：`{std_active_ev['release_tag']}`",
            f"- **正式发布状态**：`RELEASED`（官方 main 上的 Annotated Tag `{std_active_ev['release_tag']}`，Tag Object SHA: `{std_active_ev['tag_object_sha']}`，Peeled Commit: `{std_active_ev['peeled_commit']}`，main CI Run {std_active_ev.get('main_ci_run_id') or std_active_ev['push_run_id']} 双平台全绿，{std_active_ev['test_count']} tests PASS）。",
        ])
    elif std_active_ev and std_active_ev.get("release_flow_status") == "RELEASED":
        md_lines.extend([
            f"- **当前已发布最新正式标签 (`LATEST_RELEASED_TAG`)**：`{std_active_ev.get('release_tag', lock_data.get('tag', 'v3.0.0'))}`（Tag Object SHA: `{std_active_ev.get('tag_object_sha', lock_data.get('tag_object_sha'))}`，Peeled Commit: `{std_active_ev.get('peeled_commit', lock_data.get('peeled_commit'))}`）",
            f"- **候选目标标签 (`candidate_release_tag`)**：`v{version_str}`",
            f"- **正式发布状态**：`CANDIDATE`（当前工作区 `VERSION={version_str}` 尚未合入 main 并由官方工作流签发 `v{version_str}` Tag；正式版本以官方 `main` 上的 Annotated Tag 和 main CI 为准）。",
        ])
    else:
        md_lines.extend([
            f"- **候选目标标签 (`release_tag`)**：`v{version_str}`",
            "- **正式发布状态**：候选分支上的 VERSION 不等于正式发布；正式版本以官方 main 上的 Annotated Tag 和 main CI 为准。",
        ])

    md_lines.extend([
        f"- **版本事实来源**：`VERSION` @ `{source_commit}`",
        "",
        "## 3. 正式产品功能及职责 (`product_capabilities`)",
        f"- **权威产品基线入口**：[`{rel_doc('PRODUCT_BASELINE')}`](./{Path(rel_doc('PRODUCT_BASELINE')).name}) (`{doc_id_of('PRODUCT_BASELINE')}`, `v{doc_ver_of('PRODUCT_BASELINE')}`)",
        cap_bullets,
        "",
        "## 4. 当前架构边界 (`architecture_boundaries`)",
        f"- **权威系统架构入口**：[`{rel_doc('SYSTEM_ARCHITECTURE')}`](./{Path(rel_doc('SYSTEM_ARCHITECTURE')).name}) (`{doc_id_of('SYSTEM_ARCHITECTURE')}`)",
        f"- **权威技术设计入口**：[`{rel_doc('TECHNICAL_DESIGN')}`](./{Path(rel_doc('TECHNICAL_DESIGN')).name}) (`{doc_id_of('TECHNICAL_DESIGN')}`)",
        owned_bullets,
        ro_bullets,
        "",
        "## 5. 接口契约入口 (`api_contract_entrypoints`)",
        f"- **权威接口契约入口**：[`{rel_doc('API_CONTRACT')}`](./{Path(rel_doc('API_CONTRACT')).name}) (`{doc_id_of('API_CONTRACT')}`)",
        api_bullets,
        "",
        "## 6. 已批准 ADR (`approved_adrs`)",
        f"- **权威决策记录入口**：[`{rel_doc('DECISION_RECORD')}`](./{Path(rel_doc('DECISION_RECORD')).name}) (`{doc_id_of('DECISION_RECORD')}`)",
        "",
        "| 决策编号 | 决策摘要 | 审批状态 | 权威来源 |",
        "|:---|:---|:---|:---|",
        adr_rows,
        "",
        "## 7. 当前 Standards 锁定 (`standards_lock`)",
        f"- **锁定文件**：`standards.lock.json`",
        f"- **规范仓库 (`repository`)**：`{baseline_payload['standards_lock']['repository']}`",
        f"- **锁定基线版本 (`version`)**：`{baseline_payload['standards_lock']['version']}`",
        f"- **锁定正式 Tag (`tag`)**：`{baseline_payload['standards_lock']['tag']}`",
        f"- **Tag Object SHA (`tag_object_sha`)**：`{baseline_payload['standards_lock']['tag_object_sha']}`",
        f"- **Peeled Commit (`peeled_commit`)**：`{baseline_payload['standards_lock']['peeled_commit']}`",
        f"- **核验状态 (`verification_status`)**：`{baseline_payload['standards_lock']['verification_status']}`",
        "",
        "## 8. Git 分支及 Commit 身份 (`git_identity`)",
        f"- **当前分支 (`branch`)**：`{branch_name}`",
        f"- **本地 HEAD (`local_head`)**：`{local_head}`",
        f"- **远端 main (`remote_main_head`)**：`{remote_main_head}`",
        f"- **工作区干净状态 (`worktree_clean`)**：`{str(worktree_clean).lower() if worktree_clean is not None else 'NOT_VERIFIABLE'}`",
        f"- **核验状态 (`verification_status`)**：`{baseline_payload['git_identity']['verification_status']}`",
        "",
        "## 9. 最近 CI 事实 (`recent_ci_facts`)",
        f"- **核验状态 (`verification_status`)**：`{ci_fact['verification_status']}`",
        f"- **工作流路径 (`source_path`)**：`{ci_fact['source_path']}`",
        f"- **1. 基线生成源 Commit (`source_commit`)**：`{ci_fact['source_commit']}`",
        f"- **2. Git 快照观测时间 (`git_snapshot_observed_at`)**：`{ci_fact['observed_at']}`（有效时效：24 小时；快照状态：`FRESH`）",
        f"- **3. 最近一次已验证 CI Commit (`last_verified_ci_commit`)**：`{ci_fact['details'].get('last_verified_ci_commit', verified_ci)}`",
        f"- **4. 代码候选 Commit (`candidate_commit`)**：`{ci_fact['details'].get('candidate_commit', code_candidate_commit)}`",
        f"- **5. 文档快照 Commit (`snapshot_commit`)**：`{ci_fact['details'].get('snapshot_commit', snapshot_commit)}`",
        f"- **6. 当前待验证事项 (`pending_verifications`)**：{ci_fact['details'].get('pending_verifications')}",
        "- **7. 历史 CI 记录 (`historical_ci_runs`)**：",
    ])
    for hr in ci_fact["details"].get("historical_ci_runs", []):
        md_lines.append(f"  - {hr}")
    md_lines.extend([
        f"- **证据引用 (`evidence_ref`)**：`{ci_fact['evidence_ref']}`",
        f"- **观测时间 (`observed_at`)**：`{ci_fact['observed_at']}`",
        f"- **事实说明**：{ci_fact['summary']}",
    ])
    if project_id == "ai-engineering-standards" and std_pr9_ev and std_snap_ev and std_019_ev:
        md_lines.extend([
            "",
            "### 9.1 PR9 历史发布证据 (PR9_HISTORICAL_RELEASE_EVIDENCE)",
            "- **核验状态 (`verification_status`)**：`PASS`",
            f"- **代码候选 Commit (`candidate_commit`)**：`{std_pr9_ev['candidate_commit']}`",
            f"- **文档快照 Commit (`snapshot_commit`)**：`{std_pr9_ev['snapshot_commit']}`",
            f"- **最近一次已验证 CI Commit (`last_verified_ci_commit`)**：`{std_pr9_ev['last_verified_ci_commit']}`",
            f"- **Push Run ID**：`{std_pr9_ev['push_run_id']}`",
            f"- **PR Run ID**：`{std_pr9_ev['pr_run_id']}`",
            f"- **PR 编号与状态**：PR #{std_pr9_ev['pr_number']}（状态：`{std_pr9_ev['pr_status']}`）",
            f"- **主干 HEAD (`main_head`)**：`{std_pr9_ev['main_head']}`",
            f"- **测试用例数**：`{std_pr9_ev['test_count']} tests PASS`（Run {std_pr9_ev['push_run_id']} Push / Run {std_pr9_ev['pr_run_id']} PR #{std_pr9_ev['pr_number']} 双平台全绿，{std_pr9_ev['test_count']} tests PASS）",
            f"- **发布流程状态 (`release_flow_status`)**：`{std_pr9_ev['release_flow_status']}`",
            f"- **旧 Tag 删除状态**：`OLD_TAG_DELETED={str(std_pr9_ev.get('old_tag_deleted', True)).lower()}`",
            "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
            f"- **事实说明**：PR CI 已通过 (Run: {std_pr9_ev['push_run_id']} Push / {std_pr9_ev['pr_run_id']} PR #{std_pr9_ev['pr_number']} 双平台全绿，{std_pr9_ev['test_count']} tests PASS)，PR #{std_pr9_ev['pr_number']} 已合入 main，等待修复 main CI 后重建 Tag",
            "",
            "### 9.2 Std-018 历史工程快照 (STD018_CURRENT_SNAPSHOT)",
            "- **核验状态 (`verification_status`)**：`PASS`",
            f"- **任务编号 (`task_id`)**：`{std_snap_ev.get('task_id', 'Std-018-V3-0-0-REISSUE-CURRENT-BASELINE-HANDOFF-ALIGNMENT')}`",
            f"- **当前工程候选 Commit (`candidate_commit`)**：`{std_snap_ev['candidate_commit']}`",
            f"- **当前文档快照 Commit (`snapshot_commit`)**：`{std_snap_ev['snapshot_commit']}`",
            f"- **最新已验证 CI Commit (`last_verified_ci_commit`)**：`{std_snap_ev['last_verified_ci_commit']}`",
            f"- **Push Run ID**：`{std_snap_ev['push_run_id']}`",
            f"- **PR Run ID**：`{std_snap_ev['pr_run_id']}`",
            f"- **PR 编号与状态**：PR #{std_snap_ev['pr_number']}（状态：`{std_snap_ev['pr_status']}`）",
            f"- **主干 HEAD (`main_head`)**：`{std_snap_ev['main_head']}`",
            f"- **测试用例数**：`{std_snap_ev['test_count']} tests PASS`（Run {std_snap_ev['push_run_id']} Push / Run {std_snap_ev['pr_run_id']} PR #{std_snap_ev['pr_number']} 双平台全绿，{std_snap_ev['test_count']} tests PASS）",
            f"- **发布流程状态 (`release_flow_status`)**：`{std_snap_ev['release_flow_status']}`",
            f"- **旧 Tag 删除状态**：`OLD_TAG_DELETED={str(std_snap_ev.get('old_tag_deleted', True)).lower()}`",
            "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
            "- **当前待验证事项 (`pending_verifications`)**：PR CI 已通过，等待合并及 main CI 和 Tag 重建。",
            "- **历史 CI 记录 (`historical_ci_runs`)**：",
            "  - Run 42983601133 (Push @ 21939da, conclusion: success, Windows/Ubuntu PASS, 221 tests)",
            "  - Run 42983609802 (PR #10 @ 21939da, conclusion: success, Windows/Ubuntu PASS, 221 tests)",
            f"- **事实说明**：PR CI 已通过 (Run: {std_snap_ev['push_run_id']} Push / {std_snap_ev['pr_run_id']} PR #{std_snap_ev['pr_number']} 双平台全绿，{std_snap_ev['test_count']} tests PASS)，PR #{std_snap_ev['pr_number']} 待 ChatGPT 独立复核及 Owner 批准合入 main 后重建 Tag",
            "",
            "### 9.3 Std-019 最终发布证据 (STD019_FINAL_RELEASE)",
            "- **核验状态 (`verification_status`)**：`PASS`",
            f"- **任务编号 (`task_id`)**：`{std_019_ev.get('task_id', 'Std-019-V3-0-0-POST-RELEASE-CLOSEOUT')}`",
            f"- **正式发布 Tag (`release_tag`)**：`{std_019_ev['release_tag']}`",
            f"- **Tag Object SHA (`tag_object_sha`)**：`{std_019_ev['tag_object_sha']}`",
            f"- **Peeled Commit (`peeled_commit`)**：`{std_019_ev['peeled_commit']}`",
            f"- **代码候选 Commit (`candidate_commit`)**：`{std_019_ev['candidate_commit']}`",
            f"- **文档快照 Commit (`snapshot_commit`)**：`{std_019_ev['snapshot_commit']}`",
            f"- **最新已验证 CI Commit (`last_verified_ci_commit`)**：`{std_019_ev['last_verified_ci_commit']}`",
            f"- **Push Run ID**：`{std_019_ev.get('main_ci_run_id') or std_019_ev['push_run_id']}`",
            f"- **PR Run ID**：`{std_019_ev['pr_run_id']}`",
            f"- **PR 编号与状态**：PR #{std_019_ev['pr_number']}（状态：`{std_019_ev['pr_status']}`）",
            f"- **PR 合并者 (`pr_merged_by`)**：`{std_019_ev['pr_merged_by']}`",
            f"- **发布时 main HEAD (`main_head`)**：`{std_019_ev['main_head']}`",
            f"- **测试用例数**：`{std_019_ev['test_count']} tests PASS`（Run {std_019_ev.get('main_ci_run_id') or std_019_ev['push_run_id']} main CI 双平台全绿，Tag Publish Job 成功）",
            f"- **Tag 发布状态 (`tag_publish_status`)**：`{std_019_ev['tag_publish_status']}`",
            f"- **发布流程状态 (`release_flow_status`)**：`{std_019_ev['release_flow_status']}`",
            f"- **旧 Tag 删除状态**：`OLD_TAG_DELETED={str(std_019_ev.get('old_tag_deleted', True)).lower()}`",
            "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
            f"- **事实说明**：PR #{std_019_ev['pr_number']} 已由 {std_019_ev['pr_merged_by']} 合入 main，main CI Run {std_019_ev.get('main_ci_run_id') or std_019_ev['push_run_id']} 双平台全绿（{std_019_ev['test_count']} tests PASS），Tag Publish Job 成功发布正式 Annotated Tag {std_019_ev['release_tag']}",
        ])
        if std_active_ev and str(std_active_ev.get("version", "")).lstrip("v") != str(std_019_ev.get("version", "")).lstrip("v"):
            md_lines.extend([
                "",
                "### 9.4 Std-020 最终发布证据 (STD020_FINAL_RELEASE)",
                "- **核验状态 (`verification_status`)**：`PASS`",
                f"- **任务编号 (`task_id`)**：`{std_active_ev.get('task_id', 'Std-020-CONSUMER-FEEDBACK-TOOLCHAIN-REMEDIATION')}`",
                f"- **正式发布 Tag (`release_tag`)**：`{std_active_ev.get('release_tag', 'v' + str(std_active_ev.get('version', '')))}`",
                f"- **Tag Object SHA (`tag_object_sha`)**：`{std_active_ev.get('tag_object_sha')}`",
                f"- **Peeled Commit (`peeled_commit`)**：`{std_active_ev.get('peeled_commit')}`",
                f"- **代码候选 Commit (`candidate_commit`)**：`{std_active_ev['candidate_commit']}`",
                f"- **文档快照 Commit (`snapshot_commit`)**：`{std_active_ev['snapshot_commit']}`",
                f"- **最新已验证 CI Commit (`last_verified_ci_commit`)**：`{std_active_ev['last_verified_ci_commit']}`",
                f"- **Push Run ID**：`{std_active_ev.get('main_ci_run_id') or std_active_ev['push_run_id']}`",
                f"- **PR Run ID**：`{std_active_ev['pr_run_id']}`",
                f"- **PR 编号与状态**：PR #{std_active_ev['pr_number']}（状态：`{std_active_ev['pr_status']}`）",
                f"- **PR 合并者 (`pr_merged_by`)**：`{std_active_ev.get('pr_merged_by')}`",
                f"- **发布时 main HEAD (`main_head`)**：`{std_active_ev['main_head']}`",
                f"- **测试用例数**：`{std_active_ev['test_count']} tests PASS`",
                f"- **Tag 发布状态 (`tag_publish_status`)**：`{std_active_ev.get('tag_publish_status')}`",
                f"- **发布流程状态 (`release_flow_status`)**：`{std_active_ev['release_flow_status']}`",
                "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
            ])
    md_lines.extend([
        "",
        "## 10. 最近 Build 事实 (`recent_build_facts`)",
        f"- **核验状态 (`verification_status`)**：`{build_fact['verification_status']}`",
        f"- **来源路径 (`source_path`)**：`{build_fact['source_path']}`",
        f"- **来源 Commit (`source_commit`)**：`{build_fact['source_commit']}`",
        f"- **证据引用 (`evidence_ref`)**：`{build_fact['evidence_ref']}`",
        f"- **观测时间 (`observed_at`)**：`{build_fact['observed_at']}`",
        f"- **事实说明**：{build_fact['summary']}",
        "",
        "## 11. Runtime 核验事实 (`runtime_verification_facts`)",
        f"- **核验状态 (`verification_status`)**：`{runtime_fact['verification_status']}`",
        f"- **来源路径 (`source_path`)**：`{runtime_fact['source_path']}`",
        f"- **来源 Commit (`source_commit`)**：`{runtime_fact['source_commit']}`",
        f"- **证据引用 (`evidence_ref`)**：`{runtime_fact['evidence_ref']}`",
        f"- **观测时间 (`observed_at`)**：`{runtime_fact['observed_at']}`",
        f"- **事实说明**：{runtime_fact['summary']}",
        "",
        "## 12. 测试和验收事实 (`test_and_acceptance_facts`)",
        f"- **权威原型与交互规范入口**：[`{rel_doc('PROTOTYPE_UX')}`](./{Path(rel_doc('PROTOTYPE_UX')).name}) (`{doc_id_of('PROTOTYPE_UX')}`)",
        f"- **权威测试基线入口**：[`{rel_doc('TEST_ACCEPTANCE')}`](./{Path(rel_doc('TEST_ACCEPTANCE')).name}) (`{doc_id_of('TEST_ACCEPTANCE')}`)",
        f"- **权威发布运维入口**：[`{rel_doc('RELEASE_OPERATIONS')}`](./{Path(rel_doc('RELEASE_OPERATIONS')).name}) (`{doc_id_of('RELEASE_OPERATIONS')}`)",
        f"- **权威文档总索引入口**：[`{rel_doc('DOCUMENT_INDEX')}`](./{Path(rel_doc('DOCUMENT_INDEX')).name}) (`{doc_id_of('DOCUMENT_INDEX')}`)",
        f"- **权威跨会话交接入口**：[`{rel_doc('CROSS_SESSION_HANDOFF')}`](./{Path(rel_doc('CROSS_SESSION_HANDOFF')).name}) (`{doc_id_of('CROSS_SESSION_HANDOFF')}`)",
        f"- **核验状态 (`verification_status`)**：`{test_fact['verification_status']}`",
        f"- **证据引用 (`evidence_ref`)**：`{test_fact['evidence_ref']}`",
        f"- **观测时间 (`observed_at`)**：`{test_fact['observed_at']}`",
        f"- **事实说明**：{test_fact['summary']}",
        "",
        "## 13. 未决问题 (`open_issues`)",
        "| 问题 ID | 问题描述 | 当前状态 |",
        "|:---|:---|:---|",
        issue_rows,
        "",
        "## 14. 待审批事项 (`pending_approvals`)",
        "| 事项 ID | 待审批内容 | 要求审批方 | 当前状态 |",
        "|:---|:---|:---|:---|",
        approval_rows,
        "",
        "## 15. 证据来源 (`evidence_sources`)",
        "| 仓库 (`repository`) | 来源路径 (`source_path`) | 来源 Commit (`source_commit`) | 证据引用 (`evidence_ref`) | 观测时间 (`observed_at`) | 核验状态 (`verification_status`) |",
        "|:---|:---|:---|:---|:---|:---|",
        ev_rows,
        "",
        "## 16. 来源 Commit (`source_commit`)",
        f"- `{source_commit}`",
        "",
        "## 17. 核验时间 (`verified_at`)",
        f"- `{now_iso}`",
        "",
        "## 18. 内容摘要 (`content_sha256`)",
        "- 机器可读结构化摘要见 `.artifacts/baseline/engineering_baseline.json`；本 Markdown 文档的规范摘要记录在 Frontmatter `content_sha256`。",
        "",
    ])
    cand_pr_num_display = str(eff_cand_pr_number) if eff_cand_pr_number is not None else "NOT_ASSIGNED"
    section19_lines = [
        "",
        "## 19. 当前候选状态与消费端试点 (CURRENT_CANDIDATE_PR)",
        "",
        f"- **候选版本 (`candidate_version`)**：`{version_str}`",
        f"- **当前候选 PR 编号 (`candidate_pr_number`)**：`{cand_pr_num_display}`",
        f"- **当前候选 PR 状态 (`candidate_pr_status`)**：`{effective_pr_status}`",
        f"- **PR 状态标记 (`PR_STATE`)**：`{pr_state_str}`",
        f"- **PR 草稿标记 (`PR_DRAFT`)**：`{str(pr_draft_bool).lower()}`",
        f"- **当前候选 PR Base (`candidate_pr_base`)**：`{eff_cand_pr_base}`",
        f"- **当前候选 Commit (`candidate_commit`)**：`{code_candidate_commit}`",
        "- **实时 PR HEAD 核验方式 (`live_pr_head_verification`)**：`GITHUB_PR_API_REQUIRED`（通过 GitHub PR API / Actions Event 在线核验 `candidate_commit` 为实时 PR HEAD 祖先，不自引用静态写入）",
        "- **实时 CI 运行记录方式 (`ci_runtime_record`)**：`GITHUB_STEP_SUMMARY`（实时 PR HEAD 与 CI Run ID 由 CI Runtime 与 Step Summary 记录）",
        f"- **状态快照观测时间 (`candidate_observed_at`)**：`{now_iso}`",
        f"- **当前发布状态 (`RELEASE_STATUS`)**：`{release_status_str}`",
    ]
    if effective_pr_status == "MERGED" and verified_merge_commit and verified_merged_by:
        section19_lines.extend([
            f"- **当前候选 PR Merge Commit (`candidate_pr_merge_commit`)**：`{verified_merge_commit}`",
            f"- **当前候选 PR 合并者 (`candidate_pr_merged_by`)**：`{verified_merged_by}`",
            f"- 当前候选版本：`{version_str}`；{pr_label}（状态：`MERGED`）已由 `{verified_merged_by}` 合入官方 `{eff_cand_pr_base}`（Merge Commit: `{verified_merge_commit}`）。",
        ])
    else:
        section19_lines.append(
            f"- 当前候选版本：`{version_str}`；{pr_label}（状态：`{effective_pr_status}`，`PR_STATE={pr_state_str}`，`PR_DRAFT={str(pr_draft_bool).lower()}`）尚未合入官方 `{eff_cand_pr_base}`，尚未创建正式 `v{version_str}` Tag。"
        )
    section19_lines.extend([
        "- 正式发布版本必须以官方 main 上的 Annotated Tag、Tag Object SHA、Peeled Commit 与 main CI 为准；严禁依赖 GitHub /releases/latest REST API 对象。",
        "- **消费端首个试点**：AI-Engineering-Hub；AI-KB、VTIP、SideCar 不在本轮试点范围，是否接入由各工程 Owner 后续决定。",
        "- **审批状态**：保持 `IN_REVIEW`，严禁智能体自批或伪造 `OWNER_APPROVED`。",
    ])
    md_lines.extend(section19_lines)
    markdown_text = "\n".join(md_lines)
    # Also update frontmatter content_sha256 using compute_canonical_document_sha256
    canonical_doc_sha = compute_canonical_document_sha256(markdown_text)
    markdown_text = markdown_text.replace(f'content_sha256: "{content_sha}"', f'content_sha256: "{canonical_doc_sha}"')
    return True, [], baseline_payload, markdown_text


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or verify STD-035 ENGINEERING_BASELINE (docs/当前权威基线.md)")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--standards-root", default=None, help="Path to AI-Engineering-Standards root")
    parser.add_argument("--output", default=None, help="Output markdown path (default: docs/当前权威基线.md)")
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional output path for machine-readable baseline JSON (default: .artifacts/baseline/engineering_baseline.json)",
    )
    parser.add_argument("--observed-at", default=None, help="Fixed ISO-8601 UTC timestamp for deterministic testing")
    parser.add_argument("--source-commit", default=None, help="Override source commit SHA")
    parser.add_argument("--candidate-commit", default=None, help="Override candidate commit SHA")
    parser.add_argument("--snapshot-commit", default=None, help="Override snapshot commit SHA")
    parser.add_argument("--last-verified-ci-commit", default=None, help="Override last verified CI commit SHA")
    parser.add_argument("--ci-commit", default=None, help="Explicit CI tested commit SHA")
    parser.add_argument("--ci-status", default=None, help="CI verification status (PASS, NOT_VERIFIABLE, etc.)")
    parser.add_argument("--ci-run-id", default=None, help="GitHub Actions CI Run ID")
    parser.add_argument("--push-run-id", default=None, help="Push CI Run ID")
    parser.add_argument("--pr-run-id", default=None, help="PR CI Run ID")
    parser.add_argument("--ci-evidence-ref", default=None, help="CI evidence reference file")
    parser.add_argument("--ci-summary", default=None, help="CI fact summary")
    parser.add_argument("--pending-verifications", default=None, help="Pending verifications statement")
    parser.add_argument("--test-count", type=int, default=None, help="Expected test count for verification")
    parser.add_argument("--pr-status", default=None, help="Legacy alias for --candidate-pr-status (DRAFT, OPEN, MERGED, CLOSED)")
    parser.add_argument("--pr-number", type=int, default=None, help="Legacy alias for --candidate-pr-number")
    parser.add_argument("--candidate-pr-number", type=int, default=None, help="Current candidate PR number (decoupled from historical evidence)")
    parser.add_argument("--candidate-pr-status", default=None, help="Current candidate PR status (DRAFT, OPEN, MERGED, CLOSED)")
    parser.add_argument("--candidate-pr-head", default=None, help="Current candidate PR HEAD commit SHA")
    parser.add_argument("--candidate-pr-base", default=None, help="Current candidate PR base branch (must be 'main')")
    parser.add_argument("--candidate-pr-draft", choices=["true", "false"], default=None, help="Current candidate PR draft flag (true/false)")
    parser.add_argument("--candidate-pr-merge-event", default=None, help="Path to GitHub PR API JSON proving verified merge event")
    parser.add_argument("--old-tag-deleted", default=None, help="Expected old tag deleted state (true/false)")
    parser.add_argument("--release-evidence", default=None, help="Path to PR9 release evidence JSON file")
    parser.add_argument("--snapshot-evidence", default=None, help="Path to snapshot evidence JSON file")
    parser.add_argument("--final-evidence", default=None, help="Path to final release evidence JSON file (Std-019)")
    parser.add_argument(
        "--scope",
        choices=["consumer", "standards-release"],
        default=None,
        help="Validation scope: 'consumer' verifies project baseline facts without Standards PR release evidence; 'standards-release' verifies Standards release evidence.",
    )
    parser.add_argument("--verify-only", action="store_true", help="Verify generation succeeds against committed baseline")
    parser.add_argument(
        "--require-live-pr",
        action="store_true",
        help="Require real GitHub PR API verification to succeed (blocks if API unavailable)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    standards_root = resolve_standards_root(args.standards_root)
    old_tag_deleted_val = (
        (str(args.old_tag_deleted).lower() == "true")
        if args.old_tag_deleted is not None
        else True
    )
    candidate_pr_draft_val: Optional[bool] = (
        (args.candidate_pr_draft == "true") if args.candidate_pr_draft is not None else None
    )
    candidate_pr_merge_event_obj: Optional[Dict[str, Any]] = None
    if args.candidate_pr_merge_event:
        me_path = Path(args.candidate_pr_merge_event)
        if not me_path.is_absolute():
            me_path = (project_root / me_path).resolve()
        try:
            candidate_pr_merge_event_obj = json.loads(me_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[FAIL] Failed to load --candidate-pr-merge-event '{me_path}': {exc}")
            sys.exit(1)

    effective_observed_at = args.observed_at
    if effective_observed_at is None and not args.verify_only:
        effective_observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cli_allow_offline = not bool(
        args.require_live_pr
        or (not args.verify_only and str(args.candidate_pr_status or args.pr_status or "").strip().upper() == "MERGED")
    )
    ok, errors, payload, md_text = build_engineering_baseline(
        project_root=project_root,
        standards_root=standards_root,
        observed_at=effective_observed_at,
        source_commit_override=args.source_commit,
        candidate_commit_override=args.candidate_commit,
        snapshot_commit_override=args.snapshot_commit,
        last_verified_ci_commit=args.last_verified_ci_commit,
        ci_commit=args.ci_commit,
        ci_status=args.ci_status,
        ci_run_id=args.ci_run_id,
        push_run_id=args.push_run_id,
        pr_run_id=args.pr_run_id,
        test_count=args.test_count,
        pr_status=args.pr_status,
        pr_number=args.pr_number,
        candidate_pr_number=args.candidate_pr_number,
        candidate_pr_status=args.candidate_pr_status,
        candidate_pr_head=args.candidate_pr_head,
        candidate_pr_base=args.candidate_pr_base,
        candidate_pr_draft=candidate_pr_draft_val,
        candidate_pr_merge_event=candidate_pr_merge_event_obj,
        old_tag_deleted=old_tag_deleted_val,
        ci_evidence_ref=args.ci_evidence_ref,
        ci_summary=args.ci_summary,
        pending_verifications=args.pending_verifications,
        release_evidence_path=args.release_evidence,
        snapshot_evidence_path=args.snapshot_evidence,
        final_evidence_path=args.final_evidence,
        allow_offline=cli_allow_offline,
    )
    if not ok or payload is None or md_text is None:
        print(f"[FAIL] Engineering baseline generation blocked ({len(errors)} issues):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    out_md = Path(args.output).resolve() if args.output else project_root / "docs" / "当前权威基线.md"

    if args.verify_only:
        if not out_md.exists():
            print(f"[FAIL] Committed engineering baseline file does not exist: {out_md}")
            sys.exit(1)
        actual_content = out_md.read_text(encoding="utf-8")
        actual_fm, _ = extract_frontmatter_and_body(actual_content)
        if not actual_fm:
            print(f"[FAIL] Committed baseline has invalid YAML frontmatter: {out_md}")
            sys.exit(1)

        expected_fm, _ = extract_frontmatter_and_body(md_text)
        # Compare core fields
        mismatches: List[str] = []
        for fld in ("document_id", "document_type", "project_id", "status", "approval_status", "source_commit"):
            if actual_fm.get(fld) != expected_fm.get(fld):
                mismatches.append(f"field '{fld}': committed='{actual_fm.get(fld)}' != generated='{expected_fm.get(fld)}'")

        actual_digest = compute_canonical_document_sha256(actual_content)
        if actual_fm.get("content_sha256") != actual_digest:
            mismatches.append(
                f"field 'content_sha256': committed='{actual_fm.get('content_sha256')}' does not match actual document digest '{actual_digest}'"
            )

        # Determine effective scope: if not explicitly specified, default to standards-release
        # only when verifying AI-Engineering-Standards repo where reissue evidence exists; otherwise consumer.
        effective_scope = args.scope
        if not effective_scope:
            proj_id = payload.get("project_identity", {}).get("project_id", "")
            if proj_id == "ai-engineering-standards" and (project_root / "docs" / "release-evidence" / "v3.0.0-reissue.json").exists():
                effective_scope = "standards-release"
            else:
                effective_scope = "consumer"

        # Semantic fact verification from independent release evidence (STD-034 / STD-035)
        # In standards-release scope (or when explicit release evidence is passed), verify PR9, STD018, and STD019 facts.
        # In consumer scope, skip Standards release evidence verification.
        if effective_scope == "standards-release" or args.release_evidence or args.snapshot_evidence or args.final_evidence:
            pr9_ev_path = (
                Path(args.release_evidence).resolve()
                if args.release_evidence
                else project_root / "docs" / "release-evidence" / "v3.0.0-reissue.json"
            )
            ok_ev, ev_errors, release_evidence = load_release_evidence(project_root, pr9_ev_path)
            if not ok_ev or release_evidence is None:
                print(f"[FAIL] Baseline verification blocked: PR9 release evidence error ({len(ev_errors)} issues):")
                for e in ev_errors:
                    print(f"  - {e}")
                sys.exit(1)

            snapshot_ev_path = (
                Path(args.snapshot_evidence).resolve()
                if args.snapshot_evidence
                else project_root / "docs" / "release-evidence" / "std018-current-snapshot.json"
            )
            ok_snap, snap_errors, snapshot_evidence = load_release_evidence(project_root, snapshot_ev_path)
            if not ok_snap or snapshot_evidence is None:
                print(f"[FAIL] Baseline verification blocked: snapshot evidence error ({len(snap_errors)} issues):")
                for e in snap_errors:
                    print(f"  - {e}")
                sys.exit(1)

            final_ev_path = (
                Path(args.final_evidence).resolve()
                if args.final_evidence
                else project_root / "docs" / "release-evidence" / "std019-final-release.json"
            )
            ok_final, final_errors, final_evidence = load_release_evidence(project_root, final_ev_path)
            if not ok_final or final_evidence is None:
                print(f"[FAIL] Baseline verification blocked: final release evidence error ({len(final_errors)} issues):")
                for e in final_errors:
                    print(f"  - {e}")
                sys.exit(1)

            expected_pr9_facts = {
                "candidate_commit": release_evidence["candidate_commit"],
                "snapshot_commit": release_evidence["snapshot_commit"],
                "last_verified_ci_commit": release_evidence["last_verified_ci_commit"],
                "ci_run_id": release_evidence["push_run_id"],
                "push_run_id": release_evidence["push_run_id"],
                "pr_run_id": release_evidence["pr_run_id"],
                "ci_commit": release_evidence["last_verified_ci_commit"],
                "ci_status": release_evidence["ci_status"],
                "test_count": release_evidence["test_count"],
                "pr_status": release_evidence["pr_status"],
                "main_head": release_evidence.get("main_head"),
                "release_flow_status": release_evidence["release_flow_status"],
                "old_tag_deleted": release_evidence["old_tag_deleted"],
            }
            pr9_mismatches = verify_baseline_semantic_facts(
                actual_content, expected_pr9_facts, scope="PR9_HISTORICAL_RELEASE_EVIDENCE"
            )
            mismatches.extend([f"[PR9_SCOPE] {m}" for m in pr9_mismatches])

            expected_snapshot_facts = {
                "task_id": snapshot_evidence.get("task_id", "Std-018-V3-0-0-REISSUE-CURRENT-BASELINE-HANDOFF-ALIGNMENT"),
                "candidate_commit": snapshot_evidence["candidate_commit"],
                "snapshot_commit": snapshot_evidence["snapshot_commit"],
                "last_verified_ci_commit": snapshot_evidence["last_verified_ci_commit"],
                "ci_run_id": snapshot_evidence["push_run_id"],
                "push_run_id": snapshot_evidence["push_run_id"],
                "pr_run_id": snapshot_evidence["pr_run_id"],
                "ci_commit": snapshot_evidence["last_verified_ci_commit"],
                "ci_status": snapshot_evidence["ci_status"],
                "test_count": snapshot_evidence["test_count"],
                "pr_status": snapshot_evidence["pr_status"],
                "main_head": snapshot_evidence.get("main_head"),
                "release_flow_status": snapshot_evidence["release_flow_status"],
                "old_tag_deleted": snapshot_evidence["old_tag_deleted"],
            }
            snap_mismatches = verify_baseline_semantic_facts(
                actual_content, expected_snapshot_facts, scope="STD018_CURRENT_SNAPSHOT"
            )
            mismatches.extend([f"[STD018_SCOPE] {m}" for m in snap_mismatches])

            expected_final_facts = {
                "task_id": final_evidence.get("task_id", "Std-019-V3-0-0-POST-RELEASE-CLOSEOUT"),
                "candidate_commit": final_evidence["candidate_commit"],
                "snapshot_commit": final_evidence["snapshot_commit"],
                "last_verified_ci_commit": final_evidence["last_verified_ci_commit"],
                "push_run_id": final_evidence.get("main_ci_run_id") or final_evidence["push_run_id"],
                "pr_run_id": final_evidence["pr_run_id"],
                "ci_status": final_evidence["ci_status"],
                "test_count": final_evidence["test_count"],
                "pr_number": final_evidence["pr_number"],
                "pr_status": final_evidence["pr_status"],
                "main_head": final_evidence["main_head"],
                "release_flow_status": final_evidence["release_flow_status"],
                "old_tag_deleted": final_evidence["old_tag_deleted"],
                "release_tag": final_evidence["release_tag"],
                "tag_object_sha": final_evidence["tag_object_sha"],
                "peeled_commit": final_evidence["peeled_commit"],
                "tag_publish_status": final_evidence["tag_publish_status"],
                "pr_merged_by": final_evidence["pr_merged_by"],
            }
            final_mismatches = verify_baseline_semantic_facts(
                actual_content, expected_final_facts, scope="STD019_FINAL_RELEASE"
            )
            mismatches.extend([f"[STD019_SCOPE] {m}" for m in final_mismatches])

            if not args.final_evidence:
                active_ev_path = resolve_release_evidence_path(project_root)
                if active_ev_path.resolve() != final_ev_path.resolve():
                    ok_act, act_errors, act_ev = load_release_evidence(project_root, active_ev_path)
                    if not ok_act or act_ev is None:
                        print(f"[FAIL] Baseline verification blocked: active release evidence error ({len(act_errors)} issues):")
                        for e in act_errors:
                            print(f"  - {e}")
                        sys.exit(1)
                    expected_active_facts = {
                        "task_id": act_ev.get("task_id", "Std-020-CONSUMER-FEEDBACK-TOOLCHAIN-REMEDIATION"),
                        "candidate_commit": act_ev["candidate_commit"],
                        "snapshot_commit": act_ev["snapshot_commit"],
                        "last_verified_ci_commit": act_ev["last_verified_ci_commit"],
                        "push_run_id": act_ev.get("main_ci_run_id") or act_ev["push_run_id"],
                        "pr_run_id": act_ev["pr_run_id"],
                        "ci_status": act_ev["ci_status"],
                        "test_count": act_ev["test_count"],
                        "pr_number": act_ev["pr_number"],
                        "pr_status": act_ev["pr_status"],
                        "main_head": act_ev["main_head"],
                        "release_flow_status": act_ev["release_flow_status"],
                        "release_tag": act_ev.get("release_tag"),
                        "tag_object_sha": act_ev.get("tag_object_sha"),
                        "peeled_commit": act_ev.get("peeled_commit"),
                        "tag_publish_status": act_ev.get("tag_publish_status"),
                        "pr_merged_by": act_ev.get("pr_merged_by"),
                    }
                    act_mismatches = verify_baseline_semantic_facts(
                        actual_content, expected_active_facts, scope="STD020_FINAL_RELEASE"
                    )
                    mismatches.extend([f"[STD020_SCOPE] {m}" for m in act_mismatches])

            # Verify current candidate PR identity independently from historical PR9/STD018/STD019 scopes
            hist_merge_shas: set[str] = set()
            hist_cand_shas: set[str] = set()
            for hev in (release_evidence, snapshot_evidence, final_evidence):
                if isinstance(hev, dict):
                    for k in ("main_head", "peeled_commit"):
                        v = str(hev.get(k) or "").strip()
                        if re.fullmatch(r"[0-9a-f]{40}", v):
                            hist_merge_shas.add(v)
                    cv = str(hev.get("candidate_commit") or "").strip()
                    if re.fullmatch(r"[0-9a-f]{40}", cv):
                        hist_cand_shas.add(cv)

            exp_cand_pr_facts: Dict[str, Any] = {}
            exp_pr_num_cli = args.candidate_pr_number if args.candidate_pr_number is not None else args.pr_number
            exp_pr_st_cli = args.candidate_pr_status if args.candidate_pr_status is not None else args.pr_status
            if exp_pr_num_cli is not None:
                exp_cand_pr_facts["candidate_pr_number"] = exp_pr_num_cli
            if exp_pr_st_cli is not None:
                exp_cand_pr_facts["candidate_pr_status"] = str(exp_pr_st_cli).strip().upper()
            if args.candidate_pr_head is not None:
                exp_cand_pr_facts["candidate_pr_head"] = args.candidate_pr_head.strip()
            if args.candidate_pr_base is not None:
                exp_cand_pr_facts["candidate_pr_base"] = args.candidate_pr_base.strip()
            if candidate_pr_draft_val is not None:
                exp_cand_pr_facts["pr_draft"] = candidate_pr_draft_val
            if args.candidate_commit is not None:
                exp_cand_pr_facts["candidate_commit"] = args.candidate_commit.strip()
            if args.push_run_id is not None:
                exp_cand_pr_facts["candidate_push_run_id"] = str(args.push_run_id).strip()
            if args.pr_run_id is not None:
                exp_cand_pr_facts["candidate_pr_run_id"] = str(args.pr_run_id).strip()

            is_cur_ver_rel = bool(
                str(final_evidence.get("version", "")).lstrip("v") == payload["product_version"]["version"]
                and final_evidence.get("release_flow_status") == "RELEASED"
            )
            if not is_cur_ver_rel and not args.final_evidence:
                _act_p = resolve_release_evidence_path(project_root)
                if _act_p.is_file():
                    _ok_a2, _, _ev_a2 = load_release_evidence(project_root, _act_p)
                    if _ok_a2 and _ev_a2 and str(_ev_a2.get("version", "")).lstrip("v") == payload["product_version"]["version"] and _ev_a2.get("release_flow_status") == "RELEASED":
                        is_cur_ver_rel = True

            cand_pr_mismatches, live_pr_details, live_pr_status = verify_current_candidate_pr_facts(
                content=actual_content,
                version_str=payload["product_version"]["version"],
                repository=payload["project_identity"]["repository"],
                project_root=project_root,
                historical_merge_commits=hist_merge_shas,
                historical_candidate_commits=hist_cand_shas,
                expected_facts=exp_cand_pr_facts or None,
                verify_live_pr=True,
                require_live_pr=bool(args.require_live_pr or os.environ.get("GITHUB_ACTIONS") == "true"),
                is_current_version_released=is_cur_ver_rel,
                return_details=True,
            )
            mismatches.extend([f"[CURRENT_CANDIDATE_PR] {m}" for m in cand_pr_mismatches])
            if live_pr_status:
                print(
                    f"[INFO] Live PR Identity Status: {live_pr_status}"
                    + (
                        f" (PR #{live_pr_details.get('candidate_pr_number')}, head={live_pr_details.get('pr_head_sha')}, state={live_pr_details.get('pr_state')}, draft={live_pr_details.get('pr_draft')}, ancestry={live_pr_details.get('ancestry_status')})"
                        if live_pr_details
                        else ""
                    )
                )

        elif any(
            x is not None
            for x in (
                args.candidate_pr_number,
                args.candidate_pr_status,
                args.candidate_pr_head,
                args.candidate_pr_base,
                candidate_pr_draft_val,
                args.pr_number,
                args.pr_status,
            )
        ):
            exp_cand_pr_facts = {
                "candidate_pr_number": args.candidate_pr_number if args.candidate_pr_number is not None else args.pr_number,
                "candidate_pr_status": (
                    str(args.candidate_pr_status).strip().upper()
                    if args.candidate_pr_status is not None
                    else (str(args.pr_status).strip().upper() if args.pr_status is not None else None)
                ),
                "candidate_pr_head": args.candidate_pr_head,
                "candidate_pr_base": args.candidate_pr_base,
                "pr_draft": candidate_pr_draft_val,
                "candidate_commit": args.candidate_commit,
            }
            cand_pr_mismatches = verify_current_candidate_pr_facts(
                content=actual_content,
                version_str=payload["product_version"]["version"],
                repository=payload["project_identity"]["repository"],
                project_root=project_root,
                expected_facts=exp_cand_pr_facts,
            )
            mismatches.extend([f"[CURRENT_CANDIDATE_PR] {m}" for m in cand_pr_mismatches])

        mismatches.extend(
            [f"[GIT_SNAPSHOT] {m}" for m in verify_git_snapshot_facts(project_root, actual_content, "baseline")]
        )

        if mismatches:
            print(f"[FAIL] Committed baseline mismatches generated facts ({len(mismatches)} issues):")
            for m in mismatches:
                print(f"  - {m}")
            sys.exit(1)

        print(f"[PASS] Engineering baseline verified against committed file: {out_md} (content_sha256={expected_fm.get('content_sha256')})")
        sys.exit(0)

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md_text, encoding="utf-8")

    out_json = (
        Path(args.json_out).resolve()
        if args.json_out
        else project_root / ".artifacts" / "baseline" / "engineering_baseline.json"
    )
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"[PASS] Generated engineering baseline: {out_md}")
    print(f"[PASS] Content SHA-256: {payload['content_sha256']}")


if __name__ == "__main__":
    main()
