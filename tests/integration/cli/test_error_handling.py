"""Tests for CLI error handling — catch-all and config blocking."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from digital_employee.api.cli.main import main


class ExceptionCatchAllTest(unittest.TestCase):
    """Unexpected exceptions must be caught and converted to structured errors."""

    def test_unexpected_error_returns_exit_1_json(self) -> None:
        with patch(
            "digital_employee.api.cli.main.build_deps",
            side_effect=RuntimeError("boom"),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                code = main(["--json", "config", "show"])
            self.assertEqual(code, 10)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"]["type"], "internal_error")
            self.assertEqual(payload["error"]["code"], 10)
            self.assertIsNone(payload["error"]["hint"])

    def test_unexpected_error_returns_exit_1_human(self) -> None:
        with patch(
            "digital_employee.api.cli.main.build_deps",
            side_effect=RuntimeError("boom"),
        ):
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = main(["config", "show"])
            self.assertEqual(code, 10)
            self.assertIn("unexpected error", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_input_file_error_maps_to_exit_2_json(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "--json",
                    "employee",
                    "test",
                    "sales-assistant",
                    "--input-file",
                    "/tmp/does-not-exist.txt",
                ]
            )
        self.assertEqual(code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "input_file_unreadable")
        self.assertEqual(payload["error"]["code"], 2)

    def test_input_file_error_maps_to_exit_2_human(self) -> None:
        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            code = main(
                [
                    "employee",
                    "test",
                    "sales-assistant",
                    "--input-file",
                    "/tmp/does-not-exist.txt",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("failed to read input file", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


class ConfigBlockingTest(unittest.TestCase):
    """Commands other than config show/validate/version must fail on bad config."""

    def _run_with_bad_config(self, argv: list[str]) -> tuple[int, dict]:
        """Run CLI with a config dir that has no providers (triggers validation error)."""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "configs"
            config_dir.mkdir()
            (config_dir / "system.yaml").write_text("runtime:\n  default_timeout_seconds: 30\n")
            (config_dir / "providers").mkdir()
            (config_dir / "agents").mkdir()
            (config_dir / "policies").mkdir()

            stdout = io.StringIO()
            with patch.dict(os.environ, {"DE_STATE_DIR": tmp}, clear=False):
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    original_cwd = Path.cwd()
                    os.chdir(tmp)
                    try:
                        code = main(["--json"] + argv)
                    finally:
                        os.chdir(original_cwd)
            payload = json.loads(stdout.getvalue())
            return code, payload

    def test_work_order_create_blocked_on_bad_config(self) -> None:
        code, payload = self._run_with_bad_config(
            ["work-order", "create", "--employee", "x", "--input", "hi"]
        )
        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "config_invalid")

    def test_employee_list_blocked_on_bad_config(self) -> None:
        code, payload = self._run_with_bad_config(["employee", "list"])
        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])

    def test_config_show_allowed_on_bad_config(self) -> None:
        code, payload = self._run_with_bad_config(["config", "show"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])

    def test_config_validate_allowed_on_bad_config(self) -> None:
        code, payload = self._run_with_bad_config(["config", "validate"])
        self.assertEqual(code, 3)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "config_invalid")

    def test_malformed_config_returns_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "configs"
            config_dir.mkdir()
            (config_dir / "system.yaml").write_text("runtime: [\n", encoding="utf-8")
            (config_dir / "providers").mkdir()
            (config_dir / "agents").mkdir()
            (config_dir / "policies").mkdir()

            stdout = io.StringIO()
            with patch.dict(os.environ, {"DE_STATE_DIR": tmp}, clear=False):
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    original_cwd = Path.cwd()
                    os.chdir(tmp)
                    try:
                        code = main(["--json", "config", "show"])
                    finally:
                        os.chdir(original_cwd)

        self.assertEqual(code, 3)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "config_invalid")


class TenantIsolationCLITest(unittest.TestCase):
    """CLI-level test: tenant-a work orders are invisible to tenant-b."""

    def test_tenant_b_cannot_see_tenant_a_work_orders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"DE_STATE_DIR": temp_dir}, clear=False):
                # Create a work order under tenant-a
                create_stdout = io.StringIO()
                with redirect_stdout(create_stdout):
                    create_code = main(
                        [
                            "--json",
                            "--tenant",
                            "tenant-a",
                            "work-order",
                            "create",
                            "--employee",
                            "sales-assistant",
                            "--input",
                            "Confidential tenant-a task",
                        ]
                    )
                self.assertEqual(create_code, 0)
                created = json.loads(create_stdout.getvalue())
                work_order_id = created["data"]["work_order"]["work_order_id"]

                # tenant-a can see its own work order
                get_a_stdout = io.StringIO()
                with redirect_stdout(get_a_stdout):
                    get_a_code = main(
                        ["--json", "--tenant", "tenant-a", "work-order", "get", work_order_id]
                    )
                self.assertEqual(get_a_code, 0)

                # tenant-b list must not contain tenant-a's work order
                list_b_stdout = io.StringIO()
                with redirect_stdout(list_b_stdout):
                    list_b_code = main(
                        ["--json", "--tenant", "tenant-b", "work-order", "list"]
                    )
                self.assertEqual(list_b_code, 0)
                list_b_payload = json.loads(list_b_stdout.getvalue())
                listed_ids = [
                    wo["work_order_id"]
                    for wo in list_b_payload["data"]["work_orders"]
                ]
                self.assertNotIn(work_order_id, listed_ids)

                # tenant-b get must not return tenant-a's work order
                get_b_stdout = io.StringIO()
                with redirect_stdout(get_b_stdout):
                    get_b_code = main(
                        ["--json", "--tenant", "tenant-b", "work-order", "get", work_order_id]
                    )
                self.assertNotEqual(get_b_code, 0)


if __name__ == "__main__":
    unittest.main()
