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
    seconds = int(max(0, seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h{m:02d}m{s:02d}s"

def get_elapsed(u):
    now = datetime.utcnow().timestamp()
    pauses = u.get("total_pauses", 0)
    if u["status"] == "paused":
        pauses += now - u["pause_start"]
    return max(0, now - u["start"] - pauses + u.get("bonus_seconds", 0))

def get_pause_duration(u):
    now = datetime.utcnow().timestamp()
    total = u.get("total_pauses", 0)
    if u["status"] == "paused":
        total += now - u["pause_start"]
    return total

# ─── Permissions ──────────────────────────────────────────────
PERM_KEYS = {
    "gestion":       "🔧 Rôle Gestion",
    "temps":         "⏱️ Rôle Temps",
    "comptage":      "📊 Rôle Comptage",
    "configuration": "⚙️ Rôle Configuration",
    "pointeuse":     "🕐 Rôle Pointeuse",
    "commande":      "💬 Rôle Commande",
}

def has_perm(interaction, perm):
    cfg = load_config()
    role_ids = cfg.get(f"roles_{perm}", [])
    # Si aucun rôle configuré, admins seulement
    if not role_ids:
        return interaction.user.guild_permissions.administrator
    # Si strict_mode OFF : admins passent toujours
    if not cfg.get("strict_mode") and interaction.user.guild_permissions.administrator:
        return True
    return any(r.id in role_ids for r in interaction.user.roles)

def has_perm_ctx(ctx, perm):
    cfg = load_config()
    role_ids = cfg.get(f"roles_{perm}", [])
    if not role_ids:
        return ctx.author.guild_permissions.administrator
    if not cfg.get("strict_mode") and ctx.author.guild_permissions.administrator:
        return True
    return any(r.id in role_ids for r in ctx.author.roles)

async def send_log(guild, message):
    cfg = load_config()
    ch_id = cfg.get("log_channel_id")
    if not ch_id:
        return
    ch = guild.get_channel(ch_id)
    if not ch:
        return
    embed = discord.Embed(description=message, color=0x95a5a6, timestamp=datetime.utcnow())
    embed.set_footer(text="Pointeuse • Log")
    try:
        await ch.send(embed=embed)
    except:
        pass

# ─── Embeds ───────────────────────────────────────────────────
async def build_pointeuse_embed(guild, data):
    embed = discord.Embed(title="🕐 POINTEUSE", color=0x1abc9c)
    en_service = [(uid, u) for uid, u in data.items() if u["status"] == "working"]
    en_pause = [(uid, u) for uid, u in data.items() if u["status"] == "paused"]
    lines = []
    for uid, u in en_service:
        member = guild.get_member(int(uid))
        name = member.display_name if member else f"<@{uid}>"
        lines.append(f"🟢 **{name}** — `{fmt(get_elapsed(u))}`")
    for uid, u in en_pause:
        member = guild.get_member(int(uid))
        name = member.display_name if member else f"<@{uid}>"
        lines.append(f"⏸️ **{name}** — `{fmt(get_elapsed(u))}` *(pause: {fmt(get_pause_duration(u))})*")
    embed.description = "\n".join(lines) if lines else "*Personne en service actuellement*"
    embed.set_footer(text=f"Blaine County Sheriff Office • {datetime.utcnow().strftime('%H:%M:%S')} UTC")
    return embed

async def build_gestion_embed(guild, data):
    now = datetime.utcnow()
    cfg = load_config()
    embed = discord.Embed(title="📊 PANNEAU DE GESTION", color=0xe74c3c, timestamp=now)
    en_service = [(uid, u) for uid, u in data.items() if u["status"] == "working"]
    en_pause = [(uid, u) for uid, u in data.items() if u["status"] == "paused"]
    hors_service = [(uid, u) for uid, u in data.items() if u["status"] == "off" and u.get("sessions")]

    if en_service:
        lines = []
        for uid, u in en_service:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            elapsed = get_elapsed(u)
            total_all = sum(s["duree_secondes"] for s in u.get("sessions", [])) + elapsed
            lines.append(f"🟢 **{name}**\n┣ Depuis : `{fmt(elapsed)}`\n┗ Total : `{fmt(total_all)}`")
        embed.add_field(name="━━━ EN SERVICE ━━━", value="\n\n".join(lines), inline=False)
    else:
        embed.add_field(name="━━━ EN SERVICE ━━━", value="*Personne*", inline=False)

    if en_pause:
        lines = []
        for uid, u in en_pause:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            elapsed = get_elapsed(u)
            total_all = sum(s["duree_secondes"] for s in u.get("sessions", [])) + elapsed
            lines.append(f"⏸️ **{name}**\n┣ Pause : `{fmt(get_pause_duration(u))}`\n┣ Travaillé : `{fmt(elapsed)}`\n┗ Total : `{fmt(total_all)}`")
        embed.add_field(name="━━━ EN PAUSE ━━━", value="\n\n".join(lines), inline=False)
    else:
        embed.add_field(name="━━━ EN PAUSE ━━━", value="*Personne*", inline=False)

    if hors_service:
        lines = []
        for uid, u in list(hors_service)[-5:]:
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            last = u["sessions"][-1]
            total_all = sum(s["duree_secondes"] for s in u.get("sessions", []))
            lines.append(f"⬛ **{name}**\n┣ Dernière : `{fmt(last['duree_secondes'])}` ({last['date']})\n┗ Total : `{fmt(total_all)}`")
        embed.add_field(name="━━━ HORS SERVICE ━━━", value="\n\n".join(lines), inline=False)

    if cfg.get("comptage_start"):
        debut = datetime.utcfromtimestamp(cfg["comptage_start"]).strftime("%d/%m/%y à %H:%M:%S")
        duree = fmt(now.timestamp() - cfg["comptage_start"])
        embed.add_field(name="━━━ COMPTAGE EN COURS ━━━", value=f"▶️ Démarré le `{debut}` UTC\nDurée : `{duree}`", inline=False)

    # Config résumé
    def fmt_roles(key):
        ids = cfg.get(f"roles_{key}", [])
        if not ids:
            return "`non configuré`"
        roles = [guild.get_role(rid) for rid in ids]
        return " ".join(r.mention for r in roles if r) or "`non configuré`"

    log_ch = guild.get_channel(cfg.get("log_channel_id", 0))
    cfg_lines = [f"📋 Logs : {log_ch.mention if log_ch else '`non configuré`'}"]
    for key, label in PERM_KEYS.items():
        cfg_lines.append(f"{label} : {fmt_roles(key)}")
    embed.add_field(name="━━━ CONFIGURATION ━━━", value="\n".join(cfg_lines), inline=False)

    total_en_ligne = len(en_service) + len(en_pause)
    embed.set_footer(text=f"👮 {total_en_ligne} agent(s) en ligne • Auto-refresh 3s")
    return embed

# ─── Refresh ──────────────────────────────────────────────────
async def refresh_pointeuse(guild, data):
    cfg = load_config()
    if cfg.get("pointeuse_channel_id") and cfg.get("pointeuse_msg_id"):
        ch = guild.get_channel(cfg["pointeuse_channel_id"])
        if ch:
            try:
                msg = await ch.fetch_message(cfg["pointeuse_msg_id"])
                await msg.edit(embed=await build_pointeuse_embed(guild, data))
            except:
                pass

async def refresh_gestion(guild, data):
    cfg = load_config()
    if cfg.get("gestion_channel_id") and cfg.get("gestion_msg_id"):
        ch = guild.get_channel(cfg["gestion_channel_id"])
        if ch:
            try:
                msg = await ch.fetch_message(cfg["gestion_msg_id"])
                await msg.edit(embed=await build_gestion_embed(guild, data), view=GestionView())
            except:
                pass

async def refresh_all(guild):
    data = load()
    await refresh_pointeuse(guild, data)
    await refresh_gestion(guild, data)

# ─── Vue Pointeuse ────────────────────────────────────────────
class PointeuseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def check(self, interaction):
        if not has_perm(interaction, "pointeuse"):
            await interaction.response.send_message("❌ Tu n'as pas le rôle requis.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="▶ Prendre service", style=discord.ButtonStyle.success, custom_id="pt_prendre", row=0)
    async def prendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if uid in data and data[uid]["status"] != "off":
            await interaction.response.send_message("⚠️ Tu es déjà en service !", ephemeral=True)
            return
        if uid not in data:
            data[uid] = {"status": "off", "start": None, "pause_start": None, "total_pauses": 0, "sessions": [], "bonus_seconds": 0}
        data[uid].update({"status": "working", "start": now, "pause_start": None, "total_pauses": 0, "bonus_seconds": 0})
        cfg = load_config()
        if cfg.get("comptage_start"):
            if "comptage_sessions" not in cfg: cfg["comptage_sessions"] = {}
            cfg["comptage_sessions"][uid] = {"start": now, "total": 0}
            save_config(cfg)
        save(data)
        await interaction.response.send_message("✅ Service démarré.", ephemeral=True)
        await send_log(interaction.guild, f"🟢 **{interaction.user.display_name}** a pris son service.")
        await refresh_all(interaction.guild)

    @discord.ui.button(label="⏸ Pause", style=discord.ButtonStyle.primary, custom_id="pt_pause", row=0)
    async def pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if data.get(uid, {}).get("status") != "working":
            await interaction.response.send_message("⚠️ Tu n'es pas en service.", ephemeral=True)
            return
        data[uid]["status"] = "paused"
        data[uid]["pause_start"] = now
        save(data)
        await interaction.response.send_message("⏸️ Pause enregistrée.", ephemeral=True)
        await send_log(interaction.guild, f"⏸️ **{interaction.user.display_name}** a pris une pause.")
        await refresh_all(interaction.guild)

    @discord.ui.button(label="▶ Reprendre", style=discord.ButtonStyle.secondary, custom_id="pt_reprendre", row=0)
    async def reprendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if data.get(uid, {}).get("status") != "paused":
            await interaction.response.send_message("⚠️ Tu n'es pas en pause.", ephemeral=True)
            return
        data[uid]["total_pauses"] += now - data[uid]["pause_start"]
        data[uid]["pause_start"] = None
        data[uid]["status"] = "working"
        save(data)
        await interaction.response.send_message("🟢 Service repris.", ephemeral=True)
        await send_log(interaction.guild, f"🟢 **{interaction.user.display_name}** a repris son service.")
        await refresh_all(interaction.guild)

    @discord.ui.button(label="⏹ Fin de service", style=discord.ButtonStyle.danger, custom_id="pt_fin", row=0)
    async def fin(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check(interaction): return
        data = load()
        uid = str(interaction.user.id)
        now = datetime.utcnow().timestamp()
        if data.get(uid, {}).get("status") == "off":
            await interaction.response.send_message("⚠️ Tu n'es pas en service.", ephemeral=True)
            return
        u = data[uid]
        if u["status"] == "paused":
            u["total_pauses"] += now - u["pause_start"]
        total = get_elapsed(u)
        cfg = load_config()
        if cfg.get("comptage_start") and "comptage_sessions" in cfg:
            cs = cfg["comptage_sessions"]
            if uid in cs and cs[uid].get("start"):
                cs[uid]["total"] += now - cs[uid]["start"]
                cs[uid]["start"] = None
            save_config(cfg)
        u["sessions"].append({"date": datetime.utcnow().strftime("%Y-%m-%d"), "duree_secondes": int(total)})
        u.update({"status": "off", "start": None, "pause_start": None, "total_pauses": 0, "bonus_seconds": 0})
        save(data)
        await interaction.response.send_message(f"✅ Fin de service — Temps: **{fmt(total)}**", ephemeral=True)
        await send_log(interaction.guild, f"⏹️ **{interaction.user.display_name}** a terminé son service — `{fmt(total)}`.")
        await refresh_all(interaction.guild)

# ─── Vue Gestion ──────────────────────────────────────────────
class GestionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⏹ Couper service", style=discord.ButtonStyle.danger, custom_id="admin_couper", row=0)
    async def couper(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "gestion"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        data = load()
        options = self._options(interaction.guild, data, ["working", "paused"])
        if not options:
            await interaction.response.send_message("Personne en service.", ephemeral=True)
            return
        await interaction.response.send_message("Sélectionne le membre :", view=SelectMembreView(options, "fin"), ephemeral=True)

    @discord.ui.button(label="⏸ Mettre en pause", style=discord.ButtonStyle.primary, custom_id="admin_pause", row=0)
    async def mettre_pause(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "gestion"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        data = load()
        options = self._options(interaction.guild, data, ["working"])
        if not options:
            await interaction.response.send_message("Personne en service actif.", ephemeral=True)
            return
        await interaction.response.send_message("Sélectionne le membre :", view=SelectMembreView(options, "pause"), ephemeral=True)

    @discord.ui.button(label="▶ Reprendre service", style=discord.ButtonStyle.secondary, custom_id="admin_reprendre", row=0)
    async def admin_reprendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "gestion"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        data = load()
        options = self._options(interaction.guild, data, ["paused"])
        if not options:
            await interaction.response.send_message("Personne en pause.", ephemeral=True)
            return
        await interaction.response.send_message("Sélectionne le membre :", view=SelectMembreView(options, "reprendre"), ephemeral=True)

    @discord.ui.button(label="➕ Ajouter temps", style=discord.ButtonStyle.success, custom_id="admin_add_time", row=1)
    async def add_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "temps"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        data = load()
        options = self._options_all(interaction.guild, data)
        if not options:
            await interaction.response.send_message("Aucun membre enregistré.", ephemeral=True)
            return
        await interaction.response.send_message("Sélectionne le membre :", view=SelectMembreView(options, "add_time"), ephemeral=True)

    @discord.ui.button(label="➖ Retirer temps", style=discord.ButtonStyle.danger, custom_id="admin_remove_time", row=1)
    async def remove_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "temps"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        data = load()
        options = self._options_all(interaction.guild, data)
        if not options:
            await interaction.response.send_message("Aucun membre enregistré.", ephemeral=True)
            return
        await interaction.response.send_message("Sélectionne le membre :", view=SelectMembreView(options, "remove_time"), ephemeral=True)

    @discord.ui.button(label="▶ Démarrer comptage", style=discord.ButtonStyle.success, custom_id="admin_comptage_start", row=2)
    async def comptage_start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "comptage"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        cfg = load_config()
        if cfg.get("comptage_start"):
            await interaction.response.send_message("⚠️ Un comptage est déjà en cours.", ephemeral=True)
            return
        now = datetime.utcnow().timestamp()
        data = load()
        sessions = {uid: {"start": now, "total": 0} for uid, u in data.items() if u["status"] in ("working", "paused")}
        cfg["comptage_start"] = now
        cfg["comptage_sessions"] = sessions
        save_config(cfg)
        debut_fmt = datetime.utcnow().strftime("%d/%m/%y à %H:%M:%S")
        await interaction.response.send_message(f"▶️ Comptage démarré le `{debut_fmt}` UTC", ephemeral=True)
        await send_log(interaction.guild, f"▶️ **{interaction.user.display_name}** a démarré un comptage.")
        await refresh_gestion(interaction.guild, data)

    @discord.ui.button(label="⏹ Terminer comptage", style=discord.ButtonStyle.danger, custom_id="admin_comptage_end", row=2)
    async def comptage_end(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "comptage"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        cfg = load_config()
        if not cfg.get("comptage_start"):
            await interaction.response.send_message("⚠️ Aucun comptage en cours.", ephemeral=True)
            return
        now = datetime.utcnow().timestamp()
        data = load()
        sessions = cfg.get("comptage_sessions", {})
        for uid, u in data.items():
            if u["status"] in ("working", "paused") and uid in sessions and sessions[uid].get("start"):
                sessions[uid]["total"] += now - sessions[uid]["start"]
        debut = datetime.utcfromtimestamp(cfg["comptage_start"]).strftime("%d/%m/%y à %H:%M")
        fin_str = datetime.utcnow().strftime("%d/%m/%y à %H:%M")
        embed = discord.Embed(
            title="📋 RÉSUMÉ DU COMPTAGE",
            description=f"**Du** `{debut}` **au** `{fin_str}` UTC\n**Durée :** `{fmt(now - cfg['comptage_start'])}`",
            color=0xf39c12, timestamp=datetime.utcnow()
        )
        if sessions:
            lines = [f"👮 **{(interaction.guild.get_member(int(uid)) or type('', (), {'display_name': f'ID:{uid}'})()).display_name}** — `{fmt(s['total'])}`"
                     for uid, s in sorted(sessions.items(), key=lambda x: x[1]["total"], reverse=True)]
            embed.add_field(name="Temps par agent", value="\n".join(lines), inline=False)
        cfg.pop("comptage_start", None)
        cfg.pop("comptage_sessions", None)
        save_config(cfg)
        await interaction.response.send_message(embed=embed)
        await send_log(interaction.guild, f"⏹️ **{interaction.user.display_name}** a terminé le comptage.")
        await refresh_gestion(interaction.guild, data)

    @discord.ui.button(label="⚙️ Configuration", style=discord.ButtonStyle.secondary, custom_id="admin_config", row=3)
    async def config(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_perm(interaction, "configuration"):
            await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
            return
        await interaction.response.send_message("Que veux-tu configurer ?", view=ConfigMenuView(), ephemeral=True)

    def _options(self, guild, data, statuts):
        options = []
        for uid, u in data.items():
            if u["status"] in statuts:
                member = guild.get_member(int(uid))
                name = member.display_name if member else f"ID:{uid}"
                label = {"working": "🟢 En service", "paused": "⏸️ En pause"}.get(u["status"], "")
                options.append(discord.SelectOption(label=name, value=uid, description=label))
        return options

    def _options_all(self, guild, data):
        options = []
        for uid, u in data.items():
            member = guild.get_member(int(uid))
            name = member.display_name if member else f"ID:{uid}"
            label = {"working": "🟢 En service", "paused": "⏸️ En pause", "off": "⬛ Hors service"}.get(u["status"], "")
            options.append(discord.SelectOption(label=name, value=uid, description=label))
        return options[:25]

# ─── Config Menu ──────────────────────────────────────────────
class ConfigMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="📋 Salon des logs", style=discord.ButtonStyle.secondary, row=0)
    async def cfg_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LogChannelModal())

    @discord.ui.button(label="🔧 Rôle Gestion", style=discord.ButtonStyle.secondary, row=0)
    async def cfg_gestion(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = ("## 🔧 Rôle Gestion\n\n"
               "Les membres avec ce rôle peuvent :\n"
               "- ⏹️ Couper le service de quelqu'un\n"
               "- ⏸️ Mettre quelqu'un en pause\n"
               "- ▶️ Reprendre le service de quelqu'un\n\n"
               "*Pour les superviseurs/gradés qui gèrent les agents en direct.*")
        await interaction.response.send_message(msg, view=ConfirmRoleView("gestion", "🔧 Rôle Gestion"), ephemeral=True)

    @discord.ui.button(label="⏱️ Rôle Temps", style=discord.ButtonStyle.secondary, row=0)
    async def cfg_temps(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = ("## ⏱️ Rôle Temps\n\n"
               "Les membres avec ce rôle peuvent :\n"
               "- ➕ Ajouter du temps à quelqu'un\n"
               "- ➖ Retirer du temps à quelqu'un\n\n"
               "*Pour les RH/responsables qui corrigent les temps de service.*")
        await interaction.response.send_message(msg, view=ConfirmRoleView("temps", "⏱️ Rôle Temps"), ephemeral=True)

    @discord.ui.button(label="📊 Rôle Comptage", style=discord.ButtonStyle.secondary, row=1)
    async def cfg_comptage(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = ("## 📊 Rôle Comptage\n\n"
               "Les membres avec ce rôle peuvent :\n"
               "- ▶️ Démarrer un comptage (enregistre qui travaille sur une période)\n"
               "- ⏹️ Terminer le comptage et voir le résumé de chaque agent\n\n"
               "*Pour les responsables qui font des bilans de service.*")
        await interaction.response.send_message(msg, view=ConfirmRoleView("comptage", "📊 Rôle Comptage"), ephemeral=True)

    @discord.ui.button(label="⚙️ Rôle Configuration", style=discord.ButtonStyle.secondary, row=1)
    async def cfg_configuration(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = ("## ⚙️ Rôle Configuration\n\n"
               "Les membres avec ce rôle peuvent :\n"
               "- Accéder au menu de configuration\n"
               "- Configurer les salons, rôles, mode strict\n\n"
               "⚠️ *Réservé aux admins du bot. Donne-le avec précaution.*")
        await interaction.response.send_message(msg, view=ConfirmRoleView("configuration", "⚙️ Rôle Configuration"), ephemeral=True)

    @discord.ui.button(label="🕐 Rôle Pointeuse", style=discord.ButtonStyle.secondary, row=2)
    async def cfg_pointeuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = ("## 🕐 Rôle Pointeuse\n\n"
               "Les membres avec ce rôle peuvent :\n"
               "- ▶️ Prendre leur service\n"
               "- ⏸️ Mettre en pause / reprendre\n"
               "- ⏹️ Terminer leur service\n\n"
               "*Si aucun rôle configuré ici, TOUT LE MONDE peut utiliser la pointeuse.*")
        await interaction.response.send_message(msg, view=ConfirmRoleView("pointeuse", "🕐 Rôle Pointeuse"), ephemeral=True)

    @discord.ui.button(label="💬 Rôle Commande", style=discord.ButtonStyle.secondary, row=2)
    async def cfg_commande(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg = ("## 💬 Rôle Commande\n\n"
               "Les membres avec ce rôle peuvent :\n"
               "- Utiliser `!pointeuse` pour créer le panneau pointeuse\n"
               "- Utiliser `!gestion` pour créer le panneau de gestion\n\n"
               "*Pour ceux qui déploient les panneaux dans les salons.*")
        await interaction.response.send_message(msg, view=ConfirmRoleView("commande", "💬 Rôle Commande"), ephemeral=True)

    async def _show_role_select(self, interaction, perm_key, title):
        await interaction.response.send_modal(RoleSearchModal(perm_key, title))

class ConfirmRoleView(discord.ui.View):
    def __init__(self, perm_key, title):
        super().__init__(timeout=60)
        self.perm_key = perm_key
        self.title = title

    @discord.ui.button(label="⚙️ Configurer ce rôle", style=discord.ButtonStyle.primary)
    async def configurer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RoleSearchModal(self.perm_key, self.title))

class RoleSearchModal(discord.ui.Modal):
    def __init__(self, perm_key, title):
        super().__init__(title=f"Recherche rôle — {title[:40]}")
        self.perm_key = perm_key
        self.perm_title = title
        self.recherche = discord.ui.TextInput(
            label="Nom du rôle (vide = afficher tous)",
            placeholder="Ex: Shérif, Deputy...",
            required=False,
            max_length=50
        )
        self.add_item(self.recherche)

    async def on_submit(self, interaction: discord.Interaction):
        query = self.recherche.value.strip().lower()
        roles = [r for r in interaction.guild.roles if not r.is_default() and not r.managed]
        if query:
            roles = [r for r in roles if query in r.name.lower()]
        if not roles:
            await interaction.response.send_message("❌ Aucun rôle trouvé.", ephemeral=True)
            return
        roles = roles[:25]
        cfg = load_config()
        current_ids = cfg.get(f"roles_{self.perm_key}", [])
        options = []
        for r in roles:
            opt = discord.SelectOption(label=r.name, value=str(r.id))
            if r.id in current_ids:
                opt.description = "✅ Actif"
            options.append(opt)
        view = RoleSelectView(self.perm_key, self.perm_title, options)
        await interaction.response.send_message(
            f"**{self.perm_title}**\nSélectionne les rôles (plusieurs possibles) :",
            view=view, ephemeral=True
        )

class LogChannelModal(discord.ui.Modal, title="Salon des logs"):
    valeur = discord.ui.TextInput(label="ID du salon", placeholder="Clic droit sur le salon → Copier l'ID (vide pour désactiver)", required=False, max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config()
        val = self.valeur.value.strip()
        if not val:
            cfg.pop("log_channel_id", None)
            await interaction.response.send_message("✅ Logs désactivés.", ephemeral=True)
        else:
            try:
                ch_id = int(val)
                ch = interaction.guild.get_channel(ch_id)
                if not ch:
                    await interaction.response.send_message("❌ Salon introuvable.", ephemeral=True)
                    return
                cfg["log_channel_id"] = ch_id
                await interaction.response.send_message(f"✅ Logs → {ch.mention}", ephemeral=True)
            except ValueError:
                await interaction.response.send_message("❌ ID invalide.", ephemeral=True)
                return
        save_config(cfg)
        await refresh_gestion(interaction.guild, load())

class RoleSelectView(discord.ui.View):
    def __init__(self, perm_key, title, options):
        super().__init__(timeout=60)
        self.perm_key = perm_key
        self.title = title
        select = discord.ui.Select(
            placeholder=f"Choisir les rôles pour {title}...",
            options=options,
            min_values=0,
            max_values=min(len(options), 25)
        )
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        selected_ids = [int(v) for v in interaction.data["values"]]
        cfg = load_config()
        cfg[f"roles_{self.perm_key}"] = selected_ids
        save_config(cfg)
        if selected_ids:
            roles = [interaction.guild.get_role(rid) for rid in selected_ids]
            names = ", ".join(f"`{r.name}`" for r in roles if r)
            await interaction.response.send_message(f"✅ Rôles configurés : {names}", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Rôles supprimés (admins seulement).", ephemeral=True)
        await refresh_gestion(interaction.guild, load())

# ─── Select Membre & Modal Temps ──────────────────────────────
class SelectMembreView(discord.ui.View):
    def __init__(self, options, action):
        super().__init__(timeout=60)
        self.action = action
        select = discord.ui.Select(placeholder="Choisir un membre...", options=options)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        uid = interaction.data["values"][0]
        data = load()
        now = datetime.utcnow().timestamp()
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"ID:{uid}"

        if self.action == "fin":
            u = data.get(uid)
            if not u or u["status"] == "off":
                await interaction.response.send_message(f"⚠️ **{name}** n'est pas en service.", ephemeral=True)
                return
            if u["status"] == "paused":
                u["total_pauses"] += now - u["pause_start"]
            total = get_elapsed(u)
            cfg = load_config()
            if cfg.get("comptage_start") and "comptage_sessions" in cfg:
                cs = cfg["comptage_sessions"]
                if uid in cs and cs[uid].get("start"):
                    cs[uid]["total"] += now - cs[uid]["start"]
                    cs[uid]["start"] = None
                save_config(cfg)
            u["sessions"].append({"date": datetime.utcnow().strftime("%Y-%m-%d"), "duree_secondes": int(total)})
            u.update({"status": "off", "start": None, "pause_start": None, "total_pauses": 0, "bonus_seconds": 0})
            save(data)
            await interaction.response.send_message(f"✅ **{name}** coupé — `{fmt(total)}`.", ephemeral=True)
            await send_log(interaction.guild, f"⏹️ **{interaction.user.display_name}** a coupé **{name}** — `{fmt(total)}`.")
            await refresh_all(interaction.guild)

        elif self.action == "pause":
            data[uid]["status"] = "paused"
            data[uid]["pause_start"] = now
            save(data)
            await interaction.response.send_message(f"⏸️ **{name}** mis en pause.", ephemeral=True)
            await send_log(interaction.guild, f"⏸️ **{interaction.user.display_name}** a mis **{name}** en pause.")
            await refresh_all(interaction.guild)

        elif self.action == "reprendre":
            data[uid]["total_pauses"] += now - data[uid]["pause_start"]
            data[uid]["pause_start"] = None
            data[uid]["status"] = "working"
            save(data)
            await interaction.response.send_message(f"🟢 **{name}** a repris.", ephemeral=True)
            await send_log(interaction.guild, f"🟢 **{interaction.user.display_name}** a repris le service de **{name}**.")
            await refresh_all(interaction.guild)

        elif self.action in ("add_time", "remove_time"):
            await interaction.response.send_modal(TempsModal(uid=uid, name=name, action=self.action))

class TempsModal(discord.ui.Modal):
    def __init__(self, uid, name, action):
        super().__init__(title=f"{'Ajouter' if action == 'add_time' else 'Retirer'} du temps — {name}")
        self.uid = uid
        self.action = action
        self.heures = discord.ui.TextInput(label="Heures", placeholder="0", required=False, max_length=3)
        self.minutes = discord.ui.TextInput(label="Minutes", placeholder="0", required=False, max_length=3)
        self.add_item(self.heures)
        self.add_item(self.minutes)

    async def on_submit(self, interaction: discord.Interaction):
        data = load()
        try:
            h = int(self.heures.value or 0)
            m = int(self.minutes.value or 0)
        except ValueError:
            await interaction.response.send_message("⚠️ Valeurs invalides.", ephemeral=True)
            return
        seconds = h * 3600 + m * 60
        uid = self.uid
        if uid not in data:
            data[uid] = {"status": "off", "start": None, "pause_start": None, "total_pauses": 0, "sessions": [], "bonus_seconds": 0}
        if "bonus_seconds" not in data[uid]:
            data[uid]["bonus_seconds"] = 0
        if data[uid]["status"] == "off":
            if not data[uid].get("sessions"):
                data[uid]["sessions"] = [{"date": datetime.utcnow().strftime("%Y-%m-%d"), "duree_secondes": 0}]
            if self.action == "add_time":
                data[uid]["sessions"][-1]["duree_secondes"] += seconds
            else:
                data[uid]["sessions"][-1]["duree_secondes"] = max(0, data[uid]["sessions"][-1]["duree_secondes"] - seconds)
        else:
            data[uid]["bonus_seconds"] += seconds if self.action == "add_time" else -seconds
        save(data)
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"ID:{uid}"
        symbol = "➕" if self.action == "add_time" else "➖"
        await interaction.response.send_message(f"{symbol} `{h}h{m:02d}m` {'ajouté à' if self.action == 'add_time' else 'retiré à'} **{name}**", ephemeral=True)
        await send_log(interaction.guild, f"{symbol} **{interaction.user.display_name}** a {'ajouté' if self.action == 'add_time' else 'retiré'} `{h}h{m:02d}m` à **{name}**.")
        await refresh_all(interaction.guild)

# ─── Commandes ────────────────────────────────────────────────
@bot.command(name="pointeuse")
async def pointeuse_cmd(ctx):
    if not has_perm_ctx(ctx, "commande"):
        await ctx.send("❌ Permission refusée.", delete_after=5)
        return
    data = load()
    embed = await build_pointeuse_embed(ctx.guild, data)
    msg = await ctx.send(embed=embed, view=PointeuseView())
    cfg = load_config()
    cfg["pointeuse_channel_id"] = ctx.channel.id
    cfg["pointeuse_msg_id"] = msg.id
    save_config(cfg)
    await ctx.message.delete()

@bot.command(name="gestion")
async def gestion_cmd(ctx):
    if not has_perm_ctx(ctx, "commande"):
        await ctx.send("❌ Permission refusée.", delete_after=5)
        return
    data = load()
    embed = await build_gestion_embed(ctx.guild, data)
    msg = await ctx.send(embed=embed, view=GestionView())
    cfg = load_config()
    cfg["gestion_channel_id"] = ctx.channel.id
    cfg["gestion_msg_id"] = msg.id
    save_config(cfg)
    await ctx.message.delete()

@tasks.loop(seconds=3)
async def auto_refresh():
    for guild in bot.guilds:
        await refresh_all(guild)

@bot.event
async def on_ready():
    bot.add_view(PointeuseView())
    bot.add_view(GestionView())
    auto_refresh.start()
    print(f"✅ Bot connecté : {bot.user}")

bot.run(TOKEN)
