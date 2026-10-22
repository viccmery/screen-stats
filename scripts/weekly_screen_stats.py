"""Mapped weekly trial counts, independent of intermediate experiment sheets."""

from pathlib import Path
import re

import pandas as pd


def clean(values):
    return (values.astype("string").str.replace("\u00a0", " ", regex=False)
            .str.replace(r"\s+", " ", regex=True).str.strip().replace("", pd.NA))


def load_mapping(path, screen):
    frame = pd.read_csv(path, dtype="string")
    frame.columns = frame.columns.str.strip()
    if "screen" in frame:
        frame = frame.loc[clean(frame["screen"]).str.casefold().eq(screen.casefold())].copy()
    frame["key"] = clean(frame["condition"]).str.casefold()
    # Prefer an explicit canonical name over an empty entry in repeated mappings.
    frame["line"] = clean(frame["condition_2"]).str.casefold()
    explicit = frame.dropna(subset=["key", "line"])
    conflicts = explicit.groupby("key")["line"].nunique()
    if conflicts.gt(1).any():
        raise ValueError(f"Conflicting line mappings: {conflicts[conflicts.gt(1)].index.tolist()}")
    labels = explicit.drop_duplicates("key").set_index("key")["line"]
    frame["line"] = frame["key"].map(labels).fillna(frame["key"])
    result = frame[["key", "line"]].dropna().drop_duplicates()
    if result.empty:
        raise ValueError(f"No mapped lines for {screen} in {path}")
    return result.reset_index(drop=True)


def read_weekly_sheets(directory):
    """Read every CSV/Excel sheet; ignore worksheets without experiment columns."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Weekly sheets directory not found: {directory}")
    frames = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith(("~$", ".")):
            continue
        if path.suffix.lower() == ".csv":
            sheets = {"CSV": pd.read_csv(path, dtype="string")}
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            sheets = pd.read_excel(path, sheet_name=None, dtype="string")
        else:
            continue
        for sheet, frame in sheets.items():
            frame.columns = frame.columns.str.strip()
            if not {"condition", "amendments"}.issubset(frame.columns):
                continue
            frame = frame.loc[clean(frame["condition"]).notna()].copy()
            if frame.empty:
                continue
            # Numeric sorting supports week2, week-10, week_3 and week-11.1.
            match = re.search(r"week[-_ ]*(\d+(?:\.\d+)?)", path.stem, re.I)
            if match is None:
                match = re.search(r"week[-_ ]*(\d+(?:\.\d+)?)", str(sheet), re.I)
            if match is None:
                raise ValueError(f"Cannot identify week: {path.name}, worksheet {sheet}")
            frame["week"] = match.group(1)
            frame["source_file"] = path.name
            frame["source_sheet"] = sheet
            frames.append(frame)
    if not frames:
        raise ValueError(f"No weekly experiment rows found in {directory}")
    return pd.concat(frames, ignore_index=True)


def summarise(actual, mapping, *, blank_is_successful=False):
    """Retain every mapped line and observed week, including zero-success lines.

    Unknown conditions retain their raw name and are returned for review.
    Blank/unrecognised amendments remain unscored unless legacy blank-as-success
    behaviour is explicitly enabled. Only -1 denotes a failed trial.
    """
    actual = actual.copy()
    actual["key"] = clean(actual["condition"]).str.casefold()
    actual = actual.loc[actual["key"].notna()].copy()
    actual = actual.merge(mapping, on="key", how="left", validate="m:1")
    unmapped = sorted(actual.loc[actual["line"].isna(), "key"].unique())
    actual["line"] = actual["line"].fillna(actual["key"])
    amendments = clean(actual["amendments"])
    status = pd.to_numeric(amendments, errors="coerce")
    actual["successful"] = status.eq(0).fillna(False) | (amendments.isna() & blank_is_successful)
    actual["failed"] = status.eq(-1).fillna(False)
    actual["unscored"] = ~(actual["successful"] | actual["failed"])
    lines = sorted(set(mapping["line"]) | set(actual["line"]))
    weeks = sorted(actual["week"].unique(), key=float)
    index = pd.MultiIndex.from_product([lines, weeks], names=["line", "week"])
    counts = (actual.groupby(["line", "week"])[["successful", "failed", "unscored"]]
              .sum().reindex(index, fill_value=0).astype(int).reset_index())
    totals = counts.groupby("line")[["successful", "failed", "unscored"]].sum().reset_index()
    return counts, totals, unmapped


def plot_successful(counts, title, *, target=18):
    """All mapped lines on x; stacked weeks show successful trials per line."""
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    matrix = counts.pivot(index="line", columns="week", values="successful")
    matrix = matrix.reindex(columns=sorted(matrix.columns, key=float))
    if matrix.empty:
        raise ValueError("No lines/weeks available to plot")
    fig, ax = plt.subplots(figsize=(max(14, len(matrix) * 0.25), 6))
    bottom = pd.Series(0, index=matrix.index)
    colours = plt.get_cmap("viridis")
    for i, week in enumerate(matrix.columns):
        values = matrix[week]
        ax.bar(range(len(matrix)), values, bottom=bottom,
               label=f"Week {week}", color=colours(i / max(1, len(matrix.columns) - 1)))
        bottom += values
    ax.axhline(target, color="grey", linestyle="--", linewidth=1, label=f"Target: {target}")
    ax.set_xticks(range(len(matrix)), matrix.index, rotation=90, fontsize=8)
    ax.set(xlabel="Mapped line (condition_2)", ylabel="Successful trials", title=title,
           ylim=(0, max(target, int(bottom.max())) + 2))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig, ax
