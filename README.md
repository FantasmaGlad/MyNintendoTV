# MyNintendoTV

Console d'émulation Nintendo DS autonome pour TV sur serveur Linux / Raspberry Pi. Session kiosque Openbox + Chromium, serveur backend Python sans framework (`http.server`), gestionnaire d'entrées `evdev` et interface web de contrôle.

Ce document est écrit pour quiconque souhaite **comprendre, installer, exploiter ou modifier** la console MyNintendoTV : il décrit l'architecture réellement en place (pas une intention), l'intégration système X11/Flatpak/systemd, ainsi que les mécanismes de contrôle par manette et réseau.

---

## Sommaire

1. [Stack et démarrage](#1-stack-et-démarrage)
2. [Architecture générale & Session Kiosque](#2-architecture-générale--session-kiosque)
3. [Le serveur backend (`mynintendotv.py`)](#3-le-serveur-backend-mynintendotvpy)
4. [Gestionnaire d'entrée & Écouteur manette (`evdev`)](#4-gestionnaire-dentrée--écouteur-manette-evdev)
5. [Importation & Sécurité du streaming ROMs](#5-importation--sécurité-du-streaming-roms)
6. [Intégration MelonDS & Environnement graphique](#6-intégration-melonds--environnement-graphique)
7. [Script d'installation & Services systemd](#7-script-dinstallation--services-systemd)
8. [Référence API HTTP & Diagnostics](#8-référence-api-http--diagnostics)
9. [Exploitation & Maintenance](#9-exploitation--maintenance)
10. [Licence](#10-licence)

---

## 1. Stack et démarrage

### Stack technique

- **Backend** : Python 3.10+ (bibliothèque standard `http.server`, `urllib`, `mmap`), `watchdog` (surveillance du dossier `Jeux/`), `evdev` (capture bas niveau du gamepad), Flatpak (émulateur `net.kuribo64.melonDS`).
- **Frontend** : HTML5, JavaScript ES6 natif (Server-Sent Events - SSE, Gamepad API), CSS3 (Glassmorphism & thèmes visuels).
- **Système & Kiosque** : Debian 11+ / Ubuntu 20.04+, Openbox (gestionnaire de fenêtres minimal), Chromium plein écran (kiosque X11), `ydotool` (simulation d'entrées), `unclutter` (masquage curseur), `systemd` user service avec `loginctl enable-linger`.

### Installation rapide

**Prérequis** : Machine sous Debian/Ubuntu x86_64, compte utilisateur standard (non-root) avec accès `sudo`, connexion Internet pour l'installation initiale.

```bash
git clone https://github.com/FantasmaGlad/MyNintendoTV.git
cd MyNintendoTV
sudo ./install.sh
```

À l'issue de l'installation, un redémarrage de la machine (`sudo reboot`) bascule automatiquement le système en mode console autonome.

### Exécution locale & Débogage

Pour exécuter le backend manuellement en premier plan hors du service systemd :

```bash
# Lancement direct du serveur HTTP et de l'écouteur manette
python3 mynintendotv.py

# Nettoyage des fichiers temporaires (hardlinks orphelins, logs d'émulateur)
python3 mynintendotv.py --clean
```

---

## 2. Architecture générale & Session Kiosque

```
┌───────────────────────────┐     HTTP / SSE (Port 8080)     ┌──────────────────────────────────┐
│  Navigateur / Admin Web   │ ──────────────────────────────►│         Backend Python           │
│  (/roms, télécommande)    │◀────────────────────────────── │        `mynintendotv.py`         │
└───────────────────────────┘                                └──────────────────────────────────┘
                                                                     │               │
                                                                     ▼               ▼
┌───────────────────────────┐     Commandes système / evdev  ┌──────────────┐ ┌──────────────┐
│  Session Kiosque Openbox  │ ◄───────────────────────────── │ Flatpak      │ │ Dossier      │
│  (Chromium plein écran)   │                                │ MelonDS      │ │ `Jeux/`      │
└───────────────────────────┘                                └──────────────┘ └──────────────┘
```

Au démarrage de la machine :
1. **Autologin** : La session utilisateur s'ouvre automatiquement sans mot de passe.
2. **Session Kiosque** : Le script `/usr/local/bin/mynintendotv-kiosk-session` démarre Openbox en arrière-plan noir et Chromium en mode kiosque verrouillé pointant sur `http://localhost:8080`.
3. **Persistance** : Le service user systemd `mynintendotv.service` maintient le backend actif même en cas de fermeture du navigateur.

---

## 3. Le serveur backend (`mynintendotv.py`)

Le backend est conçu autour d'un principe fort : **zéro framework web lourd** (pas de Flask, pas de FastAPI). Il repose exclusivement sur le module `http.server` de la bibliothèque standard Python afin d'offrir une empreinte mémoire minimale et une stabilité totale sur machine dédiée.

### Responsabilités du serveur

- **Distribution des fichiers** : Service des assets statiques (`index.html`, `roms.html`, `style.css`, `script.js`) et des couvertures de jeux.
- **API REST & SSE** : Gestion du catalogue de jeux, lancement/arrêt de l'émulateur, mise en veille et notifications temps réel via Server-Sent Events.
- **Streaming & Importation** : Réception multipart haute performance pour fichiers `.nds` et archives `.zip`.

---

## 4. Gestionnaire d'entrée & Écouteur manette (`evdev`)

Pour permettre une utilisation 100 % manette sur TV sans clavier ni souris, le backend intègre un écouteur bas niveau basé sur la bibliothèque Python `evdev`.

### Le Raccourci d'Arrêt d'Urgence (*Kill Combo*)

En cours de jeu, l'émulateur MelonDS prend le contrôle exclusif de la fenêtre. Pour revenir au catalogue sans clavier :

1. Maintenez enfoncées simultanement les deux gâchettes supérieures de la manette (**L1 + R1**).
2. Appuyez deux fois rapidement sur l'un des boutons de façade (**A, B, X ou Y**).

L'écouteur `gamepad_kill_listener` intercepte cette combinaison directement au niveau du périphérique `/dev/input/event*`, ferme proprement l'émulateur et redonne la main à l'interface web.

### Règle Udev (`/etc/udev/rules.d/99-gamepad-evdev.rules`)

Le script `install.sh` déploie une règle udev accordant les droits de lecture et d'écriture des gamepads à l'utilisateur membre du groupe `input`.

---

## 5. Importation & Sécurité du streaming ROMs

L'ajout de jeux s'effectue à distance via l'interface `/roms` ou par surveillance directe du dossier `Jeux/`.

### Sécurité & Traitement des Uploads (`/api/upload`)

- **Limitation de taille** : Les envois sont plafonnés à 600 Mo (retour HTTP 413 en cas de dépassement).
- **Streaming par Chunks & `mmap`** : L'écriture sur disque s'effectue par blocs de 64 Ko couplés à un parsing multipart optimisé avec `mmap`, évitant la saturation de la mémoire RAM.
- **Protection contre le Path Traversal** : Chaque nom de fichier est nettoyé via `os.path.basename()` et confiné dans le répertoire `Jeux/` via la résolution `os.path.realpath()`.
- **Extraction ZIP** : Les archives `.zip` sont décompressées à la volée et les fichiers temporaires purgés immédiatement.

### Synchronisation SSE temps réel (`watchdog`)

Le module `watchdog` surveille les modifications dans le répertoire `Jeux/`. Dès qu'une ROM est ajoutée ou supprimée, un événement SSE `reload` est émis vers le frontend avec un **debounce de 1.5s** pour éviter les rafraîchissements multiples lors d'extractions d'archives volumineuses.

---

## 6. Intégration MelonDS & Environnement graphique

Le lancement d'un jeu via l'API (`GET /launch/<game_id>`) applique plusieurs mécanismes d'isolation :

### 1. Hardlinks de sécurité (`_safe_rom_path`)
Les noms de fichiers originaux contenant des caractères spéciaux (espaces, parenthèses, crochets issues des conventions No-Intro/Redump) peuvent altérer le parsing des arguments par Flatpak. Le serveur crée un hardlink temporaire au nom assaini (`launch_tmp/rom_<hash>.nds`) pointant sur le fichier d'origine sans dupliquer la ROM sur disque.

### 2. Reconstruction de l'environnement graphique (`_build_graphical_env`)
Puisque le backend s'exécute en tant que service `systemd --user`, il ne hérite pas obligatoirement des variables de session X11. Avant chaque lancement, le serveur inspecte `/proc/<pid>/environ` des processus utilisateur actifs pour retrouver `DISPLAY`, `WAYLAND_DISPLAY` et `DBUS_SESSION_BUS_ADDRESS`.

### 3. Réinitialisation des paramètres MelonDS (`reset_melonds_config`)
Le fichier de configuration `melonDS.ini` est réinitialisé avant chaque partie afin de garantir l'application de la langue firmware configurée dans `config.json` et d'éviter qu'un réglage accidentel ne persiste.

---

## 7. Script d'installation & Services systemd

### Script d'Installation (`sudo ./install.sh`)

Le script prend en charge l'intégralité du déploiement système :
- Installation des paquets APT : `python3-pip`, `flatpak`, `chromium-browser`, `openbox`, `ydotool`, `unclutter`.
- Configuration du dépôt Flathub et installation de `net.kuribo64.melonDS`.
- Création du service systemd utilisateur `~/.config/systemd/user/mynintendotv.service`.
- Configuration de l'autologin LightDM/GDM3 et déploiement de la session Kiosque `/usr/local/bin/mynintendotv-kiosk-session`.

### Script de Purge (`sudo ./purge.sh`)

Permet une désinstallation complète et propre de la console d'émulation :
```bash
sudo ./purge.sh
```
Supprime les services systemd, la session Kiosque, les configurations d'autologin, Flatpak MelonDS et l'ensemble du répertoire du projet.

---

## 8. Référence API HTTP & Diagnostics

Le serveur écoute sur le port `8080`.

| Endpoint | Méthode | Rôle |
|---|---|---|
| `/` | `GET` | Interface principale (catalogue de jeux) |
| `/roms` | `GET` | Interface d'administration réseau et d'importation |
| `/api/games` | `GET` | Liste JSON des jeux disponibles et de leurs vignettes |
| `/launch/<game_id>` | `GET` | Lancement de l'émulateur avec la ROM spécifiée |
| `/api/kill` | `POST` | Fermeture immédiate du jeu en cours |
| `/api/upload` | `POST` | Importation streaming de fichiers `.nds` / `.zip` ou jaquettes |
| `/api/system/shutdown` | `POST` | Extinction propre de la console |
| `/api/system/reboot` | `POST` | Redémarrage du système |
| `/api/system/wake` | `POST` | Simulation d'activité pour réveiller l'écran |
| `/events` | `GET` | Canal Server-Sent Events (SSE) pour rafraîchissement temps réel |
| `/api/health` | `GET` | Vérification rapide de santé de l'API |
| `/api/diag` | `GET` | Diagnostic complet système (Flatpak, ROMs, logs, variables X11) |

---

## 9. Exploitation & Maintenance

### Commandes systemd utilisateur

```bash
# Vérifier l'état du service backend
systemctl --user status mynintendotv.service

# Redémarrer le service backend
systemctl --user restart mynintendotv.service

# Consulter les journaux en temps réel (logs)
journalctl --user -u mynintendotv.service -f
```

### Diagnostic de santé API

L'endpoint `/api/diag` fournit une analyse complète de l'état du système :
```bash
curl -s http://localhost:8080/api/diag
```

---

## 10. Licence

Ce projet est distribué sous licence **GNU Affero General Public License v3.0** (AGPL-3.0). Voir le fichier [LICENSE](LICENSE) pour le texte complet.
