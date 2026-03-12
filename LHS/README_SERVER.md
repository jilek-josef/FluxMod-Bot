# Multi-Task Inference Server v4

High-performance inference server with dynamic batching for the TCN + Performer (FAVOR+) hybrid model.

## Features

- **Dynamic Batching**: Requests are automatically batched together for efficient inference
- **Concurrent Request Handling**: Async queue handles multiple concurrent requests
- **FastAPI**: Modern, fast web framework for the API
- **Configurable**: Batch size, timeout, and device settings
- **Gradio UI**: Separate web interface for manual testing

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌─────────┐
│   Client    │────▶│  Request     │────▶│   Dynamic   │────▶│  Model  │
│   Requests  │     │    Queue     │     │   Batcher   │     │  (GPU)  │
└─────────────┘     └──────────────┘     └─────────────┘     └─────────┘
       │                                           │
       │                                           │
       └───────────────────────────────────────────┘
                        (Results returned)
```

### Dynamic Batching Flow

1. Client sends prediction request
2. Request is queued with a Future (20s timeout)
3. Batcher immediately takes first request
4. Opportunistically collects any additional requests already waiting (non-blocking)
5. Batch inference runs immediately (no artificial delay)
6. Results returned to individual clients

**Key difference**: We process immediately when a request arrives, we don't wait to fill the batch. We just opportunistically batch what's already there.

## Installation

```bash
# Install dependencies
pip install -r multitask_v4/requirements_server.txt
```

## Convert Model to SafeTensors (Recommended)

SafeTensors is a safer and faster format than PyTorch pickle files:

```bash
# Convert best_model.pt to SafeTensors format
python -m multitask_v4.convert_to_safetensors

# This creates:
#   - multitask_v4/model.safetensors (weights)
#   - multitask_v4/config.json (model config)
#   - multitask_v4/metadata.json (training metadata)
```

## Usage

### Quick Start (Server + UI)

```bash
# Convert model to SafeTensors (first time only)
python -m multitask_v4.convert_to_safetensors

# Start both server and UI
python -m multitask_v4.launch

# Start with custom ports
python -m multitask_v4.launch --server-port 8080 --ui-port 8081
```

### Start Server Only

```bash
# Basic usage
python -m inference_server

# With options
python -m inference_server \
    --host 0.0.0.0 \
    --port 8000 \
    --model-path multitask_v4/best_model.pt \
    --device cpu \
    --max-batch-size 32 \
    --max-wait-ms 50
```

### Start UI Only

```bash
# Connect to local server
python -m multitask_v4.gradio_ui

# Connect to remote server
python -m multitask_v4.gradio_ui --server-url http://remote-server:8000
```

### Test Client

```bash
# Basic test
python -m multitask_v4.test_client

# Test with concurrent requests
python -m multitask_v4.test_client --concurrent 100

# Test remote server
python -m multitask_v4.test_client --url http://remote-server:8000
```

## API Endpoints

### Health Check
```bash
GET /
```

Response:
```json
{
  "status": "healthy",
  "model_loaded": true,
  "queue_size": 0,
  "total_requests": 42,
  "device": "cpu"
}
```

### Single Prediction (with dynamic batching)
```bash
POST /predict
Content-Type: application/json

{
  "text": "Your text here",
  "threshold": 0.5
}
```

Response:
```json
{
  "predictions": {
    "toxicity": {"detected": true, "confidence": 0.95},
    ...
  },
  "detected_categories": ["toxicity"],
  "is_harmful": true,
  "inference_time_ms": 12.5
}
```

### Batch Prediction (direct, bypasses queue)
```bash
POST /predict_batch
Content-Type: application/json

{
  "texts": ["Text 1", "Text 2", "Text 3"],
  "threshold": 0.5
}
```

Response:
```json
{
  "results": [
    {
      "predictions": {...},
      "detected_categories": [...],
      "is_harmful": true
    }
  ],
  "batch_size": 3,
  "inference_time_ms": 25.0
}
```

### Statistics
```bash
GET /stats
```

Response:
```json
{
  "total_requests": 1000,
  "total_batches": 50,
  "total_items_processed": 1000,
  "current_queue_size": 0,
  "max_batch_size": 32,
  "max_wait_ms": 50
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PATH` | `multitask_v4/best_model.pt` | Path to model file |
| `DEVICE` | `cpu` | Device (`cpu` or `cuda`) |
| `MAX_BATCH_SIZE` | `32` | Maximum batch size |

### Command Line Options

**Server:**
- `--host`: Bind host (default: 0.0.0.0)
- `--port`: Bind port (default: 8000)
- `--model-path`: Path to model file
- `--device`: Device (cpu/cuda)
- `--max-batch-size`: Max batch size
- `--workers`: Number of worker processes

**UI:**
- `--host`: Bind host (default: 0.0.0.0)
- `--port`: Bind port (default: 7860)
- `--server-url`: Inference server URL
- `--share`: Create public share link

## Performance Tuning

### Dynamic Batching

The batching strategy is designed for **low latency**:
- Single requests are processed immediately (no waiting)
- Additional requests are added opportunistically if already waiting
- Queue timeout is 20s for individual requests

Tuning:
- **max_batch_size**: Controls max batch size. Under high load, bigger batches = better throughput. Under low load, doesn't affect latency.

Recommended settings:
- **Low latency priority**: `max_batch_size=16`
- **Balanced**: `max_batch_size=32` (default)
- **High throughput**: `max_batch_size=64`

### GPU Usage

```bash
# Use GPU
python -m inference_server --device cuda

# Verify GPU is being used
curl http://localhost:8000/
```

## Example Usage with Python

```python
import requests

# Single prediction
response = requests.post("http://localhost:8000/predict", json={
    "text": "You are an idiot!",
    "threshold": 0.5
})
result = response.json()
print(f"Harmful: {result['is_harmful']}")
print(f"Detected: {result['detected_categories']}")

# Batch prediction
response = requests.post("http://localhost:8000/predict_batch", json={
    "texts": ["Text 1", "Text 2", "Text 3"],
    "threshold": 0.5
})
results = response.json()['results']
```

## File Structure

```
multitask_v4/
├── inference_server.py      # FastAPI server with dynamic batching
├── gradio_ui.py             # Gradio web interface
├── convert_to_safetensors.py # Model conversion utility
├── test_client.py           # Test client script
├── launch.py                # Launcher for server + UI
├── requirements_server.txt  # Server dependencies
├── README_SERVER.md         # This file
├── model.safetensors        # Model weights (created by conversion)
├── config.json              # Model config (created by conversion)
└── metadata.json            # Training metadata (created by conversion)
```
