"""Conversation context compaction inspired by Claude Code's harness."""

from __future__ import annotations

from dataclasses import dataclass

from digital_employee.domain.session import ConversationMessage, ConversationSession, SessionCompactState


@dataclass(slots=True)
class PreparedContext:
    strategy: str
    summary: str
    recent_messages: list[ConversationMessage]
    total_tokens: int
    retained_tokens: int


class ContextCompactor:
    """Prepare provider-facing context under a bounded token budget."""

    def __init__(
        self,
        *,
        max_context_tokens: int = 2000,
        recent_message_window: int = 6,
        compaction_target_tokens: int = 400,
    ) -> None:
        self._max_context_tokens = max_context_tokens
        self._recent_message_window = recent_message_window
        self._compaction_target_tokens = compaction_target_tokens

    def prepare(self, session: ConversationSession) -> PreparedContext:
        cleaned = self.snip(session.messages)
        total_tokens = self._count_tokens(cleaned)
        if total_tokens <= self._max_context_tokens:
            state = SessionCompactState(
                strategy="none",
                summary="",
                source_message_count=len(cleaned),
                total_tokens=total_tokens,
                retained_tokens=total_tokens,
            )
            session.compact_state = state
            session.messages = cleaned
            return PreparedContext(
                strategy=state.strategy,
                summary=state.summary,
                recent_messages=list(cleaned),
                total_tokens=state.total_tokens,
                retained_tokens=state.retained_tokens,
            )

        recent = cleaned[-self._recent_message_window :] if self._recent_message_window > 0 else []
        older = cleaned[: max(len(cleaned) - len(recent), 0)]
        summary = self.microcompact(older)
        retained_tokens = self._count_tokens(recent) + self._estimate_tokens(summary)
        state = SessionCompactState(
            strategy="autocompact",
            summary=summary,
            source_message_count=len(cleaned),
            total_tokens=total_tokens,
            retained_tokens=retained_tokens,
        )
        session.compact_state = state
        session.messages = recent
        return PreparedContext(
            strategy=state.strategy,
            summary=state.summary,
            recent_messages=list(recent),
            total_tokens=state.total_tokens,
            retained_tokens=state.retained_tokens,
        )

    def snip(self, messages: list[ConversationMessage]) -> list[ConversationMessage]:
        trimmed: list[ConversationMessage] = []
        for message in messages:
            content = message.content.strip()
            if not content and not self._should_preserve_empty_message(message):
                continue
            if trimmed:
                previous = trimmed[-1]
                if (
                    previous.role == message.role
                    and previous.content == content
                    and message.role in {"system", "tool"}
                ):
                    trimmed[-1] = message
                    continue
            trimmed.append(
                ConversationMessage(
                    role=message.role,
                    content=content,
                    metadata=dict(message.metadata),
                    token_estimate=message.token_estimate or self._estimate_tokens(content),
                    created_at=message.created_at,
                )
            )
        return trimmed

    def microcompact(self, messages: list[ConversationMessage]) -> str:
        if not messages:
            return ""

        lines: list[str] = []
        for message in messages:
            if message.role == "user":
                prefix = "User"
            elif message.role == "assistant":
                prefix = "Assistant"
            elif message.role == "tool":
                tool_name = message.metadata.get("tool_name", "tool")
                prefix = f"Tool {tool_name}"
            else:
                prefix = message.role.capitalize()
            lines.append(f"{prefix}: {self._truncate_words(message.content, 14)}")

        words: list[str] = []
        for line in lines:
            candidate = words + line.split()
            if len(candidate) > self._compaction_target_tokens:
                break
            words = candidate
        if not words:
            words = lines[0].split()[: self._compaction_target_tokens]
        return " ".join(words)

    def _count_tokens(self, messages: list[ConversationMessage]) -> int:
        return sum(message.token_estimate or self._estimate_tokens(message.content) for message in messages)

    def _estimate_tokens(self, text: str) -> int:
        return max(len(text.split()), 1) if text else 0

    def _truncate_words(self, text: str, limit: int) -> str:
        words = text.split()
        if len(words) <= limit:
            return text
        return " ".join(words[:limit]) + " ..."

    def _should_preserve_empty_message(self, message: ConversationMessage) -> bool:
        if message.role == "assistant" and message.metadata.get("tool_calls"):
            return True
        return False
