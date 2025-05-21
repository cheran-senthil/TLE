# ---------- build stage ----------
FROM python:3.12-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config gcc \
        libcairo2-dev libgirepository1.0-dev gir1.2-pango-1.0 \
        libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /bot
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# ---------- runtime stage ----------
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 gir1.2-pango-1.0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /bot
COPY --from=build /usr/local /usr/local
COPY --from=build /bot /bot

# Font-config file used by matplotlib / cairo
ENV FONTCONFIG_FILE=/bot/extra/fonts.conf
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "tle"]
