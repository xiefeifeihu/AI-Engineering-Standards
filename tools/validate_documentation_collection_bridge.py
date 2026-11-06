#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Importable bridge module for tools/validate-documentation-collection.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import List, Optional, Tuple

_VALIDATOR_PATH = Path(__file__).resolve().parent / "validate-documentation-collection.py"
_SPEC = importlib.util.spec_from_file_location("validate_documentation_collection", _VALIDATOR_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

validate_project_docs = _MODULE.validate_project_docs
validate_templates_directory = _MODULE.validate_templates_directory
validate_templates_dir = _MODULE.validate_templates_directory
extract_frontmatter = _MODULE.extract_frontmatter
resolve_standards_root = _MODULE.resolve_standards_root
resolve_schema_path = _MODULE.resolve_schema_path


def run_collection_validation(
    project_root: Path,
    schema_path: Optional[Path] = None,
    standards_root: Optional[Path] = None,
    check_templates: bool = False,
    verify_source_paths: bool = False,
) -> Tuple[bool, List[str]]:
    std_root = resolve_standards_root(standards_root)
    s_path = schema_path or resolve_schema_path(
        project_root=project_root,
        explicit_schema=None,
        explicit_standards_root=std_root,
    )
    return validate_project_docs(
        project_root=project_root,
        schema_path=s_path,
        standards_root=std_root,
        check_templates=check_templates,
        verify_source_paths=verify_source_paths,
    )
