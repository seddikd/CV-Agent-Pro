#!/usr/bin/env bash
#
# CV Agent Pro — restauration d'une archive produite par sauvegarde.sh.
#
# ATTENTION : opération destructrice. La base courante est ÉCRASÉE par celle de
# l'archive. Le script exige une confirmation explicite.
#
# USAGE :
#   ./restauration.sh /chemin/cv-agent-20260812-101500.tar.gz

set -euo pipefail

ARCHIVE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
TRAVAIL="$(mktemp -d)"
trap 'rm -rf "${TRAVAIL}"' EXIT

vert() { printf '\033[32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[33m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }

if [[ -z "${ARCHIVE}" || ! -f "${ARCHIVE}" ]]; then
    rouge "USAGE : $0 /chemin/vers/cv-agent-AAAAMMJJ-HHMMSS.tar.gz"
    exit 1
fi

cd "${REPO_DIR}"
COMPOSE="docker compose -f docker-compose.yml"

tar xzf "${ARCHIVE}" -C "${TRAVAIL}"
if [[ ! -f "${TRAVAIL}/base.dump" ]]; then
    rouge "ERREUR : archive invalide (base.dump absent)."
    exit 1
fi

rouge "La base « cvagent » actuelle va être ÉCRASÉE par le contenu de l'archive."
jaune "Archive : ${ARCHIVE}"
echo
read -r -p "Tapez exactement RESTAURER pour confirmer : " reponse
if [[ "${reponse}" != "RESTAURER" ]]; then
    echo "Annulé — rien n'a été modifié."
    exit 0
fi

# ---- 0. Configuration ---------------------------------------------------------
# Restaurée EN PREMIER : le conteneur applicatif doit redémarrer avec le
# CV_AGENT_SECRET d'origine, sinon les secrets du dump seront indéchiffrables.
if [[ -f "${TRAVAIL}/env" ]]; then
    if [[ -f "${REPO_DIR}/.env" ]] && ! cmp -s "${TRAVAIL}/env" "${REPO_DIR}/.env"; then
        cp "${REPO_DIR}/.env" "${REPO_DIR}/.env.avant-restauration"
        jaune "Ancien .env conservé sous .env.avant-restauration"
    fi
    cp "${TRAVAIL}/env" "${REPO_DIR}/.env"
    chmod 600 "${REPO_DIR}/.env"
    vert "[0/3] .env restauré."
else
    jaune "[0/3] Pas de .env dans l'archive — le secret courant est conservé."
fi

# ---- 1. Base ------------------------------------------------------------------
echo "[1/3] Restauration PostgreSQL..."
# L'application doit être arrêtée : une écriture concurrente pendant le
# rechargement corromprait l'état (et le planificateur tournerait sur une base
# à moitié restaurée).
${COMPOSE} stop app >/dev/null
${COMPOSE} up -d db >/dev/null
# Attendre que la base accepte les connexions.
for _ in $(seq 1 30); do
    ${COMPOSE} exec -T db pg_isready -U cvagent -d cvagent >/dev/null 2>&1 && break
    sleep 1
done
# --clean --if-exists : supprime les objets existants avant de les recréer, ce qui
# rend la restauration reproductible sur une base non vide.
${COMPOSE} exec -T db pg_restore -U cvagent -d cvagent --clean --if-exists --no-owner \
    < "${TRAVAIL}/base.dump"
vert "      Base restaurée."

# ---- 2. Fichiers --------------------------------------------------------------
if [[ -f "${TRAVAIL}/data.tar.gz" ]]; then
    echo "[2/3] Restauration des fichiers /data..."
    ${COMPOSE} run --rm -T --entrypoint sh app -c 'tar xzf - -C /data' < "${TRAVAIL}/data.tar.gz"
    vert "      Fichiers restaurés."
else
    jaune "[2/3] Pas de data.tar.gz dans l'archive — étape ignorée."
fi

# ---- 3. Redémarrage -----------------------------------------------------------
echo "[3/3] Redémarrage..."
${COMPOSE} up -d >/dev/null
vert "Restauration terminée."
echo "Vérifiez :  ${COMPOSE} logs --tail 30 app"
