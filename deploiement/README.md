# Déploiement de CV Agent Pro

Point d'entrée unique pour installer la solution, quel que soit le système.

| | [`ubuntu/`](ubuntu/) | [`windows/`](windows/) |
|---|---|---|
| **Modes couverts** | Docker Compose, natif systemd, reverse-proxy HTTPS | Support ISO hors ligne, installeur `.exe`, sources + venv, Docker Desktop |
| **Contenu** | Scripts d'installation, sauvegarde, restauration, mise à jour, unité systemd, vhost Nginx | Guide d'orientation + outils de sauvegarde, restauration et diagnostic |
| **Guide** | [`ubuntu/README.md`](ubuntu/README.md) | [`windows/README.md`](windows/README.md) |

## Démarrage rapide

**Ubuntu — Docker (recommandé)**
```bash
sudo ./deploiement/ubuntu/docker/installer-docker.sh
```

**Ubuntu — natif, sans Docker**
```bash
sudo ./deploiement/ubuntu/natif/installer-natif.sh
```

**Windows — poste hors ligne**
Support `iso\` → `Installer.ps1` (voir [`iso/GUIDE_INSTALLATION.md`](../iso/GUIDE_INSTALLATION.md))

**Windows — depuis les sources**
```powershell
.\install.bat
.\run_web.bat
```

Dans tous les cas, la première page à ouvrir est **`http://<hôte>:6060/setup`**,
qui crée le compte administrateur initial.

## Ce que ce dossier ne remplace pas

L'outillage Windows historique **reste à la racine du dépôt** (`install.ps1`,
`install_autostart.ps1`, `installer.iss`, `build_exe.ps1`…) et sur le support
`iso\`. Rien n'a été déplacé : les chemins documentés dans `README.md`,
`MANUEL_DEPLOIEMENT.md` et `CLAUDE.md` restent valables. `deploiement/windows/`
est un point d'entrée et un complément, pas un remplacement.

La référence détaillée demeure **[`MANUEL_DEPLOIEMENT.md`](../MANUEL_DEPLOIEMENT.md)**.

## Les trois règles communes à tous les déploiements

1. **PostgreSQL est obligatoire.** `CV_AGENT_DB_URL` doit être définie ; il
   n'existe aucun repli SQLite et l'application refuse de démarrer sans elle.

2. **`CV_AGENT_SECRET` conditionne la lisibilité des secrets.** Il chiffre les
   mots de passe IMAP/SMTP et la clé API au repos, et signe le cookie de session.
   Sous Linux il est **obligatoire** (pas de DPAPI). Sous Windows, son absence
   fait basculer sur DPAPI, lié à la machine — donc impossible à restaurer
   ailleurs. Dès que deux instances partagent une base, le **même** secret doit
   être posé partout. **Il se sauvegarde avec la base** : sans lui, un dump
   restauré rend les mots de passe vides, silencieusement.

3. **Une seule instance par boîte mail, un seul worker.** APScheduler et le
   compteur `candidate_counter` supposent un processus unique. Deux instances
   pollant la même boîte produisent des candidats en double et des identifiants
   `idNNNN` en collision. Pas de réplication derrière un répartiteur de charge.

## Ports

| Port | Usage | Exposition |
|------|-------|------------|
| `6060` | Interface web | LAN, ou loopback seule derrière un reverse-proxy |
| `5432` | PostgreSQL | Jamais publié au réseau (interne compose, ou loopback en natif) |
| `11434` | Ollama | Sur l'hôte ; joint via `host.docker.internal` depuis un conteneur |
