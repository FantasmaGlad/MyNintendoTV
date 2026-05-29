# MonServeurEmu -- Console d'Emulation Autonome

Ce projet transforme une machine Linux vierge en console d'emulation dediee. L'installation configure automatiquement une session graphique minimale (sans bureau) qui demarre directement sur l'interface de jeu en plein ecran. La machine devient un terminal visuel dedie a l'emulation ; aucun environnement de bureau n'est charge.

L'interface est exposee via un serveur web local accessible depuis la machine elle-meme et depuis tout appareil connecte au reseau local.

---

## 1. Guide Utilisateur

### 1.1 Pre-requis

- Une machine physique sous Debian 11+, Ubuntu 20.04+, ou derive (Mint, Pop!_OS, Zorin).
- Architecture x86_64.
- Une connexion internet active (pour le telechargement des dependances).
- Un compte utilisateur non-root existant sur la machine.

### 1.2 Installation

```bash
git clone https://github.com/FantasmaGlad/MonServeurEmu.git
cd MonServeurEmu
sudo ./install.sh
```

Le script effectue les operations suivantes de maniere autonome :
- Installation des dependances systeme (Python, Flatpak, Chromium, openbox, ydotool, unclutter).
- Installation de l'emulateur MelonDS via Flatpak.
- Creation et activation du service backend (systemd user, linger).
- Configuration des permissions d'acces aux peripheriques d'entree (udev, groupe input).
- Deploiement d'une session kiosk dediee (openbox + Chromium plein ecran).
- Configuration de l'autologin automatique sur cette session (GDM3, LightDM ou SDDM).
- Ouverture du port 8080 dans le pare-feu local (ufw/firewalld) si actif.

Au redemarrage suivant, la machine s'allume directement sur l'interface de jeu. Aucun bureau, aucune barre des taches, aucun ecran de connexion n'est affiche.

### 1.3 Comportement Post-Installation

La machine devient une console visuelle dediee. Au demarrage :
1. Le systeme demarre et connecte automatiquement l'utilisateur configure.
2. Une session graphique minimale (openbox) se lance sur fond noir.
3. Le navigateur Chromium s'ouvre en mode kiosk (plein ecran verrouille) sur l'interface du serveur local.
4. Le curseur de la souris est masque.

Il n'y a pas de bureau classique en arriere-plan. Si Chromium est ferme (manuellement ou par crash), il redemarre automatiquement.

Pour acceder a un bureau standard (maintenance, configuration), il faut se connecter en SSH ou selectionner manuellement une autre session depuis l'ecran de connexion apres avoir desactive l'autologin.

### 1.4 Ajout de Jeux (ROMs)

Les jeux doivent etre places dans le dossier dedie. Le serveur detecte les ajouts en temps reel.

Structure attendue :
```
MonServeurEmu/
  Jeux/
    NDS/
      Nom_Du_Jeu/
        fichier_rom.nds
        cover.png       (jaquette, optionnelle)
```

Transfert depuis une autre machine du reseau local :
```bash
rsync -avz --progress ~/Telechargements/Jeux/ <UTILISATEUR>@<IP_SERVEUR>:~/chemin/vers/MonServeurEmu/Jeux/
```

### 1.5 Configuration de la Manette

L'assignation des touches dans l'emulateur necessite une souris et un clavier physiques connectes a la console.

Procedure :
1. Lancer un jeu depuis l'interface web.
2. Le systeme purge l'ancienne configuration et ouvre automatiquement la fenetre de mappage (Config > Input and Hotkeys). La souris est masquee.
3. Utiliser la souris pour cliquer sur chaque champ d'action et appuyer sur le bouton correspondant de la manette.
4. Valider avec OK. La configuration est sauvegardee pour les sessions suivantes.

### 1.6 Quitter un Jeu (Combinaison Manette)

Pour revenir a l'interface web depuis la manette, sans clavier ni souris :
1. Maintenir les gachettes superieures (L1 et R1) enfoncees.
2. Tout en les maintenant, appuyer deux fois rapidement sur un bouton de facade (A, B, X ou Y).

L'emulateur se ferme et le controle est rendu a l'interface.

### 1.7 Desinstallation Complete

```bash
cd MonServeurEmu
sudo ./purge.sh
```

Le script supprime :
- Le service systemd et le linger.
- La session kiosk (fichier de session, openbox, script de demarrage).
- La configuration d'autologin du gestionnaire d'affichage (restauration de la sauvegarde).
- L'emulateur MelonDS et ses donnees Flatpak.
- Les regles udev personnalisees.
- Chromium, openbox et unclutter.
- L'integralite du dossier du projet (code source et ROMs).

La machine revient a son etat initial. Au redemarrage suivant, l'ecran de connexion ou le bureau par defaut s'affiche normalement.

Cette operation est destructive et irreversible. Sauvegarder les ROMs au prealable.

---

## 2. Documentation Technique

### 2.1 Architecture Systeme

Le script `install.sh` deploie l'architecture suivante :

| Composant | Fichier | Role |
|---|---|---|
| Service backend | `~/.config/systemd/user/serveur_jeu.service` | Cycle de vie du serveur Python. Demarre au boot via linger. |
| Session kiosk | `/usr/share/xsessions/emu-kiosk.desktop` | Session X enregistree dans le gestionnaire de connexion. |
| Script de session | `/usr/local/bin/emu-kiosk-session` | Lance openbox + Chromium en boucle, masque le curseur, desactive DPMS. |
| Openbox autostart | `~/.config/openbox/autostart` | Point d'entree de la session, demarre le script kiosk. |
| Autologin | `/etc/gdm3/custom.conf` ou `/etc/lightdm/lightdm.conf` ou `/etc/sddm.conf.d/emu-kiosk.conf` | Connexion automatique sur la session kiosk. |
| AccountsService | `/var/lib/AccountsService/users/<user>` | Force la session par defaut pour l'utilisateur. |
| Backend Python | `serveur_jeu.py` | HTTPRequestHandler sur port 8080 avec watchdog (SSE) et evdev (gamepad). |
| Regles udev | `/etc/udev/rules.d/99-gamepad-evdev.rules` | Acces aux peripheriques d'entree pour le groupe input (MODE 0660). |

### 2.2 Arborescence

```
MonServeurEmu/
  install.sh              Installation et resolution de dependances
  purge.sh                Desinstallation destructive totale
  serveur_jeu.py          Backend serveur et ecouteur de signaux materiels (evdev)
  requirements.txt        Dependances Python de fallback (venv)
  index.html              Interface principale
  script.js               Logique d'interaction et parsing SSE
  style.css               Feuille de styles
  Assets/                 Ressources statiques (images, polices)
  Jeux/                   Volume hebergeant les ROMs
  emu_logs/               Logs de sortie des processus enfant
  launch_tmp/             Liens temporaires vers les ROMs actives
```

### 2.3 Commandes de Service

```bash
# Statut du service backend
systemctl --user status serveur_jeu.service

# Redemarrage du backend
systemctl --user restart serveur_jeu.service

# Logs en temps reel
journalctl --user -u serveur_jeu.service -f
```

### 2.4 Maintenance et Diagnostic

Procedure de nettoyage des fichiers temporaires et verrous :
```bash
python3 serveur_jeu.py --clean
```

Endpoints API internes :
- `GET /api/health` : Sonde de verification de reponse.
- `GET /api/diag` : Rapport de metriques, variables d'environnement et etat Flatpak.

### 2.5 Acces Reseau

Le serveur ecoute sur `0.0.0.0:8080` sans chiffrement TLS. L'installateur declare automatiquement une regle pare-feu si ufw ou firewalld est actif. Aucune authentification n'est implementee ; le deploiement presuppose un reseau local de confiance.

Depuis un autre appareil du reseau :
```
http://<IP_DE_LA_MACHINE>:8080
```

### 2.6 Acces Maintenance (SSH)

La machine etant dediee a l'emulation, l'administration se fait par SSH :
```bash
ssh <UTILISATEUR>@<IP_DE_LA_MACHINE>
```

Pour desactiver temporairement la session kiosk et revenir a un bureau standard :
```bash
# Supprimer l'autologin (GDM3)
sudo sed -i 's/AutomaticLoginEnable=True/AutomaticLoginEnable=False/' /etc/gdm3/custom.conf

# Redemarrer le gestionnaire d'affichage
sudo systemctl restart gdm3
```

### 2.7 Securite des Fichiers Statiques

Le serveur HTTP ne distribue que les fichiers suivants sur le reseau local :
- `index.html`, `style.css`, `script.js`, `favicon.ico`
- Contenu des dossiers `Jeux/` et `Assets/`

Tout autre fichier (scripts Python, scripts shell, fichiers git) retourne une erreur HTTP 403. Le code source du backend n'est pas accessible depuis le reseau.
