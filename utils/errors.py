from discord.ext import commands

class CommandInterrupt(commands.CommandError):
    def __init__(self, msg):
        self.message = msg
        Exception.__init__(self, msg)
