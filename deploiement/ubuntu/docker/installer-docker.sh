#!/usr/bin/env bash
#
# CV Agent Pro — installation par Docker Compose sur Ubuntu (mode recommandé).
#
# Installe Docker CE + le plugin compose depuis le dépôt officiel Docker (celui
# d'Ubuntu fournit un docker.io souvent trop ancien pour « docker compose »),
# génère le .env s'il manque, puis construit et démarre application + PostgreSQL.
#
# USAGE (depuis une copie du dépôt) :
#   sudo ./deploiement/ubuntu/docker/installer-docker.sh
#
# Idempotent : ré-exécutable. Un .env existant n'est jamais écrasé.

set -euo pipefail

PORT="6060"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
ENV_FILE="${REPO_DIR}/.env"

vert() { printf '\033[32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[33m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[36m=== %s ===\033[0m\n' "$*"; }

if [[ "${EUID}" -ne 0 ]]; then
    rouge "ERREUR : lancez ce script avec sudo (installation de paquets)."
    exit 1
fi

if [[ ! -f "${REPO_DIR}/docker-compose.yml" ]]; then
    rouge "ERREUR : docker-compose.yml introuvable dans ${REPO_DIR}."
    exit 1
fi

etape "CV Agent Pro — installation Docker sur Ubuntu"
echo "Dépôt : ${REPO_DIR}"

# ---- 1. Docker ---------------------------------------------------------------
etape "1/4 Docker"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "Docker et le plugin compose sont déjà présents."
else
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg openssl

    install -m 0755 -d /etc/apt/keyrings
    if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    vert "Docker installé."
fi

# Confort : permettre à l'utilisateur appelant de piloter docker sans sudo.
if [[ -n "${SUDO_USER:-}" ]] && ! id -nG "${SUDO_USER}" | grep -qw docker; then
    usermod -aG docker "${SUDO_USER}"
    jaune "« ${SUDO_USER} » ajouté au groupe docker — déconnexion/reconnexion nécessaire pour en profiter."
fi

# ---- 2. Fichier .env ---------------------------------------------------------
etape "2/4 Configuration (.env)"
if [[ -f "${ENV_FILE}" ]]; then
    echo ".env déjà présent — conservé tel quel."
else
    # Mots de passe hexadécimaux : ni @ ni : ni / ni ? ni # ni % ni &, qui
    # devraient sinon être percent-encodés dans CV_AGENT_DB_URL.
    POSTGRES_PASSWORD="$(openssl rand -hex 16)"
    CV_AGENT_SECRET="$(openssl rand -hex 32)"
    cat > "${ENV_FILE}" <<EOF
# CV Agent Pro — généré le $(date '+%Y-%m-%d %H:%M:%S'). NE PAS VERSIONNER.
CV_AGENT_SECRET=${CV_AGENT_SECRET}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
EOF
    chmod 600 "${ENV_FILE}"
    vert ".env généré (secrets aléatoires)."
fi

# ---- 3. Construction et démarrage --------------------------------------------
etape "3/4 Construction de l'image et démarrage"
cd "${REPO_DIR}"
# docker-compose.override.yml est une surcharge POSTE WINDOWS (elle publie la base
# sur la loopback pour l'exécution native). Sous Ubuntu elle n'a pas lieu d'être :
# on la neutralise en désignant explicitement le seul fichier voulu.
docker compose -f docker-compose.yml build
docker compose -f docker-compose.yml up -d

# ---- 4. Vérification ---------------------------------------------------------
etape "4/4 Vérification"
echo "Attente du démarrage (création du schéma au premier lancement)..."
ok=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/login" 2>/dev/null; then
        ok=1
        break
    fi
    sleep 2
done

if [[ "${ok}" -ne 1 ]]; then
    rouge "L'application ne répond pas encore sur le port ${PORT}. Diagnostic :"
    echo "  docker compose -f docker-compose.yml logs --tail 50 app"
    exit 1
fi
vert "Application opérationnelle."

# ---- Pare-feu ----------------------------------------------------------------
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow "${PORT}/tcp" >/dev/null && vert "ufw : port ${PORT}/tcp ouvert."
else
    jaune "ufw inactif — port ${PORT} non ouvert automatiquement."
fi

IP="$(hostname -I | awk '{print $1}')"
etape "Installation terminée"
echo "Créez le premier compte administrateur :"
vert "   http://${IP}:${PORT}/setup"
echo
echo "Commandes utiles (depuis ${REPO_DIR}) :"
echo "  docker compose -f docker-compose.yml ps          état des conteneurs"
echo "  docker compose -f docker-compose.yml logs -f app journal applicatif"
echo "  ./deploiement/ubuntu/docker/sauvegarde.sh        sauvegarde base + fichiers"
echo "  ./deploiement/ubuntu/docker/maj.sh               mise à jour"
echo
jaune "SAUVEGARDEZ ${ENV_FILE} : sans CV_AGENT_SECRET, les mots de passe IMAP/SMTP"
jaune "stockés en base deviennent indéchiffrables."
