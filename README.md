# benchmark_results

Results of the [MapsHD](https://github.com/MapsHD) LiDAR / LiDAR-inertial odometry benchmark, published as an interactive website.

- **`main`** holds the result tables produced by
  [benchmark-HDMapping-Orchestration](https://github.com/MapsHD/benchmark-HDMapping-Orchestration),
  the build scripts and the page template.
- **`gh-pages`** holds the generated website. It is rebuilt by CI on every push to `main`; never edit it by hand.

The site has, per dataset: a ranking chart and sortable table for each metric (APE, RPE, overlap and,
where step 8 ran, point-cloud metrics), aligned XY trajectories, and the history of every committed run.

## Repository layout

```text
results/
  <dataset-id>/
    dataset.json              title, description, links, display order
    <run-id>/                 one folder per benchmark run, usually the run date (2026-10-23)
      meta.json               date, label, source, orchestration commit, notes, stale algorithms
      ape.md                  copy of data/tum/ape_table_github.md
      rpe.md                  copy of data/tum/rpe_table_github.md
      overlap.md              copy of data/tum/overlap_results.md            (optional)
      step8.csv               copy of data/step8_evaluation/evaluation_summary.csv (optional)
      trajectories.json       aligned, downsampled XY trajectories            (optional)
      tex/                    LaTeX tables from the same run, not used by the site
scripts/
  add_run.py                  copy a finished run from a pipeline workspace into results/
  extract_trajectories.py     align TUM trajectories to ground truth -> trajectories.json
  build.py                    validate results/ and build _site/index.html
site/page.html                page template (data is inlined at build time)
.github/workflows/pages.yml   CI: validate on PRs, build and deploy main to gh-pages
```

## Publishing a new run

Run the benchmark as described in the orchestration branch for the dataset, and wait until it has
finished at least steps 5 and 6 (and step 8 if the branch has it). Then, from a clone of this repository:

```shell
python3 -m pip install numpy        # once; only needed for trajectories.json

scripts/add_run.py \
  --dataset humanoid-calibration-room-trial-1 \
  --data-dir ~/hdmapping-benchmark/data \
  --label "Full pipeline run (steps 1-6)"
```

`add_run.py`:

1. Copies the tables from `<data-dir>` into `results/<dataset>/<date>/`. If a run with that date already
   exists, it adds a suffix (`2026-10-23-2`).
2. Writes `meta.json`, reading the orchestration commit and branch from
   `<data-dir>/../benchmark-HDMapping-Orchestration` (override with `--orchestration-dir`).
3. Aligns all trajectories to ground truth and writes `trajectories.json` (skip with `--no-trajectories`).
4. Validates everything with `scripts/build.py --check`.

Then review and publish:

```shell
scripts/build.py && xdg-open _site/index.html     # optional local preview
git checkout -b add-<dataset>-<date>
git add results/<dataset>/<run-id>
git commit -m "Add <dataset> run <run-id>"
git push -u origin HEAD                           # open a PR; CI validates it
```

When the PR is merged into `main`, CI rebuilds the site and publishes it to `gh-pages` within a few minutes.

### Before you commit a run

- **Check the results are from this run.** The pipeline does not clear old algorithm outputs. If an
  algorithm fails to record (for example a ROS 2 algorithm whose `recorded-*` folder already existed), its
  previous trajectory is converted again and appears as a valid result. Compare the timestamps of each
  `data/<algorithm>/recorded-*` with the run start, or start from an empty `data/` folder.
- **Mark known-stale results** with `--stale kiss-icp,genz-icp`. They are shown dashed and labeled
  "stale" on the site.
- **Write down anything unusual** with `--notes "..."`: algorithms that crashed, timeouts, changed
  inputs. The notes are shown next to the run.
- **Record converter versions** that affect the input data in `--source`, for example
  `"start_benchmark.sh, input bag converted with mandeye_to_bag 34dbd19"`.

### Fixing a published run

Edit the files under `results/<dataset>/<run-id>/` (usually `meta.json`) in a PR. To remove a run,
delete its folder. History on the site always reflects what is on `main`.

## Adding a dataset

Create `results/<dataset-id>/dataset.json`. Use a lowercase id with hyphens, naming the recording
(`humanoid-flat-room-trial-1`, not `humanoid-2`):

```json
{
  "title": "HUMANOID-LIO — flat-room, trial 1",
  "description": "One or two sentences: sensor setup, scenario, what ground truth is used.",
  "order": 3,
  "links": {
    "Orchestration branch": "https://github.com/MapsHD/benchmark-HDMapping-Orchestration/tree/HUMANOID-LIO-DATASET",
    "Dataset (Zenodo)": "https://zenodo.org/records/21318128"
  }
}
```

`order` sets the position of the dataset tab. Then add its first run with `add_run.py`.

## Run metadata (`meta.json`)

| field | required | meaning |
| --- | --- | --- |
| `date` | yes | run date, `YYYY-MM-DD`; runs are ordered by it |
| `label` | yes | short description shown in the run picker |
| `source` | no | how the numbers were produced (script, branch, commit, converter versions) |
| `orchestration_commit` | no | short hash of the orchestration checkout |
| `stale` | no | list of algorithms whose results are known not to come from this run |
| `notes` | no | free text shown with the run |

Results reported elsewhere (for example in a branch README) can be added as runs too. Copy the tables
into `ape.md` / `rpe.md` / … and set `source` to where they came from.

## Algorithm names

The pipeline uses different spellings for the same algorithm (`genz` in the evo tables, `genz-icp` in
step 8, `HDMapping_LIO` and `hdmapping-lio`). `build.py` lowercases names, turns `_` into `-`, and applies
the `ALIASES` table in `scripts/build.py`. If a new spelling shows up as a separate algorithm on the
site, or the build reports duplicate algorithms, add it to `ALIASES`.

## Status colours

Each metric colours algorithms as good, drift or failed. The thresholds live in `METRICS` in
`scripts/build.py`:

| metric | key column | good | drift | failed |
| --- | --- | --- | --- | --- |
| APE | `rmse` | < 1 m | 1–10 m | ≥ 10 m |
| RPE | `rmse` | < 0.1 m | 0.1–1 m | ≥ 1 m |
| Overlap | `Metric1 [%]` | ≥ 95 % | 70–95 % | < 70 % |
| Point cloud | `chamfer_distance_m` | < 0.5 m | 0.5–5 m | ≥ 5 m |

## CI and deployment

`.github/workflows/pages.yml`:

- **Pull requests to `main`:** validate (`build.py --check`) and build. Nothing is deployed.
- **Push to `main`, or manual run:** validate, build, and force-push `_site/` to `gh-pages`, keeping only the
  latest version.

A failed validation lists every problem (missing `meta.json`, bad date, missing key column, unknown
stale algorithm, duplicate names) and blocks the deploy.

### One-time GitHub setup

1. **Settings → Actions → General → Workflow permissions:** select *Read and write permissions*, so the
   workflow can push `gh-pages`.
2. Push `main` once. The first workflow run creates the `gh-pages` branch.
3. **Settings → Pages:** set *Source* to *Deploy from a branch*, branch `gh-pages`, folder `/ (root)`.
4. Optionally protect `main` and require the *build* check, so every change goes through a PR.

The site is then served at `https://mapshd.github.io/benchmark_results/`.

## Local development

```shell
python3 scripts/build.py --check    # validate only
python3 scripts/build.py            # writes _site/index.html (self-contained, open it directly)
```

`build.py` needs only the Python standard library; `extract_trajectories.py` also needs `numpy`.
The page loads Plotly from jsDelivr, pinned to `plotly.js-basic-dist-min@2.35.2`.

## Citation

Będkowski J. et al., "MapsHD: A benchmark suite for LiDAR odometry frameworks", *SoftwareX* 35 (2026) 102822,
doi:[10.1016/j.softx.2026.102822](https://doi.org/10.1016/j.softx.2026.102822).
