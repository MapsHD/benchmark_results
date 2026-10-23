#!/usr/bin/env python3
"""Align TUM trajectories to ground truth and write a small trajectories.json for the site.

Usage: extract_trajectories.py <tum_dir> <run_dir> [--hz 2]

<tum_dir> is the pipeline's data/tum folder (ground_truth.tum + output_hdmapping-*_trajectory_tum.txt).
Each trajectory is aligned like `evo_traj -a`: poses are associated with ground truth by timestamp
(max 10 ms apart) and a rigid SE(3) transform (Umeyama, no scale) is fitted on the matched positions.
The aligned XY path is downsampled to --hz and rounded to centimetres.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import canonical  # noqa: E402

MAX_DT = 0.01


def load_tum(path):
    rows = [line.split() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    rows = [r for r in rows if len(r) == 8]
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    return a[:, 0], a[:, 1:4]


def associate(t_ref, t):
    idx = np.clip(np.searchsorted(t_ref, t), 1, len(t_ref) - 1)
    left, right = t_ref[idx - 1], t_ref[idx]
    idx = np.where(np.abs(t - left) <= np.abs(t - right), idx - 1, idx)
    ok = np.abs(t_ref[idx] - t) <= MAX_DT
    return np.nonzero(ok)[0], idx[ok]


def umeyama(src, dst):
    mu_s, mu_d = src.mean(0), dst.mean(0)
    cov = (dst - mu_d).T @ (src - mu_s) / len(src)
    u, _, vt = np.linalg.svd(cov)
    s = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s[2, 2] = -1
    r = u @ s @ vt
    return r, mu_d - r @ mu_s


def downsample(t, xyz, hz):
    keep = np.unique(np.floor((t - t[0]) * hz), return_index=True)[1]
    return xyz[keep]


def pack(xyz):
    return {"x": np.round(xyz[:, 0], 2).tolist(), "y": np.round(xyz[:, 1], 2).tolist()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tum_dir", type=Path)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--hz", type=float, default=2.0)
    args = ap.parse_args()

    gt = load_tum(args.tum_dir / "ground_truth.tum")
    if gt is None:
        sys.exit(f"no ground_truth.tum in {args.tum_dir}")
    t_gt, p_gt = gt
    order = np.argsort(t_gt)
    t_gt, p_gt = t_gt[order], p_gt[order]

    out = {"aligned": "SE(3) Umeyama on positions, timestamps matched within 10 ms (as evo_traj -a)",
           "hz": args.hz, "ground_truth": pack(downsample(t_gt, p_gt, args.hz)), "algorithms": []}
    for f in sorted(args.tum_dir.glob("output_hdmapping-*_trajectory_tum.txt")):
        name = re.sub(r"^output_hdmapping-|_trajectory_tum\.txt$", "", f.name)
        entry = {"id": canonical(name), "name": name}
        traj = load_tum(f)
        if traj is None:
            out["algorithms"].append({**entry, "skipped": "empty trajectory file"})
            continue
        t, p = traj
        i_traj, i_gt = associate(t_gt, t)
        if len(i_traj) < 10:
            out["algorithms"].append({**entry, "skipped": "no timestamps matching ground truth"})
            continue
        r, tr = umeyama(p[i_traj], p_gt[i_gt])
        aligned = p @ r.T + tr
        out["algorithms"].append({**entry, "matched": int(len(i_traj)), **pack(downsample(t, aligned, args.hz))})
        print(f"{name:28s} matched {len(i_traj):6d} poses")

    args.run_dir.mkdir(parents=True, exist_ok=True)
    dest = args.run_dir / "trajectories.json"
    dest.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {dest} ({dest.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
