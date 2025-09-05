#!/usr/bin/env bash
cd /usr/src/app
# Config-Werte von HA-Add-on nach env
export VENUS_IP="$(bashio::config 'venus_ip')"
export EMULATION_PROTOCOL="$(bashio::config 'protocol')"

# Konfig-Datei generieren
cat > config.yaml <<EOF
mqtt:
  host: 192.168.178.23
  port: 1883
  username: ""
  password: ""
  topics:
    net_power_w: "home/energy/net_power_w"
  formats:
    net_power_w: { json_key: "value" }

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
