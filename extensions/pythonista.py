from __future__ import annotations

import discord
import aiohttp
import re
from discord.ext import commands
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import Bot

async def setup(bot: Bot):
    await bot.add_cog(Pythonista(bot))

BADBIN_RE = re.compile(r"https://(?P<site>pastebin.com|hastebin.com)/(?P<slug>[a-zA-Z]+)[.]?(?P<ext>[a-z]{1,5})?")
GITHUB_RE = re.compile(r"([a-zA-Z0-9_!]+)?(/[a-zA-Z0-9_!]+)?##([0-9]+)")

SPECIAL_CHANNEL_INDEX = {
    669115391880069150: "twitchio",
    491048464831086592: "twitchio",
    531269424523771934: "wavelink",
    739788459006492752: "wavelink",
    491048383578898441: "discord.py"
}

class Pythonista(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession()

    async def pull_badbin_content(self, site: str, slug: str) -> str:
        async with self.session.get(f"https://{site}/raw/{slug}") as f:
            if 200 > f.status > 299:
                f.raise_for_status()

            return (await f.read()).decode()

    async def post_mystbin_content(self, contents: list[tuple[str, str]]) -> tuple[str, str | None]:
        hdrs = {}
        if self.bot.config["mystbin"]["token"]:
            hdrs["Authorization"] = self.bot.config["mystbin"]["token"]

        async with self.session.put(
                "https://api.mystb.in/paste",
                headers=hdrs,
                json={"files": [{"filename": x[1], "content": x[0]} for x in contents]}
        ) as resp:
            if 200 > resp.status > 299:
                resp.raise_for_status()

            data = await resp.json()
            print(data)
            return data["id"], data.get("notice") or None


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild.id != 490948346773635102:
            return

        matches = BADBIN_RE.findall(message.content)
        if matches:
            contents = []
            for match in matches:
                site, slug, ext = match
                if site is None or slug is None:
                    continue
                contents.append((await self.pull_badbin_content(site, slug), f"migrated.{ext or 'txt'}"))

            if contents:
                key, notice = await self.post_mystbin_content(contents)

                msg = f"I've detected a badbin and have uploaded your pastes here: https://mystb.in/{key}"
                if notice:
                    msg += "\nnotice: " + notice

                await message.channel.send(msg)

        match = GITHUB_RE.search(message.content)
        if match:
            user, lib, issue = match.groups()
            if lib:
                lib = lib.strip("/")

            if user in {"me", "!"}:
                user = message.author.name

            elif message.channel.id in {669115391880069150, 491048464831086592}:
                if not lib or lib == "!":
                    lib = "TwitchIO"

                if not user:
                    user = "TwitchIO"

            elif message.channel.id in {739788459006492752, 531269424523771934}:
                if not lib:
                    lib = "Wavelink"

                if not user:
                    user = "PythonistaGuild"

            elif message.channel.id == 698366338774728714 or (isinstance(message.channel, discord.Thread) and message.channel.parent_id == 1008693609089990766):
                if not lib:
                    lib = "mystbin"

                if not user:
                    user = "PythonistaGuild"


            elif isinstance(message.channel, discord.Thread) and isinstance(message.channel.parent, discord.ForumChannel):
                tags = set(x.name for x in message.channel.applied_tags)
                if "twitchio-help" in tags:
                    if not lib:
                        lib = "TwitchIO"

                    if not user:
                        user = "TwitchIO"

                elif "wavelink-help" in tags:
                    if not lib:
                        lib = "Wavelink"

                    if not user:
                        user = "PythonistaGuild"

                elif "discord.py-help" in tags:
                    if not lib:
                        lib = "Wavelink"

                    if not user:
                        user = "PythonistaGuild"

            if not lib and not user:
                return await message.channel.send("<:peepowtf:1027379056800440320>")

            await message.channel.send(f"https://github.com/{user}/{lib}/issues/{issue}")
