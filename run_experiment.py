#!/usr/bin/env python3
"""Runs the whole experiment: switches policies, runs every program, logs readings.

Examples
  sudo python3 run_experiment.py --pilot          # quick check (about 25 min)
  sudo python3 run_experiment.py                  # full run (about 8-9 hours)
  sudo python3 run_experiment.py --policies eevdf --secs 12 --per-block 3   # tiny test, no sudo needed
You can stop it with Ctrl+C and start it again: finished runs are skipped.
"""
import argparse, csv, json, os, platform, random, shutil, subprocess, sys, time

import config, policy

CLK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
SAMPLE_COLS = ["t", "cpu_s", "rss_kb", "wchar", "wait_ns", "slices", "alive"]
ROW_COLS = ["run_id", "round", "policy", "pos", "type", "kind", "program", "level", "is_virus",
            "warmup", "calib", "secs", "ended_early", "n_samples", "policy_ok", "ops", "start_epoch",
            "kernel"]

SUDO_UID = int(os.environ["SUDO_UID"]) if os.geteuid() == 0 and os.environ.get("SUDO_UID") else None
SUDO_GID = int(os.environ["SUDO_GID"]) if SUDO_UID is not None and os.environ.get("SUDO_GID") else None
LIVE = set()   # every child we started; all are killed on exit


def fix_owner(path):
    if SUDO_UID is None:
        return
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            try:
                os.chown(os.path.join(root, n), SUDO_UID, SUDO_GID)
            except OSError:
                pass
    try:
        os.chown(path, SUDO_UID, SUDO_GID)
    except OSError:
        pass


def launch(cmd, cores):
    kw = {}
    if SUDO_UID is not None:
        kw.update(user=SUDO_UID, group=SUDO_GID)
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         preexec_fn=lambda: os.sched_setaffinity(0, cores), **kw)
    LIVE.add(p)
    return p


def kill(p):
    if p.poll() is None:
        try:
            os.killpg(p.pid, 9)      # only the group WE started
        except ProcessLookupError:
            pass
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    LIVE.discard(p)


def _group_pids(pgid):
    """All processes of the group we started (the program and any copies it made)."""
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                s = f.read()
            if int(s[s.rfind(")") + 2:].split()[2]) == pgid:
                out.append(int(name))
        except (OSError, ValueError, IndexError):
            pass
    return out


def sample(pgid):
    """One reading of a program AND all its copies: CPU seconds, memory, bytes written, wait time.
    pgid = process group we created (= the program's PID)."""
    pids = _group_pids(pgid)
    if not pids:
        return None
    cpu = rss_kb = wchar = wait = slices = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/stat") as f:
                s = f.read()
            r = s[s.rfind(")") + 2:].split()
            cpu += (int(r[11]) + int(r[12])) / CLK
            with open(f"/proc/{pid}/statm") as f:
                rss_kb += int(f.read().split()[1]) * PAGE // 1024
            with open(f"/proc/{pid}/io") as f:
                for line in f:
                    if line.startswith("wchar:"):
                        wchar += int(line.split()[1])
            for tid in os.listdir(f"/proc/{pid}/task"):
                try:
                    with open(f"/proc/{pid}/task/{tid}/schedstat") as f:
                        a = f.read().split()
                    wait += int(a[1]); slices += int(a[2])
                except (OSError, IndexError, ValueError):
                    pass
        except (OSError, ValueError, IndexError):
            pass            # that copy just ended
    return cpu, rss_kb, wchar, wait, slices


def run_one(e, args, cores, work_cores, out):
    run_id = e["run_id"]
    workdir = os.path.join(out, "work", run_id)
    os.makedirs(workdir, exist_ok=True)
    fix_owner(workdir)
    burners = [launch([os.path.join(config.BIN, "cpu_prog"), "burn", "low", str(args.secs + args.pre + 10)],
                      work_cores) for _ in range(args.burners)]
    time.sleep(args.pre)
    cmd = [os.path.join(config.BIN, f"{e['type']}_prog"), e["kind"], e["level"], str(args.secs), workdir]
    start_epoch = time.time()
    t0 = time.monotonic()
    prog = launch(cmd, work_cores)
    rows, ended_early, i = [], 0, 0
    while True:
        target = t0 + i * config.SAMPLE_EVERY
        wait = target - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        t = time.monotonic() - t0
        s = sample(prog.pid) if (prog.poll() is None or _group_pids(prog.pid)) else None
        if s is None:
            if t < args.secs - 1.0:
                ended_early = 1
            rows.append((round(t, 3), "", "", "", "", "", 0))
            break
        rows.append((round(t, 3),) + s + (1,))
        if t >= args.secs:
            break
        i += 1
    kill(prog)
    for b in burners:
        kill(b)
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(os.path.join(out, "logs"), exist_ok=True)
    with open(os.path.join(out, "logs", run_id + ".csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(SAMPLE_COLS)
        w.writerows(rows)
    return start_epoch, ended_early, len(rows)


def block(policy_name, rnd, rng, calib, per_block):
    items = [(t, k, v, l) for t in config.TYPES for (k, v) in config.KINDS for l in config.LEVELS]
    rng.shuffle(items)
    if per_block and not calib:
        items = items[:per_block]
    out = []
    for idx, (t, k, v, l) in enumerate([("cpu", "steady", True, "low")] + items):  # first = warm-up (discarded)
        warm = idx == 0
        tag = "W" if warm else f"{idx:02d}"
        out.append(dict(run_id=f"r{rnd}_{policy_name}_{tag}_{t}_{k}_{l}", round=rnd, policy=policy_name,
                        pos=idx, type=t, kind=k, program=config.program_name(t, k), level=l,
                        is_virus=int(v), warmup=int(warm), calib=int(calib)))
    return out


def main():
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--secs", type=int, default=config.SECS)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--policies", default=",".join(config.POLICIES))
    ap.add_argument("--pre", type=float, default=config.PRE_SECS)
    ap.add_argument("--post", type=float, default=config.POST_SECS)
    ap.add_argument("--burners", type=int, default=config.BURNERS)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--skip-cal", action="store_true", help="skip the calibration block")
    ap.add_argument("--per-block", type=int, default=0, help="only run N programs per block (testing)")
    ap.add_argument("--pilot", action="store_true", help="quick check: 20 s runs, 6 programs per block, 1 repeat")
    a = ap.parse_args()
    if a.pilot:
        a.secs, a.repeats, a.per_block = 20, 1, 6

    ncpu = os.cpu_count() or 1
    logger_core = ncpu - 1
    work_cores = set(range(ncpu - 1)) or {0}
    if a.burners is None:
        a.burners = len(work_cores)
    os.sched_setaffinity(0, {logger_core})     # the logger lives alone on the last core

    pols = [p for p in a.policies.split(",") if p]
    for p in pols:
        if p not in config.POLICIES:
            sys.exit(f"Unknown policy {p}")
    if any(p != "eevdf" for p in pols) and os.geteuid() != 0:
        sys.exit("The scx policies need admin rights. Run with: sudo python3 run_experiment.py ...")
    if not os.path.exists(os.path.join(config.BIN, "cpu_prog")):
        sys.exit("Test programs are not built. Run ./setup.sh first.")

    out = os.path.abspath(a.out)
    os.makedirs(os.path.join(out, "logs"), exist_ok=True)
    os.makedirs(os.path.join(out, "sched_logs"), exist_ok=True)
    rng = random.Random(a.seed)
    plan = []
    if not a.skip_cal:
        plan += block("eevdf", 0, rng, True, 0)
    for r in range(1, a.repeats + 1):
        order = pols[:]
        rng.shuffle(order)
        for p in order:
            plan += block(p, r, rng, False, a.per_block)

    runs_csv = os.path.join(out, "runs.csv")
    done = set()
    if os.path.exists(runs_csv):
        with open(runs_csv) as f:
            done = {r["run_id"] for r in csv.DictReader(f)}
    todo = [e for e in plan if e["run_id"] not in done]
    per_run = a.secs + a.pre + a.post + 1.5
    print(f"Plan: {len(plan)} runs ({len(done & {e['run_id'] for e in plan})} already done, {len(todo)} to go).")
    print(f"Estimated time left: about {len(todo) * per_run / 3600:.1f} hours (+ a few minutes per policy switch).")
    print(f"Logger on core {logger_core}; programs and {a.burners} background hogs on cores {sorted(work_cores)}.")

    meta = dict(kernel=platform.release(), python=platform.python_version(), args=vars(a),
                versions={p: policy.version_of(p) for p in pols}, started=time.ctime(), ncpu=ncpu)
    with open(os.path.join(out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    new_file = not os.path.exists(runs_csv)
    fcsv = open(runs_csv, "a", newline="")
    wcsv = csv.DictWriter(fcsv, fieldnames=ROW_COLS)
    if new_file:
        wcsv.writeheader()

    cur_name, cur_proc, t_start, ndone = None, None, time.time(), 0
    try:
        for e in todo:
            if e["policy"] != cur_name or not policy.is_ok(cur_name, cur_proc):
                try:
                    policy.stop(cur_proc)
                except policy.PolicyError as err:
                    print("WARNING:", err)
                cur_name, cur_proc = e["policy"], None
                print(f"\n=== Switching to policy: {cur_name} ===")
                cur_proc = policy.start(cur_name, os.path.join(out, "sched_logs", f"r{e['round']}_{cur_name}.txt"))
                print(f"    sched_ext state='{policy.state() or 'n/a'}'  active scheduler='{policy.ops_name() or 'EEVDF (built-in)'}'")
                if not e["warmup"]:     # resumed in the middle of a block: do a throw-away warm-up first
                    w = dict(e, run_id=e["run_id"] + "_resumeW", warmup=1)
                    run_one(w, a, work_cores, work_cores, out)
            se, early, n = run_one(e, a, work_cores, work_cores, out)
            ok = policy.is_ok(cur_name, cur_proc)
            row = dict(e, secs=a.secs, ended_early=early, n_samples=n, policy_ok=int(ok),
                       ops=policy.ops_name() or "eevdf", start_epoch=round(se, 3), kernel=platform.release())
            wcsv.writerow(row)
            fcsv.flush()
            fix_owner(out)
            ndone += 1
            left = len(todo) - ndone
            eta = (time.time() - t_start) / ndone * left / 3600
            print(f"[{ndone}/{len(todo)}] {cur_name:12s} {e['program']:11s} {e['level']:4s}"
                  f"{' (warm-up, discarded)' if e['warmup'] else ''}"
                  f"{'  !! ended early' if early else ''}{'  !! policy changed' if not ok else ''}"
                  f"   ~{eta:.1f} h left")
            time.sleep(a.post)
    except KeyboardInterrupt:
        print("\nStopped by you. Start the same command again to continue where it stopped.")
    finally:
        for p in list(LIVE):
            kill(p)
        try:
            policy.stop(cur_proc)
        except policy.PolicyError as err:
            print("WARNING:", err)
        fcsv.close()
        fix_owner(out)
    print("Finished. Results are in", out)


if __name__ == "__main__":
    main()
