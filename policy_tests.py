#!/usr/bin/env python3
"""Extra scheduler comparisons, run AFTER analyze.py (it only reads analyze.py's output files).

  python3 policy_tests.py                     # reads results/analysis_split50/
  python3 policy_tests.py --dir <folder>      # any other analysis folder

What it does (test half only, fake viruses only, a missed virus counts as 60 s, as in analyze.py):
  1. Kruskal-Wallis test across all five policies (Kruskal & Wallis, 1952), first with all virus types
     pooled, then separately for CPU, memory and disk viruses.
  2. Every scheduler against every other scheduler (5 policies -> 10 pairs) for CPU viruses, with a
     two-sided Mann-Whitney U test and Holm's correction for making 10 comparisons (Holm, 1979).
All tests come from SciPy (Virtanen et al., 2020). Writes policy_tests.txt and policy_pairs.csv.
"""
import argparse
import itertools
import os

import numpy as np
import pandas as pd
from scipy import stats

POLICIES = ["eevdf", "scx_simple", "scx_bpfland", "scx_flash", "scx_lavd"]
DETECTORS = ["snapshot", "run10"]
TYPES = ["cpu", "mem", "io"]


def holm(pvals):
    """Holm (1979) step-down correction for several comparisons."""
    p = np.asarray(pvals, float)
    order = np.argsort(p)
    out = np.empty_like(p)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(p) - rank) * p[i]))
        out[i] = running
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join("results", "analysis_split50"))
    ap.add_argument("--secs", type=float, default=60.0)
    a = ap.parse_args()

    alarms = pd.read_csv(os.path.join(a.dir, "alarms.csv"))
    split = pd.read_csv(os.path.join(a.dir, "split.csv"))[["run_id", "half"]]
    v = alarms.merge(split, on="run_id")
    v = v[(v.half == "test") & (v.is_virus == 1)].copy()
    v["ttd"] = v["ttd"].fillna(a.secs)          # a miss counts as the full run (restricted mean)

    out = ["Scheduler comparisons (test half, fake viruses; a miss counts as %.0f s)" % a.secs, ""]
    out.append("1. Kruskal-Wallis across all five policies")
    n_type_tests = 0
    for d in DETECTORS:
        dd = v[v.detector == d]
        groups = [dd[dd.policy == p].ttd.to_numpy() for p in POLICIES]
        out.append(f"  {d:8s} all types pooled: p = {stats.kruskal(*groups).pvalue:.3f}  (runs per policy: {[len(g) for g in groups]})")
        for t in TYPES:
            dt = dd[dd.type == t]
            groups = [dt[dt.policy == p].ttd.to_numpy() for p in POLICIES]
            means = ", ".join(f"{p} {g.mean():.1f} s" for p, g in zip(POLICIES, groups))
            try:
                pv = stats.kruskal(*groups).pvalue
            except ValueError:              # all values identical
                pv = 1.0
            n_type_tests += 1
            out.append(f"  {d:8s} {t:3s} viruses only: p = {pv:.3f}  mean time to detect: {means}")
    out.append(f"  ({n_type_tests} per-type tests were made; with a Bonferroni correction each p must be below "
               f"{0.05 / n_type_tests:.4f} to count as significant.)")
    out.append("")

    out.append("2. Every pair of policies, CPU viruses (Mann-Whitney U, Holm-corrected for 10 pairs)")
    rows = []
    for d in DETECTORS:
        dc = v[(v.detector == d) & (v.type == "cpu")]
        pairs = []
        for x, y in itertools.combinations(POLICIES, 2):
            gx, gy = dc[dc.policy == x].ttd, dc[dc.policy == y].ttd
            p = stats.mannwhitneyu(gx, gy, alternative="two-sided").pvalue
            pairs.append(dict(detector=d, policy_a=x, policy_b=y, n_a=len(gx), n_b=len(gy),
                              mean_a_s=round(gx.mean(), 2), mean_b_s=round(gy.mean(), 2),
                              diff_a_minus_b_s=round(gx.mean() - gy.mean(), 2), p=p))
        adj = holm([r["p"] for r in pairs])
        for r, h in zip(pairs, adj):
            r["p"] = round(r["p"], 4)
            r["p_holm"] = round(float(h), 4)
            rows.append(r)
            out.append(f"  {d:8s} {r['policy_a']:11s} vs {r['policy_b']:11s}: difference {r['diff_a_minus_b_s']:6.1f} s, "
                       f"p = {r['p']:.3f}, Holm-corrected p = {r['p_holm']:.3f}")
    pd.DataFrame(rows).to_csv(os.path.join(a.dir, "policy_pairs.csv"), index=False)
    out.append("")
    out.append("Note: runs are treated as independent. The 50/50 split was stratified by policy x program x strength, so the")
    out.append("test-half rounds differ between policies and the runs cannot be matched by round for a blocked test.")
    with open(os.path.join(a.dir, "policy_tests.txt"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))
    print(f"\nWritten: {os.path.join(a.dir, 'policy_tests.txt')} and policy_pairs.csv")


if __name__ == "__main__":
    main()
