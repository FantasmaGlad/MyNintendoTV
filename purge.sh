#!/bin/bash
# ------------------------------------------------------------------------------
# MonServeurEmu — Script de desinstallation complete et de purge totale
# Ce script doit etre execute avec des droits administrateur (sudo ./purge.sh)
# ------------------------------------------------------------------------------

set -e

# ── Couleurs ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log_step()  { echo -e "\n${BLUE}${BOLD}[$1]${NC} $2"; }
log_ok()    { echo -e "  ${GREEN}OK :${NC} $1"; }
log_warn()  { echo -e "  ${YELLOW}--${NC} $1"; }
log_info()  { echo -e "  ${CYAN}..${NC} $1"; }

# ==============================================================================
# [0] Verification des privileges
# ==============================================================================
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}${BOLD}Erreur :${NC} Ce script doit etre execute en tant que root."
    echo "Usage : sudo ./purge.sh"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
if [ "$USER_NAME" = "root" ]; then
    DETECTED_OWNER=$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo "")
    if [ -n "$DETECTED_OWNER" ] && [ "$DETECTED_OWNER" != "root" ]; then
        USER_NAME="$DETECTED_OWNER"
    else
        echo -e "${RED}Impossible de determiner l'utilisateur reel.${NC}"
        echo "Relancez avec : sudo -E ./purge.sh"
        exit 1
    fi
fi

if ! id "$USER_NAME" &>/dev/null; then
    echo -e "${RED}L'utilisateur '$USER_NAME' n'existe pas.${NC}"
    exit 1
fi

USER_UID=$(id -u "$USER_NAME")
USER_HOME=$(eval echo "~$USER_NAME")

echo -e "${BOLD}+--------------------------------------------------------------+${NC}"
echo -e "${BOLD}|        MonServeurEmu — Desinstallation Complete              |${NC}"
echo -e "${BOLD}+--------------------------------------------------------------+${NC}"
echo -e "  Utilisateur : ${CYAN}$USER_NAME${NC}"
echo -e "  Projet      : ${CYAN}$PROJECT_DIR${NC}"

# ==============================================================================
# [1] Arret et desactivation du service systemd --user
# ==============================================================================
log_step "1/11" "Arret et desactivation du service systemd..."

runuser -l "$USER_NAME" -c "XDG_RUNTIME_DIR=/run/user/$USER_UID systemctl --user stop serveur_jeu.service" 2>/dev/null || true
runuser -l "$USER_NAME" -c "XDG_RUNTIME_DIR=/run/user/$USER_UID systemctl --user disable serveur_jeu.service" 2>/dev/null || true

SERVICE_FILE="$USER_HOME/.config/systemd/user/serveur_jeu.service"
if [ -f "$SERVICE_FILE" ]; then
    rm -f "$SERVICE_FILE"
    log_ok "Fichier de service systemd supprime"
else
    log_warn "Aucun service systemd a supprimer"
fi

runuser -l "$USER_NAME" -c "XDG_RUNTIME_DIR=/run/user/$USER_UID systemctl --user daemon-reload" 2>/dev/null || true

# ==============================================================================
# [2] Desactivation du linger
# ==============================================================================
log_step "2/11" "Desactivation du linger (lancement au boot)..."
loginctl disable-linger "$USER_NAME" 2>/dev/null || true
log_ok "Linger desactive"

# ==============================================================================
# [3] Suppression de la session kiosk dediee
# ==============================================================================
log_step "3/11" "Suppression de la session kiosk dediee..."

# Script de session
if [ -f "/usr/local/bin/emu-kiosk-session" ]; then
    rm -f "/usr/local/bin/emu-kiosk-session"
    log_ok "Script de session kiosk supprime"
fi

# Fichier de session X
if [ -f "/usr/share/xsessions/emu-kiosk.desktop" ]; then
    rm -f "/usr/share/xsessions/emu-kiosk.desktop"
    log_ok "Session X 'emu-kiosk' supprimee"
fi

# Configuration openbox du kiosk
if [ -d "$USER_HOME/.config/openbox" ]; then
    rm -rf "$USER_HOME/.config/openbox"
    log_ok "Configuration openbox supprimee"
fi

# Ancien autostart (migration)
rm -f "$USER_HOME/.config/autostart/emu-kiosk.desktop" 2>/dev/null || true

# ==============================================================================
# [4] Restauration du gestionnaire d'affichage (autologin)
# ==============================================================================
log_step "4/11" "Restauration de la configuration du gestionnaire d'affichage..."

DM_RESTORED=false

# GDM3
GDM_CONF="/etc/gdm3/custom.conf"
if [ -f "${GDM_CONF}.emu-backup" ]; then
    cp "${GDM_CONF}.emu-backup" "$GDM_CONF"
    rm -f "${GDM_CONF}.emu-backup"
    log_ok "Configuration GDM3 restauree depuis la sauvegarde"
    DM_RESTORED=true
elif [ -f "$GDM_CONF" ] && grep -q "MonServeurEmu" "$GDM_CONF" 2>/dev/null; then
    # Pas de backup, remettre la configuration par defaut
    cat > "$GDM_CONF" <<EOF
# GDM configuration storage
[daemon]

[security]

[xdmcp]

[chooser]

[debug]
EOF
    log_ok "Configuration GDM3 reinitialise (defaut)"
    DM_RESTORED=true
fi

# LightDM
LIGHTDM_CONF="/etc/lightdm/lightdm.conf"
if [ -f "${LIGHTDM_CONF}.emu-backup" ]; then
    cp "${LIGHTDM_CONF}.emu-backup" "$LIGHTDM_CONF"
    rm -f "${LIGHTDM_CONF}.emu-backup"
    log_ok "Configuration LightDM restauree depuis la sauvegarde"
    DM_RESTORED=true
elif [ -f "$LIGHTDM_CONF" ] && grep -q "MonServeurEmu" "$LIGHTDM_CONF" 2>/dev/null; then
    rm -f "$LIGHTDM_CONF"
    log_ok "Configuration LightDM kiosk supprimee"
    DM_RESTORED=true
fi

# SDDM
SDDM_CONF="/etc/sddm.conf.d/emu-kiosk.conf"
if [ -f "$SDDM_CONF" ]; then
    rm -f "$SDDM_CONF"
    log_ok "Configuration SDDM kiosk supprimee"
    DM_RESTORED=true
fi

# AccountsService
ACCOUNTS_FILE="/var/lib/AccountsService/users/$USER_NAME"
if [ -f "$ACCOUNTS_FILE" ] && grep -q "emu-kiosk" "$ACCOUNTS_FILE" 2>/dev/null; then
    rm -f "$ACCOUNTS_FILE"
    log_ok "Configuration AccountsService supprimee"
    DM_RESTORED=true
fi

if [ "$DM_RESTORED" = false ]; then
    log_warn "Aucune configuration de gestionnaire d'affichage a restaurer"
fi

# ==============================================================================
# [5] Desinstallation de MelonDS (Flatpak) et ses configurations
# ==============================================================================
log_step "5/11" "Desinstallation de MelonDS (Flatpak) et de ses configurations..."
flatpak uninstall --delete-data -y net.kuribo64.melonDS 2>/dev/null || true
runuser -l "$USER_NAME" -c "flatpak uninstall --delete-data -y net.kuribo64.melonDS" 2>/dev/null || true
log_ok "MelonDS desinstalle"

# ==============================================================================
# [6] Restauration d'input-remapper
# ==============================================================================
log_step "6/11" "Restauration des injections automatiques d'input-remapper..."
runuser -l "$USER_NAME" -c "input-remapper-control --command autoload" 2>/dev/null || true
log_ok "input-remapper restaure"

# ==============================================================================
# [7] Nettoyage des residus de configuration utilisateur
# ==============================================================================
log_step "7/11" "Nettoyage des residus de configuration utilisateur..."
rm -rf "$USER_HOME/.var/app/net.kuribo64.melonDS"
log_ok "Configurations MelonDS supprimees"

# ==============================================================================
# [8] Suppression des regles udev
# ==============================================================================
log_step "8/11" "Suppression des regles udev..."
rm -f "/etc/udev/rules.d/99-gamepad-evdev.rules" 2>/dev/null
udevadm control --reload-rules 2>/dev/null || true
log_ok "Regles udev supprimees"

# ==============================================================================
# [9] Desinstallation des paquets dedies
# ==============================================================================
log_step "9/11" "Desinstallation des paquets dedies..."

# Chromium
apt-get purge -y chromium chromium-browser 2>/dev/null || true
log_ok "Chromium desinstalle"

# Paquets kiosk (openbox, unclutter)
apt-get purge -y openbox unclutter 2>/dev/null || true
log_ok "Openbox et unclutter desinstalles"

# Nettoyage des dependances orphelines
apt-get autoremove -y 2>/dev/null || true
log_ok "Dependances orphelines nettoyees"

# ==============================================================================
# [10] Suppression du venv Python et du dossier projet
# ==============================================================================
log_step "10/11" "Suppression du venv Python..."

if [ -d "$PROJECT_DIR/.venv" ]; then
    rm -rf "$PROJECT_DIR/.venv"
    log_ok "Venv Python supprime"
else
    log_warn "Aucun venv a supprimer"
fi

log_step "10/11 (bis)" "Suppression definitive du dossier du projet (Code et ROMs) : $PROJECT_DIR..."
find "$PROJECT_DIR" -mindepth 1 -not -name "purge.sh" -delete 2>/dev/null || true

# ==============================================================================
# [11] Autodestruction finale
# ==============================================================================
log_step "11/11" "Finalisation et autodestruction..."
rm -f "$PROJECT_DIR/purge.sh"
rmdir "$PROJECT_DIR" 2>/dev/null || true

echo ""
echo -e "${BOLD}+--------------------------------------------------------------+${NC}"
echo -e "${GREEN}  Desinstallation totale et purge complete effectuees.${NC}"
echo -e "${BOLD}+--------------------------------------------------------------+${NC}"
echo ""
echo -e "  La machine est revenue a son etat initial."
echo -e "  Au prochain redemarrage, la session de bureau par defaut sera utilisee."
echo ""
