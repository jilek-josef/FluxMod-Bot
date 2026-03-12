"""
LHS Model Downloader

Downloads the model file on-demand from ModelScope if not present locally.
"""

import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
import asyncio


# Default model download URL
DEFAULT_MODEL_URL = "https://modelscope.ai/models/LRimuru/LHS/resolve/master/model.safetensors"

# Alternative mirrors (in case primary fails)
MIRROR_URLS = [
    "https://modelscope.ai/models/LRimuru/LHS/resolve/master/model.safetensors",
]

# Expected file size (for verification)
EXPECTED_FILE_SIZE = 114116700  # ~109MB


class ModelDownloadError(Exception):
    """Raised when model download fails"""
    pass


def get_model_path() -> Path:
    """Get the path where model should be stored"""
    # Get the LHS directory relative to this file
    lhs_dir = Path(__file__).parent.parent / "LHS"
    return lhs_dir / "model.safetensors"


def model_exists() -> bool:
    """Check if model file exists and has reasonable size"""
    model_path = get_model_path()
    if not model_path.exists():
        return False
    
    # Check file size is reasonable (at least 50MB)
    size = model_path.stat().st_size
    return size > 50 * 1024 * 1024


def download_model(
    url: Optional[str] = None,
    progress_callback=None,
    timeout: int = 300,
) -> Path:
    """
    Download the model file.
    
    Args:
        url: URL to download from (default: ModelScope)
        progress_callback: Optional callback(bytes_downloaded, total_bytes)
        timeout: Download timeout in seconds
    
    Returns:
        Path to downloaded model
    
    Raises:
        ModelDownloadError: If download fails
    """
    model_path = get_model_path()
    model_path.parent.mkdir(parents=True, exist_ok=True)
    
    urls_to_try = [url] if url else []
    urls_to_try.extend(MIRROR_URLS)
    
    last_error = None
    
    for try_url in urls_to_try:
        try:
            print(f"[LHS Downloader] Downloading model from {try_url}...")
            print(f"[LHS Downloader] This may take a few minutes (approx 109MB)...")
            
            # Create request with headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            request = urllib.request.Request(try_url, headers=headers)
            
            # Download with progress
            with urllib.request.urlopen(request, timeout=timeout) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                
                # Download in chunks
                chunk_size = 8192
                downloaded = 0
                
                with open(model_path, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if progress_callback and total_size:
                            progress_callback(downloaded, total_size)
                        
                        # Print progress every 10MB
                        if downloaded % (10 * 1024 * 1024) < chunk_size:
                            mb = downloaded / (1024 * 1024)
                            if total_size:
                                pct = (downloaded / total_size) * 100
                                print(f"[LHS Downloader] Downloaded: {mb:.1f}MB ({pct:.1f}%)")
                            else:
                                print(f"[LHS Downloader] Downloaded: {mb:.1f}MB")
            
            # Verify download
            actual_size = model_path.stat().st_size
            if actual_size < 50 * 1024 * 1024:
                model_path.unlink()  # Delete partial/corrupt file
                raise ModelDownloadError(f"Downloaded file too small ({actual_size} bytes)")
            
            print(f"[LHS Downloader] Download complete: {model_path}")
            print(f"[LHS Downloader] File size: {actual_size / (1024*1024):.1f}MB")
            
            return model_path
        
        except Exception as e:
            last_error = e
            print(f"[LHS Downloader] Failed to download from {try_url}: {e}")
            # Clean up partial download
            if model_path.exists():
                model_path.unlink()
            continue
    
    raise ModelDownloadError(f"Failed to download model from all sources. Last error: {last_error}")


async def download_model_async(
    url: Optional[str] = None,
    progress_callback=None,
    timeout: int = 300,
) -> Path:
    """
    Async wrapper for download_model.
    
    Runs the download in a thread pool to not block the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: download_model(url, progress_callback, timeout)
    )


def ensure_model() -> Path:
    """
    Ensure model exists, downloading if necessary.
    
    Returns:
        Path to model file
    
    Raises:
        ModelDownloadError: If model cannot be obtained
    """
    model_path = get_model_path()
    
    if model_exists():
        return model_path
    
    print("[LHS] Model not found locally, downloading...")
    return download_model()


async def ensure_model_async() -> Path:
    """Async version of ensure_model"""
    model_path = get_model_path()
    
    if model_exists():
        return model_path
    
    print("[LHS] Model not found locally, downloading...")
    return await download_model_async()


def get_model_info() -> dict:
    """Get information about the model file"""
    model_path = get_model_path()
    
    info = {
        "exists": model_exists(),
        "path": str(model_path),
        "size": 0,
        "size_human": "0 MB",
    }
    
    if model_path.exists():
        size = model_path.stat().st_size
        info["size"] = size
        info["size_human"] = f"{size / (1024*1024):.1f} MB"
    
    return info


# CLI for testing
if __name__ == "__main__":
    import sys
    
    print("LHS Model Downloader")
    print("=" * 50)
    
    # Check current status
    info = get_model_info()
    print(f"Model path: {info['path']}")
    print(f"Exists: {info['exists']}")
    if info['exists']:
        print(f"Size: {info['size_human']}")
        sys.exit(0)
    
    # Download
    print("\nModel not found. Downloading...")
    try:
        path = download_model()
        print(f"\nSuccess! Model saved to: {path}")
    except Exception as e:
        print(f"\nFailed: {e}")
        sys.exit(1)
