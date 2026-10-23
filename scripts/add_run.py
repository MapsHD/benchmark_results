#!/usr/bin/env python3
"""Copy one benchmark run from a pipeline workspace into results/<dataset>/<run>/.

Example:
  scripts/add_run.py --dataset humanoid-calibration-room-trial-1 \\
      --data-dir ~/hdmapping-benchmark/data \\
      --label "Full pipeline run (steps 1-6)" \\
      --stale kiss-icp,genz-icp --notes "..."

Reads from <data-dir>:
  tum/ape_table_github.md, tum/rpe_table_github.md   -> ape.md, rpe.md
  tum/overlap_results.md                             -> overlap.md
  step8_evaluation/evaluation_summary.csv            -> step8.csv      (if step 8 ran)
  tum/table_*.tex, tum/overlap_results.tex           -> tex/            (kept for papers)
  tum/ground_truth.tum + tum/output_hdmapping-*      -> trajectories.json (aligned, downsampled)
The orchestration commit and branch are read from --orchestration-dir
(default: <data-dir>/../benchmark-HDMapping-Orchestration). The new run is validated with build.py.
"""
import argparse
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

COPIES = [
    ("tum/ape_table_github.md", "ape.md"),
    ("tum/rpe_table_github.md", "rpe.md"),
    ("tum/overlap_results.md", "overlap.md"),
    ("step8_evaluation/evaluation_summary.csv", "step8.csv"),
]
TEX = ["tum/table_ape.tex", "tum/table_rpe.tex", "tum/overlap_results.tex"]


def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="dataset folder name under results/, e.g. bunker-dvi-reg-1")
    ap.add_argument("--data-dir", required=True, type=Path, help="pipeline data folder (contains tum/)")
    ap.add_argument("--date", default=datetime.date.today().isoformat(), help="run date YYYY-MM-DD (default: today)")
    ap.add_argument("--run", help="run folder name (default: the date; a suffix is added if it exists)")
    ap.add_argument("--label", required=True, help="short description shown in the run picker")
    ap.add_argument("--source", help="how the run was produced (default: built from the orchestration commit)")
    ap.add_argument("--orchestration-dir", type=Path, help="orchestration checkout used for the run")
    ap.add_argument("--stale", default="", help="comma-separated algorithms whose results are known to be stale")
    ap.add_argument("--notes", help="free-text notes shown with the run")
    ap.add_argument("--no-trajectories", action="store_true", help="skip trajectories.json (no numpy needed)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing run folder")
    args = ap.parse_args()

    data = args.data_dir.expanduser().resolve()
    if not (data / "tum").is_dir():
        sys.exit(f"{data} has no tum/ folder - pass the pipeline's data directory")
    ds_dir = ROOT / "results" / args.dataset
    if not (ds_dir / "dataset.json").exists():
        sys.exit(f"results/{args.dataset}/dataset.json does not exist - create the dataset first (see README, 'Adding a dataset')")

    run_name = args.run or args.date
    run_dir = ds_dir / run_name
    if run_dir.exists() and not args.force:
        if args.run:
            sys.exit(f"{run_dir} already exists - pick another --run or pass --force")
        n = 2
        while (ds_dir / f"{run_name}-{n}").exists():
            n += 1
        run_dir = ds_dir / f"{run_name}-{n}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    copied = []
    for src, dst in COPIES:
        if (data / src).exists():
            shutil.copy2(data / src, run_dir / dst)
            copied.append(dst)
    if not copied:
        shutil.rmtree(run_dir)
        sys.exit(f"no result tables found under {data} - has the pipeline finished steps 5-6?")
    tex = [t for t in TEX if (data / t).exists()]
    if tex:
        (run_dir / "tex").mkdir()
        for t in tex:
            shutil.copy2(data / t, run_dir / "tex" / Path(t).name)

    orch = (args.orchestration_dir or data.parent / "benchmark-HDMapping-Orchestration").expanduser()
    commit, branch = git(orch, "rev-parse", "--short", "HEAD"), git(orch, "rev-parse", "--abbrev-ref", "HEAD")
    meta = {
        "date": args.date,
        "label": args.label,
        "source": args.source or (f"start_benchmark.sh on branch {branch}, commit {commit}" if commit else "start_benchmark.sh"),
    }
    if commit:
        meta["orchestration_commit"] = commit
    if args.stale:
        meta["stale"] = [s.strip() for s in args.stale.split(",") if s.strip()]
    if args.notes:
        meta["notes"] = args.notes
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    if not args.no_trajectories and (data / "tum" / "ground_truth.tum").exists():
        subprocess.run([sys.executable, str(SCRIPTS / "extract_trajectories.py"), str(data / "tum"), str(run_dir)], check=True)

    print(f"\nadded {run_dir.relative_to(ROOT)}: {', '.join(copied)}" + (", tex/" if tex else "") +
          (", trajectories.json" if (run_dir / "trajectories.json").exists() else ""), flush=True)
    if not commit:
        print(f"warning: could not read the orchestration commit from {orch}; pass --orchestration-dir", file=sys.stderr)
    check = subprocess.run([sys.executable, str(SCRIPTS / "build.py"), "--check"])
    if check.returncode:
        sys.exit("the new run does not pass validation - fix the files above before committing")
    print(f"\nnext: git add {run_dir.relative_to(ROOT)} && git commit -m \"Add {args.dataset} run {run_dir.name}\" && git push")


if __name__ == "__main__":
    main()
