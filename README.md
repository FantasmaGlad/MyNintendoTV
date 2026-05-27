# MonServeurEmu

MonServeurEmu est un serveur léger en Python permettant de servir une interface web au style lowpoly pour naviguer et lancer vos jeux rétro (ROMs) directement depuis un navigateur web, sur une télé ou un serveur type Wyse5070.

## Installation & Démarrage Automatique

Le projet inclut un script d'installation automatisé qui va créer un service systemd pour vous. Ainsi, le serveur démarrera automatiquement en arrière-plan à chaque allumage de votre machine.

### 1. Prérequis

Assurez-vous que Python 3 est installé sur votre système (Debian/Ubuntu) :
```bash
sudo apt update
sudo apt install python3 git -y
```

### 2. Téléchargement

Clonez le dépôt où vous souhaitez l'installer (par exemple dans votre dossier utilisateur) :
```bash
git clone https://github.com/FantasmaGlad/MonServeurEmu.git
cd MonServeurEmu
```

### 3. Installation Automatisée

Lancez le script avec l'argument `--install` avec les droits administrateur (`sudo`). 
Le script détectera automatiquement le chemin de votre dossier ainsi que votre nom d'utilisateur, puis créera et activera le service système pour vous :

```bash
sudo python3 serveur_jeu.py --install
```

Votre serveur est maintenant installé, configuré et en cours de fonctionnement. Il se relancera tout seul à chaque redémarrage de votre serveur Debian.

## Ajout des Jeux

Pour des raisons de limites de taille de fichier sur GitHub (100 Mo), les gros fichiers ROM ne sont pas inclus. Vous devez ajouter vos jeux manuellement sur votre serveur.

1. Allez dans le répertoire du projet téléchargé.
2. Assurez-vous que le dossier `Jeux/` existe (le script le crée automatiquement s'il manque).
3. Placez-y vos dossiers de jeux, respectant la structure :
   ```
   MonServeurEmu/
   └── Jeux/
       └── NDS/
           └── Pokemon - Black Version/
               ├── Pokemon - Black Version.nds
               └── cover.png
   ```

*(L'application détecte automatiquement les nouveaux ajouts grâce à un système de watchdog intégré).*


## Utilisation et Commandes Utiles

Le serveur web tourne sur le port `8080` (accessible sur tous les appareils de votre réseau via `http://<IP-DU-SERVEUR>:8080`).

Si vous avez besoin de gérer le service, voici les commandes classiques :
- **Voir le statut du serveur :** `systemctl --user status serveur_jeu.service`
- **Arrêter le serveur :** `systemctl --user stop serveur_jeu.service`
- **Redémarrer le serveur :** `systemctl --user restart serveur_jeu.service`
- **Voir les logs en direct :** `journalctl --user -u serveur_jeu.service -f`

## Configuration des Contrôleurs

L'émulateur MelonDS utilise la bibliothèque SDL2 pour la gestion des périphériques de saisie. Les configurations de mappage des touches et des axes de joystick sont enregistrées dans le fichier de configuration de l'émulateur.

Pour configurer une manette de jeu :
1. Connectez le contrôleur physique à l'hôte hébergeant le serveur.
2. Lancez l'interface graphique de MelonDS. Si vous êtes connecté à distance via SSH, vous devez forcer l'affichage sur l'écran physique du serveur :
   ```bash
   # Depuis la session graphique locale :
   flatpak run net.kuribo64.melonDS

   # Depuis une session SSH (affichage sur l'écran physique / TV) :
   DISPLAY=:0 XAUTHORITY=~/.Xauthority flatpak run net.kuribo64.melonDS
   ```
3. Accédez au menu `Config` > `Input and Hotkeys`.
4. Sélectionnez le périphérique détecté dans le menu déroulant `Joystick` en bas de l'interface.
5. Associez chaque touche virtuelle aux boutons et axes physiques de la manette.
6. Validez par `OK` pour enregistrer les paramètres.

Les configurations sont écrites dans `~/.var/app/net.kuribo64.melonDS/config/melonDS/melonDS.ini`. Les démarrages ultérieurs de jeux via l'interface web chargeront automatiquement ces paramètres de mappage sans configuration additionnelle.
