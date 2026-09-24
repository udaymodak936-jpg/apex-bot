
        
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


@bot.command()
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
        name="\U0001f4ac General",
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