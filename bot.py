import fluxer
from colorama import Fore
import asyncio
from dotenv import load_dotenv
import os
from utils.log import log


load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = fluxer.Intents.default()
if hasattr(intents, "message_content"):
    try:
        setattr(intents, "message_content", True)
    except Exception:
        pass

client = fluxer.Bot(intents=intents, command_prefix='fm!', retry_forever=True)


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


async def main():
    if not TOKEN:
        log("Missing TOKEN in .env file. Set TOKEN and restart.", "critical")
        return

    try:
        await load_cogs()
    except Exception as e:
        log(f"Critical error loading cogs: {e}", "critical")

    try:
        log("Starting FluxMod client...", "info")
        await client.start(TOKEN)
    except KeyboardInterrupt:
        log("Manual shutdown requested (Ctrl+C)", "warn")
        await client.close()
    except Exception as e:
        log(f"Failed to start bot: {e}", "critical")

if __name__ == "__main__":
    asyncio.run(main())