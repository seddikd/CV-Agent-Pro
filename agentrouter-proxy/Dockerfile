FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /proxy
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY proxy.py ./
RUN useradd --create-home --uid 10001 cvproxy

EXPOSE 7187
USER cvproxy
CMD ["python", "proxy.py"]
