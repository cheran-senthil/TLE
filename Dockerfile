FROM ubuntu:18.04
USER root
RUN apt-get update
RUN apt-get -y install git

COPY . /TLE
COPY ./environment.template /TLE/environment

RUN apt-get install -y libcairo2-dev
RUN apt-get install -y libgirepository1.0-dev 
RUN apt-get install -y libpango1.0-dev 
RUN apt-get install -y pkg-config 
RUN apt-get install -y python3-dev 
RUN apt-get install -y gir1.2-pango-1.0
RUN apt-get install -y python3.8-venv
RUN apt-get install -y libpython3.8-dev
RUN apt-get install -y libjpeg-dev
RUN apt-get install -y zlib1g-dev
RUN apt-get -y install python3-pip
RUN python3.8 -m pip install poetry
RUN cd /TLE && python3.8 -m poetry install

ENTRYPOINT ["/TLE/run.sh"]
