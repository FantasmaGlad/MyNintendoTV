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

### 4. Maintenance & Nettoyage des temporaires

Si vous souhaitez simplement effectuer une opération de maintenance (supprimer les fichiers logs accumulés, vider le cache des liens de lancements temporaires et réinitialiser l'ouverture automatique du menu de mappage des touches pour la prochaine session), exécutez la commande suivante **sans arrêter le serveur** :
```bash
python3 serveur_jeu.py --clean
```

### 5. Désinstallation complète & Purge totale

Si vous souhaitez désinstaller définitivement tout le système, y compris le service systemd, l'émulateur MelonDS (et ses données), l'intégralité du code et **votre bibliothèque de jeux**, exécutez le script de purge avec les privilèges root :
```bash
sudo ./purge.sh
```
*Note : Ce script est destructeur pour les fichiers présents dans le répertoire du projet, veillez à sauvegarder vos ROMs au préalable si nécessaire.*

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

### Synchronisation des jeux depuis votre machine locale (via rsync/SSH)

Si vos jeux sont stockés sur votre machine locale et que vous souhaitez les synchroniser sur votre serveur distant via SSH, vous pouvez utiliser l'utilitaire `rsync`.

Exécutez la commande suivante depuis le terminal de votre machine de développement :
```bash
rsync -avz --progress /chemin/absolu/local/InterfaceEmulateur/Jeux/ <UTILISATEUR>@<ADRESSE_IP_SERVEUR>:/chemin/distant/MonServeurEmu/Jeux/
```

**Exemple concret de synchronisation :**
```bash
rsync -avz --progress /home/fanta/Documents/InterfaceEmulateur/Jeux/ fanta@baamix:~/Documents/MonServeurEmu/Jeux/
```
*(Remplacez `/home/fanta/Documents/InterfaceEmulateur/Jeux/` par votre chemin local réel, et `fanta@baamix:~/Documents/MonServeurEmu/Jeux/` par l'utilisateur et l'adresse IP/nom d'hôte de votre serveur de destination).*


## Utilisation et Commandes Utiles

Le serveur web tourne sur le port `8080` (accessible sur tous les appareils de votre réseau via `http://<IP-DU-SERVEUR>:8080`).

Si vous avez besoin de gérer le service, voici les commandes classiques :
- **Voir le statut du serveur :** `systemctl --user status serveur_jeu.service`
- **Arrêter le serveur :** `systemctl --user stop serveur_jeu.service`
- **Redémarrer le serveur :** `systemctl --user restart serveur_jeu.service`
- **Voir les logs en direct :** `journalctl --user -u serveur_jeu.service -f`

## Configuration des Contrôleurs

L'émulateur MelonDS utilise la bibliothèque SDL2 pour la gestion des périphériques de saisie. Les configurations de mappage des touches et des axes de joystick sont enregistrées dans le fichier de configuration de l'émulateur.

### 1. Premier lancement et Réinitialisation
Lors du premier lancement d'un jeu, ou si vous réinitialisez manuellement le système, les actions suivantes sont exécutées automatiquement :
- **Reset des touches :** Suppression de tout fichier de configuration `melonDS.ini` antérieur pour réinitialiser les liaisons physiques et virtuelles.
- **Mappage automatisé :** L'émulateur démarre et le serveur simule automatiquement une séquence de touches via `ydotool` pour ouvrir directement le menu `Input and Hotkeys`.
- **Désactivation de input-remapper :** Pour empêcher que les pressions de boutons durant la phase de configuration ou en jeu ne déclenchent des commandes et raccourcis non sollicités sur le système hôte, l'injection de `input-remapper` est suspendue sur tous les périphériques connectés. Elle est automatiquement restaurée dès la fermeture de l'émulateur.

Pour forcer une nouvelle réinitialisation complète et rouvrir automatiquement le menu de configuration au prochain démarrage de jeu, lancez simplement la commande de maintenance :
```bash
python3 serveur_jeu.py --clean
```

### 2. Mappage manuel (hors premier lancement)
Si vous devez lancer l'interface graphique de configuration en dehors du processus automatisé :
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

Les configurations sont écrites dans `~/.var/app/net.kuribo64.melonDS/config/melonDS/melonDS.ini`. Les lancements de jeux ultérieurs chargeront automatiquement ces configurations.
