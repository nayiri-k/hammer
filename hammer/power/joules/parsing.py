import re
import csv
import argparse
from pathlib import Path
import json
import sys
from typing import Optional, List, Dict, Any, Iterable

# ----------------------------
#  power.rpt PARSER 
# ----------------------------

ROW_RE = re.compile(
    r'^\s*[|│]?\s*(?P<category>[A-Za-z0-9_.\-]+)\s+'
    r'(?P<leakage>[0-9.eE+-]+)\s+'
    r'(?P<internal>[0-9.eE+-]+)\s+'
    r'(?P<switching>[0-9.eE+-]+)\s+'
    r'(?P<total>[0-9.eE+-]+)\s+'
    r'(?P<rowpct>[0-9.]+%)\s*$'
)

SUBTOTAL_RE = re.compile(
    r'^\s*Subtotal\s+'
    r'(?P<leakage>[0-9.eE+-]+)\s+'
    r'(?P<internal>[0-9.eE+-]+)\s+'
    r'(?P<switching>[0-9.eE+-]+)\s+'
    r'(?P<total>[0-9.eE+-]+)\s+'
    r'(?P<rowpct>[0-9.]+%)\s*$'
)

PERCENT_RE = re.compile(
    r'^\s*Percentage\s+'
    r'(?P<leakage>[0-9.]+%)\s+'
    r'(?P<internal>[0-9.]+%)\s+'
    r'(?P<switching>[0-9.]+%)\s+'
    r'(?P<total>[0-9.]+%)\s+'
    r'(?P<rowpct>[0-9.]+%)\s*$'
)

def parse_table(lines: Iterable[str]):
    rows = []
    subtotal = None
    percentage = None

    for ln in lines:
        m = ROW_RE.match(ln)
        if m:
            d = m.groupdict()
            rows.append({
                "category": d["category"].strip(),
                "leakage": float(d["leakage"]),
                "internal": float(d["internal"]),
                "switching": float(d["switching"]),
                "total": float(d["total"]),
                "row_pct": float(d["rowpct"].rstrip("%")),
            })
            continue

        m = SUBTOTAL_RE.search(ln)
        if m:
            d = m.groupdict()
            subtotal = {
                "leakage": float(d["leakage"]),
                "internal": float(d["internal"]),
                "switching": float(d["switching"]),
                "total": float(d["total"]),
                "row_pct": float(d["rowpct"].rstrip("%")),
            }
            continue

        m = PERCENT_RE.search(ln)
        if m:
            d = m.groupdict()
            percentage = {
                "leakage": float(d["leakage"].rstrip("%")),
                "internal": float(d["internal"].rstrip("%")),
                "switching": float(d["switching"].rstrip("%")),
                "total": float(d["total"].rstrip("%")),
                "row_pct": float(d["rowpct"].rstrip("%")),
            }
            continue

    return rows, subtotal, percentage

def write_csv(rows, subtotal, percentage, fileobj):
    w = csv.writer(fileobj)
    w.writerow(["category", "leakage", "internal", "switching", "total", "row_pct"])
    for r in rows:
        w.writerow([r["category"], r["leakage"], r["internal"], r["switching"], r["total"], r["row_pct"]])
    if subtotal:
        w.writerow(["Subtotal", subtotal["leakage"], subtotal["internal"], subtotal["switching"], subtotal["total"], subtotal["row_pct"]])
    if percentage:
        w.writerow(["Percentage", percentage["leakage"], percentage["internal"], percentage["switching"], percentage["total"], percentage["row_pct"]])

# ----------------------------
#  HIERARCHICAL power.rpt PARSER (output.hier.power.rpt)
# ----------------------------

# Example header seen in the file:
# Power Unit: mW
# Area Unit: Um^2
# PDB Frame : /stim#2/frame#0
# ------------------------------------------------------
# Cells Pct_cells Leakage Internal Switching Total Lvl Instance
#    3  100.00%  1.63890e-08  6.37071e-03  1.05226e-01  1.11597e-01  0 /pass

HIER_ROW_RE = re.compile(
    r'^\s*[|│]?\s*(?P<cells>\d+)\s+'
    r'(?P<pct_cells>[0-9.]+%)\s+'
    r'(?P<leakage>[0-9.eE+-]+)\s+'
    r'(?P<internal>[0-9.eE+-]+)\s+'
    r'(?P<switching>[0-9.eE+-]+)\s+'
    r'(?P<total>[0-9.eE+-]+)\s+'
    r'(?P<lvl>\d+)\s+'
    r'(?P<instance>\S.*)\s*$'
)

H_POWER_UNIT_RE = re.compile(r'^\s*Power Unit:\s*(?P<power_unit>\S+)\s*$')
H_AREA_UNIT_RE  = re.compile(r'^\s*Area Unit:\s*(?P<area_unit>.+?)\s*$')
H_PDB_FRAME_RE  = re.compile(r'^\s*PDB Frame\s*:\s*(?P<pdb_frame>.+?)\s*$')

def parse_hier_power_table(lines: Iterable[str]) -> Dict[str, Any]:
    """Parse output.hier.power.rpt into rows + optional metadata."""
    rows: List[Dict[str, Any]] = []
    meta: Dict[str, Optional[str]] = {"power_unit": None, "area_unit": None, "pdb_frame": None}

    for ln in lines:
        s = ln.strip()

        # Extract simple metadata lines if present
        m = H_POWER_UNIT_RE.match(ln)
        if m:
            meta["power_unit"] = m.group("power_unit")
            continue
        m = H_AREA_UNIT_RE.match(ln)
        if m:
            meta["area_unit"] = m.group("area_unit")
            continue
        m = H_PDB_FRAME_RE.match(ln)
        if m:
            meta["pdb_frame"] = m.group("pdb_frame")
            continue

        # Skip rule/header lines
        if not s or set(s) <= {"=", "-", "─", " ", "|", "│"}:
            continue
        if s.lower().startswith("cells ") or s.lower().startswith("cells\t"):
            continue

        m = HIER_ROW_RE.match(ln)
        if not m:
            continue
        d = m.groupdict()
        rows.append({
            "cells": int(d["cells"]),
            "pct_cells": float(d["pct_cells"].rstrip("%")),
            "leakage": float(d["leakage"]),
            "internal": float(d["internal"]),
            "switching": float(d["switching"]),
            "total": float(d["total"]),
            "lvl": int(d["lvl"]),
            "instance": d["instance"].strip(),
        })

    return {"rows": rows, "meta": meta}

def write_hier_csv(rows: List[Dict[str, Any]], fileobj):
    w = csv.writer(fileobj)
    w.writerow(["cells", "pct_cells", "leakage", "internal", "switching", "total", "lvl", "instance"])
    for r in rows:
        w.writerow([
            r.get("cells"),
            r.get("pct_cells"),
            r.get("leakage"),
            r.get("internal"),
            r.get("switching"),
            r.get("total"),
            r.get("lvl"),
            r.get("instance"),
        ])

# ----------------------------
# PPA Table parser functions next
# ----------------------------

NUM = r'(?:[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)'
NA  = r'(?:n/?a|N/?A|-)'
NUM_OR_NA = rf'(?:{NUM}|{NA})'

PPA_ROW_RE = re.compile(
    rf'^\s*(?P<category>[A-Za-z0-9_.\-/ ]+?)\s+'
    rf'(?P<bits>{NUM_OR_NA})\s+'
    rf'(?P<pct_cg>{NUM_OR_NA})\s+'
    rf'(?P<power_static>{NUM_OR_NA})\s+'
    rf'(?P<power_dynamic>{NUM_OR_NA})\s+'
    rf'(?P<timing_delay>{NUM_OR_NA})\s+'
    rf'(?P<timing_slack>{NUM_OR_NA})\s+'
    rf'(?P<area_cell>{NUM_OR_NA})\s+'
    rf'(?P<area_routing>{NUM_OR_NA})\s+'
    rf'(?P<instance_path>\S.*)?\s*$'
)

def _num_or_none(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if not s or s.lower() in {"n/a", "na", "-", "n\\a"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None

def parse_ppa_table(lines: Iterable[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for ln in lines:
        # skip header/separator lines
        if set(ln.strip()) <= {"=", "-", "─", " ", "|", "│"}:
            continue
        m = PPA_ROW_RE.match(ln)
        if not m:
            continue
        d = m.groupdict()
        category = d["category"].strip()
        if category.lower().startswith("category"):
            continue
        rows.append({
            "category": category,
            "bits": _num_or_none(d["bits"]),
            "pct_cg": _num_or_none(d["pct_cg"]),
            "power_static": _num_or_none(d["power_static"]),
            "power_dynamic": _num_or_none(d["power_dynamic"]),
            "timing_delay": _num_or_none(d["timing_delay"]),
            "timing_slack": _num_or_none(d["timing_slack"]),
            "area_cell": _num_or_none(d["area_cell"]),
            "area_routing": _num_or_none(d["area_routing"]),
            "instance_path": (d["instance_path"] or "").strip() or None,
        })
    return rows

def write_ppa_csv(rows: List[Dict[str, Any]], fileobj):
    w = csv.writer(fileobj)
    w.writerow([
        "category", "bits", "pct_cg",
        "power_static", "power_dynamic",
        "timing_delay", "timing_slack",
        "area_cell", "area_routing",
        "instance_path",
    ])
    for r in rows:
        w.writerow([
            r.get("category"),
            r.get("bits"),
            r.get("pct_cg"),
            r.get("power_static"),
            r.get("power_dynamic"),
            r.get("timing_delay"),
            r.get("timing_slack"),
            r.get("area_cell"),
            r.get("area_routing"),
            r.get("instance_path"),
        ])

# ----------------------------
# CLI: choose parser by path containing "ppa" or "hier"
# ----------------------------

DEFAULT_OUT       = "/users/vihaan1406/hammer/hammer/power/joules/output.power.csv"
DEFAULT_OUT_PPA   = "/users/vihaan1406/hammer/hammer/power/joules/output.ppa.csv"
DEFAULT_OUT_HIER  = "/users/vihaan1406/hammer/hammer/power/joules/output.hier.power.csv"

def main():
    ap = argparse.ArgumentParser(description="Parse power.rpt, hierarchical output.hier.power.rpt, or PPA output.ppa.rpt")
    ap.add_argument("source", help="path to the report file on this machine")
    ap.add_argument("--json", action="store_true", help="Output JSON (default CSV)")
    ap.add_argument("--out", "-o", default=None, help="Output file path")
    args = ap.parse_args()

    src = args.source
    lsrc = src.lower()
    is_ppa  = ("ppa" in lsrc)
    is_hier = ("hier" in lsrc)

    with open(src, encoding="utf-8") as f:
        lines = f.readlines()

    # choose output path
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path(DEFAULT_OUT_PPA if is_ppa else (DEFAULT_OUT_HIER if is_hier else DEFAULT_OUT))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if is_ppa:
        rows = parse_ppa_table(lines)
        if args.json:
            out_path.write_text(json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8")
            print("Wrote JSON to", out_path)
            return
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            write_ppa_csv(rows, f)
        print("Wrote CSV to", out_path)
        return

    if is_hier:
        parsed = parse_hier_power_table(lines)
        rows = parsed["rows"]
        meta = parsed["meta"]
        if args.json:
            out_path.write_text(json.dumps({"rows": rows, "meta": meta}, indent=2) + "\n", encoding="utf-8")
            print("Wrote JSON to", out_path)
            return
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            write_hier_csv(rows, f)
        print("Wrote CSV to", out_path)
        return

    # original behavior (flat power.rpt)
    rows, subtotal, percentage = parse_table(lines)
    if args.json:
        out_path.write_text(json.dumps(
            {"rows": rows, "subtotal": subtotal, "percentage": percentage},
            indent=2
        ) + "\n", encoding="utf-8")
        print("Wrote JSON to", out_path)
        return

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        write_csv(rows, subtotal, percentage, f)
    print("Wrote CSV to", out_path)

if __name__ == "__main__":
    main()

# command for running the parser on ppa output - PYTHONPATH=. python3 hammer/power/joules/parsing.py \e2e/build-sky130-cm/pass/power-rtl-rundir/reports/output.ppa.rpt
# command for running parser on power.rpt output -  python3 /users/vihaan1406/hammer/hammer/power/joules/parsing.py \/users/vihaan1406/hammer/e2e/build-sky130-cm/pass/power-rtl-rundir/reports/output.power.rpt
# command for running parser on hier.power.rpt - python3 /users/vihaan1406/hammer/hammer/power/joules/parsing.py \/users/vihaan1406/hammer/e2e/build-sky130-cm/pass/power-rtl-rundir/reports/output.hier.power.rpt