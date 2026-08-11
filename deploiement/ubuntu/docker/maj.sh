#!/usr/bin/env bash
#
# CV Agent Pro — mise à jour d'un déploiement Docker.
#
# Enchaîne : sauvegarde préalable → récupération du code → reconstruction de
# l'image → redémarrage → contrôle de santé. En cas d'échec du contrôle, le
# chemin de retour arrière est affiché (l'archive vient d'être créée).
#
# Le schéma de base est mis à jour tout seul au démarrage (state_db.init() est
# idempotent) : aucune migration manuelle à lancer.
#
# USAGE :
#   ./maj.sh              # git pull + rebuild + restart
#   ./maj.sh --sans-git   # rebuild seul (code déjà à jour sur la machine)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PORT="6060"
SANS_GIT=0
[[ "${1:-}" == "--sans-git" ]] && SANS_GIT=1

vert() { printf '\033[32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[33m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[36m=== %s ===\033[0m\n' "$*"; }

cd "${REPO_DIR}"
COMPOSE="docker compose -f docker-compose.yml"

# ---- 1. Sauvegarde préalable --------------------------------------------------
etape "1/4 Sauvegarde préalable"
"${SCRIPT_DIR}/sauvegarde.sh"
DERNIERE="$(ls -1t "${REPO_DIR}/sauvegardes/"cv-agent-*.tar.gz 2>/dev/null | head -n1 || true)"

# ---- 2. Code ------------------------------------------------------------------
etape "2/4 Récupération du code"
if [[ "${SANS_GIT}" -eq 1 ]]; then
    echo "Ignoré (--sans-git)."
elif [[ -d "${REPO_DIR}/.git" ]]; then
    AVANT="$(git rev-parse --short HEAD)"
    git pull --ff-only
    APRES="$(git rev-parse --short HEAD)"
    if [[ "${AVANT}" == "${APRES}" ]]; then
        echo "Déjà à jour (${APRES})."
    else
        vert "${AVANT} → ${APRES}"
    fi
else
    jaune "Pas de dépôt git ici — étape ignorée."
fi

# ---- 3. Reconstruction --------------------------------------------------------
etape "3/4 Reconstruction et redémarrage"
${COMPOSE} build
${COMPOSE} up -d

# ---- 4. Contrôle de santé -----------------------------------------------------
etape "4/4 Contrôle de santé"
ok=0
for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/login" 2>/dev/null; then
        ok=1
        break
    fi
    sleep 2
done

if [[ "${ok}" -ne 1 ]]; then
    rouge "ÉCHEC : l'application ne répond plus sur le port ${PORT}."
    echo "  ${COMPOSE} logs --tail 60 app"
    if [[ -n "${DERNIERE}" ]]; then
        echo
        jaune "Retour arrière possible avec la sauvegarde faite à l'étape 1 :"
        echo "  git checkout ${AVANT:-<commit précédent>}"
        echo "  ${SCRIPT_DIR}/restauration.sh \"${DERNIERE}\""
    fi
    exit 1
fi

vert "Mise à jour terminée — application opérationnelle."
${COMPOSE} ps
