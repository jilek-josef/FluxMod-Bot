from database.mongo import MongoDB

db = MongoDB()
guilds = db.collection("guild_settings")
bot_stats = db.collection("bot_stats")


def create_guild(guild_id: int):

    if guilds.find_one({"guild_id": guild_id}):
        return

    guilds.insert_one({
        "guild_id": guild_id,
        "automod_rules": [],
        "command_settings": {},
        "warns": []
    })


def update_bot_guild_count(count: int) -> None:
    """Persist current guild count for dashboard usage."""
    bot_stats.update_one(
        {"_id": "global"},
        {"$set": {"guild_count": max(int(count), 0)}},
        upsert=True,
    )


def get_guild(guild_id: int):
    return guilds.find_one({"guild_id": guild_id})


def get_command_settings(guild_id: int) -> dict:

    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"command_settings": 1, "_id": 0}
    )

    if not guild:
        return {}

    return guild.get("command_settings", {})


def update_command_settings(guild_id: int, settings: dict):

    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {"command_settings": settings},
            "$setOnInsert": {
                "guild_id": guild_id,
                "automod_rules": [],
                "warns": [],
            },
        },
        upsert=True,
    )


def set_log_channel_id(guild_id: int, channel_id: int):

    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {"command_settings.log_channel_id": channel_id},
            "$setOnInsert": {
                "guild_id": guild_id,
                "automod_rules": [],
                "warns": [],
            },
        },
        upsert=True
    )


def get_log_channel_id(guild_id: int) -> int | None:

    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"command_settings.log_channel_id": 1, "_id": 0}
    )

    if not guild:
        return None

    command_settings = guild.get("command_settings", {})
    channel_id = command_settings.get("log_channel_id")

    return channel_id if isinstance(channel_id, int) else None