"""
Lightweight tencentdb_agent_memory SDK shim.

Provides MemoryClient, AsyncMemoryClient, and TDAMError using raw HTTP
calls against the TDAI Gateway v2 API. Drop-in replacement for the
proprietary SDK package — no external dependencies beyond urllib.

Install: this file lives at tools/tencentdb_agent_memory.py and is
importable as `tencentdb_agent_memory` when tools/ is on sys.path
(the memory_tencentdb_v2 plugin already adds it).
"""

from __future__ import annotations

import json as _json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


class TDAMError(Exception):
    """TencentDB Agent Memory error."""
    pass


class _BaseClient:
    """Shared HTTP logic for sync and async clients."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8420",
        api_key: str = "local",
        service_id: str = "default",
        timeout: float = 10.0,
    ):
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._service_id = service_id
        self._timeout = timeout

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "x-tdai-service-id": self._service_id}
        if self._api_key and self._api_key != "local":
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _post(self, path: str, body: dict) -> dict:
        data = _json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self._endpoint}{path}",
            data=data,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return _json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise TDAMError(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            raise TDAMError(str(e)) from e

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(
            f"{self._endpoint}{path}",
            headers=self._headers(),
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return _json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise TDAMError(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            raise TDAMError(str(e)) from e


class MemoryClient(_BaseClient):
    """Synchronous TencentDB Agent Memory v2 client."""

    # ── L0: Conversation ──────────────────────────────────────────────

    def add_conversation(
        self, session_id: str, messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Add conversation turns to L0."""
        return self._post(
            "/v2/conversation/add",
            {"session_id": session_id, "messages": messages},
        )

    def search_conversation(
        self, query: str, limit: int = 5
    ) -> Dict[str, Any]:
        """Search L0 conversations (instant, raw turns)."""
        return self._post(
            "/v2/conversation/search",
            {"query": query, "limit": limit},
        )

    # ── L1: Atomic memories ───────────────────────────────────────────

    def search_atomic(
        self, query: str, limit: int = 5
    ) -> Dict[str, Any]:
        """Search L1 atomic memories (semantic, may lag new writes)."""
        return self._post(
            "/v2/atomic/search",
            {"query": query, "limit": limit},
        )

    # ── L2: Scene blocks ──────────────────────────────────────────────

    def list_scenarios(self) -> Dict[str, Any]:
        """List available L2 scene blocks."""
        return self._post("/v2/scenario/ls", {})

    def read_scenario(self, path: str) -> Dict[str, Any]:
        """Read a specific L2 scene block by path."""
        return self._post(
            "/v2/scenario/read",
            {"path": path},
        )

    # ── L3: Core / persona ────────────────────────────────────────────

    def read_core(self) -> Dict[str, Any]:
        """Read L3 core/persona content."""
        return self._post("/v2/core/read", {})

    # ── Health ────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        """Check gateway health."""
        return self._get("/health")


class AsyncMemoryClient(_BaseClient):
    """
    Async-compatible client. Uses the same sync HTTP underneath —
    wrap in asyncio.to_thread() for true async usage.
    """

    async def add_conversation(
        self, session_id: str, messages: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(
            self._post, "/v2/conversation/add",
            {"session_id": session_id, "messages": messages},
        )

    async def search_conversation(
        self, query: str, limit: int = 5
    ) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(
            self._post, "/v2/conversation/search",
            {"query": query, "limit": limit},
        )

    async def search_atomic(
        self, query: str, limit: int = 5
    ) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(
            self._post, "/v2/atomic/search",
            {"query": query, "limit": limit},
        )

    async def list_scenarios(self) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(self._post, "/v2/scenario/ls", {})

    async def read_scenario(self, path: str) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(
            self._post, "/v2/scenario/read", {"path": path},
        )

    async def read_core(self) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(self._post, "/v2/core/read", {})


__version__ = "0.1.0-shim"