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
# Board headers: HELD AT FULL SPEED, ALWAYS. Two measured facts about this
# MSI X570 / NCT6797D box drove this policy:
#  - Writing pwm_enable=5 ("auto", which is what the previous version did on clean
#    stop) parks pwm7 at duty 0 and the chassis exhaust fan stops outright:
#    measured 2026-11-18, fan7 5133 RPM -> 0 RPM. AUTO is never safe here.
#  - The old GPU-keyed curve could only reach ~87% (CEIL=100 needs an 85C GPU and
#    the cards never pass ~77C) and never read CPU temperature, so iggy cooked
#    itself at 93-95C CPU with these headers parked at 83% and tripped its internal
#    thermal limit on 2026-11-17.
# So every board header is written pwm=255 with pwm_enable=0 (no software control ->
# fan runs full on) on every poll and on clean stop. The operator's BIOS profile runs
# these headers at full speed, so this only ever matches that intent, never undercuts
# it. pwm1 (AIO pump) and pwm2 are left exactly as firmware leaves them.
BOARD_PWMS = [3, 4, 5, 6, 7]
FLOOR, CEIL = 50, 100       # percent (GPU card-fan curve)
T_LO, T_HI = 55.0, 85.0     # deg C (GPU card-fan curve)
CPU_WARN = 90.0             # deg C: log a warning; the fans are already at 100%
POLL_S = 5
LOG_EVERY = 12              # ~60s
METRICS_PORT = 9410

nvml = ctypes.CDLL(NVML_LIB)
_running = True
_last_duty = FLOOR
_state = {"handles": [], "hwmon": None, "cpu_hwmon": None}

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

def cpu_hwmon():
    for d in sorted(glob.glob(os.path.join(HWMON_ROOT, "hwmon*"))):
        try:
            name = open(os.path.join(d, "name")).read().strip().lower()
        except OSError:
            continue
        if "k10temp" in name:
            return d
    return None

def cpu_temp(hwmon):
    # k10temp exposes Tctl/Tdie as separate channels; the hottest one is what the
    # package thermal limit trips on, so take the max rather than trusting a label.
    if not hwmon:
        return None
    best = None
    for f in glob.glob(os.path.join(hwmon, "temp*_input")):
        try:
            v = int(open(f).read().strip()) / 1000.0
        except (OSError, ValueError):
            continue
        if v < -50:  # driver sentinel for an invalid channel
            continue
        if best is None or v > best:
            best = v
    return best

def board_fullspeed(hwmon):
    """Hold every board header at full speed: pwm=255 with pwm_enable=0.

    pwm_enable=0 means "no software fan speed control", which on this chip leaves the
    header driven fully on. The old clean-stop value (5, "auto") is deliberately never
    written anywhere in this script: on this board it parks pwm7 at duty 0 and the
    chassis exhaust fan stops outright."""
    if not hwmon:
        return
    for p in BOARD_PWMS:
        en = os.path.join(hwmon, "pwm%d_enable" % p)
        pw = os.path.join(hwmon, "pwm%d" % p)
        try:
            if open(pw).read().strip() != "255":
                open(pw, "w").write("255")
            if open(en).read().strip() != "0":
                open(en, "w").write("0")
        except OSError as e:
            print("WARN board pwm%d: %s" % (p, e), flush=True)

def board_state(hwmon):
    """(pwm, duty percent, enable) per board header: metrics plus startup logging."""
    out = []
    if not hwmon:
        return out
    for p in BOARD_PWMS:
        try:
            duty = int(open(os.path.join(hwmon, "pwm%d" % p)).read().strip()) * 100 // 255
            en = open(os.path.join(hwmon, "pwm%d_enable" % p)).read().strip()
        except (OSError, ValueError):
            continue
        out.append((p, duty, en))
    return out

def restore(handles, hwmon):
    for gi, h in enumerate(handles):
        rc = nvml.nvmlDeviceSetFanControlPolicy(h, 0)  # AUTO
        if rc != 0:
            print("WARN restore gpu%d policy rc=%d" % (gi, rc), flush=True)
    # Deliberately not AUTO: full speed is the state we leave behind for firmware.
    board_fullspeed(hwmon)

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
    ct = cpu_temp(_state["cpu_hwmon"])
    L += ["# HELP fanctl_cpu_temp_celsius Hottest k10temp channel (Tctl/Tdie).",
          "# TYPE fanctl_cpu_temp_celsius gauge",
          "fanctl_cpu_temp_celsius %.1f" % (ct if ct is not None else -1)]
    L += ["# HELP fanctl_gpu_fan_percent Reported card fan speed per GPU (0-100).",
          "# TYPE fanctl_gpu_fan_percent gauge"]
    for i, h in enumerate(handles):
        v = gpu_fan_percent(h)
        if v is not None:
            L.append('fanctl_gpu_fan_percent{gpu="%d"} %d' % (i, v))
    if hwmon:
        L += ["# HELP fanctl_board_pwm_percent Board fan pwm duty (0-100).",
              "# TYPE fanctl_board_pwm_percent gauge",
              "# HELP fanctl_board_pwm_enable Board pwm_enable mode (0=no software control).",
              "# TYPE fanctl_board_pwm_enable gauge"]
        for p, duty, en in board_state(hwmon):
            L.append('fanctl_board_pwm_percent{pwm="%d"} %d' % (p, duty))
            L.append('fanctl_board_pwm_enable{pwm="%d"} %s' % (p, en))
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
        print("WARN: board hwmon not found; board headers stay as firmware left them", flush=True)
    chwmon = cpu_hwmon()
    if not chwmon:
        print("WARN: k10temp hwmon not found; CPU temperature will not be reported", flush=True)
    for gi, h in enumerate(handles):
        rc = nvml.nvmlDeviceSetFanControlPolicy(h, 1)  # MANUAL
        print("gpu%d fan policy MANUAL rc=%d" % (gi, rc), flush=True)
    _state["handles"], _state["hwmon"], _state["cpu_hwmon"] = handles, hwmon, chwmon
    print("board headers as found: %s" % (board_state(hwmon),), flush=True)
    board_fullspeed(hwmon)
    print("board headers pinned full speed: %s" % (board_state(hwmon),), flush=True)
    serve_metrics()
    print("fan-control started: %d gpus, board hwmon=%s, cpu hwmon=%s, metrics on :%d"
          % (len(handles), hwmon, chwmon, METRICS_PORT), flush=True)
    i = 0
    try:
        global _last_duty
        while _running:
            temps = [gpu_temp(h) for h in handles]
            live = [t for t in temps if t is not None]
            duty = _last_duty
            if live:
                duty = curve(max(live))
                _last_duty = duty
                gpu_set_fans(handles, duty)
            # Independent of GPU telemetry: board headers stay pinned at full speed
            # even when the cards stop answering.
            board_fullspeed(hwmon)
            ctemp = cpu_temp(_state["cpu_hwmon"])
            if i % LOG_EVERY == 0:
                print("temps=[%s] gpu_duty=%d%% cpu=%s board=%s"
                      % (",".join(str(t) for t in temps), duty, ctemp, board_state(hwmon)),
                      flush=True)
                if ctemp is not None and ctemp >= CPU_WARN:
                    print("WARN cpu=%.1fC >= %.0fC with board headers already at 100%%: "
                          "at the cooling limit" % (ctemp, CPU_WARN), flush=True)
            i += 1
            time.sleep(POLL_S)
    finally:
        print("stopping: restoring auto profiles", flush=True)
        restore(handles, hwmon)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    main()
