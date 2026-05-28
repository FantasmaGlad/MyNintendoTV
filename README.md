# Serveur d'Emulation Autonome (Kiosk Mode)

Ce projet fournit une solution logicielle complete permettant de transformer un systeme Linux vierge (comme un client leger Wyse 5070 sous Debian/Ubuntu) en une console d'emulation autonome. L'interface est exposee via un serveur web local, et le systeme demarre automatiquement en plein ecran (Kiosk Mode) a chaque allumage.

---

## 1. Guide Utilisateur Standard

Cette section decrit le processus complet pour transformer une machine vierge en console de jeu, ajouter des jeux, configurer la manette et desinstaller le systeme si necessaire.

### 1.1 Installation

Un seul script est necessaire pour configurer le systeme de A a Z.

1. Ouvrez un terminal sur la machine cible.
2. Telechargez le projet :
   ```bash
   git clone https://github.com/FantasmaGlad/MonServeurEmu.git
   cd MonServeurEmu
   ```
3. Lancez l'installation avec les privileges administrateur :
   ```bash
   sudo ./install.sh
   ```

A la fin de l'installation, le systeme est pret. Au prochain redemarrage, la machine se lancera automatiquement sur l'interface de la console en plein ecran.

### 1.2 Ajout de Jeux (ROMs)

Les jeux doivent etre transferes manuellement dans le dossier dedie du projet. Le serveur detecte instantanement les ajouts.

Structure attendue :
```text
MonServeurEmu/
└── Jeux/
    └── NDS/
        └── Nom_Du_Jeu/
            ├── fichier_rom.nds
            └── cover.png (Pochette optionnelle)
```

**Transfert depuis une autre machine (via reseau local) :**
```bash
rsync -avz --progress ~/Telechargements/Jeux/ <UTILISATEUR>@<IP_SERVEUR>:~/chemin/vers/MonServeurEmu/Jeux/
```

### 1.3 Configuration de la Manette

**Note importante :** L'assignation des touches dans l'emulateur requiert obligatoirement une souris et un clavier physiques connectes a la console.

1. Lancez un jeu depuis l'interface web.
2. Le systeme purge l'ancienne configuration et ouvre automatiquement la fenetre de mappage `Config > Input and Hotkeys`. La souris est deplacee en haut a gauche de l'ecran pour la cacher.
3. Utilisez la souris pour cliquer sur chaque champ d'action et appuyez sur le bouton correspondant de votre manette.
4. Cliquez sur `OK` pour sauvegarder et commencer a jouer.

### 1.4 Quitter un jeu (Combinaison d'Urgence)

Pour revenir a l'interface web depuis la manette :
1. Maintenez les boutons de tranche superieurs (`L1` et `R1`) enfonces.
2. Tout en les maintenant, appuyez deux fois rapidement sur n'importe quel bouton de facade droit (`A`, `B`, `X` ou `Y`).

L'emulateur se ferme immediatement et le controle est redonne a l'interface web.

### 1.5 Desinstallation Complete

Pour supprimer definitivement le serveur, ses dependances, l'interface Kiosk et l'integralite des jeux stockes :

```bash
cd MonServeurEmu
sudo ./purge.sh
```
Attention : cette operation est destructive et irreversible. Sauvegardez vos jeux au prealable.

---

## 2. Guide Technique & Avance

Cette section documente le fonctionnement interne, les commandes de maintenance et l'architecture systeme.

### 2.1 Architecture Systeme

Le script `install.sh` deploie et orchestre l'architecture suivante :
* **Systemd User Service** (`serveur_jeu.service`) : Gestionnaire du cycle de vie du backend Python. Demarre automatiquement au boot via l'activation du mode `linger` via `loginctl`.
* **Mode Kiosk** (`~/.config/autostart/emu-kiosk.desktop`) : Entree d'autostart XDG declenchant le navigateur Chromium en mode `--kiosk` pointant sur l'URL du serveur local.
* **Serveur Python (Backend)** : Gestionnaire HTTPRequestHandler sur le port `8080`. Utilise la librairie `watchdog` pour l'observation asynchrone du file system et declenche la mise a jour de l'UI via SSE (Server-Sent Events).
* **Mappage des Entrees (evdev / udev / ydotool)** : Remplacement des regles `udev` (pour un acces en lecture de `/dev/input/event*` non privilegie) permettant l'interception du signal de terminaison (Kill Combo). `ydotoold` est sollicite via bash pour generer des evenements d'UI (ouverture automatisee du sous-menu de mapping SDL).
* **Gestionnaire d'etat local** : Suspension temporaire asynchrone des profils `input-remapper` durant l'execution d'une tache binaire (Flatpak).

### 2.2 Arborescence

```text
MonServeurEmu/
├── install.sh              Script d'installation et de resolution de dependances
├── purge.sh                Desinstallation destructive totale (purge binaire et data)
├── serveur_jeu.py          Serveur backend & ecouteur de signaux materiels (evdev)
├── requirements.txt        Dependencies Python de fallback (environnement virtuel)
├── index.html              DOM UI principal
├── script.js               Logique d'interaction et parsing SSE
├── style.css               Moteur CSS
├── Assets/                 Ressources statiques pre-compilees
├── Jeux/                   Volume d'hote hebergeant les fichiers ROMs
├── emu_logs/               Fichiers logs de sortie de processus enfant (stdout/stderr)
└── launch_tmp/             Gestion des symlinks volatiles
```

### 2.3 Commandes de Service

Pour administrer le deamon systemd utilisateur :

```bash
# Verifier l'etat du processus
systemctl --user status serveur_jeu.service

# Redemarrer le backend serveur
systemctl --user restart serveur_jeu.service

# Inspecter la sortie standard et d'erreur (tail follow)
journalctl --user -u serveur_jeu.service -f
```

### 2.4 Maintenance et Diagnostic

Pour executer la procedure de ramassage-miettes (garbage collection locale) sur les dossiers de configuration ephemeres et purger les verrous applicatifs :
```bash
python3 serveur_jeu.py --clean
```

**Endpoints API internes :**
* `GET /api/health` : Sonde de verification de reponse et de viabilite applicative.
* `GET /api/diag` : Generation asynchrone d'un rapport de metriques et variables d'environnement (`DISPLAY`, `XAUTHORITY`), etat du module Flatpak, et analyse post-mortem.

### 2.5 Configuration Reseau et Pare-feu

L'application ecoute sans TLS sur `0.0.0.0:8080`.
Si les utilitaires `ufw` ou `firewalld` sont presents et actifs, l'installateur declare automatiquement une regle acceptant le trafic entrant tcp. L'authentification par session (ACL/Token) n'est pas supportee ; ce systeme presuppose un deploiment en reseau LAN de confiance.

### 2.6 Appel Externe de Configuration SDL

Afin d'invoquer la configuration des inputs manette hors du thread principal du serveur :

```bash
DISPLAY=:0 XAUTHORITY=~/.Xauthority flatpak run net.kuribo64.melonDS
```
La serialisation du mapping genere par l'interface SDL s'effectue dynamiquement dans :
`~/.var/app/net.kuribo64.melonDS/config/melonDS/melonDS.ini`
