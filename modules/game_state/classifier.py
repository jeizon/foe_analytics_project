"""Service-to-domain classification for FoE payload organization."""

from __future__ import annotations

DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gbg", ("GuildBattleground", "Battleground")),
    ("player", ("Player", "User", "Profile", "Startup", "Session")),
    ("resources", ("Resource", "Currency", "Premium", "Inventory", "Reward")),
    ("city", ("City", "Building", "Production", "GreatBuilding", "Construction")),
    ("guild", ("Guild", "Clan", "GuildExpedition", "GuildRaid")),
    ("battle", ("Battlefield", "Army", "Military", "Unit")),
    ("quests", ("Quest", "Task")),
    ("social", ("Friend", "Message", "Tavern", "Conversation")),
    ("map", ("Campaign", "Province", "Continent", "Scouting")),
    ("events", ("Event", "EventPass", "PresentGame", "HiddenReward", "Anniversary")),
    ("market", ("Shop", "Merchant", "Trade", "Auction", "Sale")),
    ("ranking", ("Ranking", "Leaderboard", "League")),
    ("system", ("Time", "Timer", "Notice", "Announcements", "Boost", "Settings")),
)


def classify_service(service_name: str | None, method_name: str | None = None) -> str:
    """Return a stable domain bucket for a service/method pair."""

    if not service_name:
        return "unknown"

    target = f"{service_name}.{method_name or ''}"
    for domain, needles in DOMAIN_RULES:
        if any(needle.lower() in target.lower() for needle in needles):
            return domain

    return "other"
