#!/usr/bin/env python3
"""Read-only AMDGPU VRAM/busy telemetry from sysfs, for AMD nodes without fan duty.

Iggy's amd-fan-control DaemonSet already publishes these same sysfs files, but it
is pinned to that host by hostname and its whole purpose is writing board PWM
registers, so running it elsewhere is the wrong tool. Deleuze needed the VRAM
watermark with no side effects: before this exporter existed, nothing scraped
mem_info_vram_used on an AMD node other than iggy, so GPU memory had no history
at all and questions like "what did the vision tower cost the cards" could only
be answered from boot-log lines (measured 2026-11-25: radiance_fleet_vram_bytes
is the engine's CLAIM, flat at 28.710 GiB a card for six days, and
radiance:kv_resident_blocks exports 0 in every sample).

Every card is labelled by BOTH its sysfs name and its PCI slot, because the two
numberings disagree on this box: the engine's "card 0 / rank 0" is 0000:0a:00.0,
which /sys/class/drm calls card1, while rank 1 is 0000:0d:00.0 = card0. Without
the PCI label a panel silently compares different GPUs.

Nothing in here opens a file for writing.
"""

import glob
import http.server
import os
import re
import socketserver
import threading

PORT = 9411
DRM_ROOT = "/host-sys/class/drm"
METRIC_PREFIX = "amdgpu"
# sysfs attribute -> metric name. Missing attributes are skipped, not zeroed,
# so a card that cannot report a sensor is visibly absent rather than lying.
GAUGES = (
    ("mem_info_vram_used", "vram_used_bytes"),
    ("mem_info_vram_total", "vram_total_bytes"),
    ("mem_info_gtt_used", "gtt_used_bytes"),
    ("gpu_busy_percent", "busy_percent"),
)
# hwmon attribute -> metric name, resolved relative to <device>/hwmon/hwmon*.
HWMON_GAUGES = (
    ("temp1_input", "temp_celsius", 1000),
    ("power1_average", "power_watts", 1000000),
    ("freq1_input", "clock_sclk_hertz", 1),
)
TYPES = {
    "vram_used_bytes": "gauge",
    "vram_total_bytes": "gauge",
    "gtt_used_bytes": "gauge",
    "busy_percent": "gauge",
    "temp_celsius": "gauge",
    "power_watts": "gauge",
    "clock_sclk_hertz": "gauge",
    "info": "gauge",
}


def read_text(path):
    try:
        with open(path, encoding="ascii") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def read_int(path):
    text = read_text(path)
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def cards():
    """Discrete GPUs: a cardN dir whose device/mem_info_vram_total reads positive.

    Sorted so cardN order is stable and matches what a talosctl probe of the same
    path would see. A presence-only test would let through the render nodes and
    any card that cannot report its memory, so the number itself is the gate:
    a card that cannot state its VRAM total is not a GPU this exporter claims.
    """
    found = []
    for path in sorted(glob.glob(f"{DRM_ROOT}/card[0-9]*")):
        device = os.path.join(path, "device")
        total = read_int(os.path.join(device, "mem_info_vram_total"))
        if not total or total <= 0:
            continue
        uevent = read_text(os.path.join(device, "uevent"))
        slot = re.search(r"PCI_SLOT_NAME=(\S+)", uevent)
        driver = re.search(r"DRIVER=(\S+)", uevent)
        found.append({
            "card": os.path.basename(path),
            "pci": slot.group(1) if slot else "unknown",
            "model": read_text(os.path.join(device, "product_name")) or "unknown",
            "driver": driver.group(1) if driver else "unknown",
            "device": device,
        })
    return found


def hwmon_value(device, attribute):
    for hwmon in sorted(glob.glob(os.path.join(device, "hwmon", "hwmon*"))):
        value = read_int(os.path.join(hwmon, attribute))
        if value is not None:
            return value
    return None


def sample():
    rows = []
    for card in cards():
        labels = f'card="{card["card"]}",pci="{escape(card["pci"])}"'
        full_labels = (f'{labels},model="{escape(card["model"])}",'
                       f'driver="{escape(card["driver"])}"')
        rows.append((f"{METRIC_PREFIX}_info", full_labels, "1"))
        for attribute, metric in GAUGES:
            value = read_int(os.path.join(card["device"], attribute))
            if value is not None:
                rows.append((f"{METRIC_PREFIX}_{metric}", labels, str(value)))
        for attribute, metric, scale in HWMON_GAUGES:
            value = hwmon_value(card["device"], attribute)
            if value is None:
                continue
            text = str(value) if scale == 1 else f"{value / scale:.4g}"
            rows.append((f"{METRIC_PREFIX}_{metric}", labels, text))
    return rows


def render():
    rows = sample()
    lines = [f"# HELP {METRIC_PREFIX}_info GPU identity labels; value is always 1.",
             f"# TYPE {METRIC_PREFIX}_info gauge"]
    emitted = set()
    for name, labels, value in rows:
        if name not in emitted and name != f"{METRIC_PREFIX}_info":
            lines.append(f"# TYPE {name} {TYPES[name.split('_', 1)[1]]}")
            emitted.add(name)
        lines.append(f"{name}{{{labels}}} {value}")
    return ("\n".join(lines) + "\n").encode()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - stdlib naming
        if self.path.split("?")[0] not in ("/metrics", "/healthz"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"ok\n" if self.path.split("?")[0] == "/healthz" else render()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    available = cards()
    print(f"amdgpu-exporter: {len(available)} GPU(s) "
          f"{[(c['card'], c['pci']) for c in available]} on :{PORT}", flush=True)
    with Server(("0.0.0.0", PORT), Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        threading.Event().wait()


if __name__ == "__main__":
    main()
