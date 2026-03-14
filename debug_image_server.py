#!/usr/bin/env python3
"""
Debug script for image_inference_server.py
Runs the server directly so you can see all output and stack traces.

Usage:
    cd FluxMod-Bot
    python debug_image_server.py [--device cpu|cuda]
"""

import sys
import os
import argparse
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Debug image inference server")
    parser.add_argument('--device', default='cpu', choices=['cpu', 'cuda'])
    parser.add_argument('--port', type=int, default=9001)
    parser.add_argument('--host', default='0.0.0.0')
    args = parser.parse_args()
    
    print("=" * 70)
    print("Image Inference Server - Debug Mode")
    print("=" * 70)
    print(f"This script runs the server directly (no subprocess)")
    print(f"so you can see all output and stack traces immediately.")
    print("=" * 70)
    print(f"Host: {args.host}")
    print(f"Port: {args.port}")
    print(f"Device: {args.device}")
    print("=" * 70)
    
    # Set environment variables
    os.environ['IMAGE_MODEL_DEVICE'] = args.device
    os.environ['PYTHONUNBUFFERED'] = '1'
    
    # Import and run the server directly
    try:
        print("\n[1/3] Importing server module...")
        from LHS.image_inference_server import app, lifespan
        print("   ✓ Import successful")
        
        print("\n[2/3] Importing image moderation...")
        from LHS.image_moderation import get_image_model
        print("   ✓ Import successful")
        
        # Check model file
        print("\n[3/3] Checking model file...")
        from utils.lhs_model_downloader import get_image_model_path, image_model_exists
        model_path = get_image_model_path()
        print(f"   Model path: {model_path}")
        print(f"   Model exists: {image_model_exists()}")
        
        if not image_model_exists():
            print("\n   ⚠ Model file not found! Attempting to download...")
            print("   (This may take a few minutes - ~400MB)")
            try:
                from utils.lhs_model_downloader import ensure_image_model
                ensure_image_model()
                print("   ✓ Model downloaded successfully")
            except Exception as e:
                print(f"   ✗ Download failed: {e}")
                print("\n   Please download the model manually or check your internet connection.")
                sys.exit(1)
        
        print("\n" + "=" * 70)
        print("Starting Uvicorn server...")
        print("=" * 70)
        print(f"Server will be available at: http://{args.host}:{args.port}")
        print("Press Ctrl+C to stop")
        print("=" * 70 + "\n")
        
        import uvicorn
        uvicorn.run(
            "LHS.image_inference_server:app",
            host=args.host,
            port=args.port,
            log_level="debug",
            reload=False
        )
        
    except ImportError as e:
        print(f"\n✗ Import Error: {e}")
        print("\nMake sure you have installed all dependencies:")
        print("  pip install torch torchvision timm hqq safetensors fastapi uvicorn")
        import traceback
        traceback.print_exc()
        sys.exit(1)
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
