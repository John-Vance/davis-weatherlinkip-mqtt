ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN pip3 install --no-cache-dir paho-mqtt pyvantagepro

COPY davis2mqtt.py /app/davis2mqtt.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
