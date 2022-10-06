import asyncio

import aiohttp
import discord
import toml
from discord.ext import commands
from utils.context import Context

from typing import cast, TypedDict

class _BotConfig(TypedDict):
    token: str

class _IdevisionConfig(TypedDict):
    token: str
    webhook_url: str

class _DBConfig(TypedDict):
    dsn: str

class Config(TypedDict):
    db: _DBConfig
    discord: _BotConfig
    mystbin: _BotConfig
    idevision: _IdevisionConfig

class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        self.config: Config = cast(Config, toml.load("config.toml"))
        super().__init__(*args, **kwargs)

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession()
        await self.load_extension("jishaku")
        await self.load_extension("extensions.meta")
        await self.load_extension("extensions.idevision")
        await self.load_extension("extensions.pythonista")
        await self.load_extension("extensions.bs")

    async def on_message(self, message: discord.Message, /) -> None:
        context = await self.get_context(message, cls=Context)
        if context.valid:
            await self.invoke(context)
        elif self.user.mentioned_in(context.message):
            await self.get_cog("Bull").pinged(context) # noqa

async def main():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = Bot("]", intents=intents)
    discord.utils.setup_logging(root=False)
    async with bot:
        await bot.start(bot.config["discord"]["token"])

asyncio.run(main())