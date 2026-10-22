#!/usr/bin/env python3
"""
Reusable analysis pipeline for sensory-deprivation hole-detection CSV files.

Expected columns per experiment/video CSV:
    hole_id, max_size, lifetime

Conditions recognised from filename/path:
    W1118, 9047, ss00888, 23129, 33300, anosmic

Outputs, inside <data_folder>/analysis_output by default:
    video_summary.csv
    group_summary.csv
    overall_stats.csv
    stats_vs_W1118.csv
    unclassified_files.csv, only if needed
    all_metrics_by_condition.png

The experimental unit for statistics is the video/CSV file, not individual holes.
"""

from __future__ import annotations

import argparse
import math
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats


CONDITIONS = ["W1118", "9047", "ss00888", "23129", "33300", "anosmic"]
CONTROL = "W1118"

REQUIRED_COLUMNS = {"hole_id", "max_size", "lifetime"}

METRICS = ["n_holes", "median_max_size", "median_lifetime"]

METRIC_LABELS = {
    "n_holes": "Number of holes per video",
    "median_max_size": "Median max hole size per video",
    "median_lifetime": "Median hole lifetime per video (frames)",
}


def infer_condition(path: Path) -> str | None:
    """
    Infer condition from the file path/name.

    Returns one condition if exactly one condition is recognised.
    Returns None if no condition or multiple conditions are recognised.
    """
    text = str(path).lower()

    patterns = {
        "W1118": [r"w[-_ ]?1118", r"w1118"],
        "9047": [r"(?<!\d)9047(?!\d)"],
        "ss00888": [r"ss[-_ ]?00888", r"ss[-_ ]?888"],
        "23129": [r"(?<!\d)23129(?!\d)"],
        "33300": [r"(?<!\d)33300(?!\d)"],
        "anosmic": [r"anosmic"],
    }

    hits = []

    for condition, pats in patterns.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in pats):
            hits.append(condition)

    if len(hits) == 1:
        return hits[0]

    return None


def read_experiment_csv(path: Path) -> pd.DataFrame:
    """
    Read one experiment/video CSV and check required columns.
    """
    df = pd.read_csv(path)
    df.columns = [str(col).strip() for col in df.columns]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    df["max_size"] = pd.to_numeric(df["max_size"], errors="coerce")
    df["lifetime"] = pd.to_numeric(df["lifetime"], errors="coerce")

    return df


def summarize_video(path: Path, condition: str) -> dict:
    """
    Summarise one video/CSV file.

    One output row = one video.
    """
    df = read_experiment_csv(path)

    n_holes = int(df["hole_id"].dropna().nunique())

    return {
        "condition": condition,
        "video_file": path.name,
        "video_path": str(path),
        "n_holes": n_holes,
        "mean_max_size": df["max_size"].mean(),
        "median_max_size": df["max_size"].median(),
        "max_hole_size": df["max_size"].max(),
        "mean_lifetime": df["lifetime"].mean(),
        "median_lifetime": df["lifetime"].median(),
        "max_lifetime": df["lifetime"].max(),
        "n_rows": len(df),
        "n_valid_max_size": int(df["max_size"].notna().sum()),
        "n_valid_lifetime": int(df["lifetime"].notna().sum()),
    }


def holm_adjust(pvalues: list[float]) -> list[float]:
    """
    Holm step-down family-wise error correction.
    """
    p = np.asarray(pvalues, dtype=float)
    m = len(p)

    order = np.argsort(p)
    adjusted = np.empty(m, dtype=float)
    running = 0.0

    for rank, idx in enumerate(order):
        val = (m - rank) * p[idx]
        running = max(running, val)
        adjusted[idx] = min(running, 1.0)

    return adjusted.tolist()


def rank_biserial_from_u(u: float, n1: int, n2: int) -> float:
    """
    Rank-biserial effect size from Mann-Whitney U.

    Positive means group 1 tends to be larger than group 2.
    """
    return (2.0 * u) / (n1 * n2) - 1.0


def overall_tests(video_df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """
    Kruskal-Wallis test across all conditions for each metric.
    """
    rows = []

    for metric in metrics:
        groups = []
        included = []

        for condition in CONDITIONS:
            vals = video_df.loc[
                video_df["condition"] == condition,
                metric,
            ].dropna().to_numpy()

            if len(vals):
                groups.append(vals)
                included.append(condition)

        if len(groups) >= 2:
            h, p = stats.kruskal(*groups)
        else:
            h, p = np.nan, np.nan

        rows.append(
            {
                "metric": metric,
                "test": "Kruskal-Wallis",
                "groups_included": ";".join(included),
                "H": h,
                "p_value": p,
            }
        )

    return pd.DataFrame(rows)


def compare_to_control(video_df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """
    Compare each condition to W1118 for each metric using Mann-Whitney U.

    Stats are exported for reference, but the main plot is descriptive.
    """
    rows = []

    for metric in metrics:
        control = video_df.loc[
            video_df["condition"] == CONTROL,
            metric,
        ].dropna().to_numpy()

        raw_ps = []
        metric_rows = []

        for condition in CONDITIONS:
            if condition == CONTROL:
                continue

            test = video_df.loc[
                video_df["condition"] == condition,
                metric,
            ].dropna().to_numpy()

            if len(control) == 0 or len(test) == 0:
                row = {
                    "metric": metric,
                    "comparison": f"{condition} vs {CONTROL}",
                    "condition": condition,
                    "n_condition_videos": len(test),
                    "n_control_videos": len(control),
                    "condition_median": np.nan if len(test) == 0 else float(np.median(test)),
                    "control_median": np.nan if len(control) == 0 else float(np.median(control)),
                    "median_difference": np.nan,
                    "mannwhitney_U": np.nan,
                    "rank_biserial": np.nan,
                    "p_raw": np.nan,
                }
                metric_rows.append(row)
                raw_ps.append(np.nan)
                continue

            u, p = stats.mannwhitneyu(
                test,
                control,
                alternative="two-sided",
                method="auto",
            )

            row = {
                "metric": metric,
                "comparison": f"{condition} vs {CONTROL}",
                "condition": condition,
                "n_condition_videos": len(test),
                "n_control_videos": len(control),
                "condition_median": float(np.median(test)),
                "control_median": float(np.median(control)),
                "median_difference": float(np.median(test) - np.median(control)),
                "mannwhitney_U": float(u),
                "rank_biserial": float(rank_biserial_from_u(u, len(test), len(control))),
                "p_raw": float(p),
            }

            metric_rows.append(row)
            raw_ps.append(float(p))

        valid_idx = [i for i, p in enumerate(raw_ps) if not math.isnan(p)]

        if valid_idx:
            adjusted = holm_adjust([raw_ps[i] for i in valid_idx])
            adj_map = dict(zip(valid_idx, adjusted))
        else:
            adj_map = {}

        for i, row in enumerate(metric_rows):
            row["p_holm"] = adj_map.get(i, np.nan)
            p_adj = row["p_holm"]
            row["significant_0.05"] = bool(p_adj < 0.05) if not pd.isna(p_adj) else False
            rows.append(row)

    return pd.DataFrame(rows)


def group_summary(video_df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """
    Summarise each condition for each metric.
    """
    rows = []

    for condition in CONDITIONS:
        sub = video_df[video_df["condition"] == condition]

        for metric in metrics:
            vals = sub[metric].dropna()

            rows.append(
                {
                    "condition": condition,
                    "metric": metric,
                    "n_videos": int(vals.shape[0]),
                    "mean": vals.mean(),
                    "sd": vals.std(ddof=1) if len(vals) > 1 else np.nan,
                    "median": vals.median(),
                    "q1": vals.quantile(0.25) if len(vals) else np.nan,
                    "q3": vals.quantile(0.75) if len(vals) else np.nan,
                    "min": vals.min() if len(vals) else np.nan,
                    "max": vals.max() if len(vals) else np.nan,
                }
            )

    return pd.DataFrame(rows)


def plot_all_metrics(video_df: pd.DataFrame, output_path: Path) -> None:
    """
    Plot the three raw metrics as separate panels in one figure.

    No individual points.
    Gray boxplots only.
    """
    present_conditions = [
        condition
        for condition in CONDITIONS
        if (video_df["condition"] == condition).any()
    ]

    if not present_conditions:
        return

    fig, axes = plt.subplots(
        nrows=1,
        ncols=3,
        figsize=(18, 5.5),
    )

    for ax, metric in zip(axes, METRICS):
        values = [
            video_df.loc[
                video_df["condition"] == condition,
                metric,
            ].dropna().to_numpy()
            for condition in present_conditions
        ]

        ax.boxplot(
            values,
            tick_labels=present_conditions,
            showfliers=False,
            patch_artist=True,
            boxprops=dict(facecolor="lightgray", edgecolor="gray", linewidth=1.5),
            whiskerprops=dict(color="gray", linewidth=1.2),
            capprops=dict(color="gray", linewidth=1.2),
            medianprops=dict(color="black", linewidth=1.5),
        )

        ax.set_xlabel("Condition")
        ax.set_ylabel(METRIC_LABELS[metric])
        ax.set_title(METRIC_LABELS[metric])
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(axis="x", rotation=45)

    fig.suptitle(
        "Hole-detection metrics by condition",
        fontsize=14,
        y=1.03,
    )

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def analyse(data_folder: Path, output_folder: Path) -> None:
    output_folder.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(
        path
        for path in data_folder.rglob("*.csv")
        if output_folder not in path.parents and path.parent != output_folder
    )

    summaries = []
    problems = []

    for path in csv_files:
        condition = infer_condition(path)

        if condition is None:
            problems.append(
                {
                    "file": str(path),
                    "reason": "condition not uniquely recognised from filename/path",
                }
            )
            continue

        try:
            summaries.append(summarize_video(path, condition))
        except Exception as exc:
            problems.append(
                {
                    "file": str(path),
                    "reason": str(exc),
                }
            )

    if not summaries:
        raise RuntimeError(
            "No usable experiment CSV files were found. "
            "Ensure filenames/paths contain one of: "
            + ", ".join(CONDITIONS)
        )

    video_df = pd.DataFrame(summaries)

    video_df["condition"] = pd.Categorical(
        video_df["condition"],
        categories=CONDITIONS,
        ordered=True,
    )

    video_df = (
        video_df
        .sort_values(["condition", "video_file"])
        .reset_index(drop=True)
    )

    video_df.to_csv(output_folder / "video_summary.csv", index=False)

    group_summary(video_df, METRICS).to_csv(
        output_folder / "group_summary.csv",
        index=False,
    )

    overall_tests(video_df, METRICS).to_csv(
        output_folder / "overall_stats.csv",
        index=False,
    )

    compare_to_control(video_df, METRICS).to_csv(
        output_folder / "stats_vs_W1118.csv",
        index=False,
    )

    problems_path = output_folder / "unclassified_files.csv"

    if problems:
        pd.DataFrame(problems).to_csv(problems_path, index=False)
    elif problems_path.exists():
        problems_path.unlink()

    plot_all_metrics(
        video_df,
        output_folder / "all_metrics_by_condition.png",
    )

    counts = (
        video_df
        .groupby("condition", observed=False)
        .size()
        .reindex(CONDITIONS, fill_value=0)
    )

    print("\nAnalysis complete.")
    print(f"Data folder:   {data_folder}")
    print(f"Output folder: {output_folder}")

    print("\nVideos per condition:")
    for condition, n in counts.items():
        print(f"  {condition:8s} {int(n)}")

    print("\nSaved outputs:")
    print(f"  {output_folder / 'video_summary.csv'}")
    print(f"  {output_folder / 'group_summary.csv'}")
    print(f"  {output_folder / 'overall_stats.csv'}")
    print(f"  {output_folder / 'stats_vs_W1118.csv'}")
    print(f"  {output_folder / 'all_metrics_by_condition.png'}")

    if problems:
        print(f"\nWARNING: {len(problems)} file(s) were skipped. See {problems_path}")


def snapshot(data_folder: Path) -> tuple:
    files = []

    for path in data_folder.rglob("*.csv"):
        try:
            stat = path.stat()
            files.append((str(path), stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            pass

    return tuple(sorted(files))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse sensory-deprivation hole-detection CSV experiments."
    )

    parser.add_argument(
        "data_folder",
        type=Path,
        help="Folder containing experiment CSV files",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output folder, default: DATA_FOLDER/analysis_output",
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep running and automatically reanalyse when CSVs change",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Watch polling interval in seconds, default: 30",
    )

    args = parser.parse_args()

    data_folder = args.data_folder.expanduser().resolve()

    if not data_folder.exists():
        raise SystemExit(f"Data folder does not exist: {data_folder}")

    output_folder = (
        args.output.expanduser().resolve()
        if args.output
        else data_folder / "analysis_output"
    )

    analyse(data_folder, output_folder)

    if args.watch:
        print(
            f"\nWatching for new/changed CSV files every {args.interval:g} seconds. "
            "Press Ctrl+C to stop."
        )

        old = snapshot(data_folder)

        try:
            while True:
                time.sleep(args.interval)

                new = snapshot(data_folder)

                if new != old:
                    print("\nCSV change detected; rerunning analysis...")

                    try:
                        analyse(data_folder, output_folder)
                    except Exception as exc:
                        print(f"Analysis error: {exc}")

                    old = new

        except KeyboardInterrupt:
            print("\nStopped watching.")


if __name__ == "__main__":
    main()