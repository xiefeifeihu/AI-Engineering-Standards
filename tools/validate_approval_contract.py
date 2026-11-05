#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate ChatGPT Independent Review & Owner Approval Contracts (STD-034 / STD-035)."""

from __future__ import annotations

import argparse
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
    "SELF",
}

TRUSTED_PROVENANCE_TYPES = {
    "GITHUB_PR_REVIEW",
    "TRUSTED_CHATGPT_EVENT",
    "SIGNED_OWNER_EVENT",
}


def resolve_standards_root(explicit_root: Optional[str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    env_root = os.environ.get("AI_ENGINEERING_STANDARDS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


def compute_canonical_document_sha256(content: str) -> str:
    """Compute deterministic SHA-256 of markdown document including frontmatter metadata and body.
    Excludes self-referencing fields: approval_record, approval_evidence_ref, content_sha256.
    """
    normalized = content.replace("\r\n", "\n")
    if normalized.startswith("---\n"):
        parts = normalized.split("---\n", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2].strip()
            try:
                fm = yaml.safe_load(fm_text) or {}
                if isinstance(fm, dict):
                    # Filter out self-referencing and transient keys
                    filtered_fm = {
                        k: v
                        for k, v in sorted(fm.items())
                        if k not in ("approval_record", "approval_evidence_ref", "content_sha256")
                    }
                    canonical_fm_bytes = json.dumps(
                        filtered_fm,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                    combined = canonical_fm_bytes + b"\n" + body.encode("utf-8")
                    return "sha256:" + hashlib.sha256(combined).hexdigest()
            except Exception:
                pass
            return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
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


def verify_approval_event_provenance(record: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Verify approval authenticity and provenance.
    Pure JSON strings (reviewer='ChatGPT', approver='xiefeifeihu', chatgpt://) without
    a trusted external event adapter return NOT_VERIFIABLE.
    """
    errors: List[str] = []
    approval_event = record.get("approval_event")
    if not isinstance(approval_event, dict):
        return "NOT_VERIFIABLE", [
            "UNVERIFIABLE_APPROVAL_PROVENANCE: No trusted external approval event adapter attached; local JSON strings alone cannot prove reviewer authenticity (approval_provenance=NOT_VERIFIABLE)"
        ]

    prov_type = approval_event.get("provenance_type")
    if prov_type not in TRUSTED_PROVENANCE_TYPES:
        return "NOT_VERIFIABLE", [
            f"UNVERIFIABLE_APPROVAL_PROVENANCE: Provenance '{prov_type}' is unverified or local mock; cannot prove authentic ChatGPT/Owner approval (approval_provenance=NOT_VERIFIABLE)"
        ]

    actor_id = approval_event.get("actor_identity") or {}
    id_type = actor_id.get("identity_type")
    if id_type in ("LOCAL_MOCK", None):
        return "NOT_VERIFIABLE", [
            f"UNVERIFIABLE_APPROVAL_PROVENANCE: Actor identity_type '{id_type}' is a local unverified placeholder (approval_provenance=NOT_VERIFIABLE)"
        ]

    cand_commit = record.get("candidate_commit", "")
    ev_commit = approval_event.get("candidate_commit", "")
    if ev_commit != cand_commit:
        errors.append(f"EVENT_COMMIT_MISMATCH: approval_event candidate_commit ({ev_commit}) != record candidate_commit ({cand_commit})")

    rec_sha = normalize_sha256(record.get("content_sha256"))
    ev_sha = normalize_sha256(approval_event.get("content_sha256"))
    if ev_sha != rec_sha:
        errors.append(f"EVENT_CONTENT_HASH_MISMATCH: approval_event content_sha256 ({ev_sha}) != record content_sha256 ({rec_sha})")

    ver_status = approval_event.get("verification_status")
    if ver_status == "FAILED":
        return "FAILED", errors + ["EVENT_VERIFICATION_FAILED: External approval event verification explicitly failed"]
    if ver_status != "VERIFIED":
        return "NOT_VERIFIABLE", errors + ["EVENT_NOT_VERIFIED: External approval event is not marked VERIFIED"]

    if errors:
        return "FAILED", errors
    return "VERIFIED", []


def validate_approval_record(
    record: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
    target_content: Optional[str] = None,
    expected_commit: Optional[str] = None,
    repo_root: Optional[Path] = None,
    verify_provenance: bool = False,
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

    # 7. Authenticity & Provenance Check
    if verify_provenance and approval_status in ("AI_APPROVED", "OWNER_APPROVED"):
        prov_status, prov_errors = verify_approval_event_provenance(record)
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
    parser.add_argument("--verify-provenance", action="store_true", help="Enforce external trusted approval event verification")
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
        verify_provenance=args.verify_provenance,
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
