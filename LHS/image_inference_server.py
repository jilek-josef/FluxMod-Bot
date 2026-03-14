"""
Image/Video Content Moderation Inference Server v2

FastAPI server with dynamic batching for the CaFormer-based image moderation model.
Returns probabilities (sigmoid applied) - threshold handling is done by the caller.
"""

import os
import sys
import asyncio
import time
import io
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import torch
from PIL import Image

# Import image moderation components
from LHS.image_moderation import ImageModerationModel, get_image_model


# ============================================================================
# Data Models
# ============================================================================

class ImagePredictResponse(BaseModel):
    """Response from image moderation - returns probabilities (sigmoid applied)"""
    probabilities: List[float]  # Full probability array (12476 values, sigmoid applied)
    inference_time_ms: float


class BatchImageRequest(BaseModel):
    """Request for batch image processing"""
    # For batch endpoint via JSON (base64 encoded images)
    images_base64: Optional[List[str]] = None


class BatchImageResponse(BaseModel):
    """Response for batch image processing"""
    results: List[Dict[str, Any]]
    batch_size: int
    total_inference_time_ms: float


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    model_loaded: bool
    queue_size: int
    total_requests: int
    device: str


@dataclass
class InferenceRequest:
    """Internal inference request with future for async result."""
    image_data: bytes
    future: asyncio.Future
    timestamp: float = field(default_factory=time.time)


# ============================================================================
# Dynamic Batching Inference Engine
# ============================================================================

class ImageBatchingInferenceEngine:
    """
    Inference engine with dynamic batching for image moderation.
    
    - Requests are queued
    - Batcher collects available requests
    - Runs inference on batch
    - Returns probabilities (sigmoid applied) to individual requesters
    """
    
    def __init__(
        self,
        model: ImageModerationModel,
        max_batch_size: int = 4,  # Images are larger, so smaller batches
        queue_timeout: float = 30.0
    ):
        self.model = model
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
        print(f"[Image Engine] Batching engine started (max_batch={self.max_batch_size})", flush=True)
    
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
        print("[Image Engine] Batching engine stopped", flush=True)
    
    async def predict(self, image_data: bytes) -> Dict[str, Any]:
        """
        Queue a prediction request and wait for probabilities result.
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        
        request = InferenceRequest(
            image_data=image_data,
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
    
    async def predict_single(self, image_data: bytes) -> Dict[str, Any]:
        """
        Direct single image prediction (bypasses queue for simple use cases).
        """
        if not self.model._model_loaded:
            raise RuntimeError("Model not loaded")
        
        loop = asyncio.get_event_loop()
        
        def _infer():
            import time
            start = time.time()
            
            # Load and preprocess image
            image = Image.open(io.BytesIO(image_data)).convert("RGB")
            tensor = self.model._preprocess_image(image)
            
            # Run inference
            with torch.no_grad():
                self.model.model.eval()
                logits = self.model.model(tensor)
                probabilities = torch.sigmoid(logits)
            
            # Debug logging
            logits_np = logits[0].cpu().numpy()
            probs_np = probabilities[0].cpu().numpy()
            is_training = self.model.model.training
            print(f"[Image Engine DEBUG] Model training mode: {is_training}", flush=True)
            print(f"[Image Engine DEBUG] Raw logits - first4: {logits_np[:4]}, idx299: {logits_np[299]:.4f}, idx1558: {logits_np[1558]:.4f}, idx3664: {logits_np[3664]:.4f}", flush=True)
            print(f"[Image Engine DEBUG] After sigmoid - first4: {probs_np[:4]}, idx299: {probs_np[299]:.4f}, idx1558: {probs_np[1558]:.4f}, idx3664: {probs_np[3664]:.4f}", flush=True)
            
            elapsed = (time.time() - start) * 1000
            
            # Return probabilities (sigmoid applied), not raw logits
            return {
                'probabilities': probabilities[0].cpu().tolist(),
                'inference_time_ms': elapsed
            }
        
        return await loop.run_in_executor(self.executor, _infer)
    
    async def _batch_processor(self):
        """Main batching loop."""
        while self.running:
            try:
                batch = await self._collect_batch()
                if batch:
                    await self._process_batch(batch)
            except Exception as e:
                print(f"[Image Engine] Batch processor error: {e}", flush=True)
    
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
        while len(batch) < self.max_batch_size:
            try:
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
        
        # Run inference in thread pool
        loop = asyncio.get_event_loop()
        
        def _infer_batch():
            import time
            results = []
            
            for req in batch:
                try:
                    req_start = time.time()
                    
                    # Load and preprocess image
                    image = Image.open(io.BytesIO(req.image_data)).convert("RGB")
                    tensor = self.model._preprocess_image(image)
                    
                    # Run inference
                    with torch.no_grad():
                        self.model.model.eval()
                        logits = self.model.model(tensor)
                        probabilities = torch.sigmoid(logits)
                    
                    # Debug logging for first request in batch
                    if len(results) == 0:
                        logits_np = logits[0].cpu().numpy()
                        probs_np = probabilities[0].cpu().numpy()
                        is_training = self.model.model.training
                        print(f"[Image Engine DEBUG] Model training mode: {is_training}", flush=True)
                        print(f"[Image Engine DEBUG] Raw logits - first4: {logits_np[:4]}, idx299: {logits_np[299]:.4f}, idx1558: {logits_np[1558]:.4f}, idx3664: {logits_np[3664]:.4f}", flush=True)
                        print(f"[Image Engine DEBUG] After sigmoid - first4: {probs_np[:4]}, idx299: {probs_np[299]:.4f}, idx1558: {probs_np[1558]:.4f}, idx3664: {probs_np[3664]:.4f}", flush=True)
                    
                    req_elapsed = (time.time() - req_start) * 1000
                    
                    # Return probabilities (sigmoid applied), not raw logits
                    results.append({
                        'probabilities': probabilities[0].cpu().tolist(),
                        'inference_time_ms': req_elapsed
                    })
                except Exception as e:
                    results.append({'error': str(e)})
            
            return results
        
        try:
            results = await loop.run_in_executor(self.executor, _infer_batch)
            elapsed = (time.perf_counter() - start) * 1000
            
            # Update stats
            self.stats['total_batches'] += 1
            self.stats['total_items_processed'] += len(batch)
            
            # Distribute results
            for req, result in zip(batch, results):
                if not req.future.done():
                    if 'error' in result:
                        req.future.set_exception(RuntimeError(result['error']))
                    else:
                        req.future.set_result(result)
            
            # Log batch stats occasionally
            if self.stats['total_batches'] % 100 == 0:
                print(
                    f"[Image Engine] Stats: {self.stats['total_batches']} batches, "
                    f"{self.stats['total_items_processed']} items, "
                    f"queue_high={self.stats['queue_high_water_mark']}",
                    flush=True
                )
                
        except Exception as e:
            print(f"[Image Engine] Batch inference error: {e}", flush=True)
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
engine: Optional[ImageBatchingInferenceEngine] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    global engine
    import time
    
    # Startup
    device = os.environ.get("IMAGE_MODEL_DEVICE", "cpu")
    model_path = os.environ.get("IMAGE_MODEL_PATH")
    max_batch_size = int(os.environ.get("IMAGE_MAX_BATCH_SIZE", "4"))
    
    print("=" * 60, flush=True)
    print("IMAGE MODERATION INFERENCE SERVER v2", flush=True)
    print("=" * 60, flush=True)
    print(f"Device: {device}", flush=True)
    print(f"Model Path: {model_path or 'default'}", flush=True)
    print(f"Max Batch Size: {max_batch_size}", flush=True)
    print(f"Python: {sys.executable}", flush=True)
    print(f"CWD: {os.getcwd()}", flush=True)
    print("=" * 60, flush=True)
    
    start_time = time.time()
    print(f"[Lifespan] Getting image model...", flush=True)
    model = get_image_model(device=device)
    if model_path:
        model.model_path = model_path
    print(f"[Lifespan] Got model in {time.time() - start_time:.1f}s", flush=True)
    
    print(f"[Lifespan] Loading model (this may take a while)...", flush=True)
    t0 = time.time()
    loaded = model.load_model()
    print(f"[Lifespan] Model.load_model() returned in {time.time() - t0:.1f}s", flush=True)
    
    if loaded:
        print("✓ Model loaded successfully", flush=True)
    else:
        print("✗ Model failed to load - predictions will fail", flush=True)
    
    # Create and start batching engine
    engine = ImageBatchingInferenceEngine(
        model=model,
        max_batch_size=max_batch_size
    )
    await engine.start()
    
    total_time = time.time() - start_time
    print(f"[Lifespan] Total startup time: {total_time:.1f}s", flush=True)
    print("=" * 60, flush=True)
    
    yield
    
    # Shutdown
    print("Shutting down image moderation server...", flush=True)
    if engine:
        await engine.stop()


app = FastAPI(
    title="FluxMod Image Moderation API",
    description="CaFormer-based image/video content moderation - returns probabilities (sigmoid applied)",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    global engine
    stats = engine.get_stats() if engine else {}
    
    return HealthResponse(
        status="ok" if engine and engine.model._model_loaded else "error",
        model_loaded=engine is not None and engine.model._model_loaded,
        queue_size=stats.get('current_queue_size', 0),
        total_requests=stats.get('total_requests', 0),
        device=engine.model.device if engine else "unknown",
    )


@app.get("/stats")
async def get_stats():
    """Get detailed statistics."""
    global engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    
    return engine.get_stats()


@app.post("/predict", response_model=ImagePredictResponse)
async def predict_image(file: UploadFile = File(...)):
    """
    Get probabilities for an image file.
    Returns the full probability array (12476 values, sigmoid applied) - threshold handling is done by caller.
    """
    if engine is None or not engine.model._model_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    # Read image data
    image_data = await file.read()
    
    # Run inference
    try:
        result = await engine.predict(image_data)
        return ImagePredictResponse(
            probabilities=result['probabilities'],
            inference_time_ms=result['inference_time_ms'],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference failed: {str(e)}")


@app.post("/predict_single", response_model=ImagePredictResponse)
async def predict_image_single(file: UploadFile = File(...)):
    """
    Get probabilities for an image file (bypasses queue, direct inference).
    Returns the full probability array (12476 values, sigmoid applied) - threshold handling is done by caller.
    """
    if engine is None or not engine.model._model_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    # Read image data
    image_data = await file.read()
    
    # Run inference (bypasses queue)
    try:
        result = await engine.predict_single(image_data)
        return ImagePredictResponse(
            probabilities=result['probabilities'],
            inference_time_ms=result['inference_time_ms'],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference failed: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description="Image Moderation Inference Server v2")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=9001, help="Port to bind to")
    parser.add_argument("--model-path", help="Path to model file")
    parser.add_argument("--device", default="cpu", help="Device (cpu/cuda)")
    parser.add_argument("--max-batch-size", type=int, default=4, help="Max batch size")
    
    args = parser.parse_args()
    
    # Set environment variables for lifespan
    if args.model_path:
        os.environ["IMAGE_MODEL_PATH"] = args.model_path
    os.environ["IMAGE_MODEL_DEVICE"] = args.device
    os.environ["IMAGE_MAX_BATCH_SIZE"] = str(args.max_batch_size)
    
    print(f"Starting server on {args.host}:{args.port}")
    
    uvicorn.run(
        "LHS.image_inference_server:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
