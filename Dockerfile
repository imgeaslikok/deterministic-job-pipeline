FROM python:3.12-slim

WORKDIR /code

RUN pip install --no-cache-dir -U pip

COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt

COPY . /code