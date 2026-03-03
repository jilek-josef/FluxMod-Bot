import fluxer
from colorama import Fore, Style, init
import asyncio
from dotenv import load_dotenv
import os
from datetime import datetime


init(autoreset=True)

load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = fluxer.Intents.default()
if hasattr(intents, "message_content"):
    try:
        setattr(intents, "message_content", True)
    except Exception:
        pass

client = fluxer.Bot(intents=intents, command_prefix='n!', retry_forever=True)



def log(msg: str, level: str = "info"):
    time = datetime.now().strftime("%H:%M:%S")
    levels = {
        "info": Fore.CYAN + "[INFO]",
        "success": Fore.GREEN + "[SUCCESS]",
        "warn": Fore.YELLOW + "[WARN]",
        "error": Fore.RED + "[ERROR]",
        "critical": Fore.MAGENTA + "[CRITICAL]",
    }
    tag = levels.get(level, Fore.WHITE + "[LOG]")
    print(f"{Fore.BLACK}[{time}]{Style.RESET_ALL} {tag} {Fore.WHITE}{msg}{Style.RESET_ALL}")

@client.event
async def on_ready():
    user = client.user
    if user is None:
        log("System online, but user information is unavailable.", "warn")
    else:
        log(f"System online as {user} ({user.id})", "success")
    log(f"Connected to {len(client.guilds)} guilds.", "info")


async def load_cogs():
    loaded = []
    failed = []

    for filename in os.listdir("cogs"):
        if filename.endswith(".py"):
            name = filename[:-3]
            try:
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

import random

@client.command()
async def test_retry(message):
    """Command to test retry logic."""
    import random
    from asyncio import sleep

    log("Starting retry test...", "info")

    async def fake_request(attempt=0):
        if random.random() < 0.8:  # 80% chance to fail
            log(f"Attempt {attempt} failed!", "warn")
            raise Exception("Simulated network error")
        return {"success": True}

    max_retries = 5
    attempt = 0
    while attempt < max_retries:
        try:
            result = await fake_request(attempt)
            log(f"Request succeeded: {result}", "success")
            break
        except Exception as e:
            attempt += 1
            log(f"Retry {attempt}/{max_retries} after error: {e}", "warn")
            await sleep(0.5)
    else:
        log(f"All retries failed.", "error")

async def main():
    if not TOKEN:
        log("Missing TOKEN in .env file. Set TOKEN and restart.", "critical")
        return

    try:
        await load_cogs()
    except Exception as e:
        log(f"Critical error loading cogs: {e}", "critical")

    try:
        log("Starting Nari client...", "info")
        await client.start(TOKEN)
    except KeyboardInterrupt:
        log("Manual shutdown requested (Ctrl+C)", "warn")
        await client.close()
    except Exception as e:
        log(f"Failed to start bot: {e}", "critical")

if __name__ == "__main__":
    asyncio.run(main())