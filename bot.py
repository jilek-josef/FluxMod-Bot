import fluxer
from colorama import Fore
import asyncio
from dotenv import load_dotenv
import os
import signal
from utils.log import log
from utils.lhs_server_manager import get_lhs_server_manager, get_image_moderation_server_manager


load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = fluxer.Intents.default()
if hasattr(intents, "message_content"):
    try:
        setattr(intents, "message_content", True)
    except Exception:
        pass

client = fluxer.Bot(intents=intents, command_prefix='fm!', retry_forever=True)

# LHS Server Managers
lhs_manager = get_lhs_server_manager()
image_manager = get_image_moderation_server_manager()


@client.event
async def on_ready():
    user = client.user
    if user is None:
        log("System online, but user information is unavailable.", "warn")
    else:
        log(f"System online as {user} ({user.id})", "success")
    log(f"Connected to {len(client.guilds)} guilds.", "info")
    
    # Start LHS text moderation server if not already running (and not using external server)
    lhs_server_url = os.environ.get("LHS_SERVER_URL", "")
    is_external = lhs_server_url and not any(local in lhs_server_url for local in ["localhost", "127.0.0.1", "0.0.0.0"])
    
    if not is_external and not lhs_manager.is_running():
        log("[LHS] Auto-starting text inference server...", "info")
        started = await lhs_manager.start(wait_for_ready=True, timeout=120.0)
        if started:
            log(f"[LHS] Text inference server ready at {lhs_manager.server_url}", "success")
        else:
            log("[LHS] Failed to start text inference server - AI text moderation will be unavailable", "warn")
    elif is_external:
        log(f"[LHS] Using external text inference server at {lhs_server_url}", "info")
    else:
        log(f"[LHS] Text inference server already running at {lhs_manager.server_url}", "info")
    
    # Start image moderation server (non-blocking)
    if not image_manager.is_running():
        log("[Image Mod] Auto-starting image inference server (background)...", "info")
        # Start without waiting - let it load in background
        asyncio.create_task(_start_image_server_async())
    else:
        log(f"[Image Mod] Image inference server already running at {image_manager.server_url}", "info")


async def _start_image_server_async():
    """Start image server in background without blocking on_ready"""
    try:
        started = await image_manager.start(wait_for_ready=True, timeout=180.0, auto_download_model=True)
        if started:
            log(f"[Image Mod] Image inference server ready at {image_manager.server_url}", "success")
        else:
            log("[Image Mod] Failed to start image inference server - image moderation will be unavailable", "warn")
    except Exception as e:
        log(f"[Image Mod] Error starting server: {e}", "error")


async def load_cogs():
    loaded = []
    failed = []

    for filename in os.listdir("cogs"):
        if filename.endswith(".py"):
            name = filename[:-3]
            try:
                log(f"Loading cog: {filename}", "info")
                await client.load_extension(f"cogs.{name}")
                loaded.append(filename)
            except Exception as e:
                failed.append((filename, str(e)))

    if loaded:
        log("Loaded cogs:", "success")
        for file in loaded:
            print(Fore.GREEN + f"   → {file}")
    if failed:
        log("Failed to load cogs:", "error")
        for file, error in failed:
            print(Fore.RED + f"   → {file}: {error}")


async def graceful_shutdown():
    """Handle graceful shutdown including LHS servers"""
    log("Shutting down gracefully...", "info")
    
    # Stop LHS text server
    await lhs_manager.stop()
    
    # Stop image moderation server
    await image_manager.stop()
    
    # Close bot connection
    await client.close()
    
    log("Shutdown complete", "success")


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(sig, frame):
        log(f"Received signal {sig}, initiating shutdown...", "warn")
        asyncio.create_task(graceful_shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


async def main():
    if not TOKEN:
        log("Missing TOKEN in .env file. Set TOKEN and restart.", "critical")
        return

    # Setup signal handlers
    setup_signal_handlers()

    try:
        await load_cogs()
    except Exception as e:
        log(f"Critical error loading cogs: {e}", "critical")

    try:
        log("Starting FluxMod client...", "info")
        await client.start(TOKEN)
    except KeyboardInterrupt:
        log("Manual shutdown requested (Ctrl+C)", "warn")
        await graceful_shutdown()
    except Exception as e:
        log(f"Failed to start bot: {e}", "critical")
        await lhs_manager.stop()

if __name__ == "__main__":
    asyncio.run(main())
