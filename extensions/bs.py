from discord.ext import commands
import random
import json

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

    @commands.command("countm")
    @commands.is_owner()
    async def mention_count(self, ctx):
        await ctx.reply(str(len(self.mention_messages)), mention_author=False)

    async def pinged(self, ctx):
        await ctx.send(random.choice(self.mention_messages).replace("$m", ""))
