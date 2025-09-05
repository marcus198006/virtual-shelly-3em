#!/usr/bin/env python3
# Virtual Shelly Pro 3EM (PoC) — MQTT → UDP (RPC/CoIoT) bridge
#
# ⚠️ Proof of Concept:
# - Sends Shelly-like status packets towards a Marstek Venus (or listens for basic requests) without a real Shelly.
# - You MUST test and likely adapt field names/structures to match what your Venus expects.
# - Supports two wire protocols (toggle in config):
#   1) "rpc1010": JSON-RPC-like UDP packets to VENUS_IP:1010 (Shelly Gen2 style, *approximation*)
#   2) "coiot":   CoIoT-like JSON over UDP to VENUS_IP:5683 (and optional multicast) (*approximation*)
#
# Data source:
# - MQTT topics (e.g. from a Tasmota Lesekopf or HA's MQTT statestream).
#   - Minimal: one net power topic (W): positive=grid import, negative=export (surplus).
#   - Optional: per-phase topics (l1/l2/l3 power W). If absent, we map everything to L1.
#
# Run:
#   pip install -r requirements.txt
#   cp config.example.yaml config.yaml   # edit it
#   python3 virtual_shelly_3em.py
#
# Author: ChatGPT PoC
# License: MIT

import os
import sys
import time
import json
import yaml
import socket
import threading
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except Exception as e:
    print("Missing dependency: paho-mqtt. Install with: pip install paho-mqtt", file=sys.stderr)
    raise

# --------------------------
# Helpers
# --------------------------
def now_ms():
    return int(time.time() * 1000)

def safe_float(v, default=0.0):
    try:
        return float(v)
    except:
        return default

def log(*args):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}]", *args, flush=True)

# --------------------------
# Data Model (latest values)
# --------------------------
class MeterState:
    def __init__(self):
        self.net_power_w = 0.0  # + import from grid, - export to grid
        self.l1_power_w = None
        self.l2_power_w = None
        self.l3_power_w = None
        self.voltage_v = 230.0  # default assumptions if not provided
        self.energy_imported_wh = 0.0
        self.energy_exported_wh = 0.0
        self.last_update_ms = 0

    def update_from_topic(self, topic, payload, cfg):
        """
        Update internal values depending on topic mapping in config.
        Payload may be JSON or raw number; we support both.
        """
        # Try parse JSON
        try:
            data = json.loads(payload)
        except Exception:
            data = None

        def extract(field_cfg):
            if field_cfg is None:
                return None
            # field_cfg can be either a direct topic (handled outside), or a dict with "json_key"
            if isinstance(field_cfg, dict) and "json_key" in field_cfg:
                key = field_cfg["json_key"]
                if isinstance(data, dict) and key in data:
                    return data[key]
                return None
            # If not dict, try to interpret payload as direct numeric
            try:
                return float(payload)
            except:
                return None

        # Map topics
        maps = cfg.get("mqtt", {}).get("topics", {})
        if topic == maps.get("net_power_w"):
            v = extract(cfg["mqtt"].get("formats", {}).get("net_power_w"))
            if v is None:
                v = safe_float(payload, 0.0)
            self.net_power_w = v
            self.last_update_ms = now_ms()
        elif topic == maps.get("l1_power_w"):
            v = extract(cfg["mqtt"].get("formats", {}).get("l1_power_w"))
            if v is None:
                v = safe_float(payload, 0.0)
            self.l1_power_w = v
            self.last_update_ms = now_ms()
        elif topic == maps.get("l2_power_w"):
            v = extract(cfg["mqtt"].get("formats", {}).get("l2_power_w"))
            if v is None:
                v = safe_float(payload, 0.0)
            self.l2_power_w = v
            self.last_update_ms = now_ms()
        elif topic == maps.get("l3_power_w"):
            v = extract(cfg["mqtt"].get("formats", {}).get("l3_power_w"))
            if v is None:
                v = safe_float(payload, 0.0)
            self.l3_power_w = v
            self.last_update_ms = now_ms()
        elif topic == maps.get("voltage_v"):
            v = extract(cfg["mqtt"].get("formats", {}).get("voltage_v"))
            if v is None:
                v = safe_float(payload, 230.0)
            self.voltage_v = v
            self.last_update_ms = now_ms()
        elif topic == maps.get("energy_imported_wh"):
            v = extract(cfg["mqtt"].get("formats", {}).get("energy_imported_wh"))
            if v is None:
                v = safe_float(payload, 0.0)
            self.energy_imported_wh = v
            self.last_update_ms = now_ms()
        elif topic == maps.get("energy_exported_wh"):
            v = extract(cfg["mqtt"].get("formats", {}).get("energy_exported_wh"))
            if v is None:
                v = safe_float(payload, 0.0)
            self.energy_exported_wh = v
            self.last_update_ms = now_ms()

    def get_phase_powers(self):
        """
        Return tuple (p1, p2, p3) active powers.
        If only net_power_w is known, place it on L1 (user connects Venus on L1).
        """
        p1 = self.l1_power_w if self.l1_power_w is not None else None
        p2 = self.l2_power_w if self.l2_power_w is not None else None
        p3 = self.l3_power_w if self.l3_power_w is not None else None

        if p1 is None and p2 is None and p3 is None:
            # Fall back: map all net power to L1; others zero
            p1 = self.net_power_w
            p2 = 0.0
            p3 = 0.0
        else:
            p1 = p1 if p1 is not None else 0.0
            p2 = p2 if p2 is not None else 0.0
            p3 = p3 if p3 is not None else 0.0

        return (float(p1), float(p2), float(p3))

STATE = MeterState()

# --------------------------
# MQTT client
# --------------------------
class MqttClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = mqtt.Client(client_id=cfg["mqtt"].get("client_id", "virtual-shelly-3em"))
        username = cfg["mqtt"].get("username")
        password = cfg["mqtt"].get("password")
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log("MQTT connected")
            topics = [v for k, v in self.cfg["mqtt"]["topics"].items() if v]
            for t in topics:
                self.client.subscribe(t, qos=0)
                log("Subscribed:", t)
        else:
            log("MQTT connect failed:", rc)

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="ignore")
        # log("MQTT", msg.topic, payload)  # uncomment for debug
        try:
            STATE.update_from_topic(msg.topic, payload, self.cfg)
        except Exception as e:
            log("update_from_topic error:", e)

    def start(self):
        self.client.connect(self.cfg["mqtt"]["host"], int(self.cfg["mqtt"].get("port", 1883)), 60)
        self.client.loop_start()

# --------------------------
# UDP Emitters
# --------------------------
class Rpc1010Emitter(threading.Thread):
    """
    Emits Shelly-like JSON-RPC 'NotifyStatus' packets to Venus IP:1010.
    This is an approximation for Shelly Pro 3EM behavior.
    """
    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.interval_s = float(cfg["emulation"].get("interval_s", 2.0))
        self.dst = (cfg["venus"]["ip"], int(cfg["venus"].get("port_rpc", 1010)))
        self.src_id = cfg["emulation"].get("device_id", "shellypro3em-FAKE123456")
        self.running = True

    def build_packet(self) -> bytes:
        p1, p2, p3 = STATE.get_phase_powers()
        V = STATE.voltage_v
        # Derive currents (rough approximation); Shelly reports amps as floats
        a_curr = p1 / V if V else 0.0
        b_curr = p2 / V if V else 0.0
        c_curr = p3 / V if V else 0.0

        # Build JSON-RPC-ish message (approximate structure)
        msg = {
            "src": self.src_id,
            "dst": "*",
            "id": now_ms(),
            "method": "NotifyStatus",
            "params": {
                "em:0": {
                    "a_act_power": round(p1, 1),
                    "b_act_power": round(p2, 1),
                    "c_act_power": round(p3, 1),
                    "a_voltage": round(V, 1),
                    "b_voltage": round(V, 1),
                    "c_voltage": round(V, 1),
                    "a_current": round(a_curr, 3),
                    "b_current": round(b_curr, 3),
                    "c_current": round(c_curr, 3),
                    # Optional cumulative counters if you have them:
                    "act_total": round(STATE.energy_imported_wh / 1000.0, 3),   # kWh imported
                    "act_returned": round(STATE.energy_exported_wh / 1000.0, 3) # kWh exported
                },
                "device": {
                    "type": "SPSW-003EM",   # a plausible Shelly Pro 3EM type-id (placeholder)
                    "mac": "FA:KE:FA:KE:FA:KE",
                    "fw_id": "2024.01.0",
                    "host": self.src_id,
                }
            }
        }
        data = json.dumps(msg).encode("utf-8")
        return data

    def run(self):
        log(f"RPC1010 emitter → {self.dst[0]}:{self.dst[1]}")
        while self.running:
            try:
                data = self.build_packet()
                self.sock.sendto(data, self.dst)
            except Exception as e:
                log("RPC emitter error:", e)
            time.sleep(self.interval_s)

class CoIoTEmitter(threading.Thread):
    """
    Emits CoIoT-like JSON over UDP (Shelly-style) to Venus IP:5683 and optional multicast.
    Highly simplified PoC.
    """
    MULTICAST_GROUP = "224.0.1.187"
    MULTICAST_PORT = 5683

    def __init__(self, cfg):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.interval_s = float(cfg["emulation"].get("interval_s", 2.0))
        self.dst_unicast = (cfg["venus"]["ip"], int(cfg["venus"].get("port_coiot", 5683)))
        self.send_multicast = bool(cfg["emulation"].get("coiot_multicast", False))
        self.running = True

    def build_packet(self) -> bytes:
        p1, p2, p3 = STATE.get_phase_powers()
        total = p1 + p2 + p3
        # Simplified "G" array typical for Shelly Gen1 CoIoT
        payload = {
            "G": [
                [0, 6101, round(p1, 1)],  # L1 active power
                [0, 6102, round(p2, 1)],  # L2 active power
                [0, 6103, round(p3, 1)],  # L3 active power
                [0, 6109, round(total, 1)],  # total active power
                [0, 4105, int(STATE.energy_exported_wh)],  # returned (export) Wh
                [0, 4106, int(STATE.energy_imported_wh)],  # total (import) Wh
            ]
        }
        return json.dumps(payload).encode("utf-8")

    def run(self):
        log(f"CoIoT emitter → unicast {self.dst_unicast[0]}:{self.dst_unicast[1]}"
            + (" + multicast 224.0.1.187:5683" if self.send_multicast else ""))
        while self.running:
            try:
                data = self.build_packet()
                # unicast to Venus
                self.sock.sendto(data, self.dst_unicast)
                if self.send_multicast:
                    self.sock.sendto(data, (self.MULTICAST_GROUP, self.MULTICAST_PORT))
            except Exception as e:
                log("CoIoT emitter error:", e)
            time.sleep(self.interval_s)

# --------------------------
# Optional UDP Listener (debug)
# --------------------------
class UdpDebugListener(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = int(port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", self.port))

    def run(self):
        log(f"Debug UDP listener on 0.0.0.0:{self.port}")
        while True:
            data, addr = self.sock.recvfrom(4096)
            try:
                s = data.decode("utf-8", errors="ignore")
            except:
                s = str(data)
            log(f"UDP recv from {addr}: {s}")

# --------------------------
# Main
# --------------------------
def main():
    cfg_path = os.environ.get("VIRTUAL_SHELLY_CFG", "config.yaml")
    if not os.path.exists(cfg_path):
        log(f"Config file not found: {cfg_path}")
        sys.exit(1)

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # MQTT
    mqttc = MqttClient(cfg)
    mqttc.start()

    # Optional debug UDP listeners
    if cfg.get("debug", {}).get("listen_udp_1010", False):
        UdpDebugListener(1010).start()
    if cfg.get("debug", {}).get("listen_udp_5683", False):
        UdpDebugListener(5683).start()

    # Emitters
    emu = cfg.get("emulation", {}).get("protocol", "rpc1010").lower()
    if emu == "rpc1010":
        Rpc1010Emitter(cfg).start()
    elif emu == "coiot":
        CoIoTEmitter(cfg).start()
    else:
        log("Unknown emulation protocol in config.emulation.protocol:", emu)
        sys.exit(2)

    # Keep main alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Exiting...")

if __name__ == "__main__":
    main()
