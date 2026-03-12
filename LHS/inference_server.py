"""
Multi-Task Inference Server v4
==============================
High-performance inference server with dynamic batching.

Features:
- Concurrent request handling via async queue
- Dynamic batching (automatically batches requests from queue)
- Configurable batch size and timeout
- FastAPI for HTTP API
"""

import torch
import torch.nn as nn
import numpy as np
import asyncio
import time
import os
import sys
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import logging
from contextlib import asynccontextmanager

# FastAPI imports
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# Model architecture from inference.py
from performer_pytorch import Performer

# SafeTensors support
try:
    from safetensors.torch import load_file as load_safetensors
    SAFETENSORS_AVAILABLE = True
except ImportError:
    SAFETENSORS_AVAILABLE = False
    load_safetensors = None


# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class PredictRequest(BaseModel):
    text: str
    threshold: float = 0.5


class PredictResponse(BaseModel):
    predictions: Dict[str, Dict[str, Any]]
    detected_categories: List[str]
    is_harmful: bool
    inference_time_ms: float


class BatchPredictRequest(BaseModel):
    texts: List[str]
    threshold: float = 0.5


class BatchPredictResponse(BaseModel):
    results: List[Dict[str, Any]]
    batch_size: int
    inference_time_ms: float


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    queue_size: int
    total_requests: int
    device: str


@dataclass
class InferenceRequest:
    """Internal inference request with future for async result."""
    text: str
    threshold: float
    future: asyncio.Future
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Byte Tokenizer
# ============================================================================

class ByteTokenizer:
    """UTF-8 byte encoding with special padding token."""
    
    def __init__(self, max_length=512):
        self.max_length = max_length
        self.vocab_size = 257
        self.pad_id = 256
    
    def encode(self, text):
        if isinstance(text, str):
            bytes_list = list(text.encode('utf-8', errors='ignore'))
        else:
            bytes_list = list(text)
        
        bytes_list = [b for b in bytes_list if 0 <= b <= 255]
        
        if len(bytes_list) > self.max_length:
            bytes_list = bytes_list[:self.max_length]
        
        bytes_list = bytes_list + [self.pad_id] * (self.max_length - len(bytes_list))
        return bytes_list


# ============================================================================
# Model Architecture
# ============================================================================

class Chomp1d(nn.Module):
    def __init__(self, chomp_size):
        super().__init__()
        self.chomp_size = chomp_size

    def forward(self, x):
        return x[:, :, :-self.chomp_size].contiguous()


class TemporalBlock(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, dilation, dropout=0.2):
        super().__init__()
        
        padding = (kernel_size - 1) * dilation
        
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size,
                               padding=padding, dilation=dilation)
        self.chomp1 = Chomp1d(padding)
        self.relu1 = nn.ReLU()
        self.dropout1 = nn.Dropout(dropout)
        
        self.conv2 = nn.Conv1d(out_channels, out_channels, kernel_size,
                               padding=padding, dilation=dilation)
        self.chomp2 = Chomp1d(padding)
        self.relu2 = nn.ReLU()
        self.dropout2 = nn.Dropout(dropout)
        
        self.downsample = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else None
        self.relu = nn.ReLU()
        
    def forward(self, x):
        out = self.conv1(x)
        out = self.chomp1(out)
        out = self.relu1(out)
        out = self.dropout1(out)
        
        out = self.conv2(out)
        out = self.chomp2(out)
        out = self.relu2(out)
        out = self.dropout2(out)
        
        res = x if self.downsample is None else self.downsample(x)
        return self.relu(out + res)


class TemporalConvNet(nn.Module):
    def __init__(self, num_inputs, num_channels, kernel_size=3, dropout=0.2):
        super().__init__()
        
        layers = []
        num_levels = len(num_channels)
        
        for i in range(num_levels):
            dilation = 2 ** i
            in_channels = num_inputs if i == 0 else num_channels[i-1]
            out_channels = num_channels[i]
            
            layers.append(TemporalBlock(
                in_channels, out_channels, kernel_size, dilation, dropout
            ))
        
        self.network = nn.Sequential(*layers)
    
    def forward(self, x):
        return self.network(x)


class MultiTaskTCNPerformer(nn.Module):
    """TCN + Performer (FAVOR+) hybrid for toxicity/spam detection."""
    
    def __init__(self, vocab_size=257, embed_dim=128, 
                 tcn_channels=[256, 384, 512],
                 performer_dim=512, performer_depth=4, performer_heads=8,
                 performer_dim_head=64, dropout=0.25):
        super().__init__()
        
        self.embed_dim = embed_dim
        self.performer_dim = performer_dim
        
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=256)
        
        self.tcn = TemporalConvNet(
            num_inputs=embed_dim,
            num_channels=tcn_channels,
            kernel_size=3,
            dropout=dropout
        )
        
        self.tcn_to_performer = nn.Linear(tcn_channels[-1], performer_dim)
        
        self.performer = Performer(
            dim=performer_dim,
            depth=performer_depth,
            heads=performer_heads,
            dim_head=performer_dim_head,
            causal=False,
            ff_dropout=dropout,
        )
        
        self.dropout = nn.Dropout(dropout)
        
        self.head = nn.Sequential(
            nn.Linear(performer_dim, 256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, 11)
        )
        
    def forward(self, input_ids, lengths=None):
        x = self.embedding(input_ids)
        B, T, _ = x.shape
        
        x = x.transpose(1, 2)
        x = self.tcn(x)
        x = x.transpose(1, 2)
        
        x = self.tcn_to_performer(x)
        x = self.performer(x)
        
        if lengths is not None:
            mask = torch.arange(T, device=x.device).unsqueeze(0) < lengths.unsqueeze(1)
            mask = mask.unsqueeze(-1).float()
            x = (x * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        else:
            x = x.mean(dim=1)
        
        x = self.dropout(x)
        logits = self.head(x)
        
        return logits


# ============================================================================
# Model Wrapper
# ============================================================================

class ModelWrapper:
    """Thread-safe model wrapper for inference."""
    
    LABEL_NAMES = ['dangerous_content', 'hate_speech', 'harassment', 'sexually_explicit',
                   'toxicity', 'severe_toxicity', 'threat', 'insult', 'identity_attack',
                   'phish', 'spam']
    
    def __init__(self, model_path: str, device: str = 'cpu'):
        self.device = torch.device(device)
        self.tokenizer = ByteTokenizer(max_length=512)
        
        # Detect format and load
        if os.path.isdir(model_path):
            # Directory mode - look for safetensors
            self.model, config = self._load_from_directory(model_path)
        elif model_path.endswith('.safetensors'):
            # Direct safetensors file
            self.model, config = self._load_safetensors(model_path)
        elif model_path.endswith('.pt') or model_path.endswith('.pth'):
            # PyTorch checkpoint - check if safetensors version exists
            st_path = model_path.replace('.pt', '.safetensors').replace('.pth', '.safetensors')
            if SAFETENSORS_AVAILABLE and os.path.exists(st_path):
                logger.info(f"Found SafeTensors version at {st_path}")
                self.model, config = self._load_safetensors(st_path)
            else:
                self.model, config = self._load_pytorch(model_path)
        else:
            raise ValueError(f"Unknown model format: {model_path}")
        
        self.model.eval()
        self.model.to(self.device)
    
    def _load_safetensors(self, path: str) -> tuple:
        """Load model from SafeTensors format."""
        if not SAFETENSORS_AVAILABLE:
            raise ImportError("safetensors not installed. Run: pip install safetensors")
        
        logger.info(f"Loading SafeTensors model from {path}...")
        
        # Load config from adjacent config.json
        config_path = os.path.join(os.path.dirname(path), "config.json")
        if not os.path.exists(config_path):
            # Try with same basename
            config_path = path.replace('.safetensors', '_config.json')
        
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = json.load(f)
        else:
            raise FileNotFoundError(f"Config not found for {path}")
        
        # Load weights
        state_dict = load_safetensors(path)
        model = MultiTaskTCNPerformer(**config)
        model.load_state_dict(state_dict)
        
        model_size = os.path.getsize(path) / (1024 * 1024)
        logger.info(f"SafeTensors model loaded: {model_size:.1f} MB")
        
        return model, config
    
    def _load_pytorch(self, path: str) -> tuple:
        """Load model from PyTorch checkpoint."""
        logger.info(f"Loading PyTorch checkpoint from {path}...")
        
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        config = checkpoint['config']
        
        model = MultiTaskTCNPerformer(**config)
        model.load_state_dict(checkpoint['model_state_dict'])
        
        model_size = os.path.getsize(path) / (1024 * 1024)
        logger.info(f"PyTorch model loaded: {model_size:.1f} MB")
        
        return model, config
    
    def _load_from_directory(self, path: str) -> tuple:
        """Load model from a directory containing model files."""
        # Try safetensors first
        st_path = os.path.join(path, "model.safetensors")
        if SAFETENSORS_AVAILABLE and os.path.exists(st_path):
            return self._load_safetensors(st_path)
        
        # Fall back to pytorch
        pt_path = os.path.join(path, "best_model.pt")
        if os.path.exists(pt_path):
            return self._load_pytorch(pt_path)
        
        raise FileNotFoundError(f"No model found in directory: {path}")
    
    def predict_batch(self, texts: List[str], threshold: float = 0.5) -> List[Dict]:
        """Run batch inference."""
        if not texts:
            return []
        
        # Tokenize
        input_ids = []
        lengths = []
        
        for text in texts:
            ids = self.tokenizer.encode(text)
            length = len(text.encode('utf-8', errors='ignore'))
            input_ids.append(ids)
            lengths.append(min(length, 512))
        
        input_tensor = torch.tensor(input_ids, dtype=torch.long).to(self.device)
        length_tensor = torch.tensor(lengths, dtype=torch.long).to(self.device)
        
        # Inference
        with torch.no_grad():
            logits = self.model(input_tensor, length_tensor)
            probs = torch.sigmoid(logits).cpu().numpy()
        
        # Format results
        results = []
        for i in range(len(texts)):
            predictions = {}
            detected = []
            
            for j, name in enumerate(self.LABEL_NAMES):
                is_detected = probs[i, j] >= threshold
                predictions[name] = {
                    'detected': bool(is_detected),
                    'confidence': float(probs[i, j])
                }
                if is_detected:
                    detected.append(name)
            
            results.append({
                'predictions': predictions,
                'detected_categories': detected,
                'is_harmful': any(predictions[name]['detected'] for name in self.LABEL_NAMES)
            })
        
        return results


# ============================================================================
# Dynamic Batching Inference Engine
# ============================================================================

class BatchingInferenceEngine:
    """
    Inference engine with dynamic batching.
    
    - Requests are queued
    - Batcher immediately takes available requests (no waiting)
    - Opportunistically collects more if they're already waiting
    - Runs inference on batch
    - Returns results to individual requesters
    """
    
    def __init__(
        self,
        model_path: str,
        device: str = 'cpu',
        max_batch_size: int = 32,
        queue_timeout: float = 20.0
    ):
        self.model = ModelWrapper(model_path, device)
        self.max_batch_size = max_batch_size
        self.queue_timeout = queue_timeout
        
        # Queue for incoming requests
        self.request_queue: asyncio.Queue = asyncio.Queue()
        
        # Statistics
        self.stats = {
            'total_requests': 0,
            'total_batches': 0,
            'total_items_processed': 0,
            'queue_high_water_mark': 0,
        }
        
        # Thread pool for model inference (to not block event loop)
        self.executor = ThreadPoolExecutor(max_workers=1)
        
        # Batching task
        self.batch_task: Optional[asyncio.Task] = None
        self.running = False
    
    async def start(self):
        """Start the batching engine."""
        self.running = True
        self.batch_task = asyncio.create_task(self._batch_processor())
        logger.info(f"Batching engine started (max_batch={self.max_batch_size}, immediate processing)")
    
    async def stop(self):
        """Stop the batching engine."""
        self.running = False
        if self.batch_task:
            self.batch_task.cancel()
            try:
                await self.batch_task
            except asyncio.CancelledError:
                pass
        self.executor.shutdown(wait=True)
        logger.info("Batching engine stopped")
    
    async def predict(self, text: str, threshold: float = 0.5) -> Dict[str, Any]:
        """
        Queue a prediction request and wait for result.
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        
        request = InferenceRequest(
            text=text,
            threshold=threshold,
            future=future
        )
        
        self.stats['total_requests'] += 1
        await self.request_queue.put(request)
        
        # Update high water mark
        current_size = self.request_queue.qsize()
        if current_size > self.stats['queue_high_water_mark']:
            self.stats['queue_high_water_mark'] = current_size
        
        try:
            # Wait for result with timeout
            result = await asyncio.wait_for(future, timeout=self.queue_timeout)
            return result
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Inference timeout")
    
    async def predict_batch(self, texts: List[str], threshold: float = 0.5) -> List[Dict[str, Any]]:
        """
        Direct batch prediction (bypasses dynamic batching queue).
        """
        loop = asyncio.get_event_loop()
        
        # Run inference in thread pool to not block event loop
        def _infer():
            return self.model.predict_batch(texts, threshold)
        
        start = time.perf_counter()
        results = await loop.run_in_executor(self.executor, _infer)
        elapsed = (time.perf_counter() - start) * 1000
        
        # Add inference time to results
        for r in results:
            r['inference_time_ms'] = elapsed / len(texts)
        
        return results
    
    async def _batch_processor(self):
        """Main batching loop."""
        while self.running:
            try:
                batch = await self._collect_batch()
                if batch:
                    await self._process_batch(batch)
            except Exception as e:
                logger.error(f"Batch processor error: {e}")
    
    async def _collect_batch(self) -> List[InferenceRequest]:
        """
        Collect requests from queue.
        - Immediately takes first request (no waiting)
        - Opportunistically collects more if already waiting (non-blocking)
        - Returns as soon as we have at least one request
        """
        batch = []
        
        # Wait for first request (blocking with timeout to check running flag)
        try:
            request = await asyncio.wait_for(
                self.request_queue.get(),
                timeout=1.0
            )
            batch.append(request)
        except asyncio.TimeoutError:
            return batch  # Empty, will retry
        
        # Opportunistically collect more requests that are ALREADY waiting
        # Don't wait for new ones - process immediately to minimize latency
        while len(batch) < self.max_batch_size:
            try:
                # Non-blocking get - only take what's already there
                request = self.request_queue.get_nowait()
                batch.append(request)
            except asyncio.QueueEmpty:
                break  # No more waiting requests, process what we have
        
        return batch
    
    async def _process_batch(self, batch: List[InferenceRequest]):
        """Process a batch of requests."""
        if not batch:
            return
        
        start = time.perf_counter()
        
        # Extract texts and thresholds
        texts = [req.text for req in batch]
        # Use first threshold for batch (they're usually similar)
        threshold = batch[0].threshold
        
        # Run inference in thread pool
        loop = asyncio.get_event_loop()
        
        def _infer():
            return self.model.predict_batch(texts, threshold)
        
        try:
            results = await loop.run_in_executor(self.executor, _infer)
            elapsed = (time.perf_counter() - start) * 1000
            
            # Update stats
            self.stats['total_batches'] += 1
            self.stats['total_items_processed'] += len(batch)
            
            # Distribute results
            per_item_time = elapsed / len(batch)
            for req, result in zip(batch, results):
                result['inference_time_ms'] = per_item_time
                if not req.future.done():
                    req.future.set_result(result)
            
            # Log batch stats occasionally
            if self.stats['total_batches'] % 100 == 0:
                logger.info(
                    f"Batch stats: {self.stats['total_batches']} batches, "
                    f"{self.stats['total_items_processed']} items, "
                    f"queue_high={self.stats['queue_high_water_mark']}"
                )
                
        except Exception as e:
            logger.error(f"Batch inference error: {e}")
            # Fail all requests in batch
            for req in batch:
                if not req.future.done():
                    req.future.set_exception(e)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return {
            **self.stats,
            'current_queue_size': self.request_queue.qsize(),
            'max_batch_size': self.max_batch_size,
        }


# ============================================================================
# FastAPI Application
# ============================================================================

# Global engine instance
engine: Optional[BatchingInferenceEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    global engine
    
    # Startup
    logger.info("Starting up inference server...")
    
    model_path = os.environ.get('MODEL_PATH', '.')
    device = os.environ.get('DEVICE', 'cpu')
    max_batch_size = int(os.environ.get('MAX_BATCH_SIZE', '64'))
    
    # Check if path exists (as file or directory)
    if not os.path.exists(model_path):
        logger.error(f"Model path not found at {model_path}")
        # Try relative path
        alt_path = os.path.join(os.path.dirname(__file__), '..', model_path)
        alt_path = os.path.normpath(alt_path)
        if os.path.exists(alt_path):
            model_path = alt_path
            logger.info(f"Using model at {model_path}")
        else:
            raise RuntimeError(f"Model not found at {model_path} or {alt_path}")
    
    engine = BatchingInferenceEngine(
        model_path=model_path,
        device=device,
        max_batch_size=max_batch_size
    )
    await engine.start()
    logger.info("Inference server startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down inference server...")
    if engine:
        await engine.stop()
    logger.info("Inference server shutdown complete")


app = FastAPI(
    title="Multi-Task Inference API",
    description="TCN + Performer (FAVOR+) hybrid inference with dynamic batching",
    version="4.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    global engine
    
    stats = engine.get_stats() if engine else {}
    
    return HealthResponse(
        status="healthy" if engine else "initializing",
        model_loaded=engine is not None,
        queue_size=stats.get('current_queue_size', 0),
        total_requests=stats.get('total_requests', 0),
        device=str(engine.model.device) if engine else "unknown"
    )


@app.get("/stats")
async def get_stats():
    """Get detailed statistics."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    return engine.get_stats()


@app.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """
    Predict toxicity/spam for a single text.
    Uses dynamic batching queue.
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    start = time.perf_counter()
    result = await engine.predict(request.text, request.threshold)
    total_elapsed = (time.perf_counter() - start) * 1000
    
    return PredictResponse(
        predictions=result['predictions'],
        detected_categories=result['detected_categories'],
        is_harmful=result['is_harmful'],
        inference_time_ms=total_elapsed
    )


@app.post("/predict_batch", response_model=BatchPredictResponse)
async def predict_batch(request: BatchPredictRequest):
    """
    Batch prediction endpoint.
    Bypasses dynamic batching for direct batch processing.
    """
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    if len(request.texts) > engine.max_batch_size * 2:
        raise HTTPException(
            status_code=400, 
            detail=f"Batch too large. Max: {engine.max_batch_size * 2}"
        )
    
    start = time.perf_counter()
    results = await engine.predict_batch(request.texts, request.threshold)
    total_elapsed = (time.perf_counter() - start) * 1000
    
    return BatchPredictResponse(
        results=results,
        batch_size=len(request.texts),
        inference_time_ms=total_elapsed
    )


# ============================================================================
# Main
# ============================================================================

def main():
    """Run the inference server."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Multi-Task Inference Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--model-path", default="multitask_v4", 
                        help="Path to model (directory, .safetensors, or .pt file)")
    parser.add_argument("--device", default="cpu", help="Device (cpu/cuda)")
    parser.add_argument("--max-batch-size", type=int, default=32, help="Max batch size")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    
    args = parser.parse_args()
    
    # Set environment variables for startup event
    os.environ['MODEL_PATH'] = args.model_path
    os.environ['DEVICE'] = args.device
    os.environ['MAX_BATCH_SIZE'] = str(args.max_batch_size)
    
    print("="*60)
    print("MULTI-TASK INFERENCE SERVER v4")
    print("="*60)
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Model: {args.model_path}")
    print(f"Device: {args.device}")
    print(f"Max Batch Size: {args.max_batch_size}")
    print(f"Workers: {args.workers}")
    print("="*60)
    
    uvicorn.run(
        "inference_server:app",
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level="info"
    )


if __name__ == "__main__":
    main()
