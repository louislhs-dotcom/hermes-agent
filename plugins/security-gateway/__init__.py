"""security-gateway — wire the dormant security_guard plugin into the gateway.

The security_guard plugin (114/114 tests) was built but never activated. This
plugin bridges its injection detection into the gateway's pre_gateway_dispatch
hook, so every inbound user message is scanned for prompt injection BEFORE
auth/dispatch.

Hook contract (gateway/run.py:14277):
  kwargs: event (MessageEvent), gateway (GatewayRunner), session_store
  return: {"action": "skip", "reason": ...}  -> drop (plugin handled)
          {"action": "rewrite", "text": ...} -> replace text, continue
          {"action": "allow"} / None         -> normal dispatch

Behavior:
  - Scans event.text for injection patterns (system_override, jailbreak, etc.)
  - On match: logs, quarantines, and returns {"action": "skip"} so the message
    is dropped (never reaches the agent / LLM).
  - Fail-open: any error in the guard lets the message through (never blocks
    legitimate traffic on a guard bug).
"""
import logging
import os
import sys

logger = logging.getLogger("security-gateway")

# security_guard lives in ~/.hermes/plugins/security_guard/
_GUARD_DIR = os.path.expanduser("~/.hermes/plugins/security_guard")
if _GUARD_DIR not in sys.path:
    sys.path.insert(0, _GUARD_DIR)

# Import lazily so a missing/broken guard never breaks gateway startup.
_match_injection = None
_quarantine = None
_guard_ready = False


def _load_guard():
    global _match_injection, _quarantine, _guard_ready
    if _guard_ready:
        return True
    try:
        from injection_patterns import match_injection
        from quarantine import QuarantineManager
        _match_injection = match_injection
        _quarantine = QuarantineManager()
        _guard_ready = True
        logger.info("security-gateway: security_guard loaded")
        return True
    except Exception as e:
        logger.warning("security-gateway: guard load failed (fail-open): %s", e)
        return False


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", _scan_message)


def _scan_message(event=None, gateway=None, session_store=None, **_kwargs):
    """Scan an inbound message for prompt injection; skip if flagged."""
    try:
        if not _load_guard():
            return None  # fail-open
        if event is None:
            return None
        text = getattr(event, "text", "")
        if not isinstance(text, str) or not text.strip():
            return None

        result = _match_injection(text)
        if result:
            source = getattr(event, "source", None)
            chat_id = getattr(source, "chat_id", "unknown") if source else "unknown"
            logger.warning(
                "security-gateway: injection detected (chat=%s, pattern=%s): %.80r",
                chat_id, result, text,
            )
            # Quarantine for later review.
            try:
                _quarantine.add(chat_id, text, result)
            except Exception:
                pass
            # Drop the message — never let it reach the agent/LLM.
            return {"action": "skip", "reason": f"prompt injection ({result})"}
        return None
    except Exception as e:
        # Fail-open: never block legitimate traffic on a guard bug.
        logger.warning("security-gateway: scan error (fail-open): %s", e)
        return None
