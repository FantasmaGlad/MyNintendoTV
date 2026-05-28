# MonServeurEmu

MonServeurEmu est un serveur leger en Python permettant de servir une interface web au style lowpoly pour naviguer et lancer vos jeux retro (ROMs) directement depuis un navigateur web, sur une tele ou un serveur type Wyse5070.

## Installation

```bash
# 1. Cloner le projet
git clone https://github.com/FantasmaGlad/MonServeurEmu.git
cd MonServeurEmu

# 2. Installer
sudo ./install.sh
```

C'est tout. Le serveur est installe, configure, et demarrera automatiquement a chaque allumage de la machine.

## Guide Detaille

### Prerequis

Seul `git` est necessaire au prealable. Le script d'installation se charge du reste :
```bash
sudo apt update && sudo apt install git -y
```

### Ce que fait `install.sh`

Le script detecte automatiquement votre environnement et configure tout :

| Etape | Description |
|:---:|---|
| 1 | Detection de l'OS, de l'architecture et de la distribution |
| 2 | Installation des dependances systeme (`flatpak`, `ydotool`, `psmisc`, etc.) |
| 3 | Configuration Python — venv automatique si `python3-watchdog` est absent des repos |
| 4 | Installation de MelonDS via Flatpak |
| 5 | Configuration des permissions Flatpak (filesystem, devices, sockets X11/Wayland) |
| 6 | Activation du daemon `ydotoold` (simulation de touches) |
| 7 | Creation et activation du service `systemd --user` |
| 8 | Activation du **linger** (demarrage au boot sans connexion interactive) |
| 9 | Ouverture du port `8080` dans le firewall (UFW) si actif |
| 10 | Verification post-installation complete avec rapport |

### Acces a l'interface

Apres installation, l'interface est accessible depuis n'importe quel appareil de votre reseau :

```
http://<IP-DU-SERVEUR>:8080
```

Le script d'installation affiche l'URL exacte a la fin de l'execution.

### Compatibilite

| Environnement | Statut |
|---|:---:|
| Ubuntu 20.04+ (X11 / Wayland) | Oui |
| Ubuntu 24.04 / 26.04 LTS | Oui |
| Debian 11 (Bullseye) et + | Oui |
| Derives (Linux Mint, Pop!_OS, Zorin) | Oui |
| XFCE / X11 | Oui |
| GNOME / Wayland | Oui |
| KDE Plasma / Wayland | Oui |

## Ajout des Jeux

Les ROMs ne sont pas incluses dans le depot (limite GitHub de 100 Mo). Ajoutez vos jeux manuellement en respectant cette arborescence :

```
MonServeurEmu/
└── Jeux/
    └── NDS/
        └── Pokemon - Black Version/
            ├── Pokemon - Black Version.nds
            └── cover.png              (optionnel, pochette)
```

L'application detecte automatiquement les nouveaux ajouts en temps reel grace a un watchdog integre. Il n'y a rien d'autre a faire.

### Synchronisation distante (rsync/SSH)

Pour synchroniser vos ROMs telechargees vers le serveur :

```bash
rsync -avz --progress ~/Telechargements/Jeux/ <USER>@<IP_SERVEUR>:/chemin/distant/MonServeurEmu/Jeux/
```

**Exemple :**
```bash
rsync -avz --progress ~/Telechargements/Jeux/ fanta@192.168.1.78:~/Documents/MonServeurEmu/Jeux/
```

## Commandes Utiles

### Gestion du service

| Action | Commande |
|---|---|
| Voir le statut | `systemctl --user status serveur_jeu.service` |
| Redemarrer | `systemctl --user restart serveur_jeu.service` |
| Arreter | `systemctl --user stop serveur_jeu.service` |
| Logs en direct | `journalctl --user -u serveur_jeu.service -f` |

### Maintenance

Nettoyer les logs, le cache des liens temporaires, et reinitialiser la configuration de l'emulateur pour le prochain lancement :

```bash
python3 serveur_jeu.py --clean
```

### Diagnostic

Le serveur expose un endpoint de diagnostic accessible depuis le navigateur :

```
http://<IP-DU-SERVEUR>:8080/api/diag
```

Il retourne l'etat complet du systeme : variables d'environnement graphique, etat de Flatpak/MelonDS, ROMs detectees, derniers logs de l'emulateur, etc.

Un endpoint de health check leger est egalement disponible :

```
http://<IP-DU-SERVEUR>:8080/api/health
```

### Desinstallation complete

Pour tout supprimer (service, emulateur, venv Python, code source **et ROMs**) :

```bash
sudo ./purge.sh
```

> **Ce script est destructeur.** Sauvegardez vos ROMs au prealable si necessaire.

## Configuration des Controleurs

L'emulateur MelonDS utilise SDL2 pour la gestion des manettes. Le mappage des touches est automatiquement gere.

### Lancement de jeu

A CHAQUE lancement d'un jeu, le systeme effectue automatiquement :
1. **Reset de la configuration** — Suppression de tout `melonDS.ini` anterieur.
2. **Ouverture du menu de mappage** — Simulation de touches via `ydotool` pour ouvrir `Config > Input and Hotkeys`.
3. **Suspension de input-remapper** — Suspension temporaire du service de remappage. Restauration automatique a la fermeture de l'emulateur.

### Prerequis materiels pour le mappage

L'interface de l'emulateur MelonDS ne permet pas la navigation dans ses menus via un controleur de jeu standard. Bien que l'ouverture de la fenetre de configuration soit automatisee, l'assignation individuelle des touches requiert une interaction directe avec l'interface graphique.

Par consequent, l'utilisation d'une souris physique et d'un clavier connectes a la machine hote est strictement requise lors du processus d'assignation des entrees du controleur.

### Quitter un jeu (Kill Combo)

Pour fermer l'emulateur depuis votre canape et revenir au menu web, utilisez la combinaison d'urgence sur votre manette :
- Maintenez **L1** et **R1** enfonces (les deux boutons de tranche superieurs).
- Tout en les maintenant, **appuyez 2 fois** sur n'importe quel bouton d'action de droite (A, B, X ou Y).

L'emulateur se fermera instantanement.

### Mappage manuel

Pour configurer la manette en dehors du processus automatise :

1. Connectez la manette a la machine hote.
2. Lancez MelonDS :
   ```bash
   # Session locale :
   flatpak run net.kuribo64.melonDS

   # Via SSH (affichage sur l'ecran physique) :
   DISPLAY=:0 XAUTHORITY=~/.Xauthority flatpak run net.kuribo64.melonDS
   ```
3. Allez dans `Config` > `Input and Hotkeys`.
4. Selectionnez le joystick detecte et associez les boutons.
5. Validez avec `OK`.

Les configurations sont sauvegardees dans :
```
~/.var/app/net.kuribo64.melonDS/config/melonDS/melonDS.ini
```

## Structure du Projet

```
MonServeurEmu/
├── install.sh              Script d'installation universel
├── purge.sh                Desinstallation et purge totale
├── serveur_jeu.py          Serveur Python (backend + API)
├── requirements.txt        Dependances Python (fallback venv)
├── index.html              Interface web (frontend)
├── script.js               Logique frontend (carousel, gamepad, SSE)
├── style.css               Styles de l'interface
├── Assets/
│   ├── Images/             Ressources graphiques (fonds, textures)
│   └── Videos/
├── Jeux/                   Vos ROMs (cree automatiquement)
│   └── NDS/
├── emu_logs/               Logs de l'emulateur (runtime)
└── launch_tmp/             Liens temporaires de lancement (runtime)
```
