# ---------- builder stage ----------
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2-dev libgirepository-2.0-dev \
    build-essential cmake gcc meson \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/usr/lib/python3/dist-packages

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# ---------- runtime stage ----------
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 gir1.2-pango-1.0 gobject-introspection \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY --from=builder /usr/lib/python3/dist-packages /usr/lib/python3/dist-packages

ENV PYTHONPATH=/usr/lib/python3/dist-packages
ENV PYTHONUNBUFFERED=1

RUN useradd -m botuser
WORKDIR /bot
COPY . .
RUN mkdir -p /bot/data && chown -R botuser:botuser /bot
USER botuser

CMD ["python", "-m", "tle"]
