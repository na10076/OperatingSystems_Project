#!/usr/bin/env python3
"""Turns results/ into tables and graphs.  Run:  python3 analyze.py   (no sudo needed)

Published code used here (cite in the report): pandas (McKinney, 2010) for tables and sliding windows,
scikit-learn roc_curve / auc (Pedregosa et al., 2011), SciPy bootstrap, binomtest (Wilson interval),
Wilcoxon and Kruskal-Wallis tests (Virtanen et al., 2020), matplotlib (Hunter, 2007) for the graphs.

Both detectors are run on the SAME recordings, so the comparison is a fair pair.
Alarm lines come ONLY from the calibration round (EEVDF, harmless look-alikes) and are then frozen.
"""
import argparse, json, os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config, detect

# ---- look: validated reference palette (light mode), one font, quiet grid ----
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
POL_COL = {"eevdf": "#2a78d6", "scx_simple": "#eb6834", "scx_bpfland": "#1baf7a",
           "scx_flash": "#eda100", "scx_lavd": "#e87ba4"}
DET_COL = {"snapshot": "#2a78d6", "run5": "#f4a07c", "run10": "#eb6834", "run30": "#b24a1f"}
DET_LAB = {"snapshot": "Snapshot (quick look)", "run5": "Running total 5 s",
           "run10": "Running total 10 s", "run30": "Running total 30 s"}
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
                     "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
                     "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
                     "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
                     "axes.titlelocation": "left", "legend.frameon": False})
RNG = np.random.default_rng(7)


def boot_ci(x, fn=np.mean, n=2000):
    """Mean with a 95% bootstrap range, using scipy.stats.bootstrap (Virtanen et al., 2020)."""
    from scipy import stats
    x = np.asarray(x, float)
    if len(x) == 0:
        return np.nan, np.nan, np.nan
    if len(x) == 1 or np.all(x == x[0]):
        return fn(x), fn(x), fn(x)
    r = stats.bootstrap((x,), fn, n_resamples=n, confidence_level=0.95, method="percentile", random_state=7)
    return fn(x), r.confidence_interval.low, r.confidence_interval.high


def wilson(k, n):
    """Rate with a 95% Wilson score range, using scipy.stats.binomtest (Wilson, 1927; Virtanen et al., 2020)."""
    from scipy import stats
    if n == 0:
        return np.nan, np.nan, np.nan
    ci = stats.binomtest(int(k), int(n)).proportion_ci(confidence_level=0.95, method="wilson")
    return k / n, ci.low, ci.high


def save(fig, name, out):
    os.makedirs(os.path.join(out, "figures"), exist_ok=True)
    fig.savefig(os.path.join(out, "figures", name), dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  figure:", name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results")
    ap.add_argument("--calib", default="split50", choices=["split50", "lookalike"],
                    help="split50 (project plan): half of the runs set the alarm lines so they catch 95%% of "
                         "the viruses there, the other half is the test. lookalike: EEVDF calibration round, "
                         "line just above the loudest harmless program.")
    ap.add_argument("--seed", type=int, default=11, help="seed for the 50/50 split")
    a = ap.parse_args()
    out = a.out                                   # where the recordings are read from
    dst = os.path.join(out, f"analysis_{a.calib}")  # where tables and graphs are written
    os.makedirs(dst, exist_ok=True)
    runs = pd.read_csv(os.path.join(out, "runs.csv"))
    meta = json.load(open(os.path.join(out, "meta.json")))
    secs = float(runs["secs"].iloc[0])
    n_all = len(runs)
    bad = runs[(runs["ended_early"] == 1) | (runs["policy_ok"] == 0)]
    n_warm = int((runs["warmup"] == 1).sum())
    n_round0 = int(((runs["calib"] == 1) & (runs["warmup"] == 0)).sum())
    runs = runs[(runs["ended_early"] == 0) & (runs["policy_ok"] == 1) & (runs["warmup"] == 0)]
    if a.calib == "split50":
        # Use only the main rounds (1, 2, 3, ...), which every policy has the same number of. The old EEVDF-only
        # calibration round (round 0) is left out so every policy x program x strength has the same repeats.
        runs = runs[runs["calib"] == 0]
        # Project plan: half of the runs (every policy, every program, every intensity) set the lines,
        # the other half is the test. Stratified: each policy x program x intensity cell is split in half;
        # odd-sized cells alternate which half gets the extra run, so the overall split is ~50/50.
        rng_split = np.random.default_rng(a.seed)
        half, toggle = {}, 0
        for _, g in runs.sort_values("run_id").groupby(["policy", "program", "level"], sort=True):
            ids_ = list(g["run_id"])
            rng_split.shuffle(ids_)
            k = len(ids_) // 2
            if len(ids_) % 2:
                k += toggle
                toggle ^= 1
            for i, rid in enumerate(ids_):
                half[rid] = "calibration" if i < k else "test"
        runs = runs.assign(half=runs["run_id"].map(half))
        runs[["run_id", "policy", "program", "level", "round", "half"]].to_csv(os.path.join(dst, "split.csv"), index=False)
        cal = runs[runs["half"] == "calibration"]
        test = runs[runs["half"] == "test"].copy()
    else:
        cal = runs[runs["calib"] == 1]
        test = runs[runs["calib"] == 0].copy()
    if a.calib == "split50" and cal[cal["is_virus"] == 1].empty:
        sys.exit("No virus runs in the calibration half.")
    if a.calib == "lookalike" and cal[cal["is_virus"] == 0].empty:
        sys.exit("No calibration look-alike runs found. Run the experiment without --skip-cal first.")
    if test.empty:
        sys.exit("No test runs found yet.")
    pols = [p for p in config.POLICIES if p in set(test["policy"])]
    dets = list(config.DETECTORS)

    # ---- load recordings once ----
    logs = {r.run_id: detect.load_log(os.path.join(out, "logs", r.run_id + ".csv")) for r in runs.itertuples()}
    ser = {(rid, d): detect.series(df, config.DETECTORS[d]) for rid, df in logs.items() for d in dets}

    # ---- calibration: frozen alarm lines ----
    lines = {}
    for d in dets:
        if a.calib == "split50":
            by_type = {t: [ser[(r.run_id, d)] for r in cal[(cal["is_virus"] == 1) & (cal["type"] == t)].itertuples()]
                       for t in detect.SIGNALS}
            lines[d] = detect.calibrate95(by_type)
        else:
            reads = [ser[(r.run_id, d)] for r in cal[cal["is_virus"] == 0].itertuples()]
            lines[d] = detect.calibrate(reads)
    json.dump(lines, open(os.path.join(dst, "alarm_lines.json"), "w"), indent=1)

    # how the frozen lines do on the calibration half itself (should be ~95% caught for split50)
    cal_check = {}
    for d in dets:
        hit = {0: [], 1: []}
        for r in cal.itertuples():
            hit[int(r.is_virus)].append(np.isfinite(detect.alarm(*ser[(r.run_id, d)], lines[d])[0]))
        cal_check[d] = (np.mean(hit[1]) if hit[1] else np.nan, np.mean(hit[0]) if hit[0] else np.nan)

    # ---- alarms on every test run, for every detector ----
    rows = []
    for r in test.itertuples():
        for d in dets:
            t, sig = ser[(r.run_id, d)]
            at, which = detect.alarm(t, sig, lines[d])
            rows.append(dict(run_id=r.run_id, policy=r.policy, round=r.round, program=r.program, type=r.type,
                             kind=r.kind, level=r.level, is_virus=r.is_virus, detector=d, alarm_t=at,
                             signal=which, ttd=at if np.isfinite(at) else secs))
    al = pd.DataFrame(rows)
    al.to_csv(os.path.join(dst, "alarms.csv"), index=False)
    vir, harm = al[al.is_virus == 1], al[al.is_virus == 0]

    # ---- summary tables ----
    summ = []
    for d in dets:
        for p in pols + ["ALL"]:
            v = vir[(vir.detector == d) & ((vir.policy == p) | (p == "ALL"))]
            h = harm[(harm.detector == d) & ((harm.policy == p) | (p == "ALL"))]
            det = v["alarm_t"].notna()
            m, lo, hi = boot_ci(v["ttd"])
            # catch-curve median: first time at which half of the virus runs have been caught
            # (Kaplan-Meier style; every run is watched for the same 60 s, so the curve is just the share caught)
            at_ = np.sort(v.loc[det, "alarm_t"].to_numpy(float))
            half_t = at_[int(np.ceil(len(v) / 2)) - 1] if len(v) and len(at_) >= np.ceil(len(v) / 2) else np.nan
            summ.append(dict(detector=d, policy=p, virus_runs=len(v), detection_rate=det.mean() if len(v) else np.nan,
                             lookalike_runs=len(h), false_alarm_rate=h["alarm_t"].notna().mean() if len(h) else np.nan,
                             median_ttd_detected=v.loc[det, "alarm_t"].median() if det.any() else np.nan,
                             time_to_catch_half=half_t,
                             mean_ttd_censored=m, ttd_ci_lo=lo, ttd_ci_hi=hi))
    S = pd.DataFrame(summ)
    S.to_csv(os.path.join(dst, "summary_by_policy_detector.csv"), index=False)

    # ---- ROC analysis with scikit-learn (Pedregosa et al., 2011) ----
    # One score per run = its highest reading divided by the alarm line. Sweeping the line up and
    # down is exactly what sklearn.metrics.roc_curve does with these scores.
    from sklearn.metrics import roc_curve, auc as sk_auc
    ids = list(test["run_id"])
    isv = test["is_virus"].to_numpy() == 1
    typ = test["type"].to_numpy()
    lev = test["level"].to_numpy()
    pol = test["policy"].to_numpy()
    SC = {d: np.array([detect.peak_score(ser[(rid, d)][1], lines[d]) for rid in ids]) for d in dets}

    def _roc(y, s):
        if y.all() or (~y).all():
            return None, None
        fpr, tpr, _ = roc_curve(y.astype(int), s)
        return tpr, fpr

    def curve(d, mask):
        return _roc(isv[mask], SC[d][mask])

    def auc_of(tpr, fpr):
        return float(sk_auc(fpr, tpr))

    def fa_at(tpr, fpr, target=0.95):
        ok = tpr >= target
        return float(fpr[ok].min()) if ok.any() else np.nan

    def boot_metric(d, mask, fn, n=200):
        vi, hi = np.where(mask & isv)[0], np.where(mask & ~isv)[0]
        if len(vi) == 0 or len(hi) == 0:
            return np.nan, np.nan, np.nan
        def one(ix):
            tpr, fpr = _roc(isv[ix], SC[d][ix])
            return fn(tpr, fpr) if tpr is not None else np.nan
        base = one(np.concatenate([vi, hi]))
        vals = np.array([one(np.concatenate([RNG.choice(vi, len(vi)), RNG.choice(hi, len(hi))])) for _ in range(n)], float)
        if np.isnan(vals).all():
            return base, np.nan, np.nan
        return base, np.nanpercentile(vals, 2.5), np.nanpercentile(vals, 97.5)

    ALL = np.ones(len(ids), bool)
    auc = {d: auc_of(*curve(d, ALL)) for d in dets}

    # ---- statistics ----
    lines_txt = []
    lines_txt.append(f"Runs recorded: {n_all}. Thrown away: {n_warm} warm-ups, {len(bad)} problem runs (ended early / policy changed)"
                     + (f", {n_round0} runs of the old EEVDF-only calibration round (not used, so every policy has the same repeats)"
                        if a.calib == "split50" else "") + ".")
    lines_txt.append(f"Used: {len(runs)} runs = calibration {len(cal)} + test {len(test)}.")
    lines_txt.append(f"Kernel: {meta['kernel']}   Versions: {meta['versions']}")
    if a.calib == "split50":
        lines_txt.append("\nMethod: 50/50 split. Lines set on the calibration half so each one catches 95% of that half's "
                         "viruses of its type (CPU line from CPU viruses, etc.), then frozen and applied to the test half.")
    else:
        lines_txt.append("\nMethod: lines set on the EEVDF calibration round, just above the loudest harmless program.")
    lines_txt.append("Frozen alarm lines:")
    for d in dets:
        lines_txt.append(f"  {d:9s} cpu>{lines[d]['cpu']:.0f}%  mem>{lines[d]['mem']:.0f} MB  io>{lines[d]['io']:.1f} MB/s"
                         f"   | on the calibration half: caught {cal_check[d][0]:.0%}, false alarms {cal_check[d][1]:.0%}")
    lines_txt.append("\nPooled over all policies:")
    for d in dets:
        r = S[(S.detector == d) & (S.policy == "ALL")].iloc[0]
        fa95 = fa_at(*curve(d, ALL))
        lines_txt.append(f"  {DET_LAB[d]:24s} detection {r.detection_rate:.0%}  false alarms {r.false_alarm_rate:.0%}  "
                         f"false alarms at 95% detection {('%.0f%%' % (fa95 * 100)) if fa95 == fa95 else 'not reachable'}  "
                         f"AUC {auc[d]:.2f}")
        half = f"{r.time_to_catch_half:.1f} s" if r.time_to_catch_half == r.time_to_catch_half else "never (under half caught)"
        when = f"{r.median_ttd_detected:.1f} s" if r.median_ttd_detected == r.median_ttd_detected else "-"
        lines_txt.append(f"  {'':24s} time to detect: median when caught {when} | time until half the viruses are caught {half} | "
                         f"restricted mean within {secs:.0f} s {r.mean_ttd_censored:.1f} s (a miss counts as {secs:.0f} s)")
    try:
        from scipy import stats
        piv = vir.pivot_table(index="run_id", columns="detector", values="ttd")
        for d in [x for x in dets if x != "snapshot"]:
            w = stats.wilcoxon(piv["snapshot"], piv[d]) if (piv["snapshot"] != piv[d]).any() else None
            lines_txt.append(f"Paired Wilcoxon snapshot vs {d} on time to detect: " + (f"p = {w.pvalue:.4f}" if w else "identical"))
        for d in ["snapshot", "run10"]:
            groups = [g["ttd"].to_numpy() for _, g in vir[vir.detector == d].groupby("policy") if len(g) > 1]
            if len(groups) > 1 and len({tuple(np.round(x, 3)) for x in groups}) > 1:
                k = stats.kruskal(*groups)
                lines_txt.append(f"Kruskal-Wallis, does policy change time to detect ({d})? p = {k.pvalue:.4f}")
    except Exception as ex:
        lines_txt.append(f"(statistics skipped: {ex})")
    lines_txt.append(f"\nNote: three views of time to detect. 'Median when caught' ignores misses (read it together with the detection rate). "
                     f"'Time until half are caught' is the median of the catch curve (Kaplan & Meier, 1958). 'Restricted mean' "
                     f"counts a miss as {secs:.0f} s (restricted mean survival time; Royston & Parmar, 2013). The statistical tests use the restricted mean.")
    open(os.path.join(dst, "summary.txt"), "w").write("\n".join(lines_txt))
    print("\n".join(lines_txt))

    show = ["snapshot", "run10"]
    TYPES = [t for t in config.TYPES if t in set(typ)]
    TLAB = {"cpu": "CPU", "mem": "Memory", "io": "Disk (I/O)"}

    # ================= YOUR 11 GRAPHS =================
    def safe(fn):
        try:
            fn()
        except Exception as ex:
            print(f"  !! {fn.__name__} skipped: {type(ex).__name__}: {ex}")

    TOP = dict(x=0.01, ha="left", fontsize=11, fontweight="bold")
    steady_kinds = [("steady", "Steady viruses"), ("bursty", "Bursty viruses")]

    # 1. time to detect by policy and detector (steady vs bursty rows, one column per virus type)
    def fig01():
        fig, axes = plt.subplots(2, len(TYPES), figsize=(4.2 * len(TYPES), 6.2), sharey=True, squeeze=False)
        w = 0.38
        for r_, (kind, klab) in enumerate(steady_kinds):
            for c_, t in enumerate(TYPES):
                ax = axes[r_][c_]
                for j, d in enumerate(show):
                    for i, p in enumerate(pols):
                        x_ = vir[(vir.detector == d) & (vir.type == t) & (vir.kind == kind) & (vir.policy == p)]["ttd"].to_numpy()
                        if len(x_) == 0:
                            continue
                        m, lo, hi = boot_ci(x_)
                        x = i + (j - 0.5) * w
                        ax.bar(x, m, w * 0.92, color=DET_COL[d], label=DET_LAB[d] if (i == 0 and r_ == 0 and c_ == 0) else None)
                        ax.errorbar(x, m, yerr=[[m - lo], [hi - m]], color=INK2, capsize=2, lw=1)
                ax.set_xticks(range(len(pols))); ax.set_xticklabels(pols, rotation=30, ha="right", fontsize=8)
                ax.set_title(f"{TLAB[t]} - {klab}", fontsize=10)
                if c_ == 0:
                    ax.set_ylabel(f"restricted mean time to detect (s)\n(a miss counts as {secs:.0f} s)", fontsize=9)
        h_, l_ = axes[0][0].get_legend_handles_labels()
        fig.legend(h_, l_, loc="lower center", ncol=2, fontsize=9, bbox_to_anchor=(0.5, -0.01))
        fig.suptitle("Fig 1. Time to detect (restricted mean within the run), by policy and detector (bars = 95% range)", **TOP)
        fig.tight_layout(rect=(0, 0.04, 1, 0.96))
        save(fig, "fig01_time_to_detect_by_policy.png", dst)

    # 2. detection rate and false-alarm rate per detector per policy
    def fig02():
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
        w = 0.2
        for ax, (isvir, ttl) in zip(axes, [(1, "Fake viruses caught"), (0, "Harmless programs wrongly flagged")]):
            for j, d in enumerate(dets):
                for i, p in enumerate(pols):
                    sub = al[(al.detector == d) & (al.policy == p) & (al.is_virus == isvir)]
                    n, k = len(sub), int(sub.alarm_t.notna().sum())
                    if n == 0:
                        continue
                    pr, lo, hi = wilson(k, n)
                    x = i + (j - 1.5) * w
                    ax.bar(x, pr, w * 0.92, color=DET_COL[d], label=DET_LAB[d] if i == 0 else None)
                    ax.errorbar(x, pr, yerr=[[pr - lo], [hi - pr]], color=INK2, capsize=2, lw=1)
            ax.set_xticks(range(len(pols))); ax.set_xticklabels(pols, rotation=20, ha="right")
            ax.set_title(ttl); ax.set_ylim(0, 1.08); ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        axes[0].legend(fontsize=8, loc="lower left", ncol=1)
        fig.suptitle("Fig 2. Detection rate and false-alarm rate, per detector and policy (bars = 95% range)", **TOP)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        save(fig, "fig02_detection_and_false_alarm_rate.png", dst)

    # 3. dot picture
    def fig03():
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.3), sharey=True)
        for ax, d in zip(axes, show):
            for gi, t in enumerate(TYPES):
                for isvir, off, mk, col, lab in [(0, -0.18, "o", "#2a78d6", "Harmless look-alike"), (1, 0.18, "D", "#eb6834", "Fake virus")]:
                    sel = [rid for rid, tt, v in zip(ids, typ, isv) if tt == t and v == bool(isvir)]
                    ys = []
                    for rid in sel:
                        tt_, sg = ser[(rid, d)]
                        ys.append(max(np.nanmax(sg[k] / lines[d][k]) if np.isfinite(sg[k]).any() else 0 for k in detect.SIGNALS))
                    xs = gi + off + RNG.uniform(-0.09, 0.09, len(ys))
                    ax.scatter(xs, np.clip(ys, 0, 6), s=22, marker=mk, color=col, alpha=0.85, label=lab if gi == 0 else None, linewidths=0)
            ax.axhline(1, color=INK2, lw=1, ls=":")
            ax.text(len(TYPES) - 0.5, 1.05, "alarm line", ha="right", color=INK2, fontsize=8)
            ax.set_xticks(range(len(TYPES))); ax.set_xticklabels([TLAB[t] for t in TYPES]); ax.set_title(DET_LAB[d])
        axes[0].set_ylabel("highest reading in the run (1 = alarm line)")
        axes[0].legend(loc="upper left", fontsize=8)
        fig.suptitle("Fig 3. Dot picture: can one line split the two groups? (each dot = one run's peak reading)", **TOP)
        save(fig, "fig03_dot_picture.png", dst)

    # 4. ROC curves per virus type
    def fig04():
        fig, axes = plt.subplots(1, len(TYPES), figsize=(4.4 * len(TYPES), 4.6), sharex=True, sharey=True, squeeze=False)
        for ax, t in zip(axes[0], TYPES):
            for d in dets:
                c_ = curve(d, typ == t)
                if c_[0] is None:
                    continue
                tpr, fpr = c_
                o = np.lexsort((tpr, fpr))
                ax.step(fpr[o], np.maximum.accumulate(tpr[o]), where="post", color=DET_COL[d], lw=2 if d in show else 1.1,
                        label=f"{DET_LAB[d]} (AUC {auc_of(tpr, fpr):.2f})")
            ax.plot([0, 1], [0, 1], color=GRID, lw=1, ls="--")
            ax.set_title(TLAB[t]); ax.set_xlim(0, 1); ax.set_ylim(0, 1.02); ax.legend(loc="lower right", fontsize=7)
            ax.set_xlabel("harmless programs wrongly flagged")
        axes[0][0].set_ylabel("fake viruses caught")
        fig.suptitle("Fig 4. ROC curves per virus type (top-left is best)", **TOP)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save(fig, "fig04_roc_curves.png", dst)

    # 5. policy effect heatmap: change in time to detect vs EEVDF, blank if within the noise
    def fig05():
        others = [p for p in pols if p != "eevdf"]
        if "eevdf" not in pols or not others:
            raise ValueError("needs EEVDF and at least one other policy")
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.4 + 0.3 * len(others)), constrained_layout=True)
        cm = matplotlib.colors.LinearSegmentedColormap.from_list("div", ["#2a78d6", "#ecebe7", "#eb6834"])
        rows_out = []
        for ax, d in zip(axes, show):
            Mx = np.full((len(others), len(TYPES)), np.nan)
            sig = np.zeros_like(Mx, bool)
            for i, p in enumerate(others):
                for j, t in enumerate(TYPES):
                    a_ = vir[(vir.detector == d) & (vir.type == t) & (vir.policy == p)]["ttd"].to_numpy()
                    b_ = vir[(vir.detector == d) & (vir.type == t) & (vir.policy == "eevdf")]["ttd"].to_numpy()
                    if len(a_) < 2 or len(b_) < 2:
                        continue
                    diff = a_.mean() - b_.mean()
                    bs = [RNG.choice(a_, len(a_)).mean() - RNG.choice(b_, len(b_)).mean() for _ in range(2000)]
                    lo, hi = np.percentile(bs, [2.5, 97.5])
                    Mx[i, j] = diff
                    sig[i, j] = not (lo <= 0 <= hi)
                    rows_out.append(dict(detector=d, policy=p, type=t, change_s=diff, ci_lo=lo, ci_hi=hi, outside_noise=bool(sig[i, j])))
            lim = max(np.nanmax(np.abs(Mx)) if np.isfinite(Mx).any() else 1, 1)
            show_M = np.where(sig, Mx, np.nan)
            ax.imshow(np.zeros_like(Mx), cmap="Greys", vmin=0, vmax=1, aspect="auto", alpha=0.0)
            im = ax.imshow(show_M, cmap=cm, vmin=-lim, vmax=lim, aspect="auto")
            ax.grid(False)
            ax.set_xticks(range(len(TYPES))); ax.set_xticklabels([TLAB[t] for t in TYPES])
            ax.set_yticks(range(len(others))); ax.set_yticklabels(others if ax is axes[0] else [])
            for i in range(Mx.shape[0]):
                for j in range(Mx.shape[1]):
                    if sig[i, j]:
                        ax.text(j, i, f"{Mx[i, j]:+.1f} s", ha="center", va="center", fontsize=9, color=INK)
                    elif np.isfinite(Mx[i, j]):
                        ax.text(j, i, "within noise", ha="center", va="center", fontsize=7, color=INK2)
            ax.set_title(DET_LAB[d])
        fig.colorbar(im, ax=axes, shrink=0.8, label="change in restricted mean time to detect vs EEVDF\n(blue = faster, orange = slower)")
        fig.suptitle("Fig 5. Where did a policy really make a difference? (blank = within the noise)", **TOP)
        pd.DataFrame(rows_out).to_csv(os.path.join(dst, "policy_effect_vs_eevdf.csv"), index=False)
        save(fig, "fig05_policy_effect_heatmap.png", dst)

    # 6. catch curve: % of fake-virus runs already alarmed, over time
    def fig06():
        grid = np.arange(0, secs + 0.01, 0.5)
        def curve_t(df):
            a_ = df["alarm_t"].to_numpy(dtype=float)
            return [np.mean(np.isfinite(a_) & (a_ <= g)) for g in grid]
        fig, axes = plt.subplots(1, 3, figsize=(14, 4), sharey=True)
        for d in dets:
            axes[0].plot(grid, curve_t(vir[vir.detector == d]), color=DET_COL[d], lw=2 if d in show else 1.2, label=DET_LAB[d])
        axes[0].set_title("By detector (all policies pooled)"); axes[0].legend(fontsize=8, loc="lower right")
        for ax, d in zip(axes[1:], show):
            for p in pols:
                sub = vir[(vir.detector == d) & (vir.policy == p)]
                if len(sub):
                    ax.plot(grid, curve_t(sub), color=POL_COL[p], lw=1.8, label=p)
            ax.set_title(f"By policy - {DET_LAB[d]}"); ax.legend(fontsize=8, loc="lower right")
        for ax in axes:
            ax.set_xlabel("seconds since the program started"); ax.set_ylim(0, 1.02)
            ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        axes[0].set_ylabel("fake viruses already caught")
        fig.suptitle("Fig 6. Catch curves (Kaplan-Meier style): share of fake viruses already caught at each second", **TOP)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save(fig, "fig06_catch_curves.png", dst)

    # 7. result by intensity
    def fig07():
        levels = [l for l in config.LEVELS if l in set(lev)]
        fig, axes = plt.subplots(1, len(TYPES), figsize=(4.2 * len(TYPES), 3.9), sharey=True, squeeze=False)
        for ax, t in zip(axes[0], TYPES):
            for d in dets:
                ys = []
                for l in levels:
                    c_ = curve(d, (typ == t) & (lev == l))
                    ys.append(auc_of(*c_) if c_[0] is not None else np.nan)
                ax.plot(range(len(levels)), ys, marker="o", color=DET_COL[d], lw=2 if d in show else 1.1, label=DET_LAB[d])
            ax.set_xticks(range(len(levels))); ax.set_xticklabels(levels); ax.set_title(TLAB[t]); ax.set_ylim(0, 1.05)
            ax.set_xlabel("fake-virus intensity")
        axes[0][0].set_ylabel("how well the detector separates (AUC)")
        axes[0][0].legend(fontsize=7, loc="lower right")
        fig.suptitle("Fig 7. Result by intensity: are low-intensity viruses missed?", **TOP)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save(fig, "fig07_result_by_intensity.png", dst)

    # 8. window length: what extra steadiness costs in delay
    def fig08():
        fig, axes = plt.subplots(1, len(TYPES), figsize=(4.4 * len(TYPES), 4.2), sharey=True, squeeze=False)
        for ax, t in zip(axes[0], TYPES):
            pts = []
            for d in dets:
                v = vir[(vir.detector == d) & (vir.type == t)]["ttd"].to_numpy()
                h = harm[(harm.detector == d) & (harm.type == t)]
                if len(v) == 0 or len(h) == 0:
                    continue
                m, lo, hi = boot_ci(v)
                fa = h["alarm_t"].notna().mean()
                pts.append((d, fa, m, lo, hi))
                ax.errorbar(fa, m, yerr=[[m - lo], [hi - m]], fmt="o", color=DET_COL[d], capsize=3, ms=7)
                ax.annotate(DET_LAB[d].replace("Running total ", "RT ").replace(" (quick look)", ""), (fa, m), textcoords="offset points",
                            xytext=(6, 5), fontsize=8, color=INK2)
            rt = [p for p in pts if p[0] != "snapshot"]
            ax.plot([p[1] for p in rt], [p[2] for p in rt], color=GRID, lw=1.2, zorder=0)
            ax.set_title(TLAB[t]); ax.set_xlabel("harmless programs wrongly flagged"); ax.set_xlim(-0.05, 1.05)
            ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        axes[0][0].set_ylabel("restricted mean time to detect (s)\n(a miss counts as the full run)")
        fig.suptitle("Fig 8. Window length: time to detect against false alarms (running total 5, 10, 30 s)", **TOP)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        save(fig, "fig08_window_length.png", dst)

    # 9. one-run example
    def fig09():
        ex_v = test[(test.program == "cpu_bursty") & (test.level == "low")]
        ex_h = test[(test.program == "cpu_batch") & (test.level == "low")]
        if not (len(ex_v) and len(ex_h)):
            raise ValueError("needs cpu_bursty and cpu_batch runs")
        pol0 = ex_v.iloc[0].policy
        rv = ex_v[ex_v.policy == pol0].iloc[0].run_id
        rh = ex_h[ex_h.policy == pol0].iloc[0].run_id if len(ex_h[ex_h.policy == pol0]) else ex_h.iloc[0].run_id
        fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
        for ax, rid, ttl in zip(axes, [rv, rh], ["Fake virus (cpu_bursty)", "Harmless batch job (cpu_batch)"]):
            for d in show:
                t_, sg = ser[(rid, d)]
                ax.plot(t_, sg["cpu"], color=DET_COL[d], lw=1.6, label=DET_LAB[d])
                ax.axhline(lines[d]["cpu"], color=DET_COL[d], lw=1, ls=":")
            ax.set_title(ttl); ax.set_xlabel("seconds since program started")
        axes[0].set_ylabel("CPU use (% of one core)"); axes[0].legend(fontsize=8)
        fig.suptitle(f"Fig 9. One run, what each detector sees (dotted = alarm line; policy {pol0})", **TOP)
        save(fig, "fig09_one_run_example.png", dst)

    # 10. wait time by policy (from /proc schedstat)
    mech = []
    for r in runs[(runs.calib == 0)].itertuples():
        df = logs[r.run_id]
        if len(df) < 3:
            continue
        mech.append(dict(policy=r.policy, program=r.program, type=r.type, kind=r.kind, level=r.level, is_virus=r.is_virus,
                         cpu_pct=df.cpu_s.iloc[-1] / max(df.t.iloc[-1], 1e-9) * 100,
                         wait_s_per_s=df.wait_ns.iloc[-1] / 1e9 / max(df.t.iloc[-1], 1e-9)))
    Mm = pd.DataFrame(mech)
    Mm.to_csv(os.path.join(dst, "mechanism.csv"), index=False)

    def fig10():
        fig, axes = plt.subplots(1, len(TYPES), figsize=(4.4 * len(TYPES), 4), sharey=False, squeeze=False)
        for ax, t in zip(axes[0], TYPES):
            data, labs, cols = [], [], []
            for p in pols:
                x_ = Mm[(Mm.type == t) & (Mm.is_virus == 1) & (Mm.policy == p)]["wait_s_per_s"].to_numpy()
                if len(x_):
                    data.append(x_); labs.append(p); cols.append(POL_COL[p])
            bp = ax.boxplot(data, patch_artist=True, showfliers=False, tick_labels=labs, medianprops=dict(color=INK, lw=1.5))
            for patch, c in zip(bp["boxes"], cols):
                patch.set_facecolor(c); patch.set_edgecolor(INK2)
            ax.set_title(f"{TLAB[t]} fake viruses"); ax.tick_params(axis="x", rotation=30, labelsize=8)
        axes[0][0].set_ylabel("seconds spent waiting for a CPU, per second of run")
        fig.suptitle("Fig 10. Wait time by policy (from /proc schedstat): the mechanism behind any policy effect", **TOP)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save(fig, "fig10_wait_time_by_policy.png", dst)

    def fig10b():
        sub = Mm[(Mm.program == "cpu_steady") & (Mm.level == "high")]
        if sub.empty:
            raise ValueError("no cpu_steady high runs")
        fig, ax = plt.subplots(figsize=(6.5, 3.8))
        for i, p in enumerate(pols):
            x_ = sub[sub.policy == p]["cpu_pct"].to_numpy()
            if len(x_) == 0:
                continue
            m, lo, hi = boot_ci(x_)
            ax.bar(i, m, color=POL_COL[p], width=0.65)
            ax.errorbar(i, m, yerr=[[m - lo], [hi - m]], color=INK2, capsize=3, lw=1)
        ax.set_xticks(range(len(pols))); ax.set_xticklabels(pols, rotation=25, ha="right")
        ax.set_ylabel("CPU the virus really got (% of one core)")
        ax.set_title("Fig 10b. Extra: how much CPU each policy gave the 3-copy CPU virus")
        save(fig, "fig10b_cpu_share_by_policy.png", dst)

    # 11. order demo timeline (from demo_latency.py)
    def fig11():
        tp = os.path.join(out, "demo_timeline.csv")
        if not os.path.exists(tp):
            raise FileNotFoundError("run: sudo python3 demo_latency.py")
        T = pd.read_csv(tp)
        pl = [p for p in config.POLICIES if p in set(T.policy)]
        col = {"hog1": "#2a78d6", "hog2": "#1baf7a", "interactive": "#eb6834"}
        fig, axes = plt.subplots(len(pl), 1, figsize=(10, 1.35 * len(pl) + 1), sharex=True, squeeze=False)
        for ax, p in zip(axes[:, 0], pl):
            for lane, task in enumerate(["hog1", "hog2", "interactive"]):
                sub = T[(T.policy == p) & (T.task == task)]
                ax.broken_barh([(r.start_ms, r.end_ms - r.start_ms) for r in sub.itertuples()], (lane - 0.4, 0.8), facecolors=col[task])
            ax.set_yticks([0, 1, 2]); ax.set_yticklabels(["hog 1", "hog 2", "interactive"], fontsize=7)
            ax.set_ylabel(p, rotation=0, ha="right", va="center", fontsize=9, fontweight="bold"); ax.grid(False)
        axes[-1, 0].set_xlabel("milliseconds (400 ms slice, ONE core)")
        fig.suptitle("Fig 11. Order demo: who ran when on one core (coloured block = that task on the CPU)", **TOP)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        save(fig, "fig11_order_demo_timeline.png", dst)

    def fig11b():
        dp = os.path.join(out, "demo.csv")
        D = pd.read_csv(dp)
        pl = [p for p in config.POLICIES if p in set(D.policy)]
        fig, ax = plt.subplots(figsize=(8, 4))
        bp = ax.boxplot([D[D.policy == p]["latency_ms"].to_numpy() for p in pl], patch_artist=True, showfliers=False,
                        tick_labels=pl, medianprops=dict(color=INK, lw=1.5))
        for patch, p in zip(bp["boxes"], pl):
            patch.set_facecolor(POL_COL[p]); patch.set_edgecolor(INK2)
        ax.set_ylabel("how late the interactive task woke up (ms)")
        ax.set_title("Fig 11b. Extra: wake-up delay of the interactive task (lower = favoured)")
        save(fig, "fig11b_demo_wakeup_delay.png", dst)

    # ---- extras (not in your list, kept because they answer follow-up questions) ----
    def extra_heatmap():
        vprogs = [config.program_name(t, k) for t in TYPES for (k, isvv) in config.KINDS if isvv]
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.4), constrained_layout=True)
        cm = matplotlib.colors.LinearSegmentedColormap.from_list("blu", ["#dbe8f8", "#2a78d6", "#12386e"])
        for ax, d in zip(axes, show):
            Mx = np.full((len(vprogs), len(pols)), np.nan)
            for i, pr in enumerate(vprogs):
                for j, p in enumerate(pols):
                    x_ = vir[(vir.detector == d) & (vir.program == pr) & (vir.policy == p)]["ttd"]
                    if len(x_):
                        Mx[i, j] = np.median(x_)
            im = ax.imshow(Mx, cmap=cm, vmin=0, vmax=secs, aspect="auto"); ax.grid(False)
            ax.set_xticks(range(len(pols))); ax.set_xticklabels(pols, rotation=25, ha="right")
            ax.set_yticks(range(len(vprogs))); ax.set_yticklabels(vprogs if ax is axes[0] else [])
            for i in range(Mx.shape[0]):
                for j in range(Mx.shape[1]):
                    if np.isfinite(Mx[i, j]):
                        ax.text(j, i, f"{Mx[i, j]:.0f}", ha="center", va="center", fontsize=9, color="white" if Mx[i, j] > secs * 0.45 else INK)
            ax.set_title(DET_LAB[d])
        fig.colorbar(im, ax=axes, label="median seconds to alarm (dark = slow / missed)", shrink=0.85)
        fig.suptitle("Extra A. Median time to detect, each fake virus under each policy", **TOP)
        save(fig, "extraA_heatmap_virus_by_policy.png", dst)

    def extra_quality():
        fig, ax = plt.subplots(figsize=(10, 4.2))
        for j, d in enumerate(show):
            for i, p in enumerate(pols):
                m, lo, hi = boot_metric(d, pol == p, fa_at)
                x = i + (j - 0.5) * 0.38
                reached = m == m
                val = m if reached else 1.0
                ax.bar(x, val, 0.38 * 0.92, color=DET_COL[d], hatch=None if reached else "///", edgecolor=SURF if reached else INK2,
                       label=DET_LAB[d] if i == 0 else None)
                if reached and lo == lo:
                    ax.errorbar(x, val, yerr=[[max(val - lo, 0)], [max(hi - val, 0)]], color=INK2, capsize=3, lw=1)
                ax.text(x, min(val + 0.03, 1.05), f"{val:.0%}" if reached else "n/r", ha="center", fontsize=8)
        ax.set_xticks(range(len(pols))); ax.set_xticklabels(pols); ax.set_ylim(0, 1.15)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.set_ylabel("false alarms at 95% detection")
        ax.set_title("Extra B. Does the policy change how WELL each detector separates virus from harmless? (lower = better; n/r = 95% never reached)")
        ax.legend(loc="upper right")
        save(fig, "extraB_detector_quality_by_policy.png", dst)

    def extra_fa95():
        fig, ax = plt.subplots(figsize=(10, 4.3))
        for j, d in enumerate(dets):
            for i, t in enumerate(TYPES):
                m, lo, hi = boot_metric(d, typ == t, fa_at)
                x = i + (j - 1.5) * 0.2
                reached = m == m
                val = m if reached else 1.0
                ax.bar(x, val, 0.2 * 0.92, color=DET_COL[d], hatch=None if reached else "///", edgecolor=SURF if reached else INK2,
                       label=DET_LAB[d] if i == 0 else None)
                if reached and lo == lo:
                    ax.errorbar(x, val, yerr=[[max(val - lo, 0)], [max(hi - val, 0)]], color=INK2, capsize=2, lw=1)
                ax.text(x, min(val + 0.03, 1.05), f"{val:.0%}" if reached else "n/r", ha="center", fontsize=8)
        ax.set_xticks(range(len(TYPES))); ax.set_xticklabels([TLAB[t] for t in TYPES]); ax.set_ylim(0, 1.15)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.set_ylabel("harmless programs wrongly flagged")
        ax.set_title("Extra C. False alarms when we insist on catching 95% of fake viruses (n/r = 95% never reached)")
        ax.legend(loc="upper right", fontsize=8, ncol=2)
        save(fig, "extraC_false_alarms_at_95pct.png", dst)

    for f in [fig01, fig02, fig03, fig04, fig05, fig06, fig07, fig08, fig09, fig10, fig10b, fig11, fig11b,
              extra_heatmap, extra_quality, extra_fa95]:
        safe(f)
    print("\nDone. Tables are in", dst, "and graphs in", os.path.join(dst, "figures"))


if __name__ == "__main__":
    main()
