import discord
from discord.ext import commands
import datetime
import os

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

afk_users = {}
message_counts = {}

@bot.event
async def on_ready():
    print(f"✅ Bot is live and locked in: {bot.user.name}")
    await bot.change_presence(activity=discord.Game(name="!help | Apex Bot 🔥"))

@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel
    if channel:
        embed = discord.Embed(
            title="✨ New Member Just Dropped!",
            description=f"Yo {member.mention}, welcome to **{member.guild.name}**! Big main character energy, fr fr. 🗿🔥",
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    message_counts[user_id] = message_counts.get(user_id, 0) + 1

    if user_id in afk_users:
        del afk_users[user_id]
        await message.channel.send(f"Wyb {message.author.mention}! Removed your AFK tag, back to the chat motion. ⚡", delete_after=5)

    for mention in message.mentions:
        if mention.id in afk_users:
            reason = afk_users[mention.id]
            await message.channel.send(f"⚠️ {mention.display_name} is currently AFK, no cap. Reason: *{reason}* 😴")

    await bot.process_commands(message)

@bot.command()
async def afk(ctx, *, reason="Just chillin, no reason given"):
    afk_users[ctx.author.id] = reason
    embed = discord.Embed(
        description=f"💤 {ctx.author.mention} went AFK. Reason: **{reason}**",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed)

@bot.command()
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"📸 {member.display_name}'s Fit & Avatar", color=discord.Color.blue())
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason="Took a big L"):
    duration = datetime.timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    embed = discord.Embed(
        title="🔇 Muted / Sent to Timeout",
        description=f"{member.mention} got muted for **{minutes} mins**. Pure Cooked behavior.\n**Reason:** {reason}",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Broke the vibe"):
    await member.ban(reason=reason)
    embed = discord.Embed(
        title="🔨 Banned!",
        description=f"{member.mention} got sent to the void. Total NPC behavior.\n**Reason:** {reason}",
        color=discord.Color.dark_red()
    )
    await ctx.send(embed=embed)

@bot.command()
async def messages(ctx, member: discord.Member = None):
    member = member or ctx.author
    count = message_counts.get(member.id, 0)
    embed = discord.Embed(
        title="📊 Yapping Stats",
        description=f"{member.mention} has dropped **{count}** messages in this chat. Pure grind set! 📈",
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

bot.run(os.getenv('BOT_TOKEN'))

