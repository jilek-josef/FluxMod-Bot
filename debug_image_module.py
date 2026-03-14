#!/usr/bin/env python3
"""
Debug script for image_moderation.py module
Tests model loading directly with full stack traces.

Usage:
    cd FluxMod-Bot
    python debug_image_module.py [--device cpu|cuda]
"""

import sys
import os
import argparse
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Debug image moderation module")
    parser.add_argument('--device', default='cpu', choices=['cpu', 'cuda'])
    args = parser.parse_args()
    
    print("=" * 70)
    print("Image Moderation Module - Debug Mode")
    print("=" * 70)
    print(f"Device: {args.device}")
    print("=" * 70)
    
    # Step 1: Import dependencies
    print("\n[Step 1/5] Checking dependencies...")
    try:
        import torch
        print(f"   ✓ PyTorch {torch.__version__}")
        
        import torchvision
        print(f"   ✓ TorchVision {torchvision.__version__}")
        
        from PIL import Image
        print("   ✓ Pillow")
        
        import numpy as np
        print("   ✓ NumPy")
        
        import timm
        print(f"   ✓ timm {timm.__version__}")
        
        import hqq
        print(f"   ✓ HQQ")
        
        from safetensors.torch import load_file
        print("   ✓ SafeTensors")
        
    except ImportError as e:
        print(f"   ✗ Missing dependency: {e}")
        print("\nInstall with:")
        print("  pip install torch torchvision timm hqq safetensors pillow numpy")
        sys.exit(1)
    
    # Step 2: Import module
    print("\n[Step 2/5] Importing image_moderation module...")
    try:
        from LHS.image_moderation import ImageModerationModel, get_image_model
        print("   ✓ Module imported successfully")
    except Exception as e:
        print(f"   ✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Step 3: Check model file
    print("\n[Step 3/5] Checking model file...")
    try:
        from utils.lhs_model_downloader import get_image_model_path, image_model_exists
        model_path = get_image_model_path()
        print(f"   Model path: {model_path}")
        print(f"   Model exists: {image_model_exists()}")
        
        if image_model_exists():
            size_mb = model_path.stat().st_size / (1024 * 1024)
            print(f"   Model size: {size_mb:.1f} MB")
        else:
            print("\n   ⚠ Model file not found!")
            print("   You can download it with:")
            print("     python -c \"from utils.lhs_model_downloader import ensure_image_model; ensure_image_model()\"")
            response = input("\n   Download now? (y/n): ").strip().lower()
            if response == 'y':
                from utils.lhs_model_downloader import ensure_image_model
                ensure_image_model()
            else:
                sys.exit(1)
                
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Step 4: Create model instance
    print(f"\n[Step 4/5] Creating model instance (device={args.device})...")
    try:
        model = ImageModerationModel(device=args.device)
        print("   ✓ Model instance created")
        print(f"   Model path: {model.model_path}")
        print(f"   Device: {model.device}")
    except Exception as e:
        print(f"   ✗ Failed to create model: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Step 5: Load model
    print("\n[Step 5/5] Loading model (this may take a while)...")
    print("-" * 70)
    start_time = time.time()
    
    try:
        loaded = model.load_model()
        load_time = time.time() - start_time
        print("-" * 70)
        
        if loaded:
            print(f"\n   ✓ Model loaded successfully in {load_time:.1f}s")
            print(f"   Model is on device: {model.device}")
            print(f"   Model loaded flag: {model._model_loaded}")
            
            # Test inference with a dummy image
            print("\n   Testing inference with dummy image...")
            from PIL import Image
            import io
            
            # Create a simple test image
            img = Image.new('RGB', (512, 512), color=(100, 150, 200))
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            image_bytes = buffer.getvalue()
            
            import asyncio
            
            async def test_inference():
                return await model.moderate_image(image_bytes)
            
            result = asyncio.run(test_inference())
            
            print(f"   ✓ Inference successful!")
            print(f"\n   Results:")
            print(f"     Content Rating: {result.content_rating}")
            print(f"     Is NSFW: {result.is_nsfw}")
            print(f"     Confidence: {result.confidence:.4f}")
            print(f"     Inference Time: {result.inference_time_ms:.2f}ms")
            
        else:
            print(f"\n   ✗ Model.load_model() returned False")
            print("   Check the error messages above for details.")
            sys.exit(1)
            
    except Exception as e:
        load_time = time.time() - start_time
        print("-" * 70)
        print(f"\n   ✗ Model loading failed after {load_time:.1f}s")
        print(f"\n   Error: {e}")
        print("\n   Full traceback:")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n" + "=" * 70)
    print("✓ All debug checks passed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
