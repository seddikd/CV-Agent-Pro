#!/usr/bin/env bash
#
# CV Agent Pro — sauvegarde d'un déploiement Docker.
#
# Produit une archive horodatée contenant les TROIS éléments indispensables :
#   1. le dump PostgreSQL (candidats, réglages, utilisateurs, historique) ;
#   2. le volume de fichiers /data (cv_pdfs, logs) ;
#   3. le .env — sans CV_AGENT_SECRET, les mots de passe IMAP/SMTP du dump
#      restent chiffrés en enc:v2 et sont définitivement illisibles.
#
# USAGE :
#   ./sauvegarde.sh [dossier_destination]      (défaut : ./sauvegardes)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
DEST="${1:-${REPO_DIR}/sauvegardes}"
HORODATAGE="$(date '+%Y%m%d-%H%M%S')"
TRAVAIL="$(mktemp -d)"
trap 'rm -rf "${TRAVAIL}"' EXIT

vert() { printf '\033[32m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }

cd "${REPO_DIR}"
COMPOSE="docker compose -f docker-compose.yml"

if ! ${COMPOSE} ps --status running --services 2>/dev/null | grep -q '^db$'; then
    rouge "ERREUR : le conteneur « db » ne tourne pas — impossible de sauvegarder."
    echo "  ${COMPOSE} up -d db"
    exit 1
fi

mkdir -p "${DEST}"

# ---- 1. Base ------------------------------------------------------------------
# Format « custom » (-Fc) : compressé et restaurable sélectivement par pg_restore.
echo "[1/3] Dump PostgreSQL..."
${COMPOSE} exec -T db pg_dump -U cvagent -d cvagent -Fc > "${TRAVAIL}/base.dump"
vert "      $(du -h "${TRAVAIL}/base.dump" | cut -f1)"

# ---- 2. Fichiers --------------------------------------------------------------
# Le volume est lu depuis le conteneur applicatif : pas besoin de connaître le
# chemin réel du volume sur l'hôte, ni d'être root.
echo "[2/3] Fichiers /data (cv_pdfs, logs)..."
${COMPOSE} exec -T app tar czf - -C /data --exclude='./import' . > "${TRAVAIL}/data.tar.gz"
vert "      $(du -h "${TRAVAIL}/data.tar.gz" | cut -f1)"

# ---- 3. Configuration ---------------------------------------------------------
echo "[3/3] Configuration (.env)..."
if [[ -f "${REPO_DIR}/.env" ]]; then
    cp "${REPO_DIR}/.env" "${TRAVAIL}/env"
else
    rouge "AVERTISSEMENT : .env introuvable — la sauvegarde sera INEXPLOITABLE"
    rouge "pour les secrets chiffrés (mots de passe IMAP/SMTP)."
fi

# ---- Archive ------------------------------------------------------------------
ARCHIVE="${DEST}/cv-agent-${HORODATAGE}.tar.gz"
tar czf "${ARCHIVE}" -C "${TRAVAIL}" .
# Contient le secret de chiffrement : lisible par le seul propriétaire.
chmod 600 "${ARCHIVE}"

vert "Sauvegarde terminée : ${ARCHIVE}  ($(du -h "${ARCHIVE}" | cut -f1))"
echo "Restauration :  ./restauration.sh \"${ARCHIVE}\""
