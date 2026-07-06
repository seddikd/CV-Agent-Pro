# CV Agent Pro

> Outil RH **local, mono-poste** de tri et d'extraction automatiques des CV reçus par email.
> Relève une boîte Gmail en IMAP, détecte et extrait les CV par LLM, stocke les candidats en
> SQLite, et sert un tableau de bord web français (FastAPI + Jinja + HTMX) pour l'équipe RH.

**100 % local** — aucune donnée ne quitte la machine, sauf si le fournisseur LLM cloud
`openrouter` est explicitement choisi. Livré en exécutable Windows (`.exe` : uvicorn sur la
boucle locale + icône de la zone de notification).

---

## Fonctionnalités

**Pipeline de traitement** (automatique toutes les 60 min, ou déclenché à la main) :

```
[IMAP] → [PDF/DOCX → texte] → [LLM : est-ce un CV ?] → [LLM : extraction structurée] → [SQLite]
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
- 🌐 **API REST** (matching, stats)

**Multi-utilisateur** : authentification email/mot de passe, rôles `admin` / `manager` / `rh` / `lecture`.

---

## Architecture

- **SQLite (`state.db`) est l'unique source de vérité.** `config.yaml` n'est qu'un *gabarit de
  premier lancement* ; au runtime toute la configuration vit dans la table `settings`, éditée
  via l'interface d'administration.
- **Backend base configurable.** SQLite par défaut (local, packagé, testé) ; PostgreSQL en option
  via la variable d'environnement `CV_AGENT_DB_URL` (déploiement centralisé multi-postes).
- **Fournisseur LLM au choix** (pas de bascule automatique) : Ollama (local) ou point d'accès
  compatible OpenAI (OpenRouter / Gemini / …), selon le réglage `llm.provider`.
- **Secrets chiffrés au repos** (Windows DPAPI, portée machine) : mots de passe IMAP/SMTP et clé
  API cloud.
- **Un seul worker uvicorn** (APScheduler + écriture SQLite supposent un process unique).

Détails complets dans **[`CLAUDE.md`](CLAUDE.md)** (guide de contribution) et le
**[manuel utilisateur](MANUEL_UTILISATION.md)**.

---

## Prérequis

- Windows 10/11, Python 3.11+
- Une boîte Gmail dédiée aux candidatures + un **mot de passe d'application** (IMAP activé)
- Pour le LLM local : [Ollama](https://ollama.com) avec un modèle (ex. `qwen2.5:14b`)
  — *ou* une clé API cloud si vous choisissez le fournisseur `openrouter`

---

## Installation (développement)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python bootstrap.py           # init BD, réglages par défaut, 1er admin (interactif)
```

## Démarrage

```powershell
# Application web (dev, exposée sur le LAN, port 6060)
.\run_web.bat                 # == python -m uvicorn webapp:app --host 0.0.0.0 --port 6060

# Application bureau (boucle locale + systray, comme l'exe livré)
python desktop.py

# Un seul cycle de pipeline depuis la CLI (debug d'une passe relève/classif/extraction)
python main.py
```

Puis ouvrez `http://localhost:6060` (ou `http://<ip-machine>:6060` depuis un autre poste du LAN)
et connectez-vous avec le compte admin créé au bootstrap.

## Construire l'exécutable Windows

```powershell
pyinstaller cv-agent.spec --noconfirm     # onedir -> dist\CV-Agent\
.\build_installer.ps1                      # installeur Inno Setup + régénère le manuel PDF
```

---

## Configuration

Tout se règle depuis **Administration → Paramètres** dans l'interface (boîte IMAP, fournisseur
LLM, SMTP, notifications, planification…). `config.yaml` ne sert qu'au tout premier lancement et
ne doit **jamais** contenir de vrais identifiants (il est embarqué dans l'exe distribué).

### Variables d'environnement optionnelles

| Variable | Effet |
|---|---|
| `CV_AGENT_DB_URL` | Bascule vers PostgreSQL (ex. `postgresql://user:pw@host:5432/cvagent`). Absente → SQLite. |
| `CV_AGENT_SECRET` | Secret partagé : (1) stabilise le cookie de session, (2) **active le chiffrement portable des secrets** (`enc:v2:`) déchiffrable par tous les postes qui partagent la même valeur. Obligatoire pour un déploiement PostgreSQL multi-postes. |
| `CV_AGENT_HTTPS_ONLY` | `1` pose le drapeau `Secure` sur le cookie de session (à activer derrière un reverse-proxy HTTPS). |
| `OPENROUTER_API_KEY` | Clé cloud (prioritaire sur la valeur stockée en base). |

### Déploiement multi-postes (PostgreSQL partagé)

Pour que plusieurs postes RH partagent une **même base centralisée** :

1. Installer PostgreSQL sur un serveur du réseau, créer une base `cvagent`.
2. Générer **une** valeur secrète partagée :
   `python -c "import secrets; print(secrets.token_hex(32))"`
3. Sur **chaque** poste, définir les **deux** variables (identiques partout ;
   `/M` = niveau machine, requiert une invite admin) :
   ```powershell
   setx /M CV_AGENT_DB_URL "postgresql://user:pw@SERVEUR:5432/cvagent"
   setx /M CV_AGENT_SECRET "<la_valeur_générée_à_l_étape_2>"
   ```
4. Provisionner la base **une fois** (crée base + schéma + réglages par défaut) :
   ```powershell
   .\.venv\Scripts\python.exe init_postgres.py
   ```
5. Au premier démarrage, créer l'admin via `/setup` puis saisir les réglages
   (IMAP, SMTP, clé API) dans **Administration → Paramètres**. Les secrets sont
   alors chiffrés en `enc:v2:` (portable) et lisibles depuis tous les postes.

> ⚠️ Sans `CV_AGENT_SECRET`, les secrets sont chiffrés en DPAPI **lié à la machine**
> et ne se déchiffrent que sur le poste d'origine — à réserver au mono-poste.

---

## Sécurité et confidentialité

- Traitement **100 % local** par défaut ; le seul cas où des données sortent de la machine est
  le choix explicite du fournisseur LLM cloud `openrouter`.
- Secrets chiffrés au repos (DPAPI, liés à la machine) : une copie de `state.db` ne peut pas être
  déchiffrée ailleurs.
- Requêtes SQL exclusivement paramétrées ; auto-échappement Jinja activé ; limitation anti-force
  brute au login.
- ⚠️ **Ne versionnez jamais** `state.db`, `session.secret`, `cv_pdfs/`, `logs/` — ils contiennent
  des données personnelles de candidats et des secrets. Ils sont déjà couverts par le
  [`.gitignore`](.gitignore).

---

## Structure du projet

```
webapp.py            Application FastAPI (routes cœur + montage des modules)
web_core.py          Socle partagé des routeurs de modules ATS
mod_*.py             Routeurs des modules ATS (dashboard, jobs, matching, alertes…)
web_pipeline.py      Orchestration d'un cycle du pipeline
mail_fetcher.py      Relève IMAP
pdf_extractor.py     PDF/DOCX → texte
llm_classifier.py    Détection « est-ce un CV ? »
llm_extractor.py     Extraction structurée
llm_provider.py      Dispatch Ollama / cloud (compatible OpenAI)
matching_core.py     Scoring déterministe offre ↔ candidat
alerts_engine.py     Moteur d'alertes
db.py                Abstraction SQLite / PostgreSQL
state_db.py          Schéma, connexion, idempotence (dédup IMAP, compteur d'ids)
web_db.py            Utilisateurs / candidats / réglages / cycles
secret_store.py      Chiffrement des secrets au repos (DPAPI)
app_paths.py         Résolution des chemins (compatible exe figé)
desktop.py           Point d'entrée PyInstaller (systray + uvicorn loopback)
```

> Il n'y a **pas** de suite de tests automatisés : on valide en lançant un vrai cycle
> (`python main.py`) sur la boîte configurée, ou en exerçant un module directement.
> Voir `logs\agent.log` pour la sortie du pipeline.

---

## Licence

Projet privé — usage interne. Tous droits réservés.
