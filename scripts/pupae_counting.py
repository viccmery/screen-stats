#!/usr/bin/env python3
"""Merge a pupae-counting batch into its weekly Google Sheet.

The only required argument is the pupae batch folder name.  The experiment year
and screen week are derived from that name, for example::

    python scripts/pupae_counting.py VM_2026-06-26_VRDN-screen_week1_batch5_f12
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import gspread
import numpy as np
import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

INSTRUMENTS_ROOT = Path(
    "/Volumes/lab-windingm/data/instruments/behavioural_rigs/plugcamera"
)
CREDENTIALS_PATH = Path("credentials.json")
TOKEN_PATH = Path("token.json")
WORKSHEET_TITLE = "Sheet1"

WEEK_TO_SPREADSHEET_ID = {
    1: "1pLGTVYPtalXG0o81nfcdldW7l_wCYjrAkbaok7Qm1AA",
    2: "1LyZz-w3hfr1HtEhWeX-Mh7jGxFdMruvkwO_f6CJAFXM",
    3: "1Qhw80Em3mNXuQzxJDndURJooYMgjBusFIzSk_V5VY7k",
    4: "1WrWOelZgj5-MBAScA3J1nOvCJ362CMWuvTNuXOvOwnI",
    5: "1-_ieR_zL29S_yWGH8p5NCDg6I8T8uD8iYOywlqnv8RQ",
    6: "1p-rRjZKr78O77VeYuWq3zRA74Vjdli2j5pshYnwmJd0",
    7: "1g8utRFF02OVMsuhlnVtWP37OPk-AR87k7LYKUXkWiY0",
    8: "1XhFpnJtBSPPOwSeprZKXmq5IK9cFB-zgdKMGU89hgTE"
}

MATCH_COLUMNS = ["condition", "date", "time"]
WEEKLY_ID_COLUMNS = ["weekly_id", "date", "time"]
MISSING_LIKE = {"", "nan", "na", "n/a", "<na>", "none", "null", "nat"}
LEGACY_UPLOAD_COLUMNS = {
    "dataset",
    "pupae_source_row",
    "pupae_count",
    "raw_sheet_matches",
    # A misspelled version has also appeared in uploaded sheets.
    "raw_sheet_mates_from_pupae",
}


@dataclass(frozen=True)
class BatchMetadata:
    year: int
    target_week: int


def parse_batch_metadata(pupae_batch_folder: str) -> BatchMetadata:
    """Extract one four-digit year and one ``week`` number from a folder name."""
    folder_name = Path(pupae_batch_folder.rstrip("/\\")).name

    years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", folder_name))
    if len(years) != 1:
        raise ValueError(
            "The pupae batch folder name must contain exactly one four-digit year; "
            f"found {sorted(years) or 'none'} in {folder_name!r}."
        )

    weeks = {
        int(value)
        for value in re.findall(r"(?i)week[-_ ]?(\d+)(?!\d)", folder_name)
    }
    if len(weeks) != 1:
        raise ValueError(
            "The pupae batch folder name must identify exactly one week (for example "
            f"week1 or week-1); found {sorted(weeks) or 'none'} in {folder_name!r}."
        )

    return BatchMetadata(year=int(next(iter(years))), target_week=next(iter(weeks)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pupae_batch_folder",
        help="Batch folder name, e.g. VM_2026-06-26_VRDN-screen_week1_batch5_f12",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and merge the data without changing the Google Sheet",
    )
    return parser.parse_args()


def get_gspread_client(
    credentials_path: Path = CREDENTIALS_PATH,
    token_path: Path = TOKEN_PATH,
) -> gspread.Client:
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Google OAuth credentials were not found at {credentials_path}."
                )
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            credentials = flow.run_local_server(port=0)

        token_path.write_text(credentials.to_json())

    return gspread.authorize(credentials)


def read_pupae_counts(
    pupae_batch_folder: str,
    instruments_root: Path = INSTRUMENTS_ROOT,
) -> pd.DataFrame:
    folder_name = Path(pupae_batch_folder.rstrip("/\\")).name
    predictions_dir = instruments_root / folder_name / "pupae" / "predictions"
    if not predictions_dir.is_dir():
        raise FileNotFoundError(f"Predictions folder not found: {predictions_dir}")

    csv_files = sorted(predictions_dir.glob("*.csv"))
    if len(csv_files) != 1:
        raise ValueError(
            f"Expected exactly one CSV in {predictions_dir}, found {len(csv_files)}."
        )
    return pd.read_csv(csv_files[0])


def require_columns(df: pd.DataFrame, columns: list[str], source: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{source} is missing required columns: {', '.join(missing)}")


def clean_match_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    for column in ["condition", "weekly_id", "date", "time"]:
        if column not in result:
            result[column] = pd.NA
        result[column] = (
            result[column]
            .astype("string")
            .str.replace("\u00a0", " ", regex=False)
            .str.strip()
            .str.lower()
        )
    for column in ["condition", "weekly_id", "date", "time"]:
        result[column] = result[column].mask(result[column].isin(MISSING_LIKE))
    # Google Sheets may return numeric IDs as floats when other rows are blank.
    result["weekly_id"] = result["weekly_id"].str.replace(
        r"^(\d+)\.0$", r"\1", regex=True
    )
    result["date"] = result["date"].str.replace(
        r"^(\d{1,2})[-/](\d{1,2})$",
        lambda match: f"{int(match[1]):02d}-{int(match[2]):02d}",
        regex=True,
    )
    return result


def remove_legacy_upload_artifacts(sheet_df: pd.DataFrame) -> pd.DataFrame:
    """Remove diagnostic data accidentally uploaded by older script versions."""
    result = sheet_df.copy()

    staging = result.get("staging_date", pd.Series(pd.NA, index=result.index))
    staging = staging.astype("string").str.strip()
    missing_staging = staging.isna() | staging.str.lower().isin(MISSING_LIKE)
    source_columns = [
        column
        for column in ("dataset", "pupae_source_row", "pupae_count")
        if column in result.columns
    ]
    if source_columns and "staging_date" in result:
        has_source_data = pd.Series(False, index=result.index)
        for column in source_columns:
            values = result[column].astype("string").str.strip()
            has_source_data |= values.notna() & ~values.str.lower().isin(MISSING_LIKE)
        result = result.loc[~(missing_staging & has_source_data)].copy()

    temporary_columns = {
        column
        for column in result.columns
        if column in LEGACY_UPLOAD_COLUMNS
        or column.endswith("_from_pupae")
        or column.startswith("raw_sheet_match")
    }
    return result.drop(columns=list(temporary_columns), errors="ignore")


def prepare_sheet(sheet_df: pd.DataFrame, expected_year: int) -> pd.DataFrame:
    require_columns(sheet_df, ["condition", "Pupae"], "Google Sheet")
    result = remove_legacy_upload_artifacts(sheet_df)
    for tracking_column in ["pupae_batch_folder", "last_edit"]:
        if tracking_column not in result.columns:
            result[tracking_column] = pd.NA
    result = clean_match_columns(result)
    if "staging_date" not in result:
        return result
    staging = result["staging_date"].astype("string").str.strip()

    range_parts = staging.str.extract(
        r"^\s*(?P<first_day>\d{1,2})\s*-\s*\d{1,2}/(?P<month>\d{1,2})/(?P<year>\d{4})\s*$"
    )
    first_date_from_range = (
        range_parts["first_day"].str.zfill(2)
        + "/"
        + range_parts["month"].str.zfill(2)
        + "/"
        + range_parts["year"]
    )
    first_full_date = staging.str.extract(
        r"(?P<first_date>\d{1,2}/\d{1,2}/\d{4})", expand=False
    )
    first_date = first_date_from_range.where(
        range_parts["first_day"].notna(), first_full_date
    )
    parsed_date = pd.to_datetime(first_date, format="%d/%m/%Y", errors="coerce")

    found_years = set(parsed_date.dropna().dt.year.astype(int))
    if found_years and expected_year not in found_years:
        raise ValueError(
            f"The batch name says {expected_year}, but the Google Sheet dates contain "
            f"{sorted(found_years)}. Refusing to update the wrong year's sheet."
        )

    result["date"] = result["date"].fillna(parsed_date.dt.strftime("%d-%m"))
    night = staging.str.contains(r"\d\s*-\s*\d", na=False)
    missing_time = result["time"].isna()
    result.loc[missing_time & parsed_date.notna() & night, "time"] = "night"
    result.loc[missing_time & parsed_date.notna() & ~night, "time"] = "day"
    return clean_match_columns(result)


def prepare_pupae_counts(
    pupae_batch_csv: pd.DataFrame,
    pupae_batch_folder: str,
    year: int,
) -> pd.DataFrame:
    require_columns(pupae_batch_csv, ["dataset", "pupae_count"], "Pupae CSV")
    result = pupae_batch_csv.copy()
    result["pupae_source_row"] = result.index + 1
    result["pupae_batch_folder"] = Path(
        pupae_batch_folder.rstrip("/\\")
    ).name

    result["dataset"] = result["dataset"].astype("string").str.strip()
    result["dataset"] = result["dataset"].str.split("predictions/", n=1).str[-1]
    result["dataset"] = result["dataset"].str.replace(
        r"(\d{1,2})[-_](\d{1,2})[-_](day|night)\b",
        r"\1-\2_\3",
        regex=True,
    )
    pattern = (
        r"(?i)(?P<condition>.+?)[_-](?P<date>\d{1,2}-\d{1,2})"
        r"[_-](?P<time>day|night)(?:_|\b)"
    )
    result[["condition", "date", "time"]] = result["dataset"].str.extract(
        pattern, expand=True
    )
    # A short letter/number label (A1, B2), a number, or an explicit
    # weekly_id prefix denotes a temporary ID local to the loaded weekly sheet.
    # All other prefixes remain conditions, even if no sheet row matches them.
    weekly_id = result["condition"].str.extract(
        r"(?i)^(?:weekly[_-]?id[_-]?)?([a-z]\d+|\d+)$", expand=False
    )
    result["weekly_id"] = weekly_id
    result.loc[weekly_id.notna(), "condition"] = pd.NA
    result["staging_date_clean_dt"] = pd.to_datetime(
        result["date"] + f"-{year}", format="%d-%m-%Y", errors="coerce"
    )
    result["L_value"] = pd.to_numeric(
        result["dataset"].str.extract(r"(?i)_L(\d+)", expand=False),
        errors="coerce",
    ).astype("Int64")
    result["pupae_count"] = pd.to_numeric(result["pupae_count"], errors="coerce")
    result["Pupae"] = result["pupae_count"] + result["L_value"]
    result["last_edit"] = pd.Timestamp.today().strftime("%d-%m-%Y")
    result = clean_match_columns(result)

    invalid = result[
        result[["date", "time"]].isna().any(axis=1)
        | result["staging_date_clean_dt"].isna()
        | (result["condition"].isna() & result["weekly_id"].isna())
        | result[["pupae_count", "L_value", "Pupae"]].isna().any(axis=1)
    ]
    if not invalid.empty:
        rows = ", ".join(invalid["pupae_source_row"].astype(str))
        raise ValueError(f"Could not parse pupae CSV source row(s): {rows}.")
    return result


def merge_pupae_counts(
    sheet_df: pd.DataFrame, pupae_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Match by condition, using weekly IDs only when the filename lacks one.

    IDs are supplied by the weekly sheet, never generated from row order. They
    are scoped by date and time and must resolve to exactly one sheet row.
    """
    sheet = clean_match_columns(sheet_df).reset_index(drop=True)
    pupae = clean_match_columns(pupae_df).reset_index(drop=True)
    for column in ["pupae_batch_folder", "last_edit"]:
        if column not in sheet:
            sheet[column] = pd.NA
    sheet["_sheet_row"] = np.arange(len(sheet))
    diagnostics = []
    for use_weekly_id, keys in [(False, MATCH_COLUMNS), (True, WEEKLY_ID_COLUMNS)]:
        selected = pupae["condition"].isna().eq(use_weekly_id)
        batch = pupae.loc[selected].copy()
        if batch.empty:
            continue
        label = "/".join(keys)
        valid_sheet = sheet.loc[sheet[keys].notna().all(axis=1)]
        counts = valid_sheet.groupby(keys).size().rename("raw_sheet_matches")
        lookup = valid_sheet.drop_duplicates(keys).merge(counts, on=keys)
        lookup = lookup[keys + ["_sheet_row", "raw_sheet_matches"]]
        batch = batch.merge(lookup, on=keys, how="left", validate="m:1")
        batch["raw_sheet_matches"] = batch["raw_sheet_matches"].fillna(0).astype(int)
        batch["pupae_key_matches"] = batch.groupby(keys, dropna=False)[
            "Pupae"
        ].transform("size")
        batch["match_method"] = "weekly_id" if use_weekly_id else "condition"
        batch["pupae_merge_safety_reason"] = "safe to merge"
        batch.loc[batch["raw_sheet_matches"].eq(0), "pupae_merge_safety_reason"] = (
            f"{label} not found in Google Sheet"
        )
        batch.loc[batch["raw_sheet_matches"].gt(1), "pupae_merge_safety_reason"] = (
            f"duplicate {label} in Google Sheet"
        )
        batch.loc[batch["pupae_key_matches"].gt(1), "pupae_merge_safety_reason"] = (
            f"duplicate {label} in pupae CSV"
        )
        diagnostics.append(batch)

    if not diagnostics:
        return sheet.drop(columns="_sheet_row"), pupae
    diagnostic = pd.concat(diagnostics, ignore_index=True)
    unique_target = diagnostic["raw_sheet_matches"].eq(1)
    # A condition filename and an ID filename can both point at the same row.
    collision = diagnostic.loc[unique_target, "_sheet_row"].duplicated(keep=False)
    diagnostic.loc[collision.index[collision], "pupae_merge_safety_reason"] = (
        "multiple pupae CSV rows target the same Google Sheet row"
    )
    existing = sheet["Pupae"].astype("string").str.strip().str.lower()
    occupied = sheet["Pupae"].notna() & ~existing.isin(MISSING_LIKE)
    has_existing = diagnostic["_sheet_row"].isin(sheet.loc[occupied, "_sheet_row"])
    diagnostic.loc[unique_target & has_existing, "pupae_merge_safety_reason"] = (
        "existing Pupae already present"
    )
    diagnostic["safe_for_pupae_merge"] = diagnostic["pupae_merge_safety_reason"].eq(
        "safe to merge"
    )
    safe = diagnostic.loc[diagnostic["safe_for_pupae_merge"]]
    for column in ["Pupae", "pupae_batch_folder", "last_edit"]:
        rows = safe["_sheet_row"].astype(int)
        sheet.loc[rows, column] = safe[column].to_numpy()
    unmatched = diagnostic.loc[~diagnostic["safe_for_pupae_merge"]].drop(
        columns="_sheet_row"
    ).copy()
    return sheet.drop(columns="_sheet_row"), unmatched



def append_manual_review_rows(
    merged: pd.DataFrame, unmatched: pd.DataFrame
) -> pd.DataFrame:
    """Keep unmatched CSV counts below the sheet rows for manual review."""
    if unmatched.empty:
        return merged.copy()
    review = unmatched.copy()
    review["manual_inspection_reason"] = review["pupae_merge_safety_reason"]
    review = review.drop(
        columns=[
            "raw_sheet_matches", "pupae_key_matches", "safe_for_pupae_merge",
            "pupae_merge_safety_reason", "match_method", "staging_date_clean_dt",
            "L_value", "pupae_source_row", "pupae_count",
        ],
        errors="ignore",
    )
    return pd.concat([merged, review], ignore_index=True)



def flag_void_pupae_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Void counts outside 100–250 and append the reason to existing comments."""
    result = df.copy()
    counts = pd.to_numeric(result["Pupae"], errors="coerce")
    for column in ["amendments", "comments"]:
        if column not in result:
            result[column] = pd.NA
    outside_range = counts.lt(100) | counts.gt(250)
    if not outside_range.any():
        return result

    # Sheets can supply text columns even when amendments contains numbers.
    result["amendments"] = result["amendments"].astype(object)
    result["comments"] = result["comments"].astype(object)
    result.loc[outside_range, "amendments"] = -1

    def append_reason(value: object, reason: str) -> str:
        comment = "" if pd.isna(value) else str(value).strip()
        if comment.lower() in MISSING_LIKE:
            return reason
        existing_reasons = {part.strip().lower() for part in comment.split(",")}
        if reason in existing_reasons:
            return comment
        return f"{comment}, {reason}"

    for mask, reason in [
        (counts.lt(100), "not enough pupae"),
        (counts.gt(250), "too many pupae"),
    ]:
        result.loc[mask, "comments"] = result.loc[mask, "comments"].map(
            lambda value: append_reason(value, reason)
        )
    return result


def values_for_upload(df: pd.DataFrame) -> list[list[object]]:
    clean = df.astype(object).where(pd.notna(df), "")
    return [clean.columns.tolist(), *clean.values.tolist()]


def main() -> int:
    args = parse_args()
    folder_name = Path(args.pupae_batch_folder.rstrip("/\\")).name
    metadata = parse_batch_metadata(folder_name)
    if metadata.target_week not in WEEK_TO_SPREADSHEET_ID:
        known = ", ".join(map(str, sorted(WEEK_TO_SPREADSHEET_ID)))
        raise ValueError(
            f"Week {metadata.target_week} has no configured spreadsheet ID "
            f"(configured weeks: {known})."
        )

    print(
        f"Batch: {folder_name}\n"
        f"Derived year: {metadata.year}\n"
        f"Derived target week: {metadata.target_week}"
    )
    pupae_raw = read_pupae_counts(folder_name)
    pupae = prepare_pupae_counts(pupae_raw, folder_name, metadata.year)

    client = get_gspread_client()
    spreadsheet = client.open_by_key(WEEK_TO_SPREADSHEET_ID[metadata.target_week])
    worksheet = spreadsheet.worksheet(WORKSHEET_TITLE)
    sheet_raw = pd.DataFrame(worksheet.get_all_records())
    sheet = prepare_sheet(sheet_raw, metadata.year)
    final_df, unmatched = merge_pupae_counts(sheet, pupae)

    safe_count = len(pupae) - len(unmatched)
    print(f"Connected to: {spreadsheet.title}")
    print(f"Pupae rows with safe sheet match: {safe_count}/{len(pupae)}")
    if not unmatched.empty:
        print("Rows requiring manual review:")
        print(
            unmatched[
                ["pupae_source_row", "dataset", "pupae_merge_safety_reason"]
            ].to_string(index=False)
        )

    final_df = append_manual_review_rows(final_df, unmatched)
    final_df = flag_void_pupae_counts(final_df)

    if args.dry_run:
        print("Dry run complete; the Google Sheet was not changed.")
        return 0

    worksheet.clear()
    worksheet.update(values_for_upload(final_df), "A1")
    print(f"Updated {spreadsheet.title!r}, worksheet {WORKSHEET_TITLE!r}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, ValueError, gspread.GSpreadException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
