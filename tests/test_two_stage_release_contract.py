"""STD-014/STD-032 two-stage live acceptance contract: positive and negative cases."""
import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.validate_two_stage_release import validate_record

SHA = "a" * 40
OTHER = "b" * 40
DATE = "2026-10-29T08:00:00Z"

def valid_service():
    return {
        "schema_version":"1.0.0", "repository":"example/service", "release_version":"v1.0.0",
        "target_commit":SHA, "deployment_kind":"SERVICE", "release_task_id":"task-123",
        "pre_release":{"status":"PASS","run_id":"pre-run-001","tested_commit":SHA,"evidence_ref":"evidence/pre-release/logs","finished_at":"2026-10-29T08:00:00Z"},
        "deployment":{"status":"PASS","run_id":"deployment-001","live_commit":SHA,"build_commit":SHA,"deployed_at":"2026-10-29T08:10:00Z",
            "identity_evidence_ref":"evidence/live/identity","artifact_kind":"LOCAL_DOCKER_IMAGE_ID","artifact_value":"sha256:"+"c"*64},
        "post_deploy":{"status":"PASS","run_id":"post-run-001","observed_live_commit":SHA,"started_at":"2026-10-29T08:11:00Z","finished_at":"2026-10-29T08:15:00Z",
            "coverage_plan_ref":"docs/product-baseline/critical-journeys","required_journey_ids":["critical-01"],
            "journeys":[{"journey_id":"critical-01","status":"PASS","execution_mode":"LIVE_BROWSER",
                "real_endpoint":"http://127.0.0.1:80", "expected_outcome_ref":"docs/product-baseline/expected",
                "actual_outcome_ref":"evidence/live/result","evidence_ref":"evidence/live/playwright-and-api"}],
            "evidence_ref":"evidence/post-deploy/report"},
        "tag_commit":SHA, "overall_status":"PASS"
    }

class TwoStageReleaseTests(unittest.TestCase):
    def test_live_service_valid(self):
        self.assertEqual(validate_record(valid_service()), [])

    def test_live_failure_overrides_pre_release_green(self):
        item=valid_service()
        item["post_deploy"]["status"]="FAIL"
        self.assertTrue(validate_record(item))
        item=valid_service()
        item["post_deploy"]["journeys"][0]["status"]="FAIL"
        self.assertTrue(validate_record(item))

    def test_wrong_live_commit_must_block(self):
        item=valid_service();item["deployment"]["live_commit"]=OTHER
        self.assertIn("LIVE_COMMIT_MISMATCH",validate_record(item))
        item=valid_service();item["post_deploy"]["observed_live_commit"]=OTHER
        self.assertIn("POST_LIVE_COMMIT_MISMATCH",validate_record(item))

    def test_candidate_ci_not_live_test(self):
        item=valid_service()
        item["post_deploy"]["status"]="NOT_VERIFIABLE"
        self.assertTrue(validate_record(item))
        item=valid_service()
        item["post_deploy"].pop("journeys")
        self.assertTrue(validate_record(item))

    def test_post_deploy_must_start_after_deploy(self):
        item=valid_service();item["post_deploy"]["started_at"]="2026-10-29T08:05:00Z"
        self.assertIn("POST_TEST_BEFORE_DEPLOY",validate_record(item))

    def test_required_journey_coverage_must_exist(self):
        item=valid_service();item["post_deploy"]["required_journey_ids"].append("critical-02")
        self.assertIn("CRITICAL_JOURNEY_COVERAGE_INCOMPLETE",validate_record(item))
        item=valid_service();item["post_deploy"]["journeys"].append(copy.deepcopy(item["post_deploy"]["journeys"][0]))
        self.assertIn("CRITICAL_JOURNEY_COVERAGE_INCOMPLETE",validate_record(item))

    def test_tag_and_pre_status(self):
        item=valid_service();item["tag_commit"]=OTHER
        self.assertIn("TAG_COMMIT_MISMATCH",validate_record(item))
        item=valid_service();item["pre_release"]["status"]="FAIL"
        self.assertIn("PRE_RELEASE_NOT_PASS",validate_record(item))

    def test_no_runtime_artifact_is_separate(self):
        item=valid_service()
        item["deployment_kind"]="NON_RUNTIME_ARTIFACT"
        item["deployment"]={"status":"NOT_APPLICABLE"}
        item["post_deploy"]={"status":"NOT_APPLICABLE"}
        item["published_artifact_verification"]={"status":"PASS","evidence_ref":"evidence/standards/schema-ci","verified_ref":"official/main-and-tag"}
        self.assertEqual(validate_record(item),[])
        item["published_artifact_verification"]["status"]="BLOCK"
        self.assertTrue(validate_record(item))

if __name__ == "__main__":
    unittest.main()
