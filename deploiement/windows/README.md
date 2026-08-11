# Déploiement sur Windows

Windows est la plateforme historique du projet : l'outillage existe déjà à la
racine du dépôt et sur le support `iso\`. **Ce dossier ne le duplique pas** — il
sert de point d'entrée (quel mode choisir, quel fichier fait quoi) et ajoute les
trois outils qui manquaient : sauvegarde, restauration et diagnostic.

## Choisir son mode

| Mode | Pour qui | Point de départ |
|------|----------|-----------------|
| **Support `iso\` hors ligne** | Poste RH sans accès Internet. Installe PostgreSQL, Ollama et l'application d'un bloc. | [`iso\GUIDE_INSTALLATION.md`](../../iso/GUIDE_INSTALLATION.md) — `Installer.ps1` |
| **Installeur `.exe`** | Poste bureautique unique, prérequis déjà en place. | `dist\CV-Agent-Setup.exe` (produit par `build_installer.ps1`) |
| **Sources + venv** | Poste de développement, ou serveur LAN pour l'équipe RH. | `install.bat` à la racine |
| **Docker Desktop** | Poste déjà équipé de Docker, isolation souhaitée. | `docker compose up -d` |

La documentation détaillée reste dans **[`MANUEL_DEPLOIEMENT.md`](../../MANUEL_DEPLOIEMENT.md)**
(§ 5 Docker, § 6 natif, § 6bis support ISO, § 9 démarrage automatique,
§ 11 HTTPS, § 12 construction de l'exécutable).

## Carte des fichiers existants

À la racine du dépôt :

| Fichier | Rôle |
|---------|------|
| `install.bat` → `install.ps1` | Crée `.venv`, installe les dépendances, lance `bootstrap.py` (base + admin). Idempotent. |
| `run_web.bat` | Démarre le serveur en développement (`0.0.0.0:6060`). |
| `start_web.bat` | Lanceur silencieux utilisé par la tâche planifiée ; journalise dans `logs\web_startup.log`. |
| `install_autostart.ps1` | Tâche planifiée « CV-Agent-Web » au démarrage + règle de pare-feu 6060. **PowerShell administrateur.** |
| `uninstall_autostart.ps1` | Retire la tâche, la règle, et arrête le processus sur 6060. |
| `run_web_natif.ps1` | Application en natif Windows sur la base PostgreSQL de Docker. Nécessaire au rangement des mails Outlook (COM/win32com), impossible depuis le conteneur Linux. |
| `build_exe.ps1`, `cv-agent.spec` | Construction de l'exécutable PyInstaller (`dist\CV-Agent\`). |
| `build_installer.ps1`, `installer.iss` | Installeur Inno Setup + régénération des PDF. |
| `sign.ps1` | Signature de l'exécutable. |
| `iso\Installer.ps1` | Installation hors ligne complète depuis le support. |

## Outils ajoutés par ce dossier

```powershell
# Diagnostic complet — ne modifie rien, à lancer en premier en cas de souci
powershell -ExecutionPolicy Bypass -File .\deploiement\windows\verifier-deploiement.ps1

# Sauvegarde (détecte automatiquement Docker ou natif)
powershell -ExecutionPolicy Bypass -File .\deploiement\windows\sauvegarde.ps1
powershell -ExecutionPolicy Bypass -File .\deploiement\windows\sauvegarde.ps1 -Destination D:\sauvegardes

# Restauration — DESTRUCTIVE, demande une confirmation explicite
powershell -ExecutionPolicy Bypass -File .\deploiement\windows\restauration.ps1 -Source .\sauvegardes\cv-agent-20260812-101500
```

`verifier-deploiement.ps1` contrôle successivement : Python et `.venv`,
dépendances critiques importables, `CV_AGENT_DB_URL` / `CV_AGENT_SECRET`,
joignabilité de PostgreSQL, écoute et réponse du port 6060, tâche planifiée,
règle de pare-feu, conteneurs Docker, taille et fraîcheur des journaux. Il sort
en code 1 s'il relève une erreur — utilisable dans une supervision.

## Ce qu'il faut sauvegarder

Trois éléments **indissociables** :

1. la base PostgreSQL (candidats, réglages, comptes, historique) ;
2. les fichiers `cv_pdfs\` et `logs\` ;
3. **le secret de chiffrement** — `.env` en mode Docker, variable machine
   `CV_AGENT_SECRET` en natif.

> **Le piège à connaître.** Les mots de passe IMAP/SMTP et la clé API sont
> chiffrés au repos. Si `CV_AGENT_SECRET` est défini, ils sont en `enc:v2`
> (portable, déchiffrable partout où le même secret est présent). Sinon, repli
> sur **DPAPI `enc:v1`, lié à la machine** : le dump restauré sur un autre poste
> rendra ces mots de passe vides — sans message d'erreur, l'application
> continuera de tourner et la collecte échouera silencieusement. Dès que
> plusieurs postes partagent une base, `CV_AGENT_SECRET` devient obligatoire.

## Points de vigilance Windows

- **Une seule instance par boîte mail.** APScheduler et le compteur
  `candidate_counter` supposent un processus unique ; `--workers 1` n'est pas
  négociable. C'est aussi pourquoi `run_web_natif.ps1` refuse de démarrer tant
  que le conteneur applicatif tourne.
- **PostgreSQL est obligatoire.** Aucun repli SQLite : sans `CV_AGENT_DB_URL`,
  l'application refuse de démarrer avec une erreur explicite.
- **La tâche planifiée tourne sous un compte utilisateur**, pas `SYSTEM` : elle
  doit atteindre le Python installé dans `AppData`.
- **Encodage des scripts.** Les `.ps1` du dépôt sont en UTF-8 **avec BOM** :
  Windows PowerShell 5.1 lit un UTF-8 sans BOM comme de l'ANSI et transforme les
  accents en mojibake. Le `.gitattributes` verrouille par ailleurs les fins de
  ligne (CRLF pour `.ps1`/`.bat`, LF pour les `.sh` destinés à Ubuntu).

## Dépannage express

| Symptôme | Piste |
|----------|-------|
| L'application ne démarre pas | `verifier-deploiement.ps1` puis `logs\web_startup.log`. |
| Port 6060 déjà occupé | `uninstall_autostart.ps1` arrête le processus, ou `Get-NetTCPConnection -LocalPort 6060`. |
| Accents illisibles dans un script | `.ps1` enregistré sans BOM — voir ci-dessus. |
| `cryptography` / `psycopg` introuvable | Exécutable construit avant l'ajout de la dépendance : reconstruire (`build_exe.ps1`). |
| Bouton « Ranger les traités » grisé | Fonction Outlook COM : indisponible depuis le conteneur Linux. Utiliser `run_web_natif.ps1`. |
| Mots de passe IMAP vides après migration | Blob DPAPI d'une autre machine. Ressaisir les mots de passe, et définir `CV_AGENT_SECRET`. |

---

Pour un déploiement Linux, voir [`../ubuntu/`](../ubuntu/).
