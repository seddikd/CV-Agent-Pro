# Guide d'installation — CV Agent Pro (Windows 10 / 11)

Ce support contient **tout le nécessaire** pour installer CV Agent Pro sur un
poste Windows 10 ou 11, **sans connexion Internet** : l'application, un
installateur automatique et les prérequis (PostgreSQL, Ollama en option). Les
manuels sont dans le dossier `Manuels\`.

---

## 1. Contenu du support

```
iso\
├─ LISEZ-MOI.txt                     Démarrage rapide
├─ GUIDE_INSTALLATION.md / .pdf      Ce guide (toutes les étapes)
├─ Installer.ps1                     Installateur automatique tout-en-un
├─ Application\
│   ├─ CV-Agent\                     L'application (CV-Agent.exe + dépendances)
│   └─ CV-Agent-Setup.exe            Installateur graphique de l'application seule
├─ Prerequis\
│   ├─ postgresql-17.10-1-windows-x64.exe   PostgreSQL 17 (installation hors ligne)
│   ├─ OllamaSetup.exe               Ollama — moteur IA local, optionnel (hors ligne)
│   └─ Installer-PostgreSQL.ps1      Installation PostgreSQL autonome (secours)
├─ Config\                           (réservé)
└─ Manuels\
    ├─ Manuel_Utilisateur\           Manuel RH (PDF + Markdown)
    └─ Manuel_Deploiement\           Manuel informaticien (PDF + Markdown)
```

## 2. Prérequis de la machine

| Élément | Détail |
|---|---|
| Système | Windows 10 ou 11, 64 bits |
| Droits | Administrateur (l'installateur en a besoin) |
| Internet | **Non requis** : les installeurs des prérequis sont fournis dans `Prerequis\`. (Si ce dossier était vidé, l'installateur se rabat sur winget, qui télécharge.) |
| winget | « App Installer » — utile **seulement en repli** si `Prerequis\` est vide |
| Boîte mail | **Tout serveur IMAP** (Gmail, Outlook/Office 365, OVH, Zoho, interne…). Selon le fournisseur, un **mot de passe d'application** peut être requis. |

> **PostgreSQL est requis** : l'installateur l'installe automatiquement depuis le
> support. Il n'y a plus de base fichier (SQLite) — toutes les données vivent
> dans PostgreSQL.

## 3. Installation automatique (recommandée)

1. **Clic droit** sur `Installer.ps1` → **Exécuter avec PowerShell** (accepter
   l'élévation administrateur).
   Ou en invite PowerShell **administrateur**, dans ce dossier :
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\Installer.ps1
   # avec le moteur IA local Ollama (gratuit) :
   powershell -ExecutionPolicy Bypass -File .\Installer.ps1 -InstallOllama
   # dossier d'installation personnalisé :
   powershell -ExecutionPolicy Bypass -File .\Installer.ps1 -InstallDir "D:\CVAgent"
   ```

2. L'installateur enchaîne **6 étapes** :
   1. **PostgreSQL 17** — installation silencieuse **depuis `Prerequis\` (hors
      ligne)** ; mot de passe superutilisateur généré et enregistré dans
      `…\postgres-superuser-password.txt`. (Repli winget si l'installeur local
      est absent.)
   2. **Ollama** (si `-InstallOllama`) — moteur LLM local, installé depuis
      `Prerequis\OllamaSetup.exe` (hors ligne, repli winget).
   3. **Base `cvagent`** — rôle + base dédiés.
   4. **Variables système** — `CV_AGENT_DB_URL` (connexion) et `CV_AGENT_SECRET`
      (chiffrement des secrets + cookie de session).
   5. **Application** — copiée dans `C:\CV-Agent-Pro`, raccourcis Bureau + menu Démarrer.
   6. **Démarrage** — l'application se lance (icône près de l'horloge) et ouvre le
      navigateur sur la page de **création du compte administrateur**.

3. **Premiers pas** : créez l'admin sur `/setup`, connectez-vous, puis
   **Administration → Paramètres** :
   - **Mail** : serveur IMAP, **Sécurité IMAP** (SSL 993 / STARTTLS 143 / Aucune),
     utilisateur, mot de passe, dossier. Bouton « Tester la connexion ».
   - **LLM** : Ollama local (`http://localhost:11434`) ou cloud OpenRouter.
     Si Ollama tourne sur une **autre machine**, mettre `http://<IP_du_serveur>:11434`
     (et lancer ce serveur avec `OLLAMA_HOST=0.0.0.0`).
   - **SMTP** (optionnel) : pour les notifications par email.

## 4. Installation alternative : `Application\CV-Agent-Setup.exe`

Installateur graphique **de l'application seule** (assistant Inno Setup en
français, sans droits administrateur). Il copie l'application, crée les
raccourcis et propose la **création du compte administrateur** pendant
l'assistant. À utiliser :

- pour **mettre à jour** l'application sur un poste déjà installé ;
- quand **PostgreSQL et les variables système existent déjà** (posés par
  `Installer.ps1` ou par `Prerequis\Installer-PostgreSQL.ps1`).

> Il n'installe **ni** PostgreSQL **ni** les variables `CV_AGENT_DB_URL` /
> `CV_AGENT_SECRET` : sur un poste vierge, utilisez `Installer.ps1` (section 3),
> ou lancez d'abord `Prerequis\Installer-PostgreSQL.ps1` puis définissez les
> variables affichées avant d'exécuter ce Setup.

## 5. Accès partagé depuis d'autres postes (mode serveur LAN)

L'installation ci-dessus est en **mode bureau** (usage local, boucle locale). Pour
que **plusieurs postes RH** consultent l'application via leur navigateur, exposez
le serveur sur le réseau local : voir le **Manuel de déploiement**
(`Manuels\Manuel_Deploiement\`), section « Exposition réseau » et « Démarrage
automatique au boot ». En résumé : lancer le serveur sur `0.0.0.0:6060`, ouvrir
le port 6060 au pare-feu (sous-réseau LAN), puis les clients ouvrent
`http://<ip-serveur>:6060` — rien à installer côté client.

## 6. Alternative : déploiement Docker

Si vous préférez Docker (PostgreSQL inclus dans le paquet, multiplateforme), le
Manuel de déploiement décrit la voie `docker compose up -d`. Utile pour un
serveur centralisé. Non nécessaire pour une installation poste simple.

## 7. Mise à jour

- **Application** : remplacez le contenu de `C:\CV-Agent-Pro` par la nouvelle
  version (`Application\CV-Agent\`), ou lancez `Application\CV-Agent-Setup.exe`.
  Les données restent dans PostgreSQL (intactes).
- Les variables système et la base ne sont pas à refaire.

## 8. Désinstallation

1. Fermez l'application (clic droit sur l'icône près de l'horloge → Quitter).
2. Supprimez le dossier `C:\CV-Agent-Pro` et les raccourcis.
3. Variables système à retirer (PowerShell admin) :
   ```powershell
   [Environment]::SetEnvironmentVariable("CV_AGENT_DB_URL", $null, "Machine")
   [Environment]::SetEnvironmentVariable("CV_AGENT_SECRET", $null, "Machine")
   ```
4. PostgreSQL se désinstalle depuis « Applications et fonctionnalités » (la base
   `cvagent` contient vos données : sauvegardez-la avant si besoin, `pg_dump`).

## 9. Dépannage

| Symptôme | Cause / solution |
|---|---|
| « winget est introuvable » | N'arrive que si `Prerequis\` est vide. Remettez les installeurs dans `Prerequis\`, ou installez « App Installer » depuis le Microsoft Store, puis relancez. |
| L'installateur ne démarre pas | Clic droit → Exécuter avec PowerShell **en administrateur**. Politique d'exécution : préfixez par `powershell -ExecutionPolicy Bypass -File`. |
| « CV_AGENT_DB_URL n'est pas définie » au lancement | Rouvrez une session (les variables système ne s'appliquent qu'aux nouveaux processus) ou vérifiez l'étape 4 de l'installateur. |
| Connexion mail refusée | Vérifiez la **Sécurité IMAP** (SSL/STARTTLS) et le port. Gmail/Outlook exigent un **mot de passe d'application**. |
| PostgreSQL non installé automatiquement | Lancez `Prerequis\Installer-PostgreSQL.ps1` (utilise l'installeur local hors ligne), puis reportez l'URL affichée dans la variable `CV_AGENT_DB_URL`. Dernier recours : double-clic sur `Prerequis\postgresql-17.10-1-windows-x64.exe` (assistant graphique). |
| Le modèle IA ne répond pas | Ollama lancé ? Modèle téléchargé (`ollama pull qwen2.5:14b`) ? Sinon basculez sur le fournisseur cloud OpenRouter dans les Paramètres LLM. |
| Test Ollama : « serveur injoignable » | Vérifiez l'URL dans **Param. LLM** : `http://localhost:11434` (même PC) ou `http://<IP_du_serveur>:11434` (Ollama sur une autre machine, lancé avec `OLLAMA_HOST=0.0.0.0`). |

---

Pour l'utilisation quotidienne, voir **`Manuels\Manuel_Utilisateur\`**.
Pour l'exploitation, la sauvegarde et le mode réseau, voir
**`Manuels\Manuel_Deploiement\`**.
