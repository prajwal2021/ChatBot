from __future__ import annotations


AGENT_ALIASES: dict[str, str] = {
    "k12": "k12",
    "k12_chat": "k12",
    "ttu-online": "ttu-online",
    "ttu_online": "ttu-online",
    "online_chat": "ttu-online",
}


def canonical_agent_id(agent_id: str) -> str:
    """Return the original public agent ID while accepting newer aliases."""
    normalized = (agent_id or "").strip().lower()
    return AGENT_ALIASES.get(normalized, normalized)
