#!/bin/bash
# ------------------------------------------------------------------------------
# Script de désinstallation complète et de purge totale du serveur d'émulation
# Ce script doit être exécuté avec des droits administrateur (sudo ./purge.sh)
# ------------------------------------------------------------------------------

set -e

# 1. Vérification des privilèges
if [ "$EUID" -ne 0 ]; then
  echo "❌ Erreur : Ce script doit être exécuté en tant que root (avec sudo)."
  echo "Usage: sudo ./purge.sh"
  exit 1
fi

# 2. Identification de l'utilisateur réel
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
if [ "$USER_NAME" = "root" ]; then
  # Détecter le propriétaire réel du dossier projet
  DETECTED_OWNER=$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || echo "")
  if [ -n "$DETECTED_OWNER" ] && [ "$DETECTED_OWNER" != "root" ]; then
    USER_NAME="$DETECTED_OWNER"
  else
    echo "❌ Erreur : Impossible de déterminer l'utilisateur réel."
    echo "Relancez avec : sudo -E ./purge.sh"
    exit 1
  fi
fi

# Vérifier que l'utilisateur existe
if ! id "$USER_NAME" &>/dev/null; then
  echo "❌ Erreur : L'utilisateur '$USER_NAME' n'existe pas sur ce système."
  exit 1
fi

USER_UID=$(id -u "$USER_NAME")
USER_HOME=$(eval echo "~$USER_NAME")

echo "🧹 Début de la désinstallation complète pour l'utilisateur : $USER_NAME..."

# 3. Arrêt et désactivation du service systemd --user
echo "[1/7] Arrêt et désactivation du service systemd..."
XDG_RUNTIME_DIR="/run/user/$USER_UID" runuser -l "$USER_NAME" -c "systemctl --user stop serveur_jeu.service" 2>/dev/null || true
XDG_RUNTIME_DIR="/run/user/$USER_UID" runuser -l "$USER_NAME" -c "systemctl --user disable serveur_jeu.service" 2>/dev/null || true

SERVICE_FILE="$USER_HOME/.config/systemd/user/serveur_jeu.service"
if [ -f "$SERVICE_FILE" ]; then
  rm -f "$SERVICE_FILE"
  echo "  -> Fichier de service systemd supprimé."
fi

# Recharger systemd pour le user
XDG_RUNTIME_DIR="/run/user/$USER_UID" runuser -l "$USER_NAME" -c "systemctl --user daemon-reload" 2>/dev/null || true

# 4. Désactivation du linger
echo "[2/7] Désactivation du linger (lancement au boot)..."
loginctl disable-linger "$USER_NAME" 2>/dev/null || true

# 5. Désinstallation de l'émulateur MelonDS et de ses configurations
echo "[3/7] Désinstallation de MelonDS (Flatpak) et de ses configurations..."
# Tentative de désinstallation système
flatpak uninstall --delete-data -y net.kuribo64.melonDS 2>/dev/null || true
# Tentative de désinstallation utilisateur
runuser -l "$USER_NAME" -c "flatpak uninstall --delete-data -y net.kuribo64.melonDS" 2>/dev/null || true

# 6. Restauration de l'état d'input-remapper
echo "[4/7] Restauration des injections automatiques d'input-remapper..."
runuser -l "$USER_NAME" -c "input-remapper-control --command autoload" 2>/dev/null || true

# 7. Nettoyage des dossiers MelonDS dans le Home de l'utilisateur
echo "[5/8] Nettoyage des résidus de configuration utilisateur..."
rm -rf "$USER_HOME/.var/app/net.kuribo64.melonDS"

# 7b. Suppression de l'environnement virtuel Python (venv)
if [ -d "$PROJECT_DIR/.venv" ]; then
  echo "[6/8] Suppression du venv Python..."
  rm -rf "$PROJECT_DIR/.venv"
fi

# 9. Nettoyage du dossier du projet (CODE ET JEUX)
echo "[7/8] Suppression définitive du dossier du projet (Code & ROMs) : $PROJECT_DIR..."
# Suppression différée de quelques instants ou suppression directe de tout sauf le script puis du script lui-même
find "$PROJECT_DIR" -mindepth 1 -not -name "purge.sh" -delete || true

# 10. Autodestruction finale du script
echo "[8/8] Finalisation et autodestruction..."
rm -f "$PROJECT_DIR/purge.sh"
# Si le dossier est vide, on le supprime
rmdir "$PROJECT_DIR" 2>/dev/null || true

echo "✅ Désinstallation totale et purge complète effectuées avec succès !"
