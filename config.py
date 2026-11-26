"""Settings in one place.  Change numbers here, not in the other files."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "bin")

# The five policies (managers) we compare.  "eevdf" = Linux's normal built-in one.
POLICIES = ["eevdf", "scx_simple", "scx_bpfland", "scx_flash", "scx_lavd"]

# 3 types x 4 programs x 2 levels = 24 runs in one "block".
TYPES = ["cpu", "mem", "io"]
# (kind, is_virus).  steady+bursty = fake viruses; batch+light = harmless look-alikes.
KINDS = [("steady", True), ("bursty", True), ("batch", False), ("light", False)]
LEVELS = ["low", "high"]

SECS = 60            # how long every program runs
SAMPLE_EVERY = 0.5   # logger takes a reading this often (seconds)
PRE_SECS = 3         # background load runs alone this long before the program starts
POST_SECS = 2        # rest after each run
BURNERS = None       # background hogs; None = one per work core

# Detectors: "snapshot" looks at the latest 0.5 s reading.
# "runN" looks at the average over the last N seconds ("running total").
DETECTORS = {"snapshot": 0, "run5": 5, "run10": 10, "run30": 30}
LINE_MARGIN = 1.10   # alarm line = 10% above the highest reading any look-alike produced
MIN_LINES = {"cpu": 20.0, "mem": 50.0, "io": 1.0}   # floors so a line is never ~0
MIN_WINDOW_S = 2.0   # running total only starts judging after this many seconds

def program_name(typ, kind):
    return f"{typ}_{kind}"
