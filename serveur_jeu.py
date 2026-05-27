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
    try:
        import watchdog
    except ImportError:
        if "--install" in sys.argv:
            print("Installation des dependances système requises (python3-watchdog)...")
            try:
                # Privilégier apt-get sur Debian/Ubuntu pour éviter les conflits PEP 668 avec pip
                subprocess.run(["apt-get", "update"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["apt-get", "install", "-y", "python3-watchdog"], check=True)
                print("Dependances installees.")
                # Redémarrer le script pour prendre en compte les nouveaux modules
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except FileNotFoundError:
                # Si apt-get n'est pas trouvé, on tente pip
                subprocess.run([sys.executable, "-m", "pip", "install", "watchdog"], check=True)
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except Exception as e:
                print(f"Erreur lors de l'installation des dependances: {e}")
                sys.exit(1)
        else:
            print("Erreur : module 'watchdog' non trouvé.")
            print("Pour installer automatiquement les dépendances et le service, exécutez :")
            print("sudo python3 serveur_jeu.py --install")
            print("Pour nettoyer les logs et réinitialiser l'émulateur (maintenance), exécutez :")
            print("python3 serveur_jeu.py --clean")
            sys.exit(1)

check_dependencies()

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
    ".nds": ("NDS", ["flatpak", "run", "--filesystem=host", "net.kuribo64.melonDS"], "net.kuribo64.melonDS"),
}

# Extensions reconnues comme ROMs
ROM_EXTENSIONS = set(EMULATORS.keys())

# Liste des clients connectés aux Server-Sent Events (SSE)
sse_clients = []
sse_lock = threading.Lock()

# Debounce : évite de spammer le frontend avec plusieurs reloads pour un seul ZIP
_last_notify_time = 0
_NOTIFY_DEBOUNCE = 1.5  # secondes

FIRST_LAUNCH_MARKER = os.path.join(BASE_DIR, ".first_launch_done")
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


def reset_melonds_config():
    home = os.path.expanduser("~")
    config_dir = os.path.join(home, ".var/app/net.kuribo64.melonDS/config/melonDS")
    config_file = os.path.join(config_dir, "melonDS.ini")
    print(f"[LAUNCH] Réinitialisation de la configuration de l'émulateur dans : {config_file}")
    try:
        if os.path.exists(config_file):
            os.remove(config_file)
            print("[LAUNCH] Fichier melonDS.ini existant supprimé avec succès.")
        else:
            os.makedirs(config_dir, exist_ok=True)
            print("[LAUNCH] Dossier de configuration créé.")
    except Exception as e:
        print(f"[LAUNCH] Erreur lors de la suppression de la configuration : {e}")


def simulate_mapping_menu_opening():
    time.sleep(2.0)  # Attendre que l'émulateur soit bien affiché
    print("[LAUNCH] Simulation des touches avec ydotool pour ouvrir la page du mappage des touches...")
    try:
        # Alt (touche 56) pour ouvrir le menu
        subprocess.run(["ydotool", "key", "56:1", "56:0"], check=False)
        time.sleep(0.3)
        # Droite (touche 106)
        subprocess.run(["ydotool", "key", "106:1", "106:0"], check=False)
        time.sleep(0.1)
        # Droite (touche 106)
        subprocess.run(["ydotool", "key", "106:1", "106:0"], check=False)
        time.sleep(0.1)
        # Bas (touche 108)
        subprocess.run(["ydotool", "key", "108:1", "108:0"], check=False)
        time.sleep(0.1)
        # Entrée (touche 28) pour valider Config > Input and Hotkeys
        subprocess.run(["ydotool", "key", "28:1", "28:0"], check=False)
        print("[LAUNCH] Mappage des touches ouvert avec succès via ydotool.")
    except Exception as e:
        print(f"[LAUNCH] Échec de la simulation ydotool : {e}")


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
            notify_clients("reload")


def scan_games() -> list[dict]:
    """Scanne JEUX_DIR récursivement et retourne la liste des ROMs trouvées."""
    games = []
    if not os.path.isdir(JEUX_DIR):
        return games

    for emulator_folder in sorted(os.listdir(JEUX_DIR)):
        emulator_path = os.path.join(JEUX_DIR, emulator_folder)
        if not os.path.isdir(emulator_path):
            continue

        for entry in sorted(os.scandir(emulator_path), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            game_folder = entry.path
            for f in os.listdir(game_folder):
                ext = os.path.splitext(f)[1].lower()
                if ext not in EMULATORS:
                    continue
                rom_path = os.path.join(game_folder, f)
                title = os.path.splitext(f)[0]
                game_id = slugify(title)
                emulator_name = EMULATORS[ext][0]

                # Chercher une cover dans le dossier du jeu
                cover_url = None
                for img_ext in (".png", ".jpg", ".jpeg"):
                    cover_candidates = [
                        os.path.join(game_folder, "cover" + img_ext),
                        os.path.join(game_folder, title + img_ext),
                    ]
                    for candidate_file in os.listdir(game_folder):
                        if candidate_file.lower().endswith(img_ext):
                            cover_candidates.append(os.path.join(game_folder, candidate_file))
                    for candidate in cover_candidates:
                        if os.path.isfile(candidate):
                            rel = os.path.relpath(candidate, BASE_DIR)
                            cover_url = "/" + rel.replace(os.sep, "/")
                            break
                    if cover_url:
                        break

                games.append({
                    "id": game_id,
                    "title": title,
                    "rom": rom_path,
                    "emulator": emulator_name,
                    "cover": cover_url,
                })
                break  # Une seule ROM par dossier de jeu

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


class WiiHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
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

                # --- GESTION DU PREMIER LANCEMENT & RESET ---
                is_first_launch = not os.path.exists(FIRST_LAUNCH_MARKER)
                if is_first_launch:
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

                # Si premier lancement, ouvrir le menu du mappage et créer le fichier marqueur
                if is_first_launch:
                    threading.Thread(target=simulate_mapping_menu_opening, daemon=True).start()
                    try:
                        with open(FIRST_LAUNCH_MARKER, "w") as f:
                            f.write("done")
                    except Exception as e:
                        print(f"[LAUNCH] Impossible de créer le marqueur de premier lancement: {e}")

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

        # --- Fichiers statiques ---
        super().do_GET()

    def do_POST(self):
        self.send_response(405)
        self.end_headers()

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


def install_service():
    if os.geteuid() != 0:
        print("Erreur : l'installation du service nécessite les droits administrateur (root).")
        print("Relancez avec : sudo python3 serveur_jeu.py --install")
        sys.exit(1)
        
    print("Vérification et installation des émulateurs (Flatpak & MelonDS)...")
    try:
        subprocess.run(["apt-get", "install", "-y", "flatpak"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["flatpak", "remote-add", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"], check=True, stdout=subprocess.DEVNULL)
        print("Installation de net.kuribo64.melonDS (cela peut prendre un moment)...")
        subprocess.run(["flatpak", "install", "-y", "--noninteractive", "flathub", "net.kuribo64.melonDS"], check=False)
        # Autoriser MelonDS à accéder à l'ensemble du système de fichiers
        subprocess.run(["flatpak", "override", "--filesystem=host", "net.kuribo64.melonDS"], check=False)
        subprocess.run(["flatpak", "override", "--device=all", "net.kuribo64.melonDS"], check=False)
        subprocess.run(["flatpak", "override", "--share=ipc", "net.kuribo64.melonDS"], check=False)
        subprocess.run(["flatpak", "override", "--socket=x11", "net.kuribo64.melonDS"], check=False)
        subprocess.run(["flatpak", "override", "--socket=wayland", "net.kuribo64.melonDS"], check=False)
        subprocess.run(["flatpak", "override", "--socket=pulseaudio", "net.kuribo64.melonDS"], check=False)
    except Exception as e:
        print(f"Avertissement : Erreur lors de l'installation de MelonDS : {e}")

    # Autoriser l'affichage X11 depuis tous les processus locaux
    print("Autorisation de l'affichage X11 pour les processus locaux (xhost)...")
    subprocess.run(["apt-get", "install", "-y", "x11-xserver-utils"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    script_path = os.path.abspath(__file__)
    working_dir = os.path.dirname(script_path)
    user = os.getenv("SUDO_USER") or os.getenv("USER") or "root"
    
    import pwd
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        uid = 1000
    
    service_content = f"""[Unit]
Description=Serveur Jeu Emulateur
After=network.target

[Service]
Type=simple
WorkingDirectory={working_dir}
ExecStart=/usr/bin/python3 {script_path}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
    import pwd
    try:
        user_info = pwd.getpwnam(user)
        uid = user_info.pw_uid
        gid = user_info.pw_gid
    except KeyError:
        uid = 1000
        gid = 1000

    # Stop and disable old system service si elle existe
    subprocess.run(["systemctl", "stop", "serveur_jeu.service"], stderr=subprocess.DEVNULL)
    subprocess.run(["systemctl", "disable", "serveur_jeu.service"], stderr=subprocess.DEVNULL)

    # Création des dossiers du service utilisateur
    user_home = os.path.expanduser(f"~{user}")
    systemd_user_dir = os.path.join(user_home, ".config", "systemd", "user")
    os.makedirs(systemd_user_dir, exist_ok=True)
    
    # Corrige les permissions du dossier .config au cas où il aurait été créé par root
    os.system(f"chown -R {uid}:{gid} {user_home}/.config")
    
    # Corrige également les permissions des dossiers annexes
    if os.path.exists(_LOG_DIR):
        os.system(f"chown -R {uid}:{gid} {_LOG_DIR}")
    if os.path.exists(_SYMLINK_DIR):
        os.system(f"chown -R {uid}:{gid} {_SYMLINK_DIR}")

    service_path = os.path.join(systemd_user_dir, "serveur_jeu.service")
    try:
        with open(service_path, "w") as f:
            f.write(service_content)
        os.chown(service_path, uid, gid)
    except Exception as e:
        print(f"Erreur lors de la création du fichier service utilisateur : {e}")
        sys.exit(1)
        
    print(f"✅ Service utilisateur créé : {service_path}")
    print(f"  WorkingDirectory: {working_dir}")
    print(f"  ExecStart: /usr/bin/python3 {script_path}")
    
    print("Activation du Linger (démarrage automatique au boot sans obliger l'utilisateur à se connecter)...")
    subprocess.run(["loginctl", "enable-linger", user], check=False)

    def run_systemd_user(cmd):
        cmd_full = f"XDG_RUNTIME_DIR=/run/user/{uid} {cmd}"
        subprocess.run(["su", "-", user, "-c", cmd_full], check=True)

    print("Rechargement de systemd --user...")
    run_systemd_user("systemctl --user daemon-reload")
    
    print("Activation du service au démarrage (espace utilisateur)...")
    run_systemd_user("systemctl --user enable serveur_jeu.service")
    
    print("Démarrage du service (espace utilisateur)...")
    run_systemd_user("systemctl --user restart serveur_jeu.service")
    
    print("✅ Installation terminée avec succès !")
    print("Le serveur est désormais lié de manière native à la session graphique de l'utilisateur.")
    sys.exit(0)


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
            
    # 3. Supprimer le marqueur de premier lancement pour permettre une reconfiguration
    if os.path.exists(FIRST_LAUNCH_MARKER):
        try:
            os.remove(FIRST_LAUNCH_MARKER)
            print(f"[MAINTENANCE] Fichier marqueur de premier lancement supprimé : {FIRST_LAUNCH_MARKER}")
        except Exception as e:
            print(f"[MAINTENANCE] Impossible de supprimer le marqueur : {e}")
            
    # 4. S'assurer des permissions pour l'utilisateur
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
    if "--install" in sys.argv:
        install_service()
    if "--clean" in sys.argv:
        clean_maintenance()

    # Libérer le port si un ancien serveur tourne encore
    kill_previous_server(PORT)

    # Autoriser l'affichage X11 pour les processus enfants (émulateurs)
    env_for_xhost = _build_graphical_env()
    subprocess.run(
        ["xhost", "+local:"],
        env=env_for_xhost,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Démarrage de watchdog
    observer = Observer()
    handler = RomWatchdogHandler()
    observer.schedule(handler, path=JEUX_DIR, recursive=True)
    observer.start()
    print(f"[WATCHDOG] Observateur démarré sur : {JEUX_DIR}")

    try:
        with ThreadingHTTPServer(("0.0.0.0", PORT), WiiHandler) as httpd:
            print(f"Serveur Jeu démarré sur http://0.0.0.0:{PORT}")
            print(f"Dossier ROMs : {JEUX_DIR}")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur...")
    finally:
        observer.stop()
        observer.join()
        print("Serveur et observateur arrêtés.")
