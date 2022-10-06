import asyncio

import discord
from discord.ext import commands

from typing import Literal, Optional, overload

def boolize(string):
    string = string.lower()
    if string in ["true", "yes", "on", "enabled", "y", "t", "1"]:
        return True
    elif string in ["false", "no", "off", "disabled", "n", "f", "0"]:
        return False
    else:
        raise commands.UserInputError(f"{string} is not a recognized boolean option")

class Context(commands.Context):
    @overload
    async def ask(self, question: Optional[str], return_bool: Literal[True]=True, timeout: Optional[float] = 60.0, target: Optional[discord.User | discord.Member] = None) -> bool:
        ...
    @overload
    async def ask(self, question: Optional[str], return_bool: Literal[False]=False, timeout: Optional[float] = 60.0, target: Optional[discord.User | discord.Member] = None) -> str:
        ...
    
    async def ask(self, question: Optional[str], return_bool: bool = True, timeout: Optional[float] = 60.0, target: Optional[discord.User | discord.Member]=None) -> bool | str:
        target_: discord.User | discord.Member = target or self.author
        if question:
            await self.send(question)

        def predicate(msg):
            return msg.channel == self.channel and msg.author == target_
        try:
            m = await self.bot.wait_for("message", timeout=timeout, check=predicate)
        except asyncio.TimeoutError:
            raise commands.CommandError("timeout reached. aborting.")
        
        if not return_bool:
            return m.content
        
        return boolize(m.content)