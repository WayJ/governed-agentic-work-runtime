#!/usr/bin/env python3
"""S7 F1 audit-fix regression — actual headless Chrome, standard library only.

Standalone regression for integration-review finding F1
(.agents/notes/2026-10-14-S7-gui-integration-review.md): the committed
audit's measure_contrast recorded "element missing" and returned without
creating a check, so a required contrast measurement could be silently
omitted while the run still passed (the neutral .chip-st-evt chip is
"element missing" in both committed before/after results, with no check
among the 199), and the events-tab measurement raced the asynchronously
rendered event cards (open_tab returns on the loading note; the chips
appear only after the /api/events fetch re-renders).

Reuses the audit's CDP client and helpers by importing
docs/superpowers/acceptances/assets/S7/s7_gui_audit.py (stdlib only).
This is an audit artifact, not a runtime dependency and not part of
unittest discovery.

Probes, on a real ui-demo store in real Chrome at 1440x900 with work
wait-1 selected:

  P0   present-element control: measure_contrast on the overview's
       waiting chip appends exactly one PASSing check — the loud-missing
       guard must not false-fail or double-report present elements.
  P2   events-panel race: right after open_tab("events"), whether
       .chip-st-evt exists yet is recorded as race evidence (observed
       absent pre-fix); after waiting for the rendered chip,
       measure_contrast appends exactly one PASSing check with a real
       measured ratio >= 4.5 (expected ~12.78, ink on #eceae4).
  P1   missing-selector negative, after phase: measure_contrast on a
       selector that matches nothing must append exactly one FAILing
       "contrast ... >= 4.50" check and record "element missing" —
       never silently skip the measurement.
  P1b  missing-selector negative, before phase: the same loud failure
       must fire in the baseline phase, so neither phase can falsely
       pass with an omitted measurement.

Usage: 2026-10-14-S7-audit-fix-regression.py --out DIR [--chrome PATH]
Exit 0 when every assertion holds; 1 otherwise.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
AUDIT_PATH = os.path.join(
    REPO, "docs", "superpowers", "acceptances", "assets", "S7",
    "s7_gui_audit.py")

spec = importlib.util.spec_from_file_location("s7_gui_audit", AUDIT_PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

RESULTS = []
RECORD = {"probes": {}}


def check(name, ok, observed):
    RESULTS.append(bool(ok))
    print("%s %s — %s" % ("PASS" if ok else "FAIL", name, observed),
          flush=True)


def connect_chrome(chrome):
    """Same launch pattern as the audit and integration capture scripts."""
    profile = tempfile.mkdtemp(prefix="s7-f1-reg-profile-")
    proc = subprocess.Popen(
        [chrome, "--headless", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", "--lang=en-US",
         "--remote-debugging-port=0", "--user-data-dir=" + profile,
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 20
    devtools = None
    while time.time() < deadline:
        line = proc.stderr.readline()
        if "DevTools listening on ws://" in line:
            host = line.split("ws://", 1)[1].strip().rstrip("/")
            devtools = host.rsplit("/devtools", 1)[0]
            break
    if not devtools:
        proc.kill()
        raise RuntimeError("Chrome never reported its DevTools endpoint")
    new = urllib.request.Request("http://%s/json/new?about:blank" % devtools,
                                 method="PUT")
    target = json.load(urllib.request.urlopen(new, timeout=10))
    return proc, audit.CdpPage(devtools, target["id"])


def probe_measure(page, label, selector, phase):
    """Call audit.measure_contrast and return what it appended.

    Returns (new_result_bools, new_check_dicts, measurement) so callers
    assert on the audit's real bookkeeping, not on our own echo.
    """
    n_results = len(audit.RESULTS)
    n_checks = len(audit.RECORD.get("checks", []))
    audit.measure_contrast(page, label, selector, 4.5, phase)
    return (audit.RESULTS[n_results:],
            audit.RECORD.get("checks", [])[n_checks:],
            audit.RECORD.get("measurements", {}).get("contrast " + label))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--chrome",
                        default="/Applications/Google Chrome.app/Contents/"
                                "MacOS/Google Chrome")
    args = parser.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    workdir = tempfile.mkdtemp(prefix="s7-f1-reg-stores-")
    demo = audit.UiServer([sys.executable, "-m", "work_runtime", "ui-demo",
                           "--directory", workdir], cwd=REPO)
    proc = page = None
    try:
        proc, page = connect_chrome(args.chrome)
        page.set_viewport(1440, 900)
        page.navigate(demo.url)
        state = audit.settle_list(page)
        check("demo store settles with 5 works",
              state and state.get("items") == 5,
              json.dumps(state, ensure_ascii=False))
        selected = audit.select_work(page, "wait-1")
        check("wait-1 selected (overview visible)", bool(selected),
              repr(selected))

        # ---- P0: present-element control (sync overview surface) ---------
        bools, dicts, measurement = probe_measure(
            page, "P0 waiting warn chip (present-element control)",
            ".chip-st-waiting", "after")
        check("P0 present element appends exactly one passing check",
              len(bools) == 1 and bools[0] is True,
              "results=%r checks=%r" % (bools,
                                        [d.get("name") for d in dicts]))
        check("P0 check is the required contrast check",
              len(dicts) == 1 and dicts[0].get("ok") is True
              and dicts[0].get("name", "").startswith("contrast P0")
              and "4.50" in dicts[0].get("name", ""),
              json.dumps(dicts, ensure_ascii=False))
        check("P0 measurement is a real ratio >= 4.5",
              isinstance(measurement, dict)
              and measurement.get("ratio") is not None
              and measurement["ratio"] >= 4.5,
              json.dumps(measurement))
        RECORD["probes"]["P0"] = {"measurement": measurement}

        # ---- P2: events-panel race ---------------------------------------
        opened = audit.open_tab(page, "events")
        check("P2 events tab opens", bool(opened), repr(opened))
        immediate = page.evaluate(
            "!!document.querySelector('#detail-body .chip-st-evt')")
        # Race evidence, not an assertion: pre-fix the audit measured at
        # this exact moment and silently recorded "element missing".
        RECORD["probes"]["P2"] = {
            "chip_present_immediately_after_open_tab": bool(immediate)}
        print("MEAS P2 .chip-st-evt present immediately after open_tab — %r"
              % bool(immediate), flush=True)
        present = audit.wait_true(
            page, "!!document.querySelector('#detail-body .chip-st-evt')")
        check("P2 event chip present after waiting for async render",
              bool(present), repr(present))
        bools, dicts, measurement = probe_measure(
            page, "P2 events neutral chip", ".chip-st-evt", "after")
        check("P2 neutral chip appends exactly one passing check",
              len(bools) == 1 and bools[0] is True,
              "results=%r checks=%r" % (bools,
                                        [d.get("name") for d in dicts]))
        check("P2 measurement is a real ratio >= 4.5",
              isinstance(measurement, dict)
              and measurement.get("ratio") is not None
              and measurement["ratio"] >= 4.5,
              json.dumps(measurement))
        RECORD["probes"]["P2"]["measurement"] = measurement
        page.screenshot(os.path.join(out, "s7-f1-reg-events-chip.png"))

        # ---- P1: missing-selector negative, after phase -------------------
        bools, dicts, measurement = probe_measure(
            page, "P1 negative control (selector absent by design)",
            ".s7-f1-definitely-not-present", "after")
        check("P1 missing selector appends exactly one failing check",
              len(bools) == 1 and bools[0] is False,
              "results=%r checks=%r" % (bools,
                                        [d.get("name") for d in dicts]))
        check("P1 failing check is the required contrast check",
              len(dicts) == 1 and dicts[0].get("ok") is False
              and dicts[0].get("name", "").startswith("contrast P1")
              and "4.50" in dicts[0].get("name", ""),
              json.dumps(dicts, ensure_ascii=False))
        check("P1 measurement recorded as element missing",
              measurement == "element missing", repr(measurement))
        RECORD["probes"]["P1"] = {"measurement": measurement}

        # ---- P1b: missing-selector negative, before phase -----------------
        bools, dicts, measurement = probe_measure(
            page, "P1b negative control before phase (selector absent)",
            ".s7-f1-definitely-not-present", "before")
        check("P1b missing selector fails loudly in before phase too",
              len(bools) == 1 and bools[0] is False
              and len(dicts) == 1 and dicts[0].get("ok") is False
              and dicts[0].get("name", "").startswith("contrast P1b")
              and "4.50" in dicts[0].get("name", ""),
              "results=%r checks=%r" % (bools,
                                        [d.get("name") for d in dicts]))
        check("P1b measurement recorded as element missing",
              measurement == "element missing", repr(measurement))
        RECORD["probes"]["P1b"] = {"measurement": measurement}
    finally:
        if page:
            page.close()
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        demo.kill()

    with open(os.path.join(out, "s7-f1-regression-results.json"), "w") as fh:
        json.dump(RECORD, fh, indent=1, ensure_ascii=False)
    failed = RESULTS.count(False)
    print("s7 f1 regression: %d assertions, %d failed; evidence: %s"
          % (len(RESULTS), failed, out), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
