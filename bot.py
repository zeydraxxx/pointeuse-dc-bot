import discord
from discord.ext import commands, tasks
from datetime import datetime
import json
import os

TOKEN = os.environ["TOKEN"]
DATA_FILE = "pointages.json"
CONFIG_FILE = "config.json"

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

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)

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

def get_pause_duration(u):
    now = datetime.utcnow().timestamp()
    total = u.get("total_pauses", 0)
    if u["status"] == "paused":
        total += now - u["pause_start"]
    return total

# ─── Embeds ───────────────────────────────────────────────────
async def build_pointeuse_embed():
    embed = discord.Embed(
        title="🕐 POINTEUSE",
        description="Clique sur le bouton ci-dessous pour prendre ou gérer ton service.",
        color=0x1abc9c
    )
    embed.set_footer(text="Blaine County Sheriff Office • Pointeuse")
    return embed

async def build_gestion_embed(guild, data):
    now = datetime.utcnow()
    embed = discord.Embed(
        title="📊 PANNEAU DE GESTION — SERVICE EN COURS",
        color=0xe74c3c,
        timestamp=now
    )

    en_service = [(uid, u) for uid, u in data.items() if u["status"] == "working"]
    en_pause = [(uid, u) for uid, u in data.items() if u["status"] == "paused"]
    hors_service = [(uid, u) for uid, u in data.items() if u["status"] == "off" and u.get("sessions")]

    # EN SERVICE
    if en_service:
        lines = []
        for uid, u in en_service:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            elapsed = get_elapsed(u)
            total_all = sum(s["duree_secondes"] for s in u.get("sessions", [])) + elapsed
            lines.append(f"🟢 **{name}**\n┣ En service depuis : `{fmt(elapsed)}`\n┗ Temps total : `{fmt(total_all)}`")
        embed.add_field(name="━━━ EN SERVICE ━━━", value="\n\n".join(lines), inline=False)
    else:
        embed.add_field(name="━━━ EN SERVICE ━━━", value="*Personne en service*", inline=False)

    # EN PAUSE
    if en_pause:
        lines = []
        for uid, u in en_pause:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            elapsed = get_elapsed(u)
            pause_dur = get_pause_duration(u)
            total_all = sum(s["duree_secondes"] for s in u.get("sessions", [])) + elapsed
            lines.append(f"⏸️ **{name}**\n┣ Pause depuis : `{fmt(pause_dur)}`\n┣ Temps travaillé : `{fmt(elapsed)}`\n┗ Temps total : `{fmt(total_all)}`")
        embed.add_field(name="━━━ EN PAUSE ━━━", value="\n\n".join(lines), inline=False)
    else:
        embed.add_field(name="━━━ EN PAUSE ━━━", value="*Personne en pause*", inline=False)

    # HORS SERVICE (dernières sessions)
    if hors_service:
        lines = []
        for uid, u in hors_service[-5:]:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            last = u["sessions"][-1]
            total_all = sum(s["duree_secondes"] for s in u.get("sessions", []))
            lines.append(f"⬛ **{name}**\n┣ Dernière session : `{fmt(last['duree_secondes'])}` ({last['date']})\n┗ Temps total : `{fmt(total_all)}`")
        embed.add_field(name="━━━ HORS SERVICE ━━━", value="\n\n".join(lines), inline=False)

    total_en_ligne = len(en_service) + len(en_pause)
    embed.set_footer(text=f"👮 {total_en_ligne} agent(s) en ligne • Mise à jour automatique")
    return embed

# ─── Refresh ──────────────────────────────────────────────────
async def refresh_all(guild):
    data = load()
    cfg = load_config()

    # Refresh gestion
    if cfg.get("gestion_channel_id") and cfg.get("gestion_msg_id"):
        ch = guild.get_channel(cfg["gestion_channel_id"])
        if ch:
            try:
                msg = await ch.fetch_message(cfg["gestion_msg_id"])
                await msg.edit(embed=await build_gestion_embed(guild, data))
            except:
                pass

# ─── Vues ─────────────────────────────────────────────────────
class PrendreServiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶  Prendre service", style=discord.ButtonStyle.success, custom_id="btn_prendre")
    async def prendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if uid in data and data[uid]["status"] != "off":
            await interaction.response.send_message("⚠️ Tu es déjà en service !", ephemeral=True)
            return
        if uid not in data:
            data[uid] = {"status": "off", "start": None, "pause_start": None, "total_pauses": 0, "sessions": []}
        data[uid]["status"] = "working"
        data[uid]["start"] = now
        data[uid]["pause_start"] = None
        data[uid]["total_pauses"] = 0
        save(data)
        await interaction.response.send_message(
            f"✅ Service démarré à **{datetime.utcnow().strftime('%H:%M')}** UTC",
            view=EnServiceView(), ephemeral=True
        )
        await refresh_all(interaction.guild)


class EnServiceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏸  Pause", style=discord.ButtonStyle.primary, custom_id="btn_pause")
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
        await refresh_all(interaction.guild)

    @discord.ui.button(label="⏹  Fin de service", style=discord.ButtonStyle.danger, custom_id="btn_fin")
    async def fin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await fin_service(interaction)


class EnPauseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶  Reprendre", style=discord.ButtonStyle.secondary, custom_id="btn_reprendre")
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
        await refresh_all(interaction.guild)

    @discord.ui.button(label="⏹  Fin de service", style=discord.ButtonStyle.danger, custom_id="btn_fin_pause")
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
    u["sessions"].append({"date": datetime.utcnow().strftime("%Y-%m-%d"), "duree_secondes": int(total)})
    u["status"] = "off"
    u["start"] = None
    u["pause_start"] = None
    u["total_pauses"] = 0
    save(data)
    await interaction.response.edit_message(content=f"✅ Fin de service — Temps: **{fmt(total)}**", view=None)
    await refresh_all(interaction.guild)

# ─── Commandes ────────────────────────────────────────────────
@bot.command(name="pointeuse")
@commands.has_permissions(administrator=True)
async def pointeuse_cmd(ctx):
    embed = await build_pointeuse_embed()
    await ctx.send(embed=embed, view=PrendreServiceView())
    await ctx.message.delete()

@bot.command(name="gestion")
@commands.has_permissions(administrator=True)
async def gestion_cmd(ctx):
    data = load()
    embed = await build_gestion_embed(ctx.guild, data)
    msg = await ctx.send(embed=embed)
    cfg = load_config()
    cfg["gestion_channel_id"] = ctx.channel.id
    cfg["gestion_msg_id"] = msg.id
    save_config(cfg)
    await ctx.message.delete()

# ─── Auto-refresh 60s ─────────────────────────────────────────
@tasks.loop(seconds=60)
async def auto_refresh():
    for guild in bot.guilds:
        await refresh_all(guild)

@bot.event
async def on_ready():
    bot.add_view(PrendreServiceView())
    bot.add_view(EnServiceView())
    bot.add_view(EnPauseView())
    auto_refresh.start()
    print(f"✅ Bot connecté : {bot.user}")

bot.run(TOKEN)
