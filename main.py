import os
import discord
from discord.ext import commands
from datetime import datetime, timedelta

# Intents setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.invites = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# AFK Storage
afk_users = {}

@bot.event
async def on_ready():
    print(f"🔥 {bot.user.name} is Online & Ready!")
    await bot.change_presence(activity=discord.Game(name="!bothelp | Gen Z Vibe 🗿"))

# ----------------- AFK SYSTEM -----------------
@bot.command()
async def afk(ctx, *, reason="I am currently AFK."):
    afk_users[ctx.author.id] = reason
    await ctx.send(f"💤 {ctx.author.mention} is now AFK! **Reason:** {reason}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Remove AFK status when the user sends a message
    if message.author.id in afk_users:
        del afk_users[message.author.id]
        await message.channel.send(f"👋 Welcome back {message.author.mention}, your AFK status has been removed!")

    # Check if a mentioned user is AFK
    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            await message.channel.send(f"⚠️ {mention.display_name} is currently AFK! **Reason:** {reason}")

    await bot.process_commands(message)

# ----------------- MUTE COMMAND -----------------
@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, time_str: str = "10m", *, reason="Rule violation"):
    if member == ctx.author:
        await ctx.send("❌ You cannot mute yourself!")
        return

    unit = time_str[-1].lower()
    val_str = time_str[:-1]

    if not val_str.isdigit():
        reason = f"{time_str} {reason}".strip()
        seconds = 600
        time_str = "10m"
    else:
        num = int(val_str)
        if unit == 's': seconds = num
        elif unit == 'm': seconds = num * 60
        elif unit == 'h': seconds = num * 3600
        elif unit == 'd': seconds = num * 86400
        else: seconds = 600

    try:
        duration = timedelta(seconds=seconds)
        await member.timeout(duration, reason=reason)
        
        embed = discord.Embed(
            title="🤫 User Muted", 
            description=f"🚫 **User:** {member.mention}\n⏰ **Duration:** {time_str}\n📄 **Reason:** {reason}", 
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Failed to mute user! (Note: Bots cannot timeout Server Owners or higher Admins). Error: {e}")

# ----------------- UNMUTE COMMAND -----------------
@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None)
        embed = discord.Embed(
            title="🔊 User Unmuted", 
            description=f"✅ {member.mention} has been unmuted!", 
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Failed to unmute user! Error: {e}")

# ----------------- UTILITY & FUN -----------------
@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")

@bot.command()
async def bothelp(ctx):
    embed = discord.Embed(title="🚀 Apex Bot Commands", color=discord.Color.blue())
    embed.add_field(name="🛠️ Moderation", value="`!mute @user [time] [reason]`, `!unmute @user`", inline=False)
    embed.add_field(name="💬 General", value="`!afk [reason]`, `!ping`, `!bothelp`", inline=False)
    await ctx.send(embed=embed)

# ----------------- RUN BOT -----------------
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
