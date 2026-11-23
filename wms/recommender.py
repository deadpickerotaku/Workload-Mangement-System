"""AI-based automatic playlist recommender.

Builds a lightweight *taste profile* from the signed-in user's own history — the
moods they've requested and the audio attributes (tempo / valence / energy) and
artists of the tracks in playlists they've already generated — then uses the
same Gemini + Spotify providers as the main engine to synthesize fresh playlist
suggestions.

Each suggestion carries a title, a short human explanation of *why* it was
recommended, a preview of selected tracks, and its target attributes. Nothing is
ever written to Spotify here; a recommendation only becomes a saved playlist
when the user explicitly accepts it (see `Database.accept_recommendation`).

A suggestion the user has rejected (tracked by its stable `signature`) is never
regenerated, so refreshing keeps surfacing genuinely new ideas.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import List

import config
from .providers import gemini, spotify

# Curated mood seeds the recommender can draw on when it needs fresh ideas.
# (label, title suffix, request text handed to the Gemini provider)
_MOOD_SEEDS = [
    ("study",    "Deep Focus",      "a focused study playlist"),
    ("workout",  "Workout Fuel",    "a high energy workout mix"),
    ("party",    "Party Starter",   "upbeat party dance hits"),
    ("relax",    "Wind Down",       "relaxing chill acoustic songs"),
    ("happy",    "Good Mood",       "feel-good happy pop"),
    ("romantic", "Late Night Love", "romantic r&b and soul"),
    ("drive",    "Night Drive",     "a late-night driving playlist"),
    ("coding",   "In The Zone",     "lo-fi beats for coding"),
    ("sleep",    "Drift Off",       "calm ambient sleep sounds"),
    ("sad",      "In My Feelings",  "melancholy indie songs"),
]


# ---- taste profile ---------------------------------------------------------
def build_profile(db, user_id: int) -> dict:
    """Summarize what we know about a user's taste from their own history."""
    tracks = db.taste_tracks(user_id)
    requests = db.recent_requests(user_id)
    profile = {
        "has_history": bool(tracks or requests),
        "requests": requests,
        "tempo": None, "valence": None, "energy": None,
        "top_artists": [],
    }
    if tracks:
        def _avg(key):
            vals = [t[key] for t in tracks if t.get(key) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None
        profile["tempo"] = _avg("tempo")
        profile["valence"] = _avg("valence")
        profile["energy"] = _avg("energy")
        artists = Counter(t["artist"] for t in tracks if t.get("artist"))
        profile["top_artists"] = [a for a, _ in artists.most_common(3)]
    return profile


# ---- generation ------------------------------------------------------------
def _candidate_seeds(profile: dict) -> List[dict]:
    """Ordered seeds to try: the user's own recent moods first, then a shuffled
    set of curated moods (shuffled so each refresh explores new territory)."""
    seeds: List[dict] = []
    seen = set()
    for req in profile.get("requests", []):
        key = f"hist:{(req or '').strip().lower()[:60]}"
        if not req or key in seen:
            continue
        seen.add(key)
        label = req.strip()[:28]
        seeds.append({"key": key, "title": f"More like “{label}”",
                      "text": req, "from_history": True})

    moods = list(_MOOD_SEEDS)
    random.shuffle(moods)
    for label, title, text in moods:
        key = f"mood:{label}"
        if key in seen:
            continue
        seen.add(key)
        seeds.append({"key": key, "title": title, "text": text,
                      "from_history": False})
    return seeds


def _blend(attrs: dict, profile: dict) -> dict:
    """Nudge the mood's attributes toward the user's measured averages, so a
    recommendation reflects their actual tempo / energy / valence leanings."""
    if not profile.get("has_history"):
        return attrs
    out = dict(attrs)
    for key, ndigits in (("tempo", 1), ("valence", 2), ("energy", 2)):
        mine = profile.get(key)
        base = attrs.get(key)
        if mine is not None and base is not None:
            out[key] = round((base + mine) / 2, ndigits)
    return out


def _title(seed: dict, attrs: dict) -> str:
    if seed.get("from_history"):
        return seed["title"]
    genres = attrs.get("genres") or []
    genre = genres[0].title() if genres else "Mixed"
    return f"{seed['title']}: {genre} Mix"


def _reason(seed: dict, attrs: dict, profile: dict) -> str:
    bits: List[str] = []
    if seed.get("from_history"):
        bits.append(f"You've asked for playlists like “{seed['text']}” before.")
    if profile.get("has_history"):
        energy = profile.get("energy")
        if energy is not None:
            vibe = ("high-energy" if energy >= 0.6
                    else "mellow" if energy <= 0.4 else "balanced")
            bits.append(f"Your library leans {vibe} (avg energy {energy:.0%}).")
        if profile.get("top_artists"):
            names = ", ".join(profile["top_artists"][:2])
            bits.append(f"Chosen to sit alongside artists you play like {names}.")
    else:
        bits.append("A starter mix while we learn your taste.")
    genres = attrs.get("genres") or []
    if genres:
        bits.append(f"Leans into {', '.join(genres[:2])} "
                    f"at ~{int(attrs.get('tempo', 110))} BPM.")
    return " ".join(bits)


def generate(db, user: dict, count: int | None = None) -> List[int]:
    """Create up to `count` new PENDING recommendations for the user. Returns
    the new rec_ids (may be fewer than requested if ideas run out)."""
    if count is None:
        count = config.RECOMMENDATION_COUNT
    user_id = user["user_id"]
    profile = build_profile(db, user_id)
    taken = db.recommendation_signatures(user_id)

    created: List[int] = []
    for seed in _candidate_seeds(profile):
        if len(created) >= count:
            break
        if seed["key"] in taken:          # already pending or previously rejected
            continue
        attrs = _blend(gemini.analyze(seed["text"]), profile)
        tracks = spotify.search(attrs, n=config.RECOMMENDATION_PREVIEW)
        rec_id = db.insert_recommendation(
            user_id, _title(seed, attrs), _reason(seed, attrs, profile),
            seed["key"], seed["text"], attrs, tracks)
        created.append(rec_id)
        taken.add(seed["key"])
    return created


def ensure(db, user: dict, target: int | None = None) -> List[dict]:
    """Top the user's PENDING recommendations up to `target`, then return them.
    Called whenever the dashboard loads, so suggestions appear automatically."""
    if target is None:
        target = config.RECOMMENDATION_COUNT
    have = db.count_recommendations(user["user_id"], "PENDING")
    if have < target:
        generate(db, user, target - have)
    return db.list_recommendations(user["user_id"], "PENDING")
