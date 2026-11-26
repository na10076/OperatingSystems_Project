# Does the scheduling policy change how fast a virus is detected?
Applied OS project - 5 policies x 2 detectors x 3 fake-virus types.
Everything here is **harmless**: the "viruses" only burn CPU, fill their own (capped) memory, or write into one
small rotating file (max 64 MB) inside the run's own sandbox folder. Every program stops by itself after 60 seconds
and the runner also kills only the process group it started.

## What is in this folder
| File | What it is |
|---|---|
| `src/*.c` | the 3 test programs (cpu, memory, disk). Each acts as 2 fake viruses + 2 harmless look-alikes |
| `run_experiment.py` | runs the whole experiment and records one log per run |
| `policy.py` | switches between the 5 scheduling policies and checks which one is really active |
| `detect.py` | the two detectors (snapshot and running total), built from published methods and library code - see "Published code and methods" |
| `analyze.py` | makes all tables and graphs from the logs |
| `policy_tests.py` | extra scheduler tests: each virus type separately, and every pair of the 5 schedulers (10 pairs, Holm-corrected) |
| `demo_latency.py` | optional 2-minute one-core demo (Fig 11): which policy lets an interactive task run first |
| `live_demo.py` | shows a detector catching a fake virus and stopping it (for the viva) |
| `check_env.py` | tells you in plain words if your computer is ready |
| `config.py` | all the numbers (run length, alarm margin ...) in one place |

## The four programs per type (what "program" and "intensity" mean)
For each of CPU, memory, disk there are 4 programs and each runs at `low` and `high` intensity:
- **steady** (fake virus): works non-stop.  **bursty** (fake virus): works in pulses, harder to notice.
  Both fake viruses also act like real malware (harmlessly): they **disguise their name** as a Linux system worker
  (`kworker/u4:2`), **drop a hidden copy of themselves** in the sandbox folder, and the CPU virus **copies itself**
  (high intensity = 3 copies, a fixed maximum, no loops). The logger adds up the program AND all its copies.
- **batch** (harmless look-alike): a big job for a few seconds, then rests - looks scary in a snapshot.
- **light** (harmless look-alike): quiet steady work.
3 types x 4 programs x 2 intensities = **24 runs = one block**.

## Our setup (what the results in `results/` were produced on)
| Item | Value |
|---|---|
| Host laptop | Intel Core i7-1355U (2 performance + 8 efficiency cores, 12 threads), 16 GB RAM, Windows 11 |
| Virtual machine | VirtualBox `<version>`; 4 vCPUs, 6144 MB RAM, 50 GB disk, EFI on, VMSVGA graphics (3D off), NAT |
| Guest OS / kernel | CachyOS, kernel `7.3.5-2-cachyos-eevdf` (package `linux-cachyos-eevdf` 7.3.5-2) |
| Schedulers | EEVDF (built into the kernel); scx_bpfland, scx_flash, scx_lavd 1.1.4 (package `scx-scheds` 1.1.4-2); scx_simple built from the Linux 7.3.5 source (`tools/sched_ext`) |
| Scheduler settings | every scheduler started with **no options** (its defaults) |
| Python | 3.14 with pandas, NumPy, SciPy, scikit-learn, matplotlib |

## Reproduce the analysis only (no experiment needed, about 2 minutes)
All recordings are included in `results/logs/` (unzip `results/logs.zip` first if the logs are zipped). Then:
```
python3 analyze.py            # -> results/analysis_split50/ (summary.txt, tables, figures/)
python3 policy_tests.py       # -> results/analysis_split50/policy_tests.txt and policy_pairs.csv
```
This needs only Python 3 with pandas, numpy, scipy, scikit-learn and matplotlib (any Linux, macOS or Windows).

## Run the whole experiment from zero
### A. Make a Linux machine that can load sched_ext schedulers
WSL2 on Windows does **not** work (its kernel has `CONFIG_SCHED_CLASS_EXT` switched off). We used a VirtualBox VM:
1. Install VirtualBox. Create a VM: type Linux / Arch Linux (64-bit), 4 CPUs, 6-8 GB RAM, 50 GB disk, **EFI on**,
   graphics VMSVGA, 3D acceleration **off**.
2. Install CachyOS (Desktop edition ISO) into it: Erase disk, ext4, defaults otherwise. Remove the ISO afterwards
   (Settings -> Storage -> optical drive -> Remove disk).
3. **Do not install `virtualbox-guest-utils`** - on our VM it stopped the desktop from starting.

### B. Install the tools and the EEVDF kernel (CachyOS)
```
sudo pacman -S --needed scx-scheds scx-tools tmux base-devel clang llvm libelf python-pandas python-numpy python-matplotlib python-scipy python-scikit-learn linux-cachyos-eevdf linux-cachyos-eevdf-headers
sudo reboot
```
At the boot menu choose the **`linux-cachyos-eevdf`** entry (CachyOS's default kernel uses the BORE scheduler,
not EEVDF). If pacman asks to replace `zlib-ng-compat` with `zlib`, answer **N**. Check:
```
uname -r                                        # must end in -eevdf
zcat /proc/config.gz | grep SCHED_CLASS_EXT     # CONFIG_SCHED_CLASS_EXT=y
cat /sys/kernel/sched_ext/state                 # disabled
```

### C. Build scx_simple (it is not in the scx-scheds package)
```
mkdir -p ~/src && cd ~/src
curl -fLO https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.3.5.tar.xz
tar xf linux-7.3.5.tar.xz && cd linux-7.3.5
make -j4 -C tools/sched_ext scx_simple
sudo cp tools/sched_ext/build/bin/scx_simple /usr/local/bin/
sudo scx_simple          # prints "local=... global=..." each second; stop with Ctrl+C
```
(Use the kernel source that matches your `uname -r` version.)

### D. Build the test programs and check everything
```
cd os-sched-detect
./setup.sh
sudo python3 check_env.py --try-sched     # every line OK, all 5 policies load, "All good!"
```

### E. Pilot (about 25 minutes)
```
sudo python3 run_experiment.py --pilot --out pilot
python3 analyze.py --out pilot
```
If every detector catches 0% or 100%, the programs are too weak or too strong: change the numbers in `src/*.c`,
rebuild with `make`, run the pilot again. (Pilot runs last 20 s, so the 30 s running total cannot judge in the pilot.)

### F. Full run (650 runs, about 12 hours; run it overnight)
```
tmux new -s exp
sudo python3 run_experiment.py --repeats 5
```
Laptop plugged in, sleep off, lid open, nothing else running. Detach with Ctrl+B then D; come back with
`tmux attach -t exp`. If it stops, run the **same** command again: finished runs are skipped.
(We ran `--repeats 3` first and then `--repeats 5`, which adds only rounds 4-5.)

### G. Graphs, demo and live demo
```
sudo python3 demo_latency.py          # one-core "who ran when" demo (Fig 11), about 2 minutes
python3 analyze.py                    # final results -> results/analysis_split50/
python3 policy_tests.py               # scheduler pair tests (reads analyze.py's output)
python3 analyze.py --calib lookalike  # optional: the older line rule, for comparison
python3 live_demo.py --program cpu_steady --level high --detector run10   # detector catches and stops a fake virus
```

## The 11 graphs (all computed from the CSV logs - nothing typed in by hand)
| # | Graph | Question it answers |
|---|---|---|
| 1 | Time to detect by policy and detector (grouped bars, error bars, panel per virus type, steady vs bursty) | Does the policy change detection time? Which detector is faster? |
| 2 | Detection rate and false-alarm rate, per detector per policy | Which detector is better? |
| 3 | Dot picture (each dot = one run's peak reading, snapshot next to running total, alarm line drawn) | Why the running total helps or doesn't (real-data thief-and-jogger slide) |
| 4 | ROC curves (one line per detector, per virus type, AUC in legend) | Which detector separates better without depending on one line |
| 5 | Policy effect heatmap (policy x virus type, change in time vs EEVDF, blank if within the noise) | Where a policy really made a difference |
| 6 | Catch curve (% of virus runs already alarmed over time; per detector and per policy) | The most intuitive picture of time to detect |
| 7 | Result by intensity (low vs high) | Where each detector breaks; are low-intensity viruses missed? |
| 8 | Window length (running total 5/10/30 s: time to detect against false alarms) | What extra steadiness costs in delay |
| 9 | One-run example (a harmless batch job vs a bursty CPU virus, both detectors, alarm line) | A great presentation slide |
| 10 | Wait time by policy (box plot from /proc schedstat) | The mechanism behind any policy effect ("explain why") |
| 11 | Order demo (timeline of who ran when on one core, from `demo_latency.py`) | Shows sir how the policies really differ |
Extras made as well: 10b (CPU share by policy), 11b (wake-up delay boxes), A (virus x policy heatmap),
B (detector quality by policy), C (false alarms at 95% detection per virus type).
Note: our harmless look-alike for fig 9 is a "batch job" (busy for 2 s, then rests), which plays the role of the compile.

## How a run works (so you can explain it)
- The **logger** reads the program's numbers (CPU, memory, bytes written, time spent waiting for a CPU) every 0.5 s.
  It sits alone on the last CPU core; the programs and 3 background "hog" programs share the other cores,
  so there is real competition for the CPU - that is where the policy makes a difference.
- **Detectors are not part of the run.** They read the saved log afterwards, so both see exactly the same data.
  - *Snapshot*: alarm if the latest 0.5 s reading is over the alarm line.
  - *Running total*: alarm if the average over the last 5 / 10 / 30 s is over the line.
- **Alarm lines (project plan, default `--calib split50`):** the runs are split 50/50, stratified so every
  policy x program x intensity appears in both halves (the split is saved in `split.csv`). On the calibration half,
  each line is set so it catches 95% of that half's viruses of its own type (CPU line from CPU viruses, memory line
  from memory viruses, disk line from disk viruses). The lines are then frozen and all results come from the test half.
  `--calib lookalike` is the older rule (EEVDF calibration round, line 10% above the loudest harmless program).
- **Time to detect** = seconds from program start to the first alarm, reported three ways: median when caught (with the detection rate),
  time until half the viruses are caught (catch-curve median, Kaplan & Meier 1958), and restricted mean within 60 s where a miss
  counts as 60 s (Royston & Parmar 2013).
- Order is random: rounds, policy order and run order are shuffled; the first run after each policy switch is a
  discarded warm-up. The scheduler's own output is saved in `results/sched_logs/`.

## Honest limits (put these in the report)
- It runs in a virtual machine on one laptop whose chip may slow itself down when hot: small timing wobble.
- The look-alike and virus behaviours are our own designs; results apply to these programs, not all malware.
- The EEVDF baseline is CachyOS's `linux-cachyos-eevdf` kernel: EEVDF plus CachyOS's own patches, not an unmodified kernel.
- Two harmless look-alikes per virus type (the plan's 600-run option), written by us to imitate a compile/backup ("batch")
  and light background work ("light"), not real software.
- One fixed background load (3 CPU-bound hogs); no memory or disk competition.
- Our disk "virus" writes more slowly (8-30 MB/s) than our harmless backup imitation (40-80 MB/s in bursts), so disk
  detection by write volume alone is a hard case.
- Schedulers were run with default settings only.
- bpfland / flash / lavd behaviour was checked against their v1.1.4 source code (their READMEs can be older than the code;
  e.g. the bpfland README still describes a separate interactive queue that v1.1.4 no longer has).
- Disk test writes about 25-30 GB in total over the full experiment.

## Published code and methods used (cite these)
**No detector logic is invented by us.** Each part is a published method run through published library code:

| Part | What it is | Published source |
|---|---|---|
| Snapshot detector | fixed limit on the latest reading only (Shewhart-style control-chart rule; same as a Prometheus alert on an instant rate) | Shewhart (1931); Prometheus "Alerting rules" docs |
| Running-total detector | the same fixed limit on the average over a sliding 5/10/30 s window (Prometheus `avg_over_time(...[10s]) > line` / `rate(...[10s]) > line`) | Prometheus docs; window computed with pandas `rolling("10s")` (McKinney, 2010) |
| Raw readings | `/proc/<pid>/stat`, `statm`, `io`, `schedstat` | Linux kernel docs: proc(5), Documentation/scheduler/sched-stats.rst |
| Alarm lines (95% rule) | percentile of the practice-half virus readings | NumPy `quantile` (Harris et al., 2020) |
| ROC curves, AUC, false alarms at 95% detection | `sklearn.metrics.roc_curve`, `auc` | Pedregosa et al. (2011); Fawcett (2006); Hanley & McNeil (1982) |
| 95% ranges and tests | `scipy.stats.bootstrap`, `binomtest(...).proportion_ci(method="wilson")`, `wilcoxon`, `kruskal` | Virtanen et al. (2020); Efron (1979); Wilson (1927); Wilcoxon (1945); Kruskal & Wallis (1952) |
| Time to detect | catch curve; restricted mean within 60 s | Kaplan & Meier (1958); Royston & Parmar (2013) |
| Graphs | matplotlib | Hunter (2007) |
| Schedulers | EEVDF (Linux), scx_simple / scx_bpfland / scx_flash / scx_lavd (sched-ext/scx project) | Stoica & Abdel-Wahab (1995); scx repository at the installed version |

Harvard references (DOIs checked):
- Hunter, J.D. (2007) 'Matplotlib: a 2D graphics environment', *Computing in Science & Engineering*, 9(3), pp. 90-95. doi:10.1109/MCSE.2007.55
- McKinney, W. (2010) 'Data structures for statistical computing in Python', *Proceedings of the 9th Python in Science Conference*, pp. 56-61. doi:10.25080/Majora-92bf1922-00a
- Kaplan, E.L. and Meier, P. (1958) 'Nonparametric estimation from incomplete observations', *Journal of the American Statistical Association*, 53(282), pp. 457-481. doi:10.1080/01621459.1958.10501452
- Efron, B. (1979) 'Bootstrap methods: another look at the jackknife', *The Annals of Statistics*, 7(1), pp. 1-26. doi:10.1214/aos/1176344552
- Fawcett, T. (2006) 'An introduction to ROC analysis', *Pattern Recognition Letters*, 27(8), pp. 861-874. doi:10.1016/j.patrec.2005.10.010
- Hanley, J.A. and McNeil, B.J. (1982) 'The meaning and use of the area under a receiver operating characteristic (ROC) curve', *Radiology*, 143(1), pp. 29-36. doi:10.1148/radiology.143.1.7063747
- Harris, C.R. et al. (2020) 'Array programming with NumPy', *Nature*, 585(7825), pp. 357-362. doi:10.1038/s41586-020-2649-2
- Kruskal, W.H. and Wallis, W.A. (1952) 'Use of ranks in one-criterion variance analysis', *Journal of the American Statistical Association*, 47(260), pp. 583-621. Available at: https://www.jstor.org/stable/2280779
- Wilcoxon, F. (1945) 'Individual comparisons by ranking methods', *Biometrics Bulletin*, 1(6), pp. 80-83.
- Pedregosa, F. et al. (2011) 'Scikit-learn: machine learning in Python', *Journal of Machine Learning Research*, 12, pp. 2825-2830. (no DOI; https://jmlr.org/papers/v12/pedregosa11a.html)
- Prometheus Authors (n.d.) *Alerting rules*. Available at: https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- Virtanen, P. et al. (2020) 'SciPy 1.0: fundamental algorithms for scientific computing in Python', *Nature Methods*, 17(3), pp. 261-272. doi:10.1038/s41592-019-0686-2
- Wilson, E.B. (1927) 'Probable inference, the law of succession, and statistical inference', *Journal of the American Statistical Association*, 22(158), pp. 209-212. doi:10.1080/01621459.1927.10502953
- Royston, P. and Parmar, M.K.B. (2013) 'Restricted mean survival time: an alternative to the hazard ratio for the design and analysis of randomized trials with a time-to-event outcome', *BMC Medical Research Methodology*, 13, 152. doi:10.1186/1471-2288-13-152
- Shewhart (1931) is a book with no DOI: Shewhart, W.A. (1931) *Economic control of quality of manufactured product*. New York: D. Van Nostrand.

## AI use
Parts of the code and documentation were written with help from an AI assistant (Claude); the group checked,
ran and is responsible for all of it.
