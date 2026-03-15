"""
LHS Inference Server Manager

Manages the lifecycle of the LHS inference server subprocess.
Auto-starts the server when the bot starts and handles graceful shutdown.
"""

import subprocess
import asyncio
import os
import sys
from typing import Optional
from pathlib import Path

from utils.log import log
from utils.lhs_model_downloader import ensure_model_async, model_exists, get_model_path


class LHSServerManager:
    """
    Manages the LHS inference server as a subprocess.
    
    The server is started automatically and runs on localhost:9000 by default.
    Environment variables can override the host/port.
    """
    
    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 9000
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
        
        # Check/download model if needed (skip if LHS_SERVER_URL points to external server)
        external_server = os.environ.get("LHS_SERVER_URL", "").replace("http://", "").replace("https://", "")
        is_local = "localhost" in external_server or "127.0.0.1" in external_server or not external_server
        
        if is_local and auto_download_model and not model_exists():
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
class ImageModerationServerManager:
    """
    Manages the image moderation inference server as a subprocess.
    Runs alongside the text moderation server on a different port.
    """
    
    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 9001
    DEFAULT_DEVICE = "cpu"
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        model_path: Optional[str] = None,
        device: Optional[str] = None,
    ):
        self.host = host or os.getenv("IMAGE_MODERATION_HOST", self.DEFAULT_HOST)
        self.port = port or int(os.getenv("IMAGE_MODERATION_PORT", self.DEFAULT_PORT))
        self.model_path = model_path or os.getenv("IMAGE_MODEL_PATH")
        self.device = device or os.getenv("IMAGE_MODEL_DEVICE", self.DEFAULT_DEVICE)
        
        self.process: Optional[subprocess.Popen] = None
        self._shutdown_event = asyncio.Event()
        self._monitor_task: Optional[asyncio.Task] = None
        self._server_url = f"http://{self.host}:{self.port}"
    
    @property
    def server_url(self) -> str:
        """Get the server URL for the image moderation client"""
        return self._server_url
    
    def _build_command(self) -> list:
        """Build the command to start the image inference server"""
        cmd = [
            sys.executable,
            "-u",  # Unbuffered Python output
            "-m", "LHS.image_inference_server",
            "--host", self.host,
            "--port", str(self.port),
            "--device", self.device,
        ]
        
        if self.model_path:
            cmd.extend(["--model-path", self.model_path])
        
        return cmd
    
    async def start(self, wait_for_ready: bool = True, timeout: float = 60.0, auto_download_model: bool = True) -> bool:
        """Start the image moderation inference server"""
        if self.process is not None and self.process.poll() is None:
            log("[Image Manager] Server is already running", "info")
            return True
        
        # Check/download model if needed
        from utils.lhs_model_downloader import ensure_image_model_async, image_model_exists
        
        if auto_download_model and not image_model_exists():
            log("[Image Manager] Model not found locally, downloading...", "info")
            try:
                await ensure_image_model_async()
                log("[Image Manager] Model download complete", "success")
            except Exception as e:
                log(f"[Image Manager] Failed to download model: {e}", "error")
                log("[Image Manager] Image moderation will be unavailable", "warn")
                return False
        
        cmd = self._build_command()
        log(f"[Image Manager] Starting image moderation server on {self.host}:{self.port}...", "info")
        log(f"[Image Manager] Command: {' '.join(cmd)}", "debug")
        
        try:
            # Start process with unbuffered output for real-time logging
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            
            log("[Image Manager] Creating subprocess...", "debug")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                text=True,
                bufsize=1,  # Line buffered
                start_new_session=False,
                env=env,
                cwd=os.getcwd(),
            )
            
            log(f"[Image Manager] Server process started (PID: {self.process.pid})", "success")
            
            # Give it a moment to either fail immediately or start
            await asyncio.sleep(0.5)
            
            # Check if it died immediately
            if self.process.poll() is not None:
                stdout, _ = self.process.communicate(timeout=5)
                log(f"[Image Manager] Server died immediately! Exit code: {self.process.returncode}", "error")
                if stdout:
                    log(f"[Image Manager] Server output:\n{stdout}", "error")
                return False
            
            # Start log streaming task immediately
            log("[Image Manager] Starting log streamer...", "debug")
            asyncio.create_task(self._stream_logs())
            
            # Start monitor task
            self._monitor_task = asyncio.create_task(self._monitor_process())
            
            if wait_for_ready:
                ready = await self._wait_for_ready(timeout)
                if ready:
                    log("[Image Manager] Server is ready", "success")
                else:
                    log(f"[Image Manager] Server did not become ready within {timeout}s", "warn")
                    # Try to get final output
                    try:
                        self.process.terminate()
                        await asyncio.sleep(0.5)
                        stdout, _ = self.process.communicate(timeout=5)
                        if stdout:
                            log(f"[Image Manager] Server output:\n{stdout[-2000:]}", "error")
                    except Exception:
                        pass
                return ready
            
            return True
        
        except Exception as e:
            log(f"[Image Manager] Failed to start server: {e}", "error")
            import traceback
            log(f"[Image Manager] Traceback: {traceback.format_exc()}", "error")
            return False
    
    async def _wait_for_ready(self, timeout: float) -> bool:
        """Wait for the server to be ready"""
        import aiohttp
        
        start_time = asyncio.get_event_loop().time()
        health_url = f"{self._server_url}/"
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(health_url, timeout=2) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("status") == "ok":
                                return True
            except Exception:
                pass
            
            # Check if process died
            if self.process and self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                log(f"[Image Manager] Server process exited early (code: {self.process.returncode})", "error")
                if stderr:
                    log(f"[Image Manager] Server stderr: {stderr[:500]}", "error")
                return False
            
            await asyncio.sleep(1)
        
        return False
    
    async def _stream_logs(self):
        """Stream server logs in real-time"""
        if self.process is None or self.process.stdout is None:
            return
        
        try:
            while not self._shutdown_event.is_set():
                if self.process is None:
                    break
                
                # Read line without blocking
                import select
                
                fd = self.process.stdout.fileno()
                if fd < 0:
                    break
                
                # Check if data is available (non-blocking)
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    try:
                        line = self.process.stdout.readline()
                        if line:
                            line = line.strip()
                            if line:
                                log(f"[Image Server] {line}", "debug")
                    except Exception:
                        pass
                else:
                    # No data, check if process died
                    if self.process.poll() is not None:
                        break
                    await asyncio.sleep(0.1)
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log(f"[Image Manager] Log stream error: {e}", "debug")
    
    async def _monitor_process(self):
        """Monitor the server process"""
        try:
            while not self._shutdown_event.is_set():
                if self.process is None:
                    break
                
                retcode = self.process.poll()
                if retcode is not None:
                    stdout, stderr = self.process.communicate()
                    log(f"[Image Manager] Server process exited with code {retcode}", "warn")
                    
                    # Log final output on error
                    if retcode != 0 and stdout:
                        log(f"[Image Manager] Server final output:\n{stdout[-1500:]}", "error")
                    
                    break
                
                await asyncio.sleep(2)
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log(f"[Image Manager] Monitor error: {e}", "error")
    
    async def stop(self, timeout: float = 10.0) -> bool:
        """Stop the image moderation server gracefully"""
        if self.process is None:
            return True
        
        log("[Image Manager] Stopping image moderation server...", "info")
        self._shutdown_event.set()
        
        # Cancel monitor task
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        # Try graceful shutdown
        try:
            self.process.terminate()
            
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                    timeout=timeout
                )
                log("[Image Manager] Server stopped gracefully", "success")
                return True
            except asyncio.TimeoutError:
                log("[Image Manager] Server did not stop gracefully, forcing...", "warn")
                self.process.kill()
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                    timeout=5.0
                )
                return True
        
        except Exception as e:
            log(f"[Image Manager] Error stopping server: {e}", "error")
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


# Global image manager instance
_image_manager: Optional[ImageModerationServerManager] = None


def get_image_moderation_server_manager() -> ImageModerationServerManager:
    """Get or create global image moderation server manager"""
    global _image_manager
    if _image_manager is None:
        _image_manager = ImageModerationServerManager()
    return _image_manager


def reset_image_moderation_server_manager():
    """Reset the global image manager (useful for testing)"""
    global _image_manager
    _image_manager = None
