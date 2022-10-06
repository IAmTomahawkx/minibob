from __future__ import annotations
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from bot import Bot
    from utils.context import Context

async def setup(bot: Bot) -> None:
    await bot.add_cog(Meta(bot))


class Meta(commands.Cog):
    @commands.command("about", aliases=["info"])
    async def about(self, ctx: Context) -> None:
        emb = discord.Embed(
            title="Minibob",
            description="I am a relic of the old bot, bob. My only purpose now is providing an API wrapper for the [Idevision API](https://idevision.net/docs).",
            colour=discord.Colour.teal()
        )
        await ctx.reply(embed=emb)