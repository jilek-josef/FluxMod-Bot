# FluxMod-Bot

## Local setup

1. Install dependencies:

```bash
uv sync
```

3. Configure `.env`:

```env
TOKEN=your_bot_token

# Option A: Full URI (recommended)
MONGODB_URI=mongodb://127.0.0.1:27017/

# Option B: Piece-by-piece values
DB_IP=127.0.0.1
DB_PORT=27017
DB_NAME=fluxmod
DB_USER=
DB_PASSWORD=
DB_AUTH_SOURCE=admin
```

4. Start the bot:

```bash
uv run python bot.py
```

## UV workflow

Use these as the canonical project commands:

```bash
# Update lockfile after dependency changes
uv lock

# Sync environment from pyproject.toml + uv.lock
uv sync

# Run the bot with the project environment
uv run python bot.py
```

If `TOKEN` is missing, the bot now exits with a clear startup message.

## MongoDB utility

Use `utils/mongodb.py` when a cog/service needs MongoDB:

```python
from utils.mongodb import get_database

db = get_database(ping=True)  # uses DB_NAME from .env
users = db["users"]
```

You can also call `get_database("my_db")` to override the env name.