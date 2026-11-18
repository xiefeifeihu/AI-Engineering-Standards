#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate ChatGPT Independent Review & Owner Approval Contracts (STD-034 / STD-035)."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
import jsonschema
import yaml

OWNER_MANDATORY_CATEGORIES = {
    "PRODUCT_SCOPE_CHANGE",
    "ARCHITECTURE_DECISION_CHANGE",
    "API_SEMANTICS_CHANGE",
    "SECURITY_BOUNDARY_CHANGE",
    "DATA_OWNERSHIP_CHANGE",
    "FORMAL_STANDARDS_SEMANTIC_CHANGE",
    "BREAKING_SCHEMA_CHANGE",
    "IRREVERSIBLE_MIGRATION",
}

FORBIDDEN_SELF_APPROVAL_ROLES = {
    "CODING_AGENT",
    "CODING_AGENT_SELF_DECLARED",
    "AGENT",
    "CLAUDE_CODE",
    "CLAUDE-CODE",
    "CODEX",
    "ANTIGRAVITY",
    "VIBECODING",
    "VIBE_CODING",
    "VIBE-CODING",
    "CURSOR",
    "SELF",
}

TRUSTED_PROVENANCE_TYPES = {
    "GITHUB_PR_REVIEW",
    "GITHUB_PR_MERGE",
    "TRUSTED_CHATGPT_EVENT",
}


def resolve_standards_root(explicit_root: Optional[str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    env_root = os.environ.get("AI_ENGINEERING_STANDARDS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


def compute_canonical_document_sha256(content: str) -> str:
    """Hash normalized Frontmatter metadata and Markdown body; malformed Frontmatter fails closed."""
    normalized = content.replace("\r\n", "\n")
    if normalized.startswith("---\n"):
        parts = normalized.split("---\n", 2)
        if len(parts) < 3:
            raise ValueError("Malformed YAML Frontmatter delimiter; cannot compute approval digest")
        fm = yaml.safe_load(parts[1])
        if not isinstance(fm, dict):
            raise ValueError("YAML Frontmatter must be a mapping; cannot compute approval digest")
        body = parts[2].strip()
        filtered_fm = {
            key: value
            for key, value in sorted(fm.items())
            if key not in ("approval_record", "approval_evidence_ref", "content_sha256")
        }
        canonical_fm_bytes = json.dumps(
            filtered_fm,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(canonical_fm_bytes + b"\n" + body.encode("utf-8")).hexdigest()
    return "sha256:" + hashlib.sha256(normalized.strip().encode("utf-8")).hexdigest()

# Keep backward-compatible alias for existing callers
compute_markdown_body_sha256 = compute_canonical_document_sha256


def normalize_sha256(digest: Optional[str]) -> str:
    if not digest:
        return ""
    val = str(digest).strip().lower()
    return val if val.startswith("sha256:") else f"sha256:{val}"


def git_commit_exists(repo_root: Path, commit_sha: str) -> bool:
    if not commit_sha or not re.match(r"^[0-9a-f]{7,40}$", commit_sha):
        return False
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{commit_sha}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res.returncode == 0
    except Exception:
        return False


def _json_safe(obj: Any) -> Any:
    """Convert YAML/Python objects deterministically into JSON-serializable primitives."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def compute_content_bindings(
    project_root: Optional[Path] = None,
    git_commit: Optional[str] = None,
    prefer_git: bool = False,
) -> Tuple[str, Optional[Dict[str, str]], List[str]]:
    """Recompute canonical SHA-256 content bindings from project files or a controlled Git commit.

    Canonicalization algorithm:
    1. ci_job_mapping_sha256:
       Parse `engineering-manifest.yaml`, extract `standards_validation.required_ci_jobs`
       (default `{}` if key omitted), serialize deterministically with sorted keys and
       compact JSON (`separators=(',', ':'), ensure_ascii=False`), UTF-8 encode, SHA-256.
    2. lock_manifest_sha256:
       Parse `standards.lock.json` and `engineering-manifest.yaml`, construct
       `{"standards_lock": lock_data, "engineering_manifest": manifest_data}`,
       serialize deterministically with sorted keys and compact JSON, UTF-8 encode, SHA-256.

    Returns (status, digests_dict_or_None, errors) where status is PASS, FAIL, or NOT_VERIFIABLE.
    """
    if project_root is None:
        return "NOT_VERIFIABLE", None, ["UNVERIFIABLE_CONTENT_BINDINGS: project_root is missing"]
    root_path = Path(project_root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: project_root '{root_path}' does not exist"]

    manifest_raw: Optional[str] = None
    lock_raw: Optional[str] = None

    if prefer_git:
        if not git_commit or not re.match(r"^[0-9a-f]{40}$", str(git_commit)):
            return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Invalid or missing git_commit '{git_commit}'"]
        try:
            rc_chk = subprocess.run(
                ["git", "-C", str(root_path), "cat-file", "-e", f"{git_commit}^{{commit}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if rc_chk.returncode != 0:
                return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Git commit '{git_commit}' is unreadable in {root_path}"]
            res_m = subprocess.run(
                ["git", "-C", str(root_path), "show", f"{git_commit}:engineering-manifest.yaml"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
            if res_m.returncode != 0:
                return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Cannot read engineering-manifest.yaml at {git_commit}"]
            manifest_raw = res_m.stdout
            res_l = subprocess.run(
                ["git", "-C", str(root_path), "show", f"{git_commit}:standards.lock.json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
            )
            if res_l.returncode != 0:
                return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Cannot read standards.lock.json at {git_commit}"]
            lock_raw = res_l.stdout
        except Exception as exc:
            return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Git read error: {exc}"]
    else:
        manifest_path = root_path / "engineering-manifest.yaml"
        lock_path = root_path / "standards.lock.json"
        if not manifest_path.exists():
            return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Missing {manifest_path}"]
        if not lock_path.exists():
            return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Missing {lock_path}"]
        try:
            manifest_raw = manifest_path.read_text(encoding="utf-8")
            lock_raw = lock_path.read_text(encoding="utf-8")
        except Exception as exc:
            return "NOT_VERIFIABLE", None, [f"UNVERIFIABLE_CONTENT_BINDINGS: Failed reading files: {exc}"]

    try:
        manifest_data = yaml.safe_load(manifest_raw)
        if not isinstance(manifest_data, dict):
            return "FAIL", None, ["CONTENT_BINDING_PARSE_ERROR: engineering-manifest.yaml must be a YAML mapping"]
    except Exception as exc:
        return "FAIL", None, [f"CONTENT_BINDING_PARSE_ERROR: Invalid engineering-manifest.yaml: {exc}"]

    try:
        lock_data = json.loads(lock_raw)
        if not isinstance(lock_data, dict):
            return "FAIL", None, ["CONTENT_BINDING_PARSE_ERROR: standards.lock.json must be a JSON object"]
    except Exception as exc:
        return "FAIL", None, [f"CONTENT_BINDING_PARSE_ERROR: Invalid standards.lock.json: {exc}"]

    try:
        required_ci_jobs = (manifest_data.get("standards_validation") or {}).get("required_ci_jobs")
        if required_ci_jobs is None:
            required_ci_jobs = {}
        mapping_canonical = json.dumps(
            _json_safe(required_ci_jobs),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        ci_job_mapping_sha256 = "sha256:" + hashlib.sha256(mapping_canonical).hexdigest()

        lock_manifest_payload = _json_safe({
            "standards_lock": lock_data,
            "engineering_manifest": manifest_data,
        })
        lock_manifest_canonical = json.dumps(
            lock_manifest_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        lock_manifest_sha256 = "sha256:" + hashlib.sha256(lock_manifest_canonical).hexdigest()
    except Exception as exc:
        return "FAIL", None, [f"CONTENT_BINDING_COMPUTE_ERROR: {exc}"]

    return "PASS", {
        "ci_job_mapping_sha256": ci_job_mapping_sha256,
        "lock_manifest_sha256": lock_manifest_sha256,
    }, []


def verify_content_bindings_digests(
    record: Dict[str, Any],
    event: Optional[Dict[str, Any]] = None,
    project_root: Optional[Path] = None,
    git_commit: Optional[str] = None,
    prefer_git: bool = False,
) -> Tuple[str, List[str]]:
    """Verify actual recomputed content_bindings digests against BOTH approval record and event."""
    rec_cb = record.get("content_bindings")
    ev_cb = event.get("content_bindings") if isinstance(event, dict) else None
    if not isinstance(rec_cb, dict):
        return "FAIL", ["MISSING_CONTENT_BINDINGS: Approval record missing content_bindings"]
    if isinstance(event, dict) and not isinstance(ev_cb, dict):
        return "FAIL", ["MISSING_CONTENT_BINDINGS: Approval event missing content_bindings"]
    if isinstance(event, dict) and rec_cb != ev_cb:
        return "FAIL", ["CONTENT_BINDINGS_MISMATCH: record content_bindings != event content_bindings"]

    status, computed, errs = compute_content_bindings(
        project_root=project_root,
        git_commit=git_commit,
        prefer_git=prefer_git,
    )
    if status != "PASS" or computed is None:
        return status, errs

    mismatches: List[str] = []
    for key in ("ci_job_mapping_sha256", "lock_manifest_sha256"):
        expected = computed[key]
        rec_val = normalize_sha256(rec_cb.get(key))
        if rec_val != expected:
            mismatches.append(f"CONTENT_BINDING_DIGEST_MISMATCH: record.{key} ({rec_val}) != computed ({expected})")
        if isinstance(ev_cb, dict):
            ev_val = normalize_sha256(ev_cb.get(key))
            if ev_val != expected:
                mismatches.append(f"CONTENT_BINDING_DIGEST_MISMATCH: event.{key} ({ev_val}) != computed ({expected})")

    if mismatches:
        return "FAIL", mismatches
    return "PASS", []


def verify_approval_event_provenance(
    record: Dict[str, Any],
    standards_root: Optional[Path] = None,
    simulate_data: Optional[Dict[str, Any]] = None,
    project_root: Optional[Path] = None,
    content_binding_git_commit: Optional[str] = None,
    prefer_git_content: bool = False,
) -> Tuple[str, List[str]]:
    """Verify Owner approval through GitHub PR merge or review API; never trust JSON status labels."""
    event = record.get("approval_event")
    if not isinstance(event, dict):
        return "NOT_VERIFIABLE", ["UNVERIFIABLE_APPROVAL_PROVENANCE: No external approval event is attached"]
    event_type = event.get("event_type")
    provenance_type = event.get("provenance_type")
    if event_type not in ("GITHUB_PR_REVIEW_EVENT", "GITHUB_PR_MERGE_EVENT") or provenance_type not in ("GITHUB_PR_REVIEW", "GITHUB_PR_MERGE"):
        return "NOT_VERIFIABLE", [
            "UNVERIFIABLE_APPROVAL_PROVENANCE: ChatGPT session references and unsigned local records cannot be independently verified"
        ]
    if record.get("approval_status") != "OWNER_APPROVED":
        return "NOT_VERIFIABLE", [
            "UNVERIFIABLE_APPROVAL_PROVENANCE: GitHub PR adapter currently verifies Owner approval only"
        ]

    actor = event.get("actor_identity") or {}
    if actor.get("identity_type") != "GITHUB_USER":
        return "NOT_VERIFIABLE", ["UNVERIFIABLE_APPROVAL_PROVENANCE: Actor is not a verified GitHub user"]

    repository = str(record.get("repository") or "")
    service_ref = str(actor.get("service_provenance_ref") or "")
    expected_owner = repository.split("/", 1)[0].lower()
    identity_id = str(actor.get("identity_id") or "")

    # 1. GITHUB_PR_MERGE_EVENT: Single Owner PR Merge Approval (Option C)
    if event_type == "GITHUB_PR_MERGE_EVENT" or provenance_type == "GITHUB_PR_MERGE":
        prefix = f"https://api.github.com/repos/{repository}/pulls/"
        match = re.fullmatch(re.escape(prefix) + r"(\d+)", service_ref)
        if not match:
            return "FAILED", ["INVALID_APPROVAL_EVENT_REFERENCE: Expected exact GitHub PR API URL: https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"]
        pull_number = int(match.group(1))
        event_id = str(event.get("event_id") or "")
        if event_id.isdigit() and int(event_id) != pull_number:
            return "FAILED", ["APPROVAL_PR_ID_MISMATCH: event_id does not match PR number"]

        if simulate_data is not None:
            pr = simulate_data
        else:
            token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
            if not token:
                return "NOT_VERIFIABLE", ["UNVERIFIABLE_APPROVAL_PROVENANCE: GITHUB_TOKEN or GH_TOKEN is unavailable"]
            request = urllib.request.Request(
                service_ref,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "AI-Engineering-Standards-Approval-Verifier/3.0.0",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    pr = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                return "NOT_VERIFIABLE", [f"UNVERIFIABLE_APPROVAL_PROVENANCE: GitHub PR lookup failed: {exc}"]

        # Agent permission boundaries: Coding agents cannot hold merge permissions or authorize Owner approvals
        merged_by = (pr.get("merged_by") or {}).get("login") or ""
        if merged_by.upper() in FORBIDDEN_SELF_APPROVAL_ROLES or identity_id.upper() in FORBIDDEN_SELF_APPROVAL_ROLES or "AGENT" in merged_by.upper():
            return "FAILED", [f"AGENT_SELF_APPROVAL_FORBIDDEN: Coding agent ({merged_by or identity_id}) cannot merge PR or issue OWNER approval"]

        if not pr.get("merged"):
            return "FAILED", ["APPROVAL_PR_NOT_MERGED: PR is not merged; approval state must remain OWNER_APPROVAL_REQUIRED"]

        if not merged_by:
            return "FAILED", ["APPROVAL_PR_MERGED_BY_MISSING: PR merged_by is empty"]
        if merged_by.lower() != expected_owner or (identity_id and identity_id.lower() != merged_by.lower()):
            return "FAILED", [f"APPROVAL_ACTOR_MISMATCH: PR merged_by '{merged_by}' is not the repository owner '{expected_owner}'"]

        base_ref = (pr.get("base") or {}).get("ref") or ""
        if base_ref != "main":
            return "FAILED", [f"APPROVAL_PR_BASE_BRANCH_MISMATCH: Base branch is '{base_ref}', expected 'main'"]

        # Scope verification
        record_scope = record.get("approval_scope") or record.get("decision_scope")
        event_scope = event.get("approval_scope")
        if event_scope and record_scope and event_scope != record_scope:
            return "FAILED", [f"EVENT_SCOPE_MISMATCH: event.approval_scope '{event_scope}' != '{record_scope}'"]

        if record_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK") or event_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK"):
            if not record.get("commit_bindings") or not event.get("commit_bindings"):
                return "FAILED", ["LEGACY_SINGLE_COMMIT_BYPASS_FORBIDDEN: Scope requires dual commit_bindings in both record and event"]
            if not record.get("content_bindings") or not event.get("content_bindings"):
                return "FAILED", ["MISSING_CONTENT_BINDINGS: Scope requires content_bindings in both record and event"]

        # Cross-consistency of bindings between record and event
        rec_cb = record.get("commit_bindings")
        ev_cb = event.get("commit_bindings")
        if rec_cb and ev_cb and rec_cb != ev_cb:
            return "FAILED", ["COMMIT_BINDINGS_MISMATCH: record commit_bindings != event commit_bindings"]

        rec_cnt = record.get("content_bindings")
        ev_cnt = event.get("content_bindings")
        if rec_cnt and ev_cnt and rec_cnt != ev_cnt:
            return "FAILED", ["CONTENT_BINDINGS_MISMATCH: record content_bindings != event content_bindings"]

        head_sha = (pr.get("head") or {}).get("sha") or ""
        commit_bindings = rec_cb or ev_cb
        if commit_bindings:
            consumer_binding = commit_bindings.get("consumer") or {}
            if not consumer_binding:
                return "FAILED", ["MISSING_CONSUMER_COMMIT_BINDING: commit_bindings.consumer is required"]
            expected_head = str(consumer_binding.get("candidate_commit") or "").strip()
            expected_repo = consumer_binding.get("repository") or repository
            if expected_repo and repository.lower() != expected_repo.lower():
                return "FAILED", [f"APPROVAL_PR_REPO_MISMATCH: PR repo '{repository}' != expected consumer repo '{expected_repo}'"]
            if not expected_head or not re.match(r"^[0-9a-f]{40}$", expected_head):
                return "FAILED", [f"INVALID_CONSUMER_CANDIDATE_COMMIT: '{expected_head}'"]
            if record.get("candidate_commit") and record.get("candidate_commit") != expected_head:
                return "FAILED", [f"CONSUMER_COMMIT_MISMATCH: record.candidate_commit '{record.get('candidate_commit')}' != commit_bindings.consumer.candidate_commit '{expected_head}'"]
            if head_sha != expected_head:
                return "FAILED", [f"APPROVAL_PR_HEAD_COMMIT_MISMATCH: PR head.sha '{head_sha}' != consumer candidate_commit '{expected_head}'"]
            if event.get("candidate_commit") and event.get("candidate_commit") != expected_head:
                return "FAILED", ["EVENT_COMMIT_MISMATCH"]

            standards_binding = commit_bindings.get("standards") or {}
            if not standards_binding and (record_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK") or event_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK")):
                return "FAILED", ["MISSING_STANDARDS_COMMIT_BINDING: commit_bindings.standards is required"]
            if standards_binding:
                std_repo = standards_binding.get("repository")
                if std_repo != "xiefeifeihu/AI-Engineering-Standards":
                    return "FAILED", [f"INVALID_STANDARDS_REPOSITORY: '{std_repo}' is not official AI-Engineering-Standards"]
                std_tag = standards_binding.get("target_tag")
                std_tag_obj = standards_binding.get("tag_object_sha")
                std_peeled = standards_binding.get("peeled_commit")
                if not std_tag or not re.match(r"^v\d+\.\d+\.\d+$", str(std_tag)):
                    return "FAILED", [f"INVALID_STANDARDS_TARGET_TAG: '{std_tag}'"]
                if not std_tag_obj or not re.match(r"^[0-9a-f]{40}$", str(std_tag_obj)):
                    return "FAILED", [f"INVALID_STANDARDS_TAG_OBJECT_SHA: '{std_tag_obj}'"]
                if not std_peeled or not re.match(r"^[0-9a-f]{40}$", str(std_peeled)):
                    return "FAILED", [f"INVALID_STANDARDS_PEELED_COMMIT: '{std_peeled}'"]
                if expected_head == std_peeled:
                    return "FAILED", ["DUAL_COMMIT_CONFUSION_FORBIDDEN: consumer.candidate_commit cannot equal standards.peeled_commit"]
        else:
            if record_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK"):
                return "FAILED", ["LEGACY_SINGLE_COMMIT_BYPASS_FORBIDDEN: Scope requires dual commit_bindings"]
            cand_commit = record.get("candidate_commit") or ""
            if not cand_commit or head_sha != cand_commit:
                return "FAILED", [f"APPROVAL_PR_HEAD_COMMIT_MISMATCH: PR head.sha '{head_sha}' != candidate_commit '{cand_commit}'"]
            if event.get("candidate_commit") != cand_commit:
                return "FAILED", ["EVENT_COMMIT_MISMATCH"]

        content_bindings = rec_cnt or ev_cnt
        if content_bindings:
            mapping_sha = content_bindings.get("ci_job_mapping_sha256")
            lock_sha = content_bindings.get("lock_manifest_sha256")
            if not mapping_sha or not re.match(r"^(sha256:)?[0-9a-f]{64}$", str(mapping_sha)):
                return "FAILED", ["INVALID_CONTENT_BINDING_DIGEST: 'ci_job_mapping_sha256' is missing or invalid SHA-256"]
            if not lock_sha or not re.match(r"^(sha256:)?[0-9a-f]{64}$", str(lock_sha)):
                return "FAILED", ["INVALID_CONTENT_BINDING_DIGEST: 'lock_manifest_sha256' is missing or invalid SHA-256"]

        merged_at = pr.get("merged_at")
        if not merged_at:
            return "FAILED", ["APPROVAL_PR_MERGED_AT_EMPTY: PR merged_at is empty"]

        event_ts = str(event.get("event_timestamp") or event.get("timestamp") or "").strip()
        if not event_ts and (record_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK") or event_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK")):
            return "FAILED", ["APPROVAL_EVENT_TIMESTAMP_MISSING: approval_event missing event_timestamp"]
        elif not event_ts:
            event_ts = str(record.get("approved_at") or (record.get("owner_approval") or {}).get("approved_at") or "").strip()
        if not event_ts:
            return "FAILED", ["APPROVAL_EVENT_TIMESTAMP_MISSING: approval_event missing event_timestamp"]
        norm_merged = str(merged_at).replace("Z", "+00:00")
        norm_ev_ts = event_ts.replace("Z", "+00:00")
        if norm_ev_ts != norm_merged:
            return "FAILED", [f"APPROVAL_TIME_MISMATCH: event_timestamp '{event_ts}' != GitHub PR merged_at '{merged_at}'"]

        digest = normalize_sha256(record.get("content_sha256"))
        if not digest or normalize_sha256(event.get("content_sha256")) != digest:
            return "FAILED", ["EVENT_CONTENT_HASH_MISMATCH"]

        record_approved_at = str(record.get("approved_at") or (record.get("owner_approval") or {}).get("approved_at") or "").strip()
        if record_approved_at:
            norm_appr = record_approved_at.replace("Z", "+00:00")
            if norm_merged != norm_appr:
                return "FAILED", [f"APPROVAL_TIME_MISMATCH: approved_at '{record_approved_at}' does not match GitHub PR merged_at '{merged_at}'"]

        if record_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK") or event_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK") or content_bindings:
            is_controlled_scope = record_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK") or event_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK")
            eff_git_commit = content_binding_git_commit
            eff_prefer_git = prefer_git_content
            if is_controlled_scope:
                eff_git_commit = content_binding_git_commit or ((commit_bindings or {}).get("consumer") or {}).get("candidate_commit")
                eff_prefer_git = True
            cb_st, cb_errs = verify_content_bindings_digests(
                record=record,
                event=event,
                project_root=project_root,
                git_commit=eff_git_commit,
                prefer_git=eff_prefer_git,
            )
            if cb_st == "FAIL":
                return "FAILED", cb_errs
            if cb_st != "PASS":
                return cb_st, cb_errs

        return "VERIFIED", []

    # 2. GITHUB_PR_REVIEW_EVENT: Legacy Multi-Account Review Approval
    review_id = str(event.get("event_id") or "")
    prefix = f"https://api.github.com/repos/{repository}/pulls/"
    match = re.fullmatch(re.escape(prefix) + r"(\d+)/reviews/(\d+)", service_ref)
    if not match or not review_id.isdigit() or match.group(2) != review_id:
        return "FAILED", ["INVALID_APPROVAL_EVENT_REFERENCE: Expected exact GitHub PR review API URL"]

    if simulate_data is not None:
        review = simulate_data
    else:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            return "NOT_VERIFIABLE", ["UNVERIFIABLE_APPROVAL_PROVENANCE: GITHUB_TOKEN or GH_TOKEN is unavailable"]
        request = urllib.request.Request(
            service_ref,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "AI-Engineering-Standards-Approval-Verifier/3.0.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                review = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            return "NOT_VERIFIABLE", [f"UNVERIFIABLE_APPROVAL_PROVENANCE: GitHub review lookup failed: {exc}"]

    actual_actor = str((review.get("user") or {}).get("login") or "")

    # Anti-agent check on review actor
    if actual_actor.upper() in FORBIDDEN_SELF_APPROVAL_ROLES or identity_id.upper() in FORBIDDEN_SELF_APPROVAL_ROLES or "AGENT" in actual_actor.upper():
        return "FAILED", [f"AGENT_SELF_APPROVAL_FORBIDDEN: Coding agent ({actual_actor or identity_id}) cannot issue OWNER approval"]

    if actual_actor.lower() != expected_owner or actual_actor.lower() != identity_id.lower():
        return "FAILED", ["APPROVAL_ACTOR_MISMATCH: Review actor is not the repository owner"]
    if int(review.get("id") or 0) != int(review_id):
        return "FAILED", ["APPROVAL_REVIEW_ID_MISMATCH"]
    review_state = str(review.get("state") or "").upper()
    if review_state != "APPROVED":
        return "FAILED", [f"APPROVAL_REVIEW_NOT_APPROVED: Review state is '{review_state}', expected 'APPROVED'"]
    if review.get("commit_id") != record.get("candidate_commit"):
        return "FAILED", ["APPROVAL_REVIEW_COMMIT_MISMATCH"]

    digest = normalize_sha256(record.get("content_sha256"))
    raw_digest = digest[7:] if digest.startswith("sha256:") else digest
    body = str(review.get("body") or "")
    has_digest_binding = any(
        marker in body
        for marker in (
            f"CONTENT_SHA256={digest}",
            f"CONTENT_SHA256={raw_digest}",
            f"MAPPING_DIGEST={digest}",
            f"MAPPING_DIGEST={raw_digest}",
        )
    )
    if not has_digest_binding:
        return "FAILED", ["APPROVAL_REVIEW_CONTENT_BINDING_MISSING"]
    approved_ids = (record.get("owner_approval") or {}).get("approved_decision_ids") or []
    expected_ids = ",".join(sorted(str(value) for value in approved_ids))
    if not expected_ids or f"APPROVED_DECISION_IDS={expected_ids}" not in body:
        return "FAILED", ["APPROVAL_REVIEW_DECISION_BINDING_MISSING"]
    if event.get("candidate_commit") != record.get("candidate_commit"):
        return "FAILED", ["EVENT_COMMIT_MISMATCH"]
    if normalize_sha256(event.get("content_sha256")) != digest:
        return "FAILED", ["EVENT_CONTENT_HASH_MISMATCH"]

    record_scope = record.get("approval_scope") or record.get("decision_scope")
    event_scope = event.get("approval_scope")
    if event_scope != record_scope:
        return "FAILED", [f"EVENT_SCOPE_MISMATCH: event.approval_scope '{event_scope}' != '{record_scope}'"]
    if f"APPROVAL_SCOPE={record_scope}" not in body and f"APPROVAL_SCOPE={event_scope}" not in body:
        return "FAILED", ["APPROVAL_REVIEW_SCOPE_BINDING_MISSING: Review body must bind APPROVAL_SCOPE"]

    # Verify review submitted_at against approved_at
    review_submitted_at = str(review.get("submitted_at") or "").strip()
    record_approved_at = str(record.get("approved_at") or (record.get("owner_approval") or {}).get("approved_at") or "").strip()
    norm_sub = review_submitted_at.replace("Z", "+00:00")
    norm_appr = record_approved_at.replace("Z", "+00:00")
    if not norm_sub or not norm_appr or norm_sub != norm_appr:
        return "FAILED", [f"APPROVAL_TIME_MISMATCH: approved_at '{record_approved_at}' does not match GitHub review submitted_at '{review_submitted_at}'"]

    return "VERIFIED", []

def validate_approval_record(
    record: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
    target_content: Optional[str] = None,
    expected_commit: Optional[str] = None,
    repo_root: Optional[Path] = None,
    verify_provenance: bool = True,
    standards_root: Optional[Path] = None,
    simulate_provenance_data: Optional[Dict[str, Any]] = None,
    project_root: Optional[Path] = None,
    content_binding_git_commit: Optional[str] = None,
    prefer_git_content: bool = False,
) -> Tuple[bool, List[str]]:
    errors: List[str] = []

    # 1. Explicit anti-spoofing check before schema validation
    actor_role = str(record.get("actor_role") or "").strip().upper()
    reviewer_type = str(record.get("reviewer_type") or "").strip().upper()
    approval_status = str(record.get("approval_status") or "").strip().upper()
    review_result = str(record.get("review_result") or "").strip().upper()

    if actor_role in FORBIDDEN_SELF_APPROVAL_ROLES or reviewer_type in FORBIDDEN_SELF_APPROVAL_ROLES:
        if approval_status in ("AI_APPROVED", "OWNER_APPROVED", "HUMAN_ACCEPTED") or review_result in (
            "AI_APPROVED",
            "OWNER_APPROVED",
            "HUMAN_ACCEPTED",
        ):
            errors.append(
                f"AGENT_SELF_APPROVAL_FORBIDDEN: Coding agent ({actor_role or reviewer_type}) cannot set {approval_status or review_result}"
            )

    # 2. Schema validation
    if schema is None:
        schema_path = resolve_standards_root() / "schemas" / "documentation-approval.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

    validator = jsonschema.Draft202012Validator(schema)
    for err in validator.iter_errors(record):
        path_str = ".".join(str(p) for p in err.path) or "<root>"
        errors.append(f"SCHEMA_VIOLATION [{path_str}]: {err.message}")

    # 3. Check decision scope and change categories vs approval status
    decision_scope = record.get("decision_scope", "UNCERTAIN")
    categories = set(record.get("change_categories") or [])
    requires_owner = decision_scope in ("OWNER_MANDATORY", "UNCERTAIN") or bool(
        categories & OWNER_MANDATORY_CATEGORIES
    )

    if requires_owner and approval_status == "AI_APPROVED":
        errors.append(
            "OWNER_APPROVAL_REQUIRED_VIOLATION: Changes in OWNER_MANDATORY/UNCERTAIN scope cannot be promoted with AI_APPROVED alone"
        )

    # 4. Separate recording & binding checks for ChatGPT review
    chatgpt_review = record.get("chatgpt_review")
    cand_commit = record.get("candidate_commit", "")
    rec_sha = normalize_sha256(record.get("content_sha256"))

    if isinstance(chatgpt_review, dict):
        if chatgpt_review.get("candidate_commit") != cand_commit:
            errors.append(
                "CHATGPT_COMMIT_BINDING_MISMATCH: chatgpt_review.candidate_commit does not match record candidate_commit"
            )
        if normalize_sha256(chatgpt_review.get("content_sha256")) != rec_sha:
            errors.append(
                "CHATGPT_CONTENT_HASH_MISMATCH: chatgpt_review.content_sha256 does not match record content_sha256"
            )
        if requires_owner and chatgpt_review.get("review_result") == "AI_APPROVED" and not record.get("owner_approval"):
            errors.append(
                "OWNER_APPROVAL_MISSING: ChatGPT review cannot finalize OWNER_MANDATORY scope without separate owner_approval"
            )

    # 5. Owner approval binding checks when approval_status == OWNER_APPROVED
    owner_approval = record.get("owner_approval")
    if approval_status == "OWNER_APPROVED":
        if not isinstance(owner_approval, dict):
            errors.append("MISSING_OWNER_APPROVAL_RECORD: approval_status=OWNER_APPROVED requires owner_approval object")
        else:
            approver_str = str(owner_approval.get("approver") or "").strip().upper()
            if approver_str in FORBIDDEN_SELF_APPROVAL_ROLES or "AGENT" in approver_str:
                errors.append(
                    f"SELF_OWNER_APPROVAL_FORBIDDEN: Coding agent '{owner_approval.get('approver')}' cannot impersonate Owner"
                )
            if owner_approval.get("candidate_commit") != cand_commit:
                errors.append(
                    "OWNER_COMMIT_BINDING_MISMATCH: owner_approval.candidate_commit does not match candidate_commit"
                )
            if normalize_sha256(owner_approval.get("content_sha256")) != rec_sha:
                errors.append(
                    "OWNER_CONTENT_HASH_MISMATCH: owner_approval.content_sha256 does not match content_sha256"
                )
            if not owner_approval.get("approved_decision_ids"):
                errors.append(
                    "OWNER_DECISION_BINDING_MISSING: owner_approval must bind specific approved_decision_ids"
                )

    # 6. Target content & commit staleness / invalidation checks
    if target_content is not None:
        actual_sha = compute_canonical_document_sha256(target_content)
        if actual_sha != rec_sha:
            errors.append(
                f"APPROVAL_INVALIDATED_BY_CONTENT_CHANGE: Document content_sha256 ({actual_sha}) differs from approved digest ({rec_sha})"
            )

    if expected_commit is not None and cand_commit != expected_commit:
        errors.append(
            f"APPROVAL_INVALIDATED_BY_COMMIT_CHANGE: Target commit ({expected_commit}) differs from approved candidate_commit ({cand_commit})"
        )

    if repo_root is not None and cand_commit:
        if not git_commit_exists(repo_root, cand_commit):
            errors.append(f"UNVERIFIABLE_CANDIDATE_COMMIT: Commit '{cand_commit}' does not exist in {repo_root}")

    effective_project_root = project_root or repo_root
    cb_obj = record.get("commit_bindings")
    if isinstance(cb_obj, dict):
        cons_b = cb_obj.get("consumer") or {}
        std_b = cb_obj.get("standards") or {}
        if cons_b.get("candidate_commit") and cand_commit != cons_b.get("candidate_commit"):
            errors.append(
                f"CONSUMER_COMMIT_MISMATCH: candidate_commit '{cand_commit}' != commit_bindings.consumer.candidate_commit '{cons_b.get('candidate_commit')}'"
            )
        if cons_b.get("candidate_commit") and std_b.get("peeled_commit") and cons_b.get("candidate_commit") == std_b.get("peeled_commit"):
            errors.append("DUAL_COMMIT_CONFUSION_FORBIDDEN: consumer.candidate_commit cannot equal standards.peeled_commit")

    if not verify_provenance and effective_project_root is not None and isinstance(record.get("content_bindings"), dict):
        is_controlled_scope = decision_scope in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK") or record.get("approval_scope") in ("STANDARDS_LOCK_PROMOTION", "LOCK_ROLLBACK")
        eff_git_commit = content_binding_git_commit
        eff_prefer_git = prefer_git_content
        if is_controlled_scope:
            eff_git_commit = content_binding_git_commit or (((cb_obj or {}).get("consumer") or {}).get("candidate_commit") if isinstance(cb_obj, dict) else None)
            eff_prefer_git = True
        cb_st, cb_errs = verify_content_bindings_digests(
            record=record,
            event=record.get("approval_event"),
            project_root=effective_project_root,
            git_commit=eff_git_commit,
            prefer_git=eff_prefer_git,
        )
        if cb_st != "PASS":
            errors.extend(cb_errs)

    # 7. Authenticity & Provenance Check
    if verify_provenance and approval_status in ("AI_APPROVED", "OWNER_APPROVED"):
        prov_status, prov_errors = verify_approval_event_provenance(
            record,
            standards_root=standards_root,
            simulate_data=simulate_provenance_data,
            project_root=effective_project_root,
            content_binding_git_commit=content_binding_git_commit,
            prefer_git_content=prefer_git_content,
        )
        if prov_status != "VERIFIED":
            errors.extend(prov_errors)

    return len(errors) == 0, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate documentation/upgrade approval evidence against STD-034/STD-035")
    parser.add_argument("approval_file", help="Path to approval JSON file")
    parser.add_argument("--standards-root", default=None, help="Path to AI-Engineering-Standards root")
    parser.add_argument("--schema", default=None, help="Path to documentation-approval.schema.json")
    parser.add_argument("--target-doc", default=None, help="Optional target markdown document to verify content_sha256")
    parser.add_argument("--expected-commit", default=None, help="Optional expected candidate commit SHA")
    parser.add_argument("--repo-root", default=None, help="Optional repository root to verify commit existence")
    parser.add_argument("--allow-unverified-provenance", action="store_true", help="Diagnostic only; never use to authorize promotion")
    args = parser.parse_args()

    standards_root = resolve_standards_root(args.standards_root)
    schema_path = (
        Path(args.schema).resolve()
        if args.schema
        else standards_root / "schemas" / "documentation-approval.schema.json"
    )
    if not schema_path.exists():
        print(f"[FAIL] Schema not found: {schema_path}")
        sys.exit(1)

    approval_path = Path(args.approval_file).resolve()
    if not approval_path.exists():
        print(f"[FAIL] Approval file not found: {approval_path}")
        sys.exit(1)

    record = json.loads(approval_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    target_content = Path(args.target_doc).read_text(encoding="utf-8") if args.target_doc else None
    repo_root = Path(args.repo_root).resolve() if args.repo_root else None

    ok, errors = validate_approval_record(
        record=record,
        schema=schema,
        target_content=target_content,
        expected_commit=args.expected_commit,
        repo_root=repo_root,
        verify_provenance=not args.allow_unverified_provenance,
    )
    if ok:
        print(f"[PASS] Approval evidence verified: {approval_path.name}")
        sys.exit(0)
    else:
        print(f"[FAIL] Approval evidence validation failed ({len(errors)} issues):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
