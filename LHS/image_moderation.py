"""
Image/Video Content Moderation using CaFormer model

Provides NSFW and content rating detection for images and videos.
Model: animetimm_caformer_b36.dbv4-full_Quantized_Q8
"""

import os
import io
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from pathlib import Path

import torch
import numpy as np
from PIL import Image
from torchvision import transforms
from torchvision.transforms import InterpolationMode
from PIL import Image
import torch
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

# Model configuration
MODEL_NAME = "animetimm_caformer_b36.dbv4-full_Quantized_Q8"
MODEL_URL = "https://modelscope.ai/models/LRimuru/animetimm_caformer_b36.dbv4-full_Quantized_Q8/resolve/master/model.safetensors"
CONFIG_URL = "https://modelscope.ai/models/LRimuru/animetimm_caformer_b36.dbv4-full_Quantized_Q8/resolve/master/config.json"

# Content rating indices (first 4 logits)
CONTENT_RATINGS = ["general", "sensitive", "questionable", "explicit"]

# Special flag indices
INDEX_GURO = 3664
INDEX_REALISTIC = 1558
INDEX_CSAM_CHECK = 299  # If > 0.09 and realistic > 0.25 = potential CSAM

# Default thresholds
DEFAULT_IMAGE_THRESHOLDS = {
    "general": 0.2,
    "sensitive": 0.8,
    "questionable": 0.2,
    "explicit": 0.2,
    "guro": 0.3,
    "realistic": 0.25,
    "csam_check": 0.09,  # For index 299
    "ambiguous_threshold": 1.5,  # Sum of all ratings
}

# Video sampling configuration
VIDEO_SAMPLE_FRAMES = 3


@dataclass
class ImageModerationResult:
    """Result of image/video content moderation"""
    is_nsfw: bool
    content_rating: str  # general, sensitive, questionable, explicit
    confidence: float
    is_guro: bool
    is_realistic: bool
    potential_csam: bool
    is_ambiguous: bool
    logits: Dict[str, float]
    inference_time_ms: float

class HybridResizeCropPad:
    """
    Balanced resize that:
    - Uses ~50% crop and ~50% pad for moderate aspect ratios
    - Shifts toward more crop than pad for extreme ratios (wide/tall)
    - Never pads more than max_pad_ratio (25%) of the output dimension
    """

    def __init__(self, target_size=384, max_pad_ratio=0.25, fill=(255, 255, 255)):
        self.target = target_size if isinstance(target_size, (list, tuple)) else (target_size, target_size)
        self.T = self.target[0]  # assuming square target 384x384
        self.max_pad_pixels = int(self.T * max_pad_ratio)  # 96px for 384
        self.fill = fill

    def __call__(self, img):
        # Get original dimensions
        if isinstance(img, Image.Image):
            w, h = img.size
        else:
            # Tensor (C, H, W)
            _, h, w = img.shape

        # Calculate balanced scale: tries to make crop_amount ≈ pad_amount
        # Derived from: (s*w - T) = (T - s*h)  =>  s = 2T/(w+h)
        s_balanced = (2 * self.T) / (w + h)

        # Calculate minimum scale to respect 25% padding limit
        # We need: min(s*w, s*h) >= (T - max_pad_pixels)  =>  s >= (T - 96) / min(w,h)
        min_side = min(w, h)
        s_min = (self.T - self.max_pad_pixels) / min_side

        # Use the larger scale (guarantees padding <= 25%)
        s = max(s_balanced, s_min)

        # Resize with bicubic + antialias
        new_w = int(w * s)
        new_h = int(h * s)
        img = transforms.functional.resize(
            img,
            (new_h, new_w),
            interpolation=InterpolationMode.BICUBIC,
            antialias=True
        )

        # Determine crop/pad geometry (centered)
        # Width
        if new_w > self.T:
            # Needs crop
            crop_w = new_w - self.T
            left = crop_w // 2
            current_w = self.T
        else:
            # Needs pad
            pad_w = self.T - new_w
            left = pad_w // 2  # for padding
            current_w = new_w

        # Height
        if new_h > self.T:
            # Needs crop
            crop_h = new_h - self.T
            top = crop_h // 2
            current_h = self.T
        else:
            # Needs pad
            pad_h = self.T - new_h
            top = pad_h // 2  # for padding
            current_h = new_h

        # Apply crop if needed (to max T in each dimension)
        if new_w > self.T or new_h > self.T:
            crop_w_actual = min(new_w, self.T)
            crop_h_actual = min(new_h, self.T)
            img = transforms.functional.crop(img, top, left, crop_h_actual, crop_w_actual)

        # Apply pad if needed (to reach exactly T)
        if current_w < self.T or current_h < self.T:
            pad_right = self.T - current_w - left
            pad_bottom = self.T - current_h - top
            img = transforms.functional.pad(img, (left, top, pad_right, pad_bottom), fill=self.fill)

        return img


class ImageModerationModel:
    """CaFormer-based image content moderation model"""
    
    def __init__(self, model_path: Optional[str] = None, device: str = "cpu"):
        self.model_path = model_path or os.path.join("LHS", "image_model.safetensors")
        self.device = device
        self.model = None
        self.config = None
        self._model_loaded = False
        
    def load_model(self) -> bool:
        """Load the CaFormer model with HQQ quantization"""
        import time
        start_time = time.time()
        
        try:
            print(f"[Image Moderation] Starting model load...", flush=True)
            
            if not os.path.exists(self.model_path):
                print(f"[Image Moderation] Model not found at {self.model_path}", flush=True)
                return False
            
            print(f"[Image Moderation] Importing dependencies...", flush=True)
            import timm
            from hqq.core.quantize import HQQLinear, BaseQuantizeConfig
            from safetensors.torch import load_file
            print(f"[Image Moderation] Dependencies loaded in {time.time() - start_time:.1f}s", flush=True)
            
            # Load config
            config_path = self.model_path.replace(".safetensors", "_config.json")
            if os.path.exists(config_path):
                import json
                with open(config_path, 'r') as f:
                    self.config = json.load(f)
            
            # Create model with timm
            print(f"[Image Moderation] Creating model architecture...", flush=True)
            t0 = time.time()
            self.model = timm.create_model(
                "caformer_b36",
                pretrained=False,
                num_classes=12476,  # Model output size
            )
            print(f"[Image Moderation] Model created in {time.time() - t0:.1f}s", flush=True)
            
            # Setup HQQ quantization config
            print(f"[Image Moderation] Setting up HQQ quantization...", flush=True)
            t0 = time.time()
            quant_config = BaseQuantizeConfig(
                nbits=8,
                group_size=64,
                quant_zero=True,
                quant_scale=False,
            )
            
            # Replace Linear layers with HQQ quantized versions BEFORE loading weights
            # The saved model is already quantized, so we need matching structure
            print(f"[Image Moderation] Creating quantized layers on {self.device}...", flush=True)
            layer_count = 0
            for name, module in list(self.model.named_modules()):
                if isinstance(module, torch.nn.Linear):
                    try:
                        # Ensure module is on the correct device first
                        module = module.to(self.device)
                        # Use float16 for computation (both CPU and CUDA)
                        hqq_linear = HQQLinear(module, quant_config, device=self.device, compute_dtype=torch.float16)
                        # Ensure HQQ layer is on the correct device
                        hqq_linear = hqq_linear.to(self.device)
                        parent_name = '.'.join(name.split('.')[:-1])
                        child_name = name.split('.')[-1]
                        if parent_name:
                            parent = self.model.get_submodule(parent_name)
                            setattr(parent, child_name, hqq_linear)
                        else:
                            setattr(self.model, child_name, hqq_linear)
                        layer_count += 1
                    except Exception as e:
                        print(f"[Image Moderation] Could not quantize layer {name}: {e}", flush=True)
            print(f"[Image Moderation] {layer_count} layers quantized in {time.time() - t0:.1f}s", flush=True)

            state_dict = load_file(self.model_path)

            self.model.load_state_dict(state_dict, strict=False)
            self.model = self.model.to(self.device)
            self.model = self.model.half()
            # Add HQQ device handling loop here
            for module in self.model.modules():
                if hasattr(module, 'W_q'):
                    module.W_q = torch.nn.Parameter(module.W_q.to(self.device), requires_grad=False)
                if hasattr(module, 'meta'):
                    for key in list(module.meta.keys()):
                        if isinstance(module.meta[key], torch.Tensor):
                            module.meta[key] = module.meta[key].to(self.device)
                if hasattr(module, 'bias') and module.bias is not None:
                    module.bias = torch.nn.Parameter(module.bias.to(self.device))

            self.model.eval()
            print(f"[Image Moderation] Model ready on {self.device} in {time.time() - t0:.1f}s", flush=True)
            
            self._model_loaded = True
            total_time = time.time() - start_time
            print(f"[Image Moderation] Model loaded successfully on {self.device} in {total_time:.1f}s", flush=True)
            return True
            
        except Exception as e:
            total_time = time.time() - start_time
            print(f"[Image Moderation] Failed to load model after {total_time:.1f}s: {e}", flush=True)
            import traceback
            print(f"[Image Moderation] Traceback: {traceback.format_exc()}", flush=True)
            return False

    def _preprocess_image(self, image: Image.Image) -> torch.Tensor:
        """Preprocess image for model input"""
        from torchvision import transforms

        transform = transforms.Compose([
            HybridResizeCropPad(target_size=384, max_pad_ratio=0.25, fill=(255, 255, 255)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.48500001430511475, 0.4560000002384186, 0.4059999883174896],
                std=[0.2290000021457672, 0.2240000069141388, 0.22499999403953552]
            )
        ])
        
        # Convert to tensor, move to device, and ensure float16
        tensor = transform(image).unsqueeze(0).to(self.device).half()
        return tensor
    
    def _analyze_logits(self, logits: torch.Tensor, thresholds: Dict[str, float]) -> Dict[str, Any]:
        """Analyze model logits to determine content rating and flags"""
        logits = torch.sigmoid(logits).cpu().numpy().flatten()
        
        # Get content rating logits (first 4)
        rating_logits = logits[:4]
        
        # Get special flags
        guro_logit = logits[INDEX_GURO]
        realistic_logit = logits[INDEX_REALISTIC]
        csam_check_logit = logits[INDEX_CSAM_CHECK]
        
        # Check for ambiguous (sum of ratings > threshold)
        ratings_sum = np.sum(rating_logits)
        is_ambiguous = ratings_sum > thresholds.get("ambiguous_threshold", 1.5)
        
        # Check CSAM potential
        potential_csam = (
            csam_check_logit > thresholds.get("csam_check", 0.09) and
            realistic_logit > thresholds.get("realistic", 0.25)
        )
        
        # Determine content rating (if not ambiguous)
        content_rating = "general"
        confidence = 0.0
        is_nsfw = False
        
        if not is_ambiguous:
            # Check in order: explicit -> questionable -> general -> sensitive
            if rating_logits[3] > thresholds.get("explicit", 0.2):  # explicit
                content_rating = "explicit"
                confidence = float(rating_logits[3])
                is_nsfw = True
            elif rating_logits[2] > thresholds.get("questionable", 0.2):  # questionable
                content_rating = "questionable"
                confidence = float(rating_logits[2])
                is_nsfw = True
            elif rating_logits[0] > thresholds.get("general", 0.2):  # general
                content_rating = "general"
                confidence = float(rating_logits[0])
            elif rating_logits[1] > thresholds.get("sensitive", 0.8):  # sensitive
                content_rating = "sensitive"
                confidence = float(rating_logits[1])
            else:
                # Fallback: pick highest
                max_idx = np.argmax(rating_logits)
                content_rating = CONTENT_RATINGS[max_idx]
                confidence = float(rating_logits[max_idx])
                is_nsfw = max_idx >= 2  # questionable or explicit
        
        return {
            "is_nsfw": is_nsfw,
            "content_rating": content_rating,
            "confidence": confidence,
            "is_ambiguous": is_ambiguous,
            "is_guro": guro_logit > thresholds.get("guro", 0.3),
            "is_realistic": realistic_logit > thresholds.get("realistic", 0.25),
            "potential_csam": potential_csam,
            "guro_score": float(guro_logit),
            "realistic_score": float(realistic_logit),
            "csam_check_score": float(csam_check_logit),
            "ratings": {
                "general": float(rating_logits[0]),
                "sensitive": float(rating_logits[1]),
                "questionable": float(rating_logits[2]),
                "explicit": float(rating_logits[3]),
            },
        }
    
    async def moderate_image(
        self, 
        image_data: bytes, 
        thresholds: Optional[Dict[str, float]] = None
    ) -> ImageModerationResult:
        """Moderate a single image"""
        import time
        start_time = time.time()
        
        if not self._model_loaded:
            raise RuntimeError("Model not loaded")
        
        thresholds = thresholds or DEFAULT_IMAGE_THRESHOLDS
        
        # Load image
        image = Image.open(io.BytesIO(image_data)).convert("RGB")
        
        # Preprocess and run inference
        tensor = self._preprocess_image(image)
        
        with torch.no_grad():
            self.model.eval()
            logits = self.model(tensor)
        
        # Analyze results
        analysis = self._analyze_logits(logits[0], thresholds)
        
        inference_time = (time.time() - start_time) * 1000
        
        return ImageModerationResult(
            is_nsfw=analysis["is_nsfw"],
            content_rating=analysis["content_rating"],
            confidence=analysis["confidence"],
            is_guro=analysis["is_guro"],
            is_realistic=analysis["is_realistic"],
            potential_csam=analysis["potential_csam"],
            is_ambiguous=analysis["is_ambiguous"],
            logits=analysis["ratings"],
            inference_time_ms=inference_time,
        )
    
    def _extract_video_frames(self, video_data: bytes, num_frames: int = VIDEO_SAMPLE_FRAMES) -> List[Image.Image]:
        """Extract sample frames from video"""
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV not available for video processing")
        
        frames = []
        
        # Write video to temp file
        temp_path = "/tmp/temp_video.mp4"
        with open(temp_path, "wb") as f:
            f.write(video_data)
        
        cap = cv2.VideoCapture(temp_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if total_frames <= 0:
            cap.release()
            os.remove(temp_path)
            return frames
        
        # Sample frames evenly
        frame_indices = np.linspace(0, total_frames - 1, num_frames, dtype=int)
        
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
                frames.append(pil_image)
        
        cap.release()
        os.remove(temp_path)
        
        return frames
    
    async def moderate_video(
        self,
        video_data: bytes,
        thresholds: Optional[Dict[str, float]] = None,
        num_frames: int = VIDEO_SAMPLE_FRAMES,
    ) -> ImageModerationResult:
        """Moderate a video by sampling frames"""
        import time
        start_time = time.time()
        
        if not self._model_loaded:
            raise RuntimeError("Model not loaded")
        
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV not available for video processing")
        
        thresholds = thresholds or DEFAULT_IMAGE_THRESHOLDS
        
        # Extract frames
        frames = self._extract_video_frames(video_data, num_frames)
        
        if not frames:
            raise RuntimeError("Could not extract frames from video")
        
        # Moderate each frame
        results = []
        for frame in frames:
            tensor = self._preprocess_image(frame)
            with torch.no_grad():
                self.model.eval()
                logits = self.model(tensor)
            analysis = self._analyze_logits(logits[0], thresholds)
            results.append(analysis)
        
        # Aggregate results (worst case wins)
        is_nsfw = any(r["is_nsfw"] for r in results)
        is_guro = any(r["is_guro"] for r in results)
        is_realistic = any(r["is_realistic"] for r in results)
        potential_csam = any(r["potential_csam"] for r in results)
        is_ambiguous = any(r["is_ambiguous"] for r in results)
        
        # Determine overall rating (highest severity)
        rating_priority = {"explicit": 3, "questionable": 2, "sensitive": 1, "general": 0}
        max_priority = -1
        content_rating = "general"
        max_confidence = 0.0
        
        for r in results:
            if rating_priority.get(r["content_rating"], 0) > max_priority:
                max_priority = rating_priority[r["content_rating"]]
                content_rating = r["content_rating"]
                max_confidence = max(max_confidence, r["confidence"])
        
        # Aggregate logits (average)
        aggregated_logits = {
            "general": np.mean([r["ratings"]["general"] for r in results]),
            "sensitive": np.mean([r["ratings"]["sensitive"] for r in results]),
            "questionable": np.mean([r["ratings"]["questionable"] for r in results]),
            "explicit": np.mean([r["ratings"]["explicit"] for r in results]),
        }
        
        inference_time = (time.time() - start_time) * 1000
        
        return ImageModerationResult(
            is_nsfw=is_nsfw,
            content_rating=content_rating,
            confidence=max_confidence,
            is_guro=is_guro,
            is_realistic=is_realistic,
            potential_csam=potential_csam,
            is_ambiguous=is_ambiguous,
            logits=aggregated_logits,
            inference_time_ms=inference_time,
        )


# Global model instance
_image_model: Optional[ImageModerationModel] = None


def get_image_model(device: str = "cpu") -> ImageModerationModel:
    """Get or create global image moderation model instance"""
    global _image_model
    if _image_model is None:
        _image_model = ImageModerationModel(device=device)
    return _image_model
