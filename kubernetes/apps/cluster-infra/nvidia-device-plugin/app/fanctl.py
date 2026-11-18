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
# Board headers are FIRMWARE-OWNED by policy. The BIOS profile on these boxes runs
# every header except SYS_FAN at full speed, and the previous GPU-keyed curve capped
# pwm3-7 at ~87% (CEIL needs a 85C GPU; the cards never pass ~77C) while ignoring CPU
# temperature entirely -- iggy tripped its internal thermal limit on 2026-11-17 with
# the CPU at 93-95C and these headers parked at 83%. Software therefore never writes
# a board duty in normal operation; it only takes over at 100% as a CPU redline
# fail-safe (see board_guard), so it can add airflow but never remove it.
BOARD_PWMS = [3, 4, 5, 6, 7]
FLOOR, CEIL = 50, 100       # percent
T_LO, T_HI = 55.0, 85.0     # deg C (GPU card-fan curve)
CPU_HI, CPU_LO = 90.0, 80.0 # deg C: board-fan redline arm / release (k10temp)
POLL_S = 5
LOG_EVERY = 12              # ~60s
METRICS_PORT = 9410

nvml = ctypes.CDLL(NVML_LIB)
_running = True
_last_duty = FLOOR
_state = {"handles": [], "hwmon": None, "cpu_hwmon": None}
_override = {"armed": False}

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

def board_guard(ctemp):
    """CPU redline fail-safe for the firmware-owned board headers.

    Normal operation writes nothing: the BIOS profile already runs these headers at
    full speed. Only when the CPU crosses CPU_HI do we seize them at 100%, and we
    hand them straight back once it cools below CPU_LO."""
    hwmon = _state["hwmon"]
    if not hwmon or ctemp is None or not BOARD_PWMS:
        return
    if not _override["armed"] and ctemp >= CPU_HI:
        _override["armed"] = True
        print("OVERRIDE cpu=%.1fC >= %.0fC: forcing board pwm%s to 100%%"
              % (ctemp, CPU_HI, BOARD_PWMS), flush=True)
    elif _override["armed"] and ctemp <= CPU_LO:
        _override["armed"] = False
        board_restore(hwmon)  # hand the headers back to firmware, do not linger at 100%
        print("OVERRIDE released at cpu=%.1fC: firmware retakes board fans" % ctemp, flush=True)
    if _override["armed"]:
        board_set(hwmon, CEIL)

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
    ct = cpu_temp(_state["cpu_hwmon"])
    L += ["# HELP fanctl_cpu_temp_celsius Hottest k10temp channel, the CPU redline input.",
          "# TYPE fanctl_cpu_temp_celsius gauge",
          "fanctl_cpu_temp_celsius %.1f" % (ct if ct is not None else -1)]
    L += ["# HELP fanctl_board_override_active Board pwm forced to 100 by the CPU redline fail-safe (1/0).",
          "# TYPE fanctl_board_override_active gauge",
          "fanctl_board_override_active %d" % (1 if _override["armed"] else 0)]
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
        print("WARN: board hwmon not found; CPU redline fail-safe disabled", flush=True)
    chwmon = cpu_hwmon()
    if not chwmon:
        print("WARN: k10temp hwmon not found; CPU redline fail-safe disabled", flush=True)
    for gi, h in enumerate(handles):
        rc = nvml.nvmlDeviceSetFanControlPolicy(h, 1)  # MANUAL
        print("gpu%d fan policy MANUAL rc=%d" % (gi, rc), flush=True)
    _state["handles"], _state["hwmon"], _state["cpu_hwmon"] = handles, hwmon, chwmon
    serve_metrics()
    print("fan-control started: %d gpus, board hwmon=%s (firmware-owned, redline at %.0fC), "
          "cpu hwmon=%s, metrics on :%d"
          % (len(handles), hwmon, CPU_HI, chwmon, METRICS_PORT), flush=True)
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
            # Runs even when GPU telemetry is missing: the CPU fail-safe must not
            # depend on the cards answering.
            board_guard(cpu_temp(_state["cpu_hwmon"]))
            if i % LOG_EVERY == 0:
                print("temps=[%s] gpu_duty=%d%% cpu=%s board_override=%d"
                      % (",".join(str(t) for t in temps), duty,
                         cpu_temp(_state["cpu_hwmon"]), 1 if _override["armed"] else 0), flush=True)
            i += 1
            time.sleep(POLL_S)
    finally:
        print("stopping: restoring auto profiles", flush=True)
        restore(handles, hwmon)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    main()
