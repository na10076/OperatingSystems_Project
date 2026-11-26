#!/usr/bin/env python3
"""Live demo: the detector watches ONE fake virus and stops it when it raises the alarm.

  python3 live_demo.py --program cpu_steady --level high --detector run10
It can only stop the one program it started itself (never anything else).  Needs results/alarm_lines.json
(made by analyze.py).  Not used for the experiment numbers - only to show sir detection + stopping.
"""
import argparse, json, os, time
import pandas as pd

import config, detect
from run_experiment import launch, sample, SAMPLE_COLS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", default="cpu_steady")
    ap.add_argument("--level", default="high")
    ap.add_argument("--detector", default="run10", choices=list(config.DETECTORS))
    ap.add_argument("--secs", type=int, default=60)
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    lines = json.load(open(os.path.join(a.out, "alarm_lines.json")))[a.detector]
    typ, kind = a.program.split("_")
    cores = set(range(max((os.cpu_count() or 2) - 1, 1)))
    os.sched_setaffinity(0, {(os.cpu_count() or 1) - 1})
    work = os.path.join(a.out, "work_live"); os.makedirs(work, exist_ok=True)
    cmd = [os.path.join(config.BIN, f"{typ}_prog"), kind, a.level, str(a.secs), work]
    prog = launch(cmd, cores)
    print(f"Started fake virus {a.program} ({a.level}) as PID {prog.pid}. Detector: {a.detector}. Alarm lines: {lines}")
    t0, rows, i = time.monotonic(), [], 0
    try:
        while prog.poll() is None and time.monotonic() - t0 < a.secs:
            time.sleep(max(0, t0 + i * config.SAMPLE_EVERY - time.monotonic()))
            s = sample(prog.pid)
            if s is None:
                break
            rows.append((time.monotonic() - t0,) + s + (1,))
            df = pd.DataFrame(rows, columns=SAMPLE_COLS)
            t, sig = detect.series(df, config.DETECTORS[a.detector])
            at, which = detect.alarm(t, sig, lines)
            if i % 4 == 0:
                print(f"  t={rows[-1][0]:5.1f}s  cpu={sig['cpu'][-1]:7.1f}%  mem={sig['mem'][-1]:7.1f} MB  io={sig['io'][-1]:6.1f} MB/s")
            if at == at:   # not NaN
                print(f"\n*** ALARM at {at:.1f} s (reading: {which}). Stopping PID {prog.pid} (the program this script started). ***")
                os.killpg(prog.pid, 9)
                prog.wait()
                print(f"PID {prog.pid} stopped. Time from start to stop: {time.monotonic() - t0:.1f} s")
                return
            i += 1
        print("No alarm raised.")
    finally:
        if prog.poll() is None:
            os.killpg(prog.pid, 9)
        import shutil; shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
