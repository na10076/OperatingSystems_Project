"""Switch between the five scheduling policies and prove which one is active."""
import os, shutil, signal, subprocess, time

SYSFS = os.environ.get("SCX_SYSFS", "/sys/kernel/sched_ext")


class PolicyError(RuntimeError):
    pass


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def state():
    """'enabled' while an scx scheduler is running, 'disabled' otherwise ('' = no sched_ext)."""
    return _read(os.path.join(SYSFS, "state"))


def ops_name():
    """Name of the active scx scheduler (empty when running plain Linux EEVDF)."""
    return _read(os.path.join(SYSFS, "root", "ops"))


def supported():
    return os.path.isdir(SYSFS)


def _wait_state(want, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if state() == want:
            return True
        time.sleep(0.2)
    return state() == want


def start(name, logpath, timeout=20):
    """Make `name` the active policy.  Returns the scheduler Popen (None for eevdf)."""
    if name == "eevdf":
        if supported() and state() == "enabled":
            raise PolicyError("An scx scheduler is still running; stop it first.")
        return None
    if not supported():
        raise PolicyError("This kernel has no sched_ext (%s missing). See README, step 'Check your system'." % SYSFS)
    exe = shutil.which(name)
    if not exe:
        raise PolicyError(f"Program '{name}' not found. Install the scx package (CachyOS: sudo pacman -S scx-scheds).")
    log = open(logpath, "wb")
    p = subprocess.Popen([exe], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    end = time.time() + timeout
    while time.time() < end:
        if p.poll() is not None:
            raise PolicyError(f"{name} exited right away (code {p.returncode}). See {logpath}")
        if state() == "enabled":
            return p
        time.sleep(0.2)
    stop(p)
    raise PolicyError(f"{name} did not become active within {timeout}s. See {logpath}")


def stop(p, timeout=15):
    """Stop the running scx scheduler; Linux falls back to EEVDF by itself."""
    if p is None:
        return
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
    if supported() and not _wait_state("disabled", timeout):
        raise PolicyError("sched_ext did not return to 'disabled' after stopping the scheduler.")


def is_ok(name, p):
    """True if the policy we think is active really is active right now."""
    if name == "eevdf":
        return (not supported()) or state() == "disabled"
    return p is not None and p.poll() is None and state() == "enabled"


def version_of(name):
    exe = shutil.which(name) if name != "eevdf" else None
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return ""
