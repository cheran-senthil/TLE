FROM ubuntu:20.04
USER root
WORKDIR /TLE

ENV PYTHON_VERSION = 3.7.16

RUN apt-get update
RUN apt-get install -y git apt-utils sqlite3 make curl
RUN DEBIAN_FRONTEND="noninteractive" apt-get install -y libcairo2-dev libgirepository1.0-dev libpango1.0-dev pkg-config python3-dev gir1.2-pango-1.0 python3.8-venv libpython3.8-dev libjpeg-dev zlib1g-dev python3-pip
RUN apt-get install -y --no-install-recommends make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev wget ca-certificates curl llvm libncurses5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev mecab-ipadic-utf8 git

# Install pyenv dependencies
RUN git clone https://github.com/pyenv/pyenv.git .pyenv
ENV HOME /TLE
ENV PYENV_ROOT $HOME/.pyenv
ENV PATH $PYENV_ROOT/shims:$PYENV_ROOT/bin:$PATH

RUN pyenv install 3.7.16
RUN pyenv global 3.7.16
RUN pyenv rehash

RUN python -m pip install poetry

COPY ./poetry.lock ./poetry.lock
COPY ./pyproject.toml ./pyproject.toml

RUN python -m poetry install

COPY . .

ENTRYPOINT ["/TLE/run.sh"]

