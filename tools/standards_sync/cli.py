#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI Entrypoint for AI Engineering Standards Official Sync Tool (STD-034 / D3-D5).

Subcommands:
  - discover
  - verify-lock
  - compare
  - impact
  - prepare-upgrade
  - validate-upgrade
  - promote
  - rollback
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.standards_sync.core import (
    DEFAULT_OFFICIAL_REPO,
    detect_interrupted_transaction,
    recover_interrupted_transaction,
    analyze_consumer_impact,
    compare_versions_and_artifacts,
    discover_latest_official_tag,
    prepare_upgrade_candidate,
    promote_upgrade,
    rollback_lock,
    validate_upgrade_candidate,
    verify_project_lock,
)


def resolve_locked_standards_ref(project_root: Path, explicit_from: str | None = None) -> str | None:
    """Resolve a source ref without silently selecting a historical default."""
    if explicit_from:
        return explicit_from
    lock_path = project_root / "standards.lock.json"
    if not lock_path.exists():
        return None
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if lock.get("repository") != DEFAULT_OFFICIAL_REPO:
        return None
    tag = str(lock.get("tag") or "").strip()
    version = str(lock.get("version") or "").strip()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        return None
    if tag.lstrip("v") != version:
        return None
    for field in ("tag_object_sha", "peeled_commit"):
        if not re.fullmatch(r"[0-9a-f]{40}", str(lock.get(field) or "")):
            return None
    return tag


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="standards_sync",
        description="Official AI Engineering Standards Discovery & Controlled Sync Tool (STD-034 v3.0.0)",
    )
    parser.add_argument(
        "--standards-root",
        default=None,
        help="Path to AI-Engineering-Standards repository root (or set AI_ENGINEERING_STANDARDS_ROOT)",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # 1. discover
    p_disc = sub.add_parser("discover", help="Discover latest official Standards release Tag, Object SHA, Peeled Commit, VERSION, and main CI")
    p_disc.add_argument("--remote-url", default=f"https://github.com/{DEFAULT_OFFICIAL_REPO}.git", help="Official Git remote URL or local repo path")
    p_disc.add_argument("--repo-slug", default=DEFAULT_OFFICIAL_REPO, help="GitHub repository slug")
    p_disc.add_argument("--timeout", type=int, default=10, help="Network timeout in seconds")

    # 2. verify-lock
    p_ver = sub.add_parser("verify-lock", help="Verify project standards.lock.json against schema, annotated Tag, VERSION, and main branch")
    p_ver.add_argument("--project-root", default=".", help="Target project root directory")

    # 3. compare
    p_cmp = sub.add_parser("compare", help="Compare Standards versions, clauses, and JSON schemas")
    p_cmp.add_argument("--project-root", default=".", help="Target project root directory (reads lock if --from-ref omitted)")
    p_cmp.add_argument("--from-ref", default=None, help="Source git ref or tag (default: locked tag from standards.lock.json)")
    p_cmp.add_argument("--to-ref", default="WORKTREE", help="Target git ref, tag, or WORKTREE")

    # 4. impact
    p_imp = sub.add_parser("impact", help="Analyze consumer upgrade impact across 10 governance dimensions")
    p_imp.add_argument("--project-root", default=".", help="Target consumer project root directory")
    p_imp.add_argument("--from-ref", default=None, help="Baseline Standards ref (default: locked tag from standards.lock.json)")
    p_imp.add_argument("--to-ref", default="WORKTREE", help="Target Standards ref")

    # 5. prepare-upgrade
    p_prep = sub.add_parser("prepare-upgrade", help="Generate upgrade candidate artifacts and lock candidate")
    p_prep.add_argument("--project-root", default=".", help="Target consumer project root directory")
    p_prep.add_argument("--target-tag", required=True, help="Target official tag (e.g. v3.0.0)")
    p_prep.add_argument("--target-version", required=True, help="Target version (e.g. 3.0.0)")
    p_prep.add_argument("--target-tag-object-sha", required=True, help="40-hex annotated tag object SHA")
    p_prep.add_argument("--target-peeled-commit", required=True, help="40-hex peeled commit SHA")

    # 6. validate-upgrade
    p_val = sub.add_parser("validate-upgrade", help="Execute compatibility validation against target Standards")
    p_val.add_argument("--project-root", default=".", help="Target consumer project root directory")
    p_val.add_argument("--target-tag", default=None, help="Select the prepared candidate Tag when multiple candidates exist")
    p_val.add_argument("--evidence-file", default=None, help="Consumer CI evidence JSON (default: candidate directory/consumer-validation-evidence.json)")

    # 7. promote
    p_prom = sub.add_parser("promote", help="Controlled promotion of standards.lock.json with CI and approval gate")
    p_prom.add_argument("--project-root", default=".", help="Target consumer project root directory")
    p_prom.add_argument("--target-tag", required=True, help="Target official tag")
    p_prom.add_argument("--target-version", required=True, help="Target SemVer")
    p_prom.add_argument("--target-tag-object-sha", required=True, help="40-hex annotated tag object SHA")
    p_prom.add_argument("--target-peeled-commit", required=True, help="40-hex peeled commit SHA")
    p_prom.add_argument("--approval-file", required=True, help="Path to approval evidence JSON file")
    # CI status is queried from GitHub Actions; no caller-supplied PASS override is accepted.

    # 8. rollback
    p_rb = sub.add_parser("rollback", help="Rollback standards.lock.json to previous verified lock")
    p_rb.add_argument("--project-root", default=".", help="Target consumer project root directory")

    # 9. recover-tx
    p_rc = sub.add_parser("recover-tx", help="Detect and recover from an interrupted transaction")
    p_rc.add_argument("--project-root", default=".", help="Target consumer project root directory")

    args = parser.parse_args(argv)
    std_root = Path(args.standards_root).resolve() if args.standards_root else None

    if args.subcommand == "discover":
        res = discover_latest_official_tag(
            standards_root=std_root,
            remote_url=args.remote_url,
            repository=args.repo_slug,
            timeout=args.timeout,
        )
        print(json.dumps(res, indent=2))
        if res.get("status") == "PASS":
            return 0
        if res.get("status") == "NOT_VERIFIABLE":
            return 2
        return 1

    if args.subcommand == "verify-lock":
        res = verify_project_lock(
            project_root=Path(args.project_root),
            standards_root=std_root,
        )
        print(json.dumps(res, indent=2))
        if res.get("status") == "PASS":
            return 0
        if res.get("status") == "NOT_VERIFIABLE":
            return 2
        return 1

    if args.subcommand == "compare":
        p_root = Path(args.project_root)
        eff_from = resolve_locked_standards_ref(p_root, args.from_ref)
        if not eff_from:
            print(json.dumps({"status": "BLOCK", "reason": "MISSING_OR_INVALID_STANDARDS_LOCK: Provide a valid exact four-tuple lock or explicit --from-ref for read-only bootstrap analysis"}, indent=2))
            return 1
        res = compare_versions_and_artifacts(
            from_ref=eff_from,
            to_ref=args.to_ref,
            standards_root=std_root,
        )
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") == "PASS" else 1

    if args.subcommand == "impact":
        p_root = Path(args.project_root)
        eff_from = resolve_locked_standards_ref(p_root, args.from_ref)
        if not eff_from:
            print(json.dumps({"status": "BLOCK", "reason": "MISSING_OR_INVALID_STANDARDS_LOCK: Provide a valid exact four-tuple lock or explicit --from-ref for read-only bootstrap analysis"}, indent=2))
            return 1
        res = analyze_consumer_impact(
            project_root=p_root,
            from_ref=eff_from,
            to_ref=args.to_ref,
            standards_root=std_root,
        )
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") == "PASS" else 1

    if args.subcommand == "prepare-upgrade":
        res = prepare_upgrade_candidate(
            project_root=Path(args.project_root),
            target_tag=args.target_tag,
            target_version=args.target_version,
            target_tag_object_sha=args.target_tag_object_sha,
            target_peeled_commit=args.target_peeled_commit,
            standards_root=std_root,
        )
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") in ("CANDIDATE_GENERATED", "READY") else 1

    if args.subcommand == "validate-upgrade":
        res = validate_upgrade_candidate(
            project_root=Path(args.project_root),
            standards_root=std_root,
            target_tag=args.target_tag,
            evidence_file=Path(args.evidence_file) if args.evidence_file else None,
        )
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") == "PASS" else 1

    if args.subcommand == "promote":
        res = promote_upgrade(
            project_root=Path(args.project_root),
            target_tag=args.target_tag,
            target_version=args.target_version,
            target_tag_object_sha=args.target_tag_object_sha,
            target_peeled_commit=args.target_peeled_commit,
            approval_file=Path(args.approval_file),
            ci_status=None,
            standards_root=std_root,
        )
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") == "PROMOTED" else 1

    if args.subcommand == "rollback":
        res = rollback_lock(project_root=Path(args.project_root))
        print(json.dumps(res, indent=2))
        return 0 if res.get("status") == "ROLLED_BACK" else 1

    if args.subcommand == "recover-tx":
        project_root = Path(args.project_root).resolve()
        status = detect_interrupted_transaction(project_root)
        if not status.get("interrupted"):
            print(json.dumps({"status": "CLEAN", "message": "No interrupted transaction detected"}, indent=2))
            return 0
        rec_ok, rec_err = recover_interrupted_transaction(project_root)
        if rec_ok:
            print(json.dumps({"status": "RECOVERED", "message": "Interrupted transaction cleanly rolled back from preserved backups"}, indent=2))
            return 0
        else:
            print(json.dumps({"status": "RECOVERY_FAILED", "error": rec_err}, indent=2))
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
