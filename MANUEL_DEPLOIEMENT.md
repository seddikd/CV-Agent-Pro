# Manuel de déploiement — CV Agent Pro

> Public : la personne **IT** qui installe, configure et exploite l'application.
> Pour l'usage quotidien par l'équipe RH, voir `MANUEL_UTILISATION.md`.

CV Agent Pro est un outil RH qui relève une **boîte mail (IMAP)**, détecte et extrait
les CV par IA, stocke les candidats en base **PostgreSQL** et sert un tableau de bord
web (FastAPI + Jinja + HTMX, en français). Il fonctionne **100 % en local** : aucune
donnée ne sort du réseau, sauf si le fournisseur LLM cloud `openrouter` est explicitement choisi.

---

## Table des matières

1. [Vue d'ensemble & architecture](#1-vue-densemble--architecture)
2. [Base de données : PostgreSQL (requise)](#2-base-de-données--postgresql-requise)
3. [Prérequis](#3-prérequis)
4. [Installation des dépendances](#4-installation-des-dépendances)
5. [Déploiement Docker (recommandé)](#5-déploiement-docker-recommandé)
6. [Déploiement natif (serveur + PostgreSQL)](#6-déploiement-natif-serveur--postgresql)
7. [Exposition réseau (port applicatif 6060)](#7-exposition-réseau-port-applicatif-6060)
8. [Postes clients](#8-postes-clients)
9. [Démarrage automatique au boot](#9-démarrage-automatique-au-boot)
10. [Modèle de sécurité des secrets](#10-modèle-de-sécurité-des-secrets)
11. [HTTPS & durcissement](#11-https--durcissement)
12. [Construction de l'exécutable Windows](#12-construction-de-lexécutable-windows)
13. [Configuration LLM : Ollama vs OpenRouter](#13-configuration-llm--ollama-vs-openrouter)
14. [Sauvegarde & restauration](#14-sauvegarde--restauration)
15. [Invariants à respecter](#15-invariants-à-respecter)
16. [Exploitation courante](#16-exploitation-courante)
17. [Dépannage](#17-dépannage)
18. [Annexes](#18-annexes)

---

## 1. Vue d'ensemble & architecture

L'application est une **seule** instance FastAPI (un seul worker uvicorn) qui porte
à la fois l'interface web, le planificateur interne (APScheduler) et le pipeline de
traitement des CV. Les postes RH y accèdent par un simple **navigateur**. La base de
données est **PostgreSQL** (obligatoire).

```
┌──────────────────────────────────────────────────────────────┐
│  SERVEUR  (ex. 192.168.1.10)                                │
│                                                               │
│   ┌──────────────────────────────┐    ┌───────────────────┐   │
│   │  Application CV Agent Pro     │    │   PostgreSQL      │   │
│   │  uvicorn 0.0.0.0:6060         │───▶│   (base cvagent)  │   │
│   │  (1 worker)                   │    │                   │   │
│   │  • Interface web (Jinja/HTMX) │    └───────────────────┘   │
│   │  • Planificateur (APScheduler)│                            │
│   │  • Pipeline IMAP → LLM → base │──▶ Boîte mail (IMAP)       │
│   └──────────────────────────────┘     + Ollama ou OpenRouter │
└───────────────────────┬──────────────────────────────────────┘
                        │  HTTP :6060 (LAN)
        ┌───────────────┼───────────────┐
   navigateur       navigateur      navigateur
   (poste RH 1)     (poste RH 2)    (poste RH 3)
```

Points clés :

- **IMAP, pipeline LLM et planificateur tournent uniquement sur le serveur.** Les
  clients ne relèvent jamais la boîte mail eux-mêmes. Le bouton « Lancer maintenant »
  cliqué depuis un client déclenche la synchronisation **sur le serveur**.
- **Un seul processus** écrit la base (writer unique + APScheduler). Ne lancez jamais
  plusieurs instances qui relèvent la même boîte (voir [§15](#15-invariants-à-respecter)).
- Le flux d'un cycle : `mail_fetcher (IMAP)` → `pdf_extractor (PDF/DOCX → texte)` →
  `llm_classifier (est-ce un CV ?)` → `llm_extractor (champs structurés)` →
  insertion en base.

---

## 2. Base de données : PostgreSQL (requise)

Le moteur est **PostgreSQL**, défini par la variable d'environnement **`CV_AGENT_DB_URL`**
(voir `db.py`). Elle est **obligatoire** : sans elle, l'application refuse de démarrer
avec un message clair. Il n'y a **plus de repli SQLite** ni de fichier `state.db`.

```
CV_AGENT_DB_URL="postgresql://cvagent:motdepasse@HOTE:5432/cvagent"
```

Deux façons d'obtenir cette base :

- **Via Docker Compose** ([§5](#5-déploiement-docker-recommandé)) : un service PostgreSQL est
  fourni et provisionné automatiquement — rien à installer côté base. **Recommandé.**
- **Via un serveur PostgreSQL existant** ([§6](#6-déploiement-natif-serveur--postgresql)) : local
  au serveur applicatif ou sur un serveur dédié du réseau.

> Le schéma est produit automatiquement au premier démarrage (clés primaires `SERIAL`,
> upserts `ON CONFLICT`). Les données métier (candidats, offres, réglages, utilisateurs…)
> vivent **uniquement** dans PostgreSQL ; seuls les fichiers (`cv_pdfs/`, `logs/`) restent
> sur disque.

---

## 3. Prérequis

| Élément | Détail |
|---|---|
| **PostgreSQL** | **Obligatoire** dans tous les cas. Fourni par l'image `postgres` en Docker, ou un serveur PostgreSQL **17** existant (natif). |
| OS | Windows 10 / 11 (déploiement natif) — ou **n'importe quel OS via Docker** ([§5](#5-déploiement-docker-recommandé)) |
| Python | 3.11 ou supérieur (déploiement depuis les sources / venv ; inutile en Docker) |
| LLM local | [Ollama](https://ollama.com) + un modèle (ex. `qwen2.5:14b`) — recommandé, gratuit, 100 % local |
| LLM cloud | *ou* une clé API OpenRouter (si la machine est trop modeste pour Ollama) |
| Boîte mail | **Tout serveur IMAP** (Gmail, Outlook/Office 365, OVH, Zoho, serveur interne…). Certains fournisseurs exigent un **mot de passe d'application**. |
| Réseau | LAN entre le serveur et les postes RH |

---

## 4. Installation des dépendances

> En **Docker**, cette étape est inutile : l'image embarque tout ([§5](#5-déploiement-docker-recommandé)).
> Cette section ne concerne que le déploiement **natif** (depuis les sources).

Depuis les sources (dossier du projet) :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Ou via l'installateur fourni (crée le venv, installe, puis bootstrap interactif) :

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> `requirements.txt` inclut **`cryptography`** (chiffrement portable des secrets `enc:v2`)
> et **`psycopg[binary]`** (pilote PostgreSQL). Si vous distribuez un `.exe` déjà construit,
> **reconstruisez-le** après tout ajout de dépendance (voir [§12](#12-construction-de-lexécutable-windows)).

---

## 5. Déploiement Docker (recommandé)

La méthode la plus simple et la plus portable : tout est empaqueté dans une image
(aucune dépendance à installer, fonctionne sous **Windows / Linux / macOS**). Les
postes clients restent de simples navigateurs, et **un seul serveur applicatif** tourne.

### 5.1 Prérequis Docker

- **Docker Engine** + **Docker Compose v2**, ou **Docker Desktop** (qui inclut les deux).
- Le LLM reste **externe** au conteneur : Ollama sur l'hôte, ou le cloud OpenRouter
  (voir [§5.6](#56-llm-depuis-le-conteneur)).

### 5.2 Générer le secret partagé

`CV_AGENT_SECRET` est **obligatoire** en conteneur (voir l'encadré en fin de section).
Générez une valeur aléatoire :

```bash
docker run --rm python:3.12-slim python -c "import secrets;print(secrets.token_hex(32))"
```

### 5.3 « Batteries incluses » — application + PostgreSQL (recommandé)

Une seule commande démarre l'application **et** une base PostgreSQL, via
`docker-compose.yml` :

```bash
cp .env.example .env      # puis renseignez CV_AGENT_SECRET et POSTGRES_PASSWORD
docker compose up -d
```

- Remplissez `.env` :
  - `CV_AGENT_SECRET` = la valeur générée en [§5.2](#52-générer-le-secret-partagé) ;
  - `POSTGRES_PASSWORD` = un mot de passe **alphanumérique** (lettres/chiffres
    uniquement, pour éviter tout percent-encodage dans l'URL de connexion).
- Le **schéma et les réglages par défaut se créent automatiquement** au premier
  démarrage (aucun `init_postgres.py` à lancer) : les 11 tables sont créées, la base
  appartient au rôle `cvagent`.
- L'ordre de démarrage est géré : l'application attend que PostgreSQL soit *healthy*.

### 5.4 Image seule contre un PostgreSQL existant

Si vous avez déjà un serveur PostgreSQL (hors compose), lancez l'image seule en lui
passant `CV_AGENT_DB_URL` :

```bash
docker build -t cv-agent-pro:latest .

docker run -d --name cv-agent -p 6060:6060 --restart unless-stopped \
  -e CV_AGENT_SECRET=<hex_généré_en_5.2> \
  -e CV_AGENT_DB_URL=postgresql://cvagent:motdepasse@HOTE:5432/cvagent \
  -v cvagent-data:/data \
  cv-agent-pro:latest
```

Le schéma se crée automatiquement au démarrage (la base cible doit exister et le rôle
avoir les droits — voir [§6.1](#61-créer-le-rôle-applicatif-et-la-base)).

### 5.5 Accès, volumes et persistance

- Ouvrez `http://<hôte>:6060/setup` pour créer le premier administrateur, puis
  configurez IMAP / SMTP / LLM dans **Administration → Paramètres** (voir aussi la
  sécurité IMAP en [§6.4](#64-démarrer-et-créer-ladministrateur)).
- Les données persistent dans des **volumes nommés** (indépendants du cycle de vie des
  conteneurs) :

| Volume | Contenu |
|---|---|
| `cvagent-db` | données PostgreSQL (candidats, offres, réglages, utilisateurs…) — mode compose |
| `cvagent-data` | fichiers : `/data/cv_pdfs/` (PDF des CV) et `/data/logs/` |

> Le conteneur tourne en utilisateur **non-root** (uid 10001), propriétaire du volume
> `/data`. `CV_AGENT_DATA_DIR=/data` redirige toutes les écritures fichier vers ce volume.

### 5.6 LLM depuis le conteneur

Le conteneur doit joindre le moteur LLM :

- **Ollama sur l'hôte** : réglez `ollama.host` = `http://host.docker.internal:11434`
  dans **Administration → Paramètres** (le défaut `http://localhost:11434` ne
  fonctionne **que** pour l'app desktop `.exe` : dans un conteneur, `localhost`
  désigne le conteneur lui-même, pas l'hôte). Le `docker-compose.yml` fourni
  mappe déjà `host.docker.internal` (bloc `extra_hosts`), y compris sous Docker
  Linux natif. Avec `docker run`, ajoutez `--add-host=host.docker.internal:host-gateway`.
  Vérifiez enfin qu'Ollama écoute au-delà de `127.0.0.1` (lancez-le avec
  `OLLAMA_HOST=0.0.0.0`) pour qu'il accepte les connexions du conteneur.
- **OpenRouter (cloud)** : choisissez le fournisseur `openrouter` et renseignez la clé
  (ou passez `OPENROUTER_API_KEY` en variable d'environnement).

### 5.6bis Import de fichiers Outlook (PST/OST)

La page **Import Outlook** permet de traiter une archive `.pst`/`.ost` en plus de l'IMAP
(voir manuel utilisateur §17bis). Côté déploiement :

- **Docker (Linux)** : la lecture utilise `libpff` (paquet `libpff-python`), **compilé au
  build** de l'image (le `Dockerfile` installe `build-essential` le temps de la compilation
  puis le purge). Le `docker-compose.yml` monte `./import` → `/data/import` : déposez-y les
  fichiers volumineux (plusieurs Go), ils apparaissent dans la page. Réglage du dossier :
  `outlook.import_dir` (relatif à `/data`).
- **Windows (.exe)** : le backend fiable est **Outlook via `pywin32`** (Outlook doit être
  installé). `libpff-python` (backend `pypff`) fonctionne aussi si un compilateur/wheel est
  disponible. Le choix se règle via `outlook.backend` (`auto` | `pypff` | `win32com`).
- Un import se suit comme un cycle (page **Cycles**, source `import_outlook`) et respecte le
  même invariant « un seul traitement à la fois ».

### 5.7 Exploitation Docker

```bash
# Journaux en direct
docker compose logs -f app

# Mise à jour (nouvelle version du code)
git pull
docker compose up -d --build

# Sauvegarde PostgreSQL
docker compose exec -T db pg_dump -U cvagent -Fc cvagent > cvagent_backup.dump
# Restauration
docker compose exec -T db pg_restore -U cvagent -d cvagent < cvagent_backup.dump

# Arrêt (conteneurs) — volumes/données conservés
docker compose down
# Arrêt + SUPPRESSION des volumes (efface TOUTES les données !)
docker compose down -v
```

> ⚠️ **`CV_AGENT_SECRET` est obligatoire en conteneur.** Le chiffrement DPAPI de
> Windows n'existe pas sous Linux : c'est le chiffrement portable `enc:v2:` (Fernet,
> clé dérivée de `CV_AGENT_SECRET`) qui protège les secrets. Sans cette variable, ils
> seraient stockés en clair. Utilisez la **même** valeur si plusieurs instances
> partagent la même base. Voir [§10](#10-modèle-de-sécurité-des-secrets).

---

## 6. Déploiement natif (serveur + PostgreSQL)

Déploiement **sans Docker** : un serveur applicatif Windows + un serveur PostgreSQL
(local au serveur ou dédié). **PostgreSQL peut rester en `localhost`** si l'application
tourne sur la même machine : seule elle y accède, il est donc inutile (et déconseillé)
d'exposer le port 5432 au réseau.

> **Appli bureau / `.exe`** : `desktop.py` (uvicorn en loopback + icône systray) et
> l'exécutable Windows fonctionnent aussi, mais exigent désormais `CV_AGENT_DB_URL`
> (connexion à PostgreSQL) — il n'y a plus de base locale packagée.

### 6.1 Créer le rôle applicatif et la base

Dans **pgAdmin** ou **psql** (connecté en superutilisateur `postgres`) :

```sql
-- Rôle applicatif dédié (ne pas utiliser le superutilisateur pour l'app)
CREATE ROLE cvagent LOGIN PASSWORD 'un_mot_de_passe_fort';
ALTER ROLE cvagent CREATEDB;          -- pour qu'init_postgres.py puisse créer la base

-- Base (si vous ne laissez pas init_postgres.py la créer) + propriété au rôle
CREATE DATABASE cvagent OWNER cvagent;
GRANT ALL ON SCHEMA public TO cvagent; -- PG15+ : autorise cvagent à créer les tables
```

> La **propriété** de la base par `cvagent` (ou le `GRANT ALL ON SCHEMA public`) est
> nécessaire en PostgreSQL 15+ : par défaut, le schéma `public` n'autorise plus la
> création de tables à tout le monde.

### 6.2 Poser les variables d'environnement

Sur le serveur, dans une invite **PowerShell administrateur** (`/M` = niveau machine,
pour que la tâche planifiée et les nouveaux terminaux les voient) :

```powershell
setx /M CV_AGENT_DB_URL "postgresql://cvagent:MOT_DE_PASSE@localhost:5432/cvagent"
setx /M CV_AGENT_SECRET "COLLER_ICI_LE_SECRET_GENERE"
```

Générez d'abord le secret partagé :

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

> ⚠️ **`setx` n'affecte que les processus lancés APRÈS.** Fermez et rouvrez le
> terminal avant l'étape suivante.

#### Encodage du mot de passe dans l'URL (crucial)

`CV_AGENT_DB_URL` est une **URL** : tout caractère réservé dans le mot de passe doit
être **percent-encodé**, sinon l'URL est mal interprétée (échec de connexion).

| Caractère | Encodé | | Caractère | Encodé |
|---|---|---|---|---|
| `@` | `%40` | | `#` | `%23` |
| `:` | `%3A` | | `?` | `%3F` |
| `/` | `%2F` | | `%` | `%25` |
| `&` | `%26` | | ` ` (espace) | `%20` |

**Exemple** : mot de passe `MonPass@2024` → l'URL devient
`postgresql://cvagent:MonPass%402024@localhost:5432/cvagent` (le `@` du mot de passe
s'écrit `%40` ; le `@` qui sépare les identifiants de l'hôte reste littéral).
Le plus simple reste de choisir un mot de passe **sans caractères réservés**.

### 6.3 Provisionner la base

Toujours dans le dossier du projet, **nouveau terminal** (pour hériter des variables) :

```powershell
.\.venv\Scripts\python.exe init_postgres.py
```

`init_postgres.py` est **idempotent** (relançable sans risque) et réalise :

1. crée la base cible si elle n'existe pas (via la base de maintenance `postgres`) ;
2. crée le schéma complet (tables à clé `SERIAL`) ;
3. sème les 30 réglages par défaut.

Sortie attendue :

```
Base « cvagent » créée.            (ou « déjà présente — conservée »)
Schéma créé + 30 réglages par défaut dans « cvagent ».
Prochaine étape : démarrer l'application et créer l'admin via /setup.
```

### 6.4 Démarrer et créer l'administrateur

```powershell
.\run_web.bat
```

Puis ouvrez `http://localhost:6060/setup` pour créer le premier compte admin, et
configurez **IMAP / LLM / SMTP** dans **Administration → Paramètres**.

> **Boîte mail** : renseignez `Serveur IMAP`, `Port IMAP` et **`Sécurité IMAP`**
> (`SSL` port 993 · `STARTTLS` port 143 · `Aucune`) selon votre fournisseur —
> Gmail, Outlook/Office 365, OVH, Zoho ou serveur interne. Un bouton **« Tester la
> connexion à la boîte mail »** valide la saisie.

> **Alternative en ligne de commande** : avec `CV_AGENT_DB_URL` posée, `python
> bootstrap.py` crée aussi l'admin directement dans PostgreSQL.

---

## 7. Exposition réseau (port applicatif 6060)

L'application écoute sur `0.0.0.0:6060` (`run_web.bat`, ou `start_web.bat` avec
`--workers 1` pour la tâche planifiée). Il faut ouvrir **ce port** au LAN — **jamais**
le 5432 si PostgreSQL est local.

```powershell
# Règle pare-feu restreinte au sous-réseau LAN (adapter le /24 à votre réseau)
New-NetFirewallRule -DisplayName "CV-Agent 6060 LAN" -Direction Inbound `
  -Protocol TCP -LocalPort 6060 -Action Allow -RemoteAddress 192.168.1.0/24
```

> Restreindre `-RemoteAddress` au sous-réseau (plutôt que « n'importe où ») limite
> l'exposition. Le trafic étant en HTTP clair, voir aussi [§11](#11-https--durcissement).

---

## 8. Postes clients

**Rien à installer.** Chaque poste RH ouvre simplement dans un navigateur :

```
http://192.168.1.10:6060
```

(remplacer par l'IP réelle du serveur). Aucune variable d'environnement, aucune
configuration IMAP, aucun accès direct à la base côté client.

---

## 9. Démarrage automatique au boot

> En **Docker**, préférez `--restart unless-stopped` (image seule) ou
> `restart: unless-stopped` dans compose : le conteneur redémarre tout seul. Cette
> section concerne le déploiement **natif** Windows.

Pour que le serveur démarre l'application à chaque redémarrage Windows :

```powershell
# PowerShell ADMINISTRATEUR
powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1
```

Ce script (`install_autostart.ps1`) :

- crée une **tâche planifiée** `CV-Agent-Web` déclenchée **au démarrage** (délai 1 min
  pour laisser le réseau monter), avec redémarrage automatique (3 essais / 5 min) ;
- demande un **compte utilisateur Windows** (pas SYSTEM, pour accéder au Python
  d'AppData) et son mot de passe ; la tâche tourne sous ce compte ;
- lance `start_web.bat` (uvicorn `0.0.0.0:6060 --workers 1`, journalisé dans
  `logs\web_startup.log`) ;
- ouvre la **règle pare-feu** entrante TCP 6060 (profils Domain + Private).

> Le compte de la tâche doit voir les variables `CV_AGENT_DB_URL` / `CV_AGENT_SECRET`.
> Comme elles sont posées avec `setx /M` (niveau machine), c'est le cas.

Vérifier / démarrer sans rebooter / désinstaller :

```powershell
Start-ScheduledTask -TaskName 'CV-Agent-Web'
Get-ScheduledTask   -TaskName 'CV-Agent-Web' | Get-ScheduledTaskInfo

# Désinstallation (tâche + règle pare-feu + arrêt du process sur 6060)
powershell -ExecutionPolicy Bypass -File .\uninstall_autostart.ps1
```

---

## 10. Modèle de sécurité des secrets

Les secrets sensibles — `imap.password`, `smtp.password`, `openrouter.api_key` — sont
**chiffrés au repos** dans la table `settings`, de façon transparente (les appelants
manipulent toujours le clair en mémoire). Deux formats coexistent (`secret_store.py`) :

| Format | Mécanisme | Portable ? | Quand |
|---|---|---|---|
| **`enc:v2:…`** | Fernet (AES-128-CBC + HMAC-SHA256), clé dérivée de `CV_AGENT_SECRET` par PBKDF2-HMAC-SHA256 (200 000 itérations) | ✅ Oui — déchiffrable par toute machine partageant le même `CV_AGENT_SECRET` | dès que `CV_AGENT_SECRET` est défini |
| **`enc:v1:…`** | DPAPI Windows, portée **machine** | ❌ Non — lié à la machine d'origine | Windows natif, quand `CV_AGENT_SECRET` est absent |
| (sans préfixe) | valeur « legacy » en clair | — | migrée automatiquement au démarrage |

Conséquences pour le déploiement :

- **En conteneur Docker** (Linux), DPAPI n'existe pas : `CV_AGENT_SECRET` est
  **obligatoire** pour chiffrer les secrets (`enc:v2`). Sans elle, ils seraient en clair.
- **Une valeur illisible** (mauvais/absent `CV_AGENT_SECRET`, ou blob DPAPI copié sur
  une autre machine) renvoie `""` — l'application traite cela comme « pas
  d'identifiants » et **ne plante pas**.
- Pour un déploiement où **plusieurs instances** partagent la même base PostgreSQL,
  posez le **même** `CV_AGENT_SECRET` partout, afin que les secrets `enc:v2` soient
  déchiffrables par chaque instance.
- ⚠️ **Ne mettez jamais de vrais identifiants dans `config.yaml`** : ce fichier n'est
  qu'un gabarit de premier lancement, et il est **embarqué dans l'exe distribué**.
- ⚠️ **Ne versionnez jamais** `session.secret`, `cv_pdfs/`, `logs/`, `.env` — ils
  contiennent des données candidats et des secrets (déjà couverts par `.gitignore`).

---

## 11. HTTPS & durcissement

- **HTTP en clair sur le LAN** : par défaut le trafic n'est pas chiffré. Pour un
  réseau non maîtrisé, placez l'application derrière un **reverse-proxy TLS** (nginx,
  Caddy, IIS ARR…) et activez le drapeau `Secure` du cookie de session :
  ```powershell
  setx /M CV_AGENT_HTTPS_ONLY "1"
  ```
  (en Docker : variable d'environnement `CV_AGENT_HTTPS_ONLY=1`.)
- Le cookie de session est déjà `HttpOnly` + `SameSite=lax` (atténuation CSRF sur les
  POST mutants).
- **Anti-force-brute** : le login limite à 5 échecs par compte puis blocage 30 s.
- Restreignez la règle pare-feu 6060 au strict sous-réseau nécessaire ([§7](#7-exposition-réseau-port-applicatif-6060)).

---

## 12. Construction de l'exécutable Windows

L'application se distribue en `.exe` autonome (PyInstaller, mode *onedir*). L'exe exige
`CV_AGENT_DB_URL` (PostgreSQL) au lancement.

```powershell
# Build : produit dist\CV-Agent\CV-Agent.exe (+ dossier _internal\)
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
#   équivaut à : .\.venv\Scripts\python.exe -m PyInstaller cv-agent.spec --noconfirm --clean

# Installeur Inno Setup : produit dist\CV-Agent-Setup.exe (installation par utilisateur,
# sans UAC ; saisit le compte admin et le crée via l'exe --create-admin)
.\build_installer.ps1

# Signature (optionnelle)
powershell -ExecutionPolicy Bypass -File .\sign.ps1
```

Points d'attention :

- **`cv-agent.spec`** liste explicitement les modules dans `hiddenimports` (dont
  `web_core`, `matching_core`, `alerts_engine` et tous les `mod_*`) et embarque
  **`psycopg`** (pilote PostgreSQL) via `collect_all`. **Quand vous ajoutez un nouveau
  module top-level, ajoutez-le ici**, sinon l'exe plantera avec `ModuleNotFoundError`.
- **Après l'ajout de `cryptography` / `psycopg`**, reconstruisez impérativement l'exe
  pour que les dépendances soient embarquées.
- Le `.exe` figé écrit ses fichiers dans `%LOCALAPPDATA%\CV-Agent-Pro\` (logs,
  `cv_pdfs`, `session.secret`), jamais dans le dossier d'installation (lecture seule).
  La base, elle, est sur PostgreSQL.

---

## 13. Configuration LLM : Ollama vs OpenRouter

Le fournisseur est un **choix de configuration** (`llm.provider`), pas un basculement
automatique. Réglé dans **Administration → Paramètres**.

| Fournisseur | À préparer côté déployeur |
|---|---|
| **Ollama** (local, recommandé) | Installer Ollama, télécharger le modèle (`ollama pull qwen2.5:14b`), vérifier qu'il écoute sur `http://localhost:11434`. La valeur de `ollama.host` dépend de **où** tourne Ollama (voir tableau ci-dessous). 100 % local, aucune donnée envoyée. |
| **OpenRouter** (cloud) | Renseigner `openrouter.base_url`, `openrouter.model` et la clé API. La clé peut aussi venir de la variable d'environnement `OPENROUTER_API_KEY` (prioritaire sur la valeur stockée). ⚠️ Les CV sont alors envoyés au service cloud. |

**Valeur de `ollama.host` selon l'emplacement du serveur Ollama :**

| Où tourne Ollama | `ollama.host` |
|---|---|
| App desktop `.exe` (même PC) | `http://localhost:11434` |
| Conteneur Docker, Ollama sur l'**hôte** | `http://host.docker.internal:11434` |
| Ollama sur une **autre machine** | `http://<IP_du_serveur>:11434` |

> ⚠️ Par défaut, Ollama n'écoute que sur `127.0.0.1`. Pour qu'il soit joignable
> depuis un conteneur ou une autre machine, le lancer avec `OLLAMA_HOST=0.0.0.0`
> et ouvrir le port **11434/tcp** dans le pare-feu. Le `docker-compose.yml` fourni
> mappe déjà `host.docker.internal` (bloc `extra_hosts`), y compris sous Docker
> Linux natif. Test rapide depuis l'hôte : `curl http://<cible>:11434/api/tags`.

Le classifieur et l'extracteur passent tous deux par la même fonction et attendent un
objet JSON en retour.

---

## 14. Sauvegarde & restauration

Les données métier sont dans **PostgreSQL** ; les PDF des CV et les journaux sont des
fichiers.

### PostgreSQL (natif)

```powershell
# Sauvegarde de la base cvagent
pg_dump -U cvagent -h localhost -Fc cvagent -f cvagent_backup.dump

# Restauration (base vide au préalable)
pg_restore -U cvagent -h localhost -d cvagent cvagent_backup.dump
```

### PostgreSQL (Docker compose)

```bash
docker compose exec -T db pg_dump -U cvagent -Fc cvagent > cvagent_backup.dump
docker compose exec -T db pg_restore -U cvagent -d cvagent < cvagent_backup.dump
```

### Fichiers (PDF des CV, journaux)

Sauvegardez le dossier **`cv_pdfs/`** (et éventuellement `logs/`). En Docker, sauvegardez
le volume `cvagent-data`.

### Où vivent les données

| Donnée | Emplacement (dev / sources) | Emplacement (exe figé) | Emplacement (Docker) |
|---|---|---|---|
| Base (candidats, réglages…) | serveur PostgreSQL | serveur PostgreSQL | volume `cvagent-db` |
| PDF des CV | `cv_pdfs/` | `%LOCALAPPDATA%\CV-Agent-Pro\cv_pdfs\` | volume `cvagent-data` → `/data/cv_pdfs/` |
| Journaux | `logs\agent.log` | `%LOCALAPPDATA%\CV-Agent-Pro\logs\agent.log` | volume `cvagent-data` → `/data/logs/` |

> Toute écriture fichier passe par `app_paths.data_path()` (piloté par `CV_AGENT_DATA_DIR`
> en conteneur) : jamais de chemin relatif brut, pour rester valide une fois figé en `.exe`
> ou dans un volume Docker.

---

## 15. Invariants à respecter

- **Un seul worker uvicorn.** APScheduler et l'écriture base supposent un process
  unique (`start_web.bat` et le `Dockerfile` passent `--workers 1`). Ne montez pas à
  plusieurs workers.
- **Une seule instance qui relève l'IMAP.** Ne faites pas tourner deux serveurs
  applicatifs (ou deux conteneurs) qui relèvent la **même** boîte : ils dédoublonneraient
  mal et se disputeraient l'écriture. En architecture serveur unique, ce risque n'existe
  pas. Si vous multipliez les instances (déconseillé), désactivez le planificateur sur
  toutes sauf une (**Admin → Paramètres → planification désactivée**).
- **Requêtes SQL** (pour toute évolution du code) : placeholders `?`, token `{PK}`,
  `db.insert_returning_id(...)`, upserts `ON CONFLICT`.
- **Chemins via `app_paths.data_path()`** pour tout fichier écrit.

---

## 16. Exploitation courante

- **Journaux du pipeline** : `logs\agent.log` (relève, classification, extraction).
  Pour la tâche planifiée, la sortie de démarrage va dans `logs\web_startup.log`. En
  Docker : `docker compose logs -f app`.
- **Suivi des cycles** : page **Administration → Cycles** (emails relevés, CV détectés,
  statut, erreurs). Un cycle « Lancer maintenant » se déclenche à la demande.
- **Cycles orphelins** : si l'application est fermée pendant un cycle, la ligne
  `running` résiduelle est **nettoyée automatiquement au démarrage suivant**.
- **Planification** : par défaut, relève automatique toutes les 60 min (réglable dans
  Paramètres). Le premier cycle démarre peu après le lancement du serveur.

---

## 17. Dépannage

| Symptôme | Cause probable / résolution |
|---|---|
| L'app refuse de démarrer : *CV_AGENT_DB_URL n'est pas définie* | PostgreSQL est requis. Posez `CV_AGENT_DB_URL` (voir [§6.2](#62-poser-les-variables-denvironnement)) ou utilisez Docker compose qui la fournit. |
| Connexion PostgreSQL refusée / *password authentication failed* | Mot de passe mal **percent-encodé** dans `CV_AGENT_DB_URL` (encodez `@` en `%40`, etc. — voir [§6.2](#62-poser-les-variables-denvironnement)). Vérifiez aussi le rôle/mot de passe et que `pg_hba.conf` autorise la connexion. |
| `init_postgres.py` : *permission denied to create table* | Le rôle `cvagent` n'a pas les droits sur le schéma `public`. Rejouez `ALTER DATABASE cvagent OWNER TO cvagent;` puis `GRANT ALL ON SCHEMA public TO cvagent;`. |
| Les postes clients n'accèdent pas au serveur | Règle pare-feu 6060 absente / trop restrictive, ou l'app écoute sur `127.0.0.1` au lieu de `0.0.0.0`. Utilisez `run_web.bat` / `start_web.bat` (ou publiez `-p 6060:6060` en Docker). |
| Le port 6060 est déjà occupé | Un ancien process uvicorn tourne encore. `uninstall_autostart.ps1` tue le process sur 6060, ou repérez-le via `Get-NetTCPConnection -LocalPort 6060`. |
| Secrets « vides » en Docker ou après changement de machine | `CV_AGENT_SECRET` absent (Docker) ou blobs DPAPI (`enc:v1`) liés à l'ancienne machine. Posez `CV_AGENT_SECRET` (chiffrement portable `enc:v2`) et ressaisissez les secrets une fois. |
| La connexion à la boîte mail échoue | Mauvais **`Sécurité IMAP`** (SSL vs STARTTLS) ou port ; certains fournisseurs (Gmail, Outlook) exigent un **mot de passe d'application**. Utilisez le bouton « Tester la connexion ». |
| L'exe plante avec `ModuleNotFoundError` | Module top-level manquant dans `hiddenimports` de `cv-agent.spec`. Ajoutez-le et reconstruisez. |
| L'exe ne trouve pas `cryptography` / `psycopg` | Exe construit **avant** l'ajout de la dépendance. Reconstruisez (`build_exe.ps1`). |
| Variables d'environnement ignorées | `setx` n'affecte que les nouveaux processus : **rouvrez** le terminal (et redémarrez la tâche planifiée) après les avoir posées. |
| L'IA ne répond pas | Ollama non démarré / modèle non téléchargé, ou clé OpenRouter absente/invalide. Voir `logs\agent.log`. |
| Test Ollama : « serveur injoignable » (`Connection refused` sur `:11434`) | Mauvaise `ollama.host`. En Docker : `http://host.docker.internal:11434` (Ollama sur l'hôte) ou `http://<IP_du_serveur>:11434` (autre machine). Vérifier aussi qu'Ollama écoute sur `0.0.0.0` (pas seulement `127.0.0.1`) et que le port 11434 est ouvert. Test : `curl http://<cible>:11434/api/tags`. |

---

## 18. Annexes

### 18.1 Variables d'environnement

| Variable | Rôle | Exemple |
|---|---|---|
| `CV_AGENT_DB_URL` | **Obligatoire.** Connexion PostgreSQL ; mot de passe **percent-encodé**. | `postgresql://cvagent:pw@localhost:5432/cvagent` |
| `CV_AGENT_SECRET` | (1) stabilise le cookie de session entre redémarrages ; (2) active le chiffrement portable des secrets (`enc:v2`). **Obligatoire en conteneur** ; requis aussi si plusieurs instances partagent une base. | `<64 hex générés>` (voir §5.2 / §6.2) |
| `CV_AGENT_DATA_DIR` | Force le dossier des fichiers (`cv_pdfs`, `logs`). Utilisé en conteneur pour pointer vers un volume monté. | `/data` |
| `CV_AGENT_HTTPS_ONLY` | `1` ⇒ drapeau `Secure` sur le cookie (derrière un reverse-proxy TLS). | `1` |
| `POSTGRES_PASSWORD` | (docker-compose) mot de passe du rôle `cvagent` ; **alphanumérique** de préférence. | `MotDePasseAlphaNum123` |
| `OPENROUTER_API_KEY` | Clé cloud OpenRouter (prioritaire sur la valeur stockée en base). | `sk-or-…` |

### 18.2 Commandes utiles

```powershell
# Vérifier que CV_AGENT_DB_URL est bien vue (sinon lève une erreur claire)
.\.venv\Scripts\python.exe -c "import db; print(db.db_url())"

# Générer un CV_AGENT_SECRET
python -c "import secrets; print(secrets.token_hex(32))"

# Provisionner / re-provisionner PostgreSQL natif (idempotent)
.\.venv\Scripts\python.exe init_postgres.py

# Lancer un seul cycle de pipeline (debug d'une passe relève/classif/extraction)
python main.py

# Démarrer le serveur LAN (natif)
.\run_web.bat

# Docker : démarrer / journaux / arrêter
docker compose up -d
docker compose logs -f app
docker compose down
```

### 18.3 Checklist — déploiement Docker (recommandé)

- [ ] Docker Engine + Compose (ou Docker Desktop) installés
- [ ] `CV_AGENT_SECRET` généré
- [ ] `.env` créé à partir de `.env.example` (`CV_AGENT_SECRET` + `POSTGRES_PASSWORD` alphanumérique)
- [ ] `docker compose up -d`
- [ ] Conteneur *healthy* ; admin créé via `http://<hôte>:6060/setup`
- [ ] IMAP (serveur + **sécurité** + identifiants) / LLM / SMTP configurés dans Administration → Paramètres
- [ ] `ollama.host` = `http://host.docker.internal:11434` (ou clé OpenRouter valide)
- [ ] Port **6060** accessible depuis les postes clients
- [ ] Sauvegarde planifiée (`pg_dump` + volume `cvagent-data`)

### 18.4 Checklist — déploiement natif (PostgreSQL)

- [ ] PostgreSQL 17 installé et démarré (serveur local ou dédié)
- [ ] Rôle `cvagent` créé (LOGIN + CREATEDB), propriétaire de la base
- [ ] `CV_AGENT_SECRET` généré et posé (`setx /M`)
- [ ] `CV_AGENT_DB_URL` posée avec mot de passe **percent-encodé** (`setx /M`)
- [ ] Terminal rouvert (héritage des variables)
- [ ] `init_postgres.py` exécuté sans erreur (schéma + 30 réglages)
- [ ] Règle pare-feu **6060** ouverte au LAN (5432 **non** exposé)
- [ ] Application démarrée (`run_web.bat` ou tâche planifiée)
- [ ] Admin créé via `/setup` ; IMAP (avec **sécurité**) / LLM / SMTP configurés
- [ ] Ollama opérationnel (ou clé OpenRouter valide)
- [ ] Un poste client accède bien à `http://IP_SERVEUR:6060`
- [ ] Sauvegarde PostgreSQL planifiée (`pg_dump`)

---

*CV Agent Pro — manuel de déploiement. Pour l'utilisation quotidienne, voir
`MANUEL_UTILISATION.md` ; pour les conventions de code, voir `CLAUDE.md`.*
