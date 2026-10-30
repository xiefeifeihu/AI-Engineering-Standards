#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate STD-014/STD-034 AI-Driven Test Coverage Verification Report.

Enforces:
1. Schema conformity (schemas/test-coverage-verification.schema.json).
2. Business outcome rigor (BLOCK/CONFIGURED/MOCK_ONLY cannot equal PASS).
3. Required P0 Case ID execution and evidence binding.
4. Detection of unexecuted test functions claiming PASS.
5. Prohibition of Mock in POST_DEPLOY / live production.
6. Prohibition of candidate ports masquerading as production.
7. Detection of weakened or trivial assertions.
8. Detection of screenshots with business / UI errors.
9. Tested commit and target commit consistency.
10. Mandatory change impact analysis for product changes.
11. Detection of silent removal of historical baseline cases.
"""
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "test-coverage-verification.schema.json"

# Common candidate/staging ports that must not be used as production endpoints
CANDIDATE_PORTS = {
    ":8000", ":8080", ":3000", ":5000", ":8001", ":8888", ":8443", ":9000", ":9090"
}

# Trivial assertion patterns
TRIVIAL_ASSERTION_PATTERNS = [
    r"^\s*assert\s+True\s*$",
    r"^\s*assert\s+1\s*==\s*1\s*$",
    r"^\s*assert\s+not\s+False\s*$",
    r"^\s*pass\s*$",
    r"^\s*$"
]

def validate_coverage_record(
    record: Dict[str, Any],
    baseline_record: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Validate a coverage verification record and return a list of error strings."""
    errors: List[str] = []
    
    # 1. JSON Schema validation
    if not SCHEMA_PATH.exists():
        return [f"SCHEMA_FILE_MISSING: {SCHEMA_PATH}"]
    
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for err in validator.iter_errors(record):
            errors.append(f"SCHEMA: {err.message} at '{err.json_path}'")
    except Exception as e:
        return [f"SCHEMA_LOAD_ERROR: {str(e)}"]

    target_commit = record.get("target_commit", "")
    root_tested_commit = record.get("tested_commit")
    stage = record.get("stage", "")
    overall_status = record.get("overall_status", "")

    # Rule 8 & Commit Consistency: root tested_commit must match target_commit if present
    if root_tested_commit and root_tested_commit != target_commit:
        errors.append(f"TESTED_COMMIT_MISMATCH: root tested_commit '{root_tested_commit}' != target_commit '{target_commit}'")

    # Rule 9: Change impact analysis must have non-empty impacted_requirements and change_summary
    impact = record.get("impact_analysis") or {}
    impacted_reqs = impact.get("impacted_requirements") or []
    change_summary = impact.get("change_summary") or ""
    if not impacted_reqs:
        errors.append("MISSING_CHANGE_IMPACT_ANALYSIS: impacted_requirements is empty")
    if len(change_summary.strip()) < 5:
        errors.append("MISSING_CHANGE_IMPACT_ANALYSIS: change_summary is too short or empty")

    required_case_ids = set(record.get("required_case_ids") or [])
    cases = record.get("cases") or []
    case_ids_present = set()

    for idx, c in enumerate(cases):
        cid = c.get("case_id", f"case_{idx}")
        case_ids_present.add(cid)
        status = c.get("status")
        business_outcome = c.get("business_outcome")
        is_mocked = c.get("is_mocked", False)
        exec_mode = c.get("execution_mode")
        c_stage = c.get("stage") or stage
        endpoint = c.get("endpoint", "")
        c_commit = c.get("tested_commit")
        assertion = c.get("outcome_assertion")
        assertion_strength = c.get("assertion_strength")
        evidence_ref = c.get("evidence_ref")
        has_ui_error = c.get("has_ui_error", False)
        priority = c.get("priority")
        test_kind = c.get("test_kind", "POSITIVE")

        # Rule 8: Individual case tested_commit must match target_commit
        if c_commit and c_commit != target_commit:
            errors.append(f"TESTED_COMMIT_MISMATCH: case '{cid}' tested_commit '{c_commit}' != target_commit '{target_commit}'")

        # Rule 1: Positive business gets BLOCK/CONFIGURED/MOCK_ONLY but marked PASS
        if test_kind in ("POSITIVE", "REGRESSION"):
            if status == "PASS" and business_outcome in ("BLOCK", "CONFIGURED", "MOCK_ONLY", "ERROR", "FAILURE"):
                errors.append(f"POSITIVE_OUTCOME_BLOCKED_CANNOT_PASS: case '{cid}' (kind={test_kind}) has business_outcome '{business_outcome}' but status is 'PASS'")
        elif test_kind == "NEGATIVE":
            if status == "PASS" and business_outcome == "SUCCESS":
                errors.append(f"NEGATIVE_TEST_UNEXPECTED_SUCCESS: negative case '{cid}' expected block/failure but got '{business_outcome}'")

        # Rule 3: Test function exists but never actually executed
        if exec_mode == "UNEXECUTED" or status == "NOT_RUN":
            if status == "PASS":
                errors.append(f"UNEXECUTED_TEST_FUNCTION: case '{cid}' is unexecuted/NOT_RUN but claimed PASS")
            if not evidence_ref and status not in ("NOT_RUN", "DEFERRED"):
                errors.append(f"UNEXECUTED_TEST_FUNCTION: case '{cid}' lacks evidence_ref")

        # Rule 4: Using Mock in place of production real call (POST_DEPLOY)
        if c_stage == "POST_DEPLOY":
            if is_mocked:
                errors.append(f"MOCK_USED_IN_LIVE_PRODUCTION: case '{cid}' uses mock in POST_DEPLOY stage")
            if exec_mode == "SIMULATED":
                errors.append(f"MOCK_USED_IN_LIVE_PRODUCTION: case '{cid}' uses SIMULATED mode in POST_DEPLOY stage")

        # Rule 5: Using candidate port test to pretend to be production test
        if c_stage == "POST_DEPLOY" and endpoint:
            for c_port in CANDIDATE_PORTS:
                if c_port in endpoint:
                    errors.append(f"CANDIDATE_PORT_MASQUERADING_AS_PRODUCTION: case '{cid}' uses candidate port '{endpoint}' in POST_DEPLOY")
                    break

        # Rule 6: Assertions deleted or weakened to pass pipeline
        if assertion_strength in ("WEAKENED", "TRIVIAL"):
            errors.append(f"WEAKENED_OR_TRIVIAL_ASSERTION: case '{cid}' has assertion_strength '{assertion_strength}'")
        if isinstance(assertion, str):
            for pat in TRIVIAL_ASSERTION_PATTERNS:
                if re.match(pat, assertion, re.IGNORECASE):
                    errors.append(f"WEAKENED_OR_TRIVIAL_ASSERTION: case '{cid}' has trivial assertion string '{assertion.strip()}'")
                    break
        elif isinstance(assertion, dict):
            if assertion.get("type") == "TRIVIAL" or assertion.get("weakened") is True:
                errors.append(f"WEAKENED_OR_TRIVIAL_ASSERTION: case '{cid}' has weakened assertion dict")

        # Rule 7: Screenshot exists but target business result is wrong / UI error present
        if evidence_ref and any(ext in evidence_ref.lower() for ext in (".png", ".jpg", "screenshot")):
            if has_ui_error:
                errors.append(f"SCREENSHOT_CONTAINS_BUSINESS_ERROR: case '{cid}' has_ui_error=true despite screenshot evidence")
            if business_outcome in ("ERROR", "FAILURE"):
                errors.append(f"SCREENSHOT_CONTAINS_BUSINESS_ERROR: case '{cid}' business_outcome='{business_outcome}' despite screenshot")

        # P0 cases failure check
        if priority == "P0" and status in ("FAIL", "BLOCK", "NOT_RUN", "NOT_VERIFIABLE") and overall_status == "PASS":
            errors.append(f"P0_REQUIRED_CASE_FAILED: P0 case '{cid}' has status '{status}', overall_status cannot be PASS")

    # Rule 2: Critical required Case IDs must have execution record
    missing_required = required_case_ids - case_ids_present
    if missing_required:
        errors.append(f"REQUIRED_CASE_NOT_EXECUTED: required cases missing: {sorted(missing_required)}")

    for c in cases:
        cid = c.get("case_id")
        if cid in required_case_ids:
            c_status = c.get("status")
            c_exec = c.get("execution_mode")
            if c_status in ("NOT_RUN", "NOT_RECORDED") or c_exec == "UNEXECUTED":
                errors.append(f"REQUIRED_CASE_NOT_EXECUTED: required case '{cid}' was not executed (status={c_status}, mode={c_exec})")

    # Rule 10: Silent removal of historical baseline cases
    if baseline_record:
        baseline_cases = {bc.get("case_id") for bc in baseline_record.get("cases", []) if bc.get("case_id")}
        retired_case_ids = {rc.get("case_id") for rc in record.get("retired_cases", []) if rc.get("case_id")}
        
        missing_from_current = baseline_cases - case_ids_present
        silent_removals = missing_from_current - retired_case_ids
        if silent_removals:
            errors.append(f"SILENT_REMOVAL_OF_HISTORICAL_CASE: historical cases removed without declared justification in retired_cases: {sorted(silent_removals)}")

    # Overall Status Gate Consistency
    if overall_status == "PASS":
        if any(c.get("status") != "PASS" for c in cases if c.get("priority") == "P0"):
            errors.append("OVERALL_STATUS_PASS_WITH_NON_PASS_P0_CASES")
        uncovered_p0 = record.get("uncovered_p0_gaps") or []
        if uncovered_p0:
            errors.append("OVERALL_STATUS_PASS_WITH_UNCOVERED_P0_GAPS")

    return errors

def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/validate_test_coverage.py <coverage_report.json> [--baseline <baseline.json>]")
        return 2

    report_path = Path(sys.argv[1])
    baseline_path = None
    if "--baseline" in sys.argv:
        idx = sys.argv.index("--baseline")
        if idx + 1 < len(sys.argv):
            baseline_path = Path(sys.argv[idx + 1])

    if not report_path.exists():
        print(f"ERROR: Report file not found: {report_path}")
        return 1

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to parse JSON report: {e}")
        return 1

    baseline_data = None
    if baseline_path:
        if not baseline_path.exists():
            print(f"ERROR: Baseline file not found: {baseline_path}")
            return 1
        try:
            baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"ERROR: Failed to parse baseline JSON: {e}")
            return 1

    errors = validate_coverage_record(data, baseline_record=baseline_data)
    if errors:
        print(json.dumps({"status": "BLOCK", "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({
        "status": "VALID_COVERAGE_REPORT",
        "task_id": data.get("task_id"),
        "cases_validated": len(data.get("cases", [])),
        "overall_status": data.get("overall_status")
    }, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
