"""
runner -- drive the SCAPS GUI through the generated scripts, resumably.

    scapsml run      project.xlsx               everything outstanding
    scapsml run      project.xlsx 0.25 0.29     named compositions
    scapsml run      project.xlsx --next 3      the next three outstanding
    scapsml status   project.xlsx               progress, no SCAPS needed
    scapsml calibrate project.xlsx              record button positions

SCAPS has no command-line batch mode, so this clicks through its GUI. That is
fragile in one known way -- button positions depend on screen resolution and
scaling -- and the workbook therefore holds them (project!btn_*), with
`scapsml calibrate` to record them for a new machine.

Dialogs are dismissed with Win32 messages sent to their OK buttons rather than
blind clicks or Enter keystrokes, so a stray keypress can never land in the
script editor. Only windows that look like dialogs are touched; SCAPS's own
panels are never dismissed.

RESUMING. Each composition is an independent script writing its own .iv
files. A composition whose files all exist is skipped, so a plain `run`
resumes rather than restarting, and Ctrl-C is safe. A header-only .iv -- SCAPS
rejecting the problem before solving -- counts as DONE: rerunning cannot change
it, and treating it as outstanding would loop forever.

The GUI libraries are imported lazily, so `status` works on any machine.
"""

from __future__ import annotations

import csv
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from ._io import read_rows, read_json, write_json

log = logging.getLogger("scapsml")

HEADER_ONLY_BYTES = 400
DEFAULTS = {
    "scaps_dir": r"C:\Program Files (x86)\Scaps3312",
    "scaps_exe": "scaps3312.exe",
    "main_title": "SCAPS 3.3.12 Action Panel",
    "btn_script_setup": "687,968",
    "btn_execute_script": "429,975",
    "btn_editor_load": "1273,335",
    "btn_editor_ok": "1282,506",
    "script_timeout": 14400,
    "stall_limit": 900,
    "launch_wait": 8,
}
PANEL_TITLES = ("action panel", "script editor", "energy band", "i-v panel",
                "iv panel", "qe panel", "c-v panel", "c-f panel", "ac panel",
                "generation", "recombination", "script results", "recorder",
                "curve fit", "band diagram", "scaps info")
DIALOG_TITLES = ("error", "warning", "convergence", "while calculating",
                 "graph scaling", "not recognised", "not recognized", "confirm",
                 "information", "attention", "message", "abort", "failed")
OK_LABELS = ("ok", "&ok", "yes", "&yes", "continue", "close", "abort", "retry")
BM_CLICK = 0x00F5


# --------------------------------------------------------------------------
# configuration and bookkeeping (no GUI)
# --------------------------------------------------------------------------
class Settings:
    def __init__(self, project):
        g = lambda k: project.setting(k, DEFAULTS[k])
        self.scaps_dir = Path(str(g("scaps_dir")))
        self.exe = self.scaps_dir / str(g("scaps_exe"))
        self.main_title = str(g("main_title"))
        xy = lambda k: tuple(int(float(v)) for v in str(g(k)).split(","))
        self.btn_setup = xy("btn_script_setup")
        self.btn_execute = xy("btn_execute_script")
        self.btn_load = xy("btn_editor_load")
        self.btn_ok = xy("btn_editor_ok")
        self.timeout = float(g("script_timeout"))
        self.stall = float(g("stall_limit"))
        self.launch_wait = float(g("launch_wait"))

    @property
    def def_dir(self):
        return self.scaps_dir / "def"

    @property
    def abs_dir(self):
        return self.scaps_dir / "absorption"

    def results_dir(self):
        """
        Whichever SCAPS results folder was written most recently. Under UAC,
        SCAPS writes to VirtualStore; after a permissions grant it may switch
        to the real folder and leave a stale VirtualStore behind.
        """
        real = self.scaps_dir / "results"
        rel = str(self.scaps_dir).split(":", 1)[-1].lstrip("\\/")
        virt = Path(os.path.expanduser("~")) / "AppData" / "Local" / \
            "VirtualStore" / rel / "results"
        cands = [p for p in (virt, real) if p.is_dir()]
        if not cands:
            return real
        return max(cands, key=lambda p: max(
            [p.stat().st_mtime] + [f.stat().st_mtime for f in p.iterdir()]))


def manifest(project):
    work = project.resolve("work_dir", "work")
    path = work / "manifest.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} -- run 'scapsml generate' first")
    return list(read_rows(path))


def compositions(project):
    seen = []
    for r in manifest(project):
        c = float(r["composition"])
        if c not in seen:
            seen.append(c)
    return seen


def expected(project, comp):
    return [r["iv_file"] for r in manifest(project)
            if abs(float(r["composition"]) - comp) < 1e-9]


def progress(project, comp):
    """(done, total, header_only) for one composition."""
    res = project.resolve("results_dir", "results")
    names = expected(project, comp)
    done = empty = 0
    for n in names:
        p = res / n
        if p.is_file():
            done += 1
            if p.stat().st_size < HEADER_ONLY_BYTES:
                empty += 1
    return done, len(names), empty


def status(project, out=print):
    comps = compositions(project)
    out(f"\nresults : {project.resolve('results_dir', 'results')}\n")
    out(f"  {'composition':>12} {'done':>7} {'total':>7} {'empty':>7}  state")
    out("  " + "-" * 56)
    td = tt = te = 0
    todo = []
    for c in comps:
        d, t, e = progress(project, c)
        td, tt, te = td + d, tt + t, te + e
        state = ("not started" if d == 0 else
                 "complete" if d >= t else f"partial ({100 * d / t:.0f}%)")
        if d < t:
            todo.append(c)
        out(f"  {c:>12.4g} {d:>7} {t:>7} {e:>7}  {state}")
    out("  " + "-" * 56)
    out(f"  {'all':>12} {td:>7} {tt:>7} {te:>7}  "
        f"{100 * td / tt if tt else 0:.1f}% complete")
    if te:
        out(f"\n  {te} header-only files: SCAPS rejected those problems before")
        out("  solving. Rerunning will not change them.")
    out(f"\n  next: scapsml run <workbook> {todo[0]:.4g}" if todo else
        "\n  all complete -- next: scapsml collect <workbook>")
    return todo


def install(project, comp, cfg):
    """Copy the defs, spectra and script this composition needs into SCAPS."""
    work = project.resolve("work_dir", "work")
    rows = [r for r in manifest(project)
            if abs(float(r["composition"]) - comp) < 1e-9]
    defs = sorted({r["def_file"] for r in rows})
    specs = sorted({r["abs_file"] for r in rows if r.get("abs_file")})
    copied, failed = 0, []
    for src, dst in ([(work / "defs" / d, cfg.def_dir / d) for d in defs] +
                     [(work / "absorption" / a, cfg.abs_dir / a) for a in specs]):
        try:
            shutil.copy2(src, dst)
            copied += 1
        except PermissionError:
            failed.append(dst.parent)
    if failed:
        raise PermissionError(
            f"cannot write to {sorted(set(map(str, failed)))}. SCAPS lives under "
            f"Program Files, which is UAC-protected. Either run this shell as "
            f"administrator, or grant yourself write access once:\n"
            f'    icacls "{cfg.def_dir}" /grant "$($env:USERNAME):(OI)(CI)M"\n'
            f'    icacls "{cfg.abs_dir}" /grant "$($env:USERNAME):(OI)(CI)M"\n'
            f"(the $(...) is required -- a bare $env:USERNAME: swallows the colon)")
    return copied


# --------------------------------------------------------------------------
# GUI (Windows only)
# --------------------------------------------------------------------------
def _gui():
    try:
        import pyautogui
        import pygetwindow as gw
        import pyperclip
    except ImportError as exc:
        raise SystemExit(
            "driving SCAPS needs the GUI extras (Windows only):\n"
            "    pip install scapsml[gui]") from exc
    try:
        import win32con
        import win32gui
        import win32process
        win32 = (win32gui, win32process, win32con)
    except ImportError:
        win32 = None
        log.warning("pywin32 missing -- dialog handling will be limited")
    pyautogui.FAILSAFE = True
    return pyautogui, gw, pyperclip, win32


def _dismiss(pid, win32):
    if not win32:
        return 0
    wg, wp, wc = win32
    hits = []

    def cb(h, _):
        if not wg.IsWindowVisible(h):
            return True
        try:
            _, p = wp.GetWindowThreadProcessId(h)
        except Exception:
            return True
        if p != pid:
            return True
        t = wg.GetWindowText(h).strip().lower()
        if any(k in t for k in PANEL_TITLES):
            return True
        if any(k in t for k in DIALOG_TITLES) or wg.GetClassName(h) == "#32770":
            hits.append(h)
        return True
    wg.EnumWindows(cb, None)
    n = 0
    for h in hits:
        def child(c, _):
            nonlocal n
            if wg.GetWindowText(c).strip().lower() in OK_LABELS:
                wg.SendMessage(c, BM_CLICK, 0, 0)
                n += 1
                return False
            return True
        try:
            wg.EnumChildWindows(h, child, None)
        except Exception:
            pass
    return n


def _kill():
    subprocess.call(["taskkill", "/F", "/IM", "scaps3312.exe"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_script(project, script, cfg):
    pyautogui, gw, pyperclip, win32 = _gui()
    res = cfg.results_dir()
    staged = cfg.def_dir / script.name
    shutil.copy2(script, staged)
    want = [res / ln.split()[-1] for ln in script.read_text().splitlines()
            if ln.strip().startswith("save results.iv ")]
    for p in want:
        try:
            p.unlink()
        except OSError:
            pass

    def wait(title, t):
        end = time.time() + t
        while time.time() < end:
            w = [x for x in gw.getAllWindows() if title.lower() in x.title.lower()]
            if w:
                return w[0]
            time.sleep(0.4)
        return None

    def click(xy, what):
        log.info(f"  click [{what}] at {xy}")
        pyautogui.click(*xy)

    _kill()
    proc = subprocess.Popen([str(cfg.exe)], cwd=str(cfg.scaps_dir))
    main = wait(cfg.main_title, cfg.launch_wait + 5)
    if not main:
        log.error("SCAPS did not open -- check project!scaps_dir")
        _kill()
        return False
    time.sleep(2)
    click(cfg.btn_setup, "Script set-up")
    time.sleep(2.5)
    if not (wait("script editor", 6) or wait("script", 4)):
        log.error("script editor did not open -- recalibrate: scapsml calibrate")
        _kill()
        return False
    click(cfg.btn_load, "Load")
    time.sleep(2.5)
    pyautogui.hotkey("ctrl", "a")
    pyperclip.copy(str(staged))
    pyautogui.hotkey("ctrl", "v")
    pyautogui.press("enter")
    time.sleep(2)
    click(cfg.btn_ok, "OK")
    time.sleep(1)
    click(cfg.btn_execute, "Execute script")
    time.sleep(2)

    deadline, found, last = time.time() + cfg.timeout, 0, time.time()
    ok = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        _dismiss(proc.pid, win32)
        n = sum(p.is_file() for p in want)
        if n > found:
            log.info(f"  progress {n}/{len(want)}")
            found, last = n, time.time()
        if n == len(want):
            ok = True
            time.sleep(1)
            break
        if time.time() - last > cfg.stall:
            log.error(f"  stalled at {found}/{len(want)} for {cfg.stall:.0f}s")
            break
        time.sleep(1.5)
    _kill()
    dest = project.resolve("results_dir", "results")
    dest.mkdir(parents=True, exist_ok=True)
    for p in want:
        if p.is_file():
            shutil.copy2(p, dest / p.name)
    try:
        staged.unlink()
    except OSError:
        pass
    return ok


def run(project, comps=None, next_n=None, force=False):
    from .generate import script_name
    cfg = Settings(project)
    allc = compositions(project)
    todo = [c for c in allc if progress(project, c)[0] < progress(project, c)[1]]
    if next_n:
        want = todo[:next_n]
    elif comps:
        want = [min(allc, key=lambda x: abs(x - c)) for c in comps]
    else:
        want = allc
    if not force:
        want = [c for c in want if c in todo]
    if not want:
        log.info("nothing to do (use --force to redo a composition)")
        return 0
    prefix = str(project.name).replace(" ", "_")
    work = project.resolve("work_dir", "work")
    for i, c in enumerate(want, 1):
        script = work / "scripts" / script_name(prefix, c)
        d, t, _ = progress(project, c)
        log.info(f"[{i}/{len(want)}] composition {c:.4g}  ({d}/{t} done)")
        try:
            install(project, c, cfg)
            run_script(project, script, cfg)
        except KeyboardInterrupt:
            log.warning("interrupted -- progress kept; rerun to resume")
            return 130
        except PermissionError as exc:
            log.error(str(exc))
            return 1
    status(project)
    return 0


def calibrate(project):
    """Record the four button positions by hovering and pressing Enter."""
    pyautogui, *_ = _gui()
    print("Open SCAPS. For each button, hover the mouse over it and press Enter.\n")
    out = {}
    for key, what in (("btn_script_setup", "Script set-up (action panel)"),
                      ("btn_execute_script", "Execute script (action panel)"),
                      ("btn_editor_load", "Load (script editor)"),
                      ("btn_editor_ok", "OK (script editor)")):
        input(f"  hover over {what}, then press Enter ")
        x, y = pyautogui.position()
        out[key] = f"{x},{y}"
        print(f"    {key} = {x},{y}")
    print("\nPaste these into the project sheet of your workbook:")
    for k, v in out.items():
        print(f"  {k}\t{v}")
    return out
