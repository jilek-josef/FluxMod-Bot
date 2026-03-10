import asyncio
import fluxer


async def delete_after(message: fluxer.Message, delay: int):
    """Delete a message after a certain amount of time."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except fluxer.NotFound:
        pass
    except fluxer.Forbidden:
        pass