#!/usr/bin/env bash
#
# CV Agent Pro — désinstallation du déploiement natif Ubuntu.
#
# Retire par défaut : service systemd, code (/opt/cv-agent), règle ufw.
# CONSERVE par défaut : la base PostgreSQL, les données (/var/lib/cv-agent) et
# le fichier d'environnement — c'est-à-dire tout ce qui est irremplaçable.
#
# USAGE :
#   sudo ./desinstaller-natif.sh              # retrait applicatif, données gardées
#   sudo ./desinstaller-natif.sh --tout       # TOUT supprimer, base comprise

set -euo pipefail

APP_USER="cvagent"
APP_DIR="/opt/cv-agent"
DATA_DIR="/var/lib/cv-agent"
ENV_DIR="/etc/cv-agent"
DB_NAME="cvagent"
DB_USER="cvagent"
SERVICE="cv-agent"
PORT="6060"

TOUT=0
[[ "${1:-}" == "--tout" ]] && TOUT=1

vert() { printf '\033[32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[33m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }

if [[ "${EUID}" -ne 0 ]]; then
    rouge "ERREUR : lancez ce script avec sudo."
    exit 1
fi

if [[ "${TOUT}" -eq 1 ]]; then
    rouge "MODE --tout : la base « ${DB_NAME} », ${DATA_DIR} et ${ENV_DIR} vont être SUPPRIMÉS."
    jaune "Tous les candidats, CV et réglages seront définitivement perdus."
    echo
    read -r -p "Tapez exactement SUPPRIMER pour confirmer : " reponse
    if [[ "${reponse}" != "SUPPRIMER" ]]; then
        echo "Annulé — rien n'a été touché."
        exit 0
    fi
fi

# ---- Service -----------------------------------------------------------------
if systemctl list-unit-files | grep -q "^${SERVICE}.service"; then
    systemctl disable --now "${SERVICE}" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/${SERVICE}.service"
    systemctl daemon-reload
    vert "Service ${SERVICE} retiré."
fi

# ---- Code --------------------------------------------------------------------
if [[ -d "${APP_DIR}" ]]; then
    rm -rf "${APP_DIR}"
    vert "${APP_DIR} supprimé."
fi

# ---- Pare-feu ----------------------------------------------------------------
if command -v ufw >/dev/null 2>&1; then
    ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true
fi

# ---- Données (uniquement en --tout) ------------------------------------------
if [[ "${TOUT}" -eq 1 ]]; then
    sudo -u postgres dropdb --if-exists "${DB_NAME}"
    sudo -u postgres psql -qc "DROP ROLE IF EXISTS ${DB_USER};" || true
    rm -rf "${DATA_DIR}" "${ENV_DIR}"
    id -u "${APP_USER}" >/dev/null 2>&1 && userdel "${APP_USER}" 2>/dev/null || true
    vert "Base, données et configuration supprimées."
else
    echo
    jaune "CONSERVÉS (suppression volontairement non automatique) :"
    echo "  base PostgreSQL « ${DB_NAME} »   →  sudo -u postgres dropdb ${DB_NAME}"
    echo "  données ${DATA_DIR}"
    echo "  configuration ${ENV_DIR}  (contient CV_AGENT_SECRET — à archiver)"
fi

vert "Désinstallation terminée."
