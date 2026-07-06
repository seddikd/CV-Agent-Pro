# Manuel d'utilisation — Agent CV Email (interface web)

> Solution locale d'automatisation du tri et de l'extraction des CV reçus par email vers une base SQLite consultable via une **interface web multi-utilisateur**, avec export Excel à la demande. Pipeline IA local via Ollama (aucun envoi de données cloud).

---

## Table des matières

1. [Présentation](#1-présentation)
2. [Architecture et fonctionnement](#2-architecture-et-fonctionnement)
3. [Prérequis](#3-prérequis)
4. [Installation des dépendances Python](#4-installation-des-dépendances-python)
5. [Configuration Gmail (boîte source)](#5-configuration-gmail-boîte-source)
6. [Configuration Ollama (LLM)](#6-configuration-ollama-llm)
7. [Bootstrap initial (1ère fois)](#7-bootstrap-initial-1ère-fois)
8. [Démarrage du serveur web et 1ère connexion](#8-démarrage-du-serveur-web-et-1ère-connexion)
9. [Démarrage automatique au boot Windows](#9-démarrage-automatique-au-boot-windows)
10. [Utiliser l'interface web (rôle RH)](#10-utiliser-linterface-web-rôle-rh)
11. [Administration (rôle admin)](#11-administration-rôle-admin)
12. [Export Excel](#12-export-excel)
13. [Mode CLI (debug / batch)](#13-mode-cli-debug--batch)
14. [Maintenance et logs](#14-maintenance-et-logs)
15. [Dépannage](#15-dépannage)
16. [Sécurité et confidentialité](#16-sécurité-et-confidentialité)
17. [FAQ](#17-faq)
18. [Limites connues et évolutions possibles](#18-limites-connues-et-évolutions-possibles)
19. [Annexes — commandes utiles](#19-annexes--commandes-utiles)

---

## 1. Présentation

### Objectif

Automatiser le traitement des candidatures reçues par email pour une **équipe RH** :

1. Polling automatique d'une boîte mail Gmail (toutes les 60 min par défaut)
2. Détection IA des emails contenant un CV
3. Extraction structurée des champs (nom, email, compétences, etc.)
4. Stockage dans une base SQLite locale
5. Consultation et édition via une **interface web LAN** (3-5 utilisateurs)
6. Export Excel à la demande

**100% local** : aucune donnée envoyée à un service cloud, aucun abonnement IA.

### Public cible

Équipes RH de 3-5 personnes accédant à une boîte mail partagée de candidatures, sur un même réseau local (LAN).

### Différence avec la v1 CLI

| Aspect | v1 CLI | v2 Web (actuelle) |
|---|---|---|
| Utilisateurs | 1 (toi) | 3-5 (équipe RH) |
| Interface | Excel ouvert dans LibreOffice/Excel | Navigateur web |
| Configuration | Édition de `config.yaml` | Page Admin → Paramètres |
| Polling | Tâche planifiée Windows | APScheduler dans le serveur web |
| Stockage | Excel + SQLite (état) | SQLite (source de vérité) |
| Excel | Source d'écriture | Export à la demande |
| Authentification | aucune | login email/mot de passe |
| Rôles | aucun | `admin` + `rh` |

---

## 2. Architecture et fonctionnement

### Schéma général

```
┌────────────────────────────────────────────────────────────┐
│              SERVEUR FastAPI (port 6060)                   │
│              tourne sur ta machine Windows                 │
│                                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Routes web   │  │ APScheduler  │  │ Pipeline IA      │  │
│  │ (Jinja2 +    │  │ (cycle 60min)│  │ (IMAP+Ollama)    │  │
│  │  HTMX)       │  │              │  │                  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                   │            │
│         └─────────────────┼───────────────────┘            │
│                           ▼                                │
│                    ┌─────────────┐                         │
│                    │  SQLite     │ ◄─── source de vérité   │
│                    │  state.db   │                         │
│                    └──────┬──────┘                         │
│                           │                                │
│                           ▼                                │
│                  ┌───────────────────┐                     │
│                  │ Export Excel      │                     │
│                  │ candidats.xlsx    │                     │
│                  └───────────────────┘                     │
└────────────────────────────────────────────────────────────┘
        ▲                          ▲                          ▲
        │                          │                          │
   RH 1 navigateur          RH 2 navigateur            Admin RH
   192.168.x.10:6060        192.168.x.11:6060          192.168.x.12:6060
```

### Pipeline de traitement (par cycle, automatique ou manuel)

```
[IMAP fetch] ──► [Pré-filtre PDF/DOCX] ──► [Extraction texte]
                                                  │
                                                  ▼
                                       [LLM #1 : Est-ce un CV ?]
                                                  │
                              ┌───────────────────┴────────┐
                              ▼                            ▼
                       non / faible                  oui (≥ seuil)
                              │                            │
                              ▼                            ▼
                    Marque comme traité     [LLM #2 : Extraction JSON]
                                                          │
                                                          ▼
                                                  Insert SQLite
                                                  Sauvegarde PDF
                                                  Marque traité
```

### Structure des fichiers

```
D:\clab-labs\cv-agent\
│
├── webapp.py                 # 🌐 App FastAPI (point d'entrée principal)
├── web_db.py                 #    Helpers SQLite : users, candidats, settings, runs
├── web_auth.py               #    bcrypt + sessions
├── web_pipeline.py           #    Pipeline IA (écrit en SQLite)
├── excel_export.py           #    Export Excel à la demande
├── bootstrap.py              # 🔧 Setup initial (1 fois)
│
├── main.py                   #    CLI : 1 cycle manuel (debug)
├── mail_fetcher.py           #    IMAP
├── pdf_extractor.py          #    PDF/DOCX → texte
├── llm_classifier.py         #    Ollama : classification
├── llm_extractor.py          #    Ollama : extraction JSON
├── state_db.py               #    Schéma SQLite + helpers bas niveau
│
├── start_web.bat             #    Lancement silencieux pour autostart
├── run_web.bat               #    Lancement interactif (debug)
├── install_autostart.ps1     #    Installe la tâche planifiée + pare-feu
├── uninstall_autostart.ps1   #    Désinstalle
│
├── requirements.txt
├── config.yaml               #    (legacy) graine pour bootstrap
├── MANUEL_UTILISATION.md     # 📖 Ce document
├── MANUEL_UTILISATION.pdf    #    Version imprimable
├── build_pdf.py              #    Regénère le PDF du manuel
│
├── state.db                  # 🔒 Base SQLite (TOUT y est)
├── cv_pdfs\                  # 📄 CVs téléchargés (référencés en DB)
├── logs\
│   ├── agent.log             #    Pipeline
│   └── web_startup.log       #    Démarrage du service
├── output\
│   └── candidats_*.xlsx      # 📊 Exports Excel à la demande
├── templates\                #    7 templates Jinja2
└── static\                   #    CSS
```

### Tables SQLite

| Table | Rôle |
|---|---|
| `users` | Comptes RH + admin (bcrypt) |
| `candidates` | Tous les CV détectés + statuts/commentaires |
| `settings` | Configuration éditable via l'UI |
| `runs` | Historique des cycles d'exécution |
| `processed_emails` | UIDs déjà traités (idempotence) |
| `candidate_counter` | Compteur d'ID incrémental |

---

## 3. Prérequis

### Matériel recommandé

| Composant | Recommandé | Cette machine |
|---|---|---|
| CPU | 8+ cœurs | i7-13xxxxx ✅ |
| RAM | 32 GB | 32 GB DDR5 ✅ |
| GPU | NVIDIA 8 GB+ VRAM | RTX 4060 8 GB ✅ |
| Stockage | 50 GB libres | — |
| OS | Windows 10/11 | Windows 11 Pro ✅ |
| Réseau | LAN câblé ou WiFi stable | — |

### Logiciels requis

- **Python 3.10+** (installé : 3.13.9 ✅)
- **Ollama** + modèle `qwen2.5:7b` (~5 GB)
- **Compte Gmail** avec 2FA activée

### Réseau

- Port **6060/TCP** ouvert en *Inbound* (le script `install_autostart.ps1` le fait automatiquement)
- IP de la machine accessible aux autres postes du LAN (idéalement IP fixe ou réservation DHCP)

---

## 4. Installation des dépendances Python

> Toutes les commandes ci-dessous se lancent dans **PowerShell**.

### Étape 1 — Créer l'environnement virtuel

```powershell
cd D:\clab-labs\cv-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> 💡 Si erreur "*l'exécution de scripts est désactivée*" :
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

Tu dois voir `(.venv)` en début de prompt.

### Étape 2 — Installer toutes les dépendances

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

Cela installe :
- `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (web)
- `bcrypt`, `itsdangerous` (auth)
- `apscheduler` (planificateur intégré)
- `imap-tools`, `ollama`, `pypdf`, `python-docx`, `openpyxl`, `PyYAML` (pipeline)

Vérification :
```powershell
pip list | findstr /I "fastapi uvicorn bcrypt apscheduler"
```

---

## 5. Configuration Gmail (boîte source)

Gmail n'autorise plus les mots de passe normaux en IMAP. Il faut un **mot de passe d'application**.

### Étape 1 — Activer la 2FA

1. https://myaccount.google.com/security
2. Section "Connexion à Google" → **Validation en deux étapes** → activer

### Étape 2 — Générer un mot de passe d'application

1. https://myaccount.google.com/apppasswords
2. Nom : `CV Agent Local`
3. **Créer** → copie immédiatement le mot de passe 16 caractères (`abcd efgh ijkl mnop`)

### Étape 3 — Activer IMAP dans Gmail

1. Gmail → ⚙️ Paramètres → **Voir tous les paramètres**
2. Onglet **Transfert et POP/IMAP**
3. **Activer IMAP** → **Enregistrer**

### Étape 4 — Test de connectivité

```powershell
Test-NetConnection imap.gmail.com -Port 993
```
Tu dois voir `TcpTestSucceeded : True`.

> ⚠️ Tu **n'as pas besoin** de mettre ces identifiants dans un fichier de config. Tu les saisiras dans l'interface web (page Admin → Paramètres) à l'étape 8.

---

## 6. Configuration Ollama (LLM)

### Étape 1 — Télécharger le modèle recommandé

Pour RTX 4060 8 GB :

```powershell
ollama pull qwen2.5:7b
```

(~4.7 GB de téléchargement.)

### Étape 2 — Vérifier

```powershell
ollama list
```

Tu dois voir `qwen2.5:7b`.

### Étape 3 — Test

```powershell
ollama run qwen2.5:7b "Réponds en JSON: {\"status\":\"ok\"}"
```

Réponse en quelques secondes = ✅.

### Étape 4 — Vérifier l'API

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

> ⚠️ Ollama doit tourner **avant** le serveur web. Vérifie qu'il est lancé au démarrage Windows (par défaut oui via l'application Ollama).

---

## 7. Bootstrap initial (1ère fois)

Le script `bootstrap.py` :
1. Initialise les tables SQLite
2. Insère les paramètres par défaut
3. Importe les valeurs de `config.yaml` si présentes
4. Te demande de créer le **1er compte administrateur**

```powershell
cd D:\clab-labs\cv-agent
.\.venv\Scripts\Activate.ps1
python bootstrap.py
```

Tu seras prompté pour :
```
Email admin : ton.email@boite.com
Nom complet : Khalil Admin
Mot de passe (min 8 chars) : ********
Confirmation             : ********
```

Sortie attendue :
```
[✓] Paramètres importés depuis config.yaml
[✓] Admin créé (id=1, email=ton.email@boite.com)
>>> Bootstrap terminé.
```

> ⚠️ Le bootstrap est **idempotent** : tu peux le relancer sans risque. Si un admin existe déjà, l'étape "création admin" est sautée.

---

## 8. Démarrage du serveur web et 1ère connexion

### Lancement manuel (mode interactif, pour la 1ère fois)

```powershell
.\run_web.bat
```

Tu dois voir :

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
2026-06-28 14:00:00 | INFO    | cv_agent.web | Scheduler armed (every 60 min)
2026-06-28 14:00:00 | INFO    | cv_agent.web | Web app started
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:6060
```

### 1ère connexion

Dans ton navigateur, va sur :
```
http://localhost:6060
```

Tu arrives sur la **page de login**. Connecte-toi avec le compte admin créé à l'étape 7.

### Saisir les identifiants Gmail dans l'UI

1. Menu → **Paramètres**
2. Remplis :
   - `imap.user` : `ton.email@gmail.com`
   - `imap.password` : ton mot de passe d'application 16 caractères (**sans espaces**)
3. Vérifie que `ollama.model` = `qwen2.5:7b`
4. Clique **💾 Enregistrer**

### Test du 1er cycle

1. Menu → **Cycles** (ou page d'accueil)
2. Clique **▶ Lancer un cycle maintenant**
3. Tu es redirigé vers `/admin/runs` avec le message *"Cycle déclenché"*
4. Rafraîchis la page après 1-2 minutes → le statut passe de `running` à `success`

Va voir le **Dashboard** : tu dois voir les premiers candidats.

> 💡 Pour limiter le 1er test, va dans Paramètres et mets `processing.fetch_since_days = 7` (ou `1`).

---

## 9. Démarrage automatique au boot Windows

Quand tout fonctionne en lancement manuel, configure le démarrage automatique :

### Étape 1 — Lancer le script d'installation

Ouvre **PowerShell en administrateur** (clic droit → Exécuter en tant qu'administrateur).

```powershell
powershell -ExecutionPolicy Bypass -File D:\clab-labs\cv-agent\install_autostart.ps1
```

Le script :
1. Vérifie que `.venv` et `start_web.bat` existent
2. Te demande le **compte Windows** sous lequel tourner (par défaut : ton compte courant)
3. Te demande le **mot de passe Windows** de ce compte (pour que la tâche tourne sans session ouverte)
4. Enregistre la tâche planifiée `CV-Agent-Web` qui démarre 1 min après chaque boot
5. Ouvre le **port 6060** dans le pare-feu Windows (profils Domain + Private)
6. Affiche les URLs LAN d'accès

Exemple de sortie :
```
[OK] Tâche planifiée installée : CV-Agent-Web
[OK] Règle pare-feu inbound TCP 6060 ouverte
=== Installation terminée ===

Accès depuis le LAN :
  http://192.168.1.50:6060
```

### Étape 2 — Démarrer sans rebooter

```powershell
Start-ScheduledTask -TaskName "CV-Agent-Web"
```

Vérifie l'état :
```powershell
Get-ScheduledTask -TaskName "CV-Agent-Web" | Get-ScheduledTaskInfo
```

Le champ `LastTaskResult` doit être `0`.

### Étape 3 — Tester l'accès depuis un autre poste

Sur un autre PC du LAN, ouvrir un navigateur et aller sur :
```
http://<ip-de-la-machine-serveur>:6060
```

Tu dois voir la page de login.

### Désinstallation

```powershell
powershell -ExecutionPolicy Bypass -File D:\clab-labs\cv-agent\uninstall_autostart.ps1
```

Cela supprime la tâche, la règle de pare-feu, et tue les processus restants sur le port 6060.

> ⚠️ **Mot de passe Windows** : il est stocké de manière chiffrée dans la planification. Si tu changes ton mot de passe Windows plus tard, tu dois relancer `install_autostart.ps1`.

> ⚠️ **Ollama doit aussi démarrer au boot** (c'est le cas par défaut si tu as installé Ollama avec l'option "Start on boot"). Vérifie sinon dans les paramètres d'Ollama.

---

## 10. Utiliser l'interface web (rôle RH)

### Page d'accueil — Dashboard

```
┌─────────────────────────────────────────────────────────────┐
│ 📨 CV Agent  Candidats  Cycles    👤 Marie (rh) Se déconnecter│
├─────────────────────────────────────────────────────────────┤
│ Candidats                              ▶ Lancer  📥 Excel   │
│                                                             │
│ [42 au total]  [Nouveau : 18]  [À contacter : 9]  ...       │
│ Dernier cycle réussi : 2026-06-28 14:32 (3 CV)              │
│                                                             │
│ [🔍 Rechercher...] [Statut ▼] [Poste...] [Filtrer]          │
│                                                             │
│ ID │ Reçu    │ Candidat       │ Poste     │ Exp │ Skills │ Statut │
│ 12 │ 28/06   │ Dupont Jean    │ Dev FS    │  5  │ React… │ Nouveau ▼ │
│ 11 │ 28/06   │ Martin Sophie  │ Data      │  3  │ Python │ À contacter ▼ │
│  9 │ 27/06   │ Petit Rémi     │ Dev FS    │  8  │ Java…  │ Entretien ▼ │
└─────────────────────────────────────────────────────────────┘
```

#### Actions disponibles

| Action | Comment |
|---|---|
| **Filtrer** | Champs en haut : recherche libre (nom/email/compétence), statut, poste |
| **Changer un statut** | Clic sur le menu déroulant dans la colonne Statut — sauvegarde **immédiate** (HTMX, pas de rechargement) |
| **Ouvrir une fiche** | Clic sur le nom du candidat ou bouton "Voir" |
| **Lancer un cycle** | Bouton ▶ en haut à droite (utile sans attendre le polling 60 min) |
| **Exporter Excel** | Bouton 📥 → télécharge un fichier `candidats_AAAAMMJJ_HHMM.xlsx` |

#### Statuts disponibles

- `Nouveau` (par défaut)
- `À contacter`
- `Entretien planifié`
- `Refusé`
- `Embauché`
- `Doublon`

### Page candidat

Ouverte en cliquant sur un nom. Affiche :

- **Carte gauche** : tous les champs extraits du CV + formulaire d'édition (statut + commentaires)
- **Carte droite** : aperçu du **PDF embarqué** (iframe)

```
┌──────────────────────────────┬──────────────────────────────┐
│ Sophie Martin   [À contacter]│                              │
│ Candidature reçue le 28/06   │                              │
│                              │                              │
│ Expéditeur : sophie@xx.com   │      [APERÇU PDF DU CV]      │
│ Téléphone  : 06 12 34 56 78  │                              │
│ Poste      : Data Engineer   │                              │
│ Expérience : 3 ans           │                              │
│ Diplôme    : Master ENSEIRB  │                              │
│ Compétences: Python, SQL...  │                              │
│ Langues    : FR, EN, ES      │                              │
│ Résumé     : Profil junior...│                              │
│ Fichier    : id0042_sm.pdf   │                              │
│                              │                              │
│ ── Édition ──                │                              │
│ Statut : [À contacter ▼]     │                              │
│ Commentaires RH :            │                              │
│ ┌──────────────────────────┐ │                              │
│ │ À recontacter mi-juillet │ │                              │
│ │ après son entretien chez │ │                              │
│ │ X. Profil solide.        │ │                              │
│ └──────────────────────────┘ │                              │
│ [💾 Enregistrer]             │                              │
└──────────────────────────────┴──────────────────────────────┘
```

### Page "Cycles"

Liste les 50 derniers cycles avec :
- ID
- Heure de démarrage et de fin
- Source (`scheduler` = automatique, `manual` = bouton, `cli` = main.py)
- Nombre d'emails lus, CV détectés
- Statut (`success`, `failed`, `running`)
- Message d'erreur si échec

Bouton **▶ Lancer un cycle maintenant** en haut.

---

## 11. Administration (rôle admin)

Le menu top affiche **Utilisateurs** et **Paramètres** uniquement pour les rôles `admin`.

### Gestion des utilisateurs (`/admin/users`)

```
➕ Créer un utilisateur
[email] [nom complet] [mot de passe] [rôle ▼] [Créer]

────────────────────────────────────────
Email             Édition
admin@xx.com     [Nom...] [admin ▼] [actif ▼] [MdP...] [💾 Modifier]
                                              [🗑 Supprimer]
marie@xx.com     [Marie ] [rh    ▼] [actif ▼] [MdP...] [💾]  [🗑]
pierre@xx.com    [Pierre] [rh    ▼] [désact▼] [MdP...] [💾]  [🗑]
```

#### Création d'un compte

1. Remplis email + nom + mot de passe + rôle
2. Clique **Créer**
3. Communique les identifiants à la personne par un canal sécurisé (en personne, signal, etc. — pas par email non chiffré)

#### Modification

- Tu peux changer le **nom**, le **rôle** et l'**actif** ligne par ligne.
- Pour changer le mot de passe : remplis le champ, sinon laisse vide.
- Clique **💾 Modifier**.

#### Suppression

- Bouton **🗑 Supprimer** avec confirmation.
- **Garde-fou** : impossible de supprimer son propre compte ou le dernier admin actif.

#### Rôles

| Rôle | Peut consulter | Peut éditer statut/commentaires | Peut administrer |
|---|---|---|---|
| `rh` | ✅ | ✅ | ❌ |
| `admin` | ✅ | ✅ | ✅ |

### Paramètres système (`/admin/settings`)

Tous les paramètres éditables depuis l'UI (pas de fichier YAML à toucher) :

| Paramètre | Description |
|---|---|
| `imap.host`, `imap.port`, `imap.user`, `imap.password`, `imap.folder` | Identifiants IMAP |
| `ollama.model`, `ollama.host`, `ollama.timeout_seconds` | Config Ollama |
| `processing.max_emails_per_run` | Plafond par cycle |
| `processing.classification_confidence_threshold` | Seuil 0-1 pour qu'un email soit considéré CV |
| `processing.pdf_max_chars` | Limite de chars envoyés au LLM |
| `processing.fetch_since_days` | Profondeur historique IMAP (jours) |
| `scheduler.interval_minutes` | Intervalle automatique (par défaut : 60) |
| `scheduler.enabled` | `true` ou `false` |

> 💡 Modifier `scheduler.interval_minutes` **re-planifie automatiquement** le job (pas de redémarrage requis).

> ⚠️ Pour `imap.password` : si tu laisses le champ vide, l'ancien mot de passe est conservé. Si tu mets une nouvelle valeur, elle remplace. Les mots de passe et la clé API sont **chiffrés au repos** dans `state.db` (cf. [§16 Sécurité](#16-sécurité-et-confidentialité)).

### Historique des cycles (`/admin/runs`)

Visible aussi par les rôles `rh` (lecture seule).
- Tableau des 50 derniers cycles
- Indication "cycle en cours" si actif
- Bouton **▶ Lancer un cycle maintenant**

---

## 12. Export Excel

### Génération à la demande

Depuis le Dashboard, bouton **📥 Exporter Excel**. Télécharge immédiatement :
```
candidats_20260628_1432.xlsx
```

### Colonnes générées

| # | Colonne | Source |
|---|---|---|
| 1 | ID | DB |
| 2 | Date de réception | DB |
| 3 | Heure de réception | DB |
| 4 | Expéditeur | header email |
| 5 | Nom | LLM |
| 6 | Prénom | LLM |
| 7 | Email | LLM (CV) |
| 8 | Téléphone | LLM |
| 9 | Poste recherché | LLM |
| 10 | Années d'expérience | LLM |
| 11 | Diplôme le plus élevé | LLM |
| 12 | Compétences principales | LLM (CSV) |
| 13 | Langues | LLM (CSV) |
| 14 | Résumé du CV | LLM |
| 15 | Nom du fichier PDF | auto |
| 16 | Chemin du PDF | auto |
| 17 | Statut | DB (modifiable web) |
| 18 | Commentaires RH | DB (modifiable web) |

### À savoir

- L'export est **un instantané** : les modifications faites dans Excel ne remontent **pas** dans la DB
- **Les statuts/commentaires faisant foi sont ceux du web**
- Pour distribuer un export aux managers, génère-le juste avant l'envoi
- Aucun fichier Excel n'est conservé sur disque (sauf si tu l'enregistres) — chaque clic = nouveau fichier

---

## 13. Mode CLI (debug / batch)

Le script `main.py` reste disponible pour des cas spécifiques :

```powershell
cd D:\clab-labs\cv-agent
.\.venv\Scripts\Activate.ps1
python main.py
```

Il lit la configuration depuis **SQLite** (plus depuis `config.yaml`), lance **1 cycle** et termine. Utile pour :
- Tester rapidement sans l'UI (debug d'un mail particulier)
- Forcer un cycle depuis un script externe
- Reprendre après une coupure si le service web a crashé

> 💡 La CLI utilise le même pipeline que le web — pas de comportement divergent.

---

## 14. Maintenance et logs

### Fichiers de log

| Fichier | Contenu |
|---|---|
| `logs\agent.log` | Pipeline (fetch, classify, extract) |
| `logs\web_startup.log` | Démarrage du service Windows |

### Voir les logs en direct

```powershell
Get-Content D:\clab-labs\cv-agent\logs\agent.log -Wait -Tail 30
```

### Inspection de la base SQLite

Installer un client SQLite :
```powershell
winget install -e --id SQLite.sqlite
```

Requêtes utiles :
```powershell
cd D:\clab-labs\cv-agent

# Compter les candidats par statut
sqlite3 state.db "SELECT statut, COUNT(*) FROM candidates GROUP BY statut;"

# Lister les 10 derniers cycles
sqlite3 state.db "SELECT id, started_at, status, cvs_detected FROM runs ORDER BY id DESC LIMIT 10;"

# Voir les utilisateurs
sqlite3 state.db "SELECT id, email, role, active FROM users;"

# Voir les paramètres
sqlite3 state.db "SELECT key, value FROM settings;"
```

### Re-traiter un email (debug)

```powershell
sqlite3 state.db "DELETE FROM processed_emails WHERE uid = '12345';"
```
Au prochain cycle, l'email sera re-fetché et re-traité.

### Sauvegarde

Sauvegarde régulière recommandée :
- `state.db` (base entière : users, candidats, settings, runs)
- `cv_pdfs\` (PDF originaux)

Exemple :
```powershell
$dest = "D:\backups\cv-agent_$(Get-Date -Format yyyyMMdd)"
New-Item -ItemType Directory -Path $dest -Force | Out-Null
Copy-Item state.db, cv_pdfs -Recurse -Destination $dest
```

> ⚠️ Les mots de passe (IMAP/SMTP) et la clé API contenus dans `state.db` sont chiffrés et **liés à la machine** : après restauration sur un autre poste, ré-saisis-les dans **Paramètres** (cf. [§16 Sécurité](#16-sécurité-et-confidentialité)).

### Reset complet (⚠️ destructif)

```powershell
Remove-Item state.db -Confirm:$false
Remove-Item cv_pdfs\*.pdf -Confirm:$false
Remove-Item logs\*.log -Confirm:$false
# Puis relance bootstrap.py
```

---

## 15. Dépannage

### ❌ Le serveur web ne démarre pas

Consulter `logs\web_startup.log`. Causes fréquentes :
1. `.venv` absent → `python -m venv .venv && pip install -r requirements.txt`
2. Port 6060 déjà occupé → `Get-NetTCPConnection -LocalPort 6060` puis `Stop-Process -Id <pid>`
3. SQLite verrouillée → un autre process tourne déjà (vérifier)

### ❌ Accès LAN impossible depuis un autre poste

1. Vérifier que le serveur tourne : `Invoke-RestMethod http://localhost:6060/healthz`
2. Vérifier la règle de pare-feu :
   ```powershell
   Get-NetFirewallRule -DisplayName "CV Agent Web (port 6060)"
   ```
3. Vérifier que le profil réseau est **Privé**, pas Public :
   ```powershell
   Get-NetConnectionProfile
   ```
   Si profil "Public", changer : `Set-NetConnectionProfile -InterfaceAlias "<nom>" -NetworkCategory Private`
4. Tester le port depuis l'autre poste :
   ```powershell
   Test-NetConnection <ip-serveur> -Port 6060
   ```

### ❌ "AUTHENTICATIONFAILED" dans les logs pipeline

1. Vérifier le mot de passe d'app Gmail dans Paramètres (pas d'espaces)
2. Régénérer un nouveau mot de passe d'app
3. Vérifier IMAP activé dans Gmail

### ❌ "ConnectionRefusedError" sur Ollama

Ollama n'est pas démarré :
```powershell
Get-Process ollama -ErrorAction SilentlyContinue
```
Si vide, lance l'application Ollama ou `ollama serve`.

### ❌ "model 'qwen2.5:7b' not found"

```powershell
ollama pull qwen2.5:7b
```

### ❌ Tous les CV classés `is_cv=False`

1. Baisser le seuil dans Paramètres : `processing.classification_confidence_threshold` à `0.5`
2. Vérifier que les pièces jointes sont bien en `.pdf`, `.docx` ou `.doc`
3. Consulter `logs\agent.log` pour voir la `reason` retournée

### ❌ "no_text_in_attachment"

PDF scanné (image) sans OCR. Limitation actuelle. Demande au candidat un PDF avec texte sélectionnable.

### ❌ Le service ne démarre plus après changement de mot de passe Windows

Relancer `install_autostart.ps1` pour ré-enregistrer la tâche avec le nouveau mot de passe.

### ❌ Performance lente (>1 min par CV)

1. Vérifier le modèle chargé : `ollama ps`
2. Vérifier l'usage GPU : `nvidia-smi`
3. Si le modèle est plus gros que la VRAM, basculer sur `qwen2.5:7b` dans Paramètres

### ❌ Conflit "Un cycle est déjà en cours"

Cycle bloqué :
```powershell
sqlite3 state.db "UPDATE runs SET status='failed', finished_at=datetime('now'), error='manual_unblock' WHERE status='running';"
```

---

## 16. Sécurité et confidentialité

L'application est conçue pour un usage **local / LAN** et applique plusieurs mesures de sécurité. Cette section les résume et liste les bonnes pratiques d'exploitation.

### Chiffrement des secrets au repos

Les identifiants sensibles stockés dans `state.db` sont **chiffrés** (Windows DPAPI, portée machine) :

- `imap.password` — mot de passe d'application Gmail
- `smtp.password` — mot de passe du serveur d'envoi (si notifications activées)
- `openrouter.api_key` — clé API cloud (si moteur `openrouter`)

Concrètement :

- En base, ces valeurs apparaissent sous la forme `enc:v1:…` (illisibles), jamais en clair.
- Le déchiffrement est **lié à la machine** : un `state.db` copié sur un autre PC **ne peut pas** être déchiffré. C'est voulu — un fichier volé est inexploitable ailleurs.
- La migration est automatique : au 1er démarrage après la mise à jour, les secrets encore en clair sont chiffrés (trace dans `logs\agent.log` : « X secret(s) chiffré(s) au repos »).

> ⚠️ **Sauvegarde / restauration sur une NOUVELLE machine** : les secrets chiffrés ne sont **pas** portables. Après restauration d'un `state.db` sur un autre poste, va dans **Paramètres** et ré-saisis le mot de passe IMAP (et, le cas échéant, le mot de passe SMTP et la clé API). Les candidats, utilisateurs et réglages non-secrets se restaurent normalement.

### Mots de passe des comptes web

Hachés avec **bcrypt** (coût 12), non réversibles. Un vol de `state.db` ne révèle donc pas les mots de passe des utilisateurs.

### Protection anti-force-brute (login)

Après **5 tentatives de connexion échouées** pour un même email, le compte est **bloqué 30 secondes** (le message de login indique le délai restant). Une connexion réussie remet le compteur à zéro. Cela ralentit fortement les attaques par essais de mots de passe.

### Mot de passe d'application Gmail — rotation

Le mot de passe d'application Gmail donne accès à la boîte de candidatures. **Change-le** (rotation) :

- **immédiatement** si tu penses qu'il a pu fuiter (présent en clair dans un fichier partagé, un ancien build, un email, une capture d'écran…) ;
- périodiquement par précaution (ex. tous les 6-12 mois).

Procédure :

1. https://myaccount.google.com/apppasswords → **supprime** l'ancien mot de passe « CV Agent Local ».
2. **Crée** un nouveau mot de passe d'application (16 caractères).
3. Interface web → **Paramètres** → `imap.password` → colle la nouvelle valeur → **💾 Enregistrer**.
4. Clique **📬 Tester la connexion à la boîte mail** pour valider.

> ⚠️ Le fichier `config.yaml` n'est qu'un **modèle de graine** (bootstrap). **N'y mets jamais d'identifiants réels** et ne distribue pas de version contenant un mot de passe : il serait embarqué **en clair** dans l'exécutable / l'installateur. Les vrais identifiants vivent uniquement dans `state.db` (chiffrés).

### Exposition réseau

| Mode | Écoute | Portée |
|---|---|---|
| Application desktop (`.exe`) | `127.0.0.1` (loopback) | Cette machine uniquement |
| Service autostart (LAN) | port `6060` | LAN — pare-feu **Domain + Private** (jamais Internet) |

Pour un accès distant, passe par un **VPN** — n'ouvre pas le port 6060 sur Internet.

### Bonnes pratiques d'exploitation

- Communiquer les identifiants des comptes RH par un **canal sécurisé** (en personne, messagerie chiffrée) — pas par email en clair.
- **Désactiver** plutôt que supprimer le compte d'un collaborateur parti (conserve l'historique).
- Restreindre l'accès physique et administrateur à la machine serveur : le chiffrement DPAPI protège contre le **vol du fichier** `state.db`, pas contre un accès complet à la session Windows ouverte.
- Sauvegarder régulièrement `state.db` + `cv_pdfs\` (cf. §14).

---

## 17. FAQ

**Q : Plusieurs RH peuvent-ils éditer le même candidat en même temps ?**
R : Oui, SQLite gère les écritures concurrentes. La dernière modification écrase la précédente — sans tracking de qui a fait quoi (cf. limites).

**Q : Mes mails restent-ils non lus ?**
R : Oui. L'agent ne modifie jamais le flag `Seen` IMAP. Tout est tracé en interne via SQLite.

**Q : Faut-il garder un onglet web ouvert pour que ça tourne ?**
R : **Non**. Le service tourne en arrière-plan. L'interface est juste un client de consultation/édition.

**Q : Comment ajouter un utilisateur sans accès admin ?**
R : Tu dois être admin. Menu → **Utilisateurs** → Créer.

**Q : Puis-je modifier l'Excel exporté et le réimporter ?**
R : **Non**. L'Excel est en lecture seule (export). Les modifs sont à faire dans l'interface web.

**Q : Le service consomme combien de RAM/CPU au repos ?**
R : Quand aucun cycle ne tourne : ~150 Mo RAM, ~0% CPU. Pendant un cycle : pic à 5 Go (modèle Ollama) + un cœur CPU.

**Q : Combien d'utilisateurs simultanés peuvent se connecter ?**
R : ~10-20 sans problème. La limite est SQLite et le single-process FastAPI.

**Q : Le serveur est-il accessible depuis Internet ?**
R : **Non**, pas par défaut. Le pare-feu n'ouvre que les profils LAN (Domain + Private). Pour accès distant, prévoir un VPN.

**Q : Où sont stockés les mots de passe utilisateurs ?**
R : Dans `state.db`, hashés avec **bcrypt** (rounds=12). Non récupérables.

**Q : Que se passe-t-il si la machine est éteinte pendant un cycle ?**
R : Le cycle est marqué `running` éternellement. Au reboot, le service redémarre mais le cycle bloqué reste. Utilise la requête SQL de la section Dépannage pour le débloquer.

**Q : Et si Gmail change leur API ou rate-limit ?**
R : L'IMAP est stable (Gmail s'engage à le maintenir). Pas de risque court terme.

---

## 18. Limites connues et évolutions possibles

### Limites actuelles

1. Pas d'**OCR** : PDF scannés (images) ignorés
2. Pas de **tracking** des modifications (qui a édité quoi quand)
3. Pas de **détection automatique de doublons**
4. **Une seule boîte mail** par installation
5. Pas de **2FA** sur les comptes web (login simple email+mot de passe)
6. Pas d'**audit log** des actions
7. Pas de **notification** quand un nouveau CV arrive (mail, push)
8. Pas de **scoring** vs fiche de poste
9. Pas de **réponse auto** au candidat
10. SQLite mono-process : pas de scale-out horizontal

### Évolutions par ordre de simplicité

| Fonctionnalité | Difficulté | Apport |
|---|---|---|
| 2FA sur les comptes web (TOTP) | Facile | Sécurité |
| Notification toast / email à l'arrivée d'un CV | Facile | Réactivité |
| Détection de doublons (par email candidat) | Facile | Hygiène |
| Audit log "qui a édité quoi quand" | Moyen | Conformité RH |
| Scoring CV vs fiche de poste | Moyen | Tri intelligent |
| OCR Tesseract pour PDF scannés | Moyen | Couverture |
| Multi-boîtes mail | Moyen | Scalabilité |
| Réponse auto au candidat (accusé de réception) | Important | Expérience candidat |
| Passage de SQLite à PostgreSQL (>1000 candidats/mois) | Important | Robustesse |

---

## 19. Annexes — commandes utiles

### Lancement / arrêt manuel

```powershell
# Lancer manuellement (console visible)
cd D:\clab-labs\cv-agent
.\run_web.bat

# Démarrer la tâche planifiée maintenant
Start-ScheduledTask -TaskName "CV-Agent-Web"

# Arrêter la tâche
Stop-ScheduledTask -TaskName "CV-Agent-Web"

# Désactiver l'autostart temporairement (vacances/maintenance)
Disable-ScheduledTask -TaskName "CV-Agent-Web"

# Réactiver
Enable-ScheduledTask -TaskName "CV-Agent-Web"
```

### Diagnostic

```powershell
# Santé du serveur
Invoke-RestMethod http://localhost:6060/healthz

# Voir l'état de la tâche
Get-ScheduledTask -TaskName "CV-Agent-Web" | Get-ScheduledTaskInfo

# Logs en direct
Get-Content D:\clab-labs\cv-agent\logs\agent.log -Wait -Tail 30

# Voir l'utilisation GPU
nvidia-smi

# Voir les modèles Ollama chargés
ollama ps

# Tester l'API Ollama
Invoke-RestMethod http://localhost:11434/api/tags
```

### CLI pipeline (debug)

```powershell
cd D:\clab-labs\cv-agent
.\.venv\Scripts\Activate.ps1
python main.py
```

### Inspection SQLite

```powershell
# Top 5 candidats récents
sqlite3 state.db "SELECT id, prenom, nom, statut, received_at FROM candidates ORDER BY received_at DESC LIMIT 5;"

# Stats par statut
sqlite3 state.db "SELECT statut, COUNT(*) FROM candidates GROUP BY statut;"

# Dernier cycle réussi
sqlite3 state.db "SELECT * FROM runs WHERE status='success' ORDER BY id DESC LIMIT 1;"
```

### Mise à jour du manuel

```powershell
# Après avoir modifié MANUEL_UTILISATION.md :
python build_pdf.py
```

---

*Manuel rédigé pour : Windows 11 Pro / RTX 4060 8 GB / Python 3.13 / Ollama qwen2.5:7b / FastAPI + SQLite.*
*Dernière mise à jour : 2026-07-05 — Version 2 (interface web) + durcissement sécurité (chiffrement des secrets au repos, anti-force-brute login).*
