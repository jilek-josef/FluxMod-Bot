import json
import os

import aiofiles


def load_json_sync(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return {}
    return {}


async def save_json(path: str, data: dict):
    async with aiofiles.open(path, "w", encoding="utf-8") as file:
        await file.write(json.dumps(data, indent=4))
