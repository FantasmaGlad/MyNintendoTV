# Consignes pour l'agent IA — MyNintendoTV

## 1. Architecture (vue d'ensemble)

Projet unique (pas de monorepo) : un backend Python sans framework (`mynintendotv.py`, stdlib
`http.server`) sert un frontend HTML/CSS/JS statique et pilote localement un émulateur Nintendo DS
(melonDS via Flatpak) sur une machine Linux transformée en console kiosk. `install.sh`/`purge.sh`
gèrent le déploiement système (systemd, session kiosk, udev).

Documentation détaillée : [README.md](README.md). Cartographie fichier par fichier :
[structure.md](structure.md).

## 2. RÈGLE D'OR : utiliser le serveur MCP avant d'explorer à l'aveugle

> Avant un `grep` large ou une exploration au hasard, utilise le serveur MCP local
> `mynintendotv-project-map` : `find_file(query)`, `list_topics()`, `get_topic_files(topic)`,
> `list_workspaces()`, `get_full_map()`.

Ce serveur relit `.claude/project-structure.json` à chaque appel — jamais périmé, même si la
cartographie vient d'être modifiée dans la session en cours.

## 3. Maintenance de la cartographie

Toute modification de structure (ajout/déplacement/suppression d'un fichier significatif) impose
une mise à jour **dans le même commit** de [structure.md](structure.md) ET
`.claude/project-structure.json`. Un de ces deux fichiers modifié sans l'autre rend la
cartographie trompeuse pour la prochaine session.

`.claude/project-structure.json`, `.claude/mcp/` et `.mcp.json` sont volontairement exclus du
suivi git (voir `.gitignore`) : ce sont des outils de travail locaux pour les agents IA, pas des
livrables du projet. Les mettre à jour reste nécessaire même s'ils ne sont jamais poussés.

## 4. Principes de développement propres au projet

- **Aucune authentification ni TLS** : le serveur écoute sur `0.0.0.0:8080` en clair, en
  supposant un réseau local privé de confiance (voir README §2.5). Ne jamais introduire de
  fonctionnalité qui suppose implicitement une authentification existante.
- **Filtrage strict des fichiers statiques** : `ConsoleHandler.do_GET` (`mynintendotv.py`) ne sert
  qu'une liste blanche explicite (`allowed_files`) + les préfixes `/jeux/` et `/assets/`. Tout
  nouveau fichier frontend à exposer doit être ajouté explicitement à cette liste — ne jamais
  élargir le filtre à un préfixe générique.
- **Upload de fichiers** : `/api/upload` traite des requêtes multipart potentiellement volumineuses
  (ROMs jusqu'à 600 Mo) en streaming (mmap, chunks 64 Ko), jamais chargées entièrement en RAM.
  Toute modification de ce chemin doit préserver ce comportement streamé et la validation de
  chemin (`os.path.realpath(...).startswith(JEUX_DIR)`) qui empêche la traversée de répertoire.
- **Pas de secrets ni de ROMs committés** : `Jeux/`, `emu_logs/`, `launch_tmp/`, `.venv/` sont dans
  `.gitignore` — ne jamais forcer leur ajout.
- **Un seul fichier backend** : `mynintendotv.py` n'a pas de framework ni de dépendances externes
  au-delà de `watchdog`/`evdev`. Ne pas introduire un framework web sans discussion explicite avec
  l'utilisateur — c'est un choix délibéré pour un service systemd minimal sur machine dédiée.
