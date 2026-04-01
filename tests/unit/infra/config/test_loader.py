from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))

from digital_employee.infra.config.loader import load_app_config


ROOT = Path(__file__).resolve().parents[4]


class ConfigLoaderTest(unittest.TestCase):
    def test_loads_defaults(self) -> None:
        config = load_app_config(ROOT)
        self.assertIn("mock", config.providers)
        self.assertIn("outreach-specialist", config.employees)
        self.assertIn("sales-assistant", config.employees)
        self.assertEqual(config.system.api.base_url, "http://localhost:8000")
        self.assertEqual(config.system.runtime.max_context_tokens, 2000)
        self.assertEqual(config.system.runtime.background_task_timeout_seconds, 900)

    def test_null_yaml_sections_do_not_crash(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "configs"
            cfg.mkdir()
            (cfg / "system.yaml").write_text("runtime:\napi:\ncli:\nobservability:\n")
            (cfg / "providers").mkdir()
            (cfg / "agents").mkdir()
            (cfg / "policies").mkdir()
            config = load_app_config(Path(tmp))
        self.assertEqual(config.system.runtime.default_timeout_seconds, 30)
        self.assertEqual(config.system.api.base_url, "http://localhost:8000")

    def test_env_overrides(self) -> None:
        with patch.dict(os.environ, {"DE_BASE_URL": "http://example.test", "DE_OUTPUT": "json"}, clear=False):
            config = load_app_config(ROOT)
        self.assertEqual(config.system.api.base_url, "http://example.test")
        self.assertEqual(config.system.cli.default_output, "json")


if __name__ == "__main__":
    unittest.main()
