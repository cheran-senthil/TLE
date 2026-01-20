FROM python:3.11-slim

# Install build tools and development libraries
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

# Setup environment variables
ENV FONTCONFIG_FILE=/bot/extra/fonts.conf
ENV PYTHONUNBUFFERED=1

WORKDIR /bot

# Install dependencies with specific versions to prevent build errors
RUN pip install --no-cache-dir pycairo==1.25.1 PyGObject==3.46.0

# Copy project files and install the bot
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy the rest of the code
COPY . .

# FIX: Downgrade Pillow to fix 'getsize' AttributeError
RUN pip install --no-cache-dir "Pillow<10.0.0"

CMD ["python", "-m", "tle"]
