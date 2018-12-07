FROM python:3.5.3
ENV PYTHONUNBUFFERED 1
RUN mkdir /perma-payments
WORKDIR /perma-payments
ADD perma-payments/requirements.txt /perma-payments/
RUN pip install -U pip; pip install -r requirements.txt
