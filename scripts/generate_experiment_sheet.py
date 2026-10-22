#!/usr/bin/env python3

import argparse
import csv
import re
import sys
import zipfile
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Sequence
from xml.etree import ElementTree as ET


CANONICAL_COLUMNS = [
    "experimenter",
    "collector",
    "incubator",
    "shelf",
    "rack",
    "plugcamera",
    "condition",
    "condition_comments",
    "Other name",
    "location",
    "staging_date",
    "date",
    "time",
    "amendments",
    "comments",
    "recording_time",
    "staging_times",
    "Pupae",
    "pupae_batch_folder",
    "mon_pm_mortality_n",
    "mon_removed_eggs_binary",
    "tues_am_mortality_n",
    "tues_am_removed_eggs_binary",
    "tues_pm_mortality_n",
    "tues_removed_pm_eggs_binary",
    "weds_am_mortality_n",
    "weds_am_removed_eggs_binary",
    "weds_pm_mortality_n",
    "weds_pm_removed_eggs_binary",
    "thurs_am_mortality_n",
    "thurs_am_removed_eggs_binary",
    "thurs_pm_mortality_n",
    "thurs_pm_removed_eggs_binary",
    "fri_am_mortality_n",
    "fri_am_removed_eggs_binary",
    "fri_pm_mortality_n",
    "fri_pm_removed_eggs_binary",
    "week",
    "staging_date_filled",
    "staging_date_clean",
    "staging_date_clean_dt",
    "last_edit",
]

INPUT_KEY_MAP = {
    "condition": "condition",
    "Condition": "condition",
    "location": "location",
    "Location": "location",
    "plugcamera": "plugcamera",
    "Plugcamera": "plugcamera",
    "plug_camera": "plugcamera",
    "other name": "Other name",
    "Other name": "Other name",
    "other_name": "Other name",
    "date": "date",
    "Date": "date",
    "time": "time",
    "Time": "time",
}

XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
ROUND_TIMES = ("night", "day")
DEFAULT_ROUND_COUNT = 6
RepeatMode = Literal["auto", "always", "never"]


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def read_xlsx_rows(path: Path) -> List[Dict[str, str]]:
    with zipfile.ZipFile(path) as workbook:
        shared_strings = _read_shared_strings(workbook)
        sheet_path = _first_sheet_path(workbook)
        root = ET.fromstring(workbook.read(sheet_path))
        rows = root.find("a:sheetData", XLSX_NS)
        if rows is None:
            return []

        parsed_rows = [_extract_xlsx_row(row, shared_strings) for row in rows.findall("a:row", XLSX_NS)]
        parsed_rows = [row for row in parsed_rows if any(value.strip() for value in row.values())]
        if not parsed_rows:
            return []

        header = parsed_rows[0]
        data_rows = []
        for row in parsed_rows[1:]:
            data_rows.append(
                {
                    header.get(column, column): value
                    for column, value in row.items()
                    if header.get(column, "").strip()
                }
            )
        return data_rows


def _read_shared_strings(workbook: zipfile.ZipFile) -> List[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []

    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    strings = []
    for item in root.findall("a:si", XLSX_NS):
        text = "".join(node.text or "" for node in item.iterfind(".//a:t", XLSX_NS))
        strings.append(text)
    return strings


def _first_sheet_path(workbook: zipfile.ZipFile) -> str:
    wb = ET.fromstring(workbook.read("xl/workbook.xml"))
    rels = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    first_sheet = wb.find("a:sheets/a:sheet", XLSX_NS)
    if first_sheet is None:
        raise ValueError("Workbook does not contain any sheets.")
    rel_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    return f"xl/{rel_map[rel_id]}"


def _extract_xlsx_row(row: ET.Element, shared_strings: List[str]) -> Dict[str, str]:
    parsed = OrderedDict()
    for cell in row.findall("a:c", XLSX_NS):
        ref = cell.attrib.get("r", "")
        col = "".join(char for char in ref if char.isalpha())
        value_node = cell.find("a:v", XLSX_NS)
        if value_node is None:
            parsed[col] = ""
            continue

        value = value_node.text or ""
        if cell.attrib.get("t") == "s":
            parsed[col] = shared_strings[int(value)]
        else:
            parsed[col] = value
    return parsed


def sheet_values_to_rows(values: Sequence[Sequence[object]]) -> List[Dict[str, str]]:
    if not values:
        return []

    header = [str(value).strip() for value in values[0]]
    rows = []
    for values_row in values[1:]:
        row = {
            key: str(values_row[index]).strip()
            for index, key in enumerate(header)
            if key and index < len(values_row) and values_row[index] not in (None, "")
        }
        if any(value for value in row.values()):
            rows.append(row)
    return rows


def rows_to_sheet_values(rows: Iterable[Dict[str, str]]) -> List[List[str]]:
    return [
        CANONICAL_COLUMNS,
        *[[str(row.get(column, "")) for column in CANONICAL_COLUMNS] for row in rows],
    ]


def read_google_sheet_rows(
    spreadsheet_id: str,
    sheet_range: str,
    credentials_path: Path,
) -> List[Dict[str, str]]:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
    service = build("sheets", "v4", credentials=creds)
    response = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=sheet_range)
        .execute()
    )
    return sheet_values_to_rows(response.get("values", []))


def read_input_rows(path: Path) -> List[Dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv_rows(path)
    if suffix == ".xlsx":
        return read_xlsx_rows(path)
    raise ValueError(f"Unsupported input type: {path.suffix}")


def normalise_input_row(row: Dict[str, str]) -> Dict[str, str]:
    normalised = {}
    for key, value in row.items():
        clean_key = key.strip() if isinstance(key, str) else key
        mapped_key = INPUT_KEY_MAP.get(clean_key, clean_key)
        normalised[mapped_key] = value.strip() if isinstance(value, str) else value
    return normalised


def extract_reference_date(reference):
    reference_text = str(reference)
    reference_name = Path(reference_text).name
    match = FILENAME_DATE_RE.search(reference_name) or FILENAME_DATE_RE.search(reference_text)
    if match is None:
        raise ValueError(
            f"Could not find a YYYY-MM-DD date in the reference name: {reference_text}"
        )
    return datetime.strptime(match.group(1), "%Y-%m-%d").date()


def extract_filename_date(path: Path):
    return extract_reference_date(path)


def format_staging_label(start_date, include_next_day: bool) -> str:
    if not include_next_day:
        return f"{start_date:%d/%m/%Y}"

    end_date = start_date + timedelta(days=1)
    if start_date.month == end_date.month and start_date.year == end_date.year:
        return f"{start_date:%d}-{end_date:%d/%m/%Y}"
    if start_date.year == end_date.year:
        return f"{start_date:%d/%m}-{end_date:%d/%m/%Y}"
    return f"{start_date:%d/%m/%Y}-{end_date:%d/%m/%Y}"


def build_round_schedule(
    reference_name,
    staging_start_offset: int,
    rounds: int,
) -> List[Dict[str, str]]:
    base_date = extract_reference_date(reference_name)
    first_date = base_date + timedelta(days=staging_start_offset)
    schedule = []

    for round_index in range(rounds):
        time = ROUND_TIMES[round_index % len(ROUND_TIMES)]
        round_date = first_date + timedelta(days=(round_index + 1) // 2)
        schedule.append(
            {
                "staging_date": format_staging_label(
                    round_date,
                    include_next_day=time == "night",
                ),
                "date": f"{round_date:%d-%m}",
                "time": time,
                "staging_date_filled": "TRUE",
                "staging_date_clean": f"{round_date:%d/%m/%Y}",
                "staging_date_clean_dt": f"{round_date:%Y-%m-%d}",
            }
        )

    return schedule


def health_check_columns() -> List[str]:
    return [
        column
        for column in CANONICAL_COLUMNS
        if column.endswith("_mortality_n")
        or ("removed" in column and "eggs_binary" in column)
    ]


def condition_sequence(rows: List[Dict[str, str]]) -> List[str]:
    return [
        str(normalise_input_row(row).get("condition", "")).strip().lower()
        for row in rows
    ]


def repeated_conditions(rows: Iterable[Dict[str, str]]) -> Dict[str, int]:
    counts = OrderedDict()
    display_names = OrderedDict()

    for row in rows:
        condition = str(normalise_input_row(row).get("condition", "")).strip()
        if not condition:
            continue

        key = condition.casefold()
        counts[key] = counts.get(key, 0) + 1
        display_names.setdefault(key, condition)

    return {
        display_names[key]: count
        for key, count in counts.items()
        if count > 1
    }


def has_round_labels(rows: List[Dict[str, str]]) -> bool:
    labels = set()
    for row in rows:
        normalised = normalise_input_row(row)
        label = (
            str(normalised.get("staging_date", "")).strip(),
            str(normalised.get("date", "")).strip(),
            str(normalised.get("time", "")).strip(),
        )
        if any(label):
            labels.add(label)
    return len(labels) > 1


def looks_like_complete_week(rows: List[Dict[str, str]], rounds: int) -> bool:
    if not rows or rounds <= 1 or len(rows) % rounds != 0 or not has_round_labels(rows):
        return False

    chunk_size = len(rows) // rounds
    first_sequence = condition_sequence(rows[:chunk_size])
    if not any(first_sequence):
        return False

    return all(
        condition_sequence(rows[index : index + chunk_size]) == first_sequence
        for index in range(chunk_size, len(rows), chunk_size)
    )


def should_repeat_source(
    source_rows: List[Dict[str, str]],
    rounds: int,
    repeat_source: RepeatMode,
) -> bool:
    if repeat_source == "always":
        return True
    if repeat_source == "never":
        return False
    return not looks_like_complete_week(source_rows, rounds)


def source_schedule_index(source_index: int, row_count: int, rounds: int) -> int:
    if row_count == 0 or rounds <= 1:
        return 0
    chunk_size = max((row_count + rounds - 1) // rounds, 1)
    return min(source_index // chunk_size, rounds - 1)


def build_row(
    source_row: Dict[str, str],
    schedule: Dict[str, str],
    plugcamera: str,
    timestamp: str,
    prefill_health_value: str,
) -> Dict[str, str]:
    row = {column: "" for column in CANONICAL_COLUMNS}
    normalised = normalise_input_row(source_row)

    for key, value in normalised.items():
        if key in row and value not in (None, ""):
            row[key] = value

    if plugcamera:
        row["plugcamera"] = plugcamera

    row.update(schedule)

    for column in health_check_columns():
        if prefill_health_value and not row.get(column):
            row[column] = prefill_health_value

    if not row.get("last_edit"):
        row["last_edit"] = timestamp

    return row


def build_output_rows(
    source_rows: Iterable[Dict[str, str]],
    reference_name,
    plugcamera_start: int,
    staging_start_offset: int,
    rounds: int = DEFAULT_ROUND_COUNT,
    repeat_source: RepeatMode = "auto",
    prefill_health_value: str = "n/d",
) -> List[Dict[str, str]]:
    source_rows = list(source_rows)
    output_rows = []
    next_plugcamera = plugcamera_start
    timestamp = datetime.now().isoformat(timespec="seconds")
    schedule = build_round_schedule(reference_name, staging_start_offset, rounds)

    if should_repeat_source(source_rows, rounds, repeat_source):
        for schedule_row in schedule:
            for source_row in source_rows:
                normalised = normalise_input_row(source_row)
                plugcamera = normalised.get("plugcamera") or str(next_plugcamera)
                if not normalised.get("plugcamera"):
                    next_plugcamera += 1
                output_rows.append(
                    build_row(
                        source_row,
                        schedule_row,
                        plugcamera,
                        timestamp,
                        prefill_health_value,
                    )
                )
    else:
        for index, source_row in enumerate(source_rows):
            normalised = normalise_input_row(source_row)
            plugcamera = normalised.get("plugcamera") or str(next_plugcamera)
            if not normalised.get("plugcamera"):
                next_plugcamera += 1
            output_rows.append(
                build_row(
                    source_row,
                    schedule[source_schedule_index(index, len(source_rows), rounds)],
                    plugcamera,
                    timestamp,
                    prefill_health_value,
                )
            )

    return output_rows


def write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a standard experiment CSV from a weekly CSV/XLSX condition sheet."
    )
    parser.add_argument("input_file", type=Path, help="Weekly input file (.csv or .xlsx)")
    parser.add_argument("output_file", type=Path, help="Path for the generated CSV")
    parser.add_argument(
        "--plugcamera-start",
        type=int,
        default=1,
        help="Starting value for generated plugcamera numbers when the input lacks them",
    )
    parser.add_argument(
        "--staging-start-offset",
        type=int,
        default=8,
        help="Days after the filename date to start the first experiment round",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUND_COUNT,
        help="Number of experiment rounds to generate",
    )
    parser.add_argument(
        "--repeat-source",
        choices=["auto", "always", "never"],
        default="auto",
        help=(
            "Whether to repeat the input rows for each round. "
            "'auto' repeats one-round templates and avoids repeating sheets "
            "that already look like complete repeated weeks."
        ),
    )
    parser.add_argument(
        "--prefill-health-value",
        default="n/d",
        help=(
            "Value to put in blank mortality and egg-removal columns. "
            "Use an empty string to leave them blank."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_rows = read_input_rows(args.input_file)
    output_rows = build_output_rows(
        source_rows,
        args.input_file,
        args.plugcamera_start,
        args.staging_start_offset,
        args.rounds,
        args.repeat_source,
        args.prefill_health_value,
    )
    write_csv(args.output_file, output_rows)
    print(f"Wrote {len(output_rows)} rows to {args.output_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
