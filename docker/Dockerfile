FROM registry.lil.tools/library/python:3.11-bookworm
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

# Install Stripe CLI for webhook forwarding in live tests
RUN curl -s https://packages.stripe.dev/api/security/keypair/stripe-cli-gpg/public | gpg --dearmor | tee /usr/share/keyrings/stripe.gpg > /dev/null \
    && echo "deb [signed-by=/usr/share/keyrings/stripe.gpg] https://packages.stripe.dev/stripe-cli-debian-local stable main" | tee /etc/apt/sources.list.d/stripe.list \
    && apt-get update \
    && apt-get install -y stripe

# Install ngrok for tunneling in live tests
RUN curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | tee /etc/apt/trusted.gpg.d/ngrok.asc > /dev/null \
    && echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" | tee /etc/apt/sources.list.d/ngrok.list \
    && apt-get update \
    && apt-get install -y ngrok

# pip
COPY web/requirements.txt /app/web
RUN pip install -r requirements.txt \
    && rm requirements.txt

# dev personalizations / try installing packages without rebuilding everything
RUN apt-get update && apt-get install -y nano

COPY web /app/web
