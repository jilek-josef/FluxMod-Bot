# FluxMod-Bot

## Local setup

1. Install dependencies:

```bash
uv sync
```

3. Configure `.env`:

```env
TOKEN=your_bot_token

MONGODB_URI=mongodb://127.0.0.1:27017/
DB_NAME=mongoDB
COLLECTION_NAME=local
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

## uv ruff & pyright

Please make sure you run these commands before pushing

```bash
# Ruff Check
uvx ruff check . --fix

# PyRight Check
uv run pyright .

```

If `TOKEN` is missing, the bot now exits with a clear startup message.