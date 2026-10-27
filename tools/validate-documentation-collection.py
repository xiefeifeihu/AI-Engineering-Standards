#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate Project-Level Documentation Collection against STD-035 Governance Rules."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import jsonschema
import yaml

def extract_frontmatter(content: str) -> Optional[Dict[str, Any]]:
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1])
    except Exception:
        return None

def parse_markdown_table_paths(content: str) -> List[str]:
    paths = []
    for line in content.splitlines():
        if not line.strip().startswith("|"):
            continue
        # Extract backticked paths or markdown links
        for m in re.finditer(r"`([^`]+)`", line):
            val = m.group(1).strip()
            if "/" in val and (val.endswith(".md") or val.endswith(".json") or val.endswith(".png") or val.endswith(".svg") or val.endswith("/")):
                paths.append(val.rstrip("/"))
        for m in re.finditer(r"\(([^)]+\.(?:md|json|png|svg))\)", line):
            val = m.group(1).strip()
            paths.append(val)
    return sorted(set(paths))

def validate_project_docs(project_root: Path, schema_path: Path) -> Tuple[bool, List[str]]:
    errors = []
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    manifest_path = project_root / "engineering-manifest.yaml"
    expected_project_id = None
    if manifest_path.exists():
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            expected_project_id = manifest.get("project", {}).get("id")
        except Exception as e:
            errors.append(f"Cannot parse engineering-manifest.yaml: {e}")

    # Gather markdown files in docs/ and root
    doc_files = []
    docs_dir = project_root / "docs"
    if docs_dir.exists():
        doc_files.extend(list(docs_dir.rglob("*.md")))
    root_doc_index = project_root / "DOCUMENT-INDEX.md"
    if root_doc_index.exists():
        doc_files.append(root_doc_index)

    active_entrypoints: Dict[str, List[Path]] = {}
    doc_metadata_map: Dict[Path, Dict[str, Any]] = {}

    for doc_file in doc_files:
        try:
            content = doc_file.read_text(encoding="utf-8")
        except Exception as e:
            errors.append(f"Cannot read {doc_file.relative_to(project_root)}: {e}")
            continue

        fm = extract_frontmatter(content)
        if not fm:
            # Check if this is an archive doc or template or informal doc
            is_archive = "archive" in doc_file.parts
            if not is_archive and doc_file.name in ("DOCUMENT-INDEX.md", "PROJECT-BLUEPRINT.md", "PRODUCT-BASELINE.md", "SYSTEM-ARCHITECTURE.md", "API-CONTRACT.md"):
                errors.append(f"Missing mandatory YAML Frontmatter in canonical doc: {doc_file.relative_to(project_root)}")
            continue

        # Schema validation
        try:
            jsonschema.validate(instance=fm, schema=schema)
        except jsonschema.ValidationError as ve:
            errors.append(f"Frontmatter schema violation in {doc_file.relative_to(project_root)}: {ve.message}")
            continue

        doc_type = fm.get("document_type")
        status = fm.get("status")
        primary = fm.get("primary_entrypoint", False)
        project_id = fm.get("project_id")
        doc_metadata_map[doc_file] = fm

        # Project ID consistency
        if expected_project_id and project_id != expected_project_id:
            errors.append(f"Project ID mismatch in {doc_file.relative_to(project_root)}: got '{project_id}', expected '{expected_project_id}'")

        # Archive docs lifecycle check
        if "archive" in doc_file.parts:
            if status == "ACTIVE":
                errors.append(f"Archived document must NOT be ACTIVE: {doc_file.relative_to(project_root)} has status='ACTIVE'")
            if primary:
                errors.append(f"Archived document must NOT have primary_entrypoint=true: {doc_file.relative_to(project_root)}")

        # Track active primary entrypoints
        if status == "ACTIVE" and primary:
            active_entrypoints.setdefault(doc_type, []).append(doc_file)

        # Document index table cross-checks
        if doc_type == "DOCUMENT_INDEX":
            declared_paths = parse_markdown_table_paths(content)
            for dp in declared_paths:
                target_path = project_root / dp
                if not target_path.exists():
                    errors.append(f"DOCUMENT-INDEX references missing file: '{dp}' in {doc_file.relative_to(project_root)}")
                elif target_path.is_file() and target_path.stat().st_size == 0:
                    errors.append(f"DOCUMENT-INDEX references empty file: '{dp}' in {doc_file.relative_to(project_root)}")

    # Check for multiple active primary entrypoints
    for dtype, files in active_entrypoints.items():
        if len(files) > 1:
            rel_files = [str(f.relative_to(project_root)) for f in files]
            errors.append(f"Multiple ACTIVE primary_entrypoint=true found for document_type '{dtype}': {rel_files}")

    return len(errors) == 0, errors

def main():
    parser = argparse.ArgumentParser(description="Validate documentation collection against STD-035")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--schema", default=None, help="Path to documentation-metadata.schema.json")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    schema_path = Path(args.schema).resolve() if args.schema else project_root / "schemas" / "documentation-metadata.schema.json"
    if not schema_path.exists():
        standards_candidate = Path("D:/Projects/AI-Engineering-Standards/schemas/documentation-metadata.schema.json")
        if standards_candidate.exists():
            schema_path = standards_candidate
        else:
            print(f"ERROR: Schema file not found: {schema_path}")
            sys.exit(1)

    print(f"Validating documentation collection in: {project_root}")
    print(f"Using schema: {schema_path}")

    ok, errors = validate_project_docs(project_root, schema_path)
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
