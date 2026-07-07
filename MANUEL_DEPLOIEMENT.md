# Manuel de déploiement — CV Agent Pro

> Public : la personne **IT** qui installe, configure et exploite l'application.
> Pour l'usage quotidien par l'équipe RH, voir `MANUEL_UTILISATION.md`.

CV Agent Pro est un outil RH qui relève une boîte Gmail en IMAP, détecte et extrait
les CV par IA, stocke les candidats en base et sert un tableau de bord web (FastAPI +
Jinja + HTMX, en français). Il fonctionne **100 % en local** : aucune donnée ne sort
de la machine, sauf si le fournisseur LLM cloud `openrouter` est explicitement choisi.

---

## Table des matières

1. [Vue d'ensemble & architecture](#1-vue-densemble--architecture)
2. [Choix de la base : SQLite ou PostgreSQL](#2-choix-de-la-base--sqlite-ou-postgresql)
3. [Prérequis](#3-prérequis)
4. [Installation des dépendances](#4-installation-des-dépendances)
5. [Déploiement Docker (recommandé)](#5-déploiement-docker-recommandé)
6. [Déploiement A — SQLite (mono-poste bureau)](#6-déploiement-a--sqlite-mono-poste-bureau)
7. [Déploiement B — PostgreSQL centralisé (serveur + clients navigateur)](#7-déploiement-b--postgresql-centralisé-serveur--clients-navigateur)
8. [Exposition réseau (port applicatif 6060)](#8-exposition-réseau-port-applicatif-6060)
9. [Postes clients](#9-postes-clients)
10. [Démarrage automatique au boot](#10-démarrage-automatique-au-boot)
11. [Modèle de sécurité des secrets](#11-modèle-de-sécurité-des-secrets)
12. [HTTPS & durcissement](#12-https--durcissement)
13. [Construction de l'exécutable Windows](#13-construction-de-lexécutable-windows)
14. [Configuration LLM : Ollama vs OpenRouter](#14-configuration-llm--ollama-vs-openrouter)
15. [Sauvegarde & restauration](#15-sauvegarde--restauration)
16. [Invariants à respecter](#16-invariants-à-respecter)
17. [Exploitation courante](#17-exploitation-courante)
18. [Dépannage](#18-dépannage)
19. [Annexes](#19-annexes)

---

## 1. Vue d'ensemble & architecture

L'application est une **seule** instance FastAPI (un seul worker uvicorn) qui porte
à la fois l'interface web, le planificateur interne (APScheduler) et le pipeline de
traitement des CV. Les postes RH y accèdent par un simple **navigateur**.

```
┌──────────────────────────────────────────────────────────────┐
│  SERVEUR  (ex. 192.168.1.10)                                │
│                                                               │
│   ┌──────────────────────────────┐    ┌───────────────────┐   │
│   │  Application CV Agent Pro     │    │  Base de données  │   │
│   │  uvicorn 0.0.0.0:6060         │───▶│  SQLite (state.db)│   │
│   │  (1 worker)                   │    │  OU PostgreSQL    │   │
│   │                               │    │  (localhost:5432) │   │
│   │  • Interface web (Jinja/HTMX) │    └───────────────────┘   │
│   │  • Planificateur (APScheduler)│                            │
│   │  • Pipeline IMAP → LLM → base │──▶ Gmail (IMAP) + Ollama   │
│   └──────────────────────────────┘        ou OpenRouter       │
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
- **Un seul processus** écrit la base (contrainte SQLite + APScheduler). Ne lancez
  jamais plusieurs instances qui relèvent la même boîte (voir [§16](#16-invariants-à-respecter)).
- Le flux d'un cycle : `mail_fetcher (IMAP)` → `pdf_extractor (PDF/DOCX → texte)` →
  `llm_classifier (est-ce un CV ?)` → `llm_extractor (champs structurés)` →
  insertion en base.

---

## 2. Choix de la base : SQLite ou PostgreSQL

Le moteur est choisi par la **seule** variable d'environnement `CV_AGENT_DB_URL`
(voir `db.py`). Aucune modification de code n'est nécessaire pour basculer.

| Critère | **SQLite** (défaut) | **PostgreSQL** (optionnel) |
|---|---|---|
| Activation | `CV_AGENT_DB_URL` absente | `CV_AGENT_DB_URL="postgresql://…"` |
| Fichier / serveur | fichier `state.db` local | serveur PostgreSQL |
| Packagé dans l'exe | ✅ oui, testé | ❌ nécessite un serveur PG |
| Idéal pour | poste unique / bureau | centralisation, sauvegardes SQL, outillage externe |
| Administration | aucune | rôle, base, sauvegardes à gérer |

> **Important** : puisque l'architecture retenue est **un seul serveur applicatif**
> (les clients sont de simples navigateurs), **SQLite suffit** parfaitement. Une seule
> instance accède à la base. **PostgreSQL reste possible** si vous voulez des sauvegardes
> centralisées, de l'outillage SQL externe, ou anticiper une évolutivité — mais ce n'est
> pas une obligation. PostgreSQL n'apporte un gain fonctionnel que si vous faisiez tourner
> **plusieurs** instances serveur sur la même base (cas non standard ici).

Les deux moteurs partagent le même schéma, produit de façon portable (placeholders
`?`, clé primaire `{PK}` rendue en `AUTOINCREMENT`/`SERIAL`, upserts `ON CONFLICT`).

---

## 3. Prérequis

| Élément | Détail |
|---|---|
| OS | Windows 10 / 11 (déploiement natif, DPAPI natif) — ou **n'importe quel OS via Docker** ([§5](#5-déploiement-docker-recommandé)) |
| Python | 3.11 ou supérieur (si déploiement depuis les sources / venv, hors Docker) |
| PostgreSQL | **17** (seulement pour le déploiement B natif ; en Docker il est fourni par l'image `postgres`) |
| LLM local | [Ollama](https://ollama.com) + un modèle (ex. `qwen2.5:14b`) — recommandé, gratuit, 100 % local |
| LLM cloud | *ou* une clé API OpenRouter (si la machine est trop modeste pour Ollama) |
| Réseau | LAN entre le serveur et les postes RH ; une boîte Gmail dédiée avec **mot de passe d'application** (IMAP activé) |

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

> `requirements.txt` inclut désormais **`cryptography`** (chiffrement portable des
> secrets `enc:v2`) et **`psycopg[binary]`** (pilote PostgreSQL). Si vous distribuez
> un `.exe` déjà construit, **reconstruisez-le** après cet ajout (voir [§13](#13-construction-de-lexécutable-windows)).

---

## 5. Déploiement Docker (recommandé)

La méthode la plus simple et la plus portable : tout est empaqueté dans une image
(aucune dépendance à installer, fonctionne sous **Windows / Linux / macOS**). Les
postes clients restent de simples navigateurs, et **un seul serveur applicatif**
tourne — comme dans les déploiements natifs.

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

### 5.3 Mode 1 — « batteries incluses » (application + PostgreSQL)

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

### 5.4 Mode 2 — conteneur unique avec SQLite (façon Uptime Kuma)

Sans PostgreSQL : une image, un volume, terminé.

```bash
docker build -t cv-agent-pro:latest .

docker run -d --name cv-agent -p 6060:6060 --restart unless-stopped \
  -e CV_AGENT_SECRET=<hex_généré_en_5.2> \
  -v cvagent-data:/data \
  cv-agent-pro:latest
```

Sans `CV_AGENT_DB_URL`, l'image utilise **SQLite** par défaut : la base vit dans
`/data/state.db` (dans le volume).

### 5.5 Accès, volumes et persistance

- Ouvrez `http://<hôte>:6060/setup` pour créer le premier administrateur, puis
  configurez IMAP / SMTP / LLM dans **Administration → Paramètres**.
- Les données persistent dans des **volumes nommés** (indépendants du cycle de vie des
  conteneurs) :

| Volume | Contenu |
|---|---|
| `cvagent-data` | `/data` : `cv_pdfs/`, `logs/`, et `state.db` en mode SQLite |
| `cvagent-db` | données PostgreSQL (mode compose uniquement) |

> Le conteneur tourne en utilisateur **non-root** (uid 10001), propriétaire du volume
> `/data`. `CV_AGENT_DATA_DIR=/data` redirige toutes les écritures vers ce volume.

### 5.6 LLM depuis le conteneur

Le conteneur doit joindre le moteur LLM :

- **Ollama sur l'hôte** : réglez `ollama.host` = `http://host.docker.internal:11434`
  dans **Administration → Paramètres**. Sous Linux, ajoutez si besoin
  `--add-host=host.docker.internal:host-gateway` au `docker run` (ou le mapping
  équivalent dans compose).
- **OpenRouter (cloud)** : choisissez le fournisseur `openrouter` et renseignez la clé
  (ou passez `OPENROUTER_API_KEY` en variable d'environnement).

### 5.7 Exploitation Docker

```bash
# Journaux en direct
docker compose logs -f app

# Mise à jour (nouvelle version du code)
git pull
docker compose up -d --build

# Sauvegarde PostgreSQL (mode compose)
docker compose exec -T db pg_dump -U cvagent -Fc cvagent > cvagent_backup.dump
# Restauration
docker compose exec -T db pg_restore -U cvagent -d cvagent < cvagent_backup.dump

# Sauvegarde SQLite / fichiers : copier le contenu du volume cvagent-data

# Arrêt (conteneurs) — volumes/données conservés
docker compose down
# Arrêt + SUPPRESSION des volumes (efface TOUTES les données !)
docker compose down -v
```

> ⚠️ **`CV_AGENT_SECRET` est obligatoire en conteneur.** Le chiffrement DPAPI de
> Windows n'existe pas sous Linux : c'est le chiffrement portable `enc:v2:` (Fernet,
> clé dérivée de `CV_AGENT_SECRET`) qui protège les secrets. Sans cette variable, ils
> seraient stockés en clair. Utilisez la **même** valeur si plusieurs conteneurs
> partagent la même base. Voir [§11](#11-modèle-de-sécurité-des-secrets).

---

## 6. Déploiement A — SQLite (mono-poste bureau)

Le mode natif le plus simple : tout tient sur une machine, base SQLite locale.

```powershell
# 1. Dépendances + base + compte admin (interactif)
python bootstrap.py

# 2a. Application bureau (boucle locale 127.0.0.1 + icône systray) — comme l'exe livré
python desktop.py

# 2b. OU serveur web exposé au LAN (0.0.0.0:6060)
.\run_web.bat
```

- `bootstrap.py` initialise le schéma, sème les réglages par défaut, importe
  éventuellement `config.yaml`, puis crée le **premier administrateur** (interactif).
- `desktop.py` reproduit le comportement de l'exe : uvicorn en loopback + icône de
  la zone de notification. Les données vont dans `%LOCALAPPDATA%\CV-Agent-Pro\`
  quand l'application est figée en `.exe`, ou dans le dossier projet en développement.
- Ensuite, configurez IMAP / LLM / SMTP dans **Administration → Paramètres**.

---

## 7. Déploiement B — PostgreSQL centralisé (serveur + clients navigateur)

C'est le cas d'un serveur unique avec base PostgreSQL locale sur ce même serveur
(installation **native**, sans Docker). **PostgreSQL peut rester en `localhost`** :
seule l'application du serveur y accède, il est donc inutile (et déconseillé) d'exposer
le port 5432 au réseau.

### 7.1 Créer le rôle applicatif et la base

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

### 7.2 Poser les variables d'environnement

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

### 7.3 Provisionner la base

Toujours dans le dossier du projet, **nouveau terminal** (pour hériter des variables) :

```powershell
.\.venv\Scripts\python.exe init_postgres.py
```

`init_postgres.py` est **idempotent** (relançable sans risque) et réalise :

1. crée la base cible si elle n'existe pas (via la base de maintenance `postgres`) ;
2. crée le schéma complet (tables à clé `SERIAL`) ;
3. sème les 29 réglages par défaut.

Sortie attendue :

```
Base « cvagent » créée.            (ou « déjà présente — conservée »)
Schéma créé + 29 réglages par défaut dans « cvagent ».
Prochaine étape : démarrer l'application et créer l'admin via /setup.
```

### 7.4 Démarrer et créer l'administrateur

```powershell
.\run_web.bat
```

Puis ouvrez `http://localhost:6060/setup` pour créer le premier compte admin, et
configurez IMAP / LLM / SMTP dans **Administration → Paramètres**.

> **Alternative en ligne de commande** : avec `CV_AGENT_DB_URL` posée, `python
> bootstrap.py` crée aussi l'admin directement dans PostgreSQL (le chemin SQLite est
> ignoré en mode PostgreSQL).

---

## 8. Exposition réseau (port applicatif 6060)

L'application écoute sur `0.0.0.0:6060` (`run_web.bat`, ou `start_web.bat` avec
`--workers 1` pour la tâche planifiée). Il faut ouvrir **ce port** au LAN — **jamais**
le 5432 si PostgreSQL est local.

```powershell
# Règle pare-feu restreinte au sous-réseau LAN (adapter le /24 à votre réseau)
New-NetFirewallRule -DisplayName "CV-Agent 6060 LAN" -Direction Inbound `
  -Protocol TCP -LocalPort 6060 -Action Allow -RemoteAddress 192.168.1.0/24
```

> Restreindre `-RemoteAddress` au sous-réseau (plutôt que « n'importe où ») limite
> l'exposition. Le trafic étant en HTTP clair, voir aussi [§12](#12-https--durcissement).

---

## 9. Postes clients

**Rien à installer.** Chaque poste RH ouvre simplement dans un navigateur :

```
http://192.168.1.10:6060
```

(remplacer par l'IP réelle du serveur). Aucune variable d'environnement, aucune
configuration IMAP, aucun accès direct à la base côté client.

---

## 10. Démarrage automatique au boot

> En **Docker**, préférez `--restart unless-stopped` (mode conteneur unique) ou
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

## 11. Modèle de sécurité des secrets

Les secrets sensibles — `imap.password`, `smtp.password`, `openrouter.api_key` — sont
**chiffrés au repos** dans la table `settings`, de façon transparente (les appelants
manipulent toujours le clair en mémoire). Deux formats coexistent (`secret_store.py`) :

| Format | Mécanisme | Portable ? | Quand |
|---|---|---|---|
| **`enc:v2:…`** | Fernet (AES-128-CBC + HMAC-SHA256), clé dérivée de `CV_AGENT_SECRET` par PBKDF2-HMAC-SHA256 (200 000 itérations) | ✅ Oui — déchiffrable par toute machine partageant le même `CV_AGENT_SECRET` | dès que `CV_AGENT_SECRET` est défini |
| **`enc:v1:…`** | DPAPI Windows, portée **machine** | ❌ Non — lié à la machine d'origine | quand `CV_AGENT_SECRET` est absent |
| (sans préfixe) | valeur « legacy » en clair | — | migrée automatiquement au démarrage |

Conséquences pour le déploiement :

- **En conteneur Docker** (Linux), DPAPI n'existe pas : `CV_AGENT_SECRET` est
  **obligatoire** pour chiffrer les secrets (`enc:v2`). Sans elle, ils seraient en clair.
- **Une valeur illisible** (mauvais/absent `CV_AGENT_SECRET`, ou blob DPAPI copié sur
  une autre machine) renvoie `""` — l'application traite cela comme « pas
  d'identifiants » et **ne plante pas**.
- **Sans `CV_AGENT_SECRET`**, les secrets chiffrés en DPAPI **ne suivent pas** si vous
  copiez `state.db` (ou basculez la base) vers une autre machine : il faudra les
  ressaisir. C'est pourquoi un déploiement partagé (Docker, ou PostgreSQL centralisé)
  doit poser `CV_AGENT_SECRET` (même valeur partout où l'app tourne).
- ⚠️ **Ne mettez jamais de vrais identifiants dans `config.yaml`** : ce fichier n'est
  qu'un gabarit de premier lancement, et il est **embarqué dans l'exe distribué**.
- ⚠️ **Ne versionnez jamais** `state.db`, `session.secret`, `cv_pdfs/`, `logs/`, `.env` —
  ils contiennent des données candidats et des secrets (déjà couverts par `.gitignore`).

---

## 12. HTTPS & durcissement

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
- Restreignez la règle pare-feu 6060 au strict sous-réseau nécessaire ([§8](#8-exposition-réseau-port-applicatif-6060)).

---

## 13. Construction de l'exécutable Windows

L'application se distribue en `.exe` autonome (PyInstaller, mode *onedir*).

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
  `web_core`, `matching_core`, `alerts_engine` et tous les `mod_*`). **Quand vous
  ajoutez un nouveau module top-level, ajoutez-le ici**, sinon l'exe plantera avec
  `ModuleNotFoundError`.
- **Après l'ajout de `cryptography`**, reconstruisez impérativement l'exe pour que la
  dépendance soit embarquée (PyInstaller la collecte automatiquement via son hook).
- Le `.exe` figé écrit ses données dans `%LOCALAPPDATA%\CV-Agent-Pro\` (base, logs,
  `cv_pdfs`, `session.secret`), jamais dans le dossier d'installation (lecture seule).

---

## 14. Configuration LLM : Ollama vs OpenRouter

Le fournisseur est un **choix de configuration** (`llm.provider`), pas un basculement
automatique. Réglé dans **Administration → Paramètres**.

| Fournisseur | À préparer côté déployeur |
|---|---|
| **Ollama** (local, recommandé) | Installer Ollama, télécharger le modèle (`ollama pull qwen2.5:14b`), vérifier qu'il écoute sur `http://localhost:11434`. En Docker : `ollama.host` = `http://host.docker.internal:11434`. 100 % local, aucune donnée envoyée. |
| **OpenRouter** (cloud) | Renseigner `openrouter.base_url`, `openrouter.model` et la clé API. La clé peut aussi venir de la variable d'environnement `OPENROUTER_API_KEY` (prioritaire sur la valeur stockée). ⚠️ Les CV sont alors envoyés au service cloud. |

Le classifieur et l'extracteur passent tous deux par la même fonction et attendent un
objet JSON en retour.

---

## 15. Sauvegarde & restauration

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

### SQLite

Copier à froid (application arrêtée) le fichier **`state.db`** et le dossier
**`cv_pdfs/`** (les PDF des candidats). En Docker, sauvegardez le volume `cvagent-data`.

### Où vivent les données

| Donnée | Emplacement (dev / sources) | Emplacement (exe figé) | Emplacement (Docker) |
|---|---|---|---|
| Base SQLite | `state.db` (dossier projet) | `%LOCALAPPDATA%\CV-Agent-Pro\state.db` | volume `cvagent-data` → `/data/state.db` |
| PDF des CV | `cv_pdfs/` | `%LOCALAPPDATA%\CV-Agent-Pro\cv_pdfs\` | volume `cvagent-data` → `/data/cv_pdfs/` |
| Journaux | `logs\agent.log` | `%LOCALAPPDATA%\CV-Agent-Pro\logs\agent.log` | volume `cvagent-data` → `/data/logs/` |
| Base PostgreSQL | serveur PG | serveur PG | volume `cvagent-db` |

> Toute écriture passe par `app_paths.data_path()` (piloté par `CV_AGENT_DATA_DIR` en
> conteneur) : jamais de chemin relatif brut, pour rester valide une fois figé en `.exe`
> ou dans un volume Docker.

En mode PostgreSQL, la base n'est plus dans `state.db` (elle est sur le serveur PG),
mais `cv_pdfs/` et `logs/` restent locaux au serveur applicatif — à sauvegarder aussi.

---

## 16. Invariants à respecter

- **Un seul worker uvicorn.** APScheduler et l'écriture base supposent un process
  unique (`start_web.bat` et le `Dockerfile` passent `--workers 1`). Ne montez pas à
  plusieurs workers.
- **Une seule instance qui relève l'IMAP.** Ne faites pas tourner deux serveurs
  applicatifs (ou deux conteneurs) qui relèvent la **même** boîte : ils dédoublonneraient
  mal et se disputeraient l'écriture. En architecture serveur unique, ce risque n'existe
  pas. Si vous multipliez les instances (déconseillé), désactivez le planificateur sur
  toutes sauf une (**Admin → Paramètres → planification désactivée**).
- **Règles SQL portables** (pour toute évolution du code) : placeholders `?`, token
  `{PK}`, `db.insert_returning_id(...)`, upserts `ON CONFLICT` — jamais de
  `cur.lastrowid` ni de `INSERT OR IGNORE/REPLACE` (SQLite-only).
- **Chemins via `app_paths.data_path()`** pour tout fichier écrit.

---

## 17. Exploitation courante

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

## 18. Dépannage

| Symptôme | Cause probable / résolution |
|---|---|
| Connexion PostgreSQL refusée / *password authentication failed* | Mot de passe mal **percent-encodé** dans `CV_AGENT_DB_URL` (encodez `@` en `%40`, etc. — voir [§7.2](#72-poser-les-variables-denvironnement)). Vérifiez aussi le rôle/mot de passe et que `pg_hba.conf` autorise la connexion. |
| `init_postgres.py` : *permission denied to create table* | Le rôle `cvagent` n'a pas les droits sur le schéma `public`. Rejouez `ALTER DATABASE cvagent OWNER TO cvagent;` puis `GRANT ALL ON SCHEMA public TO cvagent;`. |
| Les postes clients n'accèdent pas au serveur | Règle pare-feu 6060 absente / trop restrictive, ou l'app écoute sur `127.0.0.1` au lieu de `0.0.0.0`. Utilisez `run_web.bat` / `start_web.bat` (ou publiez `-p 6060:6060` en Docker). |
| Le port 6060 est déjà occupé | Un ancien process uvicorn tourne encore. `uninstall_autostart.ps1` tue le process sur 6060, ou repérez-le via `Get-NetTCPConnection -LocalPort 6060`. |
| Secrets « vides » après copie de `state.db` / en Docker | Blobs DPAPI (`enc:v1`) liés à l'ancienne machine, **ou** `CV_AGENT_SECRET` absent en conteneur. Posez `CV_AGENT_SECRET` (chiffrement portable `enc:v2`) et ressaisissez les secrets une fois. |
| L'exe plante avec `ModuleNotFoundError` | Module top-level manquant dans `hiddenimports` de `cv-agent.spec`. Ajoutez-le et reconstruisez. |
| L'exe ne trouve pas `cryptography` | Exe construit **avant** l'ajout de la dépendance. Reconstruisez (`build_exe.ps1`). |
| Variables d'environnement ignorées | `setx` n'affecte que les nouveaux processus : **rouvrez** le terminal (et redémarrez la tâche planifiée) après les avoir posées. |
| L'IA ne répond pas | Ollama non démarré / modèle non téléchargé, ou clé OpenRouter absente/invalide. En Docker, `ollama.host` doit pointer vers `host.docker.internal`. Voir `logs\agent.log`. |

---

## 19. Annexes

### 19.1 Variables d'environnement

| Variable | Rôle | Exemple |
|---|---|---|
| `CV_AGENT_DB_URL` | Bascule vers PostgreSQL. Absente ⇒ SQLite. Mot de passe **percent-encodé**. | `postgresql://cvagent:pw@localhost:5432/cvagent` |
| `CV_AGENT_SECRET` | (1) stabilise le cookie de session entre redémarrages ; (2) active le chiffrement portable des secrets (`enc:v2`). **Obligatoire en conteneur** ; requis aussi si plusieurs instances partagent une base. | `<64 hex générés>` (voir §7.2 / §5.2) |
| `CV_AGENT_DATA_DIR` | Force le dossier des données (base SQLite, `cv_pdfs`, `logs`). Utilisé en conteneur pour pointer vers un volume monté. | `/data` |
| `CV_AGENT_HTTPS_ONLY` | `1` ⇒ drapeau `Secure` sur le cookie (derrière un reverse-proxy TLS). | `1` |
| `POSTGRES_PASSWORD` | (docker-compose) mot de passe du rôle `cvagent` ; **alphanumérique** de préférence. | `MotDePasseAlphaNum123` |
| `OPENROUTER_API_KEY` | Clé cloud OpenRouter (prioritaire sur la valeur stockée en base). | `sk-or-…` |

### 19.2 Commandes utiles

```powershell
# Vérifier le backend actif et l'état PostgreSQL
.\.venv\Scripts\python.exe -c "import db; print(db.backend(), db.is_postgres())"

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

### 19.3 Checklist — déploiement Docker (recommandé)

- [ ] Docker Engine + Compose (ou Docker Desktop) installés
- [ ] `CV_AGENT_SECRET` généré
- [ ] `.env` créé à partir de `.env.example` (`CV_AGENT_SECRET` + `POSTGRES_PASSWORD` alphanumérique)
- [ ] `docker compose up -d` (ou `docker run` en mode SQLite)
- [ ] Conteneur *healthy* ; admin créé via `http://<hôte>:6060/setup`
- [ ] IMAP / LLM / SMTP configurés dans Administration → Paramètres
- [ ] `ollama.host` = `http://host.docker.internal:11434` (ou clé OpenRouter valide)
- [ ] Port **6060** accessible depuis les postes clients
- [ ] Sauvegarde planifiée (volume `cvagent-data` et, en compose, `pg_dump`)

### 19.4 Checklist — déploiement B natif (PostgreSQL centralisé)

- [ ] PostgreSQL 17 installé et démarré sur le serveur
- [ ] Rôle `cvagent` créé (LOGIN + CREATEDB), propriétaire de la base
- [ ] `CV_AGENT_SECRET` généré et posé (`setx /M`)
- [ ] `CV_AGENT_DB_URL` posée avec mot de passe **percent-encodé** (`setx /M`)
- [ ] Terminal rouvert (héritage des variables)
- [ ] `init_postgres.py` exécuté sans erreur (schéma + 29 réglages)
- [ ] Règle pare-feu **6060** ouverte au LAN (5432 **non** exposé)
- [ ] Application démarrée (`run_web.bat` ou tâche planifiée)
- [ ] Admin créé via `/setup` ; IMAP / LLM / SMTP configurés
- [ ] Ollama opérationnel (ou clé OpenRouter valide)
- [ ] Un poste client accède bien à `http://IP_SERVEUR:6060`
- [ ] Sauvegarde PostgreSQL planifiée (`pg_dump`)

---

*CV Agent Pro — manuel de déploiement. Pour l'utilisation quotidienne, voir
`MANUEL_UTILISATION.md` ; pour les conventions de code, voir `CLAUDE.md`.*
