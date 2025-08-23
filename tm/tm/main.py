import os
import datetime
import random
from discord.ext import commands
import requests
import json, time
from duckduckgo_search import DDGS
import asyncio
import discord
from discord.ext import commands
from subprocess import run, PIPE



EMBED_COLOR = discord.Color(int("2b2d31", 16))
DATA_FILE = "data.json"

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({"afk": afk_map, "warnings": warnings}, f)

def load_data():
    global afk_map, warnings
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            afk_map = data.get("afk", {})
            warnings = data.get("warnings", {})
    except FileNotFoundError:
        pass

PREFIX = "*"
intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("*"),
    intents=intents
)

afk_map = {}
warnings = {}
vc_owners = {}  # channel_id -> owner_id

@bot.event
async def on_ready():
    load_data()
    print(f"✅ Logged in as {bot.user}")
    ...

load_data()

# ----------------- AFK -----------------
@bot.command()
async def afk(ctx, *, reason="AFK"):
    afk_map[str(ctx.author.id)] = {
        "reason": reason,
        "time": time.time()
    }
    save_data()
    await ctx.reply(f"😴 You are now AFK: **{reason}**")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, amount: int):
    if amount < 1:
        return await ctx.reply("You must specify a number greater than 0.")

    deleted = await ctx.channel.purge(limit=amount + 1)  # +1 includes the purge command itself
    await ctx.send(f"🧹 Deleted {len(deleted)-1} messages.", delete_after=5)

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return

    # remove AFK if user talks again
    if str(msg.author.id) in afk_map:
        afk_info = afk_map.pop(str(msg.author.id))
        save_data()

        elapsed = int(time.time() - afk_info["time"])
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        duration = f"{hours}h {mins}m" if hours else f"{mins}m"

        await msg.reply(f"👋 You were **AFK** for: **{duration}**.")
    # check mentions for AFK
    for user in msg.mentions:
        if str(user.id) in afk_map:
            afk_info = afk_map[str(user.id)]
            elapsed = int(time.time() - afk_info["time"])
            mins, secs = divmod(elapsed, 60)
            hours, mins = divmod(mins, 60)
            duration = f"{hours}h {mins}m" if hours else f"{mins}m"
            await msg.reply(f"💤 {user} is AFK: **{afk_info['reason']}** (for {duration})")

    await bot.process_commands(msg)

# ----------------- WARN -----------------
@bot.command()
@commands.has_permissions(manage_messages=True)  # only mods/admins
async def warn(ctx, member: discord.Member, *, reason="No reason"):
    user_warnings = warnings.get(str(member.id), [])
    user_warnings.append(reason)
    warnings[str(member.id)] = user_warnings
    save_data()
    embed = discord.Embed(
        title="⚠️ Warning Issued",
        description=f"{member.mention} has been warned.",
        color=EMBED_COLOR
    )
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Total Warnings", value=len(user_warnings), inline=True)
    await ctx.reply(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)  # only mods/admins can view
async def warnings_list(ctx, member: discord.Member):
    user_warnings = warnings.get(str(member.id), [])
    embed = discord.Embed(
        title=f"⚠️ Warnings for {member}",
        color=EMBED_COLOR
    )
    if not user_warnings:
        embed.description = "✅ No warnings."
    else:
        formatted = "\n".join([f"{i+1}. {w}" for i, w in enumerate(user_warnings)])
        embed.description = formatted
    await ctx.reply(embed=embed)

# ----------------- VC CREATION -----------------
async def create_private_vc(member: discord.Member):
    """Creates a private VC for a member and remembers ownership"""
    overwrites = {
        member.guild.default_role: discord.PermissionOverwrite(connect=False),
        member: discord.PermissionOverwrite(connect=True, manage_channels=True),
    }
    channel = await member.guild.create_voice_channel(
        f"{member.name}'s VC",
        overwrites=overwrites
    )
    vc_owners[channel.id] = member.id  # store owner

    async def auto_delete():
        while True:
            await asyncio.sleep(60)
            if len(channel.members) == 0:
                vc_owners.pop(channel.id, None)  # cleanup
                await channel.delete()
                break

    bot.loop.create_task(auto_delete())
    return channel


# ----------------- BUTTONS -----------------
class ControlsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CreateVCButton())
        self.add_item(LockVCButton())
        self.add_item(RenameVCButton())
        self.add_item(DeleteVCButton())


class CreateVCButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="➕ Create VC", style=discord.ButtonStyle.primary, custom_id="create_vc")

    async def callback(self, interaction: discord.Interaction):
        channel = await create_private_vc(interaction.user)
        await interaction.response.send_message(f"Created {channel.mention}", ephemeral=True)


class LockVCButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="🔒 Lock/Unlock", style=discord.ButtonStyle.secondary, custom_id="lock_vc")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ You must be in your VC.", ephemeral=True)

        channel = interaction.user.voice.channel
        if vc_owners.get(channel.id) != interaction.user.id:
            return await interaction.response.send_message("❌ Only the VC owner can control this.", ephemeral=True)

        perms = channel.overwrites_for(interaction.guild.default_role)
        perms.connect = not perms.connect
        await channel.set_permissions(interaction.guild.default_role, overwrite=perms)
        state = "locked 🔒" if not perms.connect else "unlocked 🔓"
        await interaction.response.send_message(f"Channel {state}.", ephemeral=True)


class RenameVCButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="✏️ Rename", style=discord.ButtonStyle.secondary, custom_id="rename_vc")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ You must be in your VC.", ephemeral=True)

        channel = interaction.user.voice.channel
        if vc_owners.get(channel.id) != interaction.user.id:
            return await interaction.response.send_message("❌ Only the VC owner can control this.", ephemeral=True)

        modal = discord.ui.Modal(title="Rename VC")
        name_input = discord.ui.TextInput(label="New channel name", placeholder="Enter name...", max_length=30)
        modal.add_item(name_input)

        async def modal_callback(inter: discord.Interaction):
            await channel.edit(name=str(name_input))
            await inter.response.send_message(f"Renamed channel to {channel.name}", ephemeral=True)

        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)


class DeleteVCButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="❌ Delete", style=discord.ButtonStyle.danger, custom_id="delete_vc")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ You must be in your VC.", ephemeral=True)

        channel = interaction.user.voice.channel
        if vc_owners.get(channel.id) != interaction.user.id:
            return await interaction.response.send_message("❌ Only the VC owner can control this.", ephemeral=True)

        vc_owners.pop(channel.id, None)
        await channel.delete()
        await interaction.response.send_message("Deleted your VC.", ephemeral=True)


# ----------------- EVENTS -----------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    bot.add_view(ControlsView())  # Register persistent buttons

    for guild in bot.guilds:
        controls = discord.utils.get(guild.text_channels, name="controls")
        if controls:
            async for msg in controls.history(limit=20):
                if msg.author == bot.user and msg.components:
                    break
            else:
                await controls.send(
                    "**VoiceMaster Controls**\n\n"
                    "➕ Create VC — Make a private VC\n"
                    "🔒 Lock/Unlock — Toggle whether others can join\n"
                    "✏️ Rename — Rename your VC\n"
                    "❌ Delete — Delete your VC",
                    view=ControlsView()
                )


@bot.event
async def on_voice_state_update(member, before, after):
    # Join-to-Create system
    if after.channel and after.channel.name.lower() == "jtc":
        channel = await create_private_vc(member)
        await member.move_to(channel)


# ----------------- MODERATION -----------------
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason"):
    await member.ban(reason=reason)
    await ctx.reply(f"🔨 Banned {member} ({reason})")


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason"):
    await member.kick(reason=reason)
    await ctx.reply(f"👢 Kicked {member} ({reason})")

SERPAPI_KEY = "34b86b430680ccc1576a953b90056e2d571505f890fee6a208370788652e3570"
banned_words = ["nsfw", "porn", "nude", "sex", "gore", "hentai"]

@bot.command()
async def image(ctx, *, query: str):
    # Filter banned words
    if any(bad in query.lower() for bad in banned_words):
        await ctx.reply("🚫 That search isn’t allowed.")
        return

    # Try DuckDuckGo first
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.images(query, safesearch="On", max_results=1)]
        if results:
            await ctx.reply(results[0]["image"])
            return
    except Exception as e:
        print(f"DuckDuckGo failed: {e}")

    # Fallback to SerpApi
    try:
        url = "https://serpapi.com/search.json"
        params = {
            "engine": "google",
            "q": query,
            "tbm": "isch",
            "safe": "active",
            "api_key": SERPAPI_KEY
        }
        r = requests.get(url, params=params).json()
        if "images_results" in r and len(r["images_results"]) > 0:
            first_image = r["images_results"][0]["original"]
            await ctx.reply(first_image)
            return
    except Exception as e:
        print(f"SerpApi failed: {e}")

    await ctx.reply("❌ No image found.")

# ----------------- EXEC (OWNER ONLY) -----------------
@bot.command()
async def execpy(ctx, *, code: str):
    if str(ctx.author.id) != os.getenv("OWNER_ID"):
        return await ctx.reply("🚫 Not allowed.")

    try:
        exec(
            f'async def _exec(ctx):\n' +
            ''.join(f'    {line}\n' for line in code.split('\n'))
        )
        result = await locals()["_exec"](ctx)
        if result is not None:
            await ctx.reply(f"✅ {result}")
    except Exception as e:
        await ctx.reply(f"❌ Error: {e}")

# ----------------- LOGGING -----------------
LOG_CHANNEL_NAME = "logs"

async def get_log_channel(guild):
    return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

@bot.event
async def on_member_join(member):
    if member.guild.system_channel:
        await member.guild.system_channel.send(f"👋 Welcome, {member.mention}!")

    channel = await get_log_channel(member.guild)
    if channel:
        embed = discord.Embed(
            title="👋 Member Joined",
            description=f"{member.mention} ({member})",
            color=EMBED_COLOR
        )
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M"), inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_member_remove(member):
    channel = await get_log_channel(member.guild)
    if channel:
        embed = discord.Embed(
            title="👋 Member Left",
            description=f"{member.mention} ({member})",
            color=EMBED_COLOR
        )
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Joined At", value=member.joined_at.strftime("%Y-%m-%d %H:%M") if member.joined_at else "Unknown", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    channel = await get_log_channel(message.guild)
    if channel:
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            description=f"Author: {message.author.mention}\nChannel: {message.channel.mention}",
            color=EMBED_COLOR
        )
        if message.content:
            embed.add_field(name="Content", value=message.content, inline=False)
        embed.set_footer(text=f"Message ID: {message.id}")
        await channel.send(embed=embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    channel = await get_log_channel(before.guild)
    if channel:
        embed = discord.Embed(
            title="✏️ Message Edited",
            description=f"Author: {before.author.mention}\nChannel: {before.channel.mention}",
            color=EMBED_COLOR
        )
        embed.add_field(name="Before", value=before.content or "*empty*", inline=False)
        embed.add_field(name="After", value=after.content or "*empty*", inline=False)
        embed.set_footer(text=f"Message ID: {before.id}")
        await channel.send(embed=embed)

@bot.event
async def on_member_ban(guild, user):
    channel = await get_log_channel(guild)
    if channel:
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{user.mention} ({user})",
            color=EMBED_COLOR
        )
        embed.add_field(name="ID", value=user.id, inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        await channel.send(embed=embed)

@bot.event
async def on_member_unban(guild, user):
    channel = await get_log_channel(guild)
    if channel:
        embed = discord.Embed(
            title="⚖️ Member Unbanned",
            description=f"{user.mention} ({user})",
            color=EMBED_COLOR
        )
        embed.add_field(name="ID", value=user.id, inline=True)
        embed.set_thumbnail(url=user.display_avatar.url)
        await channel.send(embed=embed)

# ----------------- ERRORS -----------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  
    elif isinstance(error, commands.MissingPermissions):
        await ctx.reply("🚫 You don’t have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply(f"⚠️ Missing argument: `{error.param.name}`")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ Slow down! Try again in {round(error.retry_after, 2)}s.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.reply("⚠️ I don’t have the required permissions to do that.")
    else:
        await ctx.reply("❌ An unexpected error occurred.")
        raise error  # still print in console

# ----------------- MISC COMMANDS -----------------
@bot.command()
async def ping(ctx):
    await ctx.reply(f"Pong! 🏓 Latency: {round(bot.latency * 1000)}ms")

@bot.command()
async def roll(ctx, sides: int = 6):
    result = random.randint(1, sides)
    await ctx.reply(f"🎲 You rolled a **{result}** (1-{sides})!")

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(
        title=f"Server Info - {guild.name}",
        color=EMBED_COLOR,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="Owner", value=guild.owner.mention, inline=False)
    embed.add_field(name="Server ID", value=guild.id, inline=True)
    embed.add_field(name="Members", value=guild.member_count, inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    embed.add_field(name="Voice Channels", value=len(guild.voice_channels), inline=True)
    embed.add_field(name="Created On", value=guild.created_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True)
    embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)
    await ctx.reply(embed=embed)

@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(
        title=f"User Info - {member}",
        color=EMBED_COLOR,
        timestamp=datetime.datetime.utcnow()
    )
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Nickname", value=member.nick if member.nick else "None", inline=True)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%b %d, %Y"), inline=True)
    roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
    embed.add_field(name="Roles", value=", ".join(roles) if roles else "No roles", inline=False)
    embed.add_field(name="Top Role", value=member.top_role.mention, inline=True)
    embed.add_field(name="Is Bot?", value="Yes" if member.bot else "No", inline=True)
    await ctx.reply(embed=embed)

@bot.command()
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(
        title=f"🖼️ Avatar - {member}",
        color=EMBED_COLOR
    )
    if member.avatar:
        embed.set_image(url=member.avatar.url)
    else:
        embed.description = "This user has no avatar."
    await ctx.reply(embed=embed)

@bot.command()
async def poll(ctx, *, question: str):
    embed = discord.Embed(
        title="📊 Poll",
        description=question,
        color=EMBED_COLOR
    )
    poll_message = await ctx.send(embed=embed)
    await poll_message.add_reaction("👍")
    await poll_message.add_reaction("👎")
    await ctx.message.delete()

# ----------------- RUN -----------------
bot.run(os.getenv("TOKEN"))