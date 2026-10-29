#!/usr/bin/env python3
"""Validate v2.10.0 two-stage release evidence. Structural PASS is not execution proof."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "two-stage-release-acceptance.schema.json"

def _time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

def validate_record(data):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [f"SCHEMA: {e.message}" for e in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data)]
    target = data.get("target_commit")
    pre = data.get("pre_release") or {}
    dep = data.get("deployment") or {}
    post = data.get("post_deploy") or {}
    if pre.get("tested_commit") and pre["tested_commit"] != target:
        errors.append("PRE_RELEASE_COMMIT_MISMATCH")
    if data.get("overall_status") == "PASS":
        if pre.get("status") != "PASS":
            errors.append("PRE_RELEASE_NOT_PASS")
        if data.get("tag_commit") != target:
            errors.append("TAG_COMMIT_MISMATCH")
        if data.get("deployment_kind") == "SERVICE":
            for field in ("live_commit", "build_commit"):
                if dep.get(field) != target:
                    errors.append(f"{field.upper()}_MISMATCH")
            if post.get("observed_live_commit") != target:
                errors.append("POST_LIVE_COMMIT_MISMATCH")
            if dep.get("run_id") == post.get("run_id"):
                errors.append("PRE_POST_RUN_ID_NOT_DISTINCT")
            actual = [c.get("journey_id") for c in post.get("journeys", [])]
            required = post.get("required_journey_ids", [])
            if len(actual) != len(set(actual)) or not set(required).issubset(set(actual)):
                errors.append("CRITICAL_JOURNEY_COVERAGE_INCOMPLETE")
            if any(c.get("status") != "PASS" for c in post.get("journeys", [])):
                errors.append("POST_JOURNEY_NOT_PASS")
            try:
                if _time(post["started_at"]) < _time(dep["deployed_at"]):
                    errors.append("POST_TEST_BEFORE_DEPLOY")
                if _time(post["finished_at"]) < _time(post["started_at"]):
                    errors.append("POST_TIME_REVERSED")
            except (KeyError, ValueError, TypeError):
                errors.append("POST_TIME_UNVERIFIABLE")
        elif data.get("deployment_kind") == "NON_RUNTIME_ARTIFACT":
            if (data.get("published_artifact_verification") or {}).get("status") != "PASS":
                errors.append("ARTIFACT_VERIFICATION_NOT_PASS")
        else:
            errors.append("DEPLOYMENT_KIND_UNKNOWN")
    return errors

def main():
    if len(sys.argv) != 2:
        print("Usage: python tools/validate_two_stage_release.py <two_stage_release.json>")
        return 2
    record = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    errors = validate_record(record)
    if errors:
        print(json.dumps({"status":"BLOCK","errors":errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status":"VALID_CONTRACT","note":"External runtime evidence verification is still required"}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
