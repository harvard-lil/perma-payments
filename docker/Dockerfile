FROM python:3.7-buster
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_SRC=/usr/local/src

RUN mkdir -p /app/web
WORKDIR /app/web

# Get build dependencies and packages required by the app
RUN apt-get update && apt-get install -y postgresql-client

# pip
COPY web/requirements.txt /app/web
RUN pip install -r requirements.txt \
    && rm requirements.txt

# dev personalizations / try installing packages without rebuilding everything
RUN apt-get install -y nano

COPY web /app/web
