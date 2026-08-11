# Déploiement sur Ubuntu

Guide d'installation de CV Agent Pro sur Ubuntu Server ou Desktop (22.04 LTS et
24.04 LTS). Deux modes au choix, plus une option HTTPS commune aux deux.

| Mode | Pour qui | Dossier |
|------|----------|---------|
| **Docker Compose** *(recommandé)* | Cas général. Application + PostgreSQL livrés ensemble, mises à jour et sauvegardes scriptées. | [`docker/`](docker/) |
| **Natif systemd** | Serveurs où Docker est interdit, ou intégration à un PostgreSQL déjà administré. | [`natif/`](natif/) |
| **Reverse-proxy HTTPS** | Complément aux deux précédents, dès que l'accès sort du LAN. | [`nginx/`](nginx/) |

> **Prérequis commun aux deux modes : `CV_AGENT_SECRET`.**
> Sous Linux il n'y a pas de DPAPI Windows. Ce secret est donc **obligatoire** :
> il chiffre les mots de passe IMAP/SMTP et la clé API au repos (format `enc:v2`)
> et signe le cookie de session. Les scripts le génèrent automatiquement.
> **Le perdre rend les secrets stockés définitivement illisibles** — ils
> ressortent vides, sans message d'erreur. Sauvegardez-le avec la base.

---

## Mode 1 — Docker Compose (recommandé)

```bash
git clone https://github.com/seddikd/CV-Agent-Pro.git
cd CV-Agent-Pro
sudo ./deploiement/ubuntu/docker/installer-docker.sh
```

Le script installe Docker CE depuis le dépôt officiel (celui d'Ubuntu fournit un
`docker.io` souvent trop ancien pour la commande `docker compose`), génère un
`.env` avec des secrets aléatoires, construit l'image, démarre application et
PostgreSQL, puis attend que `/login` réponde avant de rendre la main.

Ouvrez ensuite **`http://<ip-du-serveur>:6060/setup`** pour créer le premier
compte administrateur.

### Exploitation courante

Toutes les commandes se lancent depuis la racine du dépôt :

```bash
docker compose -f docker-compose.yml ps           # état des conteneurs
docker compose -f docker-compose.yml logs -f app  # journal en direct
docker compose -f docker-compose.yml restart app  # redémarrage

./deploiement/ubuntu/docker/sauvegarde.sh         # archive horodatée
./deploiement/ubuntu/docker/restauration.sh <archive.tar.gz>
./deploiement/ubuntu/docker/maj.sh                # sauvegarde + pull + rebuild
```

> **Pourquoi `-f docker-compose.yml` partout ?**
> `docker-compose.override.yml` est fusionné automatiquement par Docker. Or cette
> surcharge existe pour un **poste Windows** : elle publie PostgreSQL sur la
> loopback pour permettre l'exécution native de l'application. Sous Ubuntu elle
> n'a aucune raison d'être, et désigner explicitement le fichier de base la
> neutralise proprement.

### Sauvegarde

`sauvegarde.sh` produit une archive `sauvegardes/cv-agent-<horodatage>.tar.gz`
contenant les trois éléments indissociables :

1. le dump PostgreSQL (candidats, réglages, comptes, historique) ;
2. le volume `/data` (`cv_pdfs`, `logs`) ;
3. le `.env` — **sans lui, les mots de passe du dump restent chiffrés et sont
   irrécupérables**.

L'archive est en `chmod 600` puisqu'elle contient le secret. Pour une sauvegarde
quotidienne à 2 h du matin :

```bash
sudo crontab -e
# 0 2 * * * cd /chemin/CV-Agent-Pro && ./deploiement/ubuntu/docker/sauvegarde.sh >> /var/log/cv-agent-sauvegarde.log 2>&1
```

### Ollama sur l'hôte

Le `docker-compose.yml` déclare `host.docker.internal:host-gateway`, ce qui rend
ce nom valable sous Docker Linux natif. Si Ollama tourne sur la machine hôte,
renseignez dans **Administration → Paramètres** :

```
http://host.docker.internal:11434
```

---

## Mode 2 — Natif systemd (sans Docker)

```bash
git clone https://github.com/seddikd/CV-Agent-Pro.git
cd CV-Agent-Pro
sudo ./deploiement/ubuntu/natif/installer-natif.sh
```

Ce que le script met en place :

| Élément | Emplacement |
|---------|-------------|
| Code applicatif | `/opt/cv-agent` |
| Environnement Python | `/opt/cv-agent/.venv` |
| Données (`cv_pdfs`, `logs`) | `/var/lib/cv-agent` |
| Configuration (secrets) | `/etc/cv-agent/cv-agent.env` — `chmod 640`, `root:cvagent` |
| Service | `/etc/systemd/system/cv-agent.service` |
| Compte système | `cvagent` (sans shell de connexion) |
| Base | PostgreSQL local, base et rôle `cvagent` |

Puis **`http://<ip-du-serveur>:6060/setup`**.

### Points de conception

- **`requirements-docker.txt`, pas `requirements.txt`.** C'est le sous-ensemble
  *runtime serveur*. `requirements.txt` tire `pystray`, `pillow` et `pyinstaller`
  (bureautique et build Windows), inutiles ici et sources d'échecs de compilation.
- **Pas de `bootstrap.py`.** Il est interactif (`input()`/`getpass`), donc
  inutilisable depuis un service. Ce n'est pas un contournement : `state_db.init()`
  crée le schéma au démarrage et `/setup` crée le premier admin — exactement le
  chemin suivi par le déploiement Docker.
- **Un seul worker**, invariant du projet : APScheduler et le compteur
  `candidate_counter` supposent un unique processus. Passer à `--workers 2`
  provoquerait des cycles de collecte en double et des identifiants `idNNNN` en
  collision.
- **Service durci** : `ProtectSystem=strict`, `ProtectHome`, `NoNewPrivileges`,
  et `/var/lib/cv-agent` comme seul chemin inscriptible.

### Exploitation courante

```bash
systemctl status cv-agent            # état
journalctl -u cv-agent -f            # journal du service
sudo systemctl restart cv-agent      # redémarrage
sudo less /var/lib/cv-agent/logs/agent.log   # journal du pipeline
```

### Mise à jour

```bash
cd /chemin/CV-Agent-Pro && git pull
sudo ./deploiement/ubuntu/natif/installer-natif.sh   # ré-exécutable sans risque
```

Le script resynchronise le code et les dépendances ; la base, le secret et le
mot de passe déjà générés sont conservés. Le schéma se met à jour au démarrage.

### Désinstallation

```bash
sudo ./deploiement/ubuntu/natif/desinstaller-natif.sh          # garde la base
sudo ./deploiement/ubuntu/natif/desinstaller-natif.sh --tout   # supprime TOUT
```

### Sauvegarde en mode natif

```bash
sudo -u postgres pg_dump -Fc cvagent > base.dump
sudo tar czf donnees.tar.gz -C /var/lib/cv-agent .
sudo cp /etc/cv-agent/cv-agent.env config.env    # contient CV_AGENT_SECRET
```

---

## Option — HTTPS avec Nginx

Utilisable derrière l'un ou l'autre mode. Prérequis : un domaine pointant sur le
serveur et les ports 80/443 ouverts (certbot valide par le port 80).

```bash
sudo ./deploiement/ubuntu/nginx/installer-https.sh cv.mon-entreprise.fr admin@mon-entreprise.fr
```

Le script pose le vhost, obtient le certificat, active la redirection HTTP→HTTPS
et referme le port 6060 sur ufw.

**Deux réglages restent à appliquer à la main** — le script les rappelle en fin
d'exécution, ils ne peuvent pas être devinés :

1. **`CV_AGENT_HTTPS_ONLY=1`** pour le drapeau `Secure` sur le cookie.
   L'application ne lit pas `X-Forwarded-Proto` (uvicorn tourne sans
   `--proxy-headers`) : ce drapeau vient *uniquement* de cette variable.
2. **Restreindre l'écoute à la loopback**, sinon `http://<ip>:6060` contourne
   tout le HTTPS. Docker : `"127.0.0.1:6060:6060"`. Natif : `--host 127.0.0.1`.

---

## Dépannage

| Symptôme | Cause probable et correctif |
|----------|------------------------------|
| `bad interpreter: /bin/bash^M` | Les `.sh` ont été récupérés en CRLF. Le `.gitattributes` du dépôt force `eol=lf` ; si le fichier a transité par un partage Windows : `sed -i 's/\r$//' script.sh`. |
| Permission refusée au lancement | `chmod +x deploiement/ubuntu/**/*.sh` |
| `CV_AGENT_DB_URL` manquant | Variable non transmise au service. Natif : vérifier `/etc/cv-agent/cv-agent.env` et `EnvironmentFile=`. Docker : vérifier `.env`. |
| Mots de passe IMAP/SMTP vides après restauration | `CV_AGENT_SECRET` différent de celui d'origine. Restaurer le `.env`/`cv-agent.env` d'époque, puis redémarrer. |
| Le service redémarre en boucle | `journalctl -u cv-agent -n 50`. Le plus souvent PostgreSQL pas encore prêt ou identifiants erronés. |
| Port 6060 injoignable depuis le LAN | `sudo ufw allow 6060/tcp`, et vérifier que l'écoute est bien sur `0.0.0.0`. |
| `docker compose` : commande inconnue | Ancien `docker.io` d'Ubuntu. `installer-docker.sh` installe la version officielle qui fournit le plugin. |
| Erreur 413 à l'import d'un CV | `client_max_body_size` dans le vhost Nginx (déjà à 100M dans le modèle fourni). |

---

## Rappels de sécurité

- **Une seule instance par boîte mail.** Deux instances qui pollent la même boîte
  violent l'invariant mono-processus (doublons de candidats, compteurs en
  collision). Ne pas répliquer le service derrière un répartiteur de charge.
- **Instances multiples sur une même base** : le **même** `CV_AGENT_SECRET`
  partout, sans quoi chacune sera incapable de déchiffrer les secrets des autres.
- **`.env` et `cv-agent.env` ne se versionnent jamais.** Le premier est déjà
  couvert par le `.gitignore`.
- **PostgreSQL ne s'expose pas au réseau.** Le compose de base ne publie aucun
  port pour la base ; en natif, l'écoute par défaut sur la loopback convient.
