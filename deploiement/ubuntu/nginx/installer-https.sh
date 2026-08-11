#!/usr/bin/env bash
#
# CV Agent Pro — reverse-proxy Nginx + certificat Let's Encrypt.
#
# Pose le vhost, obtient le certificat via certbot, active la redirection HTTP→HTTPS
# puis rappelle les deux réglages sans lesquels le HTTPS reste contournable.
#
# PRÉREQUIS :
#   - CV Agent déjà installé et joignable sur 127.0.0.1:6060 (Docker ou natif) ;
#   - un nom de domaine pointant (enregistrement A/AAAA) sur l'IP publique ;
#   - les ports 80 et 443 ouverts — certbot valide le domaine via le port 80.
#
# USAGE :
#   sudo ./installer-https.sh cv.mon-entreprise.fr admin@mon-entreprise.fr

set -euo pipefail

DOMAINE="${1:-}"
EMAIL="${2:-}"
PORT="6060"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

vert() { printf '\033[32m%s\033[0m\n' "$*"; }
jaune() { printf '\033[33m%s\033[0m\n' "$*"; }
rouge() { printf '\033[31m%s\033[0m\n' "$*"; }
etape() { printf '\n\033[36m=== %s ===\033[0m\n' "$*"; }

if [[ "${EUID}" -ne 0 ]]; then
    rouge "ERREUR : lancez ce script avec sudo."
    exit 1
fi
if [[ -z "${DOMAINE}" || -z "${EMAIL}" ]]; then
    rouge "USAGE : $0 <domaine> <email>"
    echo "  exemple : $0 cv.mon-entreprise.fr admin@mon-entreprise.fr"
    exit 1
fi

etape "Reverse-proxy HTTPS pour ${DOMAINE}"

# ---- 0. L'application répond-elle ? ------------------------------------------
if ! curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/login" 2>/dev/null; then
    rouge "ERREUR : rien ne répond sur http://127.0.0.1:${PORT}."
    echo "Installez et démarrez CV Agent avant de poser le proxy."
    exit 1
fi
vert "Application joignable sur 127.0.0.1:${PORT}."

# ---- 1. Paquets ---------------------------------------------------------------
etape "1/4 Nginx et certbot"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx
vert "Paquets installés."

# ---- 2. Vhost -----------------------------------------------------------------
etape "2/4 Configuration du site"
CIBLE="/etc/nginx/sites-available/cv-agent"
sed "s/__DOMAINE__/${DOMAINE}/g" "${SCRIPT_DIR}/cv-agent.conf" > "${CIBLE}"
ln -sf "${CIBLE}" /etc/nginx/sites-enabled/cv-agent

# Le site par défaut capterait les requêtes en tant que serveur par défaut.
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
    jaune "Site « default » de Nginx désactivé."
fi

nginx -t
systemctl reload nginx
vert "Vhost actif (HTTP)."

# ---- 3. Certificat ------------------------------------------------------------
etape "3/4 Certificat Let's Encrypt"
# --redirect : certbot ajoute lui-même la redirection 80 → 443 dans le vhost.
certbot --nginx \
    -d "${DOMAINE}" \
    --non-interactive \
    --agree-tos \
    --email "${EMAIL}" \
    --redirect
vert "Certificat obtenu et redirection HTTP→HTTPS en place."

# Le renouvellement est assuré par le timer systemd installé avec certbot.
systemctl enable --now certbot.timer >/dev/null 2>&1 || true
echo "Renouvellement automatique : $(systemctl is-active certbot.timer 2>/dev/null || echo 'timer certbot à vérifier')"

# ---- 4. Fermeture du port applicatif -----------------------------------------
etape "4/4 Fermeture de l'accès direct au port ${PORT}"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true
    ufw allow 'Nginx Full' >/dev/null 2>&1 || true
    vert "ufw : ${PORT} fermé au réseau, 80/443 ouverts."
else
    jaune "ufw inactif : le port ${PORT} reste peut-être joignable en direct."
    jaune "Tant qu'il l'est, le HTTPS se contourne en visant http://<ip>:${PORT}."
fi

# ---- Rappels ------------------------------------------------------------------
etape "Terminé"
vert "https://${DOMAINE}"
echo
jaune "DEUX RÉGLAGES RESTENT À VÉRIFIER :"
echo
echo "1) Drapeau Secure sur le cookie de session — CV_AGENT_HTTPS_ONLY=1"
echo "   Docker : ajoutez la ligne au .env, puis"
echo "            docker compose -f docker-compose.yml up -d"
echo "   Natif  : décommentez la ligne dans /etc/cv-agent/cv-agent.env, puis"
echo "            sudo systemctl restart cv-agent"
echo
echo "2) L'application ne doit plus écouter sur toutes les interfaces."
echo "   Docker : remplacez  \"6060:6060\"  par  \"127.0.0.1:6060:6060\""
echo "            dans docker-compose.yml (section ports du service app)."
echo "   Natif  : remplacez  --host 0.0.0.0  par  --host 127.0.0.1"
echo "            dans /etc/systemd/system/cv-agent.service, puis"
echo "            sudo systemctl daemon-reload && sudo systemctl restart cv-agent"
