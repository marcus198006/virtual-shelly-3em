ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY virtual_shelly_3em.py .
COPY run.sh .
RUN chmod +x run.sh

CMD [ "/usr/src/app/run.sh" ]
