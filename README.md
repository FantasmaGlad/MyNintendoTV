# MonServeurEmu

MonServeurEmu est un service HTTP léger écrit en Python, conçu pour héberger et servir une interface web de gestion et d'exécution de fichiers ROMs. Ce document détaille les procédures d'installation automatisée, de gestion du service système, et l'arborescence requise.

## Installation et configuration initiale

L'application intègre un module d'auto-déploiement. Lors de son exécution avec les privilèges appropriés, le script installe les dépendances requises (`watchdog`), génère l'unité systemd correspondante et active le service au démarrage.

### 1. Prérequis système

L'environnement nécessite Python 3 et le système de gestion de paquets standard (apt).

```bash
sudo apt update
sudo apt install python3 git -y
```

### 2. Déploiement du dépôt

Cloner le dépôt dans le répertoire cible (ex. `/home/utilisateur/MonServeurEmu`) :

```bash
git clone https://github.com/FantasmaGlad/MonServeurEmu.git
cd MonServeurEmu
```

### 3. Exécution de la procédure d'installation

Lancer le script d'initialisation avec les privilèges superutilisateur. Le script se chargera de :
- Vérifier et installer la dépendance `python3-watchdog`.
- Détecter le répertoire d'exécution et l'utilisateur courant.
- Déployer l'unité `/etc/systemd/system/serveur_jeu.service`.
- Activer et démarrer le service en tâche de fond.

```bash
sudo python3 serveur_jeu.py --install
```

Une fois cette commande exécutée, le serveur est opérationnel et persistant.

---

## Arborescence et gestion des fichiers ROMs

En raison des limitations de quota sur GitHub (limite stricte à 100 Mo par fichier), les binaires ROMs ne sont pas versionnés. L'utilisateur doit les importer manuellement sur l'hôte cible.

1. Accéder au répertoire d'installation.
2. Créer ou utiliser le répertoire `Jeux/`.
3. Organiser les fichiers selon l'architecture stricte suivante :

```text
MonServeurEmu/
└── Jeux/
    └── NDS/
        └── Titre du Jeu/
            ├── Fichier_du_jeu.nds
            └── cover.png
```

Le service dispose d'un processus `watchdog` actif : toute modification (ajout, suppression) dans le répertoire `Jeux/` est automatiquement synchronisée avec les clients web connectés via Server-Sent Events (SSE).

---

## Gestion du service (systemd)

Le serveur écoute par défaut sur toutes les interfaces réseau (`0.0.0.0`) via le port `8080`.

Commandes d'administration courantes pour contrôler l'état du service :

- Obtenir l'état actuel du processus :
  `sudo systemctl status serveur_jeu.service`
- Suspendre le service :
  `sudo systemctl stop serveur_jeu.service`
- Relancer le service :
  `sudo systemctl restart serveur_jeu.service`
- Consulter le flux de journaux (logs) en temps réel :
  `sudo journalctl -u serveur_jeu.service -f`
