FROM python:3.11-slim

WORKDIR /app

# espeak-ng is required by piper-tts for phonemization
RUN apt-get update && apt-get install -y --no-install-recommends \
    espeak-ng \
    libespeak-ng1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/audio /data/models

ENV QUIZ_CONFIG_PATH=/data/config.json
ENV QUIZ_AUDIO_DIR=/data/audio
ENV PIPER_MODELS_DIR=/data/models

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
