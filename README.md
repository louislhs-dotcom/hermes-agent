# Hermes Security Guard Plugins

Portable, MIT-licensed prompt-injection defense plugins for Hermes Agent.
Extracted and hardened from Louis Ling's local Hermes setup; published here as
standalone, machine-independent code with no local-stack configuration.

## Contents

- **`plugins/security_guard/`** — standalone defense library:
  - `injection_patterns.py` — prompt-injection detection patterns
  - `sanitizer.py` — message sanitization
  - `rate_limiter.py` — per-chat sliding-window rate limiting
  - `quarantine.py` — bounded quarantine store with auto-expiry
  - `response_cache.py` — SQLite-backed response cache with TTL, SHA-256 keys,
    path containment, LRU eviction
  - `path_guard.py` — path-containment guard
  - `security_guard.py` — the combined guard middleware
  - `tests/` — 122 passing tests

- **`plugins/security-gateway/`** — gateway hook that wires the dormant
  security_guard into inbound dispatch (scan before send to the LLM).

## Intent

Defense against prompt injection at the trust boundary: an inbound message is
scanned, sanitized, rate-limited, and quarantined BEFORE it reaches the agent
or LLM. Fail-open by design — a guard error never blocks legitimate traffic.

## Tests

```bash
python3 -m pytest plugins/security_guard/tests   # 122 passed
```

## License

MIT. See individual plugin metadata.
