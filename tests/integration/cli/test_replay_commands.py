from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from digital_employee.api.cli.main import main


class CLIReplayCommandsTest(unittest.TestCase):
    def test_replay_run_returns_ledger_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"DE_STATE_DIR": temp_dir}, clear=False):
                create_stdout = io.StringIO()
                with redirect_stdout(create_stdout):
                    create_code = main(
                        [
                            "--json",
                            "work-order",
                            "create",
                            "--employee",
                            "sales-assistant",
                            "--input",
                            "Follow up on open quotes",
                        ]
                    )
                self.assertEqual(create_code, 0)
                work_order_id = json.loads(create_stdout.getvalue())["data"]["work_order"]["work_order_id"]

                with redirect_stdout(io.StringIO()):
                    run_code = main(["--json", "work-order", "run", work_order_id])
                self.assertEqual(run_code, 0)

                replay_stdout = io.StringIO()
                with redirect_stdout(replay_stdout):
                    replay_code = main(["--json", "replay", "run", work_order_id])
                self.assertEqual(replay_code, 0)
                replay_payload = json.loads(replay_stdout.getvalue())
                data = replay_payload["data"]["replay"]
                self.assertEqual(data["work_order_id"], work_order_id)
                self.assertGreater(data["event_count"], 0)
                self.assertTrue(data["session_id"])
                self.assertIn("turn.completed", [item["event_type"] for item in data["events"]])

    def test_replay_run_requires_existing_ledger_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"DE_STATE_DIR": temp_dir}, clear=False):
                create_stdout = io.StringIO()
                with redirect_stdout(create_stdout):
                    create_code = main(
                        [
                            "--json",
                            "work-order",
                            "create",
                            "--employee",
                            "sales-assistant",
                            "--input",
                            "Follow up on open quotes",
                        ]
                    )
                self.assertEqual(create_code, 0)
                work_order_id = json.loads(create_stdout.getvalue())["data"]["work_order"]["work_order_id"]

                replay_stdout = io.StringIO()
                with redirect_stdout(replay_stdout):
                    replay_code = main(["--json", "replay", "run", work_order_id])
                self.assertEqual(replay_code, 7)
                replay_payload = json.loads(replay_stdout.getvalue())
                self.assertEqual(replay_payload["error"]["type"], "replay_events_missing")


if __name__ == "__main__":
    unittest.main()
