#!/usr/bin/env bash
cd /usr/src/app

# Config-Werte aus HA Add-on UI
export VENUS_IP="$(bashio::config 'venus_ip')"
export EMULATION_PROTOCOL="$(bashio::config 'protocol')"
export MQTT_USERNAME="$(bashio::config 'mqtt_username')"
export MQTT_PASSWORD="$(bashio::config 'mqtt_password')"
export MQTT_HOST="$(bashio::config 'mqtt_host')"
export MQTT_PORT="$(bashio::config 'mqtt_port')"

# Topics von HA / Tasmota / Solaredge
export TOPIC_NET="$(bashio::config 'topics.net_power_w')"
export TOPIC_PV="$(bashio::config 'topics.pv_production_w')"
export TOPIC_FEED="$(bashio::config 'topics.net_feed_power')"

# Konfig-Datei generieren
cat > config.yaml <<EOF
mqtt:
  host: "${MQTT_HOST}"
  port: ${MQTT_PORT}
  username: "${MQTT_USERNAME}"
  password: "${MQTT_PASSWORD}"
  topics:
    net_power_w: "${TOPIC_NET}"
    pv_production_w: "${TOPIC_PV}"
    net_feed_power: "${TOPIC_FEED}"
  formats:
    net_power_w: { json_key: "value" }
    pv_production_w: { json_key: "value" }
    net_feed_power: { json_key: "value" }

venus:
  ip: "${VENUS_IP}"
  port_rpc: 1010
  port_coiot: 5683

emulation:
  protocol: "${EMULATION_PROTOCOL}"
  interval_s: 2.0
  device_id: "shellypro3em-FAKE123456"

debug:
  listen_udp_1010: false
  listen_udp_5683: false
EOF

exec python3 virtual_shelly_3em.py
