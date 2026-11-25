# IOT-166 : image unique des services Edge, Cloud et du simulateur de capteurs.
# Chaque service de docker-compose.yml choisit sa commande.
FROM python:3.14.6-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY models/device_model.joblib models/device_model.joblib

# Journaux Edge et Cloud : volumes nommés montés par docker-compose.yml
RUN mkdir -p /data/edge /data/cloud
