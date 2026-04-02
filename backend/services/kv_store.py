"""
KV store abstraction for Zwillingstag.

Provides two implementations:
- DiskKVStore   – local development; stores JSON files under a configurable directory
- CloudflareKVStore – Cloudflare Workers KV namespace (accessed via JS interop)

Usage in Workers: the module-level ``current_kv`` is set by middleware at the
start of each request so that services can always call ``get_kv()``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Module-level reference used by services when running inside Cloudflare Workers.
# Set by the Workers lifespan / middleware before any request is processed.
_current_kv: Optional["KVStore"] = None


def set_kv(store: "KVStore") -> None:
    global _current_kv
    _current_kv = store


def get_kv() -> Optional["KVStore"]:
    return _current_kv


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class KVStore:
    """Minimal async KV interface shared by all implementations."""

    async def get(self, key: str) -> Optional[str]:
        raise NotImplementedError

    async def get_json(self, key: str) -> Any:
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception as exc:
            logger.warning("KV JSON parse error for key %s: %s", key, exc)
            return None

    async def put(self, key: str, value: str) -> None:
        raise NotImplementedError

    async def put_json(self, key: str, value: Any) -> None:
        await self.put(key, json.dumps(value, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Disk-based implementation (local development)
# ---------------------------------------------------------------------------


class DiskKVStore(KVStore):
    """Stores values as individual files under *cache_dir*. No TTL."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Sanitise key so it is safe as a file-name component
        safe = key.replace("/", "__").replace(":", "__").replace(" ", "_")
        return self._dir / f"{safe}.kv"

    async def get(self, key: str) -> Optional[str]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("DiskKVStore read error for %s: %s", key, exc)
            return None

    async def put(self, key: str, value: str) -> None:
        p = self._path(key)
        try:
            p.write_text(value, encoding="utf-8")
        except Exception as exc:
            logger.warning("DiskKVStore write error for %s: %s", key, exc)


# ---------------------------------------------------------------------------
# Cloudflare Workers KV implementation
# ---------------------------------------------------------------------------


class CloudflareKVStore(KVStore):
    """
    Wraps a Cloudflare Workers KV namespace binding.

    The *namespace* argument is the JS proxy object obtained from the Workers
    environment (``env.SPEECH_CACHE`` etc.) and passed in during app startup.
    All KV operations are async and are awaited via Pyodide's JS-interop layer.
    """

    def __init__(self, namespace: Any) -> None:
        self._ns = namespace

    async def get(self, key: str) -> Optional[str]:
        try:
            result = await self._ns.get(key)
            # Workers KV returns JS null when a key is missing; Pyodide maps
            # JS null/undefined to Python None automatically.
            if result is None:
                return None
            return str(result)
        except Exception as exc:
            logger.warning("CloudflareKVStore get error for %s: %s", key, exc)
            return None

    async def put(self, key: str, value: str) -> None:
        try:
            await self._ns.put(key, value)
        except Exception as exc:
            logger.warning("CloudflareKVStore put error for %s: %s", key, exc)
