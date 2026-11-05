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


def verify_approval_event_provenance(record: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Verify Owner approval through the GitHub PR review API; never trust JSON status labels."""
    event = record.get("approval_event")
    if not isinstance(event, dict):
        return "NOT_VERIFIABLE", ["UNVERIFIABLE_APPROVAL_PROVENANCE: No external approval event is attached"]
    if event.get("event_type") != "GITHUB_PR_REVIEW_EVENT" or event.get("provenance_type") != "GITHUB_PR_REVIEW":
        return "NOT_VERIFIABLE", [
            "UNVERIFIABLE_APPROVAL_PROVENANCE: ChatGPT session references and unsigned local records cannot be independently verified"
        ]
    if record.get("approval_status") != "OWNER_APPROVED":
        return "NOT_VERIFIABLE", [
            "UNVERIFIABLE_APPROVAL_PROVENANCE: GitHub PR review adapter currently verifies Owner approval only"
        ]

    actor = event.get("actor_identity") or {}
    if actor.get("identity_type") != "GITHUB_USER":
        return "NOT_VERIFIABLE", ["UNVERIFIABLE_APPROVAL_PROVENANCE: Actor is not a verified GitHub user"]

    repository = str(record.get("repository") or "")
    review_id = str(event.get("event_id") or "")
    service_ref = str(actor.get("service_provenance_ref") or "")
    prefix = f"https://api.github.com/repos/{repository}/pulls/"
    match = re.fullmatch(re.escape(prefix) + r"(\d+)/reviews/(\d+)", service_ref)
    if not match or not review_id.isdigit() or match.group(2) != review_id:
        return "FAILED", ["INVALID_APPROVAL_EVENT_REFERENCE: Expected exact GitHub PR review API URL"]

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

    expected_owner = repository.split("/", 1)[0].lower()
    actual_actor = str((review.get("user") or {}).get("login") or "")
    if actual_actor.lower() != expected_owner or actual_actor.lower() != str(actor.get("identity_id") or "").lower():
        return "FAILED", ["APPROVAL_ACTOR_MISMATCH: Review actor is not the repository owner"]
    if int(review.get("id") or 0) != int(review_id):
        return "FAILED", ["APPROVAL_REVIEW_ID_MISMATCH"]
    if str(review.get("state") or "").upper() != "APPROVED":
        return "FAILED", ["APPROVAL_REVIEW_NOT_APPROVED"]
    if review.get("commit_id") != record.get("candidate_commit"):
        return "FAILED", ["APPROVAL_REVIEW_COMMIT_MISMATCH"]

    digest = normalize_sha256(record.get("content_sha256"))
    body = str(review.get("body") or "")
    if f"CONTENT_SHA256={digest}" not in body:
        return "FAILED", ["APPROVAL_REVIEW_CONTENT_BINDING_MISSING"]
    approved_ids = (record.get("owner_approval") or {}).get("approved_decision_ids") or []
    expected_ids = ",".join(sorted(str(value) for value in approved_ids))
    if not expected_ids or f"APPROVED_DECISION_IDS={expected_ids}" not in body:
        return "FAILED", ["APPROVAL_REVIEW_DECISION_BINDING_MISSING"]
    if event.get("candidate_commit") != record.get("candidate_commit"):
        return "FAILED", ["EVENT_COMMIT_MISMATCH"]
    if normalize_sha256(event.get("content_sha256")) != digest:
        return "FAILED", ["EVENT_CONTENT_HASH_MISMATCH"]
    if event.get("approval_scope") != record.get("decision_scope"):
        return "FAILED", ["EVENT_SCOPE_MISMATCH"]
    return "VERIFIED", []

def validate_approval_record(
    record: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
    target_content: Optional[str] = None,
    expected_commit: Optional[str] = None,
    repo_root: Optional[Path] = None,
    verify_provenance: bool = True,
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
