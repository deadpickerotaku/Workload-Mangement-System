"""User accounts and service tiers — the basis for multi-tenant fair scheduling.

Each request belongs to a user, and each user has a tier. The tier determines a
scheduling *weight*: PREMIUM users get a larger share of the scarce external-API
budget than FREE users. This is what turns the scheduler from an academic demo
into real business logic (paid vs free service levels).
"""
from __future__ import annotations

import threading
import time


class Tier:
    FREE = "FREE"
    PREMIUM = "PREMIUM"
    ALL = (FREE, PREMIUM)


# Scheduling weight per tier. A PREMIUM user's virtual time advances 3x slower,
# so under Weighted Fair Queuing they receive ~3x the service of a FREE user.
TIER_WEIGHT = {
    Tier.FREE: 1.0,
    Tier.PREMIUM: 3.0,
}


def weight_for_tier(tier: str) -> float:
    return TIER_WEIGHT.get(tier, 1.0)


class Users:
    """Small registry backed by the USER table, cached in memory."""

    def __init__(self, database):
        self.db = database
        self._by_id: dict[int, dict] = {}
        self._by_name: dict[str, dict] = {}
        self._lock = threading.Lock()
        for u in self.db.list_users():
            self._cache(u)

    def _cache(self, u: dict) -> None:
        self._by_id[u["user_id"]] = u
        self._by_name[u["name"]] = u

    def get_or_create(self, name: str, tier: str = Tier.FREE) -> dict:
        name = (name or "guest").strip() or "guest"
        if tier not in Tier.ALL:
            tier = Tier.FREE
        with self._lock:
            existing = self._by_name.get(name)
            if existing:
                # Allow upgrading/downgrading a user's tier on re-submit.
                if existing["tier"] != tier:
                    self.db.update_user_tier(existing["user_id"], tier)
                    existing["tier"] = tier
                return existing
            user_id = self.db.insert_user(name, tier, time.time() * 1000.0)
            u = {"user_id": user_id, "name": name, "tier": tier}
            self._cache(u)
            return u

    def tier_of(self, user_id: int) -> str:
        u = self._by_id.get(user_id)
        return u["tier"] if u else Tier.FREE

    def weight_of(self, user_id: int) -> float:
        return weight_for_tier(self.tier_of(user_id))
