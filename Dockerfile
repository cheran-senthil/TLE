FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libcairo2-dev gir1.2-pango-1.0 libgirepository-2.0-dev \
    gobject-introspection  \
    libjpeg-dev zlib1g-dev \
    build-essential cmake gcc meson \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/usr/lib/python3/dist-packages
ENV FONTCONFIG_FILE=/bot/extra/fonts.conf
ENV PYTHONUNBUFFERED=1

WORKDIR /bot
COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

CMD ["python", "-m", "tle"]
