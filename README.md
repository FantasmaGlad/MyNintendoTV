# MonServeurEmu

MonServeurEmu est un serveur léger en Python permettant de servir une interface web au style lowpoly pour naviguer et lancer vos jeux rétro (ROMs) directement depuis un navigateur web, sur une télé ou un serveur type Wyse5070.

## Installation Rapide

```bash
# 1. Cloner le projet
git clone https://github.com/FantasmaGlad/MonServeurEmu.git
cd MonServeurEmu

# 2. Installer (une seule commande)
sudo ./install.sh
```

C'est tout. Le serveur est installé, configuré, et démarrera automatiquement à chaque allumage de la machine.

## Guide Détaillé

### Prérequis

Seul `git` est nécessaire au préalable. Le script d'installation se charge du reste :
```bash
sudo apt update && sudo apt install git -y
```

### Ce que fait `install.sh`

Le script détecte automatiquement votre environnement et configure tout :

| Étape | Description |
|:---:|---|
| 1 | 🔍 Détection de l'OS, de l'architecture et de la distribution |
| 2 | 📦 Installation des dépendances système (`flatpak`, `ydotool`, `psmisc`, etc.) |
| 3 | 🐍 Configuration Python — venv automatique si `python3-watchdog` est absent des repos |
| 4 | 🎮 Installation de MelonDS via Flatpak |
| 5 | 🔐 Configuration des permissions Flatpak (filesystem, devices, sockets X11/Wayland) |
| 6 | ⌨️ Activation du daemon `ydotoold` (simulation de touches) |
| 7 | ⚙️ Création et activation du service `systemd --user` |
| 8 | 🔁 Activation du **linger** (démarrage au boot sans connexion interactive) |
| 9 | 🔥 Ouverture du port `8080` dans le firewall (UFW) si actif |
| 10 | ✅ Vérification post-installation complète avec rapport |

> **Rétrocompatibilité** : la commande `sudo python3 serveur_jeu.py --install` fonctionne toujours et délègue automatiquement à `install.sh`.

### Accès à l'interface

Après installation, l'interface est accessible depuis n'importe quel appareil de votre réseau :

```
http://<IP-DU-SERVEUR>:8080
```

Le script d'installation affiche l'URL exacte à la fin de l'exécution.

### Compatibilité

| Environnement | Statut |
|---|:---:|
| Ubuntu 20.04+ (X11 / Wayland) | ✅ |
| Ubuntu 24.04 / 26.04 LTS | ✅ |
| Debian 11 (Bullseye) et + | ✅ |
| Dérivés (Linux Mint, Pop!_OS, Zorin) | ✅ |
| XFCE / X11 | ✅ |
| GNOME / Wayland | ✅ |
| KDE Plasma / Wayland | ✅ |

## Ajout des Jeux

Les ROMs ne sont pas incluses dans le dépôt (limite GitHub de 100 Mo). Ajoutez vos jeux manuellement en respectant cette arborescence :

```
MonServeurEmu/
└── Jeux/
    └── NDS/
        └── Pokemon - Black Version/
            ├── Pokemon - Black Version.nds
            └── cover.png              ← optionnel (pochette)
```

L'application détecte automatiquement les nouveaux ajouts en temps réel grâce à un watchdog intégré. Il n'y a rien d'autre à faire.

### Import via l'interface web

Vous pouvez importer des fichiers `.zip` ou `.nds` directement depuis le menu **Paramètres** de l'interface web. Les archives ZIP sont automatiquement extraites dans le bon dossier.

### Synchronisation distante (rsync/SSH)

Pour synchroniser vos ROMs depuis votre machine de développement vers le serveur :

```bash
rsync -avz --progress ./Jeux/ <USER>@<IP_SERVEUR>:~/MonServeurEmu/Jeux/
```

**Exemple :**
```bash
rsync -avz --progress ./Jeux/ fanta@192.168.1.78:~/Documents/MonServeurEmu/Jeux/
```

## Commandes Utiles

### Gestion du service

| Action | Commande |
|---|---|
| Voir le statut | `systemctl --user status serveur_jeu.service` |
| Redémarrer | `systemctl --user restart serveur_jeu.service` |
| Arrêter | `systemctl --user stop serveur_jeu.service` |
| Logs en direct | `journalctl --user -u serveur_jeu.service -f` |

### Maintenance

Nettoyer les logs, le cache des liens temporaires, et réinitialiser la configuration de l'émulateur pour le prochain lancement :

```bash
python3 serveur_jeu.py --clean
```

### Diagnostic

Le serveur expose un endpoint de diagnostic accessible depuis le navigateur :

```
http://<IP-DU-SERVEUR>:8080/api/diag
```

Il retourne l'état complet du système : variables d'environnement graphique, état de Flatpak/MelonDS, ROMs détectées, derniers logs de l'émulateur, etc.

Un endpoint de health check léger est également disponible :

```
http://<IP-DU-SERVEUR>:8080/api/health
```

### Désinstallation complète

Pour tout supprimer (service, émulateur, venv Python, code source **et ROMs**) :

```bash
sudo ./purge.sh
```

> ⚠️ **Ce script est destructeur.** Sauvegardez vos ROMs au préalable si nécessaire.

## Configuration des Contrôleurs

L'émulateur MelonDS utilise SDL2 pour la gestion des manettes. Le mappage des touches est automatiquement géré au premier lancement.

### Premier lancement

Lors du premier lancement d'un jeu, le système effectue automatiquement :
1. **Reset de la configuration** — Suppression de tout `melonDS.ini` antérieur.
2. **Ouverture du menu de mappage** — Simulation de touches via `ydotool` pour ouvrir `Config > Input and Hotkeys`.
3. **Suspension de input-remapper** — Évite les entrées parasites pendant la configuration. Restauration automatique à la fermeture de l'émulateur.

Pour forcer une nouvelle réinitialisation :
```bash
python3 serveur_jeu.py --clean
```

### Mappage manuel

Pour configurer la manette en dehors du processus automatisé :

1. Connectez la manette à la machine hôte.
2. Lancez MelonDS :
   ```bash
   # Session locale :
   flatpak run net.kuribo64.melonDS

   # Via SSH (affichage sur l'écran physique) :
   DISPLAY=:0 XAUTHORITY=~/.Xauthority flatpak run net.kuribo64.melonDS
   ```
3. Allez dans `Config` > `Input and Hotkeys`.
4. Sélectionnez le joystick détecté et associez les boutons.
5. Validez avec `OK`.

Les configurations sont sauvegardées dans :
```
~/.var/app/net.kuribo64.melonDS/config/melonDS/melonDS.ini
```

## Structure du Projet

```
MonServeurEmu/
├── install.sh              ← Script d'installation universel
├── purge.sh                ← Désinstallation et purge totale
├── serveur_jeu.py          ← Serveur Python (backend + API)
├── requirements.txt        ← Dépendances Python (fallback venv)
├── index.html              ← Interface web (frontend)
├── script.js               ← Logique frontend (carousel, gamepad, SSE)
├── style.css               ← Styles de l'interface
├── Assets/
│   ├── Images/             ← Ressources graphiques (fonds, textures)
│   └── Videos/
├── Jeux/                   ← Vos ROMs (créé automatiquement)
│   └── NDS/
├── emu_logs/               ← Logs de l'émulateur (runtime)
└── launch_tmp/             ← Liens temporaires de lancement (runtime)
```
