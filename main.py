import os
import datetime
import random
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# AFK Storage
afk_users = {}

@bot.event
async def on_ready():
    print(f"✅ Bot is live and locked in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Check if AFK user spoke
    if message.author.id in afk_users:
        del afk_users[message.author.id]
        await message.channel.send(f"Welcome back {message.author.mention}, tera AFK status hata diya hai!")

    # Check if mentioned user is AFK
    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            await message.channel.send(f"zzz {mention.mention} is AFK. Reason: {reason}")

    await bot.process_commands(message)

# ------------------- 📌 UTILITY & INFO -------------------

# 1. AFK
@bot.command()
async def afk(ctx, *, reason="Just chillin, no reason given"):
    afk_users[ctx.author.id] = reason
    await ctx.send(f"zzz {ctx.author.mention} went AFK. Reason: **{reason}**")

# 2. Avatar (!avatar / !av)
@bot.command(aliases=["av"])
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"💫 {member.name} ka Avatar", color=discord.Color.blue())
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)

# 3. Member Info (!userinfo / !ui / !memberinfo)
@bot.command(aliases=["ui", "memberinfo"])
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles = [role.mention for role in member.roles[1:]] or ["None"]
    embed = discord.Embed(title=f"👤 {member.name} Details", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles), inline=False)
    await ctx.send(embed=embed)

# 4. Server Info (!serverinfo / !si)
@bot.command(aliases=["si"])
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"📊 {guild.name} Server Stats", color=discord.Color.purple())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
    embed.add_field(name="Total Members", value=guild.member_count, inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    embed.add_field(name="Created On", value=guild.created_at.strftime("%b %d, %Y"), inline=False)
    await ctx.send(embed=embed)

# 5. Banned Members List (!banlist)
@bot.command()
@commands.has_permissions(ban_members=True)
async def banlist(ctx):
    bans = [entry async for entry in ctx.guild.bans()]
    if not bans:
        await ctx.send("📋 Iss server mein koi bhi user banned nahi hai, sab clean hai!")
        return
    banned_desc = "\n".join([f"• **{b.user.name}** (ID: {b.user.id})" for b in bans[:10]])
    embed = discord.Embed(title="🚫 Banned Members List", description=banned_desc, color=discord.Color.red())
    await ctx.send(embed=embed)

# ------------------- 🛡️ MODERATION & CHANNEL CONTROL -------------------

# 6. Mute (Timeout)
@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason="No reason given"):
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await ctx.send(f"🤫 {member.mention} ko {minutes} minutes ke liye mute kar diya hai. Reason: **{reason}**")

# 7. Unmute
@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    await member.timeout(None)
    await ctx.send(f"🔊 {member.mention} ab unmute ho gaya hai!")

# 8. Lock Channel (!lock)
@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send(f"🔒 {channel.mention} channel lock ho gaya hai!")

# 9. Unlock Channel (!unlock)
@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(ctx.guild.default_role, send_messages=True)
    await ctx.send(f"🔓 {channel.mention} channel unlock kar diya hai!")

# 10. Channel Bypass (!bypass)
@bot.command()
@commands.has_permissions(manage_channels=True)
async def bypass(ctx, target: discord.Member, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    await channel.set_permissions(target, send_messages=True)
    await ctx.send(f"⚡ {target.mention} ko {channel.mention} mein bypass access mil gaya hai!")

# 11. Clear Messages (!clear / !purge)
@bot.command(aliases=["purge"])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 {amount} messages delete kar diye!", delete_after=3)

# ------------------- 🎮 TIMEPASS GAMES -------------------

# 12. Magic 8Ball (!8ball)
@bot.command(name="8ball")
async def eightball(ctx, *, question: str):
    responses = [
        "Haan bilkul lala!", "100% Sahi hai.", "Probable lag raha hai.",
        "Dimaag mat kharab kar, baad mein pooch.", "Mujhe nahi lagta bhai.",
        "Bhul ja, aisa nahi hoga.", "No chance brother."
    ]
    reply = random.choice(responses)
    await ctx.send(f"🎱 **Question:** {question}\n**Answer:** {reply}")

# 13. Dice Roll (!roll)
@bot.command()
async def roll(ctx):
    number = random.randint(1, 100)
    await ctx.send(f"🎲 {ctx.author.mention} rolled **{number}** (1-100)!")

# 14. Coin Flip (!flip / !coin)
@bot.command(aliases=["coin"])
async def flip(ctx):
    result = random.choice(["Heads 👑", "Tails 🪙"])
    await ctx.send(f"🪙 Result: **{result}**")

# 15. Ping
@bot.command()
async def ping(ctx):
    await ctx.send(f"Pong! 🏓 `{round(bot.latency * 1000)}ms`")

# ------------------- 📋 HELP COMMAND -------------------

@bot.command()
async def bothelp(ctx):
    embed = discord.Embed(title="🤖 Apex Bot - Full Command List", color=discord.Color.gold())
    embed.add_field(name="📌 Info", value="`!afk`, `!av`, `!ui`, `!si`, `!banlist`", inline=False)
    embed.add_field(name="🛡️ Moderation", value="`!mute @user [min]`, `!unmute @user`, `!clear [num]`", inline=False)
    embed.add_field(name="🔒 Channel", value="`!lock`, `!unlock`, `!bypass @user`", inline=False)
    embed.add_field(name="🎮 Timepass Games", value="`!8ball [question]`, `!roll`, `!flip`", inline=False)
    await ctx.send(embed=embed)

bot.run(os.getenv("BOT_TOKEN"))
