"""
LHS Inference Server Manager

Manages the lifecycle of the LHS inference server subprocess.
Auto-starts the server when the bot starts and handles graceful shutdown.
"""

import subprocess
import asyncio
import os
import signal
import sys
from typing import Optional
from pathlib import Path

from utils.log import log
from utils.lhs_model_downloader import ensure_model_async, model_exists, get_model_path


class LHSServerManager:
    """
    Manages the LHS inference server as a subprocess.
    
    The server is started automatically and runs on localhost:8000 by default.
    Environment variables can override the host/port.
    """
    
    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 8000
    DEFAULT_MODEL_PATH = "LHS"
    DEFAULT_DEVICE = "cpu"
    DEFAULT_MAX_BATCH_SIZE = 32
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        model_path: Optional[str] = None,
        device: Optional[str] = None,
        max_batch_size: Optional[int] = None,
    ):
        self.host = host or os.getenv("LHS_HOST", self.DEFAULT_HOST)
        self.port = port or int(os.getenv("LHS_PORT", self.DEFAULT_PORT))
        self.model_path = model_path or os.getenv("LHS_MODEL_PATH", self.DEFAULT_MODEL_PATH)
        self.device = device or os.getenv("LHS_DEVICE", self.DEFAULT_DEVICE)
        self.max_batch_size = max_batch_size or int(os.getenv("LHS_MAX_BATCH_SIZE", self.DEFAULT_MAX_BATCH_SIZE))
        
        self.process: Optional[subprocess.Popen] = None
        self._shutdown_event = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None
        self._server_url = f"http://{self.host}:{self.port}"
    
    @property
    def server_url(self) -> str:
        """Get the server URL for the LHS client"""
        return self._server_url
    
    def _find_model_path(self) -> str:
        """Find the model file, checking multiple locations"""
        # First check the standard downloaded model location
        default_model = get_model_path()
        if default_model.exists():
            return str(default_model)
        
        # Check other locations
        paths_to_check = [
            self.model_path,
            "LHS/model.safetensors",
            "LHS/best_model.pt",
            "LHS/model.pt",
            "LHS/",
            os.path.join(os.path.dirname(__file__), "..", "LHS", "model.safetensors"),
            os.path.join(os.path.dirname(__file__), "..", "LHS", "best_model.pt"),
        ]
        
        for path in paths_to_check:
            if path and os.path.exists(path):
                return path
        
        # Return default path - server will provide better error message
        return str(default_model)
    
    def _build_command(self) -> list:
        """Build the command to start the inference server"""
        # Determine the module path
        # The inference_server.py is inside the LHS folder
        lhs_dir = Path(__file__).parent.parent / "LHS"
        
        if not lhs_dir.exists():
            log(f"[LHS Manager] Warning: LHS directory not found at {lhs_dir}", "warn")
        
        # Build command
        cmd = [
            sys.executable,
            "-m", "LHS.inference_server",
            "--host", self.host,
            "--port", str(self.port),
            "--model-path", self._find_model_path(),
            "--device", self.device,
            "--max-batch-size", str(self.max_batch_size),
        ]
        
        return cmd
    
    async def start(self, wait_for_ready: bool = True, timeout: float = 60.0, auto_download_model: bool = True) -> bool:
        """
        Start the LHS inference server.
        
        Args:
            wait_for_ready: Whether to wait for the server to be ready
            timeout: Maximum time to wait for server to be ready
            auto_download_model: Whether to download model if missing
        
        Returns:
            True if server started successfully, False otherwise
        """
        if self.process is not None and self.process.poll() is None:
            log("[LHS Manager] Server is already running", "info")
            return True
        
        # Check/download model if needed
        if auto_download_model and not model_exists():
            log("[LHS Manager] Model not found locally, downloading...", "info")
            try:
                await ensure_model_async()
                log("[LHS Manager] Model download complete", "success")
            except Exception as e:
                log(f"[LHS Manager] Failed to download model: {e}", "error")
                log("[LHS Manager] Please download manually from: https://modelscope.ai/models/LRimuru/LHS", "warn")
                return False
        
        cmd = self._build_command()
        log(f"[LHS Manager] Starting LHS inference server on {self.host}:{self.port}...", "info")
        log(f"[LHS Manager] Model: {self.model_path}, Device: {self.device}", "debug")
        
        try:
            # Start the subprocess
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                # Don't create a new process group so signals propagate correctly
                start_new_session=False,
            )
            
            log(f"[LHS Manager] Server process started (PID: {self.process.pid})", "success")
            
            # Start monitor task
            self._monitor_task = asyncio.create_task(self._monitor_process())
            
            if wait_for_ready:
                ready = await self._wait_for_ready(timeout)
                if ready:
                    log("[LHS Manager] Server is ready and accepting requests", "success")
                else:
                    log(f"[LHS Manager] Server did not become ready within {timeout}s", "warn")
                return ready
            
            return True
        
        except Exception as e:
            log(f"[LHS Manager] Failed to start server: {e}", "error")
            return False
    
    async def _wait_for_ready(self, timeout: float) -> bool:
        """Wait for the server to be ready by polling the health endpoint"""
        import aiohttp
        
        start_time = asyncio.get_event_loop().time()
        health_url = f"{self._server_url}/"
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(health_url, timeout=2) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("model_loaded"):
                                return True
            except Exception:
                pass
            
            # Check if process died
            if self.process and self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                log(f"[LHS Manager] Server process exited early (code: {self.process.returncode})", "error")
                if stderr:
                    log(f"[LHS Manager] Server stderr: {stderr[:500]}", "error")
                return False
            
            await asyncio.sleep(1)
        
        return False
    
    async def _monitor_process(self):
        """Monitor the server process and restart if it crashes"""
        try:
            while not self._shutdown_event.is_set():
                if self.process is None:
                    break
                
                retcode = self.process.poll()
                if retcode is not None:
                    # Process died
                    stdout, stderr = self.process.communicate()
                    log(f"[LHS Manager] Server process exited with code {retcode}", "warn")
                    
                    if stderr:
                        log(f"[LHS Manager] Server stderr: {stderr[:500]}", "debug")
                    
                    # Don't auto-restart on clean shutdown
                    if not self._shutdown_event.is_set():
                        log("[LHS Manager] Server stopped unexpectedly", "warn")
                    
                    break
                
                await asyncio.sleep(2)
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log(f"[LHS Manager] Monitor error: {e}", "error")
    
    async def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the LHS inference server gracefully.
        
        Args:
            timeout: Maximum time to wait for graceful shutdown
        
        Returns:
            True if server stopped successfully, False otherwise
        """
        if self.process is None:
            return True
        
        log("[LHS Manager] Stopping LHS inference server...", "info")
        self._shutdown_event.set()
        
        # Cancel monitor task
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        # Try graceful shutdown first
        try:
            self.process.terminate()
            
            # Wait for process to exit
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                    timeout=timeout
                )
                log("[LHS Manager] Server stopped gracefully", "success")
                return True
            except asyncio.TimeoutError:
                log("[LHS Manager] Server did not stop gracefully, forcing...", "warn")
                self.process.kill()
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                    timeout=5.0
                )
                return True
        
        except Exception as e:
            log(f"[LHS Manager] Error stopping server: {e}", "error")
            try:
                self.process.kill()
            except Exception:
                pass
            return False
        
        finally:
            self.process = None
    
    def is_running(self) -> bool:
        """Check if the server process is running"""
        return self.process is not None and self.process.poll() is None


# Global manager instance
_lhs_manager: Optional[LHSServerManager] = None


def get_lhs_server_manager() -> LHSServerManager:
    """Get or create global LHS server manager"""
    global _lhs_manager
    if _lhs_manager is None:
        _lhs_manager = LHSServerManager()
    return _lhs_manager


def reset_lhs_server_manager():
    """Reset the global manager (useful for testing)"""
    global _lhs_manager
    _lhs_manager = None
