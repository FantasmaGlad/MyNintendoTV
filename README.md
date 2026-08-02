# MyNintendoTV - Console d'Emulation Autonome

Ce projet permet de transformer une machine Linux en une console d'emulation dediee et autonome. L'installation configure une session graphique minimale sans environnement de bureau, demarrant directement sur l'interface de jeu en plein ecran. La machine devient ainsi un terminal visuel dedie a l'emulation.

L'interface utilisateur est exposee via un serveur web local accessible depuis la console elle-meme et depuis n'importe quel appareil connecte au reseau local.

Pour une cartographie fichier par fichier du depot (utile pour retrouver rapidement "ou est le code qui gere X"), voir [structure.md](structure.md).

---

## Partie 1 : Partie Grand Public - Guide d'Installation et d'Utilisation

### 1.1 Pre-requis

* Une machine physique sous Debian 11+, Ubuntu 20.04+, ou derive (Mint, Pop!_OS, Zorin).
* Architecture systeme x86_64.
* Une connexion internet active pour le telechargement initial des dependances systeme.
* Un compte utilisateur standard (non-root) existant sur la machine cible.

### 1.2 Procedure d'Installation

Pour installer le systeme, executez les commandes suivantes dans un terminal :

```bash
git clone https://github.com/FantasmaGlad/MyNintendoTV.git
cd MyNintendoTV
sudo ./install.sh
```

Le script effectue automatiquement les operations suivantes :
* Installation des dependances (Python, Flatpak, Chromium, Openbox, ydotool, unclutter).
* Installation de l'emulateur MelonDS via Flatpak.
* Creation et activation du service backend en tache de fond.
* Configuration des droits d'acces aux peripheriques d'entree pour le groupe systeme.
* Deploiement de la session kiosk (Openbox avec Chromium lance en plein ecran verrouille).
* Configuration de la connexion automatique (autologin) sur le gestionnaire d'affichage.
* Ouverture du port reseau 8080 dans le pare-feu local.

A l'issue de l'installation, redemarrez la machine pour que celle-ci bascule directement sur l'interface console.

### 1.3 Comportement Post-Installation

Au demarrage de la machine :
1. La session utilisateur configuree s'ouvre automatiquement.
2. Une session graphique minimale (Openbox) est lancee avec un arriere-plan noir.
3. Le navigateur Chromium s'ouvre en mode kiosk (plein ecran strict) chargeant l'interface locale.
4. Le curseur de la souris est masque pour ameliorer l'immersion visuelle.

Si le navigateur est ferme accidentellement, il redemarre automatiquement. Il n'y a aucun acces direct a un bureau standard.

### 1.4 Importation et Gestion des Jeux

L'ajout de nouveaux jeux s'effectue desormais a distance sans intervention physique sur la console.

#### Methode d'Importation Standard (Web)
1. Ouvrez un navigateur web depuis n'importe quel ordinateur ou appareil mobile connecte au reseau local.
2. Accedez a l'interface d'administration reseau a l'adresse suivante :
   `http://<IP_DE_LA_CONSOLE>:8080/roms`
3. Importez vos jeux au format `.nds` ou `.zip` en cliquant sur le coffre central ou en y glissant vos fichiers.
4. Les fichiers `.zip` sont automatiquement decompresses dans le repertoire `/Jeux` de la console. Le rafraichissement de la liste des jeux sur l'ecran de la console s'effectue en temps reel.

#### Fonctionnalites de Maintenance Reseau
Cette meme interface web d'administration `/roms` met a disposition trois boutons de controle situes en haut a gauche de l'ecran :
* **Eteindre** : Arrete proprement la console a distance.
* **Allumer / Reveiller** : Force le reveil de l'affichage video si l'ecran de la console s'est mis en veille.
* **Redemarrer** : Execute un redemarrage propre du systeme d'emulation.

### 1.5 Configuration de la Manette

Pour configurer une nouvelle manette de jeu, vous devez temporairement connecter un clavier et une souris physiques a la console :
1. Lancez un jeu depuis l'interface visuelle.
2. Le systeme affiche la fenetre de configuration des touches de MelonDS (Config > Input and Hotkeys).
3. Cliquez sur chaque action a l'aide de la souris et appuyez sur la touche correspondante de votre manette.
4. Cliquez sur le bouton "OK" pour valider. La configuration est sauvegardee de maniere permanente pour les prochaines sessions.

### 1.6 Raccourci de Sortie de Jeu

Pour quitter un jeu en cours et retourner a la liste des titres sans clavier ni souris :
1. Maintenez enfoncees simultanement les deux gachettes superieures de votre manette (L1 et R1).
2. Appuyez deux fois rapidement sur l'un des boutons de facade (A, B, X ou Y).

L'emulateur se fermera proprement et l'affichage basculera instantanement sur le catalogue de jeux.

### 1.7 Desinstallation du Systeme

Pour supprimer l'integralite de la console d'emulation et restaurer votre machine a son etat d'origine, executez :

```bash
cd MyNintendoTV
sudo ./purge.sh
```

Cette procedure automatique supprime les services systemd, la session kiosk, les configurations d'autologin, l'emulateur MelonDS, le serveur web, ainsi que l'ensemble des jeux importes.

---

## Partie 2 : Partie Technique - Architecture et Administration

### 2.1 Architecture Generale

L'integration systeme s'appuie sur la repartition des roles suivants :

| Composant | Emplacement | Fonction |
|---|---|---|
| Service Backend | `~/.config/systemd/user/mynintendotv.service` | Gestionnaire systemd demarrant le serveur Python des le boot grace au linger user. |
| Session Kiosk | `/usr/share/xsessions/mynintendotv-kiosk.desktop` | Fichier d'entree session declare dans le gestionnaire d'affichage. |
| Script d'Initialisation | `/usr/local/bin/mynintendotv-kiosk-session` | Boucle de lancement persistant d'Openbox, de Chromium (mode kiosk) et masquage du curseur (unclutter). |
| Configuration Autostart | `~/.config/openbox/autostart` | Sequenceur de demarrage chargeant le script de session principal. |
| Autologin Systeme | `/etc/gdm3/custom.conf` (ou configuration LightDM/SDDM) | Injection des directives permettant de court-circuiter l'ecran de verrouillage systeme. |
| Droits d'Acces Materiel | `/etc/udev/rules.d/99-gamepad-evdev.rules` | Regles udev octroyant les droits de lecture/ecriture du gamepad au groupe local input. |
| Serveur d'Application | `mynintendotv.py` | Serveur HTTP asynchrone gerant le catalogue, la reception/extraction des fichiers ROMs, l'API systeme et l'ecoute active des manettes. |

### 2.2 Arborescence Detaillee du Projet

```
MyNintendoTV/
  install.sh              Script shell d'installation systeme et des dependances
  purge.sh                Script shell de desinstallation et nettoyage systeme
  mynintendotv.py          Code source backend (Python HTTP, API, Watchdog SSE et gestion evdev)
  requirements.txt        Dependances Python requises
  index.html              Interface utilisateur principale (catalogue de jeux)
  roms.html               Interface d'administration reseau (importation et maintenance)
  script.js               Comportement dynamique frontend (SSE, interactions manette)
  style.css               Fiche de styles CSS globale
  Assets/                 Dossier des ressources d'interface (images, polices)
  Jeux/                   Repertoire de stockage des titres NDS
  emu_logs/               Fichiers de journalisation des processus de l'emulateur
  launch_tmp/             Repertoire des liens d'execution temporaires
```

### 2.3 Commandes d'Administration du Service

Le cycle de vie du serveur Python est pilote par le gestionnaire d'init systemd en mode utilisateur. Les commandes d'administration courantes sont :

```bash
# Consulter l'etat du service
systemctl --user status mynintendotv.service

# Redemarrer le serveur d'application
systemctl --user restart mynintendotv.service

# Visualiser les journaux d'evenements (logs) en temps reel
journalctl --user -u mynintendotv.service -f
```

### 2.4 Diagnostic et Outils de Maintenance

Un outil de nettoyage est directement integre au backend pour purger les fichiers temporaires orphelins :
```bash
python3 mynintendotv.py --clean
```

Des points d'entree d'API (endpoints) ont ete implementes pour le diagnostic reseau :
* `GET /api/health` : Retourne un statut de connectivite basique.
* `GET /api/diag` : Renvoie un rapport complet des variables systeme, metriques d'execution et etat Flatpak.

### 2.5 Securite Reseau et Filtrage de Fichiers

Le serveur HTTP s'execute sur le port `8080` sur l'interface generique `0.0.0.0`. Aucun mecanisme de chiffrement TLS ou d'authentification n'est integre au protocole ; le systeme suppose son deploiement dans un reseau local prive et securise.

Par mesure de protection, le serveur met en oeuvre un filtrage strict sur la distribution des fichiers. Seuls les elements suivants peuvent etre consultes ou telecharges a distance :
* Les fichiers sources frontend : `index.html`, `roms.html`, `style.css`, `script.js`, `favicon.ico`.
* Le contenu des repertoires `Jeux/` (ROMs) et `Assets/` (images, polices).

Toute requete ciblant d'autres ressources (notamment les scripts d'administration `.py` ou `.sh`) est automatiquement bloquee et retourne un code HTTP 403 Forbidden.

L'endpoint `/api/upload` traite des fichiers potentiellement volumineux (ROMs jusqu'a 600 Mo) : le corps de la requete est ecrit sur disque puis parse par chunks via `mmap` plutot que d'etre charge integralement en RAM, et toute taille depassant la limite est rejetee avant lecture complete (HTTP 413). Le nom de destination d'une ROM existante est systematiquement resolu avec `os.path.realpath()` et verifie contre la racine `Jeux/` pour empecher toute traversee de repertoire.

### 2.6 Abstractions Centrales et Choix d'Architecture

Quelques decisions structurantes qui different d'un CRUD generique et meritent d'etre comprises avant de modifier le backend :

* **Un seul fichier, sans framework.** `mynintendotv.py` s'appuie uniquement sur `http.server` de la bibliotheque standard (pas de Flask/FastAPI). Choix delibere : le serveur tourne comme service systemd minimal sur une machine dediee, sans etape de build ni environnement complexe a maintenir dans le temps.
* **Hardlink "safe path" avant lancement (`_safe_rom_path`).** Les noms de ROM originaux contiennent souvent espaces, parentheses et virgules (conventions No-Intro/Redump). MelonDS via Flatpak parse mal ces caracteres dans certains contextes. Le serveur cree donc un hardlink temporaire vers un nom assaini (`rom_<hash>.ext`) dans `launch_tmp/` avant de lancer l'emulateur, sans dupliquer le fichier sur disque.
* **Reconstruction de l'environnement graphique (`_build_graphical_env`).** Le serveur tourne comme service `systemd --user` qui demarre potentiellement avant ou sans heritage direct de `DISPLAY`/`WAYLAND_DISPLAY`/`DBUS_SESSION_BUS_ADDRESS`. Avant chaque lancement d'emulateur, ces variables sont retrouvees en inspectant les processus actifs de l'utilisateur (`/proc/<pid>/environ`) puis en repli par detection de sockets X11/Wayland connus.
* **Kill Combo manette (`gamepad_kill_listener`).** La console n'a ni clavier ni souris en usage normal. Le seul moyen de fermer un jeu bloque est la manette : la combinaison L1+R1 maintenus + 2 appuis sur un bouton de facade, ecoutee directement via `evdev` (bas niveau, independant du focus fenetre de l'emulateur).
* **Reset systematique de la configuration MelonDS (`reset_melonds_config`).** Le fichier `melonDS.ini` est regenere a chaque lancement avec uniquement la langue firmware configuree (`config.json`). Ceci evite qu'un reglage modifie manuellement dans l'emulateur (resolution, chemin, etc.) ne persiste de facon incoherente entre deux sessions de jeu sur une console partagee.
* **Notifications SSE avec debounce.** `watchdog` surveille `Jeux/` et declenche un evenement `reload` cote frontend via Server-Sent Events. Un debounce de 1.5s evite qu'une extraction ZIP (plusieurs evenements fichier en rafale) ne spamme le frontend de rechargements.

### 2.7 Verification et Tests

Il n'existe pas de suite de tests automatises : le projet est un service systeme qui depend fortement de l'environnement graphique/materiel local (Flatpak, evdev, ydotool), difficile a isoler dans des tests unitaires classiques. La verification se fait via :

```bash
# Demarrage manuel en avant-plan (hors systemd), pour voir les logs en direct
python3 mynintendotv.py

# Nettoyage des fichiers de maintenance (logs, hardlinks temporaires)
python3 mynintendotv.py --clean
```

* `GET /api/health` : verification rapide que le serveur repond et que `Jeux/` est accessible.
* `GET /api/diag` : rapport complet (etat Flatpak/MelonDS, variables d'environnement graphique detectees, liste des jeux avec verification d'existence/lisibilite de chaque ROM, derniers logs d'emulateur).
* Avant tout changement touchant `/api/upload` ou `/launch/<id>`, tester manuellement un import de ROM (fichier seul, ZIP, dossier complet via `/roms`) et un lancement de jeu de bout en bout — ce sont les deux chemins les plus sensibles du projet (parsing multipart, permissions, environnement graphique).

---

## Licence

Ce projet est distribue sous licence **GNU Affero General Public License v3.0** (AGPL-3.0). Voir le fichier [LICENSE](LICENSE) pour le texte complet.
