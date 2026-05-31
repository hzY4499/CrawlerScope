from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class CacheStore:
    """Small JSON file cache for public API responses."""

    ALLOWED_NAMESPACES = {"crossref", "openalex", "semantic_scholar", "unpaywall"}
    _KEY_RE = re.compile(r"^[a-f0-9]{64}$")

    def __init__(self, cache_dir: Path = Path("data/cache/api")) -> None:
        self.cache_dir = Path(cache_dir)

    def get_json(self, namespace: str, key: str) -> dict[str, Any] | None:
        path = self._path_for(namespace, key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set_json(self, namespace: str, key: str, data: dict[str, Any]) -> Path:
        path = self._path_for(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def has(self, namespace: str, key: str) -> bool:
        return self._path_for(namespace, key).exists()

    def make_key(self, *parts: str) -> str:
        digest = hashlib.sha256()
        for part in parts:
            digest.update(part.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def _path_for(self, namespace: str, key: str) -> Path:
        if namespace not in self.ALLOWED_NAMESPACES:
            raise ValueError(f"Unsupported cache namespace: {namespace}")
        if not self._KEY_RE.fullmatch(key):
            raise ValueError("Cache key must be a sha256 hex digest from CacheStore.make_key().")
        return self.cache_dir / namespace / f"{key}.json"
