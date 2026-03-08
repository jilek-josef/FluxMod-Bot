from datetime import datetime, timezone
from collections import defaultdict
from uuid import uuid4

from database.mongo import MongoDB
from database.guilds import create_guild

db = MongoDB()
guilds = db.collection("guild_settings")


def _as_utc(dt: object) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)



def add_warn(guild_id: int, user_id: int, moderator_id: int, reason: str):

    create_guild(guild_id)

    warn = {
        "warn_id": str(uuid4()),
        "user_id": user_id,
        "moderator_id": moderator_id,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc)
    }

    guilds.update_one(
        {"guild_id": guild_id},
        {"$push": {"warns": warn}}
    )


def get_user_warns(guild_id: int, user_id: int):

    create_guild(guild_id)

    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"warns": 1, "_id": 0}
    )

    if not guild:
        return []

    warns = guild.get("warns", [])
    user_warns = [warn for warn in warns if warn.get("user_id") == user_id]

    min_utc = datetime.min.replace(tzinfo=timezone.utc)
    user_warns.sort(
        key=lambda warn: _as_utc(warn.get("timestamp")) or min_utc
    )

    return user_warns


def remove_warn(guild_id: int, user_id: int, warn_id):

    create_guild(guild_id)
    
    guilds.update_one(
        {"guild_id": guild_id},
        {"$pull": {"warns": {"user_id": user_id, "warn_id": str(warn_id)}}}
    )


def clear_user_warns(guild_id: int, user_id: int):

    create_guild(guild_id)

    guilds.update_one(
        {"guild_id": guild_id},
        {"$pull": {"warns": {"user_id": user_id}}}
    )


def remove_warn_by_index(guild_id: int, user_id: int, index: int) -> bool:

    user_warns = get_user_warns(guild_id, user_id)

    if not (0 <= index < len(user_warns)):
        return False

    warn_id = user_warns[index].get("warn_id")

    if warn_id is None:
        return False

    result = guilds.update_one(
        {"guild_id": guild_id},
        {"$pull": {"warns": {"user_id": user_id, "warn_id": warn_id}}}
    )

    return result.modified_count > 0


def get_warns_grouped_by_guild_user() -> dict[int, dict[int, list[dict]]]:

    grouped: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))

    cursor = guilds.find({}, {"guild_id": 1, "warns": 1, "_id": 0})

    for guild in cursor:
        guild_id = guild.get("guild_id")

        if not isinstance(guild_id, int):
            continue

        warns = guild.get("warns", [])
        for warn in warns:
            user_id = warn.get("user_id")
            if not isinstance(user_id, int):
                continue
            grouped[guild_id][user_id].append(warn)

    return {gid: dict(users) for gid, users in grouped.items()}


def delete_warns_older_than(cutoff: datetime) -> int:

    cutoff_utc = _as_utc(cutoff)
    if cutoff_utc is None:
        return 0

    removed = 0

    cursor = guilds.find({}, {"guild_id": 1, "warns": 1, "_id": 0})
    for guild in cursor:
        guild_id = guild.get("guild_id")
        warns = guild.get("warns", [])

        if not isinstance(guild_id, int) or not isinstance(warns, list):
            continue

        kept_warns = [
            warn for warn in warns
            if not (
                (ts := _as_utc(warn.get("timestamp"))) is not None
                and ts < cutoff_utc
            )
        ]

        removed += len(warns) - len(kept_warns)

        if len(kept_warns) != len(warns):
            guilds.update_one(
                {"guild_id": guild_id},
                {"$set": {"warns": kept_warns}}
            )

    return removed