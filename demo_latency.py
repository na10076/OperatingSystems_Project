#!/usr/bin/env python3
"""One-core "who ran when" demo (your friend's idea).

On ONE core we start two CPU hogs and one "interactive" task (sleeps 20 ms, wakes, works 3 ms, repeat).
Every task records exactly when it was on the CPU.  We draw a timeline per policy (Fig 11) and also
measure how late the interactive task wakes up (Fig 11b).

  sudo python3 demo_latency.py                              # all policies, 12 s each (~2 min)
  sudo python3 demo_latency.py --policies eevdf --secs 5    # quick test (no sudo needed)
Writes results/demo_timeline.csv and results/demo.csv, and prints a table you can show in the viva.
"""
import argparse, csv, os, subprocess, sys, time
import numpy as np

import config, policy

GAP_NS = 150_000          # a pause longer than 150 microseconds = the task was NOT on the CPU
WINDOW_START, WINDOW_LEN = 4.0, 0.40   # the timeline we keep: 4.0 s to 4.4 s after the start


def child(role, start_ns, secs, outpath):
    os.sched_setaffinity(0, {0})
    now = time.perf_counter_ns
    while now() < start_ns:
        time.sleep(0.001)
    w0, w1 = start_ns + int(WINDOW_START * 1e9), start_ns + int((WINDOW_START + WINDOW_LEN) * 1e9)
    end = start_ns + int(secs * 1e9)
    segs, lat = [], []
    seg_start = last = now()

    def close(a, b):
        if b >= w0 and a <= w1:
            segs.append((max(a, w0), min(b, w1)))

    if role.startswith("hog"):
        while True:
            t = now()
            if t - last > GAP_NS:
                close(seg_start, last)
                seg_start = t
            last = t
            if t >= end:
                break
        close(seg_start, last)
    else:   # interactive
        while now() < end:
            t0 = now()
            time.sleep(0.020)
            t1 = now()
            lat.append((t1 - t0 - 20_000_000) / 1e6)
            seg_start = last = t1
            while now() - t1 < 3_000_000:      # work for 3 ms
                t = now()
                if t - last > GAP_NS:
                    close(seg_start, last)
                    seg_start = t
                last = t
            close(seg_start, last)
    with open(outpath, "w") as f:
        f.write("start_ms,end_ms,latency_ms\n")
        for a, b in segs:
            f.write(f"{(a - start_ns) / 1e6:.4f},{(b - start_ns) / 1e6:.4f},\n")
        for x in lat:
            f.write(f",,{x:.4f}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policies", default=",".join(config.POLICIES))
    ap.add_argument("--secs", type=int, default=12)
    ap.add_argument("--out", default="results")
    ap.add_argument("--child", nargs=4)
    a = ap.parse_args()
    if a.child:
        role, start_ns, secs, outpath = a.child
        return child(role, int(start_ns), float(secs), outpath)
    os.makedirs(os.path.join(a.out, "sched_logs"), exist_ok=True)
    tl_rows, lat_rows, table = [], [], []
    for name in a.policies.split(","):
        proc = None
        try:
            proc = policy.start(name, os.path.join(a.out, "sched_logs", f"demo_{name}.txt")) if name != "eevdf" else None
        except (policy.PolicyError, FileNotFoundError) as e:
            print(f"{name}: skipped ({e})")
            continue
        print(f"\n--- {name}  (active: {policy.ops_name() or 'EEVDF built-in'}) ---")
        start_ns = time.perf_counter_ns() + 800_000_000
        kids = []
        for role in ["hog1", "hog2", "interactive"]:
            tmp = os.path.join(a.out, f"_demo_{name}_{role}.csv")
            kids.append((role, tmp, subprocess.Popen([sys.executable, __file__, "--child", role, str(start_ns), str(a.secs), tmp])))
        for role, tmp, p in kids:
            p.wait()
        policy.stop(proc)
        for role, tmp, p in kids:
            for line in open(tmp).read().splitlines()[1:]:
                s, e, l = line.split(",")
                if s:
                    tl_rows.append((name, role, float(s), float(e)))
                if l:
                    lat_rows.append((name, float(l)))
            os.remove(tmp)
        lat = np.array([r[1] for r in lat_rows if r[0] == name])
        table.append((name, np.percentile(lat, 50), np.percentile(lat, 95), np.percentile(lat, 99), lat.max()))
        got = sum(e - s for n, r, s, e in tl_rows if n == name and r == "interactive")
        print(f"    interactive task woke up late by: median {table[-1][1]:.2f} ms, 95% {table[-1][2]:.2f} ms")
    with open(os.path.join(a.out, "demo_timeline.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["policy", "task", "start_ms", "end_ms"]); w.writerows(tl_rows)
    with open(os.path.join(a.out, "demo.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["policy", "latency_ms"]); w.writerows(lat_rows)
    print("\npolicy        median_ms   p95_ms   p99_ms   worst_ms   (how late the interactive task woke up)")
    for t in table:
        print(f"{t[0]:12s} {t[1]:9.2f} {t[2]:8.2f} {t[3]:8.2f} {t[4]:9.2f}")


if __name__ == "__main__":
    main()
