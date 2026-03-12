# FluxMod Bot Setup

## Prerequisites

- Python 3.9+
- MongoDB instance
- Discord Bot Token

## Installation

### 1. Install Dependencies

```bash
cd FluxMod-Bot
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file:

```env
TOKEN=your_discord_bot_token
MONGO_URI=your_mongodb_uri
# Optional: LHS_SERVER_URL=http://127.0.0.1:8000
```

### 3. LHS Model (AI Moderation)

The LHS model is downloaded **automatically** on first bot startup (~109MB).

**Manual download** if needed:
```bash
cd FluxMod-Bot/LHS
curl -L -o model.safetensors "https://modelscope.ai/models/LRimuru/LHS/resolve/master/model.safetensors"
```

The model file is excluded from git (in `.gitignore`).

### 4. Run the Bot

```bash
python bot.py
```

The bot will:
1. Download the LHS model if not present
2. Start the LHS inference server
3. Connect to Discord

## LHS Configuration

Environment variables for LHS (all optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `LHS_HOST` | 127.0.0.1 | Server bind address |
| `LHS_PORT` | 8000 | Server port |
| `LHS_DEVICE` | cpu | Device (cpu/cuda) |
| `LHS_MAX_BATCH_SIZE` | 32 | Max batch size |

## Troubleshooting

### Model Download Fails

- Check internet connection
- Download manually from: https://modelscope.ai/models/LRimuru/LHS
- Place in `FluxMod-Bot/LHS/model.safetensors`

### LHS Server Won't Start

- Check port 8000 is not in use
- Try different port: `LHS_PORT=8001 python bot.py`
- Check model file exists and is ~109MB
