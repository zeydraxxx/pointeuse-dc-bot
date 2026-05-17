import discord
from discord.ext import commands
from datetime import datetime, timedelta
import json
import os

TOKEN = os.environ["TOKEN"]
DATA_FILE = "pointages.json"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ─── Données ────────────────────────────────────────────────
def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(data, uid):
    uid = str(uid)
    if uid not in data:
        data[uid] = {"status": "off", "start": None, "pause_start": None, "total_pauses": 0, "sessions": []}
    return data[uid]

def fmt_duration(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h {m:02d}m {s:02d}s"

# ─── Vue embed ────────────────────────────────────────────────
def make_embed(user: discord.Member, u: dict):
    now = datetime.utcnow().timestamp()
    status = u["status"]

    if status == "off":
        color = discord.Color.dark_gray()
        desc = "⏹️ Hors service"
    elif status == "working":
        elapsed = now - u["start"] - u["total_pauses"]
        color = discord.Color.green()
        desc = f"🟢 En service — **{fmt_duration(elapsed)}**"
    elif status == "paused":
        elapsed = now - u["start"] - u["total_pauses"] - (now - u["pause_start"])
        color = discord.Color.orange()
        desc = f"⏸️ En pause — Temps travaillé: **{fmt_duration(elapsed)}**"
    else:
        color = discord.Color.dark_gray()
        desc = "Inconnu"

    embed = discord.Embed(title=f"⏱️ Pointeuse — {user.display_name}", description=desc, color=color)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=f"Mis à jour: {datetime.utcnow().strftime('%H:%M:%S')} UTC")
    return embed

# ─── Vue boutons ─────────────────────────────────────────────
class PointeuseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="▶ Pointer", style=discord.ButtonStyle.success, custom_id="btn_start")
    async def btn_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        u = get_user(data, interaction.user.id)
        now = datetime.utcnow().timestamp()

        if u["status"] == "working":
            await interaction.response.send_message("⚠️ Tu es déjà en service !", ephemeral=True)
            return
        if u["status"] == "paused":
            await interaction.response.send_message("⚠️ Tu es en pause, reprends d'abord !", ephemeral=True)
            return

        u["status"] = "working"
        u["start"] = now
        u["total_pauses"] = 0
        u["pause_start"] = None
        save(data)
        await interaction.response.edit_message(embed=make_embed(interaction.user, u), view=self)

    @discord.ui.button(label="⏸ Pause", style=discord.ButtonStyle.primary, custom_id="btn_pause")
    async def btn_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        u = get_user(data, interaction.user.id)
        now = datetime.utcnow().timestamp()

        if u["status"] != "working":
            await interaction.response.send_message("⚠️ Tu dois être en service pour faire une pause.", ephemeral=True)
            return

        u["status"] = "paused"
        u["pause_start"] = now
        save(data)
        await interaction.response.edit_message(embed=make_embed(interaction.user, u), view=self)

    @discord.ui.button(label="▶ Reprendre", style=discord.ButtonStyle.secondary, custom_id="btn_resume")
    async def btn_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        u = get_user(data, interaction.user.id)
        now = datetime.utcnow().timestamp()

        if u["status"] != "paused":
            await interaction.response.send_message("⚠️ Tu n'es pas en pause.", ephemeral=True)
            return

        u["total_pauses"] += now - u["pause_start"]
        u["pause_start"] = None
        u["status"] = "working"
        save(data)
        await interaction.response.edit_message(embed=make_embed(interaction.user, u), view=self)

    @discord.ui.button(label="⏹ Dépointer", style=discord.ButtonStyle.danger, custom_id="btn_stop")
    async def btn_stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load()
        u = get_user(data, interaction.user.id)
        now = datetime.utcnow().timestamp()

        if u["status"] == "off":
            await interaction.response.send_message("⚠️ Tu n'es pas en service.", ephemeral=True)
            return

        if u["status"] == "paused":
            u["total_pauses"] += now - u["pause_start"]

        total_worked = now - u["start"] - u["total_pauses"]
        session = {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "heure": datetime.utcnow().strftime("%H:%M"),
            "duree_secondes": int(total_worked)
        }
        u["sessions"].append(session)
        u["status"] = "off"
        u["start"] = None
        u["pause_start"] = None
        u["total_pauses"] = 0
        save(data)

        embed = make_embed(interaction.user, u)
        embed.add_field(name="✅ Session terminée", value=f"Temps travaillé: **{fmt_duration(total_worked)}**", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

# ─── Commandes ───────────────────────────────────────────────
@bot.command(name="pointeuse")
async def pointeuse(ctx):
    """Affiche la pointeuse avec les boutons"""
    data = load()
    u = get_user(data, ctx.author.id)
    save(data)
    view = PointeuseView()
    await ctx.send(embed=make_embed(ctx.author, u), view=view)

@bot.command(name="historique")
async def historique(ctx):
    """Affiche les dernières sessions"""
    data = load()
    u = get_user(data, ctx.author.id)
    sessions = u.get("sessions", [])

    if not sessions:
        await ctx.send("Aucune session enregistrée.", ephemeral=True)
        return

    embed = discord.Embed(title=f"📋 Historique — {ctx.author.display_name}", color=discord.Color.blurple())
    for s in sessions[-10:][::-1]:
        embed.add_field(
            name=f"📅 {s['date']} à {s['heure']}",
            value=f"⏱️ {fmt_duration(s['duree_secondes'])}",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="reset")
async def reset(ctx):
    """Remet à zéro ta session en cours"""
    data = load()
    u = get_user(data, ctx.author.id)
    u["status"] = "off"
    u["start"] = None
    u["pause_start"] = None
    u["total_pauses"] = 0
    save(data)
    await ctx.send("✅ Session réinitialisée.")

@bot.event
async def on_ready():
    bot.add_view(PointeuseView())  # Persistance des boutons au redémarrage
    print(f"✅ Bot connecté : {bot.user}")

bot.run(TOKEN)
