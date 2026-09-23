import os
import random
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

    await bot.process_commands(message)


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
async def bothelp(ctx):
    embed = discord.Embed(title="🚀 Apex Bot Commands", color=discord.Color.purple())
    embed.add_field(
        name="🛠️ Moderation",
        value=(
            "`!mute @user [time] [reason]`\n"
            "`!unmute @user`\n"
            "`!ban @user [reason]`\n"
            "`!lock`\n"
            "`!unlock`\n"
            "`!createchannel <name>`"
        ),
        inline=False,
    )
    embed.add_field(name="🔥 Fun", value="`!roast [@user]`", inline=False)
    embed.add_field(
        name="💬 General",
        value=(
            "`!afk [reason]`\n"
            "`!avatar [@user]`\n"
            "`!messages [@user]`\n"
            "`!serverinfo`\n"
            "`!userinfo [@user]`\n"
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
    """Turn '10m' / '2h' / '1d' into a timedelta. Returns None if invalid."""
    if not time_str:
        return None
    unit = time_str[-1].lower()
    try:
        amount = int(time_str[:-1])
    except ValueError:
        return None
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
    duration = parse_duration(time) if time else datetime.timedelta(minutes=10)
    try:
        await member.timeout(duration, reason=reason)
        label = time if time else "10m (default)"
        await ctx.send(f"🔇 {member.mention} muted for **{label}**. Reason: {reason}")
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
    except discord.Forbidden:
        await ctx.send("❌ I don't have permission to ban this user.")


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
# ERROR HANDLING (so one bad command doesn't crash the bot)
# ---------------------------------------------------------------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Couldn't find that member.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`. Check `!bothelp`.")
    elif isinstance(error, commands.CommandNotFound):
        return  # ignore unknown commands silently
    else:
        print(f"Unhandled error: {error}")
        await ctx.send("⚠️ Something went wrong running that command.")


# ---------------------------------------------------------------------------
# RUN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set!")
    keep_alive()
    bot.run(token)
