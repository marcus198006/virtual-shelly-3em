name: "Virtual Shelly 3EM"
version: "1.0.0"
slug: "virtual_shelly_3em"
description: "Virtual Shelly 3EM integration for Home Assistant"
arch:
  - amd64
image: "ghcr.io/marcus198006/virtual-shelly-3em-{arch}"
startup: application
boot: auto
map:
  - share:rw
  - config:rw
options:
  mqtt_host: "localhost"
  mqtt_port: 1883
schema:
  mqtt_host: str
  mqtt_port: int
ports:
  "80/tcp": null  # Adjust if your script exposes a web server


