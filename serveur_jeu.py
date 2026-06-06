import os
import sys

# Enrichir le PATH pour s'assurer que les utilitaires système et utilisateur sont trouvés par subprocess
os.environ["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:" + os.environ.get("PATH", "")
import queue
import threading
import time
import json
import urllib.parse
import http.server
import socketserver
import subprocess

def check_dependencies():
    """Vérifie que les dépendances Python sont installées.
    Si ce n'est pas le cas, oriente l'utilisateur vers install.sh."""
    try:
        import watchdog  # noqa: F401
    except ImportError:
        print("Erreur : module 'watchdog' non trouvé.")
        print("")
        print("Lancez le script d'installation pour configurer le système :")
        print("  sudo ./install.sh")
        print("")
        print("Pour la maintenance (nettoyage des logs/cache) :")
        print("  python3 serveur_jeu.py --clean")
        sys.exit(1)

check_dependencies()

try:
    import evdev
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    print("[INIT] Module 'evdev' non trouvé. Le 'Kill Combo' à la manette sera désactivé.")

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

PORT = 8080

# Racine des ROMs, organisée par émulateur
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JEUX_DIR = os.path.join(BASE_DIR, "Jeux")
# S'assurer que le dossier Jeux existe
if not os.path.exists(JEUX_DIR):
    os.makedirs(JEUX_DIR, exist_ok=True)
    # Si le script est lancé via sudo, on redonne les droits à l'utilisateur d'origine
    sudo_user = os.getenv("SUDO_USER")
    if sudo_user:
        import pwd
        user_info = pwd.getpwnam(sudo_user)
        os.chown(JEUX_DIR, user_info.pw_uid, user_info.pw_gid)

# Mapping extension → (émulateur, commande flatpak, motif de kill)
EMULATORS = {
    ".nds": ("NDS", ["flatpak", "run", "--filesystem=host", "net.kuribo64.melonDS", "--fullscreen"], "net.kuribo64.melonDS"),
}

# Extensions reconnues comme ROMs
ROM_EXTENSIONS = set(EMULATORS.keys())

# Liste des clients connectés aux Server-Sent Events (SSE)
sse_clients = []
sse_lock = threading.Lock()

# Debounce : évite de spammer le frontend avec plusieurs reloads pour un seul ZIP
_last_notify_time = 0
_NOTIFY_DEBOUNCE = 1.5  # secondes

active_emulators_count = 0
emulators_lock = threading.Lock()


def _stop_input_remapper_injections():
    """Désactive toutes les injections actives de input-remapper pour éviter les entrées parasites sur le bureau."""
    print("[INPUT-REMAPPER] Arrêt des injections pour éviter les entrées sauvages sur le bureau...")
    try:
        result = subprocess.run(["input-remapper-control", "--list-devices"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            devices = []
            for line in result.stdout.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Ignorer les warnings Pydantic, ydotool, imports et chemins
                if any(x in line.lower() for x in ["ydotool", "warning", "pydantic", "import", "from ", "/"]):
                    continue
                devices.append(line)
            
            for device in devices:
                print(f"[INPUT-REMAPPER] Arrêt de l'injection pour le périphérique : {device}")
                subprocess.run(["input-remapper-control", "--command", "stop", "--device", device], check=False)
        else:
            print("[INPUT-REMAPPER] Impossible de lister les périphériques.")
    except Exception as e:
        print(f"[INPUT-REMAPPER] Erreur lors de l'arrêt des injections: {e}")


def _restore_input_remapper_injections():
    """Restaure les injections automatiques de input-remapper."""
    print("[INPUT-REMAPPER] Restauration des configurations automatiques (autoload)...")
    try:
        subprocess.run(["input-remapper-control", "--command", "autoload"], check=False)
    except Exception as e:
        print(f"[INPUT-REMAPPER] Erreur lors de la restauration: {e}")


def register_emulator_start():
    global active_emulators_count
    with emulators_lock:
        if active_emulators_count == 0:
            _stop_input_remapper_injections()
        active_emulators_count += 1


def register_emulator_exit():
    global active_emulators_count
    with emulators_lock:
        active_emulators_count -= 1
        if active_emulators_count <= 0:
            active_emulators_count = 0
            _restore_input_remapper_injections()


_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def get_configured_language():
    # Par défaut: 2 (Français)
    default_lang = 2
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("firmware_language", default_lang)
        except Exception:
            pass
    return default_lang


def reset_melonds_config():
    home = os.path.expanduser("~")
    # Gérer les deux répertoires de configuration possibles pour melonDS (Flatpak et Hôte XDG)
    config_paths = [
        os.path.join(home, ".var/app/net.kuribo64.melonDS/config/melonDS/melonDS.ini"),
        os.path.join(home, ".config/melonDS/melonDS.ini")
    ]
    
    lang = get_configured_language()
    
    for config_file in config_paths:
        config_dir = os.path.dirname(config_file)
        print(f"[LAUNCH] Réinitialisation de la configuration de l'émulateur dans : {config_file}")
        try:
            if os.path.exists(config_file):
                os.remove(config_file)
                print(f"[LAUNCH] Fichier existant supprimé avec succès : {config_file}")
            else:
                os.makedirs(config_dir, exist_ok=True)
                print(f"[LAUNCH] Dossier créé : {config_dir}")
            
            # Écrire le fichier par défaut avec la langue configurée
            with open(config_file, "w") as f:
                f.write(f"[melonDS]\nFirmwareLanguage={lang}\n")
            print(f"[LAUNCH] Configuration initialisée avec FirmwareLanguage={lang} dans {config_file}")
        except Exception as e:
            print(f"[LAUNCH] Erreur lors de la réinitialisation de {config_file} : {e}")


def _ensure_ydotoold_running():
    """Vérifie que le daemon ydotoold est actif, et le démarre si nécessaire."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    socket_path = os.path.join(runtime_dir, ".ydotool_socket")

    if os.path.exists(socket_path):
        return True  # Socket présent → daemon actif

    print("[YDOTOOL] Daemon ydotoold non détecté. Tentative de démarrage...")

    # Tenter via systemd --user
    for unit in ("ydotool.socket", "ydotool.service", "ydotoold.socket", "ydotoold.service"):
        result = subprocess.run(
            ["systemctl", "--user", "start", unit],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            time.sleep(0.5)
            if os.path.exists(socket_path):
                print(f"[YDOTOOL] Daemon démarré via {unit}")
                return True

    # Dernier recours : lancement manuel en arrière-plan
    try:
        subprocess.Popen(
            ["ydotoold"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        time.sleep(1.0)
        if os.path.exists(socket_path):
            print("[YDOTOOL] Daemon démarré manuellement")
            return True
    except FileNotFoundError:
        print("[YDOTOOL] ydotoold introuvable — ydotool ne fonctionnera pas")
        return False
    except Exception as e:
        print(f"[YDOTOOL] Erreur au démarrage de ydotoold : {e}")

    print("[YDOTOOL] Impossible de démarrer ydotoold")
    return False


def simulate_mapping_menu_opening():
    time.sleep(5.0)  # Attendre que l'émulateur Flatpak soit bien affiché en plein écran

    # Vérifier que ydotoold est actif avant d'envoyer des touches
    if not _ensure_ydotoold_running():
        print("[LAUNCH] Abandon de la simulation ydotool (daemon absent).")
        return

    # Construire l'environnement avec le chemin du socket explicite
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    socket_path = os.path.join(runtime_dir, ".ydotool_socket")
    ydo_env = os.environ.copy()
    ydo_env["YDOTOOL_SOCKET"] = socket_path

    def ydo_run(args):
        """Exécute une commande ydotool avec le socket explicite."""
        result = subprocess.run(
            ["ydotool"] + args,
            env=ydo_env,
            capture_output=True,
            timeout=5
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            print(f"[YDOTOOL] Erreur (code {result.returncode}): {stderr}")
        return result.returncode == 0

    print("[LAUNCH] Simulation des touches avec ydotool pour ouvrir la page du mappage des touches...")
    try:
        # Cacher la souris (en haut à gauche) - Mouvement absolu puis relatif
        ydo_run(["mousemove", "-a", "-x", "0", "-y", "0"])
        ydo_run(["mousemove", "-x", "-5000", "-y", "-5000"])
        time.sleep(0.2)

        # Alt (touche 56) pour ouvrir la barre de menu
        ydo_run(["key", "56:1", "56:0"])
        time.sleep(0.8)
        # Droite (touche 106) — aller du menu File à System
        ydo_run(["key", "106:1", "106:0"])
        time.sleep(0.2)
        # Droite (touche 106) — aller de System à View
        ydo_run(["key", "106:1", "106:0"])
        time.sleep(0.2)
        # Droite (touche 106) — aller de View à Config (ouvre le menu)
        ydo_run(["key", "106:1", "106:0"])
        time.sleep(0.5) # Laisser le temps au menu déroulant de s'ouvrir complètement
        
        # Bas (touche 108) — focus sur le premier élément (Emu settings)
        ydo_run(["key", "108:1", "108:0"])
        time.sleep(0.2)
        
        # Bas (touche 108) — descendre vers le deuxième élément (Input and hotkeys)
        ydo_run(["key", "108:1", "108:0"])
        time.sleep(0.2)
        
        # Entrée (touche 28) pour valider
        ydo_run(["key", "28:1", "28:0"])
        print("[LAUNCH] Mappage des touches ouvert avec succès via ydotool.")
    except Exception as e:
        print(f"[LAUNCH] Échec de la simulation ydotool : {e}")


def gamepad_kill_listener(proc):
    """Écoute la manette pour le kill combo (L1 + R1 maintenus + 2x n'importe quel bouton de façade)"""
    if not EVDEV_AVAILABLE:
        return
        
    print("[GAMEPAD] Démarrage de l'écoute du Kill Combo (L + R + 2x Bouton)...")
    import select
    
    try:
        FACE_BUTTONS = {
            evdev.ecodes.BTN_A, evdev.ecodes.BTN_B, evdev.ecodes.BTN_X, evdev.ecodes.BTN_Y,
            evdev.ecodes.BTN_SOUTH, evdev.ecodes.BTN_EAST, evdev.ecodes.BTN_NORTH, evdev.ecodes.BTN_WEST,
            evdev.ecodes.BTN_1, evdev.ecodes.BTN_2, evdev.ecodes.BTN_3, evdev.ecodes.BTN_4,
            evdev.ecodes.BTN_TRIGGER_HAPPY1, evdev.ecodes.BTN_TRIGGER_HAPPY2, evdev.ecodes.BTN_TRIGGER_HAPPY3, evdev.ecodes.BTN_TRIGGER_HAPPY4
        }
        
        state_l = False
        state_r = False
        tap_count = 0
        last_tap_time = 0
        
        gamepads = {} # path -> evdev.InputDevice
        
        def refresh_gamepads():
            try:
                current_paths = evdev.list_devices()
            except Exception:
                return
                
            # Remove disconnected devices
            for p in list(gamepads.keys()):
                if p not in current_paths:
                    try:
                        gamepads[p].close()
                    except Exception:
                        pass
                    del gamepads[p]
                    
            # Add new devices
            for p in current_paths:
                if p not in gamepads:
                    try:
                        d = evdev.InputDevice(p)
                        if evdev.ecodes.EV_KEY in d.capabilities():
                            gamepads[p] = d
                    except Exception:
                        pass

        while proc.poll() is None:
            refresh_gamepads()
            valid_devices = list(gamepads.values())
            
            if not valid_devices:
                time.sleep(1.0)
                continue
                
            try:
                r, _, _ = select.select(valid_devices, [], [], 1.0)
            except OSError:
                time.sleep(0.5)
                continue
                
            for d in r:
                try:
                    for event in d.read():
                        if event.type == evdev.ecodes.EV_KEY:
                            if event.code in [evdev.ecodes.BTN_TL, evdev.ecodes.BTN_TL2, evdev.ecodes.BTN_Z]:
                                state_l = (event.value > 0)
                            elif event.code in [evdev.ecodes.BTN_TR, evdev.ecodes.BTN_TR2, evdev.ecodes.BTN_C]:
                                state_r = (event.value > 0)
                            elif event.code in FACE_BUTTONS and event.value == 1:
                                if state_l and state_r:
                                    now = time.time()
                                    if now - last_tap_time > 1.5:
                                        tap_count = 1
                                    else:
                                        tap_count += 1
                                        
                                    last_tap_time = now
                                    
                                    if tap_count >= 2:
                                        print("\n[GAMEPAD] ⚡ KILL COMBO DÉTECTÉ ⚡ Fermeture de l'émulateur...")
                                        
                                        # Bloquer tout relancement pendant 5 secondes (cooldown de sécurité globale)
                                        global _last_launch_time
                                        _last_launch_time = time.time()
                                        
                                        proc.terminate()
                                        subprocess.run(["flatpak", "kill", "net.kuribo64.melonDS"], check=False)
                                        try:
                                            proc.wait(timeout=2)
                                        except subprocess.TimeoutExpired:
                                            proc.kill()
                                        return
                except OSError:
                    # Le périphérique s'est déconnecté pendant la lecture
                    pass
    except Exception as e:
        print(f"[GAMEPAD] Erreur critique dans le listener: {e}")


def monitor_emulator_process(proc):
    proc.wait()
    print(f"[LAUNCH] Processus émulateur terminé (PID {proc.pid}). Restauration de l'environnement...")
    register_emulator_exit()


def slugify(name: str) -> str:
    """Transforme un nom de fichier en identifiant URL-safe."""
    return urllib.parse.quote(name, safe="")


def notify_clients(event_type: str, data: dict = None):
    """Envoie une notification SSE à tous les clients connectés (avec debounce)."""
    global _last_notify_time
    now = time.monotonic()
    if now - _last_notify_time < _NOTIFY_DEBOUNCE:
        return
    _last_notify_time = now

    if data is None:
        data = {}
    data["type"] = event_type

    payload = f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

    with sse_lock:
        active_clients = []
        for q in sse_clients:
            try:
                q.put_nowait(payload)
                active_clients.append(q)
            except queue.Full:
                pass
        sse_clients[:] = active_clients
    print(f"[SSE] Notification → {len(active_clients)} client(s) : {event_type}")


class RomWatchdogHandler(FileSystemEventHandler):
    """Handler Watchdog pour écouter les modifications des ROMs."""

    def on_any_event(self, event):
        if event.is_directory:
            return

        ext = os.path.splitext(event.src_path)[1].lower()
        dest_ext = ""
        if hasattr(event, "dest_path") and event.dest_path:
            dest_ext = os.path.splitext(event.dest_path)[1].lower()

        if ext in ROM_EXTENSIONS or dest_ext in ROM_EXTENSIONS:
            print(f"[WATCHDOG] {event.event_type} → {event.src_path}")
            global _cached_games
            _cached_games = None
            notify_clients("reload")

_cached_games = None
_last_scan_time = 0

def scan_games() -> list[dict]:
    """Scanne JEUX_DIR récursivement et retourne la liste des ROMs trouvées. Les résultats sont mis en cache."""
    global _cached_games, _last_scan_time
    now = time.monotonic()

    # Return cache if valid
    if _cached_games is not None and (now - _last_scan_time) < 2.0:
        return _cached_games

    games = []
    if not os.path.isdir(JEUX_DIR):
        _cached_games = games
        _last_scan_time = now
        return games

    for emulator_folder in sorted(os.listdir(JEUX_DIR)):
        emulator_path = os.path.join(JEUX_DIR, emulator_folder)
        if not os.path.isdir(emulator_path):
            continue

        for entry in sorted(os.scandir(emulator_path), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            game_folder = entry.path

            try:
                folder_files = os.listdir(game_folder)
            except OSError:
                continue

            rom_file = None
            rom_ext = None
            for f in folder_files:
                ext = os.path.splitext(f)[1].lower()
                if ext in EMULATORS:
                    rom_file = f
                    rom_ext = ext
                    break

            if not rom_file:
                continue

            rom_path = os.path.join(game_folder, rom_file)
            title = os.path.splitext(rom_file)[0]
            game_id = slugify(title)
            emulator_name = EMULATORS[rom_ext][0]

            # Chercher une cover dans le dossier du jeu
            cover_url = None
            img_files = [cf for cf in folder_files if cf.lower().endswith((".png", ".jpg", ".jpeg"))]

            if img_files:
                best_cover = None
                title_lower = title.lower()
                for img in img_files:
                    img_lower = img.lower()
                    if img_lower.startswith("cover."):
                        best_cover = img
                        break
                    elif not best_cover and img_lower.startswith(title_lower + "."):
                        best_cover = img

                if not best_cover:
                    best_cover = img_files[0]

                rel = os.path.relpath(os.path.join(game_folder, best_cover), BASE_DIR)
                cover_url = "/" + rel.replace(os.sep, "/")

            games.append({
                "id": game_id,
                "title": title,
                "rom": rom_path,
                "emulator": emulator_name,
                "cover": cover_url,
            })

    _cached_games = games
    _last_scan_time = now
    return games


def detect_emulator_for_ext(ext: str) -> str | None:
    """Retourne le nom du dossier émulateur pour une extension donnée."""
    info = EMULATORS.get(ext.lower())
    return info[0] if info else None



def _find_env_from_user_processes():
    """Tente de récupérer les variables d'environnement graphiques en inspectant
    les processus de l'utilisateur en cours d'exécution."""
    my_uid = os.getuid()
    important_vars = ["DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"]
    
    for pid_str in os.listdir("/proc"):
        if not pid_str.isdigit():
            continue
        try:
            pid = int(pid_str)
            stat_info = os.stat(f"/proc/{pid}")
            if stat_info.st_uid != my_uid:
                continue
            
            if pid == os.getpid():
                continue
                
            with open(f"/proc/{pid}/environ", "rb") as f:
                env_data = f.read()
            
            proc_env = {}
            for item in env_data.split(b"\x00"):
                if b"=" in item:
                    k, v = item.split(b"=", 1)
                    try:
                        proc_env[k.decode("utf-8")] = v.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
            
            if proc_env.get("DISPLAY") or proc_env.get("WAYLAND_DISPLAY"):
                res = {v: proc_env[v] for v in important_vars if v in proc_env and proc_env[v]}
                if res.get("DISPLAY") or res.get("WAYLAND_DISPLAY"):
                    return res
        except Exception:
            continue
    return {}

def _build_graphical_env():
    """Construit un environnement complet pour lancer une application graphique
    depuis un service systemd qui n'a pas forcément accès au display."""
    env = os.environ.copy()

    # --- HOME (indispensable pour Flatpak) ---
    if "HOME" not in env:
        import pwd
        try:
            env["HOME"] = pwd.getpwuid(os.getuid()).pw_dir
        except KeyError:
            env["HOME"] = os.path.expanduser("~")

    # --- 1. Tenter d'hériter de l'environnement d'une session active de l'utilisateur ---
    user_proc_env = _find_env_from_user_processes()
    for var, val in user_proc_env.items():
        if var not in env or not env[var]:
            env[var] = val

    # --- 2. Fallbacks et détections manuelles si nécessaire ---
    # --- Détection DISPLAY (X11) ---
    if "DISPLAY" not in env or not env["DISPLAY"]:
        x11_dir = "/tmp/.X11-unix"
        detected_display = None
        my_uid = os.getuid()
        if os.path.isdir(x11_dir):
            for entry in sorted(os.listdir(x11_dir)):
                if entry.startswith("X"):
                    path = os.path.join(x11_dir, entry)
                    try:
                        stat = os.stat(path)
                        if stat.st_uid == my_uid:
                            detected_display = f":{entry[1:]}"
                            break
                    except Exception:
                        pass
            if not detected_display:
                for entry in sorted(os.listdir(x11_dir)):
                    if entry.startswith("X"):
                        detected_display = f":{entry[1:]}"
                        break
        env["DISPLAY"] = detected_display if detected_display else ":0"

    # --- Détection XAUTHORITY ---
    if "XAUTHORITY" not in env or not env["XAUTHORITY"]:
        import glob
        home = env["HOME"]
        candidates = [
            os.path.join(home, ".Xauthority"),
            f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*",
        ]
        for c in candidates:
            matches = glob.glob(c)
            if matches and os.path.isfile(matches[0]):
                env["XAUTHORITY"] = matches[0]
                break

    # --- XDG_RUNTIME_DIR ---
    if "XDG_RUNTIME_DIR" not in env or not env["XDG_RUNTIME_DIR"]:
        candidate = f"/run/user/{os.getuid()}"
        if os.path.isdir(candidate):
            env["XDG_RUNTIME_DIR"] = candidate

    # --- Détection WAYLAND_DISPLAY ---
    if "WAYLAND_DISPLAY" not in env or not env["WAYLAND_DISPLAY"]:
        runtime_dir = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        for name in ("wayland-0", "wayland-1"):
            if os.path.exists(os.path.join(runtime_dir, name)):
                env["WAYLAND_DISPLAY"] = name
                break

    # --- DBUS_SESSION_BUS_ADDRESS ---
    if "DBUS_SESSION_BUS_ADDRESS" not in env or not env["DBUS_SESSION_BUS_ADDRESS"]:
        bus_path = f"/run/user/{os.getuid()}/bus"
        if os.path.exists(bus_path):
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus_path}"

    # Nettoyer l'environnement pour s'assurer que toutes les clés et valeurs sont des strings non-nulles
    clean_env = {}
    for k, v in env.items():
        if k is not None and v is not None:
            clean_env[str(k)] = str(v)

    print(f"[LAUNCH] ENV: HOME={clean_env.get('HOME')}, DISPLAY={clean_env.get('DISPLAY')}, "
          f"WAYLAND={clean_env.get('WAYLAND_DISPLAY')}, "
          f"XDG_RUNTIME_DIR={clean_env.get('XDG_RUNTIME_DIR')}, "
          f"DBUS={clean_env.get('DBUS_SESSION_BUS_ADDRESS','(none)')}")
    return clean_env

def _ensure_dir_permissions(dir_path):
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)
    
    sudo_user = os.getenv("SUDO_USER")
    if sudo_user:
        import pwd
        try:
            user_info = pwd.getpwnam(sudo_user)
            os.chown(dir_path, user_info.pw_uid, user_info.pw_gid)
        except Exception:
            pass

# Répertoires pour le bon fonctionnement
_LOG_DIR = os.path.join(BASE_DIR, "emu_logs")
_SYMLINK_DIR = os.path.join(BASE_DIR, "launch_tmp")

_ensure_dir_permissions(_LOG_DIR)
_ensure_dir_permissions(_SYMLINK_DIR)

def _safe_rom_path(rom_path: str) -> str:
    """Crée un lien physique (hardlink) temporaire vers la ROM avec un nom de fichier propre
    (sans espaces, parenthèses, virgules) pour éviter les problèmes de parsing Flatpak/MelonDS.
    Retourne le chemin du hardlink."""
    import hashlib
    rom_path = os.path.realpath(rom_path)
    ext = os.path.splitext(rom_path)[1]
    path_hash = hashlib.md5(rom_path.encode()).hexdigest()[:12]
    safe_name = f"rom_{path_hash}{ext}"
    link_path = os.path.join(_SYMLINK_DIR, safe_name)
    
    if os.path.exists(link_path):
        # Si le fichier existe et pointe vers le même inode, on le garde, sinon on le supprime
        if os.stat(link_path).st_ino == os.stat(rom_path).st_ino:
            return link_path
        os.unlink(link_path)
    
    try:
        os.link(rom_path, link_path)
    except OSError:
        # En cas d'échec (ex: partitions différentes), repli silencieux vers le chemin original
        print(f"[LAUNCH] Avertissement: Impossible de créer un hardlink pour {rom_path}")
        return rom_path
    
    return link_path
        
_last_launch_time = 0
_LAUNCH_LOCK = threading.Lock()
_LAUNCH_COOLDOWN = 5.0  # secondes de cooldown de sécurité globale entre les lancements


class ConsoleHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        # --- API : health check ---
        if self.path == "/api/health":
            health = {
                "status": "ok",
                "pid": os.getpid(),
                "uptime_info": "running",
                "games_count": len(scan_games()),
                "jeux_dir_exists": os.path.isdir(JEUX_DIR),
            }
            body = json.dumps(health, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # --- API : liste des jeux ---
        # --- API : diagnostic ---
        if self.path == "/api/diag":
            diag = {
                "flatpak": subprocess.run(["which", "flatpak"], capture_output=True).returncode == 0,
                "melonds_installed": subprocess.run(["flatpak", "info", "net.kuribo64.melonDS"], capture_output=True).returncode == 0,
                "display": os.environ.get("DISPLAY", "(non défini)"),
                "wayland": os.environ.get("WAYLAND_DISPLAY", "(non défini)"),
                "home": os.environ.get("HOME", "(non défini)"),
                "xdg_runtime": os.environ.get("XDG_RUNTIME_DIR", "(non défini)"),
                "dbus": os.environ.get("DBUS_SESSION_BUS_ADDRESS", "(non défini)"),
                "uid": os.getuid(),
                "pid": os.getpid(),
                "jeux_dir": JEUX_DIR,
                "jeux_dir_exists": os.path.isdir(JEUX_DIR),
                "games": [],
            }
            for g in scan_games():
                diag["games"].append({
                    "title": g["title"],
                    "id": g["id"],
                    "rom": g["rom"],
                    "rom_exists": os.path.exists(g["rom"]),
                    "rom_readable": os.access(g["rom"], os.R_OK),
                })
            # Tester l'env graphique
            test_env = _build_graphical_env()
            diag["launch_env"] = {
                "HOME": test_env.get("HOME"),
                "DISPLAY": test_env.get("DISPLAY"),
                "WAYLAND_DISPLAY": test_env.get("WAYLAND_DISPLAY"),
                "XAUTHORITY": test_env.get("XAUTHORITY"),
                "XDG_RUNTIME_DIR": test_env.get("XDG_RUNTIME_DIR"),
                "DBUS_SESSION_BUS_ADDRESS": test_env.get("DBUS_SESSION_BUS_ADDRESS"),
            }
            # Ajouter les derniers logs
            diag["latest_logs"] = ""
            try:
                import glob
                log_files = glob.glob(os.path.join(_LOG_DIR, "emu_*.log"))
                if log_files:
                    latest_log = max(log_files, key=os.path.getctime)
                    with open(latest_log, "r") as f:
                        diag["latest_logs"] = f.read()[-3000:] # 3000 derniers caractères
            except Exception as e:
                diag["latest_logs"] = f"Erreur de lecture: {e}"
            body = json.dumps(diag, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/games":
            games = scan_games()
            body = json.dumps(games, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # --- SSE Endpoint ---
        if self.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q = queue.Queue(maxsize=10)
            with sse_lock:
                sse_clients.append(q)

            print(f"[SSE] Client connecté ({len(sse_clients)} actif(s))")

            try:
                self.wfile.write(f"data: {json.dumps({'type': 'connected'})}\n\n".encode("utf-8"))
                self.wfile.flush()
            except Exception:
                with sse_lock:
                    if q in sse_clients:
                        sse_clients.remove(q)
                return

            try:
                while True:
                    data = q.get()
                    self.wfile.write(data)
                    self.wfile.flush()
            except (ConnectionResetError, BrokenPipeError, Exception):
                pass
            finally:
                with sse_lock:
                    if q in sse_clients:
                        sse_clients.remove(q)
                print(f"[SSE] Client déconnecté ({len(sse_clients)} actif(s))")
            return

        # --- Lancement générique : /launch/<id> ---
        if self.path.startswith("/launch/"):
            global _last_launch_time
            now = time.time()
            with _LAUNCH_LOCK:
                if now - _last_launch_time < _LAUNCH_COOLDOWN:
                    print(f"[LAUNCH] Requête ignorée (cooldown de {_LAUNCH_COOLDOWN}s actif pour éviter les multi-lancements)")
                    self.send_response(429)
                    self.end_headers()
                    self.wfile.write("Un lancement est déjà en cours...".encode("utf-8"))
                    return
                _last_launch_time = now

            game_id = urllib.parse.unquote(self.path[len("/launch/"):])
            print(f"[LAUNCH] Requête reçue pour game_id brut: {self.path[len('/launch/'):]!r}")
            print(f"[LAUNCH] Requête décodée: {game_id!r}")
            games = scan_games()

            # Essayer d'abord une correspondance exacte, sinon décoder les deux côtés
            match = next((g for g in games if g["id"] == game_id), None)
            if match is None:
                # Tenter aussi la comparaison avec le game_id brut (URL-encodé)
                raw_id = self.path[len("/launch/"):]
                match = next((g for g in games if g["id"] == raw_id), None)
            if match is None:
                # Dernier recours: décoder les deux côtés
                decoded_id = urllib.parse.unquote(game_id)
                match = next(
                    (g for g in games if urllib.parse.unquote(g["id"]) == decoded_id),
                    None
                )

            if match is None:
                print(f"[LAUNCH] ERREUR: Aucun jeu trouvé pour id={game_id!r}")
                print(f"[LAUNCH] IDs disponibles: {[g['id'] for g in games]}")
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Jeu introuvable")
                return

            rom_path = match["rom"]
            ext = os.path.splitext(rom_path)[1].lower()
            emulator_cmd = EMULATORS.get(ext)

            if emulator_cmd is None:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Emulateur non supporte")
                return

            if not os.path.exists(rom_path):
                print(f"[LAUNCH] ERREUR: ROM introuvable sur disque: {rom_path}")
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Fichier ROM introuvable")
                return

            if not os.access(rom_path, os.R_OK):
                print(f"[LAUNCH] ERREUR: fichier non lisible: {rom_path}")
                self.send_response(403)
                self.end_headers()
                self.wfile.write(f"ROM non lisible: {rom_path}".encode("utf-8"))
                return

            try:
                launch_env = _build_graphical_env()
                safe_path = _safe_rom_path(rom_path)
                cmd = emulator_cmd[1] + [safe_path]
                print(f"[LAUNCH] Commande: {cmd}")
                print(f"[LAUNCH] ROM réelle: {rom_path}")
                print(f"[LAUNCH] Hardlink  : {safe_path}")
                print(f"[LAUNCH] ROM taille: {os.path.getsize(rom_path)} octets")

                # Fichier de log pour capturer stderr sans bloquer le process
                import datetime
                log_name = datetime.datetime.now().strftime("emu_%Y%m%d_%H%M%S.log")
                log_path = os.path.join(_LOG_DIR, log_name)
                
                # Tuer l'émulateur existant avant d'en lancer un nouveau
                print("[LAUNCH] Arrêt des anciennes instances de l'émulateur...")
                if "flatpak" in emulator_cmd[1]:
                    subprocess.run(["flatpak", "kill", emulator_cmd[2]], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["pkill", "-f", emulator_cmd[2]], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["pkill", "-f", "melonDS"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)

                # --- GESTION DU RESET (À CHAQUE LANCEMENT) ---
                reset_melonds_config()
                
                is_file_log = True
                try:
                    log_file = open(log_path, "w")
                except OSError as e:
                    print(f"[LAUNCH] Impossible d'écrire dans {_LOG_DIR} ({e}). Repli sur /tmp...")
                    tmp_log_dir = "/tmp/emu_logs"
                    try:
                        os.makedirs(tmp_log_dir, exist_ok=True)
                        log_path = os.path.join(tmp_log_dir, log_name)
                        log_file = open(log_path, "w")
                    except OSError:
                        print("[LAUNCH] Impossible d'écrire dans /tmp. Repli sur DEVNULL")
                        log_file = subprocess.DEVNULL
                        is_file_log = False

                proc = subprocess.Popen(
                    cmd,
                    env=launch_env,
                    stdout=subprocess.DEVNULL,
                    stderr=log_file,
                    start_new_session=True,  # Détacher du process parent
                )

                # Enregistrer le démarrage pour couper input-remapper
                register_emulator_start()

                # Démarrer l'écoute du Kill Combo à la manette
                threading.Thread(target=gamepad_kill_listener, args=(proc,), daemon=True).start()

                # Ouvrir le menu du mappage à chaque lancement
                threading.Thread(target=simulate_mapping_menu_opening, daemon=True).start()

                # Attendre brièvement pour détecter un crash immédiat
                try:
                    proc.wait(timeout=3)
                    register_emulator_exit()  # Décrémenter car crash précoce
                    if is_file_log:
                        try:
                            log_file.close()
                            # Lire le log d'erreur
                            with open(log_path, "r") as f:
                                err_msg = f.read(1000)
                        except Exception as close_err:
                            err_msg = f"Erreur de lecture de log: {close_err}"
                    else:
                        err_msg = "Logs non disponibles (DEVNULL utilisé)."

                    print(f"[LAUNCH] ECHEC (code {proc.returncode}): {match['title']}")
                    if err_msg:
                        print(f"[LAUNCH] stderr: {err_msg[:500]}")
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(f"Emulateur crash (code {proc.returncode}): {err_msg[:300]}".encode("utf-8"))
                except subprocess.TimeoutExpired:
                    # Toujours en cours après 3s = lancement réussi
                    print(f"[LAUNCH] OK: {match['title']} (PID {proc.pid})")
                    if is_file_log:
                        try:
                            log_file.close()
                        except Exception:
                            pass
                    
                    # Démarrer le thread de surveillance de la durée de vie du process
                    threading.Thread(target=monitor_emulator_process, args=(proc,), daemon=True).start()
                    
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(f"Lancement: {match['title']}".encode("utf-8"))
            except Exception as e:
                print(f"[LAUNCH] Exception: {e}")
                import traceback
                traceback.print_exc()
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Erreur: {e}".encode("utf-8"))
            return

        # --- Fichiers statiques (Sécurité) ---
        # Ne servir que les fichiers de l'interface et le dossier Jeux, interdire le reste (ex: .py, .sh, .git)
        safe_path = self.path.split('?')[0]
        if safe_path == "/":
            self.path = "/index.html"
            safe_path = "/index.html"
        elif safe_path == "/roms" or safe_path == "/roms/":
            self.path = "/roms.html"
            safe_path = "/roms.html"
            
        allowed_files = ["/index.html", "/style.css", "/script.js", "/favicon.ico", "/roms.html"]
        lower_path = safe_path.lower()
        
        # Autoriser explicitement l'interface et les images du dossier Jeux/ et Assets/
        if safe_path in allowed_files or lower_path.startswith("/jeux/") or lower_path.startswith("/assets/"):
            super().do_GET()
        else:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Acces interdit (Securite)")

    def do_POST(self):
        # --- API : Maintenance Éteindre ---
        if self.path == "/api/system/shutdown":
            print("[SYSTEM] Arrêt du système demandé...")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Arret en cours...")
            
            def shutdown_system():
                cmds = [
                    ["systemctl", "poweroff"],
                    ["shutdown", "now"],
                    ["dbus-send", "--system", "--print-reply", "--dest=org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager.PowerOff", "boolean:true"]
                ]
                for cmd in cmds:
                    try:
                        res = subprocess.run(cmd, capture_output=True)
                        if res.returncode == 0:
                            print(f"[SYSTEM] Commande reussie: {cmd}")
                            return
                    except Exception as e:
                        print(f"[SYSTEM] Echec de la commande {cmd}: {e}")
            threading.Thread(target=shutdown_system, daemon=True).start()
            return

        # --- API : Maintenance Redémarrer ---
        if self.path == "/api/system/reboot":
            print("[SYSTEM] Redémarrage du système demandé...")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Redemarrage en cours...")
            
            def reboot_system():
                cmds = [
                    ["systemctl", "reboot"],
                    ["reboot"],
                    ["dbus-send", "--system", "--print-reply", "--dest=org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager.Reboot", "boolean:true"]
                ]
                for cmd in cmds:
                    try:
                        res = subprocess.run(cmd, capture_output=True)
                        if res.returncode == 0:
                            print(f"[SYSTEM] Commande reussie: {cmd}")
                            return
                    except Exception as e:
                        print(f"[SYSTEM] Echec de la commande {cmd}: {e}")
            threading.Thread(target=reboot_system, daemon=True).start()
            return

        # --- API : Maintenance Réveiller l'écran (Allumer) ---
        if self.path == "/api/system/wake":
            print("[SYSTEM] Réveil de l'écran demandé...")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Reveil en cours...")
            
            def wake_system():
                env = _build_graphical_env()
                try:
                    subprocess.run(["xset", "dpms", "force", "on"], env=env)
                    subprocess.run(["xset", "s", "reset"], env=env)
                except Exception as e:
                    print(f"[SYSTEM] Echec du reveil ecran: {e}")
            threading.Thread(target=wake_system, daemon=True).start()
            return

        # --- API : Importation de Jeux ---
        if self.path == "/api/upload":
            # Taille maximale d'upload : 600 Mo (protège contre le DoS par épuisement mémoire)
            MAX_UPLOAD_SIZE = 600 * 1024 * 1024
            STREAM_CHUNK_SIZE = 65536  # 64 Ko par chunk de lecture

            # Fichiers temporaires à nettoyer en fin de traitement
            _tmp_files_to_cleanup = []

            def _cleanup_tmp():
                for p in _tmp_files_to_cleanup:
                    try:
                        if p and os.path.exists(p):
                            os.unlink(p)
                    except OSError:
                        pass

            try:
                content_type = self.headers.get('Content-Type')
                if not content_type or 'multipart/form-data' not in content_type:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Type de contenu invalide. multipart/form-data requis.")
                    return

                boundary = content_type.split("boundary=")[1].encode('utf-8')
                content_length = int(self.headers.get('Content-Length', 0))

                # --- Protection DoS : rejet des requêtes trop volumineuses ---
                if content_length > MAX_UPLOAD_SIZE:
                    max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
                    # Vider le flux d'entrée pour éviter de bloquer le client
                    remaining = content_length
                    while remaining > 0:
                        discard = self.rfile.read(min(STREAM_CHUNK_SIZE, remaining))
                        if not discard:
                            break
                        remaining -= len(discard)
                    self.send_response(413)
                    self.end_headers()
                    self.wfile.write(f"Fichier trop volumineux. Taille max : {max_mb} Mo.".encode('utf-8'))
                    return

                if content_length == 0:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Requete vide.")
                    return

                # --- Streaming du corps vers un fichier temporaire (64 Ko par chunk) ---
                import tempfile
                import mmap
                import shutil

                tmp_body_fd, tmp_body_path = tempfile.mkstemp(dir=JEUX_DIR, prefix='.upload_body_')
                _tmp_files_to_cleanup.append(tmp_body_path)

                remaining = content_length
                with os.fdopen(tmp_body_fd, 'wb') as tmp_f:
                    while remaining > 0:
                        chunk = self.rfile.read(min(STREAM_CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        tmp_f.write(chunk)
                        remaining -= len(chunk)

                # --- Parsing multipart via mmap (pas de chargement complet en RAM) ---
                rom_tmp_path = None   # chemin vers le fichier temp contenant les données ROM
                rom_filename = None
                cover_tmp_path = None  # chemin vers le fichier temp contenant les données cover
                cover_filename = None
                existing_rom_filename = None

                file_size = os.path.getsize(tmp_body_path)
                if file_size == 0:
                    _cleanup_tmp()
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Requete vide.")
                    return

                with open(tmp_body_path, 'rb') as f:
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        boundary_marker = b'--' + boundary

                        # Trouver toutes les positions des frontières multipart
                        positions = []
                        search_pos = 0
                        while True:
                            pos = mm.find(boundary_marker, search_pos)
                            if pos == -1:
                                break
                            positions.append(pos)
                            search_pos = pos + len(boundary_marker)

                        # Traiter chaque partie entre les frontières
                        for i in range(len(positions)):
                            part_start = positions[i] + len(boundary_marker)

                            # Détecter la frontière de fin (--)
                            if part_start + 2 <= len(mm) and mm[part_start:part_start + 2] == b'--':
                                break

                            # Sauter le \r\n après la frontière
                            if part_start + 2 <= len(mm) and mm[part_start:part_start + 2] == b'\r\n':
                                part_start += 2

                            part_end = positions[i + 1] if i + 1 < len(positions) else file_size

                            # Séparer les en-têtes du corps de la partie
                            header_sep = mm.find(b'\r\n\r\n', part_start, part_end)
                            if header_sep == -1:
                                continue

                            headers_str = mm[part_start:header_sep].decode('utf-8', errors='ignore')
                            body_start = header_sep + 4
                            # Retirer le \r\n final avant la prochaine frontière
                            body_end = part_end - 2 if part_end >= 2 else part_end

                            import re
                            part_name = None
                            part_filename = None
                            name_match = re.search(r'name="([^"]+)"', headers_str)
                            if name_match:
                                part_name = name_match.group(1)
                            filename_match = re.search(r'filename="([^"]+)"', headers_str)
                            if filename_match:
                                part_filename = filename_match.group(1)

                            data_len = body_end - body_start
                            if data_len <= 0:
                                continue

                            if part_name == "file" or (not rom_filename and part_filename and os.path.splitext(part_filename)[1].lower() in ('.nds', '.zip')):
                                rom_filename = part_filename
                                # Écrire les données ROM dans un fichier temp (par chunks depuis le mmap)
                                rom_fd, rom_tmp_path = tempfile.mkstemp(dir=JEUX_DIR, prefix='.upload_rom_')
                                _tmp_files_to_cleanup.append(rom_tmp_path)
                                with os.fdopen(rom_fd, 'wb') as rom_f:
                                    offset = body_start
                                    while offset < body_end:
                                        end = min(offset + STREAM_CHUNK_SIZE, body_end)
                                        rom_f.write(mm[offset:end])
                                        offset = end

                            elif part_name == "cover" or (not cover_filename and part_filename and os.path.splitext(part_filename)[1].lower() in ('.png', '.jpg', '.jpeg', '.webp')):
                                cover_filename = part_filename
                                # Les covers sont petites, mais on les écrit aussi sur disque par cohérence
                                cov_fd, cover_tmp_path = tempfile.mkstemp(dir=JEUX_DIR, prefix='.upload_cov_')
                                _tmp_files_to_cleanup.append(cover_tmp_path)
                                with os.fdopen(cov_fd, 'wb') as cov_f:
                                    cov_f.write(mm[body_start:body_end])

                            elif part_name == "existing_rom_filename":
                                existing_rom_filename = mm[body_start:body_end].decode('utf-8', errors='ignore').strip()

                # Le fichier body temporaire n'est plus nécessaire
                try:
                    os.unlink(tmp_body_path)
                    _tmp_files_to_cleanup.remove(tmp_body_path)
                except OSError:
                    pass

                # Cas 1 : Ajout/mise à jour uniquement de la cover pour un jeu existant
                if existing_rom_filename and cover_tmp_path and cover_filename:
                    # Sécurité : assainir le nom de fichier pour empêcher la traversée de répertoire
                    existing_rom_filename = os.path.basename(existing_rom_filename)
                    if not existing_rom_filename or '..' in existing_rom_filename:
                        _cleanup_tmp()
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b"Nom de fichier invalide.")
                        return
                    rom_title = os.path.splitext(existing_rom_filename)[0]
                    target_folder = os.path.join(JEUX_DIR, "NDS", rom_title)
                    # Vérification supplémentaire : le chemin résolu doit rester dans JEUX_DIR
                    if not os.path.realpath(target_folder).startswith(os.path.realpath(JEUX_DIR)):
                        _cleanup_tmp()
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b"Chemin de destination invalide.")
                        return
                    if os.path.isdir(target_folder):
                        cover_ext = os.path.splitext(cover_filename)[1].lower()
                        # Supprimer les anciennes covers pour éviter les doublons avec extensions différentes
                        for ext_to_del in ('.png', '.jpg', '.jpeg', '.webp'):
                            old_cov = os.path.join(target_folder, "cover" + ext_to_del)
                            if os.path.exists(old_cov):
                                os.unlink(old_cov)
                        
                        target_cover_path = os.path.join(target_folder, "cover" + cover_ext)
                        shutil.copyfile(cover_tmp_path, target_cover_path)
                        
                        _cleanup_tmp()
                        notify_clients("reload")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "success", "message": "Couverture synchronisee avec succes."}).encode('utf-8'))
                        return
                    else:
                        _cleanup_tmp()
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b"Dossier de jeu introuvable pour la couverture.")
                        return

                if not rom_tmp_path or not rom_filename:
                    _cleanup_tmp()
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Aucun fichier de jeu valide trouve dans la requete.")
                    return

                rom_filename = os.path.basename(rom_filename)
                temp_upload_path = os.path.join(JEUX_DIR, rom_filename)
                shutil.move(rom_tmp_path, temp_upload_path)
                if rom_tmp_path in _tmp_files_to_cleanup:
                    _tmp_files_to_cleanup.remove(rom_tmp_path)
                _tmp_files_to_cleanup.append(temp_upload_path)
                
                ext = os.path.splitext(rom_filename)[1].lower()
                
                if ext == '.zip':
                    import zipfile
                    extracted_any = False
                    
                    try:
                        with zipfile.ZipFile(temp_upload_path, 'r') as zip_ref:
                            for file_info in zip_ref.infolist():
                                if file_info.is_dir() or file_info.filename.startswith('__MACOSX') or os.path.basename(file_info.filename).startswith('.'):
                                    continue
                                
                                file_ext = os.path.splitext(file_info.filename)[1].lower()
                                if file_ext in ROM_EXTENSIONS:
                                    rom_title = os.path.splitext(os.path.basename(file_info.filename))[0]
                                    emu_folder = detect_emulator_for_ext(file_ext) or "NDS"
                                    target_folder = os.path.join(JEUX_DIR, emu_folder, rom_title)
                                    os.makedirs(target_folder, exist_ok=True)
                                    
                                    target_rom_path = os.path.join(target_folder, os.path.basename(file_info.filename))
                                    with zip_ref.open(file_info) as source, open(target_rom_path, 'wb') as target:
                                        shutil.copyfileobj(source, target)
                                    extracted_any = True
                                    
                                    # Écriture de la cover associée si présente
                                    if cover_tmp_path and cover_filename:
                                        cover_ext = os.path.splitext(cover_filename)[1].lower()
                                        target_cover_path = os.path.join(target_folder, "cover" + cover_ext)
                                        shutil.copyfile(cover_tmp_path, target_cover_path)
                        
                        os.unlink(temp_upload_path)
                        if temp_upload_path in _tmp_files_to_cleanup:
                            _tmp_files_to_cleanup.remove(temp_upload_path)
                        
                        if extracted_any:
                            _cleanup_tmp()
                            notify_clients("reload")
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"status": "success", "message": "Fichier ZIP extrait avec succes."}).encode('utf-8'))
                        else:
                            _cleanup_tmp()
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b"Aucune ROM valide (.nds) trouvee dans le fichier ZIP.")
                    except Exception as e:
                        if os.path.exists(temp_upload_path):
                            os.unlink(temp_upload_path)
                            if temp_upload_path in _tmp_files_to_cleanup:
                                _tmp_files_to_cleanup.remove(temp_upload_path)
                        _cleanup_tmp()
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(f"Erreur lors de la decompression du ZIP : {e}".encode('utf-8'))
                
                elif ext in ROM_EXTENSIONS:
                    rom_title = os.path.splitext(rom_filename)[0]
                    emu_folder = detect_emulator_for_ext(ext) or "NDS"
                    target_folder = os.path.join(JEUX_DIR, emu_folder, rom_title)
                    os.makedirs(target_folder, exist_ok=True)
                    
                    target_rom_path = os.path.join(target_folder, rom_filename)
                    os.rename(temp_upload_path, target_rom_path)
                    if temp_upload_path in _tmp_files_to_cleanup:
                        _tmp_files_to_cleanup.remove(temp_upload_path)
                    
                    # Écriture de la cover associée si présente
                    if cover_tmp_path and cover_filename:
                        cover_ext = os.path.splitext(cover_filename)[1].lower()
                        target_cover_path = os.path.join(target_folder, "cover" + cover_ext)
                        shutil.copyfile(cover_tmp_path, target_cover_path)
                    
                    _cleanup_tmp()
                    notify_clients("reload")
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "message": "ROM importee avec succes."}).encode('utf-8'))
                else:
                    os.unlink(temp_upload_path)
                    if temp_upload_path in _tmp_files_to_cleanup:
                        _tmp_files_to_cleanup.remove(temp_upload_path)
                    _cleanup_tmp()
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(f"Extension de fichier non supportee : {ext}".encode('utf-8'))
                    
            except Exception as e:
                _cleanup_tmp()
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Erreur serveur : {e}".encode('utf-8'))
            return

    def log_message(self, format, *args):
        msg = format % args
        if "/api/" not in msg:
            print(f"[{self.address_string()}] {msg}")


# Serveur multithreadé pour SSE + requêtes concurrentes
class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def kill_previous_server(port: int):
    """Tue tout process qui écoute sur le port donné (évite 'Address already in use')."""
    import signal
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split()
        my_pid = os.getpid()
        for pid_str in pids:
            try:
                pid = int(pid_str)
                if pid != my_pid:
                    os.kill(pid, signal.SIGTERM)
                    print(f"[INIT] Process {pid} tué (occupait le port {port})")
            except (ValueError, ProcessLookupError):
                pass
        if pids:
            time.sleep(0.5)
    except FileNotFoundError:
        # fuser n'est pas installé, on tente quand même
        pass
    except Exception as e:
        print(f"[INIT] Impossible de libérer le port : {e}")




def clean_maintenance():
    print("[MAINTENANCE] Nettoyage des fichiers temporaires et de maintenance...")
    
    # 1. Nettoyer les fichiers de logs (recréer le dossier vide)
    if os.path.exists(_LOG_DIR):
        try:
            import shutil
            shutil.rmtree(_LOG_DIR)
            os.makedirs(_LOG_DIR, exist_ok=True)
            print(f"[MAINTENANCE] Dossier de logs réinitialisé : {_LOG_DIR}")
        except Exception as e:
            print(f"[MAINTENANCE] Erreur lors de la purge de {_LOG_DIR} : {e}")
            
    # 2. Nettoyer les liens de lancement temporaires (recréer le dossier vide)
    if os.path.exists(_SYMLINK_DIR):
        try:
            import shutil
            shutil.rmtree(_SYMLINK_DIR)
            os.makedirs(_SYMLINK_DIR, exist_ok=True)
            print(f"[MAINTENANCE] Dossier de lancements temporaires réinitialisé : {_SYMLINK_DIR}")
        except Exception as e:
            print(f"[MAINTENANCE] Erreur lors de la purge de {_SYMLINK_DIR} : {e}")
            
    # 3. S'assurer des permissions pour l'utilisateur
    sudo_user = os.getenv("SUDO_USER")
    if sudo_user:
        import pwd
        try:
            user_info = pwd.getpwnam(sudo_user)
            uid = user_info.pw_uid
            gid = user_info.pw_gid
            if os.path.exists(_LOG_DIR):
                os.chown(_LOG_DIR, uid, gid)
            if os.path.exists(_SYMLINK_DIR):
                os.chown(_SYMLINK_DIR, uid, gid)
        except Exception:
            pass

    print("✅ Nettoyage de maintenance terminé. Le système est opérationnel et prêt !")
    sys.exit(0)


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean_maintenance()

    # Libérer le port si un ancien serveur tourne encore
    kill_previous_server(PORT)

    # Autoriser l'affichage X11 pour les processus enfants (émulateurs)
    # xhost n'est utile que sous X11 ou Xwayland, pas sous Wayland pur
    env_for_xhost = _build_graphical_env()
    has_x11 = bool(env_for_xhost.get("DISPLAY"))
    if has_x11:
        xhost_path = subprocess.run(["which", "xhost"], capture_output=True).returncode == 0
        if xhost_path:
            subprocess.run(
                ["xhost", "+local:"],
                env=env_for_xhost,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[INIT] xhost +local: appliqué (X11/Xwayland détecté)")
        else:
            print("[INIT] xhost non installé — ignoré")
    else:
        print("[INIT] Pas de DISPLAY X11 — xhost ignoré (Wayland pur)")

    # Démarrage de watchdog
    observer = Observer()
    handler = RomWatchdogHandler()
    observer.schedule(handler, path=JEUX_DIR, recursive=True)
    observer.start()
    print(f"[WATCHDOG] Observateur démarré sur : {JEUX_DIR}")

    try:
        with ThreadingHTTPServer(("0.0.0.0", PORT), ConsoleHandler) as httpd:
            print(f"Serveur Jeu démarré sur http://0.0.0.0:{PORT}")
            print(f"Dossier ROMs : {JEUX_DIR}")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur...")
    finally:
        observer.stop()
        observer.join()
        print("Serveur et observateur arrêtés.")
