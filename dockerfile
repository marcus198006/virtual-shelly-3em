FROM alpine:3.18

# Python installieren
RUN apk add --no-cache python3 py3-pip

WORKDIR /usr/src/app

# Python Dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Dein Script kopieren
COPY virtual_shelly_3em.py .
COPY run.sh .
RUN chmod +x run.sh

# Startbefehl
CMD [ "/usr/src/app/run.sh" ]

