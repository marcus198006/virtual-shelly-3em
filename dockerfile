ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip
WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY virtual_shelly_3em.py .
COPY run.sh .
RUN chmod +x run.sh

CMD [ "/usr/src/app/run.sh" ]
