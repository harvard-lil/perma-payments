FROM debian:stretch-20180426
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_BINARY=:all: \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_SRC=/usr/local/src \
    PIPENV_HIDE_EMOJIS=true \
    PIPENV_NOSPIN=true
RUN mkdir /perma-payments
WORKDIR /perma-payments

# Get build dependencies and packages required by the app
RUN apt-get update \
    && apt-get install -y python3-pip \
    && apt-get install -y python3-dev \
    && apt-get install -y python3-virtualenv \
    && apt-get install -y git \
    \
    && apt-get install -y libffi-dev \
    && apt-get install -y libssl-dev\
    && apt-get install -y libpq-dev \
    && apt-get install -y postgresql-client

# python requirements via pipenv.
# to access the virtualenv, invoke python like this: `pipenv run python`
# COPY Pipfile though it is ignored, per https://github.com/pypa/pipenv/issues/2834
COPY Pipfile /perma-payments
COPY Pipfile.lock /perma-payments
RUN pip3 install -U pip \
    && pip install pipenv \
    && pipenv --python 3.5 install --ignore-pipfile --dev

# dev personalizations / try installing packages without rebuilding everything
RUN apt-get install -y nano

COPY . /perma-payments
