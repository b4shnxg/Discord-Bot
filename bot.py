import os
import re
import json
import math
import random
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.messages = True
INTENTS.message_content = True

BOT_PREFIX = os.getenv("BOT_PREFIX", "!")
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")
THUMB_URL = os.getenv("THUMB_URL", "")
BANNER_URL = os.getenv("BANNER_URL", "")

COLOR_BASE = 0x2B2D31
COLOR_OK = 0x00FF9D
COLOR_WARN = 0xFFCC00
COLOR_ERR = 0xFF4D4D

START_TIME = datetime.utcnow()

bot = commands.Bot(command_prefix=BOT_PREFIX, intents=INTENTS)
bot.remove_command("help")

open_tickets = {}
ticket_cooldown = {}
afk_users = {}
giveaways = {}
gw_records = {}

LEVELS_FILE = "levels.json"
WARN_FILE = "warns.json"
ANTILINK_FILE = "antilink.json"

def _levels_default():
    return {"users": {}}

def load_levels():
    if not os.path.exists(LEVELS_FILE):
        with open(LEVELS_FILE, "w") as f:
            json.dump(_levels_default(), f, indent=4)
    try:
        with open(LEVELS_FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = _levels_default()
    if "users" not in data or not isinstance(data["users"], dict):
        data["users"] = {}
    for uid, u in list(data["users"].items()):
        if "msgs" not in u:
            data["users"][uid] = {"msgs": 0, "level": int(u.get("level", 0))}
    return data

def save_levels():
    with open(LEVELS_FILE, "w") as f:
        json.dump(levels_db, f, indent=4)

def cumulative_msgs_for_level(level: int) -> int:
    return 25 * level * (level + 1)

def msgs_needed_for_next(level: int) -> int:
    return 50 * (level + 1)

def get_user_stats(uid: int):
    uid = str(uid)
    user = levels_db["users"].get(uid)
    if not user:
        user = {"msgs": 0, "level": 0}
        levels_db["users"][uid] = user
    user["msgs"] = int(user.get("msgs", 0))
    user["level"] = int(user.get("level", 0))
    return user

def add_message_and_check_levelup(uid: int):
    user = get_user_stats(uid)
    user["msgs"] += 1
    leveled_up = 0
    while user["msgs"] >= cumulative_msgs_for_level(user["level"] + 1):
        user["level"] += 1
        leveled_up += 1
    save_levels()
    cur_level = user["level"]
    cur_prog = user["msgs"] - cumulative_msgs_for_level(cur_level)
    next_req = msgs_needed_for_next(cur_level)
    return leveled_up, cur_level, cur_prog, next_req, user["msgs"]

def set_level(uid: int, level: int):
    user = get_user_stats(uid)
    level = max(0, int(level))
    user["level"] = level
    user["msgs"] = cumulative_msgs_for_level(level)
    save_levels()

def set_all_zero():
    for uid in list(levels_db["users"].keys()):
        levels_db["users"][uid]["level"] = 0
        levels_db["users"][uid]["msgs"] = 0
    save_levels()

def progress_bar(current: int, total: int, width: int = 20) -> str:
    if total <= 0:
        total = 1
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(width * ratio))
    return "▰" * filled + "▱" * (width - filled)

levels_db = load_levels()

def load_warns():
    if not os.path.exists(WARN_FILE):
        with open(WARN_FILE, "w") as f:
            json.dump({}, f)
    with open(WARN_FILE, "r") as f:
        return json.load(f)

def save_warns():
    with open(WARN_FILE, "w") as f:
        json.dump(warns_db, f, indent=4)

def generate_warn_id():
    from random import randint
    return str(randint(100000, 999999))

warns_db = load_warns()

def _antilink_default():
    return {"enabled": False, "whitelist": []}

def load_antilink():
    if not os.path.exists(ANTILINK_FILE):
        with open(ANTILINK_FILE, "w") as f:
            json.dump(_antilink_default(), f, indent=4)
    with open(ANTILINK_FILE, "r") as f:
        try:
            data = json.load(f)
        except Exception:
            data = _antilink_default()
    if "enabled" not in data:
        data["enabled"] = False
    if "whitelist" not in data or not isinstance(data["whitelist"], list):
        data["whitelist"] = []
    return data

def save_antilink():
    with open(ANTILINK_FILE, "w") as f:
        json.dump(antilink_cfg, f, indent=4)

antilink_cfg = load_antilink()

ANTILINK_PATTERNS = [
    r"https?://\S+",
    r"\bwww\.\S+",
    r"\bdiscord\.gg/\S+",
    r"\bdiscordapp\.com/invite/\S+",
]
antiregex = re.compile("|".join(ANTILINK_PATTERNS), re.IGNORECASE)

def antilink_allowed(member: discord.Member) -> bool:
    if member.guild_permissions.manage_messages or member.guild_permissions.administrator:
        return True
    if str(member.id) in antilink_cfg.get("whitelist", []):
        return True
    return False

def winners_label(n: int) -> str:
    return "1 winner" if n == 1 else f"{n} winners"

def parse_duration(s: str) -> int:
    if not s:
        raise ValueError
    total = 0
    num = ""
    units = {"d": 86400, "h": 3600, "m": 60}
    for ch in s.strip().lower():
        if ch.isdigit():
            num += ch
        elif ch in units and num:
            total += int(num) * units[ch]
            num = ""
        else:
            raise ValueError
    if num or total <= 0:
        raise ValueError
    return total

def fmt_delta(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if not parts:
        parts.append(f"{s}s")
    return " ".join(parts)

def build_gw_description(prize: str, ends_in: str, participants: int, winners: int) -> str:
    return (
        f"Prize: {prize}\n"
        f"🏆 {winners_label(winners)}\n"
        f"⏳ Ends in: {ends_in}\n"
        f"👥 Participants: {participants}\n\n"
        f"Press Join to participate."
    )

class GiveawayView(discord.ui.View):
    def __init__(self, msg_id: int):
        super().__init__(timeout=None)
        self.msg_id = msg_id

    @discord.ui.button(label="Join 🎉", style=discord.ButtonStyle.success, custom_id="gw_join")
    async def join(self, interaction: discord.Interaction, _):
        data = giveaways.get(self.msg_id)
        if not data:
            return await interaction.response.send_message("This giveaway is no longer active.", ephemeral=True)
        uid = interaction.user.id
        if uid in data["participants"]:
            data["participants"].remove(uid)
            text = "You left the giveaway."
        else:
            data["participants"].add(uid)
            text = "You joined the giveaway."
        try:
            msg = interaction.message or await interaction.channel.fetch_message(self.msg_id)
            if msg and msg.embeds:
                embed = msg.embeds[0]
                remaining = max(0, int(data["end"] - datetime.utcnow().timestamp()))
                embed.title = f"Giveaway running — {winners_label(data['winners'])}"
                embed.description = build_gw_description(data["prize"], fmt_delta(remaining), len(data["participants"]), data["winners"])
                await msg.edit(embed=embed, view=self)
        except Exception:
            pass
        await interaction.response.send_message(text, ephemeral=True)

async def end_giveaway(bot_instance, message_id: int, manual=False):
    data = giveaways.pop(message_id, None)
    if not data:
        return
    channel = bot_instance.get_channel(data["channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(message_id)
    except Exception:
        return
    participants = list(data["participants"])
    winners_num = max(1, data["winners"])
    if len(participants) == 0:
        result_text = "No one participated."
        winners = []
    else:
        random.shuffle(participants)
        winners = participants[:winners_num]
        winners_mentions = ", ".join(f"<@{w}>" for w in winners)
        result_text = f"Winner(s): {winners_mentions}"
    rec = gw_records.get(message_id, {"prize": data["prize"], "participants": [], "won": [], "channel_id": data["channel_id"]})
    part_set = set(rec.get("participants", []))
    part_set.update(list(data["participants"]))
    won_set = set(rec.get("won", []))
    won_set.update(winners)
    gw_records[message_id] = {
        "prize": data["prize"],
        "participants": list(part_set),
        "won": list(won_set),
        "channel_id": data["channel_id"]
    }
    embed = msg.embeds[0] if msg.embeds else discord.Embed(color=COLOR_BASE)
    embed.title = f"Giveaway ended — {winners_label(winners_num)}"
    embed.description = f"Prize: {data['prize']}\n{result_text}"
    embed.timestamp = datetime.utcnow()
    await msg.edit(embed=embed, view=None)
    await channel.send(f"Giveaway ended — Prize: {data['prize']}\n{result_text}")

class TicketManageView(discord.ui.View):
    def __init__(self, creator: discord.Member):
        super().__init__(timeout=None)
        self.creator = creator
        self.claimed_by = None
        close_button = discord.ui.Button(label="Close", style=discord.ButtonStyle.danger, emoji="🗑️")
        close_button.callback = self.close_callback
        self.add_item(close_button)
        claim_button = discord.ui.Button(label="Claim", style=discord.ButtonStyle.success, emoji="🛠️")
        claim_button.callback = self.claim_callback
        self.add_item(claim_button)

    async def claim_callback(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Only moderation can claim tickets.", ephemeral=True)
        if self.claimed_by is None:
            self.claimed_by = interaction.user
            await interaction.response.send_message(f"Ticket claimed by {interaction.user.mention}", ephemeral=False)
        else:
            await interaction.response.send_message(f"This ticket is already claimed by {self.claimed_by.mention}", ephemeral=True)

    async def close_callback(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Only moderation can close tickets.", ephemeral=True)
        await interaction.response.send_message("Closing ticket...", ephemeral=True)
        await asyncio.sleep(2)
        user_id = self.creator.id
        open_tickets.pop(user_id, None)
        ticket_cooldown[user_id] = asyncio.get_event_loop().time() + 20
        await interaction.channel.delete(reason="Ticket closed")

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.categories = [
            "category 1",
            "category 2",
            "category 3",
            "category 4",
            "category 5",
            "category 6"
        ]
        for cat in self.categories:
            self.add_item(discord.ui.Button(label=cat, style=discord.ButtonStyle.primary, custom_id=cat))

@bot.command()
@commands.has_permissions(manage_channels=True)
async def ticket(ctx):
    await ctx.message.delete()
    now = asyncio.get_event_loop().time()
    if ticket_cooldown.get(ctx.author.id, 0) > now:
        remaining = int(ticket_cooldown[ctx.author.id] - now)
        return await ctx.send(f"You must wait {remaining} seconds to open another ticket.", delete_after=10)
    embed = discord.Embed(
        title="Ticket Panel",
        description=(
            "Select the type of ticket you need.\n\n"
            "Use tickets responsibly."
        ),
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    view = TicketView()
    await ctx.send(embed=embed, view=view)

@ticket.error
async def ticket_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(f"{ctx.author.mention}, Manage Channels is required.", mention_author=False, delete_after=10)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if not interaction.data or not interaction.data.get("custom_id"):
        return
    category = interaction.data["custom_id"]
    valid_categories = [
        "category 1",
        "category 2",
        "category 3",
        "category 4",
        "category 5",
        "category 6"
    ]
    if category not in valid_categories:
        return
    guild = interaction.guild
    member = interaction.user
    if member.id in open_tickets:
        existing_channel = guild.get_channel(open_tickets[member.id])
        if existing_channel:
            return await interaction.response.send_message(f"You already have an open ticket: {existing_channel.mention}", ephemeral=True)
    now = asyncio.get_event_loop().time()
    if ticket_cooldown.get(member.id, 0) > now:
        remaining = int(ticket_cooldown[member.id] - now)
        return await interaction.response.send_message(f"You must wait {remaining} seconds to open another ticket.", ephemeral=True)
    category_obj = None
    for c in guild.categories:
        if c.name.lower() in {"tickets", "support", "soporte"}:
            category_obj = c
            break
    channel_name = f"{category} | {member.name}"
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    for r in guild.roles:
        if r.permissions.manage_messages or r.permissions.administrator:
            overwrites[r] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    new_channel = await guild.create_text_channel(
        name=channel_name,
        category=category_obj,
        overwrites=overwrites,
        topic=f"Ticket from {member} - {category} ",
        reason=f"Ticket created by {member}"
    )
    open_tickets[member.id] = new_channel.id
    view = TicketManageView(creator=member)
    embed_ticket = discord.Embed(
        title=f"Ticket - {category}",
        description="Choose an option using the buttons below.",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed_ticket.set_thumbnail(url=THUMB_URL)
    role_ping = None
    for r in guild.roles:
        if r.permissions.manage_messages or r.permissions.administrator:
            role_ping = r
            break
    mention_text = role_ping.mention if role_ping else ""
    await new_channel.send(content=f"{member.mention} {mention_text}".strip(), embed=embed_ticket, view=view)
    await interaction.response.send_message(f"Ticket created: {new_channel.mention}", ephemeral=True)

@bot.command(name="help")
async def help_cmd(ctx):
    categories = {
        "🎫 Ticket": {
            f"{BOT_PREFIX}ticket": "Send the ticket panel (only admin can use this)."
        },
        "🧹 Moderation": {
            f"{BOT_PREFIX}purge <amount>": "Delete messages in the channel.",
            f"{BOT_PREFIX}nuke [reason]": "Recreate the channel from scratch.",
            f"{BOT_PREFIX}ban [@user] [reason]": "Ban a user.",
            f"{BOT_PREFIX}kick [@user] [reason]": "Kick a user.",
            f"{BOT_PREFIX}unban <id or name#discrim>": "Unban a user.",
            f"{BOT_PREFIX}warn [@user] [reason]": "Warn a user.",
            f"{BOT_PREFIX}warnings [@user]": "Show a user's warnings.",
            f"{BOT_PREFIX}warnremove <ID>": "Remove a warning by its ID.",
            f"{BOT_PREFIX}lock [#channel]": "Lock a channel.",
            f"{BOT_PREFIX}unlock [#channel]": "Unlock a channel.",
            f"{BOT_PREFIX}slowmode <sec>": "Set channel slowmode.",
            f'{BOT_PREFIX}poll "Question" op1 | op2': "Create a quick poll.",
            f"{BOT_PREFIX}gwstart <duration> <prize> [n]": "Start a giveaway.",
            f"{BOT_PREFIX}gwend": "End an active giveaway.",
            f"{BOT_PREFIX}gwreroll": "Reroll a giveaway.",
            f"{BOT_PREFIX}levelreset": "Reset levels and messages."
        },
        "🧑‍🤝‍🧑 Users": {
            f"{BOT_PREFIX}afk [reason]": "Set your away status.",
            f"{BOT_PREFIX}userinfo [@user]": "User info.",
            f"{BOT_PREFIX}avatar [@user]": "Show avatar.",
            f"{BOT_PREFIX}banner [@user]": "Show banner."
        },
        "ℹ️ Server & Roles": {
            f"{BOT_PREFIX}serverinfo": "Server info.",
            f"{BOT_PREFIX}servericon": "Server icon.",
            f"{BOT_PREFIX}roleinfo [role]": "Role info."
        },
        "🛠️ Utilities": {
            f"{BOT_PREFIX}say <message>": "Make the bot send a message.",
            f"{BOT_PREFIX}ping": "Bot latency.",
            f"{BOT_PREFIX}uptime": "Uptime.",
            f"{BOT_PREFIX}botinfo": "Bot technical info.",
            f"{BOT_PREFIX}embedbuilder": "Create embeds easily."
        },
        "🧷 Antilink": {
            f"{BOT_PREFIX}antilink on": "Enable link filter.",
            f"{BOT_PREFIX}antilink off": "Disable the filter.",
            f"{BOT_PREFIX}antilink status": "Filter status.",
            f"{BOT_PREFIX}antilink whitelist add @user": "Add to whitelist.",
            f"{BOT_PREFIX}antilink whitelist remove @user": "Remove from whitelist.",
            f"{BOT_PREFIX}antilink whitelist list": "List whitelist."
        },
        "🏅 Levels": {
            f"{BOT_PREFIX}rank [@user]": "Your level and progress.",
            f"{BOT_PREFIX}top [n]": "Server leaderboard.",
            f"{BOT_PREFIX}levelset @user <level>": "Set a user's level."
        }
    }

    colors = {
        "🎫 Ticket": 0x1ABC9C,
        "🧹 Moderation": 0xED4245,
        "🧑‍🤝‍🧑 Users": 0x3BA55D,
        "ℹ️ Server & Roles": 0xFEE75C,
        "🛠️ Utilities": 0xEB459E,
        "🧷 Antilink": 0x9B59B6,
        "🏅 Levels": 0x00B8FF
    }

    def avatar_url_safe(member: discord.Member):
        return member.avatar.url if member and member.avatar else None

    def build_divider():
        return "┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈ ┈"

    def build_home_embed() -> discord.Embed:
        cats_list = "\n".join([f"{name}" for name in categories.keys()])
        e = discord.Embed(
            title="Help Center",
            description=(
                f"{build_divider()}\n"
                "Browse the categories to see commands.\n"
                f"{build_divider()}\n\n"
                "Categories\n\n"
                f"{cats_list}\n\n"
                f"{build_divider()}\n"
                "Use the menu below to choose."
            ),
            color=0x57F287,
            timestamp=datetime.utcnow()
        )
        if THUMB_URL:
            e.set_author(name="Help")
            e.set_thumbnail(url=THUMB_URL)
        if BANNER_URL:
            e.set_image(url=BANNER_URL)
        e.set_footer(text=f"Requested by {ctx.author}", icon_url=avatar_url_safe(ctx.author))
        return e

    def build_category_embed(category_name: str, commands_dict: dict) -> discord.Embed:
        e = discord.Embed(
            title=f"{category_name}",
            description=f"{build_divider()}\nAvailable commands:\n{build_divider()}",
            color=colors.get(category_name, COLOR_BASE),
            timestamp=datetime.utcnow()
        )
        for command_text, description in commands_dict.items():
            e.add_field(name=f"{command_text}", value=f"{description}", inline=False)
        if THUMB_URL:
            e.set_thumbnail(url=THUMB_URL)
        e.set_footer(text=f"Requested by {ctx.author}")
        return e

    class CategoryMenu(discord.ui.Select):
        def __init__(self, parent_view, author):
            self.parent_view = parent_view
            self.author = author
            options = [
                discord.SelectOption(
                    label=c.split(' ', 1)[1] if ' ' in c else c,
                    description=f"View {c.split(' ', 1)[1] if ' ' in c else c}",
                    emoji=c.split(' ')[0] if ' ' in c else "🗂️",
                    value=c
                )
                for c in categories.keys()
            ]
            super().__init__(placeholder="Choose a category…", min_values=1, max_values=1, options=options)

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.author.id:
                return await interaction.response.send_message("Only the command invoker can use this menu.", ephemeral=True)
            category = self.values[0]
            embed = build_category_embed(category, categories[category])
            self.parent_view.current_embed = embed
            await interaction.response.edit_message(embed=embed, view=self.parent_view)

    class HelpView(discord.ui.View):
        def __init__(self, author: discord.Member):
            super().__init__(timeout=300)
            self.author = author
            self.current_embed = build_home_embed()
            self.add_item(CategoryMenu(self, author))
            self.add_item(self.HomeButton())
            self.add_item(self.CloseButton())

        async def on_timeout(self):
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(view=self)
            except:
                pass

        class HomeButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="Home", style=discord.ButtonStyle.success, emoji="🏠")

            async def callback(self, interaction: discord.Interaction):
                view: HelpView = self.view
                if interaction.user.id != view.author.id:
                    return await interaction.response.send_message("Only the command invoker can use this button.", ephemeral=True)
                embed = build_home_embed()
                view.current_embed = embed
                await interaction.response.edit_message(embed=embed, view=view)

        class CloseButton(discord.ui.Button):
            def __init__(self):
                super().__init__(label="Close", style=discord.ButtonStyle.danger, emoji="🛑")

            async def callback(self, interaction: discord.Interaction):
                view: HelpView = self.view
                if interaction.user.id != view.author.id:
                    return await interaction.response.send_message("Only the command invoker can close.", ephemeral=True)
                for item in view.children:
                    item.disabled = True
                await interaction.response.edit_message(content="Help closed.", embed=None, view=view)

    view = HelpView(ctx.author)
    msg = await ctx.send(embed=view.current_embed, view=view)
    view.message = msg

@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1:
        return await ctx.send("You must specify an amount greater than 0.", delete_after=5)
    await ctx.message.delete()
    deleted = await ctx.channel.purge(limit=amount)
    authors = [msg.author.mention for msg in deleted if not msg.author.bot]
    unique_authors = list(dict.fromkeys(authors))
    authors_text = ", ".join(unique_authors) or "No user messages"
    embed = discord.Embed(
        title="Purge complete",
        description=f"{len(deleted)} messages deleted.",
        color=COLOR_BASE,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Executed by", value=ctx.author.mention, inline=False)
    embed.add_field(name="Affected authors", value=authors_text, inline=False)
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="nuke")
@commands.has_permissions(manage_channels=True)
async def nuke(ctx, *, reason: str = "No reason"):
    channel = ctx.channel
    data = {
        "position": channel.position,
        "overwrites": channel.overwrites,
        "category": channel.category,
        "name": channel.name,
        "topic": channel.topic,
        "slowmode": channel.slowmode_delay,
        "nsfw": channel.is_nsfw()
    }
    embed_confirm = discord.Embed(
        title="Nuke Confirmation",
        description=f"Are you sure you want to nuke {channel.mention}?",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed_confirm.set_thumbnail(url=THUMB_URL)
    embed_confirm.set_footer(text=f"Requested by {ctx.author}")
    class ConfirmNuke(discord.ui.View):
        def __init__(self, author, message):
            super().__init__(timeout=30)
            self.author = author
            self.message = message
        @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, emoji="✅")
        async def confirm(self, interaction: discord.Interaction, _):
            if interaction.user != self.author:
                await interaction.response.send_message("You didn't run the command.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            try:
                new_channel = await channel.clone(reason=f"Nuke by {self.author}")
                await channel.delete(reason=f"Nuke by {self.author}")
                await new_channel.edit(
                    position=data["position"],
                    overwrites=data["overwrites"],
                    category=data["category"],
                    topic=data["topic"],
                    slowmode_delay=data["slowmode"],
                    nsfw=data["nsfw"]
                )
                embed = discord.Embed(
                    title="Channel restarted",
                    description=f"Channel {new_channel.mention} has been restarted.",
                    color=COLOR_BASE,
                    timestamp=datetime.utcnow()
                )
                if THUMB_URL:
                    embed.set_thumbnail(url=THUMB_URL)
                embed.add_field(name="Executed by", value=self.author.mention, inline=False)
                embed.add_field(name="Reason", value=reason, inline=False)
                await new_channel.send(embed=embed)
                self.stop()
            except Exception as e:
                await ctx.send(f"An error occurred: `{e}`")
        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="🛑")
        async def cancel(self, interaction: discord.Interaction, _):
            if interaction.user != self.author:
                await interaction.response.send_message("You didn't run the command.", ephemeral=True)
                return
            await self.message.delete()
            self.stop()
    message = await ctx.send(embed=embed_confirm)
    view = ConfirmNuke(ctx.author, message)
    await message.edit(view=view)

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, *, arg: str = None):
    member = None
    reason = None
    if ctx.message.reference:
        referenced_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced_msg.author
        reason = arg or "Unspecified"
    else:
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
            mention_text = f"<@{member.id}>"
            reason = arg.replace(mention_text, "").strip() if arg else "Unspecified"
        else:
            return await ctx.send("You must mention a user or reply to their message.", delete_after=5)
    real_reason = f"{reason} • Banned by {ctx.author}"
    try:
        dm_embed = discord.Embed(
            title=f"You have been banned from {ctx.guild.name}",
            description=f"Reason: {reason}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        if THUMB_URL:
            dm_embed.set_thumbnail(url=THUMB_URL)
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass
    try:
        await member.ban(reason=real_reason)
        embed = discord.Embed(title="User banned", color=COLOR_BASE, timestamp=datetime.utcnow())
        embed.add_field(name="User", value=member.mention, inline=False)
        embed.add_field(name="Banned by", value=ctx.author.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed_error = discord.Embed(title="Error", description="Insufficient permission to ban.", color=COLOR_ERR, timestamp=datetime.utcnow())
        await ctx.send(embed=embed_error)
    except discord.HTTPException:
        embed_error = discord.Embed(title="Error", description="I could not ban the user.", color=COLOR_ERR, timestamp=datetime.utcnow())
        await ctx.send(embed=embed_error)

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, *, arg: str = None):
    member = None
    reason = None
    if ctx.message.reference:
        referenced_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        member = referenced_msg.author
        reason = arg or "Unspecified"
    else:
        if ctx.message.mentions:
            member = ctx.message.mentions[0]
            mention_text = f"<@{member.id}>"
            reason = arg.replace(mention_text, "").strip() if arg else "Unspecified"
        else:
            return await ctx.send("You must mention a user or reply to their message.", delete_after=5)
    real_reason = f"{reason} • Kick by {ctx.author}"
    try:
        dm_embed = discord.Embed(
            title=f"You have been kicked from {ctx.guild.name}",
            description=f"Reason: {reason}",
            color=0xffa500,
            timestamp=datetime.utcnow()
        )
        if THUMB_URL:
            dm_embed.set_thumbnail(url=THUMB_URL)
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass
    try:
        await member.kick(reason=real_reason)
        embed = discord.Embed(title="User kicked", color=COLOR_BASE, timestamp=datetime.utcnow())
        embed.add_field(name="User", value=member.mention, inline=False)
        embed.add_field(name="Kicked by", value=ctx.author.mention, inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        await ctx.send(embed=embed)
    except discord.Forbidden:
        embed_error = discord.Embed(title="Error", description="Insufficient permission to kick.", color=COLOR_ERR, timestamp=datetime.utcnow())
        await ctx.send(embed=embed_error)
    except discord.HTTPException:
        embed_error = discord.Embed(title="Error", description="I could not kick the user.", color=COLOR_ERR, timestamp=datetime.utcnow())
        await ctx.send(embed=embed_error)

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, user: str):
    user = user.strip()
    found = False
    async for ban_entry in ctx.guild.bans():
        ban_user = ban_entry.user
        if user == str(ban_user.id) or user.lower() == str(ban_user).lower():
            found = True
            try:
                await ctx.guild.unban(ban_user)
                embed = discord.Embed(title="User unbanned", color=0x2bff00, timestamp=datetime.utcnow())
                embed.add_field(name="User", value=f"{ban_user} ({ban_user.id})", inline=False)
                embed.add_field(name="Unbanned by", value=ctx.author.mention, inline=False)
                if THUMB_URL:
                    embed.set_thumbnail(url=THUMB_URL)
                await ctx.send(embed=embed)
            except discord.Forbidden:
                embed_error = discord.Embed(title="Error", description="Insufficient permission to unban.", color=COLOR_ERR, timestamp=datetime.utcnow())
                await ctx.send(embed=embed_error)
            except discord.HTTPException:
                embed_error = discord.Embed(title="Error", description="I could not unban the user.", color=COLOR_ERR, timestamp=datetime.utcnow())
                await ctx.send(embed=embed_error)
            break
    if not found:
        embed_notfound = discord.Embed(title="User not found", description="Not in the ban list.", color=COLOR_ERR, timestamp=datetime.utcnow())
        await ctx.send(embed=embed_notfound)

@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
async def lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    try:
        await ctx.message.delete()
    except:
        pass
    try:
        await channel.set_permissions(ctx.guild.default_role, send_messages=False)
        embed = discord.Embed(title="Channel locked", description=f"{channel.mention} has been locked.", color=COLOR_BASE, timestamp=datetime.utcnow())
    except discord.Forbidden:
        embed = discord.Embed(title="Error", description="I don't have permission to lock this channel.", color=COLOR_ERR, timestamp=datetime.utcnow())
    await ctx.send(embed=embed)

@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    try:
        await ctx.message.delete()
    except:
        pass
    try:
        await channel.set_permissions(ctx.guild.default_role, send_messages=True)
        embed = discord.Embed(title="Channel unlocked", description=f"{channel.mention} has been unlocked.", color=COLOR_BASE, timestamp=datetime.utcnow())
    except discord.Forbidden:
        embed = discord.Embed(title="Error", description="I don't have permission to unlock this channel.", color=COLOR_ERR, timestamp=datetime.utcnow())
    await ctx.send(embed=embed)

@bot.command(name="roleinfo")
async def roleinfo(ctx, role: discord.Role = None):
    sorted_roles = sorted(ctx.guild.roles, key=lambda r: r.position, reverse=True)
    if role:
        embed = discord.Embed(title=f"Role: {role.name}", color=role.color, timestamp=datetime.utcnow())
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Members", value=len(role.members), inline=True)
        embed.add_field(name="Created at", value=role.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)
        return
    class RolesSelect(discord.ui.Select):
        def __init__(self):
            roles_filtered = []
            for r in sorted_roles:
                if r.name == "@everyone":
                    continue
                if len(r.members) == 0:
                    continue
                human_members = [m for m in r.members if not m.bot]
                bot_members = [m for m in r.members if m.bot]
                if len(human_members) >= 1 or len(bot_members) >= 2:
                    roles_filtered.append(r)
            roles_filtered = roles_filtered[:25]
            options = [
                discord.SelectOption(
                    label=r.name,
                    description=f"{len(r.members)} members",
                    value=str(r.id)
                )
                for r in roles_filtered
            ]
            super().__init__(placeholder="Select a role...", options=options, min_values=1, max_values=1)
        async def callback(self, interaction: discord.Interaction):
            selected_role = discord.utils.get(ctx.guild.roles, id=int(self.values[0]))
            embed = discord.Embed(title=f"Role: {selected_role.name}", color=selected_role.color, timestamp=datetime.utcnow())
            embed.add_field(name="ID", value=selected_role.id, inline=True)
            embed.add_field(name="Members", value=len(selected_role.members), inline=True)
            embed.add_field(name="Created at", value=selected_role.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
            embed.add_field(name="Mentionable", value="Yes" if selected_role.mentionable else "No", inline=True)
            if THUMB_URL:
                embed.set_thumbnail(url=THUMB_URL)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await interaction.response.edit_message(embed=embed, view=self.view)
    class MembersButton(discord.ui.Button):
        def __init__(self):
            super().__init__(label="Members", style=discord.ButtonStyle.primary, emoji="🧩")
        async def callback(self, interaction: discord.Interaction):
            selected_role_id = None
            for item in self.view.children:
                if isinstance(item, discord.ui.Select) and item.values:
                    selected_role_id = int(item.values[0])
            if selected_role_id is None:
                await interaction.response.send_message("Select a role.", ephemeral=True)
                return
            role = discord.utils.get(ctx.guild.roles, id=selected_role_id)
            if not role:
                await interaction.response.send_message("Role not found.", ephemeral=True)
                return
            all_members = [m.mention for m in role.members]
            text = "There are no members in this role." if not all_members else ", ".join(all_members)
            if len(text) > 1900:
                text = text[:1900] + "…"
            await interaction.response.send_message(text, ephemeral=True)
    class RolesView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=180)
            self.add_item(RolesSelect())
            self.add_item(MembersButton())
    embed = discord.Embed(title="Select a role", description="Use the menu to view a role's information.", color=discord.Color.blue(), timestamp=datetime.utcnow())
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed, view=RolesView())

@bot.command(name="userinfo")
async def userinfo(ctx, *, arg: str = None):
    if ctx.message.reference:
        referenced_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        target = referenced_msg.author
    elif ctx.message.mentions:
        target = ctx.message.mentions[0]
    else:
        target = ctx.author
    color = (target.top_role.color if target.top_role and target.top_role.color.value != 0 else discord.Color.from_rgb(43,45,49))
    status_map = {
        discord.Status.online: "🟢 Online",
        discord.Status.idle: "🟠 Idle",
        discord.Status.dnd: "🔴 Do Not Disturb",
        discord.Status.offline: "⚫ Offline",
        discord.Status.invisible: "⚫ Invisible",
    }
    state = status_map.get(target.status, "⚫ Unknown")
    created = target.created_at.strftime("%d/%m/%Y %H:%M:%S")
    joined = target.joined_at.strftime("%d/%m/%Y %H:%M:%S") if target.joined_at else "Unknown"
    top_role = target.top_role.mention if target.top_role else "None"
    is_bot = "Yes" if target.bot else "No"
    boosting = "Yes" if getattr(target, "premium_since", None) else "No"
    embed = discord.Embed(title=f"Information for {target}", color=color, timestamp=datetime.utcnow())
    if target.avatar:
        embed.set_thumbnail(url=target.avatar.url)
    embed.add_field(name="Name", value=target.name, inline=True)
    embed.add_field(name="ID", value=str(target.id), inline=True)
    embed.add_field(name="Mention", value=target.mention, inline=True)
    embed.add_field(name="Status", value=state, inline=True)
    embed.add_field(name="Top role", value=top_role, inline=True)
    embed.add_field(name="Bot?", value=is_bot, inline=True)
    embed.add_field(name="Account created", value=created, inline=False)
    embed.add_field(name="Joined server", value=joined, inline=False)
    embed.add_field(name="Boosting", value=boosting, inline=True)
    try:
        u = await bot.fetch_user(target.id)
        if u.banner:
            embed.set_image(url=u.banner.url)
    except:
        pass
    embed.set_footer(text=f"Requested by {ctx.author}")
    class UserInfoView(discord.ui.View):
        def __init__(self, invoker: discord.Member, target_member: discord.Member):
            super().__init__(timeout=180)
            self.invoker = invoker
            self.target_member = target_member
        @discord.ui.button(label="Roles", style=discord.ButtonStyle.primary, emoji="🧩")
        async def roles_btn(self, interaction: discord.Interaction, _):
            roles = [r.mention for r in sorted(self.target_member.roles, key=lambda r: r.position, reverse=True) if r.name != "@everyone"]
            roles_text = ", ".join(roles) if roles else "No roles."
            e = discord.Embed(title=f"Roles of {self.target_member.display_name}", description=roles_text if len(roles_text) < 4000 else roles_text[:3990] + "…", color=color, timestamp=datetime.utcnow())
            if THUMB_URL:
                e.set_thumbnail(url=THUMB_URL)
            e.set_footer(text=f"Requested by {interaction.user}")
            await interaction.response.send_message(embed=e, ephemeral=True)
        @discord.ui.button(label="Warnings", style=discord.ButtonStyle.danger, emoji="⚠️")
        async def warns_btn(self, interaction: discord.Interaction, _):
            user_warns = warns_db.get(str(self.target_member.id), [])
            if not user_warns:
                desc = "This user has no warnings."
            else:
                lines = []
                for w in user_warns[:10]:
                    mod = interaction.guild.get_member(int(w.get("moderator", 0))) if w.get("moderator") else None
                    mod_txt = mod.mention if mod else f"`{w.get('moderator','?')}`"
                    lines.append(f"• ID: `{w['id']}` — Reason: {w.get('reason','') } — Mod: {mod_txt} — {w.get('date','')}")
                extra = f"\n\n… and {len(user_warns)-10} more." if len(user_warns) > 10 else ""
                desc = "\n".join(lines) + extra
            e = discord.Embed(title=f"Warnings for {self.target_member.display_name}", description=desc, color=COLOR_BASE, timestamp=datetime.utcnow())
            if THUMB_URL:
                e.set_thumbnail(url=THUMB_URL)
            e.set_footer(text=f"Requested by {interaction.user}")
            await interaction.response.send_message(embed=e, ephemeral=False)
        @discord.ui.button(label="Avatar", style=discord.ButtonStyle.secondary, emoji="🖼️")
        async def avatar_btn(self, interaction: discord.Interaction, _):
            if not self.target_member.avatar:
                e = discord.Embed(title="Avatar", description="This user has no custom avatar.", color=COLOR_ERR, timestamp=datetime.utcnow())
            else:
                e = discord.Embed(title=f"Avatar of {self.target_member}", color=color, timestamp=datetime.utcnow())
                e.set_image(url=self.target_member.avatar.url)
            e.set_footer(text=f"Requested by {interaction.user}")
            await interaction.response.send_message(embed=e, ephemeral=True)
        @discord.ui.button(label="Banner", style=discord.ButtonStyle.secondary, emoji="🏞️")
        async def banner_btn(self, interaction: discord.Interaction, _):
            try:
                u = await bot.fetch_user(self.target_member.id)
                if u.banner:
                    e = discord.Embed(title=f"Banner of {self.target_member}", color=color, timestamp=datetime.utcnow())
                    e.set_image(url=u.banner.url)
                else:
                    e = discord.Embed(title="Banner", description="This user has no banner.", color=COLOR_ERR, timestamp=datetime.utcnow())
            except:
                e = discord.Embed(title="Banner", description="Couldn't fetch the banner.", color=COLOR_ERR, timestamp=datetime.utcnow())
            e.set_footer(text=f"Requested by {interaction.user}")
            await interaction.response.send_message(embed=e, ephemeral=True)
    view = UserInfoView(ctx.author, target)
    await ctx.send(embed=embed, view=view)

@bot.command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"Server info: {guild.name}", color=COLOR_BASE, timestamp=datetime.utcnow())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Server ID", value=guild.id, inline=True)
    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="Total members", value=guild.member_count, inline=True)
    embed.add_field(name="Humans", value=len([m for m in guild.members if not m.bot]), inline=True)
    embed.add_field(name="Bots", value=len([m for m in guild.members if m.bot]), inline=True)
    embed.add_field(name="Text channels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="Voice channels", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Emojis", value=len(guild.emojis), inline=True)
    embed.add_field(name="Verification level", value=str(guild.verification_level).title(), inline=True)
    embed.add_field(name="Locale/Region", value=guild.preferred_locale, inline=True)
    embed.add_field(name="Boosts", value=f"{guild.premium_subscription_count} (Tier {guild.premium_tier})", inline=True)
    embed.add_field(name="Created at", value=guild.created_at.strftime("%d/%m/%Y %H:%M:%S"), inline=False)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="warn")
@commands.has_permissions(kick_members=True, ban_members=True, manage_roles=True)
async def warn(ctx, user: discord.Member = None, *, reason=None):
    if not user and ctx.message.reference:
        msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        user = msg.author
    if not user:
        embed = discord.Embed(title="Incorrect usage", description=f"You must mention a user or reply to their message.\nExample: {BOT_PREFIX}warn @user [reason]", color=COLOR_ERR)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(f"{ctx.author.mention}", embed=embed)
        return
    if user.bot:
        embed = discord.Embed(title="Action not allowed", description="You cannot warn bots.", color=COLOR_ERR)
        await ctx.send(f"{ctx.author.mention}", embed=embed)
        return
    if user == ctx.author:
        embed = discord.Embed(title="Invalid action", description="You cannot warn yourself.", color=COLOR_ERR)
        await ctx.send(f"{ctx.author.mention}", embed=embed)
        return
    if reason is None:
        reason = "Unspecified"
    warn_id = generate_warn_id()
    if str(user.id) not in warns_db:
        warns_db[str(user.id)] = []
    warns_db[str(user.id)].append({
        "id": warn_id,
        "moderator": str(ctx.author.id),
        "reason": reason,
        "date": datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")
    })
    save_warns()
    embed = discord.Embed(title="User Warned", color=COLOR_WARN, timestamp=datetime.utcnow())
    embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
    embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Warn ID", value=f"{warn_id}", inline=False)
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="warnings")
async def warnings(ctx, user: discord.Member = None):
    if not user and ctx.message.reference:
        msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        user = msg.author
    user = user or ctx.author
    user_warns = warns_db.get(str(user.id), [])
    embed = discord.Embed(title=f"Warnings for {user.display_name}", color=COLOR_BASE, timestamp=datetime.utcnow())
    if not user_warns:
        embed.description = "This user has no warnings."
    else:
        for w in user_warns:
            mod = ctx.guild.get_member(int(w.get("moderator", 0))) if w.get("moderator") else None
            embed.add_field(
                name=f"ID: {w['id']}",
                value=(f"Moderator: {mod.mention if mod else 'Unknown'}\n"
                       f"Reason: {w.get('reason','')}\n"
                       f"Date: {w.get('date','')}"),
                inline=False
            )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="warnremove")
@commands.has_permissions(kick_members=True, ban_members=True, manage_roles=True)
async def warnremove(ctx, warn_id: str = None):
    if not warn_id:
        embed = discord.Embed(title="Incorrect usage", description=f"You must provide the warn ID.\nExample: {BOT_PREFIX}warnremove 123456", color=COLOR_ERR)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(f"{ctx.author.mention}", embed=embed)
        return
    found = False
    for user_id, warn_list in list(warns_db.items()):
        for w in list(warn_list):
            if w["id"] == warn_id:
                warn_list.remove(w)
                found = True
                if not warn_list:
                    del warns_db[user_id]
                save_warns()
                break
    if not found:
        embed = discord.Embed(title="Not found", description=f"No warning found with ID {warn_id}.", color=COLOR_ERR)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(f"{ctx.author.mention}", embed=embed)
        return
    embed = discord.Embed(title="Warning removed", description=f"The warning with ID {warn_id} has been removed.", color=COLOR_OK, timestamp=datetime.utcnow())
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Action by {ctx.author}")
    await ctx.send(embed=embed)

@bot.group(name="antilink", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antilink_group(ctx):
    await ctx.send(f"Usage: {BOT_PREFIX}antilink on|off|status|whitelist add @user|whitelist remove @user|whitelist list")

@antilink_group.command(name="on")
@commands.has_permissions(administrator=True)
async def antilink_on(ctx):
    antilink_cfg["enabled"] = True
    save_antilink()
    await ctx.send("Antilink enabled.")

@antilink_group.command(name="off")
@commands.has_permissions(administrator=True)
async def antilink_off(ctx):
    antilink_cfg["enabled"] = False
    save_antilink()
    await ctx.send("Antilink disabled.")

@antilink_group.command(name="status")
@commands.has_permissions(administrator=True)
async def antilink_status(ctx):
    st = "Enabled" if antilink_cfg.get("enabled") else "Disabled"
    wl = antilink_cfg.get("whitelist", [])
    wl_txt = ", ".join([f"<@{int(uid)}>" for uid in wl]) if wl else "Empty"
    embed = discord.Embed(title="Antilink Status", color=COLOR_BASE, timestamp=datetime.utcnow())
    embed.add_field(name="Status", value=st, inline=False)
    embed.add_field(name="Whitelist", value=wl_txt, inline=False)
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    await ctx.send(embed=embed)

@antilink_group.group(name="whitelist", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def antilink_whitelist(ctx):
    await ctx.send(f"Usage: {BOT_PREFIX}antilink whitelist add @user | remove @user | list")

@antilink_whitelist.command(name="add")
@commands.has_permissions(administrator=True)
async def antilink_whitelist_add(ctx, member: discord.Member = None):
    if not member:
        return await ctx.send(f"You must mention a user. E.g.: {BOT_PREFIX}antilink whitelist add @user")
    uid = str(member.id)
    if uid not in antilink_cfg["whitelist"]:
        antilink_cfg["whitelist"].append(uid)
        save_antilink()
    await ctx.send(f"{member.mention} added to whitelist.")

@antilink_whitelist.command(name="remove")
@commands.has_permissions(administrator=True)
async def antilink_whitelist_remove(ctx, member: discord.Member = None):
    if not member:
        return await ctx.send(f"You must mention a user. E.g.: {BOT_PREFIX}antilink whitelist remove @user")
    uid = str(member.id)
    if uid in antilink_cfg["whitelist"]:
        antilink_cfg["whitelist"].remove(uid)
        save_antilink()
        return await ctx.send(f"{member.mention} removed from whitelist.")
    await ctx.send("That user is not in the whitelist.")

@antilink_whitelist.command(name="list")
@commands.has_permissions(administrator=True)
async def antilink_whitelist_list(ctx):
    wl = antilink_cfg.get("whitelist", [])
    if not wl:
        return await ctx.send("Whitelist is empty.")
    txt = ", ".join([f"<@{int(uid)}>" for uid in wl])
    await ctx.send(f"Whitelist: {txt}")

@bot.event
async def on_message(message: discord.Message):
    if not message.guild:
        return
    if message.author.bot:
        return
    if message.author.id in afk_users:
        afk_users.pop(message.author.id, None)
        embed = discord.Embed(
            title="AFK cleared",
            description=f"{message.author.mention}, your AFK status has been removed.",
            color=COLOR_OK,
            timestamp=datetime.utcnow()
        )
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text="AFK")
        await message.channel.send(embed=embed, delete_after=10)
    for user in message.mentions:
        if user.id in afk_users:
            info = afk_users[user.id]
            delta = datetime.utcnow() - info["since"]
            total_seconds = int(delta.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            time_str = []
            if hours > 0:
                time_str.append(f"{hours}h")
            if minutes > 0:
                time_str.append(f"{minutes}m")
            time_str.append(f"{seconds}s")
            time_str = " ".join(time_str)
            embed = discord.Embed(
                title=f"{user.display_name} is AFK",
                description=f"Reason: {info['reason']}\nAFK time: {time_str}",
                color=0xffa500,
                timestamp=datetime.utcnow()
            )
            if THUMB_URL:
                embed.set_thumbnail(url=THUMB_URL)
            embed.set_footer(text="AFK")
            await message.channel.send(f"{message.author.mention}", embed=embed, delete_after=20)
    if antilink_cfg.get("enabled") and not antilink_allowed(message.author):
        if antiregex.search(message.content or ""):
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            await message.channel.send(f"{message.author.mention} Links are not allowed here.", delete_after=6)
            return
    try:
        leveled, new_level, cur_prog, next_req, total_msgs = add_message_and_check_levelup(message.author.id)
        if leveled > 0:
            e = discord.Embed(
                title="Level Up",
                description=f"{message.author.mention} is now Level {new_level}",
                color=COLOR_OK,
                timestamp=datetime.utcnow()
            )
            e.add_field(name="Total messages", value=str(total_msgs), inline=True)
            e.add_field(name="Next level in", value=f"{next_req - cur_prog} messages", inline=True)
            if THUMB_URL:
                e.set_thumbnail(url=THUMB_URL)
            await message.channel.send(embed=e)
    except Exception:
        pass
    await bot.process_commands(message)

@bot.command(name="afk")
async def afk(ctx, *, reason: str = "Unspecified"):
    afk_users[ctx.author.id] = {"reason": reason, "since": datetime.utcnow()}
    embed = discord.Embed(title="AFK enabled", description=f"{ctx.author.mention} is now AFK.\nReason: {reason}", color=0xffa500, timestamp=datetime.utcnow())
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="say")
@commands.has_permissions(manage_messages=True)
async def say(ctx, *, message_text: str = None):
    if not message_text:
        notice = await ctx.reply(f"You must write something after the command {BOT_PREFIX}say.", mention_author=False)
        await asyncio.sleep(5)
        await notice.delete()
        return
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        notice = await ctx.reply("I don't have permission to delete your message in this channel.", mention_author=False)
        await asyncio.sleep(5)
        await notice.delete()
    except discord.HTTPException:
        pass
    await ctx.send(message_text)

@say.error
async def say_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="Permission denied",
            description=f"{ctx.author.mention}, you don't have permission to use this command.",
            color=COLOR_ERR
        )
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed, delete_after=10)

@bot.command(name="ping")
async def ping(ctx):
    ws_ms = int(bot.latency * 1000)
    t0 = datetime.utcnow()
    msg = await ctx.send("Measuring latency…")
    t1 = datetime.utcnow()
    api_send_ms = int((t1 - t0).total_seconds() * 1000)
    e0 = datetime.utcnow()
    await msg.edit(content="Calculating…")
    e1 = datetime.utcnow()
    api_edit_ms = int((e1 - e0).total_seconds() * 1000)
    api_ms = (api_send_ms + api_edit_ms) // 2
    embed = discord.Embed(
        title="Pong",
        description=(f"WebSocket: {ws_ms} ms\nAPI: {api_ms} ms\n"),
        color=COLOR_OK,
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await msg.edit(content=None, embed=embed)

@bot.command(name="uptime")
async def uptime(ctx):
    delta: timedelta = datetime.utcnow() - START_TIME
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    pretty = f"{days}d {hours}h {minutes}m {seconds}s"
    embed = discord.Embed(title="Uptime", description=f"The bot has been online for {pretty}.", color=COLOR_BASE, timestamp=datetime.utcnow())
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="botinfo")
async def botinfo(ctx):
    ws_ms = int(bot.latency * 1000)
    mem_txt = "N/A"
    try:
        import psutil, os as _os
        process = psutil.Process(_os.getpid())
        mem_bytes = process.memory_info().rss
        mem_mb = mem_bytes / (1024*1024)
        mem_txt = f"{mem_mb:.1f} MB"
    except Exception:
        pass
    delta: timedelta = datetime.utcnow() - START_TIME
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    pretty = f"{days}d {hours}h {minutes}m {seconds}s"
    embed = discord.Embed(title="Bot Info", color=COLOR_BASE, timestamp=datetime.utcnow())
    embed.add_field(name="WebSocket Latency", value=f"{ws_ms} ms", inline=True)
    embed.add_field(name="Uptime", value=pretty, inline=True)
    embed.add_field(name="Process Memory", value=mem_txt, inline=True)
    embed.add_field(name="Prefix", value=f"`{BOT_PREFIX}`", inline=True)
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    if seconds < 0 or seconds > 21600:
        e = discord.Embed(title="Incorrect usage", description="Slowmode must be between 0 and 21600 seconds.", color=COLOR_ERR, timestamp=datetime.utcnow())
        if THUMB_URL:
            e.set_thumbnail(url=THUMB_URL)
        e.set_footer(text=f"Requested by {ctx.author}")
        return await ctx.send(embed=e)
    await ctx.channel.edit(slowmode_delay=seconds, reason=f"Slowmode by {ctx.author}")
    txt = "disabled" if seconds == 0 else f"set to {seconds}s"
    e = discord.Embed(title="Slowmode updated", description=f"Slowmode has been {txt} in {ctx.channel.mention}.", color=COLOR_BASE, timestamp=datetime.utcnow())
    if THUMB_URL:
        e.set_thumbnail(url=THUMB_URL)
    e.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=e)

@bot.command(name="avatar")
async def avatar(ctx, member: discord.Member = None):
    if ctx.message.reference and not member:
        referenced_message = ctx.message.reference.resolved
        if referenced_message:
            member = referenced_message.author
    member = member or ctx.author
    embed = discord.Embed(title=f"Avatar of {member}", color=COLOR_BASE, timestamp=datetime.utcnow())
    if member.avatar:
        embed.set_image(url=member.avatar.url)
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="banner")
async def banner(ctx, member: discord.Member = None):
    member = member or ctx.author
    user = await bot.fetch_user(member.id)
    if user.banner:
        embed = discord.Embed(title=f"Banner of {member}", color=COLOR_BASE, timestamp=datetime.utcnow())
        embed.set_image(url=user.banner.url)
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        await ctx.send(embed=embed)
    else:
        embed = discord.Embed(title=f"Banner of {member}", description="This user has no banner.", color=COLOR_ERR, timestamp=datetime.utcnow())
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        await ctx.send(embed=embed)

@bot.command(name="gwstart")
async def gwstart(ctx, duration: str = None, *, rest: str = None):
    mod_ok = ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.administrator
    if not mod_ok:
        return await ctx.send(f"{ctx.author.mention}, you don't have permission to use this command.", delete_after=10)
    usage = f"Usage: {BOT_PREFIX}gwstart <duration> <prize> [winners]\nExamples:\n{BOT_PREFIX}gwstart 1h Key\n{BOT_PREFIX}gwstart 2d3h VIP 3"
    if not duration or not rest:
        return await ctx.send(usage)
    parts = rest.strip().split()
    winners = 1
    if parts and parts[-1].isdigit():
        winners = int(parts[-1])
        prize = " ".join(parts[:-1]).strip()
    else:
        prize = " ".join(parts).strip()
    if not prize:
        return await ctx.send(usage)
    try:
        seconds = parse_duration(duration)
    except ValueError:
        return await ctx.send("Invalid duration. Use d, h, m. E.g.: 1d2h30m.\n" + usage)
    end_at = datetime.utcnow().timestamp() + seconds
    ends_text = fmt_delta(seconds)
    embed = discord.Embed(
        title=f"Giveaway running — {winners_label(winners)}",
        description=build_gw_description(prize, ends_text, 0, winners),
        color=COLOR_BASE, timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    msg = await ctx.send(embed=embed, view=GiveawayView(0))
    giveaways[msg.id] = {
        "end": end_at, "prize": prize, "winners": winners,
        "participants": set(), "channel_id": ctx.channel.id,
    }
    await msg.edit(view=GiveawayView(msg.id))

@bot.command(name="gwend")
async def gwend(ctx):
    mod_ok = ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.administrator
    if not mod_ok:
        return await ctx.send(f"{ctx.author.mention}, you don't have permission to use this command.", delete_after=10)
    usage = f"Usage: reply to the giveaway message with {BOT_PREFIX}gwend"
    if not ctx.message.reference:
        return await ctx.send("You must reply to the giveaway message.\n" + usage)
    try:
        ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    except Exception:
        return await ctx.send("Couldn't read the referenced message.\n" + usage)
    if ref_msg.id not in giveaways:
        return await ctx.send("That message is not an active giveaway.\n" + usage)
    await end_giveaway(bot, ref_msg.id, manual=True)
    await ctx.message.add_reaction("✅")

@bot.command(name="gwreroll")
async def gwreroll(ctx):
    mod_ok = ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.administrator
    if not mod_ok:
        return await ctx.send(f"{ctx.author.mention}, you don't have permission to use this command.", delete_after=10)
    usage = f"Usage: reply to the ended giveaway message with {BOT_PREFIX}gwreroll"
    if not ctx.message.reference:
        return await ctx.send("You must reply to the giveaway message.\n" + usage)
    try:
        ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
    except Exception:
        return await ctx.send("Couldn't read the referenced message.\n" + usage)
    rec = gw_records.get(ref_msg.id)
    if not rec:
        return await ctx.send("I can't find data for that giveaway.", delete_after=10)
    participants = [uid for uid in rec.get("participants", []) if isinstance(uid, int) or str(uid).isdigit()]
    won = set([uid for uid in rec.get("won", []) if isinstance(uid, int) or str(uid).isdigit()])
    pool = [uid for uid in participants if int(uid) not in won]
    if not pool:
        return await ctx.send("No participants available for reroll.", delete_after=10)
    new_winner = random.choice(pool)
    won.add(int(new_winner))
    rec["won"] = list(won)
    gw_records[ref_msg.id] = rec
    mention = f"<@{int(new_winner)}>"
    prize = rec.get("prize", "Prize")
    await ctx.send(f"Reroll for giveaway {ref_msg.jump_url}\nNew winner: {mention}\nPrize: {prize}")

class PollView(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=300)
        self.votes = {opt: set() for opt in options}
        for opt in options[:5]:
            self.add_item(discord.ui.Button(label=opt, style=discord.ButtonStyle.primary, custom_id=opt))
    @discord.ui.button(label="End", style=discord.ButtonStyle.danger, custom_id="__end", row=1)
    async def end(self, interaction: discord.Interaction, _):
        results = "\n".join(f"• {k} — {len(v)} vote(s)" for k, v in self.votes.items())
        await interaction.response.edit_message(content=f"Results:\n{results}", view=None, embed=None)
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cid = interaction.data.get("custom_id")
        if cid and cid in self.votes:
            for s in self.votes.values():
                s.discard(interaction.user.id)
            self.votes[cid].add(interaction.user.id)
            await interaction.response.send_message(f"You voted for {cid}", ephemeral=True)
        return False

@bot.command(name="poll")
async def poll(ctx, *, data: str = None):
    mod_ok = ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.administrator
    if not mod_ok:
        return await ctx.send(f"{ctx.author.mention}, you don't have permission to use this command.", delete_after=10)
    if not data or '"' not in data:
        return await ctx.send(f'Usage: {BOT_PREFIX}poll "Question" option1 | option2 | option3')
    try:
        q = data.split('"', 2)[1]
        opts_raw = data.split('"', 2)[2].strip()
        options = [o.strip() for o in opts_raw.split("|") if o.strip()]
    except Exception:
        return await ctx.send(f'Usage: {BOT_PREFIX}poll "Question" option1 | option2 | option3')
    if len(options) < 2:
        return await ctx.send("You must provide at least 2 options.")
    if len(options) > 5:
        options = options[:5]
    view = PollView(options)
    embed = discord.Embed(title=f"{q}", description="\n".join(f"• {o}" for o in options), color=COLOR_BASE, timestamp=datetime.utcnow())
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    await ctx.send(embed=embed, view=view)

@bot.command(name="servericon")
async def servericon(ctx):
    icon = ctx.guild.icon.url if ctx.guild.icon else None
    if not icon:
        return await ctx.send("This server has no icon set.")
    embed = discord.Embed(
        title=f"Icon of {ctx.guild.name}",
        color=COLOR_BASE,
        timestamp=datetime.utcnow()
    )
    embed.set_image(url=icon)
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Requested by {ctx.author}")
    await ctx.send(embed=embed)

class EmbedBuilderView(discord.ui.View):
    def __init__(self, author: discord.Member):
        super().__init__(timeout=600)
        self.author = author
        self.embed = discord.Embed(
            title="(no title)",
            description="(no description)",
            color=COLOR_BASE,
            timestamp=datetime.utcnow()
        )
        self.embed.set_footer(text="Embed")
        self.preview_msg = None
        self.timestamp_enabled = True
    async def send_preview(self, interaction: discord.Interaction):
        try:
            if not self.preview_msg:
                self.preview_msg = await interaction.channel.send(embed=self.embed)
            else:
                await self.preview_msg.edit(embed=self.embed)
        except Exception:
            pass
    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("Only the person who started the builder can use it.", ephemeral=True)
            return False
        return True
    @discord.ui.button(label="Title", style=discord.ButtonStyle.primary, row=0)
    async def set_title(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Type the embed title.", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        self.embed.title = msg.content[:256]
        try: await msg.delete()
        except: pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Description", style=discord.ButtonStyle.primary, row=0)
    async def set_desc(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Type the embed description.", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        self.embed.description = msg.content[:4096]
        try: await msg.delete()
        except: pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Color", style=discord.ButtonStyle.secondary, row=0)
    async def set_color(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Send a HEX color, e.g. #2B2D31.", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        try:
            color_hex = int(msg.content.strip().lstrip("#"), 16)
            self.embed.color = discord.Color(color_hex)
            try: await msg.delete()
            except: pass
            await self.send_preview(interaction)
        except ValueError:
            await interaction.followup.send("Invalid color. Use HEX.", ephemeral=True)
    @discord.ui.button(label="Thumbnail", style=discord.ButtonStyle.secondary, row=1)
    async def set_thumbnail(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Send a link or image for the thumbnail.", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        url = msg.attachments[0].url if msg.attachments else msg.content.strip()
        self.embed.set_thumbnail(url=url)
        try: await msg.delete()
        except: pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Image", style=discord.ButtonStyle.secondary, row=1)
    async def set_image(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Send a link or the main image.", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        url = msg.attachments[0].url if msg.attachments else msg.content.strip()
        self.embed.set_image(url=url)
        try: await msg.delete()
        except: pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Title URL", style=discord.ButtonStyle.secondary, row=1)
    async def set_title_url(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Send the URL to link the title.", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        self.embed.url = msg.content.strip()
        try: await msg.delete()
        except: pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Field (+)", style=discord.ButtonStyle.success, row=2)
    async def add_field(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Type the field name.", ephemeral=True)
        name_msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        await interaction.followup.send("Type the field value.", ephemeral=True)
        value_msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        self.embed.add_field(name=name_msg.content[:256], value=value_msg.content[:1024], inline=False)
        try:
            await name_msg.delete()
            await value_msg.delete()
        except:
            pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Clear fields", style=discord.ButtonStyle.secondary, row=2)
    async def clear_fields(self, interaction: discord.Interaction, _):
        self.embed.clear_fields()
        await interaction.response.send_message("All fields have been cleared.", ephemeral=True)
        await self.send_preview(interaction)
    @discord.ui.button(label="Footer", style=discord.ButtonStyle.secondary, row=2)
    async def set_footer(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Type the footer text (or 'clear').", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        txt = msg.content.strip()
        if txt.lower() == "clear":
            self.embed.set_footer(text=None, icon_url=None)
        else:
            self.embed.set_footer(text=txt[:2048])
        try: await msg.delete()
        except: pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Author", style=discord.ButtonStyle.secondary, row=3)
    async def set_author(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Type the author name (or 'clear'). You may attach an icon.", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        name = msg.content.strip()
        icon = msg.attachments[0].url if msg.attachments else None
        if name.lower() == "clear":
            self.embed.set_author(name=None, url=None, icon_url=None)
        else:
            self.embed.set_author(name=name[:256], icon_url=icon)
        try: await msg.delete()
        except: pass
        await self.send_preview(interaction)
    @discord.ui.button(label="Timestamp ON/OFF", style=discord.ButtonStyle.secondary, row=3)
    async def toggle_timestamp(self, interaction: discord.Interaction, _):
        self.timestamp_enabled = not self.timestamp_enabled
        self.embed.timestamp = datetime.utcnow() if self.timestamp_enabled else None
        await interaction.response.send_message(f"Timestamp {'enabled' if self.timestamp_enabled else 'disabled'}.", ephemeral=True)
        await self.send_preview(interaction)
    @discord.ui.button(label="Send", style=discord.ButtonStyle.success, row=3)
    async def send_final(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Mention the channel or type its ID/name:", ephemeral=True)
        msg = await bot.wait_for("message", check=lambda m: m.author == interaction.user and m.channel == interaction.channel)
        arg = (msg.content or "").strip()
        chan = None
        m = re.search(r"<#(\d+)>", arg)
        if m:
            cid = int(m.group(1))
            chan = interaction.guild.get_channel(cid)
        if chan is None and arg.isdigit():
            chan = interaction.guild.get_channel(int(arg))
        if chan is None and arg:
            name = arg.lstrip("#").strip()
            chan = discord.utils.get(interaction.guild.text_channels, name=name)
        if chan is None:
            m2 = re.search(r"/channels/\d+/(\d+)", arg)
            if m2:
                cid = int(m2.group(1))
                chan = interaction.guild.get_channel(cid)
        if chan is None:
            await interaction.followup.send("Invalid or not found channel.", ephemeral=True)
            try: await msg.delete()
            except: pass
            return
        perms = chan.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages):
            await interaction.followup.send(f"I don't have permissions in {chan.mention}.", ephemeral=True)
            try: await msg.delete()
            except: pass
            return
        await chan.send(embed=self.embed)
        await interaction.followup.send(f"Embed sent to {chan.mention}.", ephemeral=True)
        try: await msg.delete()
        except: pass
        self.stop()
        if self.preview_msg:
            try: await self.preview_msg.delete()
            except: pass
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except:
            pass
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=3)
    async def cancel(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("Embed creation canceled.", ephemeral=True)
        if self.preview_msg:
            try: await self.preview_msg.delete()
            except: pass
        self.stop()
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except:
            pass

@bot.command(name="embedbuilder")
@commands.has_permissions(manage_messages=True)
async def embedbuilder(ctx):
    embed = discord.Embed(
        title="Embed Builder",
        description="Use the buttons to build an embed step by step.",
        color=COLOR_BASE,
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    view = EmbedBuilderView(ctx.author)
    await ctx.send(embed=embed, view=view)

@embedbuilder.error
async def embedbuilder_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="Permission denied",
            description=f"{ctx.author.mention}, Manage Messages is required.",
            color=COLOR_ERR,
            timestamp=datetime.utcnow()
        )
        if THUMB_URL:
            embed.set_thumbnail(url=THUMB_URL)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed, delete_after=10)

@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel
    if not channel:
        for c in member.guild.text_channels:
            if c.permissions_for(member.guild.me).send_messages:
                channel = c
                break
    if not channel:
        return
    embed = discord.Embed(
        title="Welcome",
        description=f"Hi {member.mention}, welcome to the server.",
        color=COLOR_BASE,
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    await channel.send(content=f"Welcome {member.mention}", embed=embed)

async def _gw_updater():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now_ts = datetime.utcnow().timestamp()
        to_end = []
        for mid, data in list(giveaways.items()):
            remaining = int(data["end"] - now_ts)
            if remaining <= 0:
                to_end.append(mid)
                continue
            try:
                channel = bot.get_channel(data["channel_id"])
                if not channel:
                    continue
                msg = await channel.fetch_message(mid)
                if not msg or not msg.embeds:
                    continue
                embed = msg.embeds[0]
                embed.title = f"Giveaway running — {winners_label(data['winners'])}"
                embed.description = build_gw_description(data["prize"], fmt_delta(remaining), len(data["participants"]), data["winners"])
                await msg.edit(embed=embed, view=GiveawayView(mid))
            except Exception:
                pass
        for mid in to_end:
            try:
                await end_giveaway(bot, mid)
            except Exception:
                pass
        await asyncio.sleep(30)

@bot.command(name="rank")
async def rank_cmd(ctx, member: discord.Member = None):
    member = member or ctx.author
    if member.bot:
        return await ctx.send("Bots don't have levels.")
    stats = get_user_stats(member.id)
    cur_level = stats["level"]
    total_msgs = stats["msgs"]
    needed_next = msgs_needed_for_next(cur_level)
    cur_prog = total_msgs - cumulative_msgs_for_level(cur_level)
    bar = progress_bar(cur_prog, needed_next, 20)
    embed = discord.Embed(
        title=f"Level of {member.display_name}",
        color=COLOR_BASE,
        timestamp=datetime.utcnow()
    )
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    elif THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.add_field(name="Level", value=f"{cur_level}", inline=True)
    embed.add_field(name="Total messages", value=f"{total_msgs}", inline=True)
    embed.add_field(name="Progress", value=f"{bar}\n{cur_prog}/{needed_next}", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="top")
async def top_cmd(ctx, n: int = 10):
    n = max(1, min(25, n))
    pairs = []
    for uid_str, data in levels_db.get("users", {}).items():
        try:
            uid = int(uid_str)
        except:
            continue
        member = ctx.guild.get_member(uid)
        if member and not member.bot:
            lvl = int(data.get("level", 0))
            total_msgs = int(data.get("msgs", 0))
            cur_prog = total_msgs - cumulative_msgs_for_level(lvl)
            req = msgs_needed_for_next(lvl)
            score = lvl + (cur_prog / req if req > 0 else 0)
            pairs.append((member, lvl, total_msgs, cur_prog, req, score))
    pairs.sort(key=lambda x: x[5], reverse=True)
    top_list = pairs[:n]
    if not top_list:
        return await ctx.send("No level data yet.")
    lines = []
    pos = 1
    for m, lvl, total_msgs, cur_prog, req, score in top_list:
        lines.append(f"#{pos} — {m.mention} • Level {lvl} — {cur_prog}/{req} (Total {total_msgs})")
        pos += 1
    embed = discord.Embed(
        title=f"Top {len(top_list)} — Levels",
        description="\n".join(lines),
        color=COLOR_BASE,
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    await ctx.send(embed=embed)

@bot.command(name="levelset")
@commands.has_permissions(administrator=True)
async def levelset_cmd(ctx, member: discord.Member = None, level: int = None):
    if not member or level is None:
        return await ctx.send(f"Usage: {BOT_PREFIX}levelset @user <level>")
    if member.bot:
        return await ctx.send("You can't set levels for bots.")
    set_level(member.id, int(level))
    embed = discord.Embed(
        title="Level updated",
        description=f"{member.mention} is now Level {int(level)}",
        color=COLOR_OK,
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    embed.set_footer(text=f"Updated by {ctx.author}")
    await ctx.send(embed=embed)

@bot.command(name="levelreset")
@commands.has_permissions(administrator=True)
async def levelreset_cmd(ctx):
    embed = discord.Embed(
        title="Confirm level reset",
        description="This will set to 0 the level and messages of all users stored by the bot. Irreversible action.",
        color=COLOR_WARN,
        timestamp=datetime.utcnow()
    )
    if THUMB_URL:
        embed.set_thumbnail(url=THUMB_URL)
    class ConfirmResetView(discord.ui.View):
        def __init__(self, author):
            super().__init__(timeout=30)
            self.author = author
        @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="🗑️")
        async def confirm(self, interaction: discord.Interaction, _):
            if interaction.user != self.author:
                return await interaction.response.send_message("Only the command invoker can confirm.", ephemeral=True)
            set_all_zero()
            ok = discord.Embed(
                title="Reset completed",
                description="All levels and messages have been reset to 0.",
                color=COLOR_OK,
                timestamp=datetime.utcnow()
            )
            if THUMB_URL:
                ok.set_thumbnail(url=THUMB_URL)
            await interaction.response.edit_message(embed=ok, view=None)
        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="🚫")
        async def cancel(self, interaction: discord.Interaction, _):
            if interaction.user != self.author:
                return await interaction.response.send_message("Only the command invoker can cancel.", ephemeral=True)
            await interaction.response.edit_message(content="Operation canceled.", embed=None, view=None)
    await ctx.send(embed=embed, view=ConfirmResetView(ctx.author))

@bot.event
async def on_ready():
    print(f"bot is online")
    await bot.change_presence(status=discord.Status.dnd, activity=discord.Game(name=f"{BOT_PREFIX}help"))
    bot.loop.create_task(_gw_updater())

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
