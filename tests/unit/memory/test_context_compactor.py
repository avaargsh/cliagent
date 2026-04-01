from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from digital_employee.domain.session import ConversationMessage, ConversationSession
from digital_employee.memory.context_compactor import ContextCompactor


class ContextCompactorTest(unittest.TestCase):
    def test_snip_deduplicates_stale_tool_messages(self) -> None:
        session = ConversationSession(session_id="s1", work_order_id="wo1")
        session.messages = [
            ConversationMessage(role="tool", content="same", metadata={"tool_name": "x"}, token_estimate=1),
            ConversationMessage(role="tool", content="same", metadata={"tool_name": "x"}, token_estimate=1),
            ConversationMessage(role="assistant", content="keep", token_estimate=1),
        ]
        compactor = ContextCompactor(max_context_tokens=10, recent_message_window=2, compaction_target_tokens=5)
        trimmed = compactor.snip(session.messages)
        self.assertEqual(len(trimmed), 2)
        self.assertEqual(trimmed[0].role, "tool")

    def test_prepare_autocompacts_old_messages(self) -> None:
        session = ConversationSession(session_id="s1", work_order_id="wo1")
        for idx in range(8):
            session.add_message("user" if idx % 2 == 0 else "assistant", f"message {idx} with several words")
        compactor = ContextCompactor(max_context_tokens=10, recent_message_window=2, compaction_target_tokens=12)
        prepared = compactor.prepare(session)
        self.assertEqual(prepared.strategy, "autocompact")
        self.assertTrue(prepared.summary)
        self.assertEqual(len(prepared.recent_messages), 2)
        self.assertEqual(session.compact_state.strategy, "autocompact")

    def test_snip_preserves_empty_assistant_message_with_tool_calls(self) -> None:
        session = ConversationSession(session_id="s1", work_order_id="wo1")
        session.messages = [
            ConversationMessage(
                role="assistant",
                content="",
                metadata={
                    "tool_calls": [
                        {
                            "tool_name": "knowledge-search",
                            "payload": {"query": "upsell playbook"},
                            "tool_call_id": "call_1",
                        }
                    ]
                },
                token_estimate=0,
            ),
            ConversationMessage(
                role="tool",
                content='{"matches":["renewal script"]}',
                metadata={"tool_name": "knowledge-search", "tool_call_id": "call_1"},
                token_estimate=1,
            ),
        ]
        compactor = ContextCompactor(max_context_tokens=10, recent_message_window=2, compaction_target_tokens=5)
        trimmed = compactor.snip(session.messages)
        self.assertEqual(len(trimmed), 2)
        self.assertEqual(trimmed[0].role, "assistant")
        self.assertEqual(trimmed[0].metadata["tool_calls"][0]["tool_call_id"], "call_1")


if __name__ == "__main__":
    unittest.main()
