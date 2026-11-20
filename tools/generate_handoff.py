#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automated Generator & Validator for STD-020 Cross-Session Handoff."""

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

from tools.validate_approval_contract import compute_canonical_document_sha256
from tools.release_evidence import (
    _query_pr_via_api,
    _query_pr_via_gh,
    load_release_evidence,
    resolve_release_evidence_path,
    verify_candidate_pr_merge_event,
    verify_candidate_pr_section,
    verify_commit_ancestry,
)


def resolve_standards_root(explicit_root: Optional[str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    env_root = os.environ.get("AI_ENGINEERING_STANDARDS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


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


def extract_adrs_from_decision_record(project_root: Path) -> List[Dict[str, str]]:
    dr_path = project_root / "docs" / "DECISION-RECORD.md"
    if not dr_path.exists():
        return []
    adrs: List[Dict[str, str]] = []
    lines = dr_path.read_text(encoding="utf-8").splitlines()
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
            summary = re.sub(r"[`*]", "", cols[1]).strip()
            status_match = re.search(r"(OWNER_APPROVED|AI_APPROVED)", cols[3])
            if status_match:
                approval_st = status_match.group(1)
            else:
                continue
            adrs.append({
                "decision_id": dec_id,
                "summary": summary,
                "approval_status": approval_st,
                "approval_reference": f"docs/DECISION-RECORD.md#{dec_id}",
            })
    return adrs


def compute_deterministic_handoff_sha256(payload: Dict[str, Any]) -> str:
    filtered = {k: v for k, v in sorted(payload.items()) if k not in ("captured_at", "content_sha256")}
    raw = json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


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
        return "", [f"SCOPE_SECTION_MISSING: Scope section '{scope_tag}' not found in handoff document"]
    if len(matches) > 1:
        return "", [f"DUPLICATE_SCOPE_SECTION: Duplicate scope section '{scope_tag}' found in handoff document ({len(matches)} occurrences)"]

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
        identity_match = re.search(
            r"## 8\. Git 分支及 Commit 身份.*?(?=\n## 9\.)",
            content,
            re.S,
        )
        if not identity_match:
            return ["BASELINE_GIT_SNAPSHOT_SECTION_MISSING: Git identity section not found"]
        identity_text = identity_match.group(0)
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


def verify_handoff_semantic_facts(
    content: str,
    expected_facts: Dict[str, Any],
    scope: Optional[str] = None,
) -> List[str]:
    """Verify semantic facts inside committed docs/CROSS-SESSION-HANDOFF.md.
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
            "last_verified_ci_commit": [r'(?:last_verified_ci_commit|已验证 CI Commit|最近一次已验证 CI Commit)[^:：\n]*?[:：]\s*`([0-9a-f]{40})`'],
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

    # 1. TASK_ID
    exp_task = expected_facts.get("task_id")
    if exp_task:
        m_task = (
            re.search(r'TASK_ID=([A-Za-z0-9_-]+)', target_text)
            or re.search(r'任务编号[^\n]*?：`([A-Za-z0-9_-]+)`', target_text)
            or re.search(r'TASK_ID[^\n]*?`([A-Za-z0-9_-]+)`', target_text)
        )
        if not m_task:
            mismatches.append(f"TASK_ID missing from handoff text (expected '{exp_task}')")
        elif m_task.group(1) != exp_task:
            mismatches.append(f"TASK_ID committed='{m_task.group(1)}' != expected='{exp_task}'")

    # 2. candidate_commit
    exp_cand = expected_facts.get("candidate_commit")
    if exp_cand:
        m_cand = (
            re.search(r'当前候选 Commit\*\*：`([0-9a-f]{40})`', target_text)
            or re.search(r'PR9_CANDIDATE_COMMIT=([0-9a-f]{40})', target_text)
            or re.search(r'候选 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'candidate_commit.*?`([0-9a-f]{40})`', target_text)
        )
        if not m_cand:
            mismatches.append(f"candidate_commit missing from handoff text (expected '{exp_cand}')")
        elif m_cand.group(1) != exp_cand:
            mismatches.append(f"candidate_commit committed='{m_cand.group(1)}' != expected='{exp_cand}'")

    # 3. snapshot_commit
    exp_snap = expected_facts.get("snapshot_commit")
    if exp_snap:
        m_snap = (
            re.search(r'PR9 发布凭证快照\*\*：COMMIT_HASH=([0-9a-f]{40})', target_text)
            or re.search(r'COMMIT_HASH=([0-9a-f]{40})', target_text)
            or re.search(r'本地 HEAD \(`local_head`\)\*\*：`([0-9a-f]{40})`', target_text)
            or re.search(r'快照 Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'snapshot_commit.*?`([0-9a-f]{40})`', target_text)
        )
        if not m_snap:
            mismatches.append(f"snapshot_commit missing from handoff text (expected '{exp_snap}')")
        elif m_snap.group(1) != exp_snap:
            mismatches.append(f"snapshot_commit committed='{m_snap.group(1)}' != expected='{exp_snap}'")

    # 4. last_verified_ci_commit
    exp_ci_commit = expected_facts.get("last_verified_ci_commit") or expected_facts.get("ci_commit")
    if exp_ci_commit:
        m_ci = (
            re.search(r'最近一次已验证 CI Commit\*\*：`([0-9a-f]{40})`', target_text)
            or re.search(r'最近一次已验证 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'最新已验证 CI Commit.*?`([0-9a-f]{40})`', target_text)
            or re.search(r'last_verified_ci_commit.*?`([0-9a-f]{40})`', target_text)
        )
        if not m_ci:
            mismatches.append(f"last_verified_ci_commit missing from handoff text (expected '{exp_ci_commit}')")
        elif m_ci.group(1) != exp_ci_commit:
            mismatches.append(f"last_verified_ci_commit committed='{m_ci.group(1)}' != expected='{exp_ci_commit}'")

    # 5. Push Run ID
    exp_push = expected_facts.get("push_run_id") or expected_facts.get("ci_run_id")
    if exp_push:
        str_push = str(exp_push)
        m_push = (
            re.search(r'Push Run ID\*\*：`([0-9]+)`', target_text)
            or re.search(r'Run ID \(`run_id`\)\*\*：`([0-9]+)`', target_text)
            or re.search(r'Push Run.*?`([0-9]+)`', target_text)
        )
        if not m_push:
            mismatches.append(f"push_run_id missing from handoff text (expected '{str_push}')")
        elif m_push.group(1) != str_push:
            mismatches.append(f"push_run_id committed='{m_push.group(1)}' != expected='{str_push}'")

    # 5b. PR Run ID
    exp_pr = expected_facts.get("pr_run_id")
    if exp_pr:
        str_pr = str(exp_pr)
        m_pr = (
            re.search(r'PR Run ID\*\*：`([0-9]+)`', target_text)
            or re.search(r'PR Run.*?`([0-9]+)`', target_text)
        )
        if not m_pr:
            mismatches.append(f"pr_run_id missing from handoff text (expected '{str_pr}')")
        elif m_pr.group(1) != str_pr:
            mismatches.append(f"pr_run_id committed='{m_pr.group(1)}' != expected='{str_pr}'")

    # 6. CI Commit
    exp_ci_com = expected_facts.get("ci_commit")
    if exp_ci_com:
        m_ci_com = re.search(r'关联 Commit \(`commit`\)\*\*：`([0-9a-f]{40}|NOT_RUN|NOT_VERIFIABLE)`', target_text)
        if not m_ci_com:
            mismatches.append(f"ci commit missing from handoff text (expected '{exp_ci_com}')")
        elif m_ci_com.group(1) != exp_ci_com:
            mismatches.append(f"ci commit committed='{m_ci_com.group(1)}' != expected='{exp_ci_com}'")

    # 7. CI verification_status
    exp_st = expected_facts.get("ci_status")
    if exp_st:
        m_st = (
            re.search(r'核验状态 \(`verification_status`\)\*\*：`([A-Z_]+)`', target_text)
            or re.search(
                r'## 4\. 远端 CI 关联.*?\n(?:- [^\n]+\n)*?- \*\*核验状态 \(`verification_status`\)\*\*：`([A-Z_]+)`',
                target_text,
            )
        )
        if not m_st:
            mismatches.append(f"ci verification_status missing from handoff text (expected '{exp_st}')")
        elif m_st.group(1) != exp_st:
            mismatches.append(f"ci verification_status committed='{m_st.group(1)}' != expected='{exp_st}'")

    # 8. TEST_COUNT
    exp_tests = expected_facts.get("test_count") or expected_facts.get("test_passed")
    if exp_tests is not None:
        m_tests = (
            re.search(r'通过 / 失败用例数\*\*：`(\d+)\s*/\s*(\d+)`', target_text)
            or re.search(r'测试用例数\*\*：`(\d+)\s*/\s*(\d+)`', target_text)
            or re.search(r'全量测试用例数\*\*：`(\d+)\s*/\s*(\d+)`', target_text)
            or re.search(r'(\d+)\s+tests\s+PASS', target_text)
        )
        if not m_tests:
            mismatches.append(f"test count missing from handoff text (expected {exp_tests})")
        elif int(m_tests.group(1)) != int(exp_tests):
            mismatches.append(f"test count committed={m_tests.group(1)} != expected={exp_tests}")

    # 9. PR 状态
    exp_pr_st = expected_facts.get("pr_status")
    if exp_pr_st:
        m_pr_st = (
            re.search(r'PR 状态 \(`pr_status`\)\*\*：`([A-Za-z_]+)`', target_text)
            or re.search(r'PR 状态.*?`([A-Za-z_]+)`', target_text)
            or re.search(r'PR9=([A-Za-z_]+)', target_text)
            or re.search(r'PR10=([A-Za-z_]+)', target_text)
        )
        if not m_pr_st and exp_pr_st not in target_text:
            mismatches.append(f"pr_status missing from handoff text (expected '{exp_pr_st}')")
        elif m_pr_st and m_pr_st.group(1) != exp_pr_st:
            mismatches.append(f"pr_status committed='{m_pr_st.group(1)}' != expected='{exp_pr_st}'")

    # 9b. main_head
    exp_main = expected_facts.get("main_head")
    if exp_main:
        m_main = (
            re.search(r'主干 HEAD \(`main_head`\)\*\*：`([0-9a-f]{40})`', target_text)
            or re.search(r'main_head=([0-9a-f]{40})', target_text)
            or re.search(r'远端 main \(`remote_head`\)\*\*：`([0-9a-f]{40})`', target_text)
        )
        if not m_main:
            mismatches.append(f"main_head missing from handoff text (expected '{exp_main}')")
        elif m_main.group(1) != exp_main:
            mismatches.append(f"main_head committed='{m_main.group(1)}' != expected='{exp_main}'")

    # 10. release_flow_status
    exp_rf_st = expected_facts.get("release_flow_status")
    if exp_rf_st:
        m_rf_st = re.search(r'发布流程状态 \(`release_flow_status`\)\*\*：`([A-Za-z_]+)`', target_text)
        if not m_rf_st:
            mismatches.append(f"release_flow_status missing from handoff text (expected '{exp_rf_st}')")
        elif m_rf_st.group(1) != exp_rf_st:
            mismatches.append(f"release_flow_status committed='{m_rf_st.group(1)}' != expected='{exp_rf_st}'")

    # 11. OLD_TAG_DELETED
    exp_ot_del = expected_facts.get("old_tag_deleted")
    if exp_ot_del is not None:
        expected_str = str(exp_ot_del).lower()
        m_ot = (
            re.search(r'旧 Tag 删除状态 \(`old_tag_deleted`\)\*\*：`(true|false)`', target_text)
            or re.search(r'OLD_TAG_DELETED=(true|false)', target_text)
        )
        if not m_ot:
            mismatches.append(f"old_tag_deleted missing from handoff text (expected '{expected_str}')")
        elif m_ot.group(1) != expected_str:
            mismatches.append(f"old_tag_deleted committed='{m_ot.group(1)}' != expected='{expected_str}'")

    return mismatches


def verify_handoff_candidate_pr_facts(
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
    """Delegate handoff CURRENT_CANDIDATE_PR verification to the shared F13+F14 contract."""
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


def build_handoff_payload(
    project_root: Path,
    task_id: str,
    version: Optional[str] = None,
    handoff_type: str = "DURABLE",
    status: str = "IN_PROGRESS",
    completed_items: Optional[List[str]] = None,
    pending_items: Optional[List[str]] = None,
    blockers: Optional[List[Dict[str, str]]] = None,
    approved_decisions: Optional[List[Dict[str, str]]] = None,
    proposed_items: Optional[List[Dict[str, Any]]] = None,
    test_results_override: Optional[Dict[str, Any]] = None,
    ci_run_override: Optional[Dict[str, Any]] = None,
    captured_at: Optional[str] = None,
    source_commit_override: Optional[str] = None,
    candidate_commit_override: Optional[str] = None,
    snapshot_commit_override: Optional[str] = None,
    last_verified_ci_commit: Optional[str] = None,
    ci_commit: Optional[str] = None,
    push_run_id: Optional[str] = None,
    pr_run_id: Optional[str] = None,
    pr_head_override: Optional[str] = None,
    old_tag_deleted: bool = True,
    release_flow_status: str = "IN_PROGRESS",
    pr_status: Optional[str] = None,
    pr_number: Optional[int] = None,
    candidate_pr_number: Optional[int] = None,
    candidate_pr_status: Optional[str] = None,
    candidate_pr_head: Optional[str] = None,
    candidate_pr_base: Optional[str] = None,
    candidate_pr_draft: Optional[bool] = None,
    candidate_pr_merge_event: Optional[Dict[str, Any]] = None,
    expected_repo_owner: Optional[str] = None,
    pending_verifications: Optional[str] = None,
    release_evidence_path: Optional[str] = None,
    release_evidence: Optional[Dict[str, Any]] = None,
    snapshot_evidence_path: Optional[str] = None,
    final_evidence_path: Optional[str] = None,
    standards_root: Optional[Path] = None,
    allow_offline: bool = True,
) -> Tuple[bool, List[str], Optional[Dict[str, Any]], Optional[str]]:
    errors: List[str] = []
    project_root = project_root.resolve()
    std_root = resolve_standards_root(str(standards_root) if standards_root else None)

    existing_handoff = project_root / "docs" / "CROSS-SESSION-HANDOFF.md"
    existing_facts: Dict[str, Any] = {}
    if existing_handoff.exists():
        try:
            ex_txt = existing_handoff.read_text(encoding="utf-8")
            m_cap = re.search(
                r'CAPTURED_AT=([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z)',
                ex_txt,
            )
            if m_cap:
                existing_facts["captured_at"] = m_cap.group(1).strip()
            m_cand = re.search(r'当前候选 Commit\*\*：`([0-9a-f]{40})`', ex_txt)
            if m_cand:
                existing_facts["candidate_commit"] = m_cand.group(1).strip()
            m_ci = re.search(r'最近一次已验证 CI Commit\*\*：`([0-9a-f]{40})`', ex_txt)
            if m_ci:
                existing_facts["last_verified_ci_commit"] = m_ci.group(1).strip()
            m_run = re.search(r'Run ID \(`run_id`\)\*\*：`(\d+)`', ex_txt)
            if m_run:
                existing_facts["ci_run_id"] = m_run.group(1).strip()
            m_pr_run = re.search(r'PR Run ID\*\*：`(\d+)`', ex_txt)
            if m_pr_run:
                existing_facts["pr_run_id"] = m_pr_run.group(1).strip()
            m_push_run = re.search(r'Push Run ID\*\*：`(\d+)`', ex_txt)
            if m_push_run:
                existing_facts["push_run_id"] = m_push_run.group(1).strip()
        except Exception:
            pass

    now_iso = (
        captured_at
        or existing_facts.get("captured_at")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    today_date = now_iso[:10]

    # Project ID, repository, and version
    manifest_path = project_root / "engineering-manifest.yaml"
    project_id = "ai-engineering-standards"
    repository = "xiefeifeihu/AI-Engineering-Standards"
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            proj_obj = manifest.get("project") or {}
            project_id = str(proj_obj.get("id") or project_id)
            repository = str(proj_obj.get("repository") or repository)
        except Exception:
            pass

    ver_file = project_root / "VERSION"
    if not ver_file.exists():
        errors.append("HANDOFF_MISSING_VERSION: VERSION file does not exist")
        resolved_version = (version or "3.0.0").lstrip("v")
    else:
        resolved_version = (version or ver_file.read_text(encoding="utf-8").strip()).lstrip("v")

    # 1 & 2. Auto-collect Git state, branch, and Commit
    evidence_data: Optional[Dict[str, Any]] = release_evidence
    if snapshot_evidence_path:
        snap_ok, snap_errors, _ = load_release_evidence(project_root, snapshot_evidence_path)
        if not snap_ok:
            errors.extend([f"HANDOFF_SNAPSHOT_EVIDENCE_INVALID: {e}" for e in snap_errors])
    if release_evidence_path and final_evidence_path:
        pr9_ok, pr9_errors, _ = load_release_evidence(project_root, release_evidence_path)
        if not pr9_ok:
            errors.extend([f"HANDOFF_HISTORICAL_RELEASE_EVIDENCE_INVALID: {e}" for e in pr9_errors])
    if final_evidence_path:
        final_ok, final_errors, final_loaded = load_release_evidence(project_root, final_evidence_path)
        if not final_ok or final_loaded is None:
            errors.extend([f"HANDOFF_FINAL_RELEASE_EVIDENCE_INVALID: {e}" for e in final_errors])
        else:
            evidence_data = final_loaded
    elif evidence_data is None:
        ev_ok, ev_errors, ev_loaded = load_release_evidence(project_root, release_evidence_path)
        if ev_ok and ev_loaded:
            evidence_data = ev_loaded
        elif release_evidence_path:
            errors.extend([f"HANDOFF_RELEASE_EVIDENCE_INVALID: {e}" for e in ev_errors])

    is_current_version_released = bool(
        evidence_data
        and str(evidence_data.get("version", "")).lstrip("v") == resolved_version
        and evidence_data.get("release_flow_status") == "RELEASED"
    )
    current_ver_evidence: Optional[Dict[str, Any]] = evidence_data if is_current_version_released else None

    rc_head, git_head = run_git(project_root, ["rev-parse", "HEAD"])
    live_head = git_head if rc_head == 0 and re.match(r"^[0-9a-f]{40}$", git_head) else ""
    local_head = snapshot_commit_override or live_head or (
        (current_ver_evidence.get("snapshot_commit") if current_ver_evidence else None) or ""
    )
    if not local_head:
        errors.append("HANDOFF_INVALID_COMMIT: Local Git HEAD is not a valid 40-character SHA")

    eff_cand_pr_number: Optional[int] = (
        candidate_pr_number if candidate_pr_number is not None else pr_number
    )
    if eff_cand_pr_number is not None and int(eff_cand_pr_number) < 1:
        errors.append(
            f"CANDIDATE_PR_INVALID_NUMBER: candidate_pr_number must be >= 1 (got '{eff_cand_pr_number}')"
        )
    raw_pr_status = candidate_pr_status if candidate_pr_status is not None else pr_status
    if raw_pr_status is not None:
        effective_pr_status = str(raw_pr_status).strip().upper()
        if effective_pr_status not in ("DRAFT", "OPEN", "MERGED", "CLOSED"):
            errors.append(
                f"CANDIDATE_PR_INVALID_STATUS: candidate_pr_status '{effective_pr_status}' must be DRAFT, OPEN, MERGED, or CLOSED"
            )
    else:
        effective_pr_status = "DRAFT"
    eff_cand_pr_base = str(candidate_pr_base).strip() if candidate_pr_base is not None else "main"
    if eff_cand_pr_base != "main":
        errors.append(f"CANDIDATE_PR_BASE_NOT_MAIN: candidate_pr_base '{eff_cand_pr_base}' must be 'main'")

    code_candidate_commit = (
        candidate_commit_override
        or (current_ver_evidence.get("candidate_commit") if current_ver_evidence else None)
        or local_head
    )
    if (project_root / ".git").exists() and code_candidate_commit:
        if not re.fullmatch(r"[0-9a-f]{40}", code_candidate_commit) or code_candidate_commit == "0" * 40:
            errors.append(
                f"HANDOFF_CANDIDATE_COMMIT_INVALID: '{code_candidate_commit}' must be a non-zero 40-hex commit SHA"
            )
        else:
            rc_cand_obj, _ = run_git(project_root, ["cat-file", "-e", f"{code_candidate_commit}^{{commit}}"])
            if rc_cand_obj != 0:
                errors.append(
                    f"HANDOFF_CANDIDATE_COMMIT_NOT_FOUND: candidate_commit '{code_candidate_commit}' does not exist in Git repository"
                )

    eff_cand_pr_head = candidate_pr_head or pr_head_override or code_candidate_commit
    if candidate_pr_head:
        anc_st, anc_errs = verify_commit_ancestry(
            project_root,
            code_candidate_commit,
            candidate_pr_head,
            repository=repository,
            allow_remote_compare=not allow_offline,
        )
        if anc_st == "FAIL":
            errors.extend(anc_errs)
        elif anc_st == "NOT_VERIFIABLE" and not allow_offline:
            errors.extend(anc_errs)

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

    effective_ci_commit = (
        ci_commit
        or last_verified_ci_commit
        or (current_ver_evidence.get("last_verified_ci_commit") if current_ver_evidence else None)
    )

    if effective_pr_status == "DRAFT":
        if candidate_pr_draft is False:
            errors.append(
                "CANDIDATE_PR_DRAFT_CONFLICT: candidate_pr_status='DRAFT' conflicts with candidate_pr_draft=False"
            )
        pr_state_str = "OPEN"
        pr_draft_bool = True
        cand_release_status = "CANDIDATE"
    elif effective_pr_status == "OPEN":
        pr_state_str = "OPEN"
        pr_draft_bool = bool(candidate_pr_draft) if candidate_pr_draft is not None else False
        cand_release_status = "CANDIDATE"
    elif effective_pr_status == "MERGED":
        pr_state_str = "MERGED"
        pr_draft_bool = False
        cand_release_status = "RELEASED" if is_current_version_released else "MERGED_PENDING_TAG"
    else:
        pr_state_str = "CLOSED"
        pr_draft_bool = False
        cand_release_status = "BLOCKED"

    # Baseline source commit resolution
    pb_path = project_root / "docs" / "PRODUCT-BASELINE.md"
    default_source_commit = "9687f961b22df612c4311961e06fc1c1fd508c37"
    if pb_path.exists():
        try:
            pb_txt = pb_path.read_text(encoding="utf-8")
            m_sc = re.search(r'source_commit:\s*"([0-9a-f]{40})"', pb_txt)
            if m_sc:
                default_source_commit = m_sc.group(1)
        except Exception:
            pass

    if source_commit_override:
        if not re.match(r"^[0-9a-f]{40}$", source_commit_override):
            errors.append(f"HANDOFF_INVALID_COMMIT: source_commit_override '{source_commit_override}' is not 40-hex SHA")
        source_commit = source_commit_override
    else:
        source_commit = default_source_commit

    branch_name = resolve_snapshot_branch_name(project_root)
    rc_sb, git_sb = run_git(project_root, ["status", "-sb"])
    rc_porcelain, git_porcelain = run_git(project_root, ["status", "--porcelain"])
    worktree_clean = rc_porcelain == 0 and len(git_porcelain.strip()) == 0

    # Live query remote main - never fallback to local cache
    remote_head = query_remote_main_head(project_root)

    # 3. Auto-collect Standards lock - fail closed if missing
    lock_path = project_root / "standards.lock.json"
    if not lock_path.exists():
        return False, ["HANDOFF_MISSING_STANDARDS_LOCK: standards.lock.json is missing; cannot generate handoff without authoritative lock"], None, None
    try:
        lock_raw = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, [f"HANDOFF_CORRUPT_STANDARDS_LOCK: {e}"], None, None

    for req_k in ("repository", "version", "tag", "tag_object_sha", "peeled_commit"):
        if not lock_raw.get(req_k):
            errors.append(f"HANDOFF_INVALID_STANDARDS_LOCK: standards.lock.json missing '{req_k}'")

    standards_lock = {
        "repository": str(lock_raw.get("repository")),
        "version": str(lock_raw.get("version")),
        "tag": str(lock_raw.get("tag")),
        "tag_object_sha": str(lock_raw.get("tag_object_sha")),
        "peeled_commit": str(lock_raw.get("peeled_commit")),
    }

    # 4. Auto-summarize actual test results - never default to fake PASS
    default_test_log = project_root / ".artifacts" / "test_results.txt"
    if test_results_override:
        test_results = test_results_override
    elif default_test_log.exists():
        test_results = {
            "verification_status": "NOT_VERIFIABLE",
            "command": "python -m unittest discover -s tests -v",
            "exit_code": None,
            "passed_count": 0,
            "failed_count": 0,
            "evidence_ref": ".artifacts/test_results.txt",
        }
    elif current_ver_evidence and current_ver_evidence.get("ci_status") == "PASS":
        test_results = {
            "verification_status": "PASS",
            "command": "python -m unittest discover -s tests -v",
            "exit_code": 0,
            "passed_count": current_ver_evidence.get("test_count", 219),
            "failed_count": current_ver_evidence.get("test_failed", 0),
            "evidence_ref": ".github/workflows/standards-ci.yml",
        }
    else:
        test_results = {
            "verification_status": "NOT_RUN",
            "command": "python -m unittest discover -s tests -v",
            "exit_code": None,
            "passed_count": 0,
            "failed_count": 0,
            "evidence_ref": "NONE",
        }

    if test_results.get("verification_status") == "PASS":
        ev_ref = str(test_results.get("evidence_ref") or "").strip()
        if not ev_ref or ev_ref in ("NONE", "N/A", "NOT_RUN"):
            errors.append("HANDOFF_TEST_PASS_WITHOUT_EVIDENCE: test_results=PASS requires valid evidence_ref")
        elif not (project_root / ev_ref).exists():
            errors.append(f"HANDOFF_TEST_PASS_MISSING_EVIDENCE_FILE: evidence_ref '{ev_ref}' does not exist on disk")

    # 5. Auto-associate CI Run ID (strictly decoupled from historical v3.0.0 runs when on candidate version)
    active_push_run_id = (
        push_run_id
        or (current_ver_evidence.get("push_run_id") if current_ver_evidence else None)
        or (ci_run_override.get("run_id") if ci_run_override else None)
    )
    active_pr_run_id = (
        pr_run_id
        or (current_ver_evidence.get("pr_run_id") if current_ver_evidence else None)
    )
    active_run_id = active_push_run_id or active_pr_run_id
    ci_commit_val = effective_ci_commit or "NOT_VERIFIABLE"
    if ci_run_override:
        ci_run = dict(ci_run_override)
        if not ci_run.get("run_id") and active_run_id:
            ci_run["run_id"] = int(active_run_id) if str(active_run_id).isdigit() else active_run_id
        if not ci_run.get("commit") or ci_run.get("commit") in ("NOT_RUN", None, ""):
            ci_run["commit"] = ci_commit_val
    else:
        ci_run = {
            "run_id": int(active_run_id) if (active_run_id and str(active_run_id).isdigit()) else active_run_id,
            "workflow": ".github/workflows/standards-ci.yml",
            "commit": ci_commit_val,
            "verification_status": "PASS" if (active_run_id and is_current_version_released) else "NOT_VERIFIABLE",
            "evidence_ref": ".github/workflows/standards-ci.yml",
        }
    if ci_run.get("commit") in ("NOT_RUN", None, "") and ci_commit_val:
        ci_run["commit"] = ci_commit_val

    # 6, 7, 8, 9, 10. Items, blockers, approved decisions, proposed items
    comp_list = completed_items if completed_items is not None else []
    pend_list = pending_items if pending_items is not None else []
    blocker_list = blockers if blockers is not None else []

    # Markdown status labels alone are not approval provenance.
    approved_list = approved_decisions if approved_decisions is not None else []

    proposed_list = proposed_items if proposed_items is not None else []

    # Verify no proposed item is mixed into approved_decisions
    for dec in approved_list:
        if dec.get("approval_status") not in ("AI_APPROVED", "OWNER_APPROVED"):
            errors.append(
                f"HANDOFF_UNAPPROVED_DECISION_MIXED: Decision '{dec.get('decision_id')}' has non-approved status '{dec.get('approval_status')}'"
            )

    # 11. Next-session startup guide
    next_guide = {
        "mandatory_read_order": [
            "docs/DOCUMENT-INDEX.md",
            "docs/当前权威基线.md",
            "docs/CROSS-SESSION-HANDOFF.md",
            "docs/PROJECT-BLUEPRINT.md",
            "docs/PRODUCT-BASELINE.md",
            "docs/SYSTEM-ARCHITECTURE.md",
            "docs/API-CONTRACT.md",
            "docs/TEST-ACCEPTANCE.md",
            "docs/DECISION-RECORD.md",
        ],
        "verification_commands": [
            "git status -sb && git rev-parse HEAD && git branch --show-current",
            "python tools/standards_sync/cli.py verify-lock --project-root .",
            "python tools/validate-documentation-collection.py --project-root . --check-templates",
            "python tools/validate-schemas.py",
        ],
        "immediate_next_steps": [
            "核验远端 Draft PR CI 状态与 ChatGPT 独立审核结论",
            "严禁仅凭旧会话聊天摘要推断当前 Git、CI 或 Runtime 状态",
        ],
    }

    payload: Dict[str, Any] = {
        "schema_version": "2.0.0",
        "handoff_type": handoff_type,
        "task_id": task_id,
        "version": f"v{resolved_version}",
        "status": status,
        "git_state": {
            "branch": branch_name,
            "local_head": local_head,
            "remote_head": remote_head,
            "worktree_clean": worktree_clean,
            "status_summary": git_sb.splitlines()[0] if git_sb else f"## {branch_name}",
        },
        "standards_lock": standards_lock,
        "test_results": test_results,
        "ci_run": ci_run,
        "completed_items": comp_list,
        "pending_items": pend_list,
        "blockers": blocker_list,
        "approved_decisions": approved_list,
        "proposed_items": proposed_list,
        "next_session_guide": next_guide,
        "captured_at": now_iso,
        "content_sha256": "",
    }
    content_sha = compute_deterministic_handoff_sha256(payload)
    payload["content_sha256"] = content_sha

    schema_path = std_root / "schemas" / "cross-session-handoff.schema.json"
    if schema_path.exists():
        h_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(instance=payload, schema=h_schema)
        except jsonschema.ValidationError as ve:
            errors.append(f"HANDOFF_SCHEMA_VIOLATION: {ve.message}")

    if errors:
        return False, errors, None, None

    doc_prefix = project_id.upper().replace("_", "-")
    is_primary = handoff_type == "DURABLE"
    comp_md = "\n".join(f"- [x] {item}" for item in comp_list) or "- 暂无"
    pend_md = "\n".join(f"- [ ] {item}" for item in pend_list) or "- 暂无"
    block_md = (
        "\n".join(
            f"- **`{b['blocker_id']}` ({b['severity']})**：{b['description']}（缓解措施：{b['remediation']}）"
            for b in blocker_list
        )
        if blocker_list
        else "- 当前无 `BLOCK` 阻断项。"
    )
    approved_md = (
        "\n".join(
            f"| `{d['decision_id']}` | {d['summary']} | `{d['approval_status']}` | `{d['approval_reference']}` |"
            for d in approved_list
        )
        if approved_list
        else "| - | 暂无批准决策 | - | - |"
    )
    proposed_md = "\n".join(
        f"| `{p['proposal_id']}` | {p['summary']} | `{str(p['requires_owner_approval']).lower()}` | `{p['status']}` |"
        for p in proposed_list
    )
    read_md = "\n".join(f"{idx + 1}. `{p}`" for idx, p in enumerate(next_guide["mandatory_read_order"]))
    cmd_md = "\n".join(f"   - `{c}`" for c in next_guide["verification_commands"])
    step_md = "\n".join(f"   - {s}" for s in next_guide["immediate_next_steps"])

    # Generation never grants approval; a separate trusted review event is required.
    doc_status = "IN_REVIEW"
    doc_approval = "IN_REVIEW"

    pr_head = eff_cand_pr_head
    pr_label = f"PR #{eff_cand_pr_number}" if eff_cand_pr_number is not None else "当前候选 PR"
    if pending_verifications is not None:
        pending_text = pending_verifications
    elif ci_run.get("verification_status") == "PASS":
        pending_text = f"{pr_label} CI 已通过，等待独立复核与 Owner 批准合入 main 后由 main CI 自动签发 v{resolved_version} Tag。"
    else:
        pending_text = "远端 GitHub Actions CI 双平台实测；严禁在推送前或运行完成前伪造 CI PASS"

    if last_verified_ci_commit and ("（" in str(last_verified_ci_commit) or "(" in str(last_verified_ci_commit)):
        verified_ci_text = str(last_verified_ci_commit)
    elif effective_ci_commit:
        effective_passed = test_results.get("passed_count") or (current_ver_evidence.get("test_count") if current_ver_evidence else None)
        passed_suffix = f"，{effective_passed} tests PASS" if effective_passed else ""
        if active_push_run_id and active_pr_run_id and str(active_push_run_id) != str(active_pr_run_id):
            run_desc = f"Run {active_push_run_id} Push / Run {active_pr_run_id} {pr_label} 双平台全绿{passed_suffix}"
            verified_ci_text = f"`{effective_ci_commit}`（{run_desc}）"
        elif active_run_id:
            run_desc = f"Run {active_run_id} 双平台全绿{passed_suffix}"
            verified_ci_text = f"`{effective_ci_commit}`（{run_desc}）"
        else:
            verified_ci_text = f"`{effective_ci_commit}`"
    else:
        verified_ci_text = "`NOT_VERIFIABLE`"

    if task_id.startswith("Std-009"):
        hist_ci_text = "Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748"
    elif task_id.startswith("Std-010"):
        hist_ci_text = "Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748, 42763704495, 42763710456"
    elif task_id.startswith("Std-012"):
        hist_ci_text = "Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748, 42763704495, 42763710456, 42772211734, 42772217074"
    elif task_id.startswith("Std-013"):
        hist_ci_text = "Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748, 42763704495, 42763710456, 42772211734, 42772217074, 42783497089, 42783504258"
    elif task_id.startswith("Std-014"):
        hist_ci_text = "Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748, 42763704495, 42763710456, 42772211734, 42772217074, 42783497089, 42783504258, 42800374434, 42800383714"
    elif task_id.startswith("Std-015"):
        hist_ci_text = "Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748, 42763704495, 42763710456, 42772211734, 42772217074, 42783497089, 42783504258, 42800374434, 42800383714, 42835602231, 42835611644"
    else:
        hist_ci_text = "Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748, 42763704495, 42763710456, 42772211734, 42772217074, 42783497089, 42783504258, 42800374434, 42800383714, 42835602231, 42835611644, 42843755347, 42843964061"

    md_lines = [
        "---",
        f'document_id: "DOC-{doc_prefix}-CROSS-SESSION-HANDOFF-001"',
        f'document_version: "{resolved_version}"',
        f'project_id: "{project_id}"',
        'document_type: "CROSS_SESSION_HANDOFF"',
        f'status: "{doc_status}"',
        f'applies_to_release: "v{resolved_version}"',
        f'last_updated: "{today_date}"',
        "supersedes: null",
        f'change_summary: "自动采集生成任务 {task_id} 跨会话交接文档 (STD-020 v2.0.0)"',
        "history_reference: null",
        f"primary_entrypoint: {str(is_primary).lower()}",
        f'source_commit: "{source_commit}"',
        f'content_sha256: "{content_sha}"',
        'approval_scope: "AI_APPROVABLE"',
        f'approval_status: "{doc_approval}"',
        "---",
        "",
        f"# 跨会话工作交接 ({task_id})",
        "",
        "```text",
        f"TASK_ID={task_id}",
        f"VERSION=v{resolved_version}",
        f"HANDOFF_TYPE={handoff_type}",
        f"STATUS={status}",
        f"COMMIT_HASH={local_head}",
        f"CAPTURED_AT={now_iso}",
        f"CONTENT_SHA256={content_sha}",
        "```",
        "",
        "> **强制重核验约束 (`STD-020` §3)**：新会话接手时必须重新核验实时工程事实（Git、Standards 锁定、CI 与 Runtime），严禁仅凭旧聊天摘要推断当前状态。",
        "",
        "## 1. 当前 Git 状态与分支身份 (`git_state`)",
        f"- **当前分支 (`branch`)**：`{branch_name}`",
        f"- **当前快照 Commit (`snapshot_commit`)**：`{local_head}`",
        f"- **本地 HEAD (`local_head`)**：`{local_head}`",
        f"- **远端 main (`remote_head`)**：`{remote_head}`",
        f"- **工作区干净状态 (`worktree_clean`)**：`{str(worktree_clean).lower()}`",
        f"- **Git 状态摘要 (`status_summary`)**：`{payload['git_state']['status_summary']}`",
        "",
        "## 2. 当前 Standards 锁定 (`standards_lock`)",
        f"- **规范仓库 (`repository`)**：`{standards_lock['repository']}`",
        f"- **锁定版本 (`version`)**：`{standards_lock['version']}`",
        f"- **锁定正式 Tag (`tag`)**：`{standards_lock['tag']}`",
        f"- **Tag Object SHA (`tag_object_sha`)**：`{standards_lock['tag_object_sha']}`",
        f"- **Peeled Commit (`peeled_commit`)**：`{standards_lock['peeled_commit']}`",
        "",
        "## 3. 实际测试结果汇总 (`test_results`)",
        f"- **核验状态 (`verification_status`)**：`{test_results['verification_status']}`",
        f"- **执行命令 (`command`)**：`{test_results['command']}`",
        f"- **退出码 (`exit_code`)**：`{test_results['exit_code']}`",
        f"- **通过 / 失败用例数**：`{test_results['passed_count']} / {test_results['failed_count']}`",
        f"- **证据引用 (`evidence_ref`)**：`{test_results['evidence_ref']}`",
        "",
        "## 4. 远端 CI 关联 (`ci_run`)",
        f"- **Run ID (`run_id`)**：`{ci_run['run_id']}`",
        f"- **Push Run ID**：`{active_push_run_id}`",
        f"- **PR Run ID**：`{active_pr_run_id}`",
        f"- **工作流 (`workflow`)**：`{ci_run['workflow']}`",
        f"- **关联 Commit (`commit`)**：`{ci_run['commit']}`",
        f"- **核验状态 (`verification_status`)**：`{ci_run['verification_status']}`",
        f"- **证据引用 (`evidence_ref`)**：`{ci_run['evidence_ref']}`",
        "",
        "### 4.1 六项 CI / 快照核心概念区分 (`STD-034` / `STD-035`)",
        f"- **1. 基线源 Commit**：`{source_commit}`",
        f"- **2. Git 快照观测时间**：`{now_iso}`（快照有效时间 24 小时；过期标记 STALE 或 NOT_VERIFIABLE）",
        f"- **3. 最近一次已验证 CI Commit**：{verified_ci_text}",
        f"- **4. 当前候选 Commit**：`{code_candidate_commit}`",
        f"- **5. 当前待验证事项**：{pending_text}",
        f"- **6. 历史 CI 记录**：{hist_ci_text}（避免每次记录 CI 无限触发基线变更）",
        "",
    ]
    _h_pr9_ev: Optional[Dict[str, Any]] = None
    _h_snap_ev: Optional[Dict[str, Any]] = None
    _h_019_ev: Optional[Dict[str, Any]] = None
    _h_act_ev: Optional[Dict[str, Any]] = None
    if project_id == "ai-engineering-standards" and (project_root / "docs" / "release-evidence").exists():
        _hp_pr9 = project_root / "docs" / "release-evidence" / "v3.0.0-reissue.json"
        if _hp_pr9.exists():
            _hok, _, _hev = load_release_evidence(project_root, _hp_pr9)
            if _hok:
                _h_pr9_ev = _hev
        _hp_snap = project_root / "docs" / "release-evidence" / "std018-current-snapshot.json"
        if _hp_snap.exists():
            _hok, _, _hev = load_release_evidence(project_root, _hp_snap)
            if _hok:
                _h_snap_ev = _hev
        _hp_019 = project_root / "docs" / "release-evidence" / "std019-final-release.json"
        if _hp_019.exists():
            _hok, _, _hev = load_release_evidence(project_root, _hp_019)
            if _hok:
                _h_019_ev = _hev
        _hok, _, _hev = load_release_evidence(project_root, resolve_release_evidence_path(project_root))
        if _hok:
            _h_act_ev = _hev

    if project_id == "ai-engineering-standards" and _h_pr9_ev and _h_snap_ev and _h_019_ev:
        md_lines.extend([
            "### 4.2 PR9 历史发布凭证 (PR9_HISTORICAL_RELEASE_EVIDENCE)",
            f"- **PR9 发布凭证快照**：COMMIT_HASH={_h_pr9_ev['candidate_commit']}",
            f"- **当前候选 Commit**：`{_h_pr9_ev['candidate_commit']}`",
            f"- **本地 HEAD (`local_head`)**：`{_h_pr9_ev['snapshot_commit']}`",
            f"- **最近一次已验证 CI Commit**：`{_h_pr9_ev['last_verified_ci_commit']}`",
            f"- **关联 Commit (`commit`)**：`{_h_pr9_ev['candidate_commit']}`",
            f"- **Push Run ID**：`{_h_pr9_ev['push_run_id']}`",
            f"- **PR Run ID**：`{_h_pr9_ev['pr_run_id']}`",
            "- **核验状态 (`verification_status`)**：`PASS`",
            f"- **通过 / 失败用例数**：`{_h_pr9_ev['test_count']} / 0`",
            "- **工作流 (`workflow`)**：`.github/workflows/standards-ci.yml`",
            f"- **PR 编号 (`pr_number`)**：`{_h_pr9_ev['pr_number']}`",
            f"- **PR 状态 (`pr_status`)**：`{_h_pr9_ev['pr_status']}`",
            f"- **PR HEAD (`pr_head`)**：`{_h_pr9_ev['candidate_commit']}`",
            f"- **主干 HEAD (`main_head`)**：`{_h_pr9_ev['main_head']}`",
            "- **旧 Tag 状态 (`old_tag`)**：`v3.0.0`",
            f"- **旧 Tag 删除状态 (`old_tag_deleted`)**：`{str(_h_pr9_ev.get('old_tag_deleted', True)).lower()}`",
            f"- **原 Tag Object SHA (`old_tag_object`)**：`{_h_pr9_ev['old_tag_object']}`",
            f"- **原 Peeled Commit (`old_tag_peeled_commit`)**：`{_h_pr9_ev['old_tag_peeled_commit']}`",
            f"- **旧 Tag 本地 Bundle 备份 SHA256 (`old_tag_bundle_sha256`)**：`{_h_pr9_ev['old_tag_bundle_sha256']}`",
            f"- **发布流程状态 (`release_flow_status`)**：`{_h_pr9_ev['release_flow_status']}`",
            "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
            "",
            "### 4.3 Std-018 历史工程快照与治理追踪 (STD018_CURRENT_SNAPSHOT)",
            f"- **任务编号 (`task_id`)**：`{_h_snap_ev.get('task_id', 'Std-018-V3-0-0-REISSUE-CURRENT-BASELINE-HANDOFF-ALIGNMENT')}`",
            f"- **当前候选 Commit**：`{_h_snap_ev['candidate_commit']}`",
            f"- **本地 HEAD (`local_head`)**：`{_h_snap_ev['snapshot_commit']}`",
            f"- **最近一次已验证 CI Commit**：`{_h_snap_ev['last_verified_ci_commit']}`",
            f"- **关联 Commit (`commit`)**：`{_h_snap_ev['candidate_commit']}`",
            f"- **Push Run ID**：`{_h_snap_ev['push_run_id']}`",
            f"- **PR Run ID**：`{_h_snap_ev['pr_run_id']}`",
            "- **核验状态 (`verification_status`)**：`PASS`",
            f"- **通过 / 失败用例数**：`{_h_snap_ev['test_count']} / 0`",
            "- **工作流 (`workflow`)**：`.github/workflows/standards-ci.yml`",
            f"- **PR 编号 (`pr_number`)**：`{_h_snap_ev['pr_number']}`",
            f"- **PR 状态 (`pr_status`)**：`{_h_snap_ev['pr_status']}`",
            f"- **PR HEAD (`pr_head`)**：`{_h_snap_ev['candidate_commit']}`",
            f"- **主干 HEAD (`main_head`)**：`{_h_snap_ev['main_head']}`",
            "- **旧 Tag 状态 (`old_tag`)**：`v3.0.0`",
            f"- **旧 Tag 删除状态 (`old_tag_deleted`)**：`{str(_h_snap_ev.get('old_tag_deleted', True)).lower()}`",
            f"- **原 Tag Object SHA (`old_tag_object`)**：`{_h_snap_ev['old_tag_object']}`",
            f"- **原 Peeled Commit (`old_tag_peeled_commit`)**：`{_h_snap_ev['old_tag_peeled_commit']}`",
            f"- **旧 Tag 本地 Bundle 备份 SHA256 (`old_tag_bundle_sha256`)**：`{_h_snap_ev['old_tag_bundle_sha256']}`",
            f"- **发布流程状态 (`release_flow_status`)**：`{_h_snap_ev['release_flow_status']}`",
            "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
            "",
            "### 4.4 Std-019 最终发布证据与发布后收口 (STD019_FINAL_RELEASE)",
            "- **核验状态 (`verification_status`)**：`PASS`",
            f"- **任务编号 (`task_id`)**：`{_h_019_ev.get('task_id', 'Std-019-V3-0-0-POST-RELEASE-CLOSEOUT')}`",
            f"- **正式发布 Tag (`release_tag`)**：`{_h_019_ev['release_tag']}`",
            f"- **Tag Object SHA (`tag_object_sha`)**：`{_h_019_ev['tag_object_sha']}`",
            f"- **Peeled Commit (`peeled_commit`)**：`{_h_019_ev['peeled_commit']}`",
            f"- **代码候选 Commit (`candidate_commit`)**：`{_h_019_ev['candidate_commit']}`",
            f"- **文档快照 Commit (`snapshot_commit`)**：`{_h_019_ev['snapshot_commit']}`",
            f"- **最新已验证 CI Commit (`last_verified_ci_commit`)**：`{_h_019_ev['last_verified_ci_commit']}`",
            f"- **Push Run ID**：`{_h_019_ev.get('main_ci_run_id') or _h_019_ev['push_run_id']}`",
            f"- **PR Run ID**：`{_h_019_ev['pr_run_id']}`",
            f"- **PR 编号与状态**：PR #{_h_019_ev['pr_number']}（状态：`{_h_019_ev['pr_status']}`）",
            f"- **PR 合并者 (`pr_merged_by`)**：`{_h_019_ev['pr_merged_by']}`",
            f"- **发布时 main HEAD (`main_head`)**：`{_h_019_ev['main_head']}`",
            f"- **测试用例数**：`{_h_019_ev['test_count']} tests PASS`",
            f"- **Tag 发布状态 (`tag_publish_status`)**：`{_h_019_ev['tag_publish_status']}`",
            f"- **发布流程状态 (`release_flow_status`)**：`{_h_019_ev['release_flow_status']}`",
            f"- **旧 Tag 删除状态**：`OLD_TAG_DELETED={str(_h_019_ev.get('old_tag_deleted', True)).lower()}`",
            "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
        ])
        if _h_act_ev and str(_h_act_ev.get("version", "")).lstrip("v") != str(_h_019_ev.get("version", "")).lstrip("v"):
            md_lines.extend([
                "",
                "### 4.5 Std-020 最终发布证据与发布后收口 (STD020_FINAL_RELEASE)",
                "- **核验状态 (`verification_status`)**：`PASS`",
                f"- **任务编号 (`task_id`)**：`{_h_act_ev.get('task_id', 'Std-020-CONSUMER-FEEDBACK-TOOLCHAIN-REMEDIATION')}`",
                f"- **正式发布 Tag (`release_tag`)**：`{_h_act_ev.get('release_tag', 'v' + str(_h_act_ev.get('version', '')))}`",
                f"- **Tag Object SHA (`tag_object_sha`)**：`{_h_act_ev.get('tag_object_sha')}`",
                f"- **Peeled Commit (`peeled_commit`)**：`{_h_act_ev.get('peeled_commit')}`",
                f"- **代码候选 Commit (`candidate_commit`)**：`{_h_act_ev['candidate_commit']}`",
                f"- **文档快照 Commit (`snapshot_commit`)**：`{_h_act_ev['snapshot_commit']}`",
                f"- **最新已验证 CI Commit (`last_verified_ci_commit`)**：`{_h_act_ev['last_verified_ci_commit']}`",
                f"- **Push Run ID**：`{_h_act_ev.get('main_ci_run_id') or _h_act_ev['push_run_id']}`",
                f"- **PR Run ID**：`{_h_act_ev['pr_run_id']}`",
                f"- **PR 编号与状态**：PR #{_h_act_ev['pr_number']}（状态：`{_h_act_ev['pr_status']}`）",
                f"- **PR 合并者 (`pr_merged_by`)**：`{_h_act_ev.get('pr_merged_by')}`",
                f"- **发布时 main HEAD (`main_head`)**：`{_h_act_ev['main_head']}`",
                f"- **测试用例数**：`{_h_act_ev['test_count']} tests PASS`",
                f"- **Tag 发布状态 (`tag_publish_status`)**：`{_h_act_ev.get('tag_publish_status')}`",
                f"- **发布流程状态 (`release_flow_status`)**：`{_h_act_ev.get('release_flow_status')}`",
                "- **证据引用 (`evidence_ref`)**：`.github/workflows/standards-ci.yml`",
            ])
        else:
            cand_pr_num_disp = str(eff_cand_pr_number) if eff_cand_pr_number is not None else "NOT_ASSIGNED"
            sec45_lines = [
                "",
                "### 4.5 当前发布候选状态与实时 PR 身份 (CURRENT_CANDIDATE_PR)",
                f"- **任务编号 (`task_id`)**：`{task_id}`",
                f"- **候选版本 (`candidate_version`)**：`{resolved_version}`",
                f"- **当前候选 PR 编号 (`candidate_pr_number`)**：`{cand_pr_num_disp}`",
                f"- **当前候选 PR 状态 (`candidate_pr_status`)**：`{effective_pr_status}`",
                f"- **PR 状态标记 (`PR_STATE`)**：`{pr_state_str}`",
                f"- **PR 草稿标记 (`PR_DRAFT`)**：`{str(pr_draft_bool).lower()}`",
                f"- **当前候选 PR Base (`candidate_pr_base`)**：`{eff_cand_pr_base}`",
                f"- **当前候选 Commit (`candidate_commit`)**：`{code_candidate_commit}`",
                "- **实时 PR HEAD 核验方式 (`live_pr_head_verification`)**：`GITHUB_PR_API_REQUIRED`（实时 PR HEAD 与 PR 状态通过 GitHub PR API / Actions Event 在线核验，不自引用静态写入）",
                "- **实时 CI 运行记录方式 (`ci_runtime_record`)**：`GITHUB_STEP_SUMMARY`（实时 PR HEAD 与 CI Run ID 由 CI Runtime 与 Step Summary 记录）",
                f"- **状态快照观测时间 (`candidate_observed_at`)**：`{now_iso}`",
                f"- **当前最新已发布正式 Tag (`LATEST_RELEASED_TAG`)**：`{_h_019_ev['release_tag']}`",
            ]
            if effective_pr_status == "MERGED" and verified_merge_commit and verified_merged_by:
                sec45_lines.extend([
                    f"- **当前候选 PR Merge Commit (`candidate_pr_merge_commit`)**：`{verified_merge_commit}`",
                    f"- **当前候选 PR 合并者 (`candidate_pr_merged_by`)**：`{verified_merged_by}`",
                ])
                if is_current_version_released:
                    rel_desc = f"{pr_label} 已由 `{verified_merged_by}` 合入 main（Merge Commit: `{verified_merge_commit}`），正式 Tag `v{resolved_version}` 已签发"
                else:
                    rel_desc = f"{pr_label} 已由 `{verified_merged_by}` 合入 main（Merge Commit: `{verified_merge_commit}`），尚未创建正式 `v{resolved_version}` Tag，待 main CI 全绿后由官方工作流自动签发"
            else:
                rel_desc = f"待 {pr_label} 经独立审查与 Owner 批准合入 main 后由 main CI 自动签发 v{resolved_version} Tag"
            sec45_lines.append(
                f"- **发布流程状态 (`RELEASE_STATUS`)**：`{cand_release_status}`（{rel_desc}）"
            )
            md_lines.extend(sec45_lines)
    else:
        md_lines.extend([
            "### 4.2 v3.0.0 一次性重发发布与 Tag 状态追踪",
            f"- **PR 编号 (`pr_number`)**：`{pr_number}`",
            f"- **PR 状态 (`pr_status`)**：`{effective_pr_status}`",
            f"- **PR HEAD (`pr_head`)**：`{pr_head}`",
            f"- **主干 HEAD (`main_head`)**：`{remote_head}`",
            f"- **旧 Tag 状态 (`old_tag`)**：`v{resolved_version}`",
            f"- **旧 Tag 删除状态 (`old_tag_deleted`)**：`{str(old_tag_deleted).lower()}`（已于远端删除，新 Tag 尚未创建）",
            "- **原 Tag Object SHA (`old_tag_object`)**：`325008af90a1e6dcc88ff714c9ec4e7ecee86ec6`",
            "- **原 Peeled Commit (`old_tag_peeled_commit`)**：`1d5cbbd6710bef749c8f79e9c1fd21dd14223b1b`",
            "- **旧 Tag 本地 Bundle 备份 SHA256 (`old_tag_bundle_sha256`)**：`45bc3e455fc06b96a669ba9d7c44195f5dfb4e42e55397d795200942e434ebfc`",
            f"- **发布流程状态 (`release_flow_status`)**：`{release_flow_status}`（PR #{pr_number} 已合入 main；待修复 main CI 历史 PR Run 关联后由 main CI 自动重建同名 Tag）" if effective_pr_status == "MERGED" else f"- **发布流程状态 (`release_flow_status`)**：`{release_flow_status}`（待 Owner 最终合入 PR #{pr_number} 后由 main CI 自动重建同名 Tag）",
        ])

    md_lines.extend([
        "",
        "## 5. 已完成事项 (`completed_items`)",
        comp_md,
        "",
        "## 6. 未完成事项 (`pending_items`)",
        pend_md,
        "",
        "## 7. 阻断项 (`blockers`)",
        block_md,
        "",
        "## 8. 已批准决策 (`approved_decisions`)",
        "| 决策 ID | 决策摘要 | 审批状态 | 审批证据引用 |",
        "|:---|:---|:---|:---|",
        approved_md,
        "",
        "## 9. 待审批建议事项 (`proposed_items`)",
        "| 提案 ID | 提案内容 | 需 Owner 批准 | 状态 |",
        "|:---|:---|:---|:---|",
        proposed_md,
        "",
        "## 10. 下一会话启动指引 (`next_session_guide`)",
        "### 10.1 新会话必读顺序 (`mandatory_read_order`)",
        read_md,
        "",
        "### 10.2 启动实时重核验命令 (`verification_commands`)",
        cmd_md,
        "",
        "### 10.3 立即执行事项 (`immediate_next_steps`)",
        step_md,
        "",
    ])
    markdown_text = "\n".join(md_lines)
    canonical_doc_sha = compute_canonical_document_sha256(markdown_text)
    markdown_text = markdown_text.replace(f'content_sha256: "{content_sha}"', f'content_sha256: "{canonical_doc_sha}"')
    return True, [], payload, markdown_text


def write_handoff_files(
    project_root: Path,
    task_id: str,
    version: Optional[str] = None,
    write_canonical_entrypoint: bool = True,
    write_task_snapshot: bool = True,
    write_temporary: bool = False,
    allow_snapshot_overwrite: bool = False,
    **kwargs: Any,
) -> Tuple[bool, List[str], Dict[str, str]]:
    project_root = project_root.resolve()
    ok, errors, payload, md_text = build_handoff_payload(
        project_root=project_root,
        task_id=task_id,
        version=version,
        **kwargs,
    )
    if not ok or payload is None or md_text is None:
        return False, errors, {}

    written_paths: Dict[str, str] = {}
    ver_tag = payload["version"]

    if write_task_snapshot:
        handoff_dir = project_root / "handoff"
        handoff_dir.mkdir(parents=True, exist_ok=True)
        task_snapshot_path = handoff_dir / f"{task_id}-{ver_tag}-handoff.md"
        if task_snapshot_path.exists() and not allow_snapshot_overwrite:
            return (
                False,
                [
                    f"HISTORICAL_HANDOFF_OVERWRITE_FORBIDDEN: '{task_snapshot_path.relative_to(project_root)}' already exists; refusing to overwrite historical handoff evidence"
                ],
                {},
            )
        snapshot_md = md_text.replace("primary_entrypoint: true", "primary_entrypoint: false", 1)
        snap_sha = compute_canonical_document_sha256(snapshot_md)
        snapshot_md = re.sub(
            r'content_sha256:\s*"?(?:sha256:)?[0-9a-f]{64}"?',
            f'content_sha256: "{snap_sha}"',
            snapshot_md,
            count=1,
        )
        task_snapshot_path.write_text(snapshot_md, encoding="utf-8")
        written_paths["task_snapshot"] = str(task_snapshot_path.relative_to(project_root)).replace("\\", "/")

    if write_canonical_entrypoint:
        docs_handoff = project_root / "docs" / "CROSS-SESSION-HANDOFF.md"
        docs_handoff.parent.mkdir(parents=True, exist_ok=True)
        docs_handoff.write_text(md_text, encoding="utf-8")
        written_paths["canonical_entrypoint"] = str(docs_handoff.relative_to(project_root)).replace("\\", "/")

        json_out = project_root / ".artifacts" / "handoff" / "cross_session_handoff.json"
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written_paths["handoff_json"] = str(json_out.relative_to(project_root)).replace("\\", "/")

    if write_temporary:
        temp_dir = project_root / ".artifacts" / "handoff" / "temporary"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{task_id}-RETURN.md"
        temp_md = md_text.replace('handoff_type: "DURABLE"', 'handoff_type: "TEMPORARY"').replace(
            "HANDOFF_TYPE=DURABLE", "HANDOFF_TYPE=TEMPORARY"
        ).replace(
            "primary_entrypoint: true", "primary_entrypoint: false", 1
        )
        temp_sha = compute_canonical_document_sha256(temp_md)
        temp_md = re.sub(
            r'content_sha256:\s*"?(?:sha256:)?[0-9a-f]{64}"?',
            f'content_sha256: "{temp_sha}"',
            temp_md,
            count=1,
        )
        temp_path.write_text(temp_md, encoding="utf-8")
        written_paths["temporary_handoff"] = str(temp_path.relative_to(project_root)).replace("\\", "/")

    return True, [], written_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or verify STD-020 CROSS_SESSION_HANDOFF")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--standards-root", default=None, help="Path to AI-Engineering-Standards root")
    parser.add_argument("--task-id", default=None, help="Task ID")
    parser.add_argument("--version", default=None, help="Product version (default: from VERSION file)")
    parser.add_argument(
        "--handoff-type",
        choices=["DURABLE", "TEMPORARY"],
        default="DURABLE",
        help="Handoff durability type",
    )
    parser.add_argument(
        "--status",
        choices=["IN_PROGRESS", "BLOCKED", "COMPLETED"],
        default="IN_PROGRESS",
        help="Task completion status",
    )
    parser.add_argument("--write-temporary", action="store_true", help="Also generate temporary handoff artifact")
    parser.add_argument("--no-task-snapshot", action="store_true", help="Do not write handoff/<TASK>-<VER>-handoff.md")
    parser.add_argument("--no-canonical-entrypoint", action="store_true", help="Do not write docs/CROSS-SESSION-HANDOFF.md")
    parser.add_argument("--source-commit", default=None, help="Override source commit SHA")
    parser.add_argument("--captured-at", default=None, help="Fixed ISO-8601 UTC timestamp for deterministic testing")
    parser.add_argument("--test-status", default=None, help="Test verification status (PASS, FAIL, etc.)")
    parser.add_argument("--test-passed", type=int, default=None, help="Number of passed tests")
    parser.add_argument("--test-failed", type=int, default=None, help="Number of failed tests")
    parser.add_argument("--test-command", default=None, help="Test execution command")
    parser.add_argument("--test-evidence-ref", default=None, help="Relative path to test evidence log")
    parser.add_argument("--ci-run-id", default=None, help="GitHub Actions CI Run ID")
    parser.add_argument("--ci-status", default=None, help="CI verification status (PASS, NOT_RUN, etc.)")
    parser.add_argument(
        "--completed-item",
        action="append",
        dest="completed_items",
        default=None,
        help="Completed item description (can specify multiple)",
    )
    parser.add_argument(
        "--pending-item",
        action="append",
        dest="pending_items",
        default=None,
        help="Pending item description (can specify multiple)",
    )
    parser.add_argument("--candidate-commit", default=None, help="Override candidate commit SHA")
    parser.add_argument("--snapshot-commit", default=None, help="Override snapshot commit SHA")
    parser.add_argument("--last-verified-ci-commit", default=None, help="Override last verified CI commit SHA")
    parser.add_argument("--ci-commit", default=None, help="Explicit CI tested commit SHA")
    parser.add_argument("--push-run-id", default=None, help="Push CI Run ID")
    parser.add_argument("--pr-run-id", default=None, help="PR CI Run ID")
    parser.add_argument("--pr-head", default=None, help="PR HEAD commit SHA")
    parser.add_argument("--pr-number", type=int, default=None, help="Legacy alias for --candidate-pr-number")
    parser.add_argument("--pr-status", default=None, help="Legacy alias for --candidate-pr-status (DRAFT, OPEN, MERGED)")
    parser.add_argument("--candidate-pr-number", type=int, default=None, help="Current candidate PR number")
    parser.add_argument("--candidate-pr-status", default=None, help="Current candidate PR status (DRAFT, OPEN, MERGED, CLOSED)")
    parser.add_argument("--candidate-pr-head", default=None, help="Current candidate PR HEAD commit SHA")
    parser.add_argument("--candidate-pr-base", default=None, help="Current candidate PR base branch (must be 'main')")
    parser.add_argument("--candidate-pr-draft", choices=["true", "false"], default=None, help="Current candidate PR draft flag (true/false)")
    parser.add_argument("--candidate-pr-merge-event", default=None, help="Path to GitHub PR API JSON proving verified merge event")
    parser.add_argument("--release-flow-status", default="IN_PROGRESS", help="Release flow status")
    parser.add_argument("--old-tag-deleted", default=None, help="Expected old tag deleted state (true/false)")
    parser.add_argument("--pending-verifications", default=None, help="Pending verifications statement")
    parser.add_argument(
        "--allow-snapshot-overwrite",
        action="store_true",
        help="Allow overwriting existing handoff/<TASK>-<VER>-handoff.md snapshot",
    )
    parser.add_argument("--release-evidence", default=None, help="Path to release evidence JSON file")
    parser.add_argument("--snapshot-evidence", default=None, help="Path to snapshot evidence JSON file")
    parser.add_argument("--final-evidence", default=None, help="Path to final release evidence JSON file (Std-019)")
    parser.add_argument("--output", default=None, help="Target markdown path for verification (default: docs/CROSS-SESSION-HANDOFF.md)")
    parser.add_argument("--verify-only", action="store_true", help="Verify handoff generation against committed file")
    parser.add_argument(
        "--require-live-pr",
        action="store_true",
        help="Require real GitHub PR API verification to succeed (blocks if API unavailable)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    standards_root = resolve_standards_root(args.standards_root)

    test_override = None
    if args.test_status:
        test_override = {
            "verification_status": args.test_status,
            "command": args.test_command or "python -m unittest discover -s tests -v",
            "exit_code": 0 if args.test_status == "PASS" else 1,
            "passed_count": args.test_passed if args.test_passed is not None else 0,
            "failed_count": args.test_failed if args.test_failed is not None else 0,
            "evidence_ref": args.test_evidence_ref or "NONE",
        }
    ci_override = None
    run_id_val = args.ci_run_id or args.push_run_id or args.pr_run_id
    if run_id_val or args.ci_status or args.ci_commit:
        effective_ci_com = (
            args.ci_commit
            or args.last_verified_ci_commit
            or args.candidate_commit
            or args.snapshot_commit
            or "NOT_RUN"
        )
        ci_override = {
            "run_id": int(run_id_val) if (run_id_val and str(run_id_val).isdigit()) else run_id_val,
            "workflow": ".github/workflows/standards-ci.yml",
            "commit": effective_ci_com,
            "verification_status": args.ci_status or "PASS",
            "evidence_ref": ".github/workflows/standards-ci.yml",
        }

    old_tag_deleted_val = (
        (str(args.old_tag_deleted).lower() == "true")
        if args.old_tag_deleted is not None
        else True
    )

    task_id_val = args.task_id or "Std-019-V3-0-0-POST-RELEASE-CLOSEOUT"
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
    cli_allow_offline = not bool(
        args.require_live_pr
        or (not args.verify_only and str(args.candidate_pr_status or args.pr_status or "").strip().upper() == "MERGED")
    )
    effective_captured_at = args.captured_at
    if effective_captured_at is None and not args.verify_only:
        effective_captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok, errors, payload, md_text = build_handoff_payload(
        project_root=project_root,
        task_id=task_id_val,
        version=args.version,
        handoff_type=args.handoff_type,
        status=args.status,
        completed_items=args.completed_items,
        pending_items=args.pending_items,
        source_commit_override=args.source_commit,
        candidate_commit_override=args.candidate_commit,
        snapshot_commit_override=args.snapshot_commit,
        last_verified_ci_commit=args.last_verified_ci_commit,
        ci_commit=args.ci_commit,
        push_run_id=args.push_run_id,
        pr_run_id=args.pr_run_id,
        pr_head_override=args.pr_head,
        old_tag_deleted=old_tag_deleted_val,
        release_flow_status=args.release_flow_status,
        pr_status=args.pr_status,
        pr_number=args.pr_number,
        candidate_pr_number=args.candidate_pr_number,
        candidate_pr_status=args.candidate_pr_status,
        candidate_pr_head=args.candidate_pr_head,
        candidate_pr_base=args.candidate_pr_base,
        candidate_pr_draft=candidate_pr_draft_val,
        candidate_pr_merge_event=candidate_pr_merge_event_obj,
        pending_verifications=args.pending_verifications,
        test_results_override=test_override,
        ci_run_override=ci_override,
        captured_at=effective_captured_at,
        release_evidence_path=args.release_evidence,
        snapshot_evidence_path=args.snapshot_evidence,
        final_evidence_path=args.final_evidence,
        standards_root=standards_root,
        allow_offline=cli_allow_offline,
    )
    if not ok or payload is None or md_text is None:
        print(f"[FAIL] Cross-session handoff generation blocked ({len(errors)} issues):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    if args.verify_only:
        committed_path = Path(args.output).resolve() if args.output else project_root / "docs" / "CROSS-SESSION-HANDOFF.md"
        if not committed_path.exists():
            print(f"[FAIL] Committed handoff file does not exist: {committed_path}")
            sys.exit(1)
        actual_content = committed_path.read_text(encoding="utf-8")
        actual_fm = yaml.safe_load(actual_content.split("---")[1]) if actual_content.startswith("---") else {}
        expected_fm = yaml.safe_load(md_text.split("---")[1])

        mismatches: List[str] = []
        for fld in ("document_id", "document_type", "project_id", "status", "approval_status"):
            if actual_fm.get(fld) != expected_fm.get(fld):
                mismatches.append(f"field '{fld}': committed='{actual_fm.get(fld)}' != expected='{expected_fm.get(fld)}'")

        actual_digest = compute_canonical_document_sha256(actual_content)
        if actual_fm.get("content_sha256") != actual_digest:
            mismatches.append(
                f"field 'content_sha256': committed='{actual_fm.get('content_sha256')}' does not match actual document digest '{actual_digest}'"
            )

        # Semantic fact verification from independent release evidence (STD-034 / STD-035)
        pr9_ev_path = (
            Path(args.release_evidence).resolve()
            if args.release_evidence
            else project_root / "docs" / "release-evidence" / "v3.0.0-reissue.json"
        )
        ok_ev, ev_errors, release_evidence = load_release_evidence(project_root, pr9_ev_path)
        if not ok_ev or release_evidence is None:
            print(f"[FAIL] Cross-session handoff verification blocked: release evidence error ({len(ev_errors)} issues):")
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
            print(f"[FAIL] Cross-session handoff verification blocked: snapshot evidence error ({len(snap_errors)} issues):")
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
            print(f"[FAIL] Cross-session handoff verification blocked: final release evidence error ({len(final_errors)} issues):")
            for e in final_errors:
                print(f"  - {e}")
            sys.exit(1)

        expected_pr9_facts = {
            "candidate_commit": release_evidence["candidate_commit"],
            "snapshot_commit": release_evidence["snapshot_commit"],
            "last_verified_ci_commit": release_evidence["last_verified_ci_commit"],
            "ci_commit": release_evidence["last_verified_ci_commit"],
            "ci_run_id": release_evidence["push_run_id"],
            "push_run_id": release_evidence["push_run_id"],
            "pr_run_id": release_evidence["pr_run_id"],
            "ci_status": release_evidence["ci_status"],
            "test_count": release_evidence["test_count"],
            "pr_status": release_evidence["pr_status"],
            "main_head": release_evidence.get("main_head"),
            "release_flow_status": release_evidence["release_flow_status"],
            "old_tag_deleted": release_evidence["old_tag_deleted"],
        }
        pr9_mismatches = verify_handoff_semantic_facts(
            actual_content, expected_pr9_facts, scope="PR9_HISTORICAL_RELEASE_EVIDENCE"
        )
        mismatches.extend([f"[PR9_SCOPE] {m}" for m in pr9_mismatches])

        if args.task_id and args.task_id not in (
            "STANDARDS-BASELINE-SYNC-GOVERNANCE-IMPLEMENTATION-001",
            "Std-019-V3-0-0-POST-RELEASE-CLOSEOUT",
            "Std-020-CONSUMER-FEEDBACK-TOOLCHAIN-REMEDIATION",
        ):
            expected_task_id = args.task_id
        else:
            expected_task_id = snapshot_evidence.get("task_id", "Std-018-V3-0-0-REISSUE-CURRENT-BASELINE-HANDOFF-ALIGNMENT")

        if args.task_id:
            m_top_task = re.search(r'^TASK_ID=([^\r\n]+)', actual_content, re.M)
            if not m_top_task or m_top_task.group(1).strip() != args.task_id:
                actual_top = m_top_task.group(1).strip() if m_top_task else "<MISSING>"
                mismatches.append(f"[TOP_TASK_ID] committed='{actual_top}' != expected='{args.task_id}'")

        expected_snapshot_facts = {
            "task_id": expected_task_id,
            "candidate_commit": snapshot_evidence["candidate_commit"],
            "snapshot_commit": snapshot_evidence["snapshot_commit"],
            "last_verified_ci_commit": snapshot_evidence["last_verified_ci_commit"],
            "ci_commit": snapshot_evidence["last_verified_ci_commit"],
            "ci_run_id": snapshot_evidence["push_run_id"],
            "push_run_id": snapshot_evidence["push_run_id"],
            "pr_run_id": snapshot_evidence["pr_run_id"],
            "ci_status": snapshot_evidence["ci_status"],
            "test_count": snapshot_evidence["test_count"],
            "pr_status": snapshot_evidence["pr_status"],
            "main_head": snapshot_evidence.get("main_head"),
            "release_flow_status": snapshot_evidence["release_flow_status"],
            "old_tag_deleted": snapshot_evidence["old_tag_deleted"],
        }
        snap_mismatches = verify_handoff_semantic_facts(
            actual_content, expected_snapshot_facts, scope="STD018_CURRENT_SNAPSHOT"
        )
        mismatches.extend([f"[STD018_SCOPE] {m}" for m in snap_mismatches])

        expected_final_facts = {
            "task_id": "Std-019-V3-0-0-POST-RELEASE-CLOSEOUT",
            "candidate_commit": final_evidence["candidate_commit"],
            "snapshot_commit": final_evidence["snapshot_commit"],
            "last_verified_ci_commit": final_evidence["last_verified_ci_commit"],
            "ci_commit": final_evidence["last_verified_ci_commit"],
            "ci_run_id": final_evidence.get("main_ci_run_id") or final_evidence["push_run_id"],
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
        final_mismatches = verify_handoff_semantic_facts(
            actual_content, expected_final_facts, scope="STD019_FINAL_RELEASE"
        )
        mismatches.extend([f"[STD019_SCOPE] {m}" for m in final_mismatches])
        if not args.final_evidence:
            active_ev_path = resolve_release_evidence_path(project_root)
            if active_ev_path.resolve() != final_ev_path.resolve():
                ok_act, act_errors, act_ev = load_release_evidence(project_root, active_ev_path)
                if not ok_act or act_ev is None:
                    print(f"[FAIL] Cross-session handoff verification blocked: active release evidence error ({len(act_errors)} issues):")
                    for e in act_errors:
                        print(f"  - {e}")
                    sys.exit(1)
                expected_active_facts = {
                    "task_id": act_ev.get("task_id", "Std-020-CONSUMER-FEEDBACK-TOOLCHAIN-REMEDIATION"),
                    "candidate_commit": act_ev["candidate_commit"],
                    "snapshot_commit": act_ev["snapshot_commit"],
                    "last_verified_ci_commit": act_ev["last_verified_ci_commit"],
                    "ci_commit": act_ev["last_verified_ci_commit"],
                    "ci_run_id": act_ev.get("main_ci_run_id") or act_ev["push_run_id"],
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
                act_mismatches = verify_handoff_semantic_facts(
                    actual_content, expected_active_facts, scope="STD020_FINAL_RELEASE"
                )
                mismatches.extend([f"[STD020_SCOPE] {m}" for m in act_mismatches])
        mismatches.extend(
            [f"[GIT_SNAPSHOT] {m}" for m in verify_git_snapshot_facts(project_root, actual_content, "handoff")]
        )

        # Shared F13+F14 Candidate PR & Live PR API contract verification (only on candidate non-released versions)
        ver_file_chk = project_root / "VERSION"
        cur_ver_str = ver_file_chk.read_text(encoding="utf-8").strip().lstrip("v") if ver_file_chk.exists() else payload["version"].lstrip("v")
        active_ev_for_cand = resolve_release_evidence_path(project_root)
        active_ev_is_current_released = False
        if active_ev_for_cand.is_file():
            ok_ae, _, ae_data = load_release_evidence(project_root, active_ev_for_cand)
            if ok_ae and ae_data and str(ae_data.get("version", "")).lstrip("v") == cur_ver_str and ae_data.get("release_flow_status") == "RELEASED":
                active_ev_is_current_released = True

        if not active_ev_is_current_released and "CURRENT_CANDIDATE_PR" in actual_content:
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

            exp_cand_facts: Dict[str, Any] = {}
            exp_pr_n = args.candidate_pr_number if args.candidate_pr_number is not None else args.pr_number
            exp_pr_s = args.candidate_pr_status if args.candidate_pr_status is not None else args.pr_status
            if exp_pr_n is not None:
                exp_cand_facts["candidate_pr_number"] = exp_pr_n
            if exp_pr_s is not None:
                exp_cand_facts["candidate_pr_status"] = str(exp_pr_s).strip().upper()
            if args.candidate_pr_head is not None:
                exp_cand_facts["candidate_pr_head"] = args.candidate_pr_head.strip()
            if args.candidate_pr_base is not None:
                exp_cand_facts["candidate_pr_base"] = args.candidate_pr_base.strip()
            if candidate_pr_draft_val is not None:
                exp_cand_facts["pr_draft"] = candidate_pr_draft_val
            if args.candidate_commit is not None:
                exp_cand_facts["candidate_commit"] = args.candidate_commit.strip()

            cand_errs, live_pr_details, live_pr_status = verify_handoff_candidate_pr_facts(
                content=actual_content,
                version_str=cur_ver_str,
                repository=payload["standards_lock"]["repository"],
                project_root=project_root,
                historical_merge_commits=hist_merge_shas,
                historical_candidate_commits=hist_cand_shas,
                expected_facts=exp_cand_facts or None,
                verify_live_pr=True,
                require_live_pr=bool(args.require_live_pr or os.environ.get("GITHUB_ACTIONS") == "true"),
                is_current_version_released=active_ev_is_current_released,
                return_details=True,
            )
            mismatches.extend([f"[CURRENT_CANDIDATE_PR] {m}" for m in cand_errs])
            if live_pr_status:
                print(
                    f"[INFO] Live PR Identity Status: {live_pr_status}"
                    + (
                        f" (PR #{live_pr_details.get('candidate_pr_number')}, head={live_pr_details.get('pr_head_sha')}, state={live_pr_details.get('pr_state')}, draft={live_pr_details.get('pr_draft')}, ancestry={live_pr_details.get('ancestry_status')})"
                        if live_pr_details
                        else ""
                    )
                )
        elif not active_ev_is_current_released:
            mismatches.append(
                "[CURRENT_CANDIDATE_PR] SCOPE_SECTION_MISSING: Active candidate handoff must contain CURRENT_CANDIDATE_PR section"
            )

        if mismatches:
            print(f"[FAIL] Committed handoff mismatches expected facts ({len(mismatches)} issues):")
            for m in mismatches:
                print(f"  - {m}")
            sys.exit(1)

        print(f"[PASS] Cross-session handoff verified against committed file: {committed_path}")
        sys.exit(0)

    ok, errors, written = write_handoff_files(
        project_root=project_root,
        task_id=task_id_val,
        version=args.version,
        handoff_type=args.handoff_type,
        status=args.status,
        completed_items=args.completed_items,
        pending_items=args.pending_items,
        allow_snapshot_overwrite=args.allow_snapshot_overwrite,
        write_canonical_entrypoint=not args.no_canonical_entrypoint,
        write_task_snapshot=not args.no_task_snapshot,
        write_temporary=args.write_temporary,
        source_commit_override=args.source_commit,
        candidate_commit_override=args.candidate_commit,
        snapshot_commit_override=args.snapshot_commit,
        last_verified_ci_commit=args.last_verified_ci_commit,
        ci_commit=args.ci_commit,
        push_run_id=args.push_run_id,
        pr_run_id=args.pr_run_id,
        pr_head_override=args.pr_head,
        old_tag_deleted=old_tag_deleted_val,
        release_flow_status=args.release_flow_status,
        pr_status=args.pr_status,
        pr_number=args.pr_number,
        candidate_pr_number=args.candidate_pr_number,
        candidate_pr_status=args.candidate_pr_status,
        candidate_pr_head=args.candidate_pr_head,
        candidate_pr_base=args.candidate_pr_base,
        candidate_pr_draft=candidate_pr_draft_val,
        candidate_pr_merge_event=candidate_pr_merge_event_obj,
        pending_verifications=args.pending_verifications,
        test_results_override=test_override,
        ci_run_override=ci_override,
        captured_at=effective_captured_at,
        release_evidence_path=args.release_evidence,
        snapshot_evidence_path=args.snapshot_evidence,
        final_evidence_path=args.final_evidence,
        standards_root=standards_root,
        allow_offline=cli_allow_offline,
    )
    if not ok:
        print(f"[FAIL] Failed to write handoff files ({len(errors)} issues):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("[PASS] Cross-session handoff written successfully:")
    for k, v in written.items():
        print(f"  - {k}: {v}")


if __name__ == "__main__":
    main()
