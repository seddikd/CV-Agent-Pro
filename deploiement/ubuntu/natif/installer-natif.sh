#!/usr/bin/env bash
#
# CV Agent Pro — installation NATIVE sur Ubuntu (sans Docker).
#
# Met en place : paquets système, utilisateur dédié « cvagent », PostgreSQL local
# (rôle + base), copie du code dans /opt/cv-agent, environnement virtuel Python,
# fichier d'environnement chiffré en 600, service systemd, pare-feu ufw.
#
# USAGE (depuis une copie du dépôt) :
#   sudo ./deploiement/ubuntu/natif/installer-natif.sh
#
# Idempotent : ré-exécutable sans casse (met à jour le code et les dépendances,
# conserve la base, le secret et les mots de passe déjà générés).
#
# Testé sur Ubuntu 22.04 LTS et 24.04 LTS.

set -euo pipefail

# ---- Paramètres --------------------------------------------------------------
APP_USER="cvagent"
APP_DIR="/opt/cv-agent"
DATA_DIR="/var/lib/cv-agent"
ENV_DIR="/etc/cv-agent"
ENV_FILE="${ENV_DIR}/cv-agent.env"
DB_NAME="cvagent"
DB_USER="cvagent"
PORT="6060"
SERVICE="cv-agent"

# Racine du dépôt = trois niveaux au-dessus de ce script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

vert() { printf '\033[32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[33m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[36m=== %s ===\033[0m\n' "$*"; }

# ---- Garde-fous --------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
    rouge "ERREUR : ce script doit être lancé avec sudo (il crée un utilisateur système et un service)."
    echo "  sudo $0"
    exit 1
fi

if [[ ! -f "${REPO_DIR}/webapp.py" ]]; then
    rouge "ERREUR : webapp.py introuvable dans ${REPO_DIR}."
    echo "Lancez ce script depuis une copie complète du dépôt."
    exit 1
fi

etape "CV Agent Pro — installation native Ubuntu"
echo "Source      : ${REPO_DIR}"
echo "Destination : ${APP_DIR}"

# ---- 1. Paquets système ------------------------------------------------------
etape "1/7 Paquets système"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# build-essential + python3-dev : libpff-python (lecture des .pst/.ost) se compile.
# libpq-dev : en secours si le wheel binaire psycopg n'est pas disponible.
apt-get install -y -qq \
    python3 python3-venv python3-dev \
    build-essential libpq-dev \
    postgresql postgresql-contrib \
    rsync openssl ca-certificates
vert "Paquets installés."

# ---- 2. Utilisateur système --------------------------------------------------
etape "2/7 Utilisateur système « ${APP_USER} »"
if id -u "${APP_USER}" >/dev/null 2>&1; then
    echo "Utilisateur déjà présent."
else
    # Compte de service : pas de shell de connexion, pas de home classique.
    useradd --system --home-dir "${DATA_DIR}" --create-home --shell /usr/sbin/nologin "${APP_USER}"
    vert "Utilisateur créé."
fi
install -d -o "${APP_USER}" -g "${APP_USER}" -m 750 "${DATA_DIR}"

# ---- 3. PostgreSQL : rôle + base --------------------------------------------
etape "3/7 PostgreSQL"
systemctl enable --now postgresql >/dev/null 2>&1 || true

# Mot de passe : hexadécimal uniquement. Un mot de passe contenant @ : / ? # % &
# devrait être percent-encodé dans l'URL de connexion — on s'épargne le piège.
role_existe="$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" || true)"
if [[ "${role_existe}" == "1" ]]; then
    echo "Rôle « ${DB_USER} » déjà présent — mot de passe conservé."
    if [[ ! -f "${ENV_FILE}" ]]; then
        rouge "ERREUR : le rôle existe mais ${ENV_FILE} est absent."
        echo "Le mot de passe de la base est irrécupérable. Deux options :"
        echo "  - restaurer ${ENV_FILE} depuis une sauvegarde ;"
        echo "  - réattribuer un mot de passe :"
        echo "      sudo -u postgres psql -c \"ALTER ROLE ${DB_USER} WITH PASSWORD 'nouveau';\""
        exit 1
    fi
    DB_PASS="$(grep -oP '(?<=://'"${DB_USER}"':)[^@]+' "${ENV_FILE}" | head -n1)"
else
    DB_PASS="$(openssl rand -hex 16)"
    sudo -u postgres psql -qc "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}';"
    vert "Rôle « ${DB_USER} » créé."
fi

base_existe="$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" || true)"
if [[ "${base_existe}" == "1" ]]; then
    echo "Base « ${DB_NAME} » déjà présente — conservée telle quelle."
else
    sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
    vert "Base « ${DB_NAME} » créée."
fi

# ---- 4. Code applicatif ------------------------------------------------------
etape "4/7 Code applicatif"
install -d -o "${APP_USER}" -g "${APP_USER}" -m 755 "${APP_DIR}"
# --delete garde /opt propre d'une version à l'autre, mais .venv et les données
# vivent hors de la zone synchronisée : ils survivent à une mise à jour.
rsync -a --delete \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude 'logs/' \
    --exclude 'cv_pdfs/' \
    --exclude 'dist/' \
    --exclude 'build/' \
    --exclude 'iso/' \
    --exclude '.env' \
    "${REPO_DIR}/" "${APP_DIR}/"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
vert "Code synchronisé dans ${APP_DIR}."

# ---- 5. Environnement Python -------------------------------------------------
etape "5/7 Environnement Python"
if [[ ! -x "${APP_DIR}/.venv/bin/python" ]]; then
    sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
fi
# requirements-docker.txt et non requirements.txt : c'est le sous-ensemble RUNTIME
# serveur. requirements.txt tire pystray/pillow/pyinstaller (bureautique et build
# Windows), inutiles ici et sources d'échecs de compilation.
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/python" -m pip install --quiet -r "${APP_DIR}/requirements-docker.txt"
vert "Dépendances installées."

# ---- 6. Fichier d'environnement ---------------------------------------------
etape "6/7 Configuration"
install -d -o root -g "${APP_USER}" -m 750 "${ENV_DIR}"
if [[ -f "${ENV_FILE}" ]]; then
    echo "${ENV_FILE} déjà présent — conservé (secret et mot de passe inchangés)."
else
    # CV_AGENT_SECRET est OBLIGATOIRE hors Windows : il n'y a pas de DPAPI sous Linux.
    # Il chiffre les secrets IMAP/SMTP/API au repos (enc:v2) et stabilise le cookie de
    # session. Le perdre rend les mots de passe stockés indéchiffrables (ils
    # ressortent vides, sans plantage) : à sauvegarder avec la base.
    SECRET="$(openssl rand -hex 32)"
    cat > "${ENV_FILE}" <<EOF
# CV Agent Pro — environnement du service systemd. NE PAS VERSIONNER.
# Généré le $(date '+%Y-%m-%d %H:%M:%S').

CV_AGENT_DB_URL=postgresql://${DB_USER}:${DB_PASS}@127.0.0.1:5432/${DB_NAME}

# Secret partagé : chiffre les secrets au repos + signe le cookie de session.
# À REPORTER À L'IDENTIQUE sur toute autre instance branchée sur cette base.
CV_AGENT_SECRET=${SECRET}

# Fichiers écrits par l'application (cv_pdfs, logs). La base vit dans PostgreSQL.
CV_AGENT_DATA_DIR=${DATA_DIR}

# Décommentez derrière un reverse-proxy HTTPS (voir ../nginx/).
#CV_AGENT_HTTPS_ONLY=1
EOF
    vert "${ENV_FILE} généré."
fi
chown root:"${APP_USER}" "${ENV_FILE}"
chmod 640 "${ENV_FILE}"

# ---- 7. Service systemd ------------------------------------------------------
etape "7/7 Service systemd"
install -m 644 "${SCRIPT_DIR}/cv-agent.service" "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable "${SERVICE}" >/dev/null
systemctl restart "${SERVICE}"

# Laisser le temps au premier démarrage (création du schéma) avant de juger.
sleep 4
if systemctl is-active --quiet "${SERVICE}"; then
    vert "Service « ${SERVICE} » actif."
else
    rouge "Le service n'est pas actif. Diagnostic :"
    echo "  journalctl -u ${SERVICE} -n 50 --no-pager"
    exit 1
fi

# ---- Pare-feu ----------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow "${PORT}/tcp" >/dev/null && vert "ufw : port ${PORT}/tcp ouvert."
else
    jaune "ufw inactif — port ${PORT} non ouvert automatiquement."
fi

# ---- Fin ---------------------------------------------------------------------
IP="$(hostname -I | awk '{print $1}')"
etape "Installation terminée"
echo "Ouvrez maintenant, pour créer le premier compte administrateur :"
vert "   http://${IP}:${PORT}/setup"
echo
echo "Commandes utiles :"
echo "  systemctl status ${SERVICE}          état du service"
echo "  journalctl -u ${SERVICE} -f          journal en direct"
echo "  systemctl restart ${SERVICE}         redémarrage"
echo "  ${DATA_DIR}/logs/agent.log           journal applicatif (pipeline)"
echo
jaune "SAUVEGARDEZ ${ENV_FILE} : sans CV_AGENT_SECRET, les mots de passe IMAP/SMTP"
jaune "stockés en base deviennent indéchiffrables."
