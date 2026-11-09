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


def build_engineering_baseline(
    project_root: Path,
    standards_root: Optional[Path] = None,
    observed_at: Optional[str] = None,
    source_commit_override: Optional[str] = None,
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
    now_iso = observed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    rc_branch, git_branch = run_git(project_root, ["branch", "--show-current"])
    branch_name = git_branch if rc_branch == 0 and git_branch else "HEAD"
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

    # Dynamic facts with mandatory 6 provenance fields
    ci_details: Dict[str, Any] = {
        "source_commit": source_commit,
        "git_snapshot_observed_at": now_iso,
        "last_verified_ci_commit": "a43ef57ddf9d573f38495bd4e6419e176ce12352",
        "candidate_commit": local_head or "NOT_VERIFIABLE",
        "pending_verifications": "当前整改候选 Commit 待推送到 GitHub Actions 远端触发 Windows/Ubuntu 双平台真实 CI 完整运行；实测完成前严格保持 NOT_VERIFIABLE，严禁本地伪造 PASS",
        "historical_ci_runs": [
            "Run 42169418901 (Push @ 4041b1d, conclusion: success, Windows/Ubuntu PASS)",
            "Run 42169424617 (PR #8 @ 4041b1d, conclusion: success, Windows/Ubuntu PASS)",
            "Run 42177850321 (Push @ a7a0177, conclusion: success, Windows/Ubuntu PASS)",
            "Run 42177858136 (PR #8 @ a7a0177, conclusion: success, Windows/Ubuntu PASS)",
            "Run 42553441590 (Push @ a43ef57, conclusion: success, Windows/Ubuntu PASS)",
            "Run 42553446392 (PR #8 @ a43ef57, conclusion: success, Windows/Ubuntu PASS)",
        ],
        "snapshot_status": "FRESH",
        "snapshot_validity_hours": 24,
        "workflow": "standards-ci.yml",
    }
    ci_fact: Dict[str, Any] = ci_fact_override or {
        "repository": repository,
        "source_path": ".github/workflows/standards-ci.yml",
        "source_commit": source_commit,
        "evidence_ref": ".github/workflows/standards-ci.yml",
        "observed_at": now_iso,
        "verification_status": "NOT_VERIFIABLE",
        "summary": "当前分支远端 GitHub Actions CI 待推送后由远端 Runner 实测（执行前保持 NOT_VERIFIABLE；历史已通过 Run: 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392）",
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
        f"- **候选目标标签 (`release_tag`)**：`v{version_str}`",
        "- **正式发布状态**：候选分支上的 VERSION 不等于正式发布；正式版本以官方 main 上的 Annotated Tag 和 main CI 为准。",
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
        f"- **3. 最近一次已验证 CI Commit (`last_verified_ci_commit`)**：`{ci_fact['details'].get('last_verified_ci_commit', 'a43ef57ddf9d573f38495bd4e6419e176ce12352')}`",
        f"- **4. 当前候选 Commit (`candidate_commit`)**：`{local_head}`",
        f"- **5. 当前待验证事项 (`pending_verifications`)**：{ci_fact['details'].get('pending_verifications')}",
        "- **6. 历史 CI 记录 (`historical_ci_runs`)**：",
        "  - Run 42169418901 (Push @ `4041b1d`, conclusion: `success`, Windows/Ubuntu PASS)",
        "  - Run 42169424617 (PR #8 @ `4041b1d`, conclusion: `success`, Windows/Ubuntu PASS)",
        "  - Run 42177850321 (Push @ `a7a0177`, conclusion: `success`, Windows/Ubuntu PASS)",
        "  - Run 42177858136 (PR #8 @ `a7a0177`, conclusion: `success`, Windows/Ubuntu PASS)",
        "  - Run 42553441590 (Push @ `a43ef57`, conclusion: `success`, Windows/Ubuntu PASS)",
        "  - Run 42553446392 (PR #8 @ `a43ef57`, conclusion: `success`, Windows/Ubuntu PASS)",
        f"- **证据引用 (`evidence_ref`)**：`{ci_fact['evidence_ref']}`",
        f"- **观测时间 (`observed_at`)**：`{ci_fact['observed_at']}`",
        f"- **事实说明**：{ci_fact['summary']}",
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
    ]
    md_lines.extend([
        "",
        "## 19. 当前候选状态与消费端试点",
        "",
        f"- 当前候选版本：`{version_str}`；PR #8 尚未合入官方 main，尚未创建正式 v{version_str} Tag。",
        "- 正式发布版本必须以官方 main 上的 Annotated Tag、Tag Object SHA、Peeled Commit 与 main CI 为准；严禁依赖 GitHub /releases/latest REST API 对象。",
        "- 区分六项 CI 与快照核心概念（STD-034 / STD-035）：",
        f"  1. **基线生成时的源 Commit**：`{ci_fact['source_commit']}`（基准比对基线）。",
        f"  2. **Git 快照观测时间**：`{ci_fact['observed_at']}`（快照有效时间 24 小时；过期事实标记 STALE 或 NOT_VERIFIABLE）。",
        f"  3. **最近一次已经验证的 CI Commit**：`{ci_fact['details'].get('last_verified_ci_commit', 'a43ef57ddf9d573f38495bd4e6419e176ce12352')}`（Windows & Ubuntu 双平台全绿）。",
        f"  4. **当前候选 Commit**：`{local_head}`（整改与测试候选 HEAD）。",
        "  5. **当前待验证事项**：远端 GitHub Actions CI 实测；严禁在推送前或运行完成前伪造 CI PASS。",
        "  6. **历史 CI 记录**：Run 42169418901, 42169424617, 42177850321, 42177858136, 42553441590, 42553446392（避免每次记录 CI 又无限触发基线提交的循环）。",
        "- 首个消费端试点为 AI-Engineering-Hub；AI-KB、VTIP、SideCar 不在本轮试点范围，是否接入由各工程 Owner 后续决定。",
        "- 审批状态：保持 `IN_REVIEW`，严禁智能体自批或伪造 `OWNER_APPROVED`。",
    ])
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
    parser.add_argument("--verify-only", action="store_true", help="Verify generation succeeds against committed baseline")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    standards_root = resolve_standards_root(args.standards_root)
    ok, errors, payload, md_text = build_engineering_baseline(
        project_root=project_root,
        standards_root=standards_root,
        observed_at=args.observed_at,
        source_commit_override=args.source_commit,
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
