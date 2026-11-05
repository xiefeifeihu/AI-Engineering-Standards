#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate Project-Level Documentation Collection against STD-035 v3.0.0 Governance Rules."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple
import jsonschema
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.validate_approval_contract import compute_canonical_document_sha256, normalize_sha256, validate_approval_record

FORMAL_DOCUMENT_TYPES: Tuple[str, ...] = (
    "PROJECT_BLUEPRINT",
    "PRODUCT_BASELINE",
    "SYSTEM_ARCHITECTURE",
    "TECHNICAL_DESIGN",
    "API_CONTRACT",
    "PROTOTYPE_UX",
    "TEST_ACCEPTANCE",
    "RELEASE_OPERATIONS",
    "DECISION_RECORD",
    "CROSS_SESSION_HANDOFF",
    "DOCUMENT_INDEX",
    "ENGINEERING_BASELINE",
)

ALWAYS_MANDATORY_TYPES: Set[str] = {
    "DOCUMENT_INDEX",
    "ENGINEERING_BASELINE",
}

CANONICAL_ENTRYPOINT_FILENAMES: Set[str] = {
    "DOCUMENT-INDEX.md",
    "文档总索引.md",
    "当前权威基线.md",
    "ENGINEERING-BASELINE.md",
    "PROJECT-BLUEPRINT.md",
    "PRODUCT-BASELINE.md",
    "SYSTEM-ARCHITECTURE.md",
    "TECHNICAL-DESIGN.md",
    "API-CONTRACT.md",
    "PROTOTYPE-UX.md",
    "TEST-ACCEPTANCE.md",
    "RELEASE-OPERATIONS.md",
    "DECISION-RECORD.md",
    "CROSS-SESSION-HANDOFF.md",
}

ARCHIVE_DIR_NAMES: Set[str] = {
    "archive",
    "99-历史归档",
    "历史档案",
}


def resolve_standards_root(explicit_root: Optional[str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    env_root = os.environ.get("AI_ENGINEERING_STANDARDS_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parent.parent


def resolve_schema_path(
    project_root: Path,
    explicit_schema: Optional[str] = None,
    explicit_standards_root: Optional[str] = None,
) -> Path:
    if explicit_schema:
        return Path(explicit_schema).resolve()
    standards_root = resolve_standards_root(explicit_standards_root)
    candidate_in_standards = standards_root / "schemas" / "documentation-metadata.schema.json"
    if candidate_in_standards.exists():
        return candidate_in_standards
    return project_root / "schemas" / "documentation-metadata.schema.json"


def extract_frontmatter(content: str) -> Optional[Dict[str, Any]]:
    normalized = content.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None
    parts = normalized.split("---\n", 2)
    if len(parts) < 3:
        return None
    try:
        parsed = yaml.safe_load(parts[1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def is_archive_path(doc_file: Path, project_root: Path) -> bool:
    rel_parts = doc_file.relative_to(project_root).parts
    return any(part in ARCHIVE_DIR_NAMES for part in rel_parts)


def parse_markdown_table_paths(content: str) -> List[str]:
    paths: List[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|:---") or stripped.startswith("| ---"):
            continue
        for m in re.finditer(r"`([^`]+)`", stripped):
            val = m.group(1).strip()
            if (
                "/" in val
                and not val.startswith("http")
                and (
                    val.endswith(".md")
                    or val.endswith(".json")
                    or val.endswith(".png")
                    or val.endswith(".svg")
                    or val.endswith(".yaml")
                    or val.endswith("/")
                )
            ):
                paths.append(val.rstrip("/"))
        for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", stripped):
            val = m.group(1).strip().split("#", 1)[0]
            if val and not val.startswith(("http://", "https://", "mailto:", "file://")):
                paths.append(val)
    return sorted(set(paths))


def slugify_heading(heading_text: str) -> str:
    """Convert Markdown heading text to GitHub-compatible anchor slug."""
    text = heading_text.strip()
    # Remove inline code backticks and markdown link formatting
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    text = text.lower()
    # Keep word chars (including Unicode Chinese characters), spaces, and hyphens
    cleaned = re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE)
    slug = re.sub(r"\s+", "-", cleaned.strip())
    return slug


def extract_markdown_headings(content: str) -> Set[str]:
    anchors: Set[str] = set()
    in_code_block = False
    normalized = content.replace("\r\n", "\n")
    # Strip frontmatter
    if normalized.startswith("---\n"):
        parts = normalized.split("---\n", 2)
        if len(parts) >= 3:
            normalized = parts[2]
    for line in normalized.splitlines():
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", s)
        if m:
            slug = slugify_heading(m.group(2))
            if slug:
                anchors.add(slug)
        # Also support explicit <a id="..."></a>
        for am in re.finditer(r'<a\s+(?:id|name)=["\']([^"\']+)["\']', s):
            anchors.add(am.group(1).strip().lower())
    return anchors


def extract_markdown_links(content: str) -> List[str]:
    links: List[str] = []
    in_code_block = False
    normalized = content.replace("\r\n", "\n")
    if normalized.startswith("---\n"):
        parts = normalized.split("---\n", 2)
        if len(parts) >= 3:
            normalized = parts[2]
    for line in normalized.splitlines():
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        # Remove inline code spans before scanning links
        line_no_code = re.sub(r"`[^`]*`", "", line)
        for m in re.finditer(r"!?\[[^\]]*\]\(([^)]+)\)", line_no_code):
            target = m.group(1).strip()
            if target and not target.startswith(("http://", "https://", "mailto:", "conversation://", "file://")):
                links.append(target)
    return links


def git_commit_verifiable(project_root: Path, commit_sha: str) -> bool:
    if not commit_sha or not re.match(r"^[0-9a-f]{40}$", commit_sha):
        return False
    git_dir = project_root / ".git"
    if not git_dir.exists():
        # In isolated temp directories during unit testing without .git, check if commit_sha is 40 hex chars
        # UNLESS a git repo was initialized or expected_commit check is active
        return False
    try:
        res = subprocess.run(
            ["git", "-C", str(project_root), "cat-file", "-e", f"{commit_sha}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res.returncode == 0
    except Exception:
        return False


def validate_templates_directory(templates_dir: Path, schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not templates_dir.exists():
        return [f"MISSING_TEMPLATES_DIR: Templates directory not found at {templates_dir}"]
    templates = sorted(templates_dir.glob("*.template.md"))
    if len(templates) < 12:
        errors.append(
            f"INCOMPLETE_TEMPLATES: Expected 12 formal documentation templates in {templates_dir}, found {len(templates)}"
        )
    seen_types: Set[str] = set()
    for tmpl in templates:
        text = tmpl.read_text(encoding="utf-8")
        fm = extract_frontmatter(text)
        if not fm:
            errors.append(f"TEMPLATE_MISSING_FRONTMATTER: {tmpl.name}")
            continue
        try:
            jsonschema.validate(instance=fm, schema=schema)
            dtype = fm.get("document_type")
            if dtype:
                seen_types.add(dtype)
        except jsonschema.ValidationError as ve:
            errors.append(f"TEMPLATE_SCHEMA_VIOLATION [{tmpl.name}]: {ve.message}")
    missing_tmpl_types = set(FORMAL_DOCUMENT_TYPES) - seen_types
    if missing_tmpl_types:
        errors.append(f"MISSING_TEMPLATE_TYPES: No template found for types: {sorted(missing_tmpl_types)}")
    return errors


def validate_project_docs(
    project_root: Path,
    schema_path: Path,
    standards_root: Optional[Path] = None,
    check_templates: bool = False,
    verify_source_paths: bool = False,
) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    project_root = project_root.resolve()
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    if check_templates:
        std_root = standards_root or resolve_standards_root()
        errors.extend(validate_templates_directory(std_root / "templates" / "documentation", schema))

    manifest_path = project_root / "engineering-manifest.yaml"
    expected_project_id: Optional[str] = None
    applicability_map: Dict[str, Dict[str, Any]] = {}
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            proj_block = manifest.get("project") or {}
            expected_project_id = proj_block.get("id")
            if not expected_project_id:
                errors.append("MANIFEST_MISSING_PROJECT_ID: engineering-manifest.yaml is missing project.id")
            raw_app = proj_block.get("document_type_applicability") or {}
            if not raw_app and "documentation" in proj_block:
                doc_block = proj_block.get("documentation") or {}
                app_list = doc_block.get("applicable_types") or []
                non_app_map = doc_block.get("non_applicable_types") or {}
                raw_app = {t: {"applicable": True} for t in app_list}
                for t, just in non_app_map.items():
                    raw_app[t] = {"applicable": False, "justification": just}
            if isinstance(raw_app, dict):
                applicability_map = raw_app
        except Exception as e:
            errors.append(f"MANIFEST_PARSE_ERROR: Cannot parse engineering-manifest.yaml: {e}")
    else:
        errors.append("MISSING_ENGINEERING_MANIFEST: engineering-manifest.yaml not found in project root")

    # Validate applicability rules
    applicable_types: Set[str] = set(FORMAL_DOCUMENT_TYPES)
    for dtype, rule in applicability_map.items():
        if dtype not in FORMAL_DOCUMENT_TYPES:
            errors.append(f"INVALID_APPLICABILITY_TYPE: Unknown document_type '{dtype}' in engineering-manifest.yaml")
            continue
        if not isinstance(rule, dict) or "applicable" not in rule:
            errors.append(f"INVALID_APPLICABILITY_RULE: '{dtype}' must specify boolean 'applicable'")
            continue
        if rule.get("applicable") is False:
            if dtype in ALWAYS_MANDATORY_TYPES:
                errors.append(f"MANDATORY_TYPE_CANNOT_BE_SKIPPED: '{dtype}' must always be applicable")
                continue
            justification = str(rule.get("justification") or "").strip()
            if len(justification) < 5:
                errors.append(
                    f"MISSING_APPLICABILITY_JUSTIFICATION: Non-applicable type '{dtype}' requires a non-empty justification"
                )
            else:
                applicable_types.discard(dtype)

    docs_dir = project_root / "docs"
    if not docs_dir.exists():
        errors.append("MISSING_DOCS_DIRECTORY: 'docs/' directory does not exist")
        return False, errors

    # Check physical existence of DOCUMENT-INDEX and ENGINEERING_BASELINE
    doc_index_candidates = [
        docs_dir / "DOCUMENT-INDEX.md",
        docs_dir / "文档总索引.md",
        project_root / "DOCUMENT-INDEX.md",
    ]
    existing_doc_indexes = [p for p in doc_index_candidates if p.exists() and p.is_file()]
    if not existing_doc_indexes:
        errors.append(
            "MISSING_DOCUMENT_INDEX: Canonical DOCUMENT-INDEX (docs/DOCUMENT-INDEX.md or docs/文档总索引.md) does not exist"
        )

    baseline_candidates = [
        docs_dir / "当前权威基线.md",
        docs_dir / "ENGINEERING-BASELINE.md",
    ]
    existing_baselines = [p for p in baseline_candidates if p.exists() and p.is_file()]
    if not existing_baselines:
        errors.append(
            "MISSING_ENGINEERING_BASELINE: Canonical ENGINEERING_BASELINE (docs/当前权威基线.md or docs/ENGINEERING-BASELINE.md) does not exist"
        )

    # First pass: collect indexed paths from DOCUMENT-INDEX so we know which files are registered as formal docs
    indexed_rel_paths: Set[str] = set()
    for idx_path in existing_doc_indexes:
        try:
            idx_text = idx_path.read_text(encoding="utf-8")
            for dp in parse_markdown_table_paths(idx_text):
                indexed_rel_paths.add(dp.replace("\\", "/"))
        except Exception:
            pass

    doc_files: List[Path] = sorted(docs_dir.rglob("*.md"))
    root_doc_index = project_root / "DOCUMENT-INDEX.md"
    if root_doc_index.exists() and root_doc_index not in doc_files:
        doc_files.append(root_doc_index)

    active_entrypoints: Dict[str, List[Path]] = {}
    seen_document_ids: Dict[str, Path] = {}
    formal_doc_contents: Dict[Path, str] = {}
    doc_headings_cache: Dict[Path, Set[str]] = {}
    active_source_commits: Dict[str, str] = {}
    has_git = (project_root / ".git").exists()
    head_commit: Optional[str] = None
    if has_git:
        try:
            res = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                head_commit = res.stdout.strip()
        except Exception:
            pass

    for doc_file in doc_files:
        rel_path_str = str(doc_file.relative_to(project_root)).replace("\\", "/")
        try:
            content = doc_file.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"READ_ERROR [{rel_path_str}]: {e}")
            continue

        doc_headings_cache[doc_file.resolve()] = extract_markdown_headings(content)
        fm = extract_frontmatter(content)
        in_archive = is_archive_path(doc_file, project_root)
        is_formal_by_name_or_index = (
            (not in_archive and doc_file.name in CANONICAL_ENTRYPOINT_FILENAMES)
            or (rel_path_str in indexed_rel_paths and not in_archive)
        )

        if fm is None:
            if is_formal_by_name_or_index:
                errors.append(
                    f"MISSING_FORMAL_FRONTMATTER: Formal document '{rel_path_str}' is missing mandatory YAML Frontmatter"
                )
            # Ordinary reference material without frontmatter is allowed
            continue

        formal_doc_contents[doc_file] = content

        # Explicit check for legacy HISTORICAL_ARCHIVE document_type
        raw_dtype = fm.get("document_type")
        if raw_dtype == "HISTORICAL_ARCHIVE":
            errors.append(
                f"DEPRECATED_HISTORICAL_ARCHIVE_TYPE [{rel_path_str}]: 'HISTORICAL_ARCHIVE' is no longer a valid formal document_type in STD-035 v3.0.0; retain original semantic document_type with status='ARCHIVED' and primary_entrypoint=false"
            )
            continue

        # Pre-check archive lifecycle before schema validation so specific error code is emitted
        status = fm.get("status")
        primary = fm.get("primary_entrypoint", False)
        if in_archive or status in ("ARCHIVED", "SUPERSEDED"):
            if status == "ACTIVE":
                errors.append(
                    f"ARCHIVED_DOC_CANNOT_BE_ACTIVE [{rel_path_str}]: Document in archive has status='ACTIVE'"
                )
            if primary is True:
                errors.append(
                    f"ARCHIVED_DOC_CANNOT_BE_PRIMARY [{rel_path_str}]: Historical/archived document must NOT have primary_entrypoint=true"
                )

        # Schema validation
        try:
            jsonschema.validate(instance=fm, schema=schema)
        except jsonschema.ValidationError as ve:
            errors.append(f"FRONTMATTER_SCHEMA_VIOLATION [{rel_path_str}]: {ve.message}")
            continue

        doc_id = str(fm.get("document_id"))
        doc_type = str(fm.get("document_type"))
        project_id = str(fm.get("project_id"))

        # Duplicate document_id check (never silently pick a winner)
        if doc_id in seen_document_ids:
            prev_rel = str(seen_document_ids[doc_id].relative_to(project_root)).replace("\\", "/")
            errors.append(
                f"DUPLICATE_DOCUMENT_ID [{rel_path_str}]: document_id '{doc_id}' conflicts with '{prev_rel}'"
            )
        else:
            seen_document_ids[doc_id] = doc_file

        # Project ID consistency
        if expected_project_id and project_id != expected_project_id:
            errors.append(
                f"PROJECT_ID_MISMATCH [{rel_path_str}]: got '{project_id}', expected '{expected_project_id}'"
            )

        # Canonical Content SHA-256 digest check
        doc_csha = fm.get("content_sha256")
        if doc_csha:
            computed_csha = compute_canonical_document_sha256(content)
            if normalize_sha256(doc_csha) != normalize_sha256(computed_csha):
                errors.append(
                    f"CONTENT_SHA256_MISMATCH [{rel_path_str}]: Frontmatter content_sha256 ({doc_csha}) != computed canonical digest ({computed_csha})"
                )

        # Source commit verification
        source_commit = fm.get("source_commit")
        if source_commit is not None:
            sc_str = str(source_commit).strip()
            if not re.match(r"^[0-9a-f]{40}$", sc_str):
                errors.append(
                    f"UNVERIFIABLE_SOURCE_COMMIT [{rel_path_str}]: source_commit '{source_commit}' must be a 40-character hexadecimal SHA"
                )
            elif not git_commit_verifiable(project_root, sc_str):
                errors.append(
                    f"UNVERIFIABLE_SOURCE_COMMIT [{rel_path_str}]: source_commit '{source_commit}' cannot be verified in Git repository"
                )
            else:
                if verify_source_paths and has_git:
                    res_path = subprocess.run(
                        ["git", "-C", str(project_root), "cat-file", "-e", f"{sc_str}:{rel_path_str}"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if res_path.returncode != 0:
                        hist_ref = fm.get("history_reference")
                        hist_ok = False
                        if hist_ref:
                            res_h = subprocess.run(
                                ["git", "-C", str(project_root), "cat-file", "-e", f"{sc_str}:{hist_ref}"],
                                capture_output=True,
                                text=True,
                                timeout=5,
                            )
                            hist_ok = (res_h.returncode == 0)
                        if not hist_ok:
                            errors.append(
                                f"SOURCE_PATH_MISSING_AT_COMMIT [{rel_path_str}]: Neither document path '{rel_path_str}' nor history_reference '{hist_ref}' exists at source_commit '{sc_str}'"
                            )
                if primary and status in ("ACTIVE", "IN_REVIEW"):
                    active_source_commits[rel_path_str] = sc_str

        # Approval status and evidence verification
        approval_status = fm.get("approval_status")
        approval_ev_ref = fm.get("approval_evidence_ref")
        approval_rec = fm.get("approval_record")

        if status == "ACTIVE":
            if approval_status == "IN_REVIEW":
                errors.append(
                    f"ACTIVE_DOC_WITH_IN_REVIEW_APPROVAL [{rel_path_str}]: Document with status='ACTIVE' cannot have approval_status='IN_REVIEW'"
                )
            elif approval_status not in ("AI_APPROVED", "OWNER_APPROVED"):
                errors.append(
                    f"ACTIVE_DOC_WITHOUT_APPROVAL [{rel_path_str}]: Document with status='ACTIVE' requires approval_status='AI_APPROVED' or 'OWNER_APPROVED'"
                )
            if not approval_ev_ref and not approval_rec:
                errors.append(
                    f"MISSING_APPROVAL_EVIDENCE [{rel_path_str}]: approval_status='{approval_status}' requires approval_evidence_ref or approval_record"
                )

        if status in ("IN_REVIEW", "CANDIDATE") and approval_status in ("AI_APPROVED", "OWNER_APPROVED"):
            errors.append(
                f"IN_REVIEW_DOC_WITH_APPROVED_STATUS [{rel_path_str}]: Document with status='{status}' cannot declare approval_status='{approval_status}'"
            )

        if approval_ev_ref:
            ev_path = project_root / str(approval_ev_ref)
            if not ev_path.exists() or not ev_path.is_file():
                errors.append(
                    f"MISSING_APPROVAL_EVIDENCE_FILE [{rel_path_str}]: approval_evidence_ref '{approval_ev_ref}' does not exist"
                )
            else:
                try:
                    ev_data = json.loads(ev_path.read_text(encoding="utf-8"))
                    ev_ok, ev_errs = validate_approval_record(
                        record=ev_data,
                        target_content=content,
                        expected_commit=str(source_commit) if source_commit else None,
                        repo_root=project_root if has_git else None,
                    )
                    if not ev_ok:
                        for ee in ev_errs:
                            errors.append(f"INVALID_APPROVAL_EVIDENCE [{rel_path_str}]: {ee}")
                    if ev_data.get("approval_status") != approval_status:
                        errors.append(
                            f"APPROVAL_STATUS_MISMATCH [{rel_path_str}]: Frontmatter has '{approval_status}' but evidence has '{ev_data.get('approval_status')}'"
                        )
                except Exception as e:
                    errors.append(f"CORRUPT_APPROVAL_EVIDENCE [{rel_path_str}]: {e}")

        if approval_rec:
            try:
                rec_ok, rec_errs = validate_approval_record(
                    record=approval_rec,
                    target_content=content,
                    expected_commit=str(source_commit) if source_commit else None,
                    repo_root=project_root if has_git else None,
                )
                if not rec_ok:
                    for ee in rec_errs:
                        errors.append(f"INVALID_INLINE_APPROVAL_RECORD [{rel_path_str}]: {ee}")
                if approval_rec.get("approval_status") != approval_status:
                    errors.append(
                        f"APPROVAL_STATUS_MISMATCH [{rel_path_str}]: Frontmatter has '{approval_status}' but inline record has '{approval_rec.get('approval_status')}'"
                    )
            except Exception as e:
                errors.append(f"CORRUPT_INLINE_APPROVAL_RECORD [{rel_path_str}]: {e}")

        # Track active and in-review primary entrypoints
        if primary and status in ("ACTIVE", "IN_REVIEW", "CANDIDATE"):
            active_entrypoints.setdefault(doc_type, []).append(doc_file)

        # Document index table cross-checks
        if doc_type == "DOCUMENT_INDEX" and primary:
            declared_paths = parse_markdown_table_paths(content)
            if not declared_paths:
                errors.append(f"EMPTY_DOCUMENT_INDEX_TABLE [{rel_path_str}]: DOCUMENT-INDEX declares no document paths")
            missing_types_in_index = [t for t in sorted(applicable_types) if t not in content]
            if missing_types_in_index:
                errors.append(
                    f"DOCUMENT_INDEX_MISSING_APPLICABLE_TYPES [{rel_path_str}]: DOCUMENT-INDEX is missing applicable document types: {missing_types_in_index}"
                )
            for dp in declared_paths:
                # Resolve relative to project_root or doc_file.parent
                target_path = project_root / dp
                if not target_path.exists():
                    alt_path = (doc_file.parent / dp).resolve()
                    if alt_path.exists():
                        target_path = alt_path
                if not target_path.exists():
                    errors.append(
                        f"MISSING_INDEX_REFERENCE [{rel_path_str}]: DOCUMENT-INDEX references missing file '{dp}'"
                    )
                elif target_path.is_file() and target_path.stat().st_size == 0:
                    errors.append(
                        f"EMPTY_INDEX_REFERENCE [{rel_path_str}]: DOCUMENT-INDEX references empty file '{dp}'"
                    )

        # Check ENGINEERING_BASELINE dynamic facts & source_commit consistency
        if doc_type == "ENGINEERING_BASELINE" and primary:
            if not source_commit:
                errors.append(
                    f"MISSING_BASELINE_SOURCE_COMMIT [{rel_path_str}]: ENGINEERING_BASELINE must declare verifiable source_commit"
                )
            # Check for PASS without evidence in markdown tables
            for line in content.splitlines():
                if line.strip().startswith("|") and "`PASS`" in line:
                    if any(bad in line for bad in ("`NONE`", "`N/A`", "`NOT_RUN`", "`null`", "|  |")):
                        errors.append(
                            f"PASS_WITHOUT_EVIDENCE [{rel_path_str}]: Baseline table contains PASS status with missing/empty evidence_ref"
                        )

    # Check source_commit consistency across active primary entrypoints when ENGINEERING_BASELINE is present
    if len(set(active_source_commits.values())) > 1:
        errors.append(
            f"SOURCE_COMMIT_MISMATCH: Inconsistent source_commit across active formal documents: {active_source_commits}"
        )

    # Check that every applicable document_type has EXACTLY 1 active primary entrypoint
    for dtype in sorted(applicable_types):
        files = active_entrypoints.get(dtype, [])
        if len(files) == 0:
            errors.append(
                f"MISSING_ACTIVE_PRIMARY_ENTRYPOINT: No ACTIVE document with primary_entrypoint=true found for applicable document_type '{dtype}'"
            )
        elif len(files) > 1:
            rel_files = [str(f.relative_to(project_root)).replace("\\", "/") for f in files]
            errors.append(
                f"MULTIPLE_ACTIVE_PRIMARY_ENTRYPOINTS: Conflicting ACTIVE primary_entrypoint=true documents for '{dtype}' (auto-selection forbidden): {rel_files}"
            )

    # Validate internal Markdown links and heading anchors across all formal documents
    for doc_file, content in formal_doc_contents.items():
        rel_doc = str(doc_file.relative_to(project_root)).replace("\\", "/")
        for raw_link in extract_markdown_links(content):
            if raw_link.startswith("#"):
                anchor = raw_link[1:].strip().lower()
                headings = doc_headings_cache.get(doc_file.resolve(), set())
                if anchor and anchor not in headings:
                    errors.append(
                        f"BROKEN_MARKDOWN_ANCHOR [{rel_doc}]: Internal anchor '#{anchor}' not found in document headings"
                    )
                continue

            path_part, _, anchor_part = raw_link.partition("#")
            target_file = (doc_file.parent / path_part).resolve()
            if not target_file.exists():
                # Also check relative to project_root ONLY if path starts with docs/ or schemas/ or standards/
                alt_target = (project_root / path_part).resolve()
                if path_part.startswith(("docs/", "schemas/", "standards/", "templates/", "tools/", "handoff/")) and alt_target.exists():
                    target_file = alt_target
                else:
                    errors.append(
                        f"BROKEN_MARKDOWN_LINK [{rel_doc}]: Link target '{raw_link}' does not exist"
                    )
                    continue

            if anchor_part and target_file.is_file() and target_file.suffix.lower() == ".md":
                target_headings = doc_headings_cache.get(target_file)
                if target_headings is None:
                    try:
                        target_headings = extract_markdown_headings(target_file.read_text(encoding="utf-8"))
                        doc_headings_cache[target_file] = target_headings
                    except Exception:
                        target_headings = set()
                expected_anchor = anchor_part.strip().lower()
                if expected_anchor not in target_headings:
                    errors.append(
                        f"BROKEN_MARKDOWN_ANCHOR [{rel_doc}]: Anchor '#{expected_anchor}' not found in target '{path_part}'"
                    )

    return len(errors) == 0, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate documentation collection against STD-035 v3.0.0")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--standards-root", default=None, help="Path to AI-Engineering-Standards root directory")
    parser.add_argument("--schema", default=None, help="Path to documentation-metadata.schema.json")
    parser.add_argument(
        "--check-templates",
        action="store_true",
        help="Also validate all templates in templates/documentation/",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    standards_root = resolve_standards_root(args.standards_root)
    schema_path = resolve_schema_path(
        project_root=project_root,
        explicit_schema=args.schema,
        explicit_standards_root=args.standards_root,
    )
    if not schema_path.exists():
        print(f"ERROR: Schema file not found: {schema_path}")
        sys.exit(1)

    print(f"Validating documentation collection in: {project_root}")
    print(f"Using schema: {schema_path}")

    ok, errors = validate_project_docs(
        project_root=project_root,
        schema_path=schema_path,
        standards_root=standards_root,
        check_templates=args.check_templates,
    )
    if ok:
        print("[PASS] Documentation collection conforms to STD-035!")
        sys.exit(0)
    else:
        print(f"[FAIL] Documentation collection validation failed ({len(errors)} issues):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
