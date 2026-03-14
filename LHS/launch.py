#!/usr/bin/env python3
"""
Launcher script for the inference server and Gradio UI.
"""

import subprocess
import sys
import time
import argparse


def start_server(args):
    """Start the inference server."""
    cmd = [
        sys.executable, "-m", "inference_server",
        "--host", args.server_host,
        "--port", str(args.server_port),
        "--model-path", args.model_path,
        "--device", args.device,
        "--max-batch-size", str(args.max_batch_size),
    ]
    
    if args.server_workers > 1:
        cmd.extend(["--workers", str(args.server_workers)])
    
    print(f"Starting inference server on {args.server_host}:{args.server_port}...")
    return subprocess.Popen(cmd)


def start_ui(args):
    """Start the Gradio UI."""
    server_url = f"http://{args.server_host}:{args.server_port}"
    
    cmd = [
        sys.executable, "-m", "gradio_ui",
        "--host", args.ui_host,
        "--port", str(args.ui_port),
        "--server-url", server_url,
    ]
    
    if args.share:
        cmd.append("--share")
    
    print(f"Starting Gradio UI on {args.ui_host}:{args.ui_port}...")
    return subprocess.Popen(cmd)


def main():
    parser = argparse.ArgumentParser(description="Launch Inference Server and/or Gradio UI")
    
    # Server options
    parser.add_argument("--server-only", action="store_true", help="Start only the server")
    parser.add_argument("--ui-only", action="store_true", help="Start only the UI")
    parser.add_argument("--server-host", default="0.0.0.0", help="Server host")
    parser.add_argument("--server-port", type=int, default=8000, help="Server port")
    parser.add_argument("--model-path", default="model.safetensors", help="Path to model (directory, .safetensors, or .pt)")
    parser.add_argument("--device", default="cpu", help="Device (cpu/cuda)")
    parser.add_argument("--max-batch-size", type=int, default=32, help="Max batch size")
    parser.add_argument("--server-workers", type=int, default=1, help="Server worker processes")
    
    # UI options
    parser.add_argument("--ui-host", default="0.0.0.0", help="UI host")
    parser.add_argument("--ui-port", type=int, default=7860, help="UI port")
    parser.add_argument("--share", action="store_true", help="Create public share link for UI")
    
    # Common options
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between starting server and UI")
    
    args = parser.parse_args()
    
    processes = []
    
    try:
        if not args.ui_only:
            # Start server
            server_proc = start_server(args)
            processes.append(("server", server_proc))
            
            # Wait for server to start
            if not args.server_only:
                print(f"Waiting {args.delay}s for server to initialize...")
                time.sleep(args.delay)
        
        if not args.server_only:
            # Start UI
            ui_proc = start_ui(args)
            processes.append(("ui", ui_proc))
        
        print("\n" + "="*60)
        if not args.ui_only:
            print(f"Inference Server: http://{args.server_host}:{args.server_port}")
        if not args.server_only:
            print(f"Gradio UI:        http://{args.ui_host}:{args.ui_port}")
        print("="*60)
        print("Press Ctrl+C to stop\n")
        
        # Wait for processes
        while True:
            for name, proc in processes:
                ret = proc.poll()
                if ret is not None:
                    print(f"\n{name} process exited with code {ret}")
                    # Kill other processes
                    for n, p in processes:
                        if p.poll() is None:
                            p.terminate()
                            try:
                                p.wait(timeout=5)
                            except:
                                p.kill()
                    return ret
            time.sleep(0.5)
    
    except KeyboardInterrupt:
        print("\n\nStopping processes...")
        for name, proc in processes:
            if proc.poll() is None:
                print(f"  Stopping {name}...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except:
                    proc.kill()
        print("Done!")


if __name__ == "__main__":
    main()
