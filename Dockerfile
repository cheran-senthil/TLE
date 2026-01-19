





















FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    pkg-config \
    libcairo2-dev \
    libgirepository1.0-dev \
    gir1.2-pango-1.0 \
    libjpeg-dev \
    zlib1g-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Setup environment
ENV FONTCONFIG_FILE=/bot/extra/fonts.conf
ENV PYTHONUNBUFFERED=1

WORKDIR /bot

# Install specific versions that work with Debian 12 (the OS of this image)
# We pin PyGObject to 3.46.0 to avoid the "girepository-2.0" error
RUN pip install --no-cache-dir pycairo==1.25.1 PyGObject==3.46.0

# Copy project files
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy the rest of the code
COPY . .

CMD ["python", "-m", "tle"]
