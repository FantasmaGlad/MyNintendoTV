import http.server
import socketserver
import subprocess
import os
import json
import urllib.parse
import queue
import threading
import time
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

PORT = 8080

# Racine des ROMs, organisée par émulateur
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JEUX_DIR = os.path.join(BASE_DIR, "Jeux")
# S'assurer que le dossier Jeux existe
os.makedirs(JEUX_DIR, exist_ok=True)

# Mapping extension → (émulateur, commande flatpak)
EMULATORS = {
    ".nds": ("NDS", ["flatpak", "run", "net.kuribo64.melonDS", "-f"]),
}

# Extensions reconnues comme ROMs
ROM_EXTENSIONS = set(EMULATORS.keys())

# Liste des clients connectés aux Server-Sent Events (SSE)
sse_clients = []
sse_lock = threading.Lock()

# Debounce : évite de spammer le frontend avec plusieurs reloads pour un seul ZIP
_last_notify_time = 0
_NOTIFY_DEBOUNCE = 1.5  # secondes


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





class WiiHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        # --- API : liste des jeux ---
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
            game_id = self.path[len("/launch/"):]
            games = scan_games()
            match = next((g for g in games if g["id"] == game_id), None)

            if match is None:
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
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Fichier ROM introuvable")
                return

            try:
                subprocess.Popen(emulator_cmd[1] + [rom_path])
                self.send_response(200)
                self.end_headers()
                self.wfile.write(f"Lancement : {match['title']}".encode("utf-8"))
                print(f"[LAUNCH] {match['title']} ({match['emulator']})")
            except Exception as e:
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
        if "/api/" not in args[0]:
            print(f"[{self.address_string()}] {format % args}")


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
        
    script_path = os.path.abspath(__file__)
    working_dir = os.path.dirname(script_path)
    user = os.getenv("SUDO_USER") or os.getenv("USER") or "root"
    
    service_content = f"""[Unit]
Description=Serveur Jeu Emulateur
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={working_dir}
ExecStart=/usr/bin/python3 {script_path}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
    service_path = "/etc/systemd/system/serveur_jeu.service"
    try:
        with open(service_path, "w") as f:
            f.write(service_content)
    except Exception as e:
        print(f"Erreur lors de la création du fichier service : {e}")
        sys.exit(1)
        
    print(f"✅ Service créé : {service_path}")
    print(f"  User: {user}")
    print(f"  WorkingDirectory: {working_dir}")
    print(f"  ExecStart: /usr/bin/python3 {script_path}")
    
    print("Rechargement de systemd...")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    print("Activation du service au démarrage...")
    subprocess.run(["systemctl", "enable", "serveur_jeu.service"], check=True)
    print("Démarrage du service...")
    subprocess.run(["systemctl", "start", "serveur_jeu.service"], check=True)
    
    print("🎉 Service installé et démarré avec succès !")
    print("Il se lancera désormais automatiquement au démarrage de la machine.")
    sys.exit(0)


if __name__ == "__main__":
    if "--install" in sys.argv:
        install_service()

    # Libérer le port si un ancien serveur tourne encore
    kill_previous_server(PORT)

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
