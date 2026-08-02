from __future__ import annotations


AGENT_ALIASES: dict[str, str] = {
    "k12": "k12_chat",
    "k12_chat": "k12_chat",
    "ttu-online": "online_chat",
    "ttu_online": "online_chat",
    "online_chat": "online_chat",
}


def canonical_agent_id(agent_id: str) -> str:
    """Return the public agent ID while accepting legacy route names."""
    return AGENT_ALIASES.get(agent_id, agent_id)

