 FROM python:3.6.1
 ENV PYTHONUNBUFFERED 1
 RUN mkdir /perma-payments
 WORKDIR /perma-payments
 ADD perma-payments/ /perma-payments/
 RUN pip install -r requirements.txt
