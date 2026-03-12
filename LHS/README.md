# LHS (Language Harm Scanner) Model

This directory contains the LHS AI model for content moderation.

## Model File

The model file (`model.safetensors`) is **not included** in the git repository due to its large size (~109MB).

### Automatic Download (Recommended)

The bot will automatically download the model on first startup if it's not present.

**Source:** [ModelScope - LRimuru/LHS](https://modelscope.ai/models/LRimuru/LHS)

### Manual Download

If automatic download fails, you can download manually:

```bash
# Download using curl
curl -L -o model.safetensors "https://modelscope.ai/models/LRimuru/LHS/resolve/master/model.safetensors"

# Or download using wget
wget -O model.safetensors "https://modelscope.ai/models/LRimuru/LHS/resolve/master/model.safetensors"
```

Then place the file in this directory (`FluxMod-Bot/LHS/`).

### Verify Download

Expected file size: ~109 MB (114,116,700 bytes)

```bash
ls -lh model.safetensors
```

## Model Information

- **Architecture:** TCN + Performer (FAVOR+) Hybrid
- **Version:** 4.0.0
- **Categories:** 11 detection categories
  - Dangerous Content
  - Hate Speech
  - Harassment
  - Sexually Explicit
  - Toxicity
  - Severe Toxicity
  - Threat
  - Insult
  - Identity Attack
  - Phishing
  - Spam

## Git

Model files are excluded from git via `.gitignore`:
```
*.safetensors
*.pt
*.pth
*.bin
*.ckpt
```
