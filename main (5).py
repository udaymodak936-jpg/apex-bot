import os
import json
import random
import asyncio
import datetime
import threading
from collections import defaultdict

import discord
from discord.ext import commands
from flask import Flask

# ---------------------------------------------------------------------------
# SETUP
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

afk_users = {}                     # {user_id: reason}
message_counts = defaultdict(int)  # {user_id: count} -- resets when bot restarts

ROASTS = [
    "If laughter is the best medicine, your face must be curing the whole world.",
    "I'd agree with you, but then we'd both be wrong.",
    "You bring everyone so much joy... when you leave the room.",
    "I'm not saying I hate you, but if you were on fire and I had water, I'd drink it.",
    "Your brain has two cells, and both are fighting for third place.",
    "You're proof that even God makes mistakes sometimes.",
    "I'd roast you, but nature already did.",
    "You have an entire lifetime to be an idiot. Why not take a day off?",
    "Every time you speak, the average IQ of the server drops.",
    "Mirror can't talk, lucky for you, it can't laugh either.",
]

# ---------------------------------------------------------------------------
# PERSISTENT DATA (saved to a local JSON file so it survives restarts as
# long as the server disk isn't wiped by a fresh deploy)
# ---------------------------------------------------------------------------

DATA_FILE = "data.json"


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "warnings": {},     # {user_id: [reasons]}
        "levels": {},       # {user_id: {"xp": int, "level": int}}
        "config": {},       # {guild_id: {"modlog": id, "welcome": id, "leave": id, "autorole": id}}
        "reaction_roles": {},  # {message_id: {emoji: role_id}}
        "economy": {},      # {user_id: {"balance": int, "last_daily": iso_str, "last_work": iso_str}}
    }


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


data = load_data()


def get_guild_config(guild_id):
    return data["config"].setdefault(str(guild_id), {})


# ---------------------------------------------------------------------------
# ECONOMY / CASINO HELPERS
# ---------------------------------------------------------------------------

STARTING_BALANCE = 500
DAILY_AMOUNT = 200
WORK_MIN, WORK_MAX = 50, 150
DAILY_COOLDOWN = datetime.timedelta(hours=24)
WORK_COOLDOWN = datetime.timedelta(hours=1)
ROB_COOLDOWN = datetime.timedelta(hours=2)


def get_account(user_id):
    uid = str(user_id)
    return data["economy"].setdefault(uid, {"balance": STARTING_BALANCE, "last_daily": None, "last_work": None, "last_rob": None})


def get_balance(user_id):
    return get_account(user_id)["balance"]


def add_balance(user_id, amount):
    acct = get_account(user_id)
    acct["balance"] = max(0, acct["balance"] + amount)
    return acct["balance"]


def time_since(iso_str):
    if not iso_str:
        return None
    return datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(iso_str)


def fmt_timedelta(td):
    total = int(td.total_seconds())
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


# ---------------------------------------------------------------------------
# KEEP-ALIVE WEB SERVER
# Render's free plan spins the service down after ~15 min with no HTTP traffic.
# This tiny Flask server gives something to ping. You still need an external
# service (UptimeRobot / cron-job.org) hitting this URL every 5-10 min --
# nothing running inside a sleeping instance can wake itself up.
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/")
def home():
    return "Apex Bot is alive!"


def run_web():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = threading.Thread(target=run_web)
    t.daemon = True
    t.start()


# ---------------------------------------------------------------------------
# EVENTS
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"\u2705 Logged in as {bot.user} ({bot.user.id})")


async def send_modlog(guild: discord.Guild, embed: discord.Embed):
    cfg = get_guild_config(guild.id)
    channel_id = cfg.get("modlog")
    if not channel_id:
        return
    channel = guild.get_channel(int(channel_id))
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass


LEVEL_XP_STEP = 100  # xp needed per level = level * LEVEL_XP_STEP


def add_xp(user_id, amount=10):
    uid = str(user_id)
    entry = data["levels"].setdefault(uid, {"xp": 0, "level": 1})
    entry["xp"] += amount
    leveled_up = False
    needed = entry["level"] * LEVEL_XP_STEP
    while entry["xp"] >= needed:
        entry["xp"] -= needed
        entry["level"] += 1
        leveled_up = True
        needed = entry["level"] * LEVEL_XP_STEP
    return leveled_up, entry["level"]


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    message_counts[message.author.id] += 1

    # remove AFK when the AFK user talks again
    if message.author.id in afk_users:
        del afk_users[message.author.id]
        await message.channel.send(f"\U0001f44b Welcome back {message.author.mention}, I removed your AFK.")

    # notify if someone pings an AFK user
    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            await message.channel.send(f"\U0001f4a4 {mention.name} is AFK: {reason}")

    # leveling / XP
    leveled_up, new_level = add_xp(message.author.id)
    if leveled_up:
        save_data()
        await message.channel.send(f"\U0001f389 {message.author.mention} leveled up to **level {new_level}**!")

    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    cfg = get_guild_config(member.guild.id)

    # welcome message
    channel_id = cfg.get("welcome")
    if channel_id:
        channel = member.guild.get_channel(int(channel_id))
        if channel:
            await channel.send(f"\U0001f44b Welcome to the server, {member.mention}! Glad to have you here.")

    # autorole
    role_id = cfg.get("autorole")
    if role_id:
        role = member.guild.get_role(int(role_id))
        if role:
            try:
                await member.add_roles(role, reason="Autorole on join")
            except discord.Forbidden:
                pass


@bot.event
async def on_member_remove(member: discord.Member):
    cfg = get_guild_config(member.guild.id)
    channel_id = cfg.get("leave")
    if channel_id:
        channel = member.guild.get_channel(int(channel_id))
        if channel:
            await channel.send(f"\U0001f44b **{member.name}** has left the server.")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    mapping = data["reaction_roles"].get(str(payload.message_id))
    if not mapping:
        return
    emoji = str(payload.emoji)
    role_id = mapping.get(emoji)
    if not role_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(int(role_id))
    member = guild.get_member(payload.user_id)
    if role and member:
        try:
            await member.add_roles(role, reason="Reaction role")
        except discord.Forbidden:
            pass


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    mapping = data["reaction_roles"].get(str(payload.message_id))
    if not mapping:
        return
    emoji = str(payload.emoji)
    role_id = mapping.get(emoji)
    if not role_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    role = guild.get_role(int(role_id))
    member = guild.get_member(payload.user_id)
    if role and member:
        try:
            await member.remove_roles(role, reason="Reaction role removed")
        except discord.Forbidden:
            pass


# ---------------------------------------------------------------------------
# GENERAL
# ---------------------------------------------------------------------------

@bot.command()
async def ping(ctx):
    await ctx.send(f"\U0001f3d3 Pong! `{round(bot.latency * 1000)}ms`")


@bot.command()
async def afk(ctx, *, reason: str = "AFK"):
    afk_users[ctx.author.id] = reason
    await ctx.send(f"\U0001f4a4 {ctx.author.mention} is now AFK: **{reason}**")


@bot.command(aliases=["av"])
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"{member.name}'s Avatar", color=discord.Color.blurple())
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def roast(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.send(f"{member.mention} {random.choice(ROASTS)}")


@bot.command()
async def messages(ctx, member: discord.Member = None):
    member = member or ctx.author
    count = message_counts.get(member.id, 0)
    await ctx.send(f"\U0001f4ca {member.mention} has sent **{count}** messages since I last restarted.")


@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"\U0001f4dc {guild.name}", color=discord.Color.green())
    embed.add_field(name="Created On", value=guild.created_at.strftime("%d %b %Y"))
    embed.add_field(name="Owner", value=str(guild.owner))
    embed.add_field(name="Members", value=str(guild.member_count))
    embed.add_field(name="Text Channels", value=str(len(guild.text_channels)))
    embed.add_field(name="Voice Channels", value=str(len(guild.voice_channels)))
    embed.add_field(name="Roles", value=str(len(guild.roles)))
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    await ctx.send(embed=embed)


@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles = [r.mention for r in member.roles if r.name != "@everyone"]
    embed = discord.Embed(title=f"\U0001f464 {member.name}", color=member.color)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%d %b %Y"))
    embed.add_field(name="Account Created", value=member.created_at.strftime("%d %b %Y"))
    embed.add_field(name="Roles", value=", ".join(roles) if roles else "None", inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    entry = data["levels"].get(str(member.id), {"xp": 0, "level": 1})
    needed = entry["level"] * LEVEL_XP_STEP
    embed = discord.Embed(title=f"\U0001f4c8 {member.name}'s Rank", color=discord.Color.gold())
    embed.add_field(name="Level", value=str(entry["level"]))
    embed.add_field(name="XP", value=f"{entry['xp']}/{needed}")
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def leaderboard(ctx):
    ranked = sorted(data["levels"].items(), key=lambda kv: (kv[1]["level"], kv[1]["xp"]), reverse=True)[:10]
    if not ranked:
        await ctx.send("No one has any XP yet \u2014 start chatting!")
        return
    lines = []
    for i, (uid, entry) in enumerate(ranked, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**{i}.** {name} \u2014 Level {entry['level']} ({entry['xp']} XP)")
    embed = discord.Embed(title="\U0001f3c6 Leaderboard", description="\n".join(lines), color=discord.Color.gold())
    await ctx.send(embed=embed)


@bot.command(aliases=["help"])
async def bothelp(ctx):
    embed = discord.Embed(title="\U0001f680 Apex Bot Commands", color=discord.Color.purple())
    embed.add_field(
        name="\U0001f6e0\ufe0f Moderation",
        value=(
            "`!mute @user [time] [reason]`\n"
            "`!unmute @user`\n"
            "`!ban @user [reason]`\n"
            "`!kick @user [reason]`\n"
            "`!warn @user [reason]`\n"
            "`!warnings @user`\n"
            "`!clearwarnings @user`\n"
            "`!clear <amount>`\n"
            "`!slowmode <seconds>`\n"
            "`!lock`\n"
            "`!unlock`\n"
            "`!createchannel <name>`"
        ),
        inline=False,
    )
    embed.add_field(
        name="\u2699\ufe0f Server Setup (Admin)",
        value=(
            "`!setmodlog #channel`\n"
            "`!setwelcome #channel`\n"
            "`!setleave #channel`\n"
            "`!setautorole @role`\n"
            "`!reactionrole <message_id> <emoji> @role`"
        ),
        inline=False,
    )
    embed.add_field(
        name="\U0001f389 Fun & Events",
        value=(
            "`!roast [@user]`\n"
            "`!poll \"question\" option1 option2 ...`\n"
            "`!giveaway <time> <winners> <prize>`"
        ),
        inline=False,
    )
    embed.add_field(
        name="\U0001f3ab Tickets",
        value="`!ticket` \u2014 open a private support ticket\n`!closeticket` \u2014 close it",
        inline=False,
    )
    embed.add_field(
        name="\U0001f3b0 Economy & Casino",
        value=(
            "`!balance [@user]`\n"
            "`!daily`\n"
            "`!work`\n"
            "`!give @user <amount>`\n"
            "`!rob @user`\n"
            "`!coinflip <bet> <heads/tails>`\n"
            "`!dice <bet>`\n"
            "`!slots <bet>`\n"
            "`!roulette <bet> <red/black/green/number>`\n"
            "`!richest`"
        ),
        inline=False,
    )
    embed.add_field(
        name="\U0001f4ac General",
        value=(
            "`!afk [reason]`\n"
            "`!avatar [@user]` (or `!av`)\n"
            "`!messages [@user]`\n"
            "`!serverinfo`\n"
            "`!userinfo [@user]`\n"
            "`!rank [@user]`\n"
            "`!leaderboard`\n"
            "`!ping`\n"
            "`!bothelp` (or `!help`)"
        ),
        inline=False,
    )
    await ctx.send(embed=embed)


# ---------------------------------------------------------------------------
# MODERATION
# ---------------------------------------------------------------------------

def parse_duration(time_str: str):
    """Turn '30s' / '10m' / '2h' / '1d' into a timedelta. Returns None if invalid."""
    if not time_str:
        return None
    unit = time_str[-1].lower()
    try:
        amount = int(time_str[:-1])
    except ValueError:
        return None
    if amount <= 0:
        return None
    if unit == "s":
        return datetime.timedelta(seconds=amount)
    if unit == "m":
        return datetime.timedelta(minutes=amount)
    if unit == "h":
        return datetime.timedelta(hours=amount)
    if unit == "d":
        return datetime.timedelta(days=amount)
    return None


@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, time: str = None, *, reason: str = "No reason provided"):
    if time:
        duration = parse_duration(time)
        if duration is None:
            await ctx.send(
                f"\u274c Invalid time format: `{time}`. Use like `30s`, `10m`, `2h`, or `1d`. "
                f"Example: `!mute @user 30s spamming`"
            )
            return
        label = time
    else:
        duration = datetime.timedelta(minutes=10)
        label = "10m (default)"

    try:
        await member.timeout(duration, reason=reason)
        await ctx.send(f"\U0001f507 {member.mention} muted for **{label}**. Reason: {reason}")
        embed = discord.Embed(title="\U0001f507 Member Muted", color=discord.Color.orange())
        embed.add_field(name="User", value=member.mention)
        embed.add_field(name="Duration", value=label)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention)
        await send_modlog(ctx.guild, embed)
    except discord.Forbidden:
        await ctx.send("\u274c I don't have permission to mute this user (check role position).")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.send(f"\U0001f50a {member.mention} has been unmuted.")
    except discord.Forbidden:
        await ctx.send("\u274c I don't have permission to unmute this user.")


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.ban(reason=reason)
        await ctx.send(f"\U0001f528 {member.mention} has been banned. Reason: {reason}")
        embed = discord.Embed(title="\U0001f528 Member Banned", color=discord.Color.red())
        embed.add_field(name="User", value=str(member))
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention)
        await send_modlog(ctx.guild, embed)
    except discord.Forbidden:
        await ctx.send("\u274c I don't have permission to ban this user.")


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"\U0001f462 {member.mention} has been kicked. Reason: {reason}")
        embed = discord.Embed(title="\U0001f462 Member Kicked", color=discord.Color.orange())
        embed.add_field(name="User", value=str(member))
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention)
        await send_modlog(ctx.guild, embed)
    except discord.Forbidden:
        await ctx.send("\u274c I don't have permission to kick this user.")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    uid = str(member.id)
    data["warnings"].setdefault(uid, []).append(reason)
    save_data()
    count = len(data["warnings"][uid])
    await ctx.send(f"\u26a0\ufe0f {member.mention} has been warned ({count} total). Reason: {reason}")
    embed = discord.Embed(title="\u26a0\ufe0f Member Warned", color=discord.Color.yellow())
    embed.add_field(name="User", value=str(member))
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=str(count))
    embed.add_field(name="Moderator", value=ctx.author.mention)
    await send_modlog(ctx.guild, embed)


@bot.command()
async def warnings(ctx, member: discord.Member = None):
    member = member or ctx.author
    warns = data["warnings"].get(str(member.id), [])
    if not warns:
        await ctx.send(f"\u2705 {member.mention} has no warnings.")
        return
    lines = [f"**{i}.** {reason}" for i, reason in enumerate(warns, start=1)]
    embed = discord.Embed(title=f"\u26a0\ufe0f Warnings for {member.name}", description="\n".join(lines), color=discord.Color.yellow())
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(moderate_members=True)
async def clearwarnings(ctx, member: discord.Member):
    data["warnings"].pop(str(member.id), None)
    save_data()
    await ctx.send(f"\U0001f9f9 Cleared all warnings for {member.mention}.")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    if amount < 1 or amount > 100:
        await ctx.send("\u274c Please choose a number between 1 and 100.")
        return
    deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to include the command message
    msg = await ctx.send(f"\U0001f9f9 Deleted {len(deleted) - 1} messages.")
    await asyncio.sleep(3)
    try:
        await msg.delete()
    except discord.NotFound:
        pass


@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    if seconds < 0 or seconds > 21600:
        await ctx.send("\u274c Seconds must be between 0 and 21600 (6 hours).")
        return
    await ctx.channel.edit(slowmode_delay=seconds)
    if seconds == 0:
        await ctx.send("\U0001f407 Slowmode disabled.")
    else:
        await ctx.send(f"\U0001f40c Slowmode set to {seconds} seconds.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("\U0001f512 This channel has been locked.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("\U0001f513 This channel has been unlocked.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def createchannel(ctx, *, name: str):
    channel = await ctx.guild.create_text_channel(name)
    await ctx.send(f"\u2705 Created channel {channel.mention}")


# ---------------------------------------------------------------------------
# SERVER SETUP (admin config commands)
# ---------------------------------------------------------------------------

@bot.command()
@commands.has_permissions(administrator=True)
async def setmodlog(ctx, channel: discord.TextChannel):
    cfg = get_guild_config(ctx.guild.id)
    cfg["modlog"] = channel.id
    save_data()
    await ctx.send(f"\u2705 Mod-log channel set to {channel.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, channel: discord.TextChannel):
    cfg = get_guild_config(ctx.guild.id)
    cfg["welcome"] = channel.id
    save_data()
    await ctx.send(f"\u2705 Welcome channel set to {channel.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setleave(ctx, channel: discord.TextChannel):
    cfg = get_guild_config(ctx.guild.id)
    cfg["leave"] = channel.id
    save_data()
    await ctx.send(f"\u2705 Leave channel set to {channel.mention}")


@bot.command()
@commands.has_permissions(administrator=True)
async def setautorole(ctx, role: discord.Role):
    cfg = get_guild_config(ctx.guild.id)
    cfg["autorole"] = role.id
    save_data()
    await ctx.send(f"\u2705 Autorole set to {role.mention} (new members get this automatically).")


@bot.command()
@commands.has_permissions(administrator=True)
async def reactionrole(ctx, message_id: int, emoji: str, role: discord.Role):
    key = str(message_id)
    data["reaction_roles"].setdefault(key, {})[emoji] = role.id
    save_data()
    try:
        message = await ctx.channel.fetch_message(message_id)
        await message.add_reaction(emoji)
    except (discord.NotFound, discord.HTTPException):
        await ctx.send("\u26a0\ufe0f Saved, but I couldn't react to that message myself \u2014 react to it manually once.")
        return
    await ctx.send(f"\u2705 Reacting with {emoji} on that message now gives {role.mention}.")


# ---------------------------------------------------------------------------
# FUN & EVENTS: poll, giveaway
# ---------------------------------------------------------------------------

NUMBER_EMOJIS = ["1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3", "5\ufe0f\u20e3", "6\ufe0f\u20e3", "7\ufe0f\u20e3", "8\ufe0f\u20e3", "9\ufe0f\u20e3"]


@bot.command()
async def poll(ctx, question: str, *options: str):
    if len(options) < 2:
        await ctx.send("\u274c Give at least 2 options. Example: `!poll \"Best game?\" Valorant Apex`")
        return
    if len(options) > len(NUMBER_EMOJIS):
        await ctx.send(f"\u274c Max {len(NUMBER_EMOJIS)} options allowed.")
        return

    description = "\n".join(f"{NUMBER_EMOJIS[i]} {opt}" for i, opt in enumerate(options))
    embed = discord.Embed(title=f"\U0001f4ca {question}", description=description, color=discord.Color.blue())
    embed.set_footer(text=f"Poll by {ctx.author.display_name}")
    poll_msg = await ctx.send(embed=embed)
    for i in range(len(options)):
        await poll_msg.add_reaction(NUMBER_EMOJIS[i])


@bot.command()
@commands.has_permissions(manage_guild=True)
async def giveaway(ctx, time: str, winners: int, *, prize: str):
    duration = parse_duration(time)
    if duration is None:
        await ctx.send("\u274c Invalid time format. Use like `30s`, `10m`, `2h`, `1d`.")
        return
    if winners < 1:
        await ctx.send("\u274c Winners must be at least 1.")
        return

    embed = discord.Embed(
        title="\U0001f389 GIVEAWAY \U0001f389",
        description=f"**Prize:** {prize}\nReact with \U0001f389 to enter!\n**Winners:** {winners}\n**Ends in:** {time}",
        color=discord.Color.magenta(),
    )
    embed.set_footer(text=f"Hosted by {ctx.author.display_name}")
    giveaway_msg = await ctx.send(embed=embed)
    await giveaway_msg.add_reaction("\U0001f389")

    await asyncio.sleep(duration.total_seconds())

    giveaway_msg = await ctx.channel.fetch_message(giveaway_msg.id)
    reaction = discord.utils.get(giveaway_msg.reactions, emoji="\U0001f389")
    if reaction is None:
        await ctx.send("\U0001f622 No one entered the giveaway.")
        return

    users = [user async for user in reaction.users() if not user.bot]
    if not users:
        await ctx.send("\U0001f622 No one entered the giveaway.")
        return

    chosen = random.sample(users, min(winners, len(users)))
    winner_mentions = ", ".join(u.mention for u in chosen)
    await ctx.send(f"\U0001f389 Congratulations {winner_mentions}! You won **{prize}**!")


# ---------------------------------------------------------------------------
# TICKET SYSTEM
# ---------------------------------------------------------------------------

@bot.command()
async def ticket(ctx):
    existing = discord.utils.get(ctx.guild.text_channels, name=f"ticket-{ctx.author.name}".lower())
    if existing:
        await ctx.send(f"\u274c You already have an open ticket: {existing.mention}")
        return

    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        ctx.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
    }
    # let anyone with manage_channels (mods) see it too
    for role in ctx.guild.roles:
        if role.permissions.manage_channels:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

    channel = await ctx.guild.create_text_channel(
        f"ticket-{ctx.author.name}", overwrites=overwrites, reason="Support ticket"
    )
    await channel.send(
        f"\U0001f3ab {ctx.author.mention} thanks for opening a ticket! A team member will be with you soon.\n"
        f"Use `!closeticket` here when you're done."
    )
    await ctx.send(f"\u2705 Ticket created: {channel.mention}")


@bot.command()
async def closeticket(ctx):
    if not ctx.channel.name.startswith("ticket-"):
        await ctx.send("\u274c This command only works inside a ticket channel.")
        return
    await ctx.send("\U0001f512 Closing this ticket in 5 seconds...")
    await asyncio.sleep(5)
    await ctx.channel.delete(reason=f"Ticket closed by {ctx.author}")


# ---------------------------------------------------------------------------
# ECONOMY / CASINO (virtual coins only -- not real money)
# ---------------------------------------------------------------------------

@bot.command(aliases=["bal"])
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    bal = get_balance(member.id)
    embed = discord.Embed(
        title=f"\U0001f4b0 {member.display_name}'s Wallet",
        description=f"**{bal}** coins",
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def daily(ctx):
    acct = get_account(ctx.author.id)
    elapsed = time_since(acct["last_daily"])
    if elapsed is not None and elapsed < DAILY_COOLDOWN:
        remaining = DAILY_COOLDOWN - elapsed
        await ctx.send(f"\u23f3 Already claimed. Come back in **{fmt_timedelta(remaining)}**.")
        return
    acct["last_daily"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    add_balance(ctx.author.id, DAILY_AMOUNT)
    save_data()
    await ctx.send(f"\U0001f381 {ctx.author.mention} claimed their daily **{DAILY_AMOUNT}** coins! Balance: **{get_balance(ctx.author.id)}**")


@bot.command()
async def work(ctx):
    acct = get_account(ctx.author.id)
    elapsed = time_since(acct["last_work"])
    if elapsed is not None and elapsed < WORK_COOLDOWN:
        remaining = WORK_COOLDOWN - elapsed
        await ctx.send(f"\u23f3 You're tired. Rest for **{fmt_timedelta(remaining)}** before working again.")
        return
    earned = random.randint(WORK_MIN, WORK_MAX)
    acct["last_work"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    add_balance(ctx.author.id, earned)
    save_data()
    jobs = ["delivered pizzas", "walked dogs", "coded a website", "streamed on Twitch", "sold NFTs (lol)", "fixed a bug"]
    await ctx.send(f"\U0001f4bc {ctx.author.mention} {random.choice(jobs)} and earned **{earned}** coins! Balance: **{get_balance(ctx.author.id)}**")


@bot.command()
async def give(ctx, member: discord.Member, amount: int):
    if amount <= 0:
        await ctx.send("\u274c Amount must be positive.")
        return
    if member.id == ctx.author.id:
        await ctx.send("\u274c You can't give coins to yourself.")
        return
    if get_balance(ctx.author.id) < amount:
        await ctx.send("\u274c You don't have enough coins.")
        return
    add_balance(ctx.author.id, -amount)
    add_balance(member.id, amount)
    save_data()
    await ctx.send(f"\U0001f91d {ctx.author.mention} gave **{amount}** coins to {member.mention}!")


@bot.command()
async def rob(ctx, member: discord.Member):
    if member.id == ctx.author.id:
        await ctx.send("\u274c You can't rob yourself.")
        return
    acct = get_account(ctx.author.id)
    elapsed = time_since(acct.get("last_rob"))
    if elapsed is not None and elapsed < ROB_COOLDOWN:
        remaining = ROB_COOLDOWN - elapsed
        await ctx.send(f"\u23f3 Lay low for **{fmt_timedelta(remaining)}** before robbing again.")
        return
    target_balance = get_balance(member.id)
    if target_balance < 50:
        await ctx.send(f"\u274c {member.mention} is too broke to rob.")
        return
    acct["last_rob"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_data()
    if random.random() < 0.5:
        stolen = random.randint(10, min(200, target_balance))
        add_balance(member.id, -stolen)
        add_balance(ctx.author.id, stolen)
        save_data()
        await ctx.send(f"\U0001f977 {ctx.author.mention} successfully robbed **{stolen}** coins from {member.mention}!")
    else:
        fine = random.randint(20, 100)
        add_balance(ctx.author.id, -fine)
        save_data()
        await ctx.send(f"\U0001f6a8 {ctx.author.mention} got caught and paid a **{fine}** coin fine!")


@bot.command()
async def coinflip(ctx, bet: int, choice: str):
    choice = choice.lower()
    if choice not in ("heads", "tails", "h", "t"):
        await ctx.send("\u274c Choose `heads` or `tails`.")
        return
    if bet <= 0:
        await ctx.send("\u274c Bet must be positive.")
        return
    if get_balance(ctx.author.id) < bet:
        await ctx.send("\u274c You don't have enough coins for that bet.")
        return
    result = random.choice(["heads", "tails"])
    won = (choice.startswith("h") and result == "heads") or (choice.startswith("t") and result == "tails")
    if won:
        add_balance(ctx.author.id, bet)
        save_data()
        await ctx.send(f"\U0001fa99 Landed on **{result}**! You won **{bet}** coins! Balance: **{get_balance(ctx.author.id)}**")
    else:
        add_balance(ctx.author.id, -bet)
        save_data()
        await ctx.send(f"\U0001fa99 Landed on **{result}**. You lost **{bet}** coins. Balance: **{get_balance(ctx.author.id)}**")


@bot.command()
async def dice(ctx, bet: int):
    if bet <= 0:
        await ctx.send("\u274c Bet must be positive.")
        return
    if get_balance(ctx.author.id) < bet:
        await ctx.send("\u274c You don't have enough coins for that bet.")
        return
    player_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)
    if player_roll > bot_roll:
        add_balance(ctx.author.id, bet)
        save_data()
        await ctx.send(f"\U0001f3b2 You rolled **{player_roll}**, I rolled **{bot_roll}**. You won **{bet}** coins!")
    elif player_roll < bot_roll:
        add_balance(ctx.author.id, -bet)
        save_data()
        await ctx.send(f"\U0001f3b2 You rolled **{player_roll}**, I rolled **{bot_roll}**. You lost **{bet}** coins.")
    else:
        await ctx.send(f"\U0001f3b2 You both rolled **{player_roll}**. It's a tie, bet refunded.")


SLOT_SYMBOLS = ["\U0001f352", "\U0001f34b", "\U0001f514", "\U0001f48e", "7\ufe0f\u20e3", "\U0001f340"]


@bot.command()
async def slots(ctx, bet: int):
    if bet <= 0:
        await ctx.send("\u274c Bet must be positive.")
        return
    if get_balance(ctx.author.id) < bet:
        await ctx.send("\u274c You don't have enough coins for that bet.")
        return
    spin = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    display = " | ".join(spin)
    if spin[0] == spin[1] == spin[2]:
        winnings = bet * 10
        add_balance(ctx.author.id, winnings)
        save_data()
        await ctx.send(f"\U0001f3b0 {display}\nJACKPOT! You won **{winnings}** coins!")
    elif spin[0] == spin[1] or spin[1] == spin[2] or spin[0] == spin[2]:
        winnings = bet * 2
        add_balance(ctx.author.id, winnings)
        save_data()
        await ctx.send(f"\U0001f3b0 {display}\nTwo match! You won **{winnings}** coins!")
    else:
        add_balance(ctx.author.id, -bet)
        save_data()
        await ctx.send(f"\U0001f3b0 {display}\nNo match. You lost **{bet}** coins.")


@bot.command()
async def roulette(ctx, bet: int, choice: str):
    choice = choice.lower()
    valid = choice in ("red", "black", "green") or choice.isdigit()
    if not valid:
        await ctx.send("\u274c Choose `red`, `black`, `green`, or a number 0-36.")
        return
    if bet <= 0:
        await ctx.send("\u274c Bet must be positive.")
        return
    if get_balance(ctx.author.id) < bet:
        await ctx.send("\u274c You don't have enough coins for that bet.")
        return

    number = random.randint(0, 36)
    red_numbers = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    color = "green" if number == 0 else ("red" if number in red_numbers else "black")

    won = False
    payout = 0
    if choice.isdigit() and int(choice) == number:
        won = True
        payout = bet * 14
    elif choice == color:
        won = True
        payout = bet * 2 if color != "green" else bet * 14

    if won:
        add_balance(ctx.author.id, payout)
        save_data()
        await ctx.send(f"\U0001f3b1 Ball landed on **{number} ({color})**! You won **{payout}** coins!")
    else:
        add_balance(ctx.author.id, -bet)
        save_data()
        await ctx.send(f"\U0001f3b1 Ball landed on **{number} ({color})**. You lost **{bet}** coins.")


@bot.command()
async def richest(ctx):
    ranked = sorted(data["economy"].items(), key=lambda kv: kv[1]["balance"], reverse=True)[:10]
    if not ranked:
        await ctx.send("No one has any coins yet!")
        return
    lines = []
    for i, (uid, acct) in enumerate(ranked, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**{i}.** {name} \u2014 {acct['balance']} coins")
    embed = discord.Embed(title="\U0001f3c6 Richest Players", description="\n".join(lines), color=discord.Color.gold())
    await ctx.send(embed=embed)


# ---------------------------------------------------------------------------
# ERROR HANDLING (so one bad command doesn't crash the bot)
# ---------------------------------------------------------------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("\u274c You don't have permission to use this command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("\u274c Couldn't find that member.")
    elif isinstance(error, commands.RoleNotFound):
        await ctx.send("\u274c Couldn't find that role.")
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("\u274c Couldn't find that channel.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"\u274c Missing argument: `{error.param.name}`. Check `!bothelp`.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("\u274c One of your arguments looks wrong. Check `!bothelp` for the right format.")
    elif isinstance(error, commands.CommandNotFound):
        return  # ignore unknown commands silently
    else:
        print(f"Unhandled error: {error}")
        await ctx.send("\u26a0\ufe0f Something went wrong running that command.")


# ---------------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set!")
    keep_alive()
    bot.run(token)
