from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.standards_sync.cli import resolve_locked_standards_ref
from tools.standards_sync.core import (
    DEFAULT_OFFICIAL_REPO,
    analyze_consumer_impact,
    discover_latest_official_tag,
)

ROOT = Path(__file__).resolve().parents[1]


class ConsumerIntegrationContractTests(unittest.TestCase):
    def test_missing_lock_does_not_resolve_to_a_historical_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(resolve_locked_standards_ref(Path(tmp)))

    def test_missing_lock_blocks_implicit_impact_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze_consumer_impact(Path(tmp), standards_root=ROOT)
        self.assertEqual(result.get("status"), "BLOCK")
        self.assertIn("MISSING_STANDARDS_LOCK", result.get("reason", ""))

    def test_non_official_remote_is_rejected_before_network_access(self) -> None:
        result = discover_latest_official_tag(
            standards_root=ROOT,
            repository=DEFAULT_OFFICIAL_REPO,
            remote_url="https://github.com/example/AI-Engineering-Standards.git",
        )
        self.assertEqual(result.get("status"), "BLOCK")
        self.assertIn("UNOFFICIAL_REMOTE_FORBIDDEN", result.get("reason", ""))

    def test_consumer_templates_do_not_pin_a_historical_latest_version(self) -> None:
        lock_template = (ROOT / "templates" / "standards.lock.template.json").read_text(encoding="utf-8")
        manifest_template = (
            ROOT / "governance" / "templates" / "engineering-manifest.template.yaml"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"version": "2.11.0"', lock_template)
        self.assertNotIn('version: "2.11.0"', manifest_template)
        self.assertIn("{{DISCOVERED_PEELED_COMMIT}}", lock_template)
        self.assertIn("{{DISCOVERED_VERSION}}", manifest_template)

    def test_only_ai_hub_is_the_first_consumer_pilot(self) -> None:
        guide = (
            ROOT / "docs" / "migration"
            / "MIGRATION-GUIDE-BASELINE-SYNC-GOVERNANCE-v3.0.0.md"
        ).read_text(encoding="utf-8")
        self.assertIn("AI-Engineering-Hub", guide)
        self.assertIn("AI-KB", guide)
        self.assertIn("OUT_OF_SCOPE", guide)
        self.assertIn("VTIP", guide)
        self.assertIn("SideCar", guide)


if __name__ == "__main__":
    unittest.main()
