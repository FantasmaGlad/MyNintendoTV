#!/usr/bin/env bash
# ==============================================================================
# MyNintendoTV — Script d'installation universel
# Compatible : Ubuntu 20.04+, Debian 11+, et dérivés (Mint, Pop!_OS, etc.)
# Environnements : GNOME/Wayland, XFCE/X11, KDE, Sway, etc.
# ==============================================================================

set -euo pipefail

# ── Couleurs ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log_step()  { echo -e "\n${BLUE}${BOLD}[$1]${NC} $2"; }
log_ok()    { echo -e "  ${GREEN}✅ $1${NC}"; }
log_warn()  { echo -e "  ${YELLOW}⚠️  $1${NC}"; }
log_err()   { echo -e "  ${RED}❌ $1${NC}"; }
log_info()  { echo -e "  ${CYAN}ℹ  $1${NC}"; }

# ── Constantes ────────────────────────────────────────────────────────────────
REQUIRED_PORT=8080
FLATPAK_APP="net.kuribo64.melonDS"
SERVICE_NAME="mynintendotv.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$PROJECT_DIR/mynintendotv.py"
VENV_DIR="$PROJECT_DIR/.venv"
INSTALL_ERRORS=0

# ── Variables détectées ───────────────────────────────────────────────────────
USE_VENV=false
PYTHON_BIN="/usr/bin/python3"
OS_ID="unknown"
OS_VERSION_ID="unknown"
OS_PRETTY="Unknown Linux"
ARCH=""

# ==============================================================================
# [0] Vérification des privilèges
# ==============================================================================
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}${BOLD}Erreur :${NC} Ce script doit être exécuté en tant que root."
    echo "Usage : sudo ./install.sh"
    exit 1
fi

REAL_USER="${SUDO_USER:-$USER}"
if [ "$REAL_USER" = "root" ]; then
    # Tenter de détecter l'utilisateur réel via le propriétaire du dossier projet
    DETECTED_OWNER=$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo "root")
    if [ "$DETECTED_OWNER" != "root" ]; then
        REAL_USER="$DETECTED_OWNER"
    else
        echo -e "${RED}Impossible de déterminer l'utilisateur réel.${NC}"
        echo "Relancez avec : sudo -u <votre_user> ./install.sh"
        exit 1
    fi
fi

REAL_HOME=$(eval echo "~$REAL_USER")
REAL_UID=$(id -u "$REAL_USER")
REAL_GID=$(id -g "$REAL_USER")

echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║          MyNintendoTV — Installation Automatique           ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo -e "  Utilisateur : ${CYAN}$REAL_USER${NC} (UID $REAL_UID)"
echo -e "  Projet      : ${CYAN}$PROJECT_DIR${NC}"

# ==============================================================================
# [0.5] Sélection de la langue par défaut du firmware
# ==============================================================================
echo -e "\n${BLUE}${BOLD}[LANGUE]${NC} Configuration de la langue par défaut pour vos jeux DS (Firmware) :"
echo "  1) Anglais (English)"
echo "  2) Français (French) - [Recommandé]"
echo "  3) Allemand (German)"
echo "  4) Italien (Italian)"
echo "  5) Espagnol (Spanish)"
echo "  6) Néerlandais (Dutch)"
echo "  7) Japonais (Japanese)"
read -p "Entrez votre choix (1-7) [2] : " LANG_CHOICE

case "${LANG_CHOICE:-2}" in
    1) FIRMWARE_LANG=1 ;;
    2) FIRMWARE_LANG=2 ;;
    3) FIRMWARE_LANG=3 ;;
    4) FIRMWARE_LANG=4 ;;
    5) FIRMWARE_LANG=5 ;;
    6) FIRMWARE_LANG=7 ;; # Dutch dans melonDS est 7
    7) FIRMWARE_LANG=0 ;; # Japanese dans melonDS est 0
    *) FIRMWARE_LANG=2 ;;
esac

# Générer le fichier config.json
CONFIG_FILE="$PROJECT_DIR/config.json"
echo "{\"firmware_language\": $FIRMWARE_LANG}" > "$CONFIG_FILE"
chown "$REAL_USER:$REAL_USER" "$CONFIG_FILE"
log_ok "Langue configurée : code de langue Nintendo DS ($FIRMWARE_LANG) sauvegardé."


# ==============================================================================
# [1] Détection OS et architecture
# ==============================================================================
log_step "1/10" "Détection du système d'exploitation..."

if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_VERSION_ID="${VERSION_ID:-unknown}"
    OS_PRETTY="${PRETTY_NAME:-Unknown}"
else
    log_warn "Fichier /etc/os-release introuvable. Détection limitée."
fi

ARCH=$(uname -m)

log_info "OS      : $OS_PRETTY"
log_info "Arch    : $ARCH"
log_info "Kernel  : $(uname -r)"

if [ "$ARCH" != "x86_64" ] && [ "$ARCH" != "amd64" ]; then
    log_warn "Architecture $ARCH détectée. MelonDS Flatpak peut ne pas être disponible."
    log_warn "Seul x86_64 est officiellement supporté pour le moment."
fi

# Vérifier la famille de distribution
case "$OS_ID" in
    ubuntu|debian|linuxmint|pop|elementary|zorin|neon)
        log_ok "Distribution compatible détectée ($OS_ID)"
        ;;
    *)
        if echo "${ID_LIKE:-}" | grep -qE "debian|ubuntu"; then
            log_ok "Distribution basée Debian/Ubuntu détectée ($OS_ID)"
        else
            log_warn "Distribution non testée ($OS_ID). L'installation peut nécessiter des ajustements."
        fi
        ;;
esac

# Vérifier l'espace disque (avertissement si < 5 Go)
# 5 Go est raisonnable pour l'OS, Flatpak, MelonDS et quelques jeux
FREE_SPACE_MB=$(df -m "$PROJECT_DIR" | awk 'NR==2 {print $4}')
if [ -n "$FREE_SPACE_MB" ] && [ "$FREE_SPACE_MB" -lt 5120 ]; then
    log_warn "Espace disque faible détecté ! Il reste moins de 5 Go libres."
    log_warn "Le système (Flatpak, émulateur) et vos jeux nécessitent au minimum 3 à 5 Go."
    sleep 2
else
    FREE_SPACE_GB=$(awk "BEGIN {printf \"%.1f\", $FREE_SPACE_MB / 1024}")
    log_ok "Espace disque suffisant ($FREE_SPACE_GB Go libres)."
fi

# ==============================================================================
# [2] Installation des dépendances système
# ==============================================================================
log_step "2/10" "Installation des dépendances système..."

apt-get update -qq 2>/dev/null

# Dépendances obligatoires (toujours disponibles)
DEPS_REQUIRED=(python3 python3-venv flatpak psmisc git openbox xterm)

# Dépendances optionnelles (vérifier la disponibilité)
DEPS_OPTIONAL=(x11-xserver-utils)

# python3-watchdog : essayer apt, sinon venv
if apt-cache show python3-watchdog &>/dev/null 2>&1; then
    DEPS_REQUIRED+=(python3-watchdog)
    log_info "python3-watchdog disponible via apt"
else
    USE_VENV=true
    log_warn "python3-watchdog non disponible via apt → installation via venv Python"
fi

# python3-evdev : essayer apt, sinon venv
if apt-cache show python3-evdev &>/dev/null 2>&1; then
    DEPS_REQUIRED+=(python3-evdev)
    log_info "python3-evdev disponible via apt"
else
    USE_VENV=true
    log_warn "python3-evdev non disponible via apt → installation via venv Python"
fi

# input-remapper : optionnel
if apt-cache show input-remapper &>/dev/null 2>&1; then
    DEPS_OPTIONAL+=(input-remapper)
fi

# Installer les paquets obligatoires
log_info "Paquets obligatoires : ${DEPS_REQUIRED[*]}"
if ! apt-get install -y "${DEPS_REQUIRED[@]}" >/dev/null 2>&1; then
    log_err "Échec de l'installation des paquets obligatoires."
    exit 1
fi
log_ok "Paquets obligatoires installés"

# Installer les paquets optionnels un par un (ignorer les échecs)
for pkg in "${DEPS_OPTIONAL[@]}"; do
    if apt-get install -y "$pkg" >/dev/null 2>&1; then
        log_ok "$pkg installé"
    else
        log_warn "$pkg non disponible — fonctionnalité réduite"
    fi
done

# Installation robuste de ydotool (indispensable pour le mappage manette)
if apt-get install -y ydotool >/dev/null 2>&1; then
    log_ok "ydotool installé via apt"
else
    log_info "ydotool non trouvé via apt. Téléchargement de la version statique depuis GitHub..."
    YDO_URL_BASE="https://github.com/ReimuNotMoe/ydotool/releases/download/v1.0.4"
    if wget -qO /usr/local/bin/ydotool "$YDO_URL_BASE/ydotool-release-ubuntu-latest" && \
       wget -qO /usr/local/bin/ydotoold "$YDO_URL_BASE/ydotoold-release-ubuntu-latest"; then
        chmod +x /usr/local/bin/ydotool /usr/local/bin/ydotoold
        log_ok "ydotool installé manuellement (statique)"
    else
        log_warn "Échec de l'installation de ydotool. Le mappage automatique ne fonctionnera pas."
    fi
fi


# ==============================================================================
# [3] Configuration Python (venv si nécessaire)
# ==============================================================================
log_step "3/10" "Configuration de l'environnement Python..."

if [ "$USE_VENV" = true ]; then
    log_info "Création du venv Python dans $VENV_DIR..."

    # Créer le venv en tant qu'utilisateur réel
    if [ -d "$VENV_DIR" ]; then
        log_info "Venv existant détecté, mise à jour..."
    fi
    runuser -l "$REAL_USER" -c "python3 -m venv '$VENV_DIR'" 2>/dev/null || \
        su - "$REAL_USER" -c "python3 -m venv '$VENV_DIR'"

    PYTHON_BIN="$VENV_DIR/bin/python3"

    log_info "Installation de watchdog dans le venv..."
    runuser -l "$REAL_USER" -c "'$VENV_DIR/bin/pip' install -q -r '$PROJECT_DIR/requirements.txt'" 2>/dev/null || \
        su - "$REAL_USER" -c "'$VENV_DIR/bin/pip' install -q -r '$PROJECT_DIR/requirements.txt'"

    log_ok "Venv configuré avec watchdog"
else
    PYTHON_BIN="/usr/bin/python3"
    log_ok "Utilisation du Python système avec python3-watchdog (apt)"
fi

log_info "Python utilisé : $PYTHON_BIN"

# ==============================================================================
# [4] Installation Flatpak + MelonDS
# ==============================================================================
log_step "4/10" "Installation de l'émulateur MelonDS via Flatpak..."

# Ajouter le dépôt Flathub
flatpak remote-add --if-not-exists flathub \
    "https://dl.flathub.org/repo/flathub.flatpakrepo" 2>/dev/null || true

# Installer MelonDS
if flatpak info "$FLATPAK_APP" &>/dev/null; then
    log_ok "MelonDS déjà installé"
else
    log_info "Téléchargement et installation de MelonDS (peut prendre un moment)..."
    if flatpak install -y --noninteractive flathub "$FLATPAK_APP" 2>/dev/null; then
        log_ok "MelonDS installé avec succès"
    else
        log_warn "Installation de MelonDS échouée. Vous pourrez l'installer manuellement plus tard."
    fi
fi

# ==============================================================================
# [5] Configuration des permissions Flatpak
# ==============================================================================
log_step "5/10" "Configuration des permissions de l'émulateur..."

OVERRIDES=(
    "--filesystem=host"
    "--device=all"
    "--share=ipc"
    "--socket=x11"
    "--socket=wayland"
    "--socket=fallback-x11"
    "--socket=pulseaudio"
)

for override in "${OVERRIDES[@]}"; do
    flatpak override "$override" "$FLATPAK_APP" 2>/dev/null || true
done
log_ok "Permissions Flatpak configurées (filesystem, devices, sockets)"

# ==============================================================================
# [5.5] Configuration des permissions Manette (udev)
# ==============================================================================
log_step "5/10 (bis)" "Configuration des permissions manette (udev sécurisé)..."

# 1. Restreindre l'accès au groupe "input" au lieu d'une ouverture totale (0666 -> 0660)
UDEV_RULE_FILE="/etc/udev/rules.d/99-gamepad-evdev.rules"
echo 'KERNEL=="event*", SUBSYSTEM=="input", GROUP="input", MODE="0660"' > "$UDEV_RULE_FILE"

# 2. Ajouter l'utilisateur courant au groupe "input" pour qu'il puisse lire les manettes
usermod -aG input "$REAL_USER" 2>/dev/null || true

udevadm control --reload-rules && udevadm trigger 2>/dev/null || true
log_ok "Permissions manette accordées (udev sécurisé pour le groupe input)"

# ==============================================================================
# [6] Activation et permissions de ydotoold (uinput)
# ==============================================================================
log_step "6/10" "Configuration de ydotool (simulation de touches)..."

# 1. S'assurer que le module noyau uinput est chargé au boot
if [ ! -f /etc/modules-load.d/uinput.conf ]; then
    echo "uinput" > /etc/modules-load.d/uinput.conf
    log_ok "Chargement automatique du module uinput configuré"
fi
modprobe uinput 2>/dev/null || true

# 2. Configurer les droits udev pour /dev/uinput (permet à ydotool de tourner sans root)
UINPUT_RULE_FILE="/etc/udev/rules.d/99-uinput.rules"
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' > "$UINPUT_RULE_FILE"
udevadm control --reload-rules && udevadm trigger /dev/uinput 2>/dev/null || true
log_ok "Permissions de /dev/uinput accordées au groupe input"

if command -v ydotool &>/dev/null; then
    # Vérifier si ydotoold est déjà actif
    YDOTOOL_SOCKET_USER="/run/user/$REAL_UID/.ydotool_socket"

    if [ -S "$YDOTOOL_SOCKET_USER" ] 2>/dev/null; then
        log_ok "ydotoold déjà actif (socket détecté)"
    else
        # Tenter d'activer via systemd --user
        YDOTOOL_ACTIVATED=false

        for unit in ydotool.socket ydotool.service ydotoold.socket ydotoold.service; do
            if runuser -l "$REAL_USER" -c \
                "XDG_RUNTIME_DIR=/run/user/$REAL_UID systemctl --user is-enabled $unit" &>/dev/null 2>&1; then
                runuser -l "$REAL_USER" -c \
                    "XDG_RUNTIME_DIR=/run/user/$REAL_UID systemctl --user enable --now $unit" 2>/dev/null || true
                YDOTOOL_ACTIVATED=true
                log_ok "ydotoold activé via systemd ($unit)"
                break
            fi
        done

        if [ "$YDOTOOL_ACTIVATED" = false ]; then
            log_warn "ydotoold sera démarré à la demande par le serveur"
        fi
    fi
else
    log_warn "ydotool non installé — la configuration automatique des touches ne fonctionnera pas"
fi

# ==============================================================================
# [7] Création du service systemd --user
# ==============================================================================
log_step "7/10" "Création du service systemd utilisateur..."

# Nettoyer un éventuel ancien service système (non --user)
systemctl stop "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/$SERVICE_NAME" 2>/dev/null || true

# Créer le dossier systemd user
SYSTEMD_USER_DIR="$REAL_HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

SERVICE_PATH="$SYSTEMD_USER_DIR/$SERVICE_NAME"

cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=MyNintendoTV — Serveur d'émulation rétro
After=network.target graphical-session.target
Wants=graphical-session.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN $SCRIPT_PATH
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

chown "$REAL_UID:$REAL_GID" "$SERVICE_PATH"
log_ok "Service créé : $SERVICE_PATH"
log_info "ExecStart : $PYTHON_BIN $SCRIPT_PATH"

# Fonction helper pour exécuter des commandes systemd --user
run_as_user() {
    local cmd="$1"
    runuser -l "$REAL_USER" -c "XDG_RUNTIME_DIR=/run/user/$REAL_UID $cmd" 2>/dev/null || \
        su - "$REAL_USER" -c "XDG_RUNTIME_DIR=/run/user/$REAL_UID $cmd" 2>/dev/null || true
}

run_as_user "systemctl --user daemon-reload"
run_as_user "systemctl --user enable $SERVICE_NAME"
run_as_user "systemctl --user restart $SERVICE_NAME"
log_ok "Service activé et démarré"

# ==============================================================================
# [7.5] Configuration de la Session Kiosk Dédiée
# ==============================================================================
log_step "7/10 (bis)" "Configuration de la session kiosk dédiée..."

# --- 1. Installation de Chromium ---
if ! command -v chromium &>/dev/null && ! command -v chromium-browser &>/dev/null; then
    log_info "Chromium non détecté, installation en cours..."
    apt-get install -y chromium-browser >/dev/null 2>&1 || apt-get install -y chromium >/dev/null 2>&1 || log_warn "Échec de l'installation de Chromium via apt."
else
    log_ok "Chromium est déjà installé"
fi

CHROMIUM_BIN="chromium"
if command -v chromium-browser &>/dev/null; then
    CHROMIUM_BIN="chromium-browser"
fi

# --- 2. Suppression de l'ancien autostart (migration depuis l'ancienne version) ---
rm -f "$REAL_HOME/.config/autostart/mynintendotv-kiosk.desktop" 2>/dev/null || true

# --- 3. Création du script de session kiosk ---
KIOSK_SCRIPT="/usr/local/bin/mynintendotv-kiosk-session"
cat > "$KIOSK_SCRIPT" <<'EOFSCRIPT'
#!/bin/bash
# MyNintendoTV — Script de session Kiosk
# Lancé par openbox comme unique processus graphique.

EMU_PORT=8080
EMU_URL="http://localhost:$EMU_PORT"

# Désactiver l'écran de veille et le DPMS (économie d'énergie écran)
xset s off 2>/dev/null || true
xset -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true

# Masquer le curseur de la souris
if command -v unclutter &>/dev/null; then
    unclutter -idle 0.1 -root &
elif command -v xdotool &>/dev/null; then
    xdotool mousemove 0 0 &
fi

# Fond noir immédiat (éviter le glitch blanc)
xsetroot -solid black 2>/dev/null || true

# Démarrer le daemon ydotoold (nécessaire pour la simulation de touches)
YDOTOOL_SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket"
if [ ! -S "$YDOTOOL_SOCKET" ]; then
    # Tenter via systemd --user
    systemctl --user start ydotool.service 2>/dev/null || \
    systemctl --user start ydotoold.service 2>/dev/null || \
    ydotoold &
fi

# Détecter le binaire Chromium disponible
CHROM_BIN="chromium"
if command -v chromium-browser &>/dev/null; then
    CHROM_BIN="chromium-browser"
fi

# Attendre que le serveur soit prêt (max 30 secondes)
for i in $(seq 1 30); do
    if curl -s -o /dev/null "$EMU_URL" 2>/dev/null; then
        break
    fi
    sleep 1
done

# Boucle infinie : si Chromium crash, il redémarre automatiquement
while true; do
    "$CHROM_BIN" \
        --kiosk \
        --no-first-run \
        --disable-translate \
        --disable-infobars \
        --disable-suggestions-service \
        --disable-save-password-bubble \
        --disable-session-crashed-bubble \
        --noerrdialogs \
        --disable-component-update \
        --check-for-update-interval=31536000 \
        --autoplay-policy=no-user-gesture-required \
        --password-store=basic \
        "$EMU_URL" 2>/dev/null
    sleep 2
done
EOFSCRIPT
chmod +x "$KIOSK_SCRIPT"
log_ok "Script de session kiosk installé ($KIOSK_SCRIPT)"

# --- 4. Configuration openbox pour lancer le script kiosk ---
OB_CONFIG_DIR="$REAL_HOME/.config/openbox"
mkdir -p "$OB_CONFIG_DIR"
chown "$REAL_UID:$REAL_GID" "$OB_CONFIG_DIR"

cat > "$OB_CONFIG_DIR/autostart" <<EOF
# MyNintendoTV — Autostart openbox
$KIOSK_SCRIPT &
EOF
chown "$REAL_UID:$REAL_GID" "$OB_CONFIG_DIR/autostart"
log_ok "Configuration openbox créée"

# --- 5. Enregistrement de la session X personnalisée ---
XSESSION_FILE="/usr/share/xsessions/mynintendotv-kiosk.desktop"
cat > "$XSESSION_FILE" <<EOF
[Desktop Entry]
Name=MyNintendoTV (Kiosk)
Comment=Console d'emulation en mode kiosk dedie
Exec=openbox-session
Type=Application
DesktopNames=Openbox
EOF
log_ok "Session X 'MyNintendoTV (Kiosk)' enregistrée"

# --- 6. Configuration de l'autologin sur la session kiosk ---
DM_CONFIGURED=false

# GDM3 (GNOME Display Manager)
GDM_CONF="/etc/gdm3/custom.conf"
if [ -f "$GDM_CONF" ] || command -v gdm3 &>/dev/null; then
    log_info "GDM3 détecté — configuration de l'autologin..."
    if [ -f "$GDM_CONF" ] && [ ! -f "${GDM_CONF}.emu-backup" ]; then
        cp "$GDM_CONF" "${GDM_CONF}.emu-backup"
    fi
    mkdir -p "$(dirname "$GDM_CONF")"
    cat > "$GDM_CONF" <<EOF
# Configuration GDM3 — MyNintendoTV Kiosk
[daemon]
AutomaticLoginEnable=True
AutomaticLogin=$REAL_USER

[security]

[xdmcp]

[chooser]

[debug]
EOF
    DM_CONFIGURED=true
    log_ok "Autologin GDM3 configuré pour $REAL_USER"
fi

# LightDM
LIGHTDM_CONF="/etc/lightdm/lightdm.conf"
if [ "$DM_CONFIGURED" = false ] && ([ -f "$LIGHTDM_CONF" ] || command -v lightdm &>/dev/null); then
    log_info "LightDM détecté — configuration de l'autologin..."
    if [ -f "$LIGHTDM_CONF" ] && [ ! -f "${LIGHTDM_CONF}.emu-backup" ]; then
        cp "$LIGHTDM_CONF" "${LIGHTDM_CONF}.emu-backup"
    fi
    mkdir -p "$(dirname "$LIGHTDM_CONF")"
    cat > "$LIGHTDM_CONF" <<EOF
# Configuration LightDM — MyNintendoTV Kiosk
[Seat:*]
autologin-user=$REAL_USER
autologin-session=mynintendotv-kiosk
user-session=mynintendotv-kiosk
EOF
    DM_CONFIGURED=true
    log_ok "Autologin LightDM configuré pour $REAL_USER"
fi

# SDDM (KDE)
SDDM_CONF="/etc/sddm.conf.d/mynintendotv-kiosk.conf"
if [ "$DM_CONFIGURED" = false ] && command -v sddm &>/dev/null; then
    log_info "SDDM détecté — configuration de l'autologin..."
    mkdir -p /etc/sddm.conf.d
    cat > "$SDDM_CONF" <<EOF
# Configuration SDDM — MyNintendoTV Kiosk
[Autologin]
User=$REAL_USER
Session=mynintendotv-kiosk
EOF
    DM_CONFIGURED=true
    log_ok "Autologin SDDM configuré pour $REAL_USER"
fi

if [ "$DM_CONFIGURED" = false ]; then
    log_warn "Aucun gestionnaire d'affichage reconnu. Configurez l'autologin manuellement."
    log_info "La session 'MyNintendoTV (Kiosk)' est disponible dans l'écran de connexion."
fi

# --- 7. Forcer la session kiosk comme session par défaut (AccountsService) ---
ACCOUNTS_DIR="/var/lib/AccountsService/users"
if [ -d "$(dirname "$ACCOUNTS_DIR")" ]; then
    mkdir -p "$ACCOUNTS_DIR"
    cat > "$ACCOUNTS_DIR/$REAL_USER" <<EOF
[User]
Session=mynintendotv-kiosk
XSession=mynintendotv-kiosk
SystemAccount=false
EOF
    log_ok "Session par défaut forcée via AccountsService"
fi

# Installation de unclutter (masquer le curseur)
apt-get install -y unclutter >/dev/null 2>&1 || log_warn "unclutter non disponible — le curseur sera déplacé en haut à gauche"

# ==============================================================================
# [8] Activation du Linger (démarrage au boot sans login)
# ==============================================================================
log_step "8/10" "Activation du démarrage automatique au boot (linger)..."

loginctl enable-linger "$REAL_USER" 2>/dev/null || true

LINGER_STATUS=$(loginctl show-user "$REAL_USER" -p Linger 2>/dev/null | cut -d= -f2)
if [ "$LINGER_STATUS" = "yes" ]; then
    log_ok "Linger activé — le serveur démarrera au boot sans connexion requise"
else
    log_warn "Activation du linger échouée. Le serveur ne démarrera qu'à la connexion de l'utilisateur."
fi

# ==============================================================================
# [9] Configuration du firewall
# ==============================================================================
log_step "9/10" "Configuration du firewall..."

FIREWALL_CONFIGURED=false

# UFW (Ubuntu default)
if command -v ufw &>/dev/null; then
    UFW_STATUS=$(ufw status 2>/dev/null | head -1)
    if echo "$UFW_STATUS" | grep -qi "active"; then
        ufw allow "$REQUIRED_PORT/tcp" comment "MyNintendoTV" >/dev/null 2>&1 || true
        log_ok "Port $REQUIRED_PORT ouvert dans UFW"
        FIREWALL_CONFIGURED=true
    else
        log_info "UFW inactif — aucune règle nécessaire"
        FIREWALL_CONFIGURED=true
    fi
fi

# firewalld (Fedora/CentOS based, parfois sur Debian)
if [ "$FIREWALL_CONFIGURED" = false ] && command -v firewall-cmd &>/dev/null; then
    if firewall-cmd --state &>/dev/null; then
        firewall-cmd --permanent --add-port="$REQUIRED_PORT/tcp" >/dev/null 2>&1 || true
        firewall-cmd --reload >/dev/null 2>&1 || true
        log_ok "Port $REQUIRED_PORT ouvert dans firewalld"
        FIREWALL_CONFIGURED=true
    fi
fi

if [ "$FIREWALL_CONFIGURED" = false ]; then
    log_info "Aucun firewall actif détecté — port $REQUIRED_PORT accessible par défaut"
fi

# ==============================================================================
# [10] Arborescence et permissions
# ==============================================================================
log_step "10/10" "Configuration de l'arborescence et des permissions..."

# Créer les dossiers nécessaires
DIRS_TO_CREATE=(
    "$PROJECT_DIR/Jeux"
    "$PROJECT_DIR/Jeux/NDS"
    "$PROJECT_DIR/emu_logs"
    "$PROJECT_DIR/launch_tmp"
)

for dir in "${DIRS_TO_CREATE[@]}"; do
    mkdir -p "$dir"
done
log_ok "Arborescence créée"

# Fixer les permissions sur tout le projet
chown -R "$REAL_UID:$REAL_GID" "$PROJECT_DIR"

# Fixer les permissions du dossier .config (au cas où root l'aurait touché)
if [ -d "$REAL_HOME/.config/systemd" ]; then
    chown -R "$REAL_UID:$REAL_GID" "$REAL_HOME/.config/systemd"
fi

log_ok "Permissions corrigées pour $REAL_USER"

# ==============================================================================
# Vérification post-installation
# ==============================================================================
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║              Vérification Post-Installation                ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"

check_result() {
    local name="$1"
    local cmd="$2"
    if eval "$cmd" &>/dev/null 2>&1; then
        echo -e "  ${GREEN}✅${NC} $name"
    else
        echo -e "  ${RED}❌${NC} $name"
        INSTALL_ERRORS=$((INSTALL_ERRORS + 1))
    fi
}

check_result "Python 3"                     "python3 --version"
check_result "Module watchdog"              "$PYTHON_BIN -c 'import watchdog'"
check_result "Flatpak"                      "flatpak --version"
check_result "MelonDS (Flatpak)"            "flatpak info $FLATPAK_APP"
check_result "ydotool"                      "command -v ydotool"
check_result "Service systemd créé"         "test -f $SERVICE_PATH"
check_result "Service systemd activé"       "runuser -l $REAL_USER -c 'XDG_RUNTIME_DIR=/run/user/$REAL_UID systemctl --user is-enabled $SERVICE_NAME'"
check_result "Linger activé"               "loginctl show-user $REAL_USER -p Linger 2>/dev/null | grep -q 'yes'"
check_result "Session kiosk installée"      "test -f /usr/share/xsessions/mynintendotv-kiosk.desktop"
check_result "Script kiosk installé"        "test -x /usr/local/bin/mynintendotv-kiosk-session"
check_result "Dossier Jeux/"               "test -d $PROJECT_DIR/Jeux"
check_result "Permissions utilisateur"      "test \$(stat -c '%U' '$PROJECT_DIR') = '$REAL_USER'"

# Attendre un instant que le serveur démarre puis tester le port
sleep 2
check_result "Serveur accessible (port $REQUIRED_PORT)"  "curl -s -o /dev/null -w '%{http_code}' http://localhost:$REQUIRED_PORT 2>/dev/null | grep -q '200'"

echo ""
if [ "$INSTALL_ERRORS" -gt 0 ]; then
    echo -e "${YELLOW}${BOLD}⚠️  $INSTALL_ERRORS problème(s) détecté(s).${NC} Vérifiez les lignes ❌ ci-dessus."
else
    echo -e "${GREEN}${BOLD}✅ Installation parfaite — 0 erreur !${NC}"
fi

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
echo -e "  Le serveur est accessible sur : ${CYAN}${BOLD}http://localhost:$REQUIRED_PORT${NC}"
echo ""
echo -e "  Depuis un autre appareil du réseau :"
IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -n "$IP_ADDR" ]; then
    echo -e "    ${CYAN}${BOLD}http://$IP_ADDR:$REQUIRED_PORT${NC}"
fi
echo ""
echo -e "  Commandes utiles :"
echo -e "    ${CYAN}systemctl --user status $SERVICE_NAME${NC}   ← statut"
echo -e "    ${CYAN}systemctl --user restart $SERVICE_NAME${NC}  ← redémarrer"
echo -e "    ${CYAN}journalctl --user -u $SERVICE_NAME -f${NC}  ← logs en direct"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════${NC}"
