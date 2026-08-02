# Cartographie du dépôt — MyNintendoTV

> Ce fichier est le miroir **human-readable** de [`.claude/project-structure.json`](.claude/project-structure.json)
> (machine-readable, lu par le serveur MCP local). **Les deux doivent être mis à jour dans le
> même commit** dès qu'un fichier significatif est ajouté, déplacé ou supprimé — sinon la
> cartographie devient trompeuse pour le prochain humain ou agent qui la consulte. Pour le détail
> du "comment/pourquoi" de l'architecture, voir [README.md](README.md).

```
MyNintendoTV/
├── mynintendotv.py        Backend unique (http.server, ~1500 lignes, sans framework).
│                         Scan du catalogue, API REST + SSE, upload ROM sécurisé (mmap streamé),
│                         lancement melonDS (hardlink anti-caractères-spéciaux, env graphique
│                         hérité pour un service systemd headless), kill-combo manette (evdev),
│                         auto-ouverture du menu de mappage des touches (ydotool).
│
├── index.html             Squelette de l'UI catalogue (plein écran, mode kiosk) — logique dans script.js.
├── script.js               Roue "cover flow" (clavier + Gamepad API), lancement de jeu avec
│                         cooldown anti-double-clic, rechargement temps réel via SSE (/api/events).
├── roms.html               Interface d'administration réseau (/roms) : import drag&drop de
│                         fichiers ET de dossiers entiers, appariement automatique ROM↔cover,
│                         synchronisation incrémentale (jeux déjà présents = skip, sauf cover à
│                         mettre à jour), boutons shutdown/wake/reboot.
├── style.css               Feuille de style globale (thème sombre, roue 3D, notifications).
│
├── install.sh              Installation système complète (root) : dépendances, Flatpak + melonDS,
│                         udev (gamepad + uinput/ydotool), service systemd --user, session kiosk
│                         Openbox/Chromium, autologin. Idempotent, ~10 étapes numérotées [0]→[7.5].
├── purge.sh                Contrepartie exacte de install.sh — désinstallation complète.
│                         Toute étape ajoutée à install.sh doit avoir sa contrepartie ici.
├── requirements.txt        Dépendances Python : watchdog (live-reload SSE) + evdev (kill-combo).
├── config.json              (Généré par install.sh §0.5, absent du repo) — langue firmware DS.
│
├── Jeux/                    (non versionné) Stockage des ROMs : Jeux/<Emulateur>/<Titre>/rom+cover.
├── Assets/                  Images/Videos de l'interface, servies directement par le backend.
├── emu_logs/                (non versionné) Logs stderr des lancements d'émulateur.
├── launch_tmp/               (non versionné) Hardlinks temporaires vers les ROMs en cours de lancement.
│
├── README.md                Doc technique complète : installation, architecture, admin, sécurité.
├── structure.md             Ce fichier.
├── LICENSE                  AGPL-3.0.
└── .claude/
    ├── project-structure.json   Cartographie machine-readable (non versionné, voir .gitignore).
    └── mcp/server.mjs           Serveur MCP local qui expose cette cartographie à l'agent IA
                                (non versionné).
```

## Sujets transversaux

Regroupements pour une question large, sans deviner les bons mots-clés :

| Sujet | Fichiers concernés |
|---|---|
| Sécurité réseau et filtrage de fichiers | `mynintendotv.py` (ConsoleHandler.do_GET, liste `allowed_files`), `README.md` §2.5 |
| Upload et import de ROMs | `mynintendotv.py` (`/api/upload`), `roms.html` (`queueUploads`, `parseDroppedEntries`) |
| Lancement et cycle de vie de l'émulateur | `mynintendotv.py` (`/launch/<id>`, `_safe_rom_path`, `_build_graphical_env`, `monitor_emulator_process`) |
| Manette / gamepad | `mynintendotv.py` (`gamepad_kill_listener`), `script.js` (`pollGamepads`) |
| Installation et déploiement kiosk | `install.sh`, `purge.sh`, `README.md` §1 et §2 |
| Interface catalogue (cover flow) | `index.html`, `script.js`, `style.css` |
| Interface d'administration réseau | `roms.html` |
| Live-reload / notifications temps réel | `mynintendotv.py` (SSE, `notify_clients`, `RomWatchdogHandler`), `script.js` (`setupLiveReload`) |
| Configuration firmware DS | `config.json`, `install.sh` §0.5, `mynintendotv.py` (`reset_melonds_config`) |

## Comment interroger cette cartographie sans lire ce fichier

Un serveur MCP local (`.claude/mcp/server.mjs`, enregistré dans `.mcp.json`) relit
`project-structure.json` à chaque appel — jamais périmé. Voir [AGENTS.md](AGENTS.md) pour la règle
d'usage complète (`find_file`, `list_topics`, `get_topic_files`, `list_workspaces`, `get_full_map`).
