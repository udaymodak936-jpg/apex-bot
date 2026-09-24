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
    }


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


data = load_data()


def get_guild_config(guild_id):
    return data["config"].setdefault(str(guild_id), {})


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
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")


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
        await message.channel.send(f"👋 Welcome back {message.author.mention}, I removed your AFK.")

    # notify if someone pings an AFK user
    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            await message.channel.send(f"💤 {mention.name} is AFK: {reason}")

    # leveling / XP
    leveled_up, new_level = add_xp(message.author.id)
    if leveled_up:
        save_data()
        await message.channel.send(f"🎉 {message.author.mention} leveled up to **level {new_level}**!")

    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
    cfg = get_guild_config(member.guild.id)

    # welcome message
    channel_id = cfg.get("welcome")
    if channel_id:
        channel = member.guild.get_channel(int(channel_id))
        if channel:
            await channel.send(f"👋 Welcome to the server, {member.mention}! Glad to have you here.")

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
            await channel.send(f"👋 **{member.name}** has left the server.")


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
    await ctx.send(f"🏓 Pong! `{round(bot.latency * 1000)}ms`")


@bot.command()
async def afk(ctx, *, reason: str = "AFK"):
    afk_users[ctx.author.id] = reason
    await ctx.send(f"💤 {ctx.author.mention} is now AFK: **{reason}**")


@bot.command()
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
    await ctx.send(f"📊 {member.mention} has sent **{count}** messages since I last restarted.")


@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"📜 {guild.name}", color=discord.Color.green())
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
    embed = discord.Embed(title=f"👤 {member.name}", color=member.color)
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
    embed = discord.Embed(title=f"📈 {member.name}'s Rank", color=discord.Color.gold())
    embed.add_field(name="Level", value=str(entry["level"]))
    embed.add_field(name="XP", value=f"{entry['xp']}/{needed}")
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command()
async def leaderboard(ctx):
    ranked = sorted(data["levels"].items(), key=lambda kv: (kv[1]["level"], kv[1]["xp"]), reverse=True)[:10]
    if not ranked:
        await ctx.send("No one has any XP yet — start chatting!")
        return
    lines = []
    for i, (uid, entry) in enumerate(ranked, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        lines.append(f"**{i}.** {name} — Level {entry['level']} ({entry['xp']} XP)")
    embed = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines), color=discord.Color.gold())
    await ctx.send(embed=embed)


@bot.command()
async def bothelp(ctx):
    embed = discord.Embed(title="🚀 Apex Bot Commands", color=discord.Color.purple())
    embed.add_field(
        name="🛠️ Moderation",
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
        name="⚙️ Server Setup (Admin)",
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
        name="🎉 Fun & Events",
        value=(
            "`!roast [@user]`\n"
            "`!poll \"question\" option1 option2 ...`\n"
            "`!giveaway <time> <winners> <prize>`"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎫 Tickets",
        value="`!ticket` — open a private support ticket\n`!closeticket` — close it",
        inline=False,
    )
    embed.add_field(
        name="💬 General",
        value=(
            "`!afk [reason]`\n"
            "`!avatar [@user]`\n"
            "`!messages [@user]`\n"
            "`!serverinfo`\n"
            "`!userinfo [@user]`\n"
            "`!rank [@user]`\n"
            "`!leaderboard`\n"
            "`!ping`\n"
            "`!bothelp`"
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
                f"❌ Invalid time format: `{time}`. Use like `30s`, `10m`, `2h`, or `1d`. "
                f"Example: `!mute @user 30s spamming`"
            )
            return
        label = time
    else:
        duration = datetime.timedelta(minutes=10)
        label = "10m (default)"

    try:
        await member.timeout(duration, reason=reason)
        await ctx.send(f"🔇 {member.mention} muted for **{label}**. Reason: {reason}")
        embed = discord.Embed(title="🔇 Member Muted", color=discord.Color.orange())
        embed.add_field(name="User", value=member.mention)
        embed.add_field(name="Duration", value=label)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention)
        await send_modlog(ctx.guild, embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to mute this user (check role position).")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        await ctx.send(f"🔊 {member.mention} has been unmuted.")
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to unmute this user.")


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.ban(reason=reason)
        await ctx.send(f"🔨 {member.mention} has been banned. Reason: {reason}")
        embed = discord.Embed(title="🔨 Member Banned", color=discord.Color.red())
        embed.add_field(name="User", value=str(member))
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention)
        await send_modlog(ctx.guild, embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to ban this user.")


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member.mention} has been kicked. Reason: {reason}")
        embed = discord.Embed(title="👢 Member Kicked", color=discord.Color.orange())
        embed.add_field(name="User", value=str(member))
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Moderator", value=ctx.author.mention)
        await send_modlog(ctx.guild, embed)
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to kick this user.")


@bot.command()
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    uid = str(member.id)
    data["warnings"].setdefault(uid, []).append(reason)
    save_data()
    count = len(data["warnings"][uid])
    await ctx.send(f"⚠️ {member.mention} has been warned ({count} total). Reason: {reason}")
    embed = discord.Embed(title="⚠️ Member Warned", color=discord.Color.yellow())
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
        await ctx.send(f"✅ {member.mention} has no warnings.")
        return
    lines = [f"**{i}.** {reason}" for i, reason in enumerate(warns, start=1)]
    embed = discord.Embed(title=f"⚠️ Warnings for {member.name}", description="\n".join(lines), color=discord.Color.yellow())
    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(moderate_members=True)
async def clearwarnings(ctx, member: discord.Member):
    data["warnings"].pop(str(member.id), None)
    save_data()
    await ctx.send(f"🧹 Cleared all warnings for {member.mention}.")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    if amount < 1 or amount > 100:
        await ctx.send("❌ Please choose a number between 1 and 100.")
        return
    deleted = await ctx.channel.purge(limit=amount + 1)  # +1 to include the command message
    msg = await ctx.send(f"🧹 Deleted {len(deleted) - 1} messages.")
    await asyncio.sleep(3)
    try:
        await msg.delete()
    except discord.NotFound:
        pass


@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    if seconds < 0 or seconds > 21600:
        await ctx.send("❌ Seconds must be between 0 and 21600 (6 hours).")
        return
    await ctx.channel.edit(slowmode_delay=seconds)
    if seconds == 0:
        await ctx.send("🐇 Slowmode disabled.")
    else:
        await ctx.send(f"🐌 Slowmode set to {seconds} seconds.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔒 This channel has been locked.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send("🔓 This channel has been unlocked.")


@bot.command()
@commands.has_permissions(manage_channels=True)
async def createchannel(ctx, *, name: str):
    channel = await ctx.guild.create_text_channel(name)
    await ctx.send(f"✅ Created channel {channel.mention}")


# ---------------------------------------------------------------------------
# SERVER SETUP (admin config commands)
# ---------------------------------------------------------------------------

@bot.command()
@commands.has_permissions(administrator=True)
async def setmodlog(ctx, channel: discord.TextChannel):
    cfg = get_guild_config(ctx.guild.id)
    cfg["modlog"] = channel.id
    save_data()
    await ctx.send(f"✅ Mod-log channel set
