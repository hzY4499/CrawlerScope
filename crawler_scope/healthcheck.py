from __future__ import annotations


def check_agentscope_import() -> str:
    import agentscope

    return getattr(agentscope, "__version__", "unknown") or "unknown"
