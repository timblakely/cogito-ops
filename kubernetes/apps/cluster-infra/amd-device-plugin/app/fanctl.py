#!/usr/bin/env python3
"""Drive Iggy's NCT6797 case fans from two AMDGPU hwmon temperature sets."""

import glob
import http.server
import os
import re
import signal
import threading
import time

HWMON_ROOT = "/host-sys/class/hwmon"
BOARD_PWMS = (3, 4, 5, 6, 7)
FLOOR, CEIL = 70, 100
T_LO, T_HI = 55.0, 80.0
POLL_S = 5
METRICS_PORT = 9410

running = True
state = {"duty": 100, "gpu_temps": {}, "sleeping": set(),
         "board": None, "healthy": False}


def read(path):
    try:
        with open(path, encoding="ascii") as handle:
            return handle.read().strip()
    except (OSError, UnicodeError):
        return None


def write(path, value):
    try:
        with open(path, "w", encoding="ascii") as handle:
            handle.write(str(value))
        return True
    except OSError as error:
        print(f"WARN writing {path}: {error}", flush=True)
        return False


def hwmon_dirs(name):
    return [path for path in sorted(glob.glob(f"{HWMON_ROOT}/hwmon*"))
            if (read(f"{path}/name") or "").lower() == name]


def read_int(path):
    try:
        return int(read(path))
    except (TypeError, ValueError):
        return None


def gpu_devices():
    devices = []
    for hwmon in hwmon_dirs("amdgpu"):
        device = os.path.dirname(os.path.dirname(os.path.realpath(hwmon)))
        devices.append((os.path.basename(device), hwmon, device))
    return sorted(devices)


def gpu_temperatures():
    result = {}
    sleeping = set()
    devices = gpu_devices()
    for pci, path, device in devices:
        values = []
        for sensor in glob.glob(f"{path}/temp*_input"):
            raw = read(sensor)
            try:
                temp = int(raw) / 1000.0
            except (TypeError, ValueError):
                continue
            if 10 <= temp <= 125:
                values.append(temp)
        if values:
            result[pci] = max(values)
        elif read(f"{device}/power/runtime_status") == "suspended":
            sleeping.add(pci)
    return result, sleeping, len(devices)


def board_hwmon():
    for path in sorted(glob.glob(f"{HWMON_ROOT}/hwmon*")):
        name = (read(f"{path}/name") or "").lower()
        if "nct6775" in name or "nct6797" in name:
            return path
    return None


def set_board_fans(board, duty):
    pwm = round(255 * duty / 100)
    for index in BOARD_PWMS:
        enable = f"{board}/pwm{index}_enable"
        value = f"{board}/pwm{index}"
        if read(enable) != "1":
            write(enable, "1")
        if read(value) != str(pwm):
            write(value, pwm)


def restore_board_fans(board):
    if board:
        for index in BOARD_PWMS:
            write(f"{board}/pwm{index}_enable", "5")


def metrics():
    lines = [
        "# TYPE amd_fanctl_applied_duty_percent gauge",
        f"amd_fanctl_applied_duty_percent {state['duty']}",
        "# TYPE amd_fanctl_sensor_healthy gauge",
        f"amd_fanctl_sensor_healthy {int(state['healthy'])}",
        "# TYPE amd_fanctl_gpu_temp_c gauge",
        "# TYPE amd_fanctl_gpu_runtime_suspended gauge",
    ]
    lines += [
        "# TYPE amd_fanctl_gpu_power_w gauge",
        "# TYPE amd_fanctl_gpu_fan_rpm gauge",
        "# TYPE amd_fanctl_gpu_busy_percent gauge",
        "# TYPE amd_fanctl_gpu_vram_used_bytes gauge",
        "# TYPE amd_fanctl_gpu_vram_total_bytes gauge",
    ]
    for index, (pci, hwmon, device) in enumerate(gpu_devices()):
        label = f'gpu="{index}",pci="{pci}"'
        if pci in state["gpu_temps"]:
            lines.append(f'amd_fanctl_gpu_temp_c{{{label}}} {state["gpu_temps"][pci]:.1f}')
        lines.append(f'amd_fanctl_gpu_runtime_suspended{{{label}}} {int(pci in state["sleeping"])}')
        fields = (
            ("power_w", f"{hwmon}/power1_average", 1_000_000),
            ("fan_rpm", f"{hwmon}/fan1_input", 1),
            ("busy_percent", f"{device}/gpu_busy_percent", 1),
            ("vram_used_bytes", f"{device}/mem_info_vram_used", 1),
            ("vram_total_bytes", f"{device}/mem_info_vram_total", 1),
        )
        for field, path, scale in fields:
            value = read_int(path)
            if value is not None:
                lines.append(f"amd_fanctl_gpu_{field}{{{label}}} {value / scale:g}")
    board = state["board"]
    if board:
        lines.append("# TYPE amd_fanctl_board_pwm_percent gauge")
        for index in BOARD_PWMS:
            raw = read(f"{board}/pwm{index}")
            if raw and raw.isdigit():
                lines.append(f'amd_fanctl_board_pwm_percent{{pwm="{index}"}} {int(raw) * 100 / 255:.1f}')
        lines.append("# TYPE amd_fanctl_board_temp_c gauge")
        for sensor in glob.glob(f"{board}/temp*_input"):
            match = re.search(r"temp(\d+)_input$", sensor)
            if not match:
                continue
            number = match.group(1)
            raw = read(sensor)
            try:
                temp = int(raw) / 1000.0
            except (TypeError, ValueError):
                continue
            if 10 <= temp <= 125:
                lines.append(f'amd_fanctl_board_temp_c{{sensor="{number}"}} {temp:.1f}')
    return "\n".join(lines) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = metrics().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def stop(*_):
    global running
    running = False


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    board = board_hwmon()
    state["board"] = board
    if board:
        set_board_fans(board, 100)
    else:
        print("WARN board hwmon absent; case fans remain on BIOS policy", flush=True)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", METRICS_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while running:
            temps, sleeping, device_count = gpu_temperatures()
            healthy = device_count == 2 and len(temps) + len(sleeping) == 2
            hottest = max(temps.values()) if temps else None
            duty = (min(CEIL, max(FLOOR, round(FLOOR +
                    (hottest - T_LO) * (CEIL - FLOOR) / (T_HI - T_LO))))
                    if healthy and hottest is not None else FLOOR if healthy else 100)
            state.update(duty=duty, gpu_temps=temps, sleeping=sleeping,
                         healthy=healthy)
            if board:
                set_board_fans(board, duty)
            print(f"gpu_temps={temps} sleeping={sorted(sleeping)} "
                  f"sensors_healthy={healthy} case_duty={duty}%", flush=True)
            time.sleep(POLL_S)
    finally:
        restore_board_fans(board)


if __name__ == "__main__":
    main()
