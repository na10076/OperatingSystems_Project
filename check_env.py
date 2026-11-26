#!/usr/bin/env python3
"""Checks that this computer is ready for the project and says what to fix, in plain words."""
import os, platform, shutil, subprocess, sys, gzip, time

import config, policy

problems = 0

def say(ok, text, fix=""):
    global problems
    print(("  OK       " if ok else "  PROBLEM  ") + text)
    if not ok:
        problems += 1
        if fix:
            print("           -> " + fix)

print("Linux version:", platform.release())
major, minor = [int(x) for x in platform.release().split(".")[:2]]
say((major, minor) >= (6, 12), "Linux is new enough (needs 6.12 or newer)", "Use a newer kernel (see README).")

cfg = {}
for path in ("/proc/config.gz",):
    if os.path.exists(path):
        with gzip.open(path, "rt") as f:
            for line in f:
                if line.startswith("CONFIG_"):
                    k, _, v = line.strip().partition("=")
                    cfg[k] = v
        break
else:
    p = f"/boot/config-{platform.release()}"
    if os.path.exists(p):
        for line in open(p):
            if line.startswith("CONFIG_"):
                k, _, v = line.strip().partition("=")
                cfg[k] = v
if cfg:
    for key, why in [("CONFIG_SCHED_CLASS_EXT", "the plug-in feature (sched_ext) is switched on"),
                     ("CONFIG_BPF_SYSCALL", "BPF is switched on"),
                     ("CONFIG_DEBUG_INFO_BTF", "BTF info is available")]:
        say(cfg.get(key) in ("y", "m"), why, "This Linux build lacks it. Use a kernel with sched_ext (CachyOS has one).")
else:
    say(False, "could not read the kernel settings file", "Skip this check, the scheduler test below is what matters.")
say(policy.supported(), "sched_ext is present at " + policy.SYSFS, "Your kernel cannot load the scx policies.")

for exe in ["gcc", "make", "taskset", "tmux"]:
    say(shutil.which(exe) is not None, f"'{exe}' is installed", f"Install it (CachyOS: sudo pacman -S {'base-devel' if exe in ('gcc','make') else exe if exe!='taskset' else 'util-linux'}).")
for mod in ["pandas", "numpy", "matplotlib", "scipy", "sklearn"]:
    try:
        __import__(mod); ok = True
    except ImportError:
        ok = False
    say(ok, f"Python package '{mod}'", f"CachyOS: sudo pacman -S python-{'scikit-learn' if mod == 'sklearn' else mod}   (Ubuntu: sudo apt install python3-{mod})")
say(os.path.exists(os.path.join(config.BIN, "cpu_prog")), "test programs are built", "Run ./setup.sh")

mem_kb = int([l for l in open("/proc/meminfo") if l.startswith("MemAvailable")][0].split()[1])
say(mem_kb > 3_000_000, f"free memory is enough ({mem_kb/1e6:.1f} GB)", "Give the VM more memory (8 GB recommended).")
print("CPU cores:", os.cpu_count(), "(4 recommended: 3 for programs, 1 for the logger)")
say((os.cpu_count() or 1) >= 2, "at least 2 cores", "Give the VM more CPUs.")

if "--try-sched" in sys.argv:
    if os.geteuid() != 0:
        print("\nRun with sudo to test the schedulers:  sudo python3 check_env.py --try-sched")
    else:
        print("\nTrying each policy for a few seconds...")
        os.makedirs("results/sched_logs", exist_ok=True)
        for name in config.POLICIES:
            try:
                p = policy.start(name, f"results/sched_logs/check_{name}.txt")
                time.sleep(3)
                say(policy.is_ok(name, p), f"{name} loads and keeps running (active: {policy.ops_name() or 'EEVDF'}) {policy.version_of(name)}")
                policy.stop(p)
            except policy.PolicyError as err:
                say(False, f"{name}: {err}")
else:
    print("\n(To also test loading each scheduler: sudo python3 check_env.py --try-sched)")
print("\nAll good!" if not problems else f"\n{problems} thing(s) to fix before running.")
