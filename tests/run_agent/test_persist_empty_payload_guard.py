"""Tests for the persist-time empty-payload guard.

Verifies that empty assistant/user messages (from dead-stream stubs that
escaped the conversation loop's skip guard via early persist paths) are
NOT written to the durable session store, preventing transcript poisoning
that permanently breaks sessions until manual /new or DB surgery.

Root cause: Ollama Cloud stream drops leave empty assistant stubs that
early-turn persistence flushes to the DB before the conversation loop's
``_is_empty_partial_stub`` guard can skip them.  Once in SQLite, the
in-memory ``repair_empty_non_final_messages`` sanitizer heals the wire
copy but never mutates stored history, so the poison is permanent.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestPersistEmptyPayloadGuard:
    """Verify _flush_messages_to_session_db skips empty-payload messages."""

    def _make_agent(self, session_db):
        """Create a minimal AIAgent with a real session DB."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            from run_agent import AIAgent
            agent = AIAgent(
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
                model="test/model",
                quiet_mode=True,
                session_db=session_db,
                session_id="test-session-empty-guard",
                skip_context_files=True,
                skip_memory=True,
            )
        agent._ensure_db_session()
        return agent

    def test_empty_assistant_message_not_persisted(self):
        """An assistant message with content=None and no tool_calls must
        not be written to the session DB."""
        from hermes_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)
            try:
                agent = self._make_agent(db)

                messages = [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": None},  # empty stub
                    {"role": "assistant", "content": "real reply"},
                ]

                agent._flush_messages_to_session_db(messages, [])

                rows = db.get_messages(agent.session_id)
                # Only "hello" and "real reply" should be persisted,
                # NOT the empty assistant stub in the middle.
                assert len(rows) == 2, f"Expected 2 messages, got {len(rows)}"
                assert rows[0]["role"] == "user"
                assert rows[0]["content"] == "hello"
                assert rows[1]["role"] == "assistant"
                assert rows[1]["content"] == "real reply"
            finally:
                db.close()

    def test_empty_user_message_not_persisted(self):
        """An empty user message (content="" with no payload) must not
        be written to the session DB."""
        from hermes_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)
            try:
                agent = self._make_agent(db)

                messages = [
                    {"role": "user", "content": "hello"},
                    {"role": "user", "content": ""},  # empty user msg
                    {"role": "assistant", "content": "reply"},
                ]

                agent._flush_messages_to_session_db(messages, [])

                rows = db.get_messages(agent.session_id)
                assert len(rows) == 2, f"Expected 2 messages, got {len(rows)}"
                assert rows[0]["content"] == "hello"
                assert rows[1]["content"] == "reply"
            finally:
                db.close()

    def test_tool_call_only_assistant_is_persisted(self):
        """An assistant message with tool_calls but no text content must
        still be persisted (tool_calls count as payload)."""
        from hermes_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)
            try:
                agent = self._make_agent(db)

                messages = [
                    {"role": "user", "content": "run a tool"},
                    {"role": "assistant", "content": None,
                     "tool_calls": [{"id": "t1", "type": "function",
                                     "function": {"name": "f", "arguments": "{}"}}]},
                ]

                agent._flush_messages_to_session_db(messages, [])

                rows = db.get_messages(agent.session_id)
                assert len(rows) == 2, f"Expected 2 messages, got {len(rows)}"
                assert rows[1]["role"] == "assistant"
                assert rows[1]["tool_calls"] is not None
            finally:
                db.close()

    def test_reasoning_only_assistant_is_persisted(self):
        """An assistant message with reasoning_content but no text content
        must still be persisted (reasoning counts as payload)."""
        from hermes_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)
            try:
                agent = self._make_agent(db)

                messages = [
                    {"role": "user", "content": "think about it"},
                    {"role": "assistant", "content": None,
                     "reasoning_content": "Let me consider..."},
                ]

                agent._flush_messages_to_session_db(messages, [])

                rows = db.get_messages(agent.session_id)
                assert len(rows) == 2, f"Expected 2 messages, got {len(rows)}"
            finally:
                db.close()

    def test_tool_message_always_persisted(self):
        """Tool messages should NOT be filtered by the empty-payload guard
        (they have their own orphan/pairing validation in the sanitizer)."""
        from hermes_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)
            try:
                agent = self._make_agent(db)

                messages = [
                    {"role": "user", "content": "run tool"},
                    {"role": "assistant", "content": None,
                     "tool_calls": [{"id": "t1", "type": "function",
                                     "function": {"name": "f", "arguments": "{}"}}]},
                    {"role": "tool", "tool_call_id": "t1", "content": ""},
                ]

                agent._flush_messages_to_session_db(messages, [])

                rows = db.get_messages(agent.session_id)
                # All 3 should be persisted — the empty tool result is
                # valid (it has tool_call_id linkage) and NOT subject to
                # the assistant/user-only empty-payload guard.
                assert len(rows) == 3, f"Expected 3 messages, got {len(rows)}"
            finally:
                db.close()

    def test_mixed_empty_and_real_messages(self):
        """A realistic transcript with an empty stub sandwiched between
        real messages should persist only the real ones."""
        from hermes_state import SessionDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDB(db_path=db_path)
            try:
                agent = self._make_agent(db)

                messages = [
                    {"role": "user", "content": "question 1"},
                    {"role": "assistant", "content": "answer 1"},
                    {"role": "user", "content": "question 2"},
                    {"role": "assistant", "content": None},  # dead stream stub
                    {"role": "assistant", "content": None},  # another dead stub
                    {"role": "user", "content": "question 3"},
                    {"role": "assistant", "content": "answer 3"},
                ]

                agent._flush_messages_to_session_db(messages, [])

                rows = db.get_messages(agent.session_id)
                # 5 real messages, 2 empty stubs skipped
                assert len(rows) == 5, f"Expected 5 messages, got {len(rows)}"
                contents = [r["content"] for r in rows]
                assert "answer 1" in contents
                assert "answer 3" in contents
                assert None not in contents
                assert "" not in contents
            finally:
                db.close()