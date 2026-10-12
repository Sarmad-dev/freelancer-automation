from __future__ import annotations

import hashlib
import json
from typing import Any


def definition_checksum(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    """Stable SHA-256 over the canonical content of a workflow version (order-independent)."""
    canonical = {
        "nodes": sorted(
            ({k: n[k] for k in ("key", "type", "config")} for n in nodes),
            key=lambda n: str(n["key"]),
        ),
        "edges": sorted(
            ({k: e.get(k) for k in ("key", "source", "target", "branch")} for e in edges),
            key=lambda e: str(e["key"]),
        ),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
