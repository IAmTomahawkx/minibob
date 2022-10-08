from __future__ import annotations
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
import random
import json

if TYPE_CHECKING:
    from utils.context import Context

async def setup(bot):
    await bot.add_cog(Bull(bot))

class Bull(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open("bullshit.json") as f:
            self.mention_messages = json.load(f)

    @commands.command(aliases=["addm"])
    @commands.is_owner()
    async def add_mention(self, ctx, *, entry):
        self.mention_messages.append(entry)

        with open("bullshit.json", "w") as f:
            json.dump(self.mention_messages, f)

        await ctx.message.add_reaction("\U0001f44d")

    @commands.command(aliases=["massaddm"])
    @commands.is_owner()
    async def mass_add_mention(self, ctx: Context, messages: commands.Greedy[discord.Message]):
        for message in messages:
            for attch in message.attachments:
                self.mention_messages.append(attch.url)

        with open("bullshit.json", "w") as f:
            json.dump(self.mention_messages, f)

        await ctx.message.add_reaction("\U0001f44d")

    @commands.command("countm")
    @commands.is_owner()
    async def mention_count(self, ctx):
        await ctx.reply(str(len(self.mention_messages)), mention_author=False)

    async def pinged(self, ctx):
        await ctx.send(random.choice(self.mention_messages).replace("$m", ""))
