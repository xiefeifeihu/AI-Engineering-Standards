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
    except Exception as e:
        return 1, str(e)


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
    standards_root: Optional[Path] = None,
) -> Tuple[bool, List[str], Optional[Dict[str, Any]], Optional[str]]:
    errors: List[str] = []
    project_root = project_root.resolve()
    std_root = resolve_standards_root(str(standards_root) if standards_root else None)
    now_iso = captured_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today_date = now_iso[:10]

    # Project ID and version
    manifest_path = project_root / "engineering-manifest.yaml"
    project_id = "ai-engineering-standards"
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            project_id = str((manifest.get("project") or {}).get("id") or project_id)
        except Exception:
            pass

    ver_file = project_root / "VERSION"
    if not ver_file.exists():
        errors.append("HANDOFF_MISSING_VERSION: VERSION file does not exist")
        resolved_version = (version or "3.0.0").lstrip("v")
    else:
        resolved_version = (version or ver_file.read_text(encoding="utf-8").strip()).lstrip("v")

    # 1 & 2. Auto-collect Git state, branch, and Commit
    rc_head, git_head = run_git(project_root, ["rev-parse", "HEAD"])
    if rc_head == 0 and re.match(r"^[0-9a-f]{40}$", git_head):
        local_head = git_head
    else:
        errors.append("HANDOFF_INVALID_COMMIT: Local Git HEAD is not a valid 40-character SHA")
        local_head = ""

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

    rc_branch, git_branch = run_git(project_root, ["branch", "--show-current"])
    branch_name = git_branch if rc_branch == 0 and git_branch else "HEAD"
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

    # 5. Auto-associate CI Run ID
    ci_run = ci_run_override or {
        "run_id": None,
        "workflow": ".github/workflows/standards-ci.yml",
        "commit": local_head or "NOT_RUN",
        "verification_status": "NOT_RUN",
        "evidence_ref": ".github/workflows/standards-ci.yml",
    }
    if ci_run.get("commit") in ("NOT_RUN", None, "") and local_head:
        ci_run["commit"] = local_head

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
        f"- **工作流 (`workflow`)**：`{ci_run['workflow']}`",
        f"- **关联 Commit (`commit`)**：`{ci_run['commit']}`",
        f"- **核验状态 (`verification_status`)**：`{ci_run['verification_status']}`",
        f"- **证据引用 (`evidence_ref`)**：`{ci_run['evidence_ref']}`",
        "",
        "### 4.1 六项 CI / 快照核心概念区分 (`STD-034` / `STD-035`)",
        f"- **1. 基线源 Commit**：`{source_commit}`",
        f"- **2. Git 快照观测时间**：`{captured_at}`（快照有效时间 24 小时；过期标记 STALE 或 NOT_VERIFIABLE）",
        "- **3. 最近一次已验证 CI Commit**：`c52f97a52c9080bc76e05684f996fd89653e1fa8`（Run 42747292971 / 42760791748 双平台全绿，215 tests PASS）",
        f"- **4. 当前候选 Commit**：`{local_head}`",
        "- **5. 当前待验证事项**：远端 GitHub Actions CI 双平台实测；严禁在推送前或运行完成前伪造 CI PASS",
        "- **6. 历史 CI 记录**：Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392, 42571376296, 42571381569, 42583709325, 42583717591, 42747292971, 42760791748（避免每次记录 CI 无限触发基线变更）",
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
    ]
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
        temp_path.write_text(temp_md, encoding="utf-8")
        written_paths["temporary_handoff"] = str(temp_path.relative_to(project_root)).replace("\\", "/")

    return True, [], written_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or verify STD-020 CROSS_SESSION_HANDOFF")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--standards-root", default=None, help="Path to AI-Engineering-Standards root")
    parser.add_argument("--task-id", required=True, help="Task ID")
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
    parser.add_argument(
        "--allow-snapshot-overwrite",
        action="store_true",
        help="Allow overwriting existing handoff/<TASK>-<VER>-handoff.md snapshot",
    )
    parser.add_argument("--verify-only", action="store_true", help="Verify handoff generation against committed file")
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
    if args.ci_run_id or args.ci_status:
        ci_override = {
            "run_id": int(args.ci_run_id) if (args.ci_run_id and args.ci_run_id.isdigit()) else args.ci_run_id,
            "workflow": ".github/workflows/standards-ci.yml",
            "commit": args.source_commit or "NOT_RUN",
            "verification_status": args.ci_status or "PASS",
            "evidence_ref": ".github/workflows/standards-ci.yml",
        }

    ok, errors, payload, md_text = build_handoff_payload(
        project_root=project_root,
        task_id=args.task_id,
        version=args.version,
        handoff_type=args.handoff_type,
        status=args.status,
        completed_items=args.completed_items,
        pending_items=args.pending_items,
        source_commit_override=args.source_commit,
        test_results_override=test_override,
        ci_run_override=ci_override,
        captured_at=args.captured_at,
        standards_root=standards_root,
    )
    if not ok or payload is None or md_text is None:
        print(f"[FAIL] Cross-session handoff generation blocked ({len(errors)} issues):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    if args.verify_only:
        committed_path = project_root / "docs" / "CROSS-SESSION-HANDOFF.md"
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

        if mismatches:
            print(f"[FAIL] Committed handoff mismatches expected facts ({len(mismatches)} issues):")
            for m in mismatches:
                print(f"  - {m}")
            sys.exit(1)

        print(f"[PASS] Cross-session handoff verified against committed file: {committed_path}")
        sys.exit(0)

    ok, errors, written = write_handoff_files(
        project_root=project_root,
        task_id=args.task_id,
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
        test_results_override=test_override,
        ci_run_override=ci_override,
        captured_at=args.captured_at,
        standards_root=standards_root,
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
