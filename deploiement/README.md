# Déploiement de CV Agent Pro

Point d'entrée unique pour installer la solution via Docker.

| | [`ubuntu/docker/`](ubuntu/docker/) |
|---|---|
| **Modes couverts** | Docker Compose, reverse-proxy HTTPS |
| **Contenu** | Scripts d'installation, sauvegarde, restauration, mise à jour, vhost Nginx |
| **Guide** | [`ubuntu/README.md`](ubuntu/README.md) |

## Démarrage rapide

**Docker Compose (recommandé)**

```bash
sudo ./deploiement/ubuntu/docker/installer-docker.sh
```

Dans tous les cas, la première page à ouvrir est **`http://<hôte>:6060/setup`**,
qui crée le compte administrateur initial.

## Ce que ce dossier ne remplace pas

La référence détaillée demeure **[`MANUEL_DEPLOIEMENT.md`](../MANUEL_DEPLOIEMENT.md)**.
`deploiement/ubuntu/docker/` est un point d'entrée et un complément, pas un
remplacement : les chemins documentés dans `README.md` et `CLAUDE.md` restent
valables.

## Les trois règles communes à tous les déploiements

1. **PostgreSQL est obligatoire.** `CV_AGENT_DB_URL` doit être définie ; il
   n'existe aucun repli SQLite et l'application refuse de démarrer sans elle.
2. **`CV_AGENT_SECRET` conditionne la lisibilité des secrets.** Il chiffre les
   mots de passe IMAP/SMTP et la clé API au repos, et signe le cookie de
   session. Il est **obligatoire en conteneur**. Dès que deux instances
   partagent une base, le **même** secret doit être posé partout. **Il se
   sauvegarde avec la base** : sans lui, un dump restauré rend les mots de
   passe vides, silencieusement.
3. **Une seule instance par boîte mail, un seul worker.** APScheduler et le
   compteur `candidate_counter` supposent un processus unique. Deux instances
   pollant la même boîte produisent des candidats en double et des
   identifiants `idNNNN` en collision. Pas de réplication derrière un
   répartiteur de charge.

## Ports

| Port | Usage | Exposition |
|------|-------|------------|
| `6060` | Interface web | LAN, ou loopback seule derrière un reverse-proxy |
| `5432` | PostgreSQL | Jamais publié au réseau (interne au réseau Docker compose) |
| `11434` | Ollama | Sur l'hôte ; joint via `host.docker.internal` depuis un conteneur |
