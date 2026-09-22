
    import os
import discord
from discord.ext import commands
from datetime import datetime, timezone

# ------------------- BOT SETUP & INTENTS -------------------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.invites = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")  # Custom bothelp ke liye default help remove kiya

# AFK Storage
afk_data = {}

@bot.event
async def on_ready():
    print(f"🔥 Apex Bot is Online & Ready as {bot.user.name}!")
    await bot.change_presence(activity=discord.Game(name="!bothelp | Gen Z Vibe 🗿"))

# ------------------- AFK LISTENER -------------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # User active hua toh AFK remove
    if message.author.id in afk_data:
        del afk_data[message.author.id]
        await message.channel.send(f"Wassup {message.author.mention}! Aapka AFK remove kar diya hai. 🔥")

    # Mention check for AFK users
    for mention in message.mentions:
        if mention.id in afk_data:
            reason = afk_data[mention.id]
            await message.channel.send(f"⚠️ **{mention.display_name}** abhi AFK hai bro! Reason: *{reason}*")

    await bot.process_commands(message)

# ------------------- AFK COMMAND -------------------
@bot.command()
async def afk(ctx, *, reason="Koyi reason nahi diya lala"):
    afk_data[ctx.author.id] = reason
    await ctx.send(f"✅ {ctx.author.mention} ab AFK par hai! Reason: **{reason}**")

# ------------------- MODERATION COMMANDS -------------------
@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason="Rules break kiya lala"):
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not muted_role:
        muted_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(muted_role, send_messages=False, speak=False)

    await member.add_roles(muted_role, reason=reason)
    await ctx.send(f"🔇 **{member.display_name}** ko mute kar diya gaya hai! Reason: *{reason}*")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if muted_role in member.roles:
        await member.remove_roles(muted_role)
        await ctx.send(f"🔊 **{member.display_name}** ko unmute kar diya hai! Mast reh ab.")
    else:
        await ctx.send("Arey lala, yeh banda mute hi nahi tha! 💀")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="Server me bakchodi nahi!"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 **{member.display_name}** ko hammer maar ke ban kar diya! Reason: *{reason}*")

@bot.command(aliases=["purge"])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 **{amount}** messages uda diye lala!", delete_after=3)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    overwrite = channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send(f"🔒 {channel.mention} ko lock kar diya hai!")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    overwrite = channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = True
    await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await ctx.send(f"🔓 {channel.mention} ko unlock kar diya hai!")

# ------------------- AUTOMATIC CHANNEL CREATOR -------------------
@bot.command()
@commands.has_permissions(manage_channels=True)
async def createchannel(ctx, channel_type: str, *, name: str):
    if channel_type.lower() in ["text", "txt"]:
        ch = await ctx.guild.create_text_channel(name)
        await ctx.send(f"⚡ Automatic Text Channel ban gaya: {ch.mention}")
    elif channel_type.lower() in ["voice", "vc"]:
        ch = await ctx.guild.create_voice_channel(name)
        await ctx.send(f"🎙️ Automatic Voice Channel ban gaya: **{ch.name}**")
    else:
        await ctx.send("❌ Galat type lala! Format: `!createchannel text <name>` ya `!createchannel voice <name>`")

# ------------------- AGE CHECKERS -------------------
@bot.command()
async def idage(ctx, user_id: int):
    try:
        created_at = discord.utils.snowflake_time(user_id)
        now = datetime.now(timezone.utc)
        diff = now - created_at

        years = diff.days // 365
        remaining_days = diff.days % 365

        date_str = created_at.strftime('%d %b %Y, %I:%M %p UTC')
        await ctx.send(f"🆔 **User ID:** `{user_id}`\n📅 **Created On:** {date_str}\n⏳ **Account Age:** **{years}** saal, **{remaining_days}** din purana hai! 🗿")
    except Exception:
        await ctx.send("❌ Galat ID dali hai lala, sahi Discord User ID daal!")

@bot.command()
async def serverage(ctx):
    created_at = ctx.guild.created_at
    now = datetime.now(timezone.utc)
    diff = now - created_at

    years = diff.days // 365
    remaining_days = diff.days % 365

    date_str = created_at.strftime('%d %b %Y, %I:%M %p UTC')
    await ctx.send(f"🏰 **Server Name:** {ctx.guild.name}\n📅 **Created On:** {date_str}\n⏳ **Server Age:** **{years}** saal, **{remaining_days}** din purana empire hai! 🔥")

# ------------------- INVITE TRACKER -------------------
@bot.command()
async def invites(ctx, member: discord.Member = None):
    member = member or ctx.author
    total_uses = 0

    try:
        all_invites = await ctx.guild.invites()
        for invite in all_invites:
            if invite.inviter and invite.inviter.id == member.id:
                total_uses += invite.uses
        await ctx.send(f"📩 **{member.display_name}** ne total **{total_uses}** logo ko server me invite kiya hai! 🚀")
    except Exception:
        await ctx.send("❌ Mere paas Invites read karne ki permission nahi hai lala!")

# ------------------- UTILITY & INFO -------------------
@bot.command(aliases=["av"])
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=f"📸 {member.display_name}'s Avatar", color=discord.Color.blue())
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(aliases=["ui", "memberinfo"])
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    roles = [role.mention for role in member.roles[1:]] or ["None"]
    embed = discord.Embed(title=f"👤 User Info - {member.name}", color=discord.Color.green())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime('%d %b %Y'), inline=True)
    embed.add_field(name="Account Created", value=member.created_at.strftime('%d %b %Y'), inline=True)
    embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles), inline=False)
    await ctx.send(embed=embed)

@bot.command(aliases=["si"])
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"🏰 {guild.name} Info", color=discord.Color.purple())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
    embed.add_field(name="Total Members", value=guild.member_count, inline=True)
    embed.add_field(name="Text Channels", value=len(guild.text_channels), inline=True)
    embed.add_field(name="Voice Channels", value=len(guild.voice_channels), inline=True)
    await ctx.send(embed=embed)

@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! Latency is **{round(bot.latency * 1000)}ms** ⚡")

# ------------------- FUN TIMEPASS -------------------
import random

@bot.command(name="8ball")
async def eightball(ctx, *, question):
    responses = ["Haan bilkul lala! 💯", "Nahi bhai, bhool ja 💀", "Pakka nahi bol sakta 🤔", "100% Sahi hai 🔥", "Kismat kharab hai teri 🥀"]
    await ctx.send(f"❓ **Sawal:** {question}\n🔮 **Jawab:** {random.choice(responses)}")

@bot.command()
async def roll(ctx):
    await ctx.send(f"🎲 Tujhe mila number: **{random.randint(1, 6)}**")

@bot.command()
async def flip(ctx):
    await ctx.send(f"🪙 Coin flipped: **{random.choice(['Heads', 'Tails'])}**")

# ------------------- BOT HELP -------------------
@bot.command()
async def bothelp(ctx):
    embed = discord.Embed(title="⚡ Apex Bot Commands Menu ⚡", color=discord.Color.gold())
    embed.add_field(name="🛡️ Moderation", value="`!mute`, `!unmute`, `!ban`, `!clear [num]`, `!lock`, `!unlock`", inline=False)
    embed.add_field(name="⚙️ Server Utils", value="`!createchannel <text/voice> <name>`, `!invites`, `!serverage`, `!idage <user_id>`", inline=False)
    embed.add_field(name="👤 User Utils", value="`!afk [reason]`, `!avatar`, `!userinfo`, `!serverinfo`, `!ping`", inline=False)
    embed.add_field(name="🎮 Timepass", value="`!8ball <q>`, `!roll`, `!flip`", inline=False)
    embed.set_footer(text="Gen Z Hinglish Vibe Activated 🗿")
    await ctx.send(embed=embed)

# ------------------- RUN BOT -------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ DISCORD_TOKEN Environment Variable nahi mila Render par!")
