# CV Agent Pro

> Outil RH de tri et d'extraction automatiques des CV reçus par email.
> Relève **toute boîte IMAP** (Gmail, Outlook/Office 365, OVH, Zoho, serveur interne…),
> détecte et extrait les CV par LLM, stocke les candidats en **PostgreSQL**, et sert un
> tableau de bord web français (FastAPI + Jinja + HTMX) pour l'équipe RH.

**100 % local** — aucune donnée ne quitte le réseau, sauf si le fournisseur LLM cloud
`openrouter` est explicitement choisi. **Déploiement via Docker uniquement.**

---

## Fonctionnalités

**Pipeline de traitement** (automatique toutes les 60 min, ou déclenché à la main) :

```
[IMAP] → [PDF/DOCX → texte] → [LLM : est-ce un CV ?] → [LLM : extraction structurée] → [PostgreSQL]
                                                                                              ↓
                                                                   [rangement des mails traités (option)]
```

**Modules ATS** (chacun dans son routeur `mod_*.py`) :

- 📊 **Tableau de bord** et **statistiques** (répartition par statut, métier, expérience…)
- 🔎 **Recherche** classique + **recherche IA** en langage naturel
- 💼 **Gestion des offres** d'emploi
- 🎯 **Matching IA** offre ↔ candidat (scoring 100 % local, déterministe, hors-ligne)
- 🔔 **Alertes** : un nouveau CV correspond fortement à une offre publiée
- 🧬 **Détection de doublons** de candidats
- 📝 **Notes internes** RH et **fiche de synthèse IA** par candidat
- 📎 **Gestion documentaire** (pièces jointes par candidat)
- ⚖️ **Comparaison** de 2 à 5 candidats côte à côte
- 📥 **Export Excel** à la demande
- 📁 **Rangement des mails traités** dans la boîte IMAP (automatique en fin de cycle ou à la demande)
- 🌐 **API REST** (matching, stats)

**Multi-utilisateur** : authentification email/mot de passe, rôles `admin` / `manager` / `rh` / `lecture`.

---

## Architecture

- **PostgreSQL est l'unique moteur de base** (source de vérité), défini par la variable
  d'environnement **`CV_AGENT_DB_URL` (obligatoire)**. `config.yaml` n'est qu'un *gabarit de
  premier lancement* ; au runtime toute la configuration vit dans la table `settings`, éditée
  via l'interface d'administration.
- **Toute boîte IMAP** est supportée via le réglage `imap.security` (`SSL` / `STARTTLS` / `None`) —
  pas seulement Gmail.
- **Rangement des mails traités** (optionnel, désactivé par défaut) : les mails **déjà analysés**
  sont déplacés dans la boîte IMAP — les CV vers `imap.move_folder_cv` (défaut *Traités*), les
  mails écartés vers `imap.move_folder_non_cv` (vide = laissés en place) ; les dossiers sont créés
  au besoin. Deux déclencheurs : automatique en fin de cycle si `imap.move_processed` est activé,
  ou bouton manuel (`POST /admin/settings/move-imap`). Le rapprochement se fait par **UID**, dans
  le dossier même qui les a produits. Hors de ce cas, la relève reste **strictement en lecture
  seule** (les mails ne sont même pas marqués « lus »).
- **Import de fichiers Outlook `.pst` / `.ost`** (page *Import Outlook*) : traitement ponctuel
  d'une archive Outlook, en plus de l'IMAP. Lecture via `libpff` (pypff, multiplateforme). Dépôt
  par upload ou chemin serveur (volume monté). Cette page a son **propre** rangement des traités,
  distinct de celui de l'IMAP : rapprochement par **Message-ID** (seule clé qui survit au passage
  d'une copie de fichier à la boîte Outlook vivante).
- **Fournisseur LLM au choix** (pas de bascule automatique) : Ollama (local) ou point d'accès
  compatible OpenAI (OpenRouter / Gemini / …), selon le réglage `llm.provider`.
- **Secrets chiffrés au repos** : `enc:v2:` (Fernet portable, clé dérivée de `CV_AGENT_SECRET`) —
  mots de passe IMAP/SMTP et clé API cloud. Un blob indéchiffrable donne `""`, jamais un crash.
- **Un seul worker uvicorn** (APScheduler + écriture base supposent un process unique).

Détails complets dans **[`CLAUDE.md`](CLAUDE.md)** (guide de contribution) et le
**[manuel utilisateur](MANUEL_UTILISATION.md)**.

---

## Prérequis

- **Docker** et **Docker Compose**
- Une boîte mail dédiée aux candidatures sur **n'importe quel serveur IMAP** ; selon le
  fournisseur (Gmail, Outlook…), un **mot de passe d'application** peut être requis
- Pour le LLM local : [Ollama](https://ollama.com) avec un modèle (ex. `qwen2.5:14b`),
  joignable depuis le conteneur — *ou* une clé API cloud si vous choisissez le fournisseur
  `openrouter`

---

## Installation

L'image conteneurise tout (aucune dépendance à installer sur l'hôte). Elle tourne sur
Windows / Linux / macOS. Les postes clients restent de simples navigateurs.

### Option 1 — « batteries incluses » (app + PostgreSQL) en une commande

```bash
cp .env.example .env      # puis renseignez CV_AGENT_SECRET et POSTGRES_PASSWORD
docker compose up -d
```

Générez le secret : `docker run --rm python:3.12-slim python -c "import secrets;print(secrets.token_hex(32))"`.
Le schéma et les réglages par défaut se créent automatiquement au 1er démarrage.

### Option 2 — image seule, contre un PostgreSQL existant

```bash
docker build -t cv-agent-pro:latest .
docker run -d --name cv-agent -p 6060:6060 --restart unless-stopped \
  -e CV_AGENT_SECRET=<hex_généré> \
  -e CV_AGENT_DB_URL=postgresql://cvagent:motdepasse@HOTE:5432/cvagent \
  -v cvagent-data:/data \
  cv-agent-pro:latest
```

Dans les deux cas : ouvrez `http://<hôte>:6060/setup` pour créer l'admin, puis
configurez IMAP/SMTP/LLM dans **Administration → Paramètres**. Les données métier
vivent dans PostgreSQL ; le volume `cvagent-data` ne porte que les fichiers (cv_pdfs, logs).

> **LLM** : le conteneur doit joindre Ollama. Régler `ollama.host` selon l'emplacement :
> `http://host.docker.internal:11434` (Ollama sur l'hôte, mappé par le `extra_hosts`
> du compose) ou `http://<IP_du_serveur>:11434` (Ollama sur une autre machine).
> Dans les deux cas, lancer Ollama avec `OLLAMA_HOST=0.0.0.0` pour qu'il accepte les
> connexions externes. Sinon, utiliser le fournisseur cloud OpenRouter.

---

## Configuration

Tout se règle depuis **Administration → Paramètres** dans l'interface (boîte IMAP, rangement des
mails traités, fournisseur LLM, SMTP, notifications, planification…). `config.yaml` ne sert qu'au
tout premier lancement et ne doit **jamais** contenir de vrais identifiants.

### Variables d'environnement

| Variable | Effet |
|---|---|
| `CV_AGENT_DB_URL` | **Obligatoire.** URL PostgreSQL (ex. `postgresql://cvagent:pw@host:5432/cvagent`). Fournie automatiquement par `docker compose`. Absente → l'application refuse de démarrer avec un message clair. |
| `CV_AGENT_SECRET` | **Obligatoire en conteneur.** Secret partagé : (1) stabilise le cookie de session, (2) active le chiffrement portable des secrets (`enc:v2:`), déchiffrable par toute instance partageant la même valeur. Requis dans tous les cas côté Linux/Docker (pas d'alternative type DPAPI). |
| `CV_AGENT_HTTPS_ONLY` | `1` pose le drapeau `Secure` sur le cookie de session (à activer derrière un reverse-proxy HTTPS). |
| `OPENROUTER_API_KEY` | Clé cloud (prioritaire sur la valeur stockée en base). |

### Déploiement serveur central (postes clients = navigateur)

Architecture : **un seul conteneur** de l'application tourne sur un poste « serveur » ; les
autres postes RH y accèdent via un **navigateur** — rien à installer côté client, aucune
configuration IMAP côté client. La relève IMAP, le pipeline LLM et le planificateur s'exécutent
**uniquement sur le serveur**. La « synchronisation » (bouton *Lancer maintenant*) déclenchée
depuis un client s'exécute donc sur le serveur.

**Sur le serveur** (PostgreSQL peut rester accessible uniquement au réseau Docker interne —
ne pas exposer 5432 au LAN) :

1. Lancer la pile complète :
   ```bash
   cp .env.example .env      # renseignez CV_AGENT_SECRET et POSTGRES_PASSWORD
   docker compose up -d
   ```
2. Ouvrir le port applicatif **6060** au LAN sur le pare-feu de l'hôte Docker.
3. Créer l'admin via `http://<ip-serveur>:6060/setup`, puis configurer IMAP/SMTP/LLM
   dans **Administration → Paramètres**.

**Sur les postes clients :** ouvrir `http://<ip-serveur>:6060` dans un navigateur.
Aucune installation, aucune variable, aucun accès IMAP côté client.

---

## Sécurité et confidentialité

- Traitement **100 % local** par défaut ; le seul cas où des données sortent du réseau est
  le choix explicite du fournisseur LLM cloud `openrouter`.
- Secrets chiffrés au repos : `enc:v2:` (Fernet portable via `CV_AGENT_SECRET`) — un blob
  indéchiffrable donne `""`, jamais un crash.
- Requêtes SQL exclusivement paramétrées ; auto-échappement Jinja activé ; limitation anti-force
  brute au login.
- ⚠️ **Ne versionnez jamais** `.env`, `session.secret`, `cv_pdfs/`, `logs/` — ils contiennent
  des secrets et des données personnelles de candidats. Ils sont déjà couverts par le
  [`.gitignore`](.gitignore). (Les données candidats vivent dans PostgreSQL, à sauvegarder via `pg_dump`.)

---

## Structure du projet

```
webapp.py            Application FastAPI (routes cœur + montage des modules)
web_core.py          Socle partagé des routeurs de modules ATS
mod_*.py             Routeurs des modules ATS (dashboard, jobs, matching, alertes…)
web_pipeline.py      Orchestration d'un cycle du pipeline
mail_fetcher.py      Relève IMAP + rangement des mails traités
pdf_extractor.py     PDF/DOCX → texte
llm_classifier.py    Détection « est-ce un CV ? »
llm_extractor.py     Extraction structurée
llm_provider.py      Dispatch Ollama / cloud (compatible OpenAI)
matching_core.py     Scoring déterministe offre ↔ candidat
alerts_engine.py     Moteur d'alertes
db.py                Adaptateur PostgreSQL (connect(), insert_returning_id)
state_db.py          Schéma, connexion, idempotence (dédup IMAP, compteur d'ids, processed_uids)
web_db.py            Utilisateurs / candidats / réglages / cycles
secret_store.py      Chiffrement des secrets au repos (enc:v2 Fernet)
static/style.css     Thème clair/sombre — palette de marque Rayanox (jetons CSS)
```

> Il n'y a **pas** de suite de tests automatisés : on valide en lançant un vrai cycle
> (`python main.py`, avec `CV_AGENT_DB_URL` défini) sur la boîte configurée, ou en exerçant
> un module directement. Voir `logs\agent.log` pour la sortie du pipeline.

---

## Licence

Projet privé — usage interne. Tous droits réservés.
