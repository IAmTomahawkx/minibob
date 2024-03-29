from __future__ import annotations
import io
import datetime

import asyncpg
import yarl
import re
import pprint
import tabulate
from typing import Optional, Union, cast, TYPE_CHECKING

import aiohttp
import discord

from discord.ext import commands

from utils import paginator, errors
from utils.context import Context

if TYPE_CHECKING:
    from bot import Bot

URL_RE = re.compile(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+")

SPECIAL_CHANNEL_INDEX = {
    669115391880069150: "twitchio",
    491048464831086592: "twitchio",
    531269424523771934: "wavelink",
    739788459006492752: "wavelink",
    491048383578898441: "discord.py"
}

class _libconverter(commands.Converter):
    async def convert(self, ctx: Context, param):
        if param.lower() in {"dpy", "discordpy", "discord.py"}:
            return "discord.py-2"
        elif param.lower() in {"dpy2", "discord.py2", "discordpy2", "2.0", "master"}:
            return "discord.py-2"
        elif param.lower() in {"tio", "twitch", "twitchio"}:
            return "twitchio"
        elif param.lower() in {"wl", "wave", "link", "wavelink"}:
            return "wavelink"
        elif param.lower() in {"ahttp", "aiohttp"}:
            return "aiohttp"
        elif param.lower() in {"enhanced-dpy", "enhanced-discord.py", "edpy"}:
            return "enhanced-discord.py"
        else:
            raise commands.UserInputError("Must be one of discord.py, discord.py2, enhanced-dpy, twitchio, wavelink, or aiohttp")

async def setup(bot):
    await bot.add_cog(Idevision(bot))

v = {
    "link1": "https://github.com/",
    "link1_name": "Github",
    "link2": "https://metrics.idevision.net",
    "link2_name": "Idevision",
    "link3": "https://twitch.tv",
    "link3_name": "Twitch",
    "link4": "https://youtube.com",
    "link4_name": "Youtube"
}

class Idevision(commands.Cog):
    url = "https://idevision.net/api/"

    def __init__(self, bot: Bot):
        self.bot = bot
        self.defaults = {}
        self.pages = {}
        self.usage = {}
        self.session = aiohttp.ClientSession(headers={"Authorization": bot.config['idevision']['token'], "User-Agent": "MiniBOB"})
        self._hook_session = aiohttp.ClientSession()
        self.hook: discord.Webhook = discord.Webhook.from_url(bot.config['idevision']['webhook_url'], session=self._hook_session) # noqa

    async def cog_load(self) -> None:
        self.db: asyncpg.Pool = await asyncpg.create_pool(self.bot.config["db"]["dsn"])

    async def cog_unload(self):
        await self._unload()

    async def _unload(self):
        await self.db.close()
        await self.session.close()
        await self._hook_session.close()

    async def do_rtfm(self, ctx, key, obj, labels=True, obvious_labels=False):
        if ctx.guild is not None and ctx.guild.id in self.defaults and key is None:
            key = self.defaults[ctx.guild.id]

        target = self.pages[key]['url']

        if obj is None:
            return await ctx.send(target)

        url = yarl.URL(self.url + "public/rtfm.sphinx").with_query(
            {
                "query": obj,
                "location": target,
                "show-labels": str(labels),
                "label-labels": str(obvious_labels)
            }
        )

        headers = {"User-Agent": f"BOB discord bot (squawking {ctx.author})"}
        async with self.session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return await ctx.send(f"The api returned an irregular status ({resp.status}) ({await resp.text()})")

            matches = await resp.json()
            if not matches['nodes']:
                return await ctx.send("Could not find anything. Sorry.")

        e = discord.Embed(colour=0x36393E)
        e.title = f"{self.pages[key]['long']}: {obj}"
        e.description = '\n'.join(f'[`{key}`]({url})' for key, url in matches['nodes'].items())
        e.url = self.url.replace("api/", "docs")
        e.set_footer(text=f"rtfm api available at {e.url}")
        await ctx.send(embed=e)

    @commands.group(aliases=['rtfd', "rtm", "rtd"], invoke_without_command=True, help="read the fucking docs. see `!help rtfm`")
    async def rtfm(self, ctx: Context, *, obj: Optional[str] = None):
        """
        view the documentation of the modules available in `rtfm list`.
        use their *quick* name to access it in the rtfm command, as such:
        `rtfm py sys`

        By default, labels are not shown in the results. To enable labels, use the `--labels` flag
        """
        await ctx.typing()

        labels = False
        obvious_labels = False
        if obj is not None:
            if "--labels" in obj:
                labels = True
                obvious_labels = True
                obj = obj.replace("--labels", "")

            from discord.ext.commands.view import StringView
            view = StringView(obj)
            key = view.get_word()  # check if the first arg is specifying a certain rtfm
            approved_key = None

            for k, v in self.pages.items():
                if key == k:
                    approved_key = k
                    view.skip_ws()
                    obj = view.read_rest().strip()
                    if not obj: obj = None
                    break

                elif key.lower() == v['long'].lower():
                    approved_key = k
                    view.skip_ws()
                    obj = view.read_rest().strip()
                    if not obj:
                        obj = None
                    break

            if approved_key is None:
                obj = (key + " " + view.read_rest()).strip()
                if not obj: obj = None

            if not approved_key and ctx.channel.id in SPECIAL_CHANNEL_INDEX:
                approved_key = list(filter(lambda m: m['long'].lower() == SPECIAL_CHANNEL_INDEX[ctx.channel.id],
                                           self.pages.values()))[0]['quick']

            if not approved_key and ctx.guild.id in self.defaults:
                approved_key = self.defaults[ctx.guild.id]

            elif not approved_key:
                raise errors.CommandInterrupt("No rtfm selected, and no default doc is set for your guild.")


        elif ctx.guild.id in self.defaults:
            approved_key = self.defaults[ctx.guild.id]
        else:
            raise errors.CommandInterrupt("No rtfm selected, and no default doc is set for your guild.")

        self.usage[approved_key] = datetime.datetime.utcnow()
        await self.do_rtfm(ctx, approved_key, obj, labels, obvious_labels)

    @rtfm.command()
    async def list(self, ctx):
        """
        shows a list of the current documentation entries. you can use the short name to use the doc. ex: !rtfm py {{insert thing here}}
        """
        all_entries = await self.db.fetch("SELECT * FROM pages")
        entries = [(a['quick'], f"{a['long']}: {a['url']}") for a in all_entries]
        pages = paginator.FieldPages(ctx, entries=entries, per_page=5)
        await pages.paginate()

    @rtfm.command()
    @commands.has_permissions(manage_guild=True)
    async def default(self, ctx: Context, default: str):
        """
        sets a default rtfm for your guild, so you don't need to type the docs prefix each time.
        requires the `Bot Editor` role or higher
        note that you can only have 1 default per guild.
        """
        if default not in self.pages:
            return await ctx.send(f"`{default}` is not a valid doc! If you wish to add one, please use `!rtfm add` to submit it for review")
        else:
            self.defaults[ctx.guild.id] = default
            await self.db.execute("INSERT INTO default_rtfm VALUES ($1,$2)", ctx.guild.id, default)
            await ctx.send(f"set the guild's default rtfm to `{self.pages[default]['long']}`")

    @rtfm.command(usage="")
    async def add(self, ctx: Context, quick=None, long=None, url=None):
        """
        Have some documentation you want to see here? Add it here!
        there are a few requirements for your docs to be approved.
        - it **must** be created with Sphinx.

        You will be prompted for the documentation information
        """
        if await ctx.bot.is_owner(ctx.author) and quick and long and url:
            if quick in self.pages:
                return await ctx.send("Already exists")
            await self.db.execute("INSERT INTO pages VALUES ($1,$2,$3)", quick, long, url)

            self.pages[quick] = {"quick": quick, "long": long, "url": url}
            return await ctx.send("\U0001f44d")

        def check_cancel(content):
            if "cancel" in content:
                raise errors.CommandInterrupt("aborting")

        await ctx.send("By adding documentation, you agree that you have read the rules to adding documentation. type cancel to abort the creation process\n\n"
                       "Please provide a quick default for your rtfm (used when not accessing your guild's default, max 7 characters)")
        msg = await ctx.bot.wait_for("message", check=lambda m: m.channel == ctx.channel and m.author == ctx.author, timeout=30)
        quick = await commands.clean_content().convert(ctx, msg.content)
        if len(quick) > 7:
            raise commands.CommandError("That's more than 7 characters!")

        check_cancel(msg.content)
        if quick in self.pages:
            raise commands.CommandError("That documentation already exists!")

        try:
            long = await commands.clean_content().convert(ctx, await ctx.ask("Now, please provide the full documentation name", return_bool=False))
            check_cancel(long)
        except errors.CommandInterrupt: raise
        except: pass

        msg = await ctx.ask("Now, provide the url to the documentation.", return_bool=False)
        check_cancel(msg)

        url = await commands.clean_content().convert(ctx, msg)
        async with self.bot.session.get(url.strip("/")+"/objects.inv") as resp:
            if resp.status != 200:
                raise errors.CommandInterrupt("Invalid url provided (no /objects.inv found). remember to remove the current page! ex. https://docs.readthedocs.io/latest")

        await self.db.execute("INSERT INTO pages VALUES ($1,$2,$3)", quick, long, url)
        self.pages[quick] = {"quick": quick, "long": long, "url": url}
        await ctx.send("Your documentation has been added")

    @rtfm.command(hidden=True)
    @commands.is_owner()
    async def remove(self, ctx: Context, quick: str):
        await self.db.execute("DELETE FROM pages WHERE quick = $1", quick)
        if quick in self.pages:
            del self.pages[quick]
            return await ctx.send(f"removed `{quick}` from rtfm")
        await ctx.send(f"`{quick}` not found")

    @rtfm.before_invoke
    @default.before_invoke
    @add.before_invoke
    async def rtfm_pre(self, ctx: Context):
        if not self.pages:
            data = await self.db.fetch("SELECT * FROM pages")
            for record in data:
                self.pages[record['quick']] = dict(record)

        if not self.defaults:
            v = await self.db.fetch("SELECT * FROM default_rtfm")
            for record in v:
                self.defaults[record['guild_id']] = record['name']

    @commands.command()
    async def xkcd(self, ctx: Context, *, no_or_search: Union[int, str]):
        nsfw = ctx.guild is None or cast(discord.TextChannel, ctx.channel).is_nsfw()

        if isinstance(no_or_search, int):
            async with self.bot.session.get(f"https://xkcd.com{no_or_search}/info.0.json") as resp:
                if resp.status == 404:
                    return await ctx.send("XKCD not found")

                resp = await resp.json()
                e = discord.Embed(title=resp['safe_title' if nsfw else "title"],
                                   description=resp['alt'], color=0x36393E)
                e.set_footer(text=f"#{resp['num']}  • {resp['month']}/{resp['day']}/{resp['year']}")
                e.set_image(url=resp['img'])
                await ctx.send(embed=e)

        else:
            async with self.session.get(self.url + f"public/xkcd?search={no_or_search}") as resp:
                if resp.status != 200:
                    return await ctx.send(f"Something messed up :( ({resp.status, resp.reason})")

                data = await resp.json()

            if not data['nodes']:
                return await ctx.send("Nothing found :(")

            ems = []
            for d in data['nodes']:
                e = discord.Embed(
                    title=d['safe_title' if nsfw else "title"],
                    description=d['alt'],
                    color=0x36393E,
                    url=d['url'],
                    timestamp=datetime.datetime.fromisoformat(d['posted'])
                ).set_footer(
                    text=f"#{d['num']}"
                ).set_image(
                    url=d['image_url']
                )
                ems.append(e)

            if len(ems) == 1:
                return await ctx.send(embed=ems[0])

            e = paginator.EmbedPages(ctx, entries=ems)
            await e.paginate()

    @commands.command("chess")
    @commands.is_owner()
    async def chess(self, ctx: Context, target: discord.User, board_theme: str="walnut"):
        th1 = await ctx.ask(f"{ctx.author.mention}, theme?", return_bool=False)
        th2 = await ctx.ask(f"{target.mention}, theme?", return_bool=False, target=target)

        async with self.session.post(self.url + "games/chess", json={"white-theme": th1, "black-theme": th2, "board-theme": board_theme}) as resp:
            if resp.status != 200:
                return await ctx.send(f"Failed to generate a game: {resp.reason}")
            
            board: dict = await resp.json()

        #board = {'pieces': ['1a11', '0a21', None, None, None, '0a60', None, '1a80', None, '0b21', None, None, None, '0b60', None, '2b80', None, '0c21', '2c31', None, None, '0c60', None, '3c80', None, '4d21', None, '0d41', None, '0d60', None, '4d80', '5e11', '0e21', '3e31', None, None, None, '0e70', '5e80', '3f11', '0f21', None, None, None, None, '0f70', '3f80', '2g11', '0g21', None, None, None, None, '0g70', '2g80', '1h11', '0h21', None, None, None, None, '0h70', '1h80'], 'turn': 1, 'transcript': ['10d2d4nn', '00d7d6nn', '13c1e3nn', '00b7b6nn', '12b1c3nn', '00c7c6nn', '14d1d2nn', '00a7a6nn'], 'white-theme': 'glass', 'black-theme': 'glass', 'board-theme': 'walnut', 'castling': '1111'}

        last: Optional[discord.Message] = None
        _last: Optional[discord.Message] = None
        arrow = None
        do_render = True

        while True:
            if last:
                await last.delete()
                if _last:
                    await _last.delete()
                last = _last = None

            if do_render:
                _last = await ctx.send(str((board, arrow)))
                async with self.session.post(self.url + "games/chess/render", json={"board": board, "arrow": arrow}) as resp:
                    if resp.status != 200:
                        return await ctx.send(f"Failed to generate a board: {resp.reason}")

                    data = io.BytesIO()
                    data.write(await resp.read())
                    data.seek(0)

                last = await ctx.send(file=discord.File(data, "board.png"))

            turn = board['turn']
            t: discord.Member | discord.User
            if turn == 1:
                t = ctx.author
            else:
                t = target

            while True:
                move = await ctx.ask(None, target=t, return_bool=False, timeout=None)
                if move in ("cancel", "stop"):
                    await ctx.send("\U0001f44d")
                    return

                if "-" in move:
                    break

                if move == "transcript":
                    async with self.session.post(self.url + "games/chess/transcript", json={"board": board}) as resp:
                        transcript = await resp.text()

                    if len(transcript) > 1500:

                        pages = paginator.TextPages(ctx, "Click \U000023f9 to continue with the game\n" + transcript, max_size=1500, prefix="", suffix="")
                        await pages.paginate()
                    else:
                        await ctx.send(transcript)

            async with self.session.post(self.url + "games/chess/turn", json={"board": board, "move": move, "move-turn": "black" if turn else "white"}) as resp:
                if resp.status == 417:
                    data = await resp.json()
                    board = data['board']
                    await ctx.send(f"expectation failed: {data['error']}")
                    do_render = True

                elif resp.status == 200:
                    data = await resp.json()
                    board = data['board']
                    arrow = data.get("arrow")
                    do_render = True

                else:
                    await ctx.send(f"something fucked up: {resp.status, resp.reason, await resp.text()}")


    @commands.command("math")
    async def math(self, ctx: Context, *, expression: str):
        r"""
        This math parser makes use of the idevision math endpoint.
        This accepts mathematical functions (P(x) = expression)
        \> Functions in the form of `y = ...` will be graphed, and will not be usable in expressions. These functions have one implicit argument, `x`.
        Geometric sequences can be created using the `s` variable: `s=1,2,4`. The third arg is optional. You can then access the sequence via `s(n)`
        The following variables are currently built in:
        - pi
        - E
        The following functions are currently built in:
        - sin(x) / asin(x, y)
        - cos(x) / acos(x, y)
        - tan(x) / atan(x, y)
        - log(n, base)
        Each line will be treated as a separate expression. Functions defined are available for all expressions.
        If you find something that returns a 500 error, or something is missing that'd you'd like to see in this endpoint, feel free to contact me @IAmTomahawkx

        *This endpoint is in heavy beta, and is inherently unstable*
        """
        headers = {"User-Agent": f"BOB discord bot (squawking {ctx.author})"}

        async with self.session.post(self.url + "public/math", data=expression, headers=headers) as resp:
            if resp.status == 417:
                await ctx.send(f"Your expression contains errors\n```\n{(await resp.text()).strip()}\n```",
                               allowed_mentions=discord.AllowedMentions.none())

            elif resp.status == 200:
                data = await resp.json()
                files = []
                if data['images']:
                    for i, x in enumerate(data['images']):
                        async with self.session.get(x) as r:
                            if r.status == 200:
                                files.append(discord.File(io.BytesIO(await r.read()), filename=f"file-{i}.png"))

                await ctx.send(data['text'], files=files)

            else:
                await ctx.send(f"The api returned a non-ok response ({resp.status}: {await resp.text()}). "
                               f"<@547861735391100931> something fucked up", allowed_mentions=discord.AllowedMentions.all())

    @commands.command("rtfm-rs")
    async def rtfm_rs(self, ctx: Context, crate: str, *, query: str):
        """
        Searches https://docs.rs/ crates using the idevision.net api. alternatively, pass `std` as the crate to search the stdlib docs.
        """
        if not crate.startswith("https") and crate != "std":
            crate = f"https://docs.rs/{crate}"

        headers = {"User-Agent": f"BOB discord bot (squawking {ctx.author})"}
        async with self.session.get(self.url + "public/rtfm.rustdoc", params={"location": crate, "query": query}, headers=headers) as resp:
            if resp.status != 200:
                return await ctx.send(f"Api returned a bad response {resp.status, resp.reason}")

            data = await resp.json()
            await ctx.send(data)

    @commands.command()
    async def rtfs(self, ctx: Context, lib: Optional[_libconverter], *, item: str): # type: ignore
        """
        Indexes a library for items matching the given input.
        The following libraries are valid: dpy, dpy2, aiohttp, twitchio, wavelink

        you can use the --source flag to receive the source directly in discord, instead of a link to github
        """
        lib: str = lib # type: ignore

        fmt: str = "links"
        if "--source" in item:
            item = item.replace("--source", "")
            fmt = "source"

        if lib is None:
            lib = SPECIAL_CHANNEL_INDEX.get(ctx.channel.id, "discord.py-2")

        url = yarl.URL(self.url + "public/rtfs").with_query(
            {
                "query": item,
                "library": cast(str, lib),
                "format": fmt
            }
        )
        headers = {"User-Agent": f"BOB discord bot (squawking {ctx.author})"}
        async with self.session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return await ctx.reply(f"The api returned a non-ok response: {resp.status} ({resp.reason})", mention_author=False)

            data = await resp.json()

        nodes = data['nodes']
        time = float(data['query_time'])

        if not nodes:
            return await ctx.reply(f"Could not find anything. Sorry. (query time {round(time, 4)})", mention_author=False)

        if fmt == "links":
            out = [f"[{name}]({url})" for name, url in nodes.items()]

            await ctx.send(embed=discord.Embed(
                description="\n".join(out),
                title=f"Result for {lib}: {item}"
            )
                .set_footer(text=f"Is the api behind on commits? Use {discord.utils.escape_mentions(cast(str, ctx.prefix))}rtfs-reload")
                .set_author(name=f"query time: {round(time, 3)} • commit {data['commit'][:6]}"))

        else:
            n = next(iter(nodes.items()))
            await ctx.reply(f"Showing source for {n[0]}\nCommit: {data['commit']}", mention_author=False)
            pages = paginator.TextPages(ctx, n[1], prefix="```py")
            await pages.paginate()

    @commands.command("rtfs-reload")
    @commands.cooldown(1, 180)
    async def rtfs_reload(self, ctx):
        """
        Reloads all rtfs nodes up to the latest commit.
        This command should not be called frequently.
        """
        url = yarl.URL(self.url + "public/rtfs.reload")

        async with self.session.put(url) as resp:
            if resp.status != 200:
                return await ctx.send(f"The api returned a non-ok response: {resp.status} ({resp.reason})")

            data = await resp.json()

        if data['fail']:
            fails = "(Failed to reload: " + ", ".join(data['fails']) + ")"
        else:
            fails = ""

        commits = "\n".join(f"{name}: {commit}" for name, commit in data['commits'].items())

        await ctx.reply(f"Reloaded {len(data['success'])} repos {fails}.\n{commits}", mention_author=False)

    @commands.command()
    @commands.cooldown(4, 10)
    async def ocr(self, ctx: Context, attachment: Optional[str] = None):
        """
        Preforms OCR on an image. This image can be uploaded as an attachment, or passed as a url link.
        OCR api: https://idevision.net/docs
        """
        if not ctx.message.attachments and not attachment:
            return await ctx.send("Please provide an attachment or a url")

        if ctx.message.attachments:
            url = ctx.message.attachments[0].url
        else:
            url = attachment

        resp = await self.bot.session.get(url) #type: aiohttp.ClientResponse
        if "image" not in resp.content_type:
            resp.close()
            return await ctx.send("URL/attachment was not an image")

        filetype = (ctx.message.attachments[0].filename if ctx.message.attachments else cast(str, attachment).split("/")[-1]).split(".")[-1]

        headers = {"User-Agent": f"BOB discord bot (squawking {ctx.author})"}
        async with self.session.get(self.url + f"public/ocr?filetype={filetype}", data=resp.content, headers=headers) as r:
            resp.close()
            if r.status != 200:
                return await ctx.send(f"The api responded with {r.status}: {r.reason}")
            else:
                d = await r.json()
                pages = paginator.TextPages(ctx, d['data'])

    @commands.group(aliases=["id"], invoke_without_command=True)
    async def idevision(self, ctx):
        """
        API control for the idevision site.
        Most of this is owner-only, the `apply` and `token` subcommands are available for public use.
        """
        await ctx.send("Idevision documentation can be found at https://idevision.net/docs\n"
                       f"To regenerate your idevision token, use `{ctx.invoked_with} token`\n"
                       f"To apply for an idevision API token, use `{ctx.invoked_with} apply`")

    @idevision.command("token")
    async def api_token(self, ctx):
        """
        Regenerates your idevision token, and dms it to you.
        """
        async with self.session.post(self.url + "internal/users/token", json={
            "discord_id": ctx.author.id
        }) as resp:
            if resp.status == 400:
                pref = await commands.clean_content().convert(ctx, ctx.prefix)
                return await ctx.send(f"You do not have an idevision account. Use `{pref}idevision apply <reason>` to apply for an account.")
            if resp.status != 200:
                return await ctx.send(f"Internal error: {resp.status}, {await resp.text()}")
            else:
                data = await resp.json()
                await ctx.author.send(f"Your idevision token is `{data['token']}`. Use the `idevision token` command to regenerate your token at any time.")
                await ctx.message.add_reaction("thumbsup")

    @idevision.command("apply")
    async def api_apply(self, ctx: Context, *, reason: str):
        """
        Allows you to apply for a token on the idevision API.
        This will give you access to the OCR endpoint, CDN endpoints, along with higher ratelimits.
        Anyone may use this command.
        """
        async with self.session.post(self.url + "internal/users/apply", json={
            "username": ctx.author.name + ctx.author.discriminator, # intentionally not using str() here
            "userid": ctx.author.id,
            "reason": reason,
            "permissions": ["public.ocr", "cdn"]
        }) as resp:
            if resp.status == 403:
                return await ctx.send(f"Failed to make the request (unauthorized): {await resp.text(), resp.reason}")
            elif resp.status != 201:
                return await ctx.send(f"Internal error: {resp.status}, {resp.reason}")
            else:
                emb = discord.Embed(colour=discord.Colour.dark_gold(), title="Application Recieved", description=f"([jump url]({ctx.message.jump_url}))\nReason:\n{reason}")
                emb = emb.set_author(name=str(ctx.author), icon_url=str(cast(discord.Asset, ctx.author.avatar).url)).set_footer(text=str(ctx.author.id))
                emb.timestamp = datetime.datetime.utcnow()
                await self.hook.send(embed=emb)
                await ctx.send("Application recieved. Please make sure your dms are enabled, or you will not recieve your token when your application is accepted.")

    @idevision.command("accept", aliases=['approve'])
    @commands.is_owner()
    async def accept(self, ctx: Context, user: discord.User):
        async with self.session.post(self.url + "internal/users/accept", json={"userid": user.id}) as resp:
            if resp.status != 201:
                return await ctx.send(f"Internal error: {resp.status}, {resp.reason}")
            else:
                data = await resp.json()
                try:
                    await user.send(f"Your idevision token is `{data['token']}`. Use the `idevision token` command to regenerate your token at any time.")
                except:
                    await ctx.send(f"Accepted {user} (failed to dm the user)")
                else:
                    await ctx.send(f"Accepted {user} (user notified through dm)")

    @idevision.command("deny", aliases=['decline'])
    @commands.is_owner()
    async def user_deny(self, ctx: Context, user: discord.User, allow_reapply=False, *, reason):
        async with self.session.post(self.url + "internal/users/deny", json={"userid": user.id, "retry": allow_reapply, "reason": reason}) as resp:
            if resp.status != 204:
                return await ctx.send(f"Internal error: {resp.status}, {resp.reason}")
            else:
                try:
                    await ctx.author.send(
                        f"Your idevision application has been denied. {'you may reapply' if allow_reapply else ''}\nreason: \n```\n{reason}\n```")
                except:
                    await ctx.send(f"Denied {user} (failed to dm the user)")
                else:
                    await ctx.send(f"Denied {user} (user notified through dm)")

    @idevision.group(invoke_without_command=True, aliases=['user'])
    @commands.is_owner()
    async def users(self, ctx: Context, username: Union[discord.User, str], unsafe:bool=False):
        url = yarl.URL(self.url + "internal/users")
        if isinstance(username, discord.User):
            url = url.with_query(username=username.name + username.discriminator, discord_id=username.id)
        else:
            url = url.with_query(username=username)

        async with self.session.get(url) as resp:
            if 200 <= resp.status < 300:
                data = await resp.json()
                if "auth_key" in data and not unsafe:
                    del data['auth_key']

                await ctx.send("\n".join(f"{x}: {v}" for x, v in data.items()))

            elif resp.reason:
                await ctx.send(f"Failed: ({resp.status})" + resp.reason)

            else:
                await ctx.send("Failed. " + str(resp.status))

    @users.command("add")
    @commands.is_owner()
    async def user_add(self, ctx: Context, user: discord.User, *perms):
        async with self.session.post(self.url + "internal/users",
                                     json={"username": user.name + user.discriminator, "permissions": perms, "discord_id": user.id}) as resp:
            if 200 <= resp.status < 300:
                data = await resp.json()
                await ctx.send(f"User has been added, token: {data['token']}")

            elif resp.reason:
                await ctx.send(f"Failed: ({resp.status})" + resp.reason)

            else:
                await ctx.send("Failed. " + str(resp.status))

    @users.command("addperms", aliases=['addperm', 'ap'])
    @commands.is_owner()
    async def user_add_perm(self, ctx: Context, username: Union[discord.User, str], *perms):
        url = yarl.URL(self.url + "internal/users")
        if isinstance(username, discord.User):
            url = url.with_query(username=username.name + username.discriminator, discord_id=username.id)
        else:
            url = url.with_query(username=username)

        async with self.session.get(url) as resp:
            if 200 <= resp.status < 300:
                data = await resp.json()
                _perms = data['permissions']

            else:
                return await ctx.send(f"Failed: ({resp.status})" + cast(str,resp.reason))

        perms = set(perms)
        perms.update(_perms)
        perms = list(perms)

        async with self.session.patch(self.url + "internal/users",
                                     json={"username": username, "permissions": perms}) as resp:
            if 200 <= resp.status < 300:
                await ctx.send(f"User modified successfully")

            elif resp.reason:
                await ctx.send(f"Failed: {resp.status, resp.reason}")

            else:
                await ctx.send("Failed. " + str(resp.status))

    @users.command("removeperm", aliases=['removeperms', 'rmperm', 'rmperms', 'rp'])
    @commands.is_owner()
    async def user_rm_perm(self, ctx: Context, username: Union[discord.User, str], *perms):
        url = yarl.URL(self.url + "internal/users")
        if isinstance(username, discord.User):
            url = url.with_query(username=username.name + username.discriminator, discord_id=username.id)
        else:
            url = url.with_query(username=username)

        async with self.session.get(url) as resp:
            if 200 <= resp.status < 300:
                data = await resp.json()
                _perms = data['permissions']

            else:
                return await ctx.send(f"Failed: ({resp.status})" + cast(str, resp.reason))

        for p in perms:
            if p in _perms:
                _perms.remove(p)

        async with self.session.patch(self.url + "internal/users",
                                     json={"username": username, "permissions": _perms}) as resp:
            if 200 <= resp.status < 300:
                await ctx.send(f"User modified successfully")

            elif resp.reason:
                await ctx.send(f"Failed: {resp.status, resp.reason}")

            else:
                await ctx.send("Failed. " + str(resp.status))

    @users.command("setname")
    @commands.is_owner()
    async def user_set_name(self, ctx: Context, currentname: Union[discord.User, str], new_name: str):
        if isinstance(currentname, discord.User):
            currentname = currentname.name + currentname.discriminator

        async with self.session.patch(self.url + "internal/users",
                                     json={"username": currentname, "new_username": new_name}) as resp:
            if 200 <= resp.status < 300:
                await ctx.send(f"User modified successfully")

            elif resp.reason:
                await ctx.send(f"Failed: {resp.status, resp.reason}")

            else:
                await ctx.send("Failed. " + str(resp.status))


    @users.command()
    @commands.is_owner()
    async def deauth(self, ctx: Context, username: str):
        async with self.session.post(self.url + "internal/users/deauth", json={"username": username}) as resp:
            if 200 <= resp.status < 300:
                await ctx.send("User has been deauthed")

            elif resp.reason:
                await ctx.send(f"Failed: ({resp.status})" + resp.reason)

            else:
                await ctx.send("Failed. " + str(resp.status))

    @users.command()
    @commands.is_owner()
    async def reauth(self, ctx: Context, username: str):
        async with self.session.post(self.url + "internal/users/auth", json={"username": username}) as resp:
            if 200 <= resp.status < 300:
                await ctx.send("User has been reauthed")

            elif resp.reason:
                await ctx.send(f"Failed: ({resp.status})" + resp.reason)

            else:
                await ctx.send("Failed. " + str(resp.status))

    @idevision.group(invoke_without_command=True)
    @commands.is_owner()
    async def cdn(self, ctx):
        await ctx.send_help(ctx.command)

    @cdn.command("stats")
    @commands.is_owner()
    async def cdn_stats(self, ctx: Context, user: Optional[str] = None):
        if user:
            async with self.session.get(self.url + f"cdn/user?username={user}") as resp:
                if 200 <= resp.status < 300:
                    data = await resp.json()
                    await ctx.send(f"Image count: {data['upload_count']}. "
                                   f"Most recent upload: <{data['last_upload']}>")
                else:
                    await ctx.send(f"fetching from the api failed: {resp.reason}")
        else:
            async with self.session.get(self.url + "cdn") as resp:
                if 200 <= resp.status < 300:
                    data = await resp.json()
                    await ctx.send(f"Image count: {data['upload_count']}. Count today: {data['uploaded_today']} "
                                   f"Most recent: <{data['last_upload']}>")

                else:
                    await ctx.send(f"fetching from the api failed: {resp.reason}")

    @cdn.command("purge", hidden=True)
    @commands.is_owner()
    async def cdn_purge(self, ctx: Context, user: str):
        async with self.session.post(self.url + "cdn/purge", json={"username": user}) as resp:
            if 200 <= resp.status < 300:
                await ctx.send(f"Purged {user}'s images")
            else:
                await ctx.send(f"Failed to purge: {resp.reason}")

    def _parse_args(self, args):
        url = None
        node = None
        filename = None
        for arg in args:
            if not arg.strip():
                continue

            if URL_RE.match(arg):
                if url:
                    raise commands.UserInputError("You may only pass 1 URL to upload")
                url = arg
            else:
                if node:
                    raise commands.UserInputError("You may only pass 1 node and 1 filename")
                if filename:
                    node = arg
                else:
                    filename = arg

        return url, node, filename

    @cdn.command("upload", usage="[url or attachment] [filename] [node]")
    async def cdn_upload(self, ctx: Context, *args):
        """
        Uploads an image to the cdn on your behalf. You must have an idevision auth token with the `cdn` permission group.
        """
        async with ctx.typing():
            url, node, filename = self._parse_args(args)

            if not ctx.message.attachments and not url:
                return await ctx.send("Provide an attachment or link to an image")

            async with self.session.get(self.url + f"internal/users?discordid={ctx.author.id}") as resp:
                if resp.status == 204:
                    return await ctx.send("Public CDN posting is coming soon... for now you must have an idevision login to use this command")
                elif resp.status != 200:
                    return await ctx.send(f"Something went wrong... {resp.reason}")

                user = await resp.json()
                if not user['administrator'] and 'cdn' not in user['permissions']:
                    return await ctx.send("Public CDN posting is coming soon... currently you are not authorized to use the cdn")

                if node and not user['administrator'] and 'cdn.manage' not in user['permissions']:
                    return await ctx.send("You do not have permission to select the node")

                if filename and not user['administrator'] and 'cdn.manage' not in user['permissions']:
                    return await ctx.send("You do not have permission to select the filename")

            if url:
                fn = url.split("/")[-1]
                async with self.bot.session.get(url, headers={"Accept": "image/*"}) as resp:
                    if resp.content_length > 30000000:
                        return await ctx.send("target URL file is too large")

                    fp = io.BytesIO()
                    fp.write(await resp.read())
                    fp.seek(0)

            else:
                fp = io.BytesIO()
                await ctx.message.attachments[0].save(fp)
                fp.seek(0)
                fn = ctx.message.attachments[0].filename

            data = aiohttp.FormData()
            data.add_field('file',
                           fp,
                           filename=fn)

            url = yarl.URL(self.url + "cdn")
            if node and filename:
                url = url.with_query(node=node, name=filename)
            elif node:
                url = url.with_query(node=node)
            elif filename:
                url = url.with_query(name=filename)

            async with self.session.post(url, data=data, headers={"Authorization": user['auth_key'], "File-Name": fn}) as resp:
                if 200 <= resp.status < 300:
                    d = await resp.json()
                    return await ctx.send(f"Uploaded {fn} to the cdn, at {d['url']}")

                else:
                    await ctx.send(f"There was an error uploading the file: ({resp.status}) {resp.reason}")

    @cdn.command("delete", hidden=True)
    async def cdn_delete(self, ctx: Context, url: str):
        """
        deletes an image from the cdn.
        You may only delete your own images unless you have the `cdn.manage` permission group
        """
        try:
            url_ = yarl.URL(url)
            if url_.host != "cdn.idevision.net":
                return await ctx.send("Not a valid image")
            pth = url_.path.strip("/")
            node, image = pth.split("/")
        except:
            return await ctx.send("Not a valid image")

        async with self.session.get(self.url + f"internal/users?discordid={ctx.author.id}") as resp:
            if resp.status == 204:
                return await ctx.send("You are not authorized to use this command")
            elif resp.status != 200:
                return await ctx.send(f"Something went wrong... {resp.reason}")

            user = await resp.json()
            if not user['administrator'] and 'cdn' not in user['permissions']:
                return await ctx.send("You are not authorized to use this command")

        async with self.session.delete(f"{self.url}cdn/{node}/{image}", headers={"Authorization": user['auth_key']}) as resp:
            if resp.status == 404:
                return await ctx.send("Image not found")

            elif resp.status == 401:
                return await ctx.send(resp.reason)

            elif resp.status == 204:
                return await ctx.send("Image deleted successfully")

            else:
                return await ctx.send(f"Something went wrong: {resp.status}, {resp.reason}")

    @cdn.command("listnode")
    @commands.is_owner()
    async def cdn_listnode(self, ctx: Context, node: str):
        """
        Lists the content of a node
        """
        async with self.session.get(self.url + f"cdn/list?node={node}&sort=nodename") as resp:
            if resp.status != 200:
                return await ctx.send(f"Something fucked up: {resp.status} ({resp.reason})")

            data = await resp.json()
            d = [list(x.values()) for x in data[node]]
            d = tabulate.tabulate(d, headers=list(data[node][-1].keys()), tablefmt="psql")
            pages = paginator.TextPages(ctx, d)
            await pages.paginate()

    @cdn.command("nodes")
    @commands.is_owner()
    async def cdn_nodes(self, ctx: Context, safe=True):
        """
        Lists all nodes
        """
        async with self.session.get(self.url + f"cdn/nodes?safe={safe}") as resp:
            if resp.status != 200:
                return await ctx.send(f"Something fucked up: {resp.status} ({resp.reason})")

            data = await resp.json()

        data = sorted({int(x): y for x, y in data.items()}.items(), key=lambda x: x[0])
        fmt = ""

        for (id, node) in data:
            fmt += f"__Node {id}__\n- Name: {node['name']}\n- Port: {node['port']}\n- Last Contact: {round(node['signin'])} Seconds Ago\n"
            if 'ip' in node:
                fmt += f"- IP: {node['ip']}\n"

            fmt += "\n"

        pages = paginator.TextPages(ctx, fmt, prefix="", suffix="")
        await pages.paginate()

    @idevision.command("homepage")
    async def cdn_homepage(self, ctx: Context,
                       display_name,
                       link1="", link1name="",
                       link2="", link2name="",
                       link3="", link3name="",
                       link4="", link4name=""):
        """
        Allows you to set homepage links for https://idevision.net/homepage
        To access your homepage, go to https://idevision.net/homepage?user={ctx.author.name}
        """
        resp = await self.session.post(self.url + "homepage", json={
            "display_name": display_name,
            "user": ctx.author.name,
            "link1": link1,
            "link2": link2,
            "link3": link3,
            "link4": link4,
            "link1_name": link1name,
            "link2_name": link2name,
            "link3_name": link3name,
            "link4_name": link4name,
        })
        resp.close()
        await ctx.send(f"Page is now available at {self.url.replace('api/', 'homepage')}?user={ctx.author.name}")

    @idevision.command("logs")
    @commands.is_owner()
    async def get_logs(self, ctx: Context, unsafe: Optional[bool], page: Optional[int] = 0, oldest_first: Optional[bool]=False):
        url = yarl.URL(self.url+"internal/logs").with_query({
            "page": str(page),
            "oldest-first": str(oldest_first).lower(),
            "safe": str(unsafe if unsafe is not None else True).lower()
        })
        async with self.session.get(url) as resp:
            if resp.status != 200:
                return await ctx.send("Bad Response")

            data = await resp.json()
            data = data['rows']

        table = tabulate.tabulate([list(x.values()) for x in data], headers=list(data[0].keys()))
        pages = paginator.TextPages(ctx, table)
        await pages.paginate()

    @idevision.group("permissions", aliases=['perms'], invoke_without_command=True)
    @commands.is_owner()
    async def perms(self, ctx):
        async with self.session.get(self.url + "internal/permissions") as resp:
            if resp.status != 200:
                return await ctx.send(f"Bad Response {resp.status, resp.reason}")

            await ctx.send(", ".join((await resp.json())['permissions']))

    @perms.command("routes")
    @commands.is_owner()
    async def routes(self, ctx):
        async with self.session.get(self.url + "internal/routes") as resp:
            if resp.status != 200:
                return await ctx.send(f"Bad Response {resp.status, resp.reason}")

            await ctx.paginate_text(pprint.pformat(await resp.json()))

    @perms.command("add")
    @commands.is_owner()
    async def routes_add(self, ctx: Context, perm: str):
        async with self.session.post(self.url + "internal/permissions", json={"permission": perm}) as resp:
            if resp.status != 204:
                return await ctx.send(f"Failed to add permission: {resp.status, resp.reason}")

            await ctx.send("Success")

    @perms.command("remove")
    @commands.is_owner()
    async def routes_remove(self, ctx: Context, perm: str):
        async with self.session.delete(self.url + "internal/permissions", json={"permission": perm}) as resp:
            if resp.status != 204:
                return await ctx.send(f"Failed to add permission: {resp.status, resp.reason}")

            await ctx.send("Success")

    @perms.command(aliases=['removeroute', 'editroute'])
    @commands.is_owner()
    async def addroute(self, ctx: Context, route: str, method: str, perm: Optional[str] = None, force = False):
        if all((route, method, perm)):
            async with self.session.post(self.url + "internal/routes?force=" + str(force), json={
                "endpoint": route,
                "method": method,
                "permission": perm
            }) as resp:
                if resp.status != 204:
                    return await ctx.send(f"Failed to add route: {resp.status, resp.reason}")

                await ctx.send("Success")

        else:
            async with self.session.delete(self.url + "internal/routes", json={
                "endpoint": route,
                "method": method
            }) as resp:
                if resp.status != 204:
                    return await ctx.send(f"Failed to remove the route: {resp.status, resp.reason}")

                await ctx.send("Success")


    @idevision.command("beta")
    @commands.is_owner()
    async def toggle_beta(self, ctx: Context, state: Optional[bool] = None):
        if state is None:
            return await ctx.send(f"Currently targeting {'beta' if self.url == 'https://beta.idevision.net/api/' else 'production'} idevision site ({self.url.replace('api/', '')})")

        if state:
            self.url = "https://beta.idevision.net/api/"
        else:
            self.url = "https://idevision.net/api/"

        await ctx.send(f"Now targeting {'beta' if self.url == 'https://beta.idevision.net/api/' else 'production'} idevision site ({self.url.replace('api/', '')})")

    @commands.command()
    async def retry(self, ctx: Context):
        """
        yeet
        """
        msg: discord.Message = ctx.message
        if not msg.reference:
            return await ctx.send("Missing a reply")

        if msg.reference.cached_message:
            if not await self.bot.is_owner(ctx.author) and msg.reference.cached_message.author.id != ctx.author.id:
                return await ctx.send("Fuck off")

            await self.bot.process_commands(msg.reference.cached_message)

        else:
            data = await ctx.channel.fetch_message(cast(int, msg.reference.message_id))
            if not await self.bot.is_owner(ctx.author) and data.author.id != ctx.author.id:
                return await ctx.send("Fuck off")

            await self.bot.process_commands(data)