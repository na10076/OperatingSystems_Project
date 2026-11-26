"""The two detectors. No AI, fixed alarm lines, built only from PUBLISHED methods and library code.

Where each piece comes from (cite these in the report):
  * Snapshot detector  = a fixed-limit check on the latest reading only, i.e. a Shewhart-style
    control-chart rule (Shewhart, 1931; Montgomery, Introduction to Statistical Quality Control).
    It is the same as a Prometheus alert on an instant rate, e.g.  rate(x[1 sample]) > line.
  * Running-total detector = the same fixed limit applied to the AVERAGE over a sliding time window,
    the windowed-average rule used in Prometheus alerting, e.g.  avg_over_time(x[10s]) > line
    or  rate(cpu_seconds_total[10s]) > line  (Prometheus docs, "Alerting rules" / PromQL functions).
  * The sliding windows are computed with pandas' time-based rolling windows
    (DataFrame.rolling("10s")) - McKinney (2010), doi:10.25080/Majora-92bf1922-00a.
  * The raw numbers come straight from the Linux kernel's /proc interface:
    /proc/<pid>/stat (utime+stime), /proc/<pid>/statm, /proc/<pid>/io (wchar), /proc/<pid>/schedstat
    - documented in proc(5) and the kernel's Documentation/scheduler/sched-stats.rst.

Readings watched for each program:
  cpu = CPU use in percent of one core (300 = three cores busy)
  mem = memory in MB
  io  = bytes written in MB per second
An alarm = any of the three goes over its alarm line.
"""
import numpy as np
import pandas as pd

import config

SIGNALS = ["cpu", "mem", "io"]


def load_log(path):
    df = pd.read_csv(path)
    df = df[df["alive"] == 1].reset_index(drop=True)
    for c in ["t", "cpu_s", "rss_kb", "wchar", "wait_ns", "slices"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def series(df, window):
    """Detector readings over time.
    window = 0  -> snapshot: rate over the latest sample only (Prometheus-style instant rate)
    window = N  -> running total: rate / average over the last N seconds (pandas rolling("Ns"))"""
    t = df["t"].to_numpy(float)
    n = len(t)
    if n < 2:
        return t, {s: np.full(n, np.nan) for s in SIGNALS}
    idx = pd.to_timedelta(df["t"], unit="s")
    d = pd.DataFrame({"dt": df["t"].diff(),
                      "cpu": df["cpu_s"].diff(),                 # CPU seconds used in this sample
                      "io": df["wchar"].diff() / 1048576.0,      # MB written in this sample
                      "mem": df["rss_kb"] / 1024.0}).set_index(idx)
    if window == 0:
        dt, cpu, io, mem = d["dt"], d["cpu"], d["io"], d["mem"]
    else:
        roll = d.rolling(f"{window}s", min_periods=1)            # pandas time-based sliding window
        dt, cpu, io = roll["dt"].sum(), roll["cpu"].sum(), roll["io"].sum()
        mem = roll["mem"].mean()
    out = {"cpu": (cpu / dt * 100.0).to_numpy(float, copy=True),
           "io": (io / dt).to_numpy(float, copy=True),
           "mem": mem.to_numpy(float, copy=True)}
    bad = ~(dt.to_numpy(float) > 0)
    if window:
        bad |= t < max(config.MIN_WINDOW_S, window)            # an N-second running total judges only once it has N seconds of readings
    for s in SIGNALS:
        out[s][bad] = np.nan
        out[s][0] = np.nan
    return t, out


def alarm(t, sig, lines, scale=1.0):
    """First time any reading crosses its line. Returns (time, which reading) or (nan, '')."""
    best, which = np.nan, ""
    for s in SIGNALS:
        hit = np.where(sig[s] > lines[s] * scale)[0]
        if len(hit) and (np.isnan(best) or t[hit[0]] < best):
            best, which = t[hit[0]], s
    return best, which


def peak_score(sig, lines):
    """Highest reading in the run, as a multiple of its alarm line (1.0 = exactly on the line).
    'Raise an alarm at scale s' is the same as 'peak_score > s', so this one number per run lets
    scikit-learn's roc_curve sweep every possible alarm line (Pedregosa et al., 2011)."""
    vals = [np.nanmax(sig[s] / lines[s]) for s in SIGNALS if np.isfinite(sig[s]).any()]
    return max(vals) if vals else 0.0


def calibrate95(virus_readings_by_type, target=0.95):
    """Project-plan rule. virus_readings_by_type: {"cpu": [(t, sig), ...], "mem": [...], "io": [...]} from the
    VIRUS runs of the calibration half, grouped by virus type. Each line (CPU, memory, disk) is set from the
    viruses of its own type so that it catches `target` (95%) of them: line = just below the 5th percentile of
    their highest readings. Lines are then frozen and applied to the test half."""
    lines = {}
    for s in SIGNALS:
        peaks = [np.nanmax(sig[s]) if np.isfinite(sig[s]).any() else 0.0 for _, sig in virus_readings_by_type.get(s, [])]
        if not peaks:
            lines[s] = config.MIN_LINES[s]
            continue
        q = float(np.quantile(peaks, 1 - target, method="lower"))
        lines[s] = max(q * 0.999, config.MIN_LINES[s])
    return lines


def calibrate(readings):
    """readings: list of (t, sig) from the harmless look-alike programs on the calibration round.
    Line = highest reading any look-alike produced x LINE_MARGIN (never below a small floor)."""
    lines = {}
    for s in SIGNALS:
        peak = 0.0
        for _, sig in readings:
            if np.isfinite(sig[s]).any():
                peak = max(peak, np.nanmax(sig[s]))
        lines[s] = max(peak * config.LINE_MARGIN, config.MIN_LINES[s])
    return lines
