FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 gir1.2-pango-1.0 \
    gobject-introspection python3-gi python3-gi-cairo python3-cairo \
    libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/usr/lib/python3/dist-packages
ENV FONTCONFIG_FILE=/bot/extra/fonts.conf
ENV PYTHONUNBUFFERED=1

WORKDIR /bot
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

CMD ["python", "-m", "tle"]
