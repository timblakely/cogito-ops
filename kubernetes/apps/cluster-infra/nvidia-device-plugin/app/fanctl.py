#!/usr/bin/env python3
import ctypes
import glob
import http.server
import os
import re
import signal
import sys
import threading
import time

NVML_LIB = "/host-libs/libnvidia-ml.so.1"
HWMON_ROOT = "/sys/class/hwmon"  # host sysfs (privileged pod); hostPath subtree mounts break sysfs relative symlinks
BOARD_PWMS = [3, 4, 5, 6, 7]
FLOOR, CEIL = 50, 100       # percent
T_LO, T_HI = 55.0, 85.0     # deg C
POLL_S = 5
LOG_EVERY = 12              # ~60s
METRICS_PORT = 9410

nvml = ctypes.CDLL(NVML_LIB)
_running = True
_last_duty = FLOOR
_state = {"handles": [], "hwmon": None}

def _stop(sig, frame):
    global _running
    _running = False

def curve(t):
    if t <= T_LO:
        return FLOOR
    if t >= T_HI:
        return CEIL
    return int(round(FLOOR + (t - T_LO) * (CEIL - FLOOR) / (T_HI - T_LO)))

def gpu_handles():
    cnt = ctypes.c_uint()
    if nvml.nvmlDeviceGetCount_v2(ctypes.byref(cnt)) != 0:
        return []
    out = []
    for i in range(cnt.value):
        h = ctypes.c_void_p()
        if nvml.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)) == 0:
            out.append(h)
    return out

def gpu_temp(h):
    t = ctypes.c_uint()
    return t.value if nvml.nvmlDeviceGetTemperature(h, 0, ctypes.byref(t)) == 0 else None

def gpu_fan_percent(h):
    # Legacy 1-arg read (what nvidia-smi uses); GetFanSpeed_v2 is rc=2 in this driver build.
    v = ctypes.c_uint()
    return v.value if nvml.nvmlDeviceGetFanSpeed(h, ctypes.byref(v)) == 0 else None

def gpu_set_fans(handles, duty):
    for gi, h in enumerate(handles):
        nf = ctypes.c_uint()
        if nvml.nvmlDeviceGetNumFans(h, ctypes.byref(nf)) != 0:
            continue
        for f in range(nf.value):
            rc = nvml.nvmlDeviceSetFanSpeed_v2(h, f, duty)
            if rc != 0:
                print("WARN gpu%d fan%d set rc=%d" % (gi, f, rc), flush=True)

def board_hwmon():
    for d in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*"))):
        try:
            name = open(os.path.join(d, "name")).read().strip().lower()
        except OSError:
            continue
        if "nct6775" in name or "nct6797" in name:
            return d
    return None

def board_set(hwmon, duty):
    raw = duty * 255 // 100  # sysfs pwm is 0-255, not percent
    for p in BOARD_PWMS:
        en = os.path.join(hwmon, "pwm%d_enable" % p)
        pw = os.path.join(hwmon, "pwm%d" % p)
        try:
            if open(en).read().strip() != "1":
                open(en, "w").write("1")
            if open(pw).read().strip() != str(raw):
                open(pw, "w").write(str(raw))
        except OSError as e:
            print("WARN board pwm%d: %s" % (p, e), flush=True)

def board_restore(hwmon):
    for p in BOARD_PWMS:
        try:
            open(os.path.join(hwmon, "pwm%d_enable" % p), "w").write("5")  # AUTO
        except OSError:
            pass

def restore(handles, hwmon):
    for gi, h in enumerate(handles):
        rc = nvml.nvmlDeviceSetFanControlPolicy(h, 0)  # AUTO
        if rc != 0:
            print("WARN restore gpu%d policy rc=%d" % (gi, rc), flush=True)
    if hwmon:
        board_restore(hwmon)

def board_temps(hwmon):
    out = {}
    try:
        files = os.listdir(hwmon)
    except OSError:
        return out
    for f in files:
        m = re.match(r"temp(\d+)_input$", f)
        if not m:
            continue
        n = m.group(1)
        try:
            val = open(os.path.join(hwmon, f)).read().strip()
        except OSError:
            continue
        try:
            label = open(os.path.join(hwmon, "temp%s_label" % n)).read().strip()
        except OSError:
            label = ""
        try:
            v = int(val) / 1000.0
        except ValueError:
            continue
        # nct6775 reports -128/-1 for unconnected channels and 0 for
        # unused ones (PCH, DIMM); real board temps never run below 10C.
        if v < 10:
            continue
        out[label or "temp%s" % n] = v
    return out

def render_metrics():
    handles, hwmon = _state["handles"], _state["hwmon"]
    L = []
    L += ["# HELP fanctl_applied_duty_percent Fan duty currently applied by fanctl (0-100).",
          "# TYPE fanctl_applied_duty_percent gauge",
          "fanctl_applied_duty_percent %d" % _last_duty]
    L += ["# HELP fanctl_gpu_fan_percent Reported card fan speed per GPU (0-100).",
          "# TYPE fanctl_gpu_fan_percent gauge"]
    for i, h in enumerate(handles):
        v = gpu_fan_percent(h)
        if v is not None:
            L.append('fanctl_gpu_fan_percent{gpu="%d"} %d' % (i, v))
    if hwmon:
        L += ["# HELP fanctl_board_pwm_percent Board fan pwm duty (0-100).",
              "# TYPE fanctl_board_pwm_percent gauge"]
        for p in BOARD_PWMS:
            try:
                raw = open(os.path.join(hwmon, "pwm%d" % p)).read().strip()
                L.append('fanctl_board_pwm_percent{pwm="%d"} %d' % (p, int(raw) * 100 // 255))
            except (OSError, ValueError):
                pass
        temps = board_temps(hwmon)
        L += ["# HELP fanctl_board_temp_c On-board (case) temperature sensor, deg C.",
              "# TYPE fanctl_board_temp_c gauge"]
        for k, v in sorted(temps.items()):
            L.append('fanctl_board_temp_c{sensor="%s"} %.1f' % (k, v))
    return "\n".join(L) + "\n"

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = render_metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass

def serve_metrics():
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", METRICS_PORT), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

def main():
    if nvml.nvmlInit_v2() != 0:
        print("FATAL: nvmlInit_v2 failed", flush=True)
        sys.exit(1)
    handles = gpu_handles()
    if not handles:
        print("FATAL: no GPUs", flush=True)
        sys.exit(1)
    hwmon = board_hwmon()
    if not hwmon:
        print("WARN: board hwmon not found; case fans stay on BIOS auto", flush=True)
    for gi, h in enumerate(handles):
        rc = nvml.nvmlDeviceSetFanControlPolicy(h, 1)  # MANUAL
        print("gpu%d fan policy MANUAL rc=%d" % (gi, rc), flush=True)
    _state["handles"], _state["hwmon"] = handles, hwmon
    serve_metrics()
    print("fan-control started: %d gpus, board hwmon=%s, metrics on :%d" % (len(handles), hwmon, METRICS_PORT), flush=True)
    i = 0
    try:
        global _last_duty
        while _running:
            temps = [gpu_temp(h) for h in handles]
            live = [t for t in temps if t is not None]
            if live:
                duty = curve(max(live))
                _last_duty = duty
                gpu_set_fans(handles, duty)
                if hwmon:
                    board_set(hwmon, duty)
                if i % LOG_EVERY == 0:
                    print("temps=[%s] duty=%d%%" % (",".join(str(t) for t in temps), duty), flush=True)
            i += 1
            time.sleep(POLL_S)
    finally:
        print("stopping: restoring auto profiles", flush=True)
        restore(handles, hwmon)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    main()
