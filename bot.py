import discord
from discord.ext import commands, tasks
from datetime import datetime
import json
import os

TOKEN = os.environ["TOKEN"]
DATA_FILE = "pointages.json"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Data ─────────────────────────────────────────────────────
def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def fmt(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h{m:02d}m{s:02d}s"

def get_elapsed(u):
    now = datetime.utcnow().timestamp()
    pauses = u.get("total_pauses", 0)
    if u["status"] == "paused":
        pauses += now - u["pause_start"]
    return now - u["start"] - pauses

# ─── Embed principal ──────────────────────────────────────────
async def build_embed(guild, data):
    embed = discord.Embed(title="📋 Pointeuse — Service en cours", color=0x2ecc71)
    en_service = [(uid, u) for uid, u in data.items() if u["status"] in ("working", "paused")]
    if not en_service:
        embed.description = "*Personne en service actuellement*"
    else:
        lines = []
        for uid, u in en_service:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"<@{uid}>"
            elapsed = fmt(get_elapsed(u))
            if u["status"] == "working":
                lines.append(f"🟢 **{name}** — {elapsed}")
            else:
                lines.append(f"⏸️ **{name}** — {elapsed} *(pause)*")
        embed.description = "\n".join(lines)
    embed.set_footer(text=f"Mis à jour: {datetime.utcnow().strftime('%H:%M:%S')} UTC")
    return embed

# ─── Config ───────────────────────────────────────────────────
CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)

async def refresh_board(guild, data):
    cfg = load_config()
    if not cfg.get("channel_id") or not cfg.get("board_msg_id"):
        return
    channel = guild.get_channel(cfg["channel_id"])
    if not channel:
        return
    try:
        msg = await channel.fetch_message(cfg["board_msg_id"])
        embed = await build_embed(guild, data)
        await msg.edit(embed=embed)
    except:
        pass

# ─── Vues ─────────────────────────────────────────────────────
class PrendreServiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶ Prendre service", style=discord.ButtonStyle.success, custom_id="btn_prendre")
    async def prendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if uid in data and data[uid]["status"] != "off":
            await interaction.response.send_message("⚠️ Tu es déjà en service !", ephemeral=True)
            return
        data[uid] = {"status": "working", "start": now, "pause_start": None, "total_pauses": 0}
        save(data)
        view = EnServiceView()
        await interaction.response.send_message(
            f"✅ Service démarré à **{datetime.utcnow().strftime('%H:%M')}** UTC", view=view, ephemeral=True
        )
        await refresh_board(interaction.guild, data)


class EnServiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏸ Pause", style=discord.ButtonStyle.primary, custom_id="btn_pause")
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if uid not in data or data[uid]["status"] != "working":
            await interaction.response.send_message("⚠️ Tu n'es pas en service.", ephemeral=True)
            return
        data[uid]["status"] = "paused"
        data[uid]["pause_start"] = now
        save(data)
        await interaction.response.edit_message(content="⏸️ En pause.", view=EnPauseView())
        await refresh_board(interaction.guild, data)

    @discord.ui.button(label="⏹ Fin de service", style=discord.ButtonStyle.danger, custom_id="btn_fin")
    async def fin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await fin_service(interaction)


class EnPauseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶ Reprendre", style=discord.ButtonStyle.secondary, custom_id="btn_reprendre")
    async def reprendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if uid not in data or data[uid]["status"] != "paused":
            await interaction.response.send_message("⚠️ Tu n'es pas en pause.", ephemeral=True)
            return
        data[uid]["total_pauses"] += now - data[uid]["pause_start"]
        data[uid]["pause_start"] = None
        data[uid]["status"] = "working"
        save(data)
        await interaction.response.edit_message(content="🟢 Service repris.", view=EnServiceView())
        await refresh_board(interaction.guild, data)

    @discord.ui.button(label="⏹ Fin de service", style=discord.ButtonStyle.danger, custom_id="btn_fin_pause")
    async def fin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await fin_service(interaction)


async def fin_service(interaction):
    data = load()
    uid = str(interaction.user.id)
    now = datetime.utcnow().timestamp()
    if uid not in data or data[uid]["status"] == "off":
        await interaction.response.send_message("⚠️ Tu n'es pas en service.", ephemeral=True)
        return
    u = data[uid]
    if u["status"] == "paused":
        u["total_pauses"] += now - u["pause_start"]
    total = get_elapsed(u)
    u["status"] = "off"
    u["start"] = None
    u["pause_start"] = None
    u["total_pauses"] = 0
    save(data)
    await interaction.response.edit_message(content=f"✅ Fin de service — Temps: **{fmt(total)}**", view=None)
    await refresh_board(interaction.guild, data)

# ─── Commande admin ───────────────────────────────────────────
@bot.command(name="pointeuse")
@commands.has_permissions(administrator=True)
async def pointeuse(ctx):
    data = load()
    embed = await build_embed(ctx.guild, data)
    board_msg = await ctx.send(embed=embed)
    await ctx.send("👇 Clique pour prendre/gérer ton service :", view=PrendreServiceView())
    save_config({"channel_id": ctx.channel.id, "board_msg_id": board_msg.id})
    await ctx.message.delete()

# ─── Auto-refresh toutes les 60s ──────────────────────────────
@tasks.loop(seconds=60)
async def auto_refresh():
    cfg = load_config()
    if not cfg.get("channel_id") or not cfg.get("board_msg_id"):
        return
    for guild in bot.guilds:
        channel = guild.get_channel(cfg["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(cfg["board_msg_id"])
                data = load()
                embed = await build_embed(guild, data)
                await msg.edit(embed=embed)
            except:
                pass

@bot.event
async def on_ready():
    bot.add_view(PrendreServiceView())
    bot.add_view(EnServiceView())
    bot.add_view(EnPauseView())
    auto_refresh.start()
    print(f"✅ Bot connecté : {bot.user}")

bot.run(TOKEN)
