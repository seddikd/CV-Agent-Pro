# syntax=docker/dockerfile:1
#
# Image « tout-en-un » de CV Agent Pro (serveur web FastAPI/uvicorn).
# Base de données : PostgreSQL (obligatoire, via CV_AGENT_DB_URL). Aucune
# dépendance Windows (DPAPI remplacé par le chiffrement portable enc:v2 via
# CV_AGENT_SECRET, obligatoire ici). Le volume /data ne porte que les fichiers
# (cv_pdfs, logs) ; les données métier vivent dans PostgreSQL.
#
# Recommandé :  docker compose up -d   (application + PostgreSQL fournis ensemble)
# Ou image seule contre un PostgreSQL existant :
#   docker build -t cv-agent-pro:latest .
#   docker run -d -p 6060:6060 -v cvagent-data:/data \
#     -e CV_AGENT_SECRET=<hex> \
#     -e CV_AGENT_DB_URL=postgresql://cvagent:motdepasse@HOTE:5432/cvagent \
#     cv-agent-pro:latest

FROM python:3.12-slim

# Réglages Python conteneur : pas de .pyc, sortie non bufferisée (logs directs).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CV_AGENT_DATA_DIR=/data \
    PORT=6060

WORKDIR /app

# 1) Dépendances d'abord (couche cache indépendante du code applicatif).
#    Les wheels binaires (cryptography, psycopg) s'installent sans toolchain.
COPY requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt

# 2) Code applicatif.
COPY . .

# 3) Utilisateur non-root + volume de données inscriptible.
RUN useradd --create-home --uid 10001 cvagent \
    && mkdir -p /data \
    && chown -R cvagent:cvagent /data /app
USER cvagent

EXPOSE 6060
VOLUME ["/data"]

# Sonde de santé : la page /login doit répondre 200 (sans dépendre de curl).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:6060/login',timeout=4).status==200 else 1)"

# Un seul worker : invariant du projet (APScheduler + écriture DB mono-process).
CMD ["python", "-m", "uvicorn", "webapp:app", "--host", "0.0.0.0", "--port", "6060", "--workers", "1"]
