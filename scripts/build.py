#!/usr/bin/env python3
"""Build the results website (_site/index.html) from results/<dataset>/<run>/ folders.

Usage: build.py [--check]     --check validates the results without writing _site/

Each run folder may contain any of:
  ape.md, rpe.md       evo tables (ape_table_github.md / rpe_table_github.md)
  overlap.md           overlap_step6 table (overlap_results.md)
  step8.csv / step8.md point-cloud evaluation (evaluation_summary.csv / .md)
  trajectories.json    aligned XY trajectories written by extract_trajectories.py
  meta.json            {"date", "label", "source", "orchestration_commit", "notes", "stale": [...]}
Each dataset folder has a dataset.json with {"title", "description", "order", "links"}.
Any problem found is reported and the script exits with status 1, so CI blocks the deploy.
"""
import csv
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
SITE = ROOT / "site"
OUT = ROOT / "_site"

# Names differ between the evo tables, the overlap table and step 8; map them to one id.
ALIASES = {
    "genz": "genz-icp",
    "kiss": "kiss-icp",
    "lidar-odometry-ros": "lidar_odometry_ros_wrapper",
    "lidar-odometry-ros-wrapper": "lidar_odometry_ros_wrapper",
    "dali-slam": "dalislam",
    "voxel-slam": "voxelslam",
    "loam": "loam-livox",
    "superodometry": "superodom",
    "mola-lidar-odometry": "mola",
    "rko-lio": "rko-lio",
}

# Metric definitions. "key" is the column used for ranking and history; "good"/"bad" are the
# thresholds for the good / drift / failed colouring (inverted when lower is not better).
METRICS = {
    "ape": {"title": "APE", "long": "Absolute Pose Error", "key": "rmse", "unit": "m", "lower": True, "good": 1, "bad": 10},
    "rpe": {"title": "RPE", "long": "Relative Pose Error", "key": "rmse", "unit": "m", "lower": True, "good": 0.1, "bad": 1},
    "overlap": {"title": "Overlap", "long": "Trajectory completeness", "key": "Metric1 [%]", "unit": "%", "lower": False, "good": 95, "bad": 70},
    "step8": {"title": "Point cloud", "long": "Registered map vs TLS reference", "key": "chamfer_distance_m", "unit": "m", "lower": True, "good": 0.5, "bad": 5},
}

STEP8_DROP = {"status", "message", "voxel_size_m", "threshold_m", "reference_input_points", "reference_points"}


def canonical(name):
    n = name.strip().rstrip("*").strip().lower().replace("_", "-")
    n = ALIASES.get(n, n)
    return "lidar_odometry_ros_wrapper" if n == "lidar-odometry-ros-wrapper" else n


def number(cell):
    cell = cell.strip()
    if cell in ("", "-", "nan", "NaN"):
        return None
    try:
        return float(cell)
    except ValueError:
        return cell


def parse_md(path):
    rows = [line.strip().strip("|").split("|") for line in path.read_text().splitlines() if line.startswith("|")]
    if not rows:
        return None
    header = [c.strip() for c in rows[0]]
    body = [r for r in rows[1:] if not re.fullmatch(r"[\s\-:|]*", "".join(r))]
    return header, [[c.strip() for c in r] for r in body]


def parse_csv(path):
    with path.open(newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], rows[1:]


def load_table(run_dir, key):
    for name in (f"{key}.csv", f"{key}.md"):
        path = run_dir / name
        if path.exists():
            parsed = parse_csv(path) if path.suffix == ".csv" else parse_md(path)
            break
    else:
        return None
    header, body = parsed
    columns = header[1:]
    if key == "step8":
        columns = [c for c in columns if c not in STEP8_DROP]
    rows = []
    for r in body:
        raw = dict(zip(header, r))
        name = r[0]
        values = {c: number(raw.get(c, "")) for c in columns}
        if key == "step8" and raw.get("status", "evaluated") != "evaluated":
            values = {c: None for c in columns}
            values["_status"] = raw.get("status")
        if name.endswith("*"):
            values["_note"] = "never moved; aligned at first pose (evo_ape --align_origin)"
        rows.append({"id": canonical(name), "name": name.rstrip("*").strip(), "values": values})
    return {"columns": columns, "rows": rows, "file": path.name}


class ResultsError(Exception):
    pass


def build():
    errors = []
    datasets = []
    for ds_dir in sorted(p for p in RESULTS.iterdir() if p.is_dir()):
        try:
            info = json.loads((ds_dir / "dataset.json").read_text())
            if not info.get("title"):
                errors.append(f"{ds_dir.name}/dataset.json: missing \"title\"")
        except FileNotFoundError:
            errors.append(f"{ds_dir.name}: missing dataset.json")
            continue
        except json.JSONDecodeError as e:
            errors.append(f"{ds_dir.name}/dataset.json: invalid JSON ({e})")
            continue
        runs = []
        for run_dir in sorted(p for p in ds_dir.iterdir() if p.is_dir()):
            where = f"{ds_dir.name}/{run_dir.name}"
            try:
                meta = json.loads((run_dir / "meta.json").read_text())
            except FileNotFoundError:
                errors.append(f"{where}: missing meta.json")
                continue
            except json.JSONDecodeError as e:
                errors.append(f"{where}/meta.json: invalid JSON ({e})")
                continue
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta.get("date", ""))):
                errors.append(f"{where}/meta.json: \"date\" must be YYYY-MM-DD")
            tables = {}
            for k in METRICS:
                try:
                    t = load_table(run_dir, k)
                except Exception as e:  # malformed file
                    errors.append(f"{where}: cannot parse {k} table ({e})")
                    continue
                if not t:
                    continue
                if METRICS[k]["key"] not in t["columns"]:
                    errors.append(f"{where}/{t['file']}: column \"{METRICS[k]['key']}\" not found (columns: {', '.join(t['columns'])})")
                ids = [r["id"] for r in t["rows"]]
                dup = sorted({i for i in ids if ids.count(i) > 1})
                if dup:
                    errors.append(f"{where}/{t['file']}: duplicate algorithms after name normalisation: {', '.join(dup)}")
                tables[k] = t
            if not tables:
                errors.append(f"{where}: no tables found (expected ape.md, rpe.md, overlap.md or step8.csv)")
                continue
            known = {r["id"] for t in tables.values() for r in t["rows"]}
            stale = [canonical(s) for s in meta.get("stale", [])]
            for s_id in stale:
                if s_id not in known:
                    errors.append(f"{where}/meta.json: stale algorithm \"{s_id}\" does not appear in any table")
            traj = None
            if (tp := run_dir / "trajectories.json").exists():
                try:
                    traj = json.loads(tp.read_text())
                except json.JSONDecodeError as e:
                    errors.append(f"{where}/trajectories.json: invalid JSON ({e})")
            runs.append({
                "id": run_dir.name,
                "date": meta.get("date", run_dir.name[:10]),
                "label": meta.get("label", run_dir.name),
                "source": meta.get("source"),
                "commit": meta.get("orchestration_commit"),
                "notes": meta.get("notes"),
                "stale": stale,
                "tables": tables,
                "trajectories": traj,
            })
        if not runs:
            errors.append(f"{ds_dir.name}: no valid runs")
            continue
        runs.sort(key=lambda r: (r["date"], r["id"]))
        datasets.append({"id": ds_dir.name, **info, "runs": runs})
    if errors:
        raise ResultsError("\n".join(f"  - {e}" for e in errors))
    datasets.sort(key=lambda d: (d.get("order", 99), d["id"]))
    built = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return {"metrics": METRICS, "datasets": datasets, "built": built}


def main():
    try:
        data = build()
    except ResultsError as e:
        sys.exit(f"results check failed:\n{e}")
    n_runs = sum(len(d["runs"]) for d in data["datasets"])
    if "--check" in sys.argv[1:]:
        print(f"results OK: {len(data['datasets'])} datasets, {n_runs} runs")
        return
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = (SITE / "page.html").read_text().replace("__DATA__", payload)
    # page.html is a fragment (title, styles, body); GitHub Pages needs a full document.
    head = '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    (OUT / "index.html").write_text(head + page + "\n</html>\n")
    (OUT / "fragment.html").write_text(page)
    (OUT / "data.json").write_text(json.dumps(data, indent=1))
    (OUT / ".nojekyll").write_text("")
    print(f"built {OUT} with {len(data['datasets'])} datasets, {n_runs} runs")


if __name__ == "__main__":
    main()
