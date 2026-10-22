#!/usr/bin/env python3

import argparse
import csv
import sys
from pathlib import Path
from typing import List

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update a Google Sheet from a CSV file."
    )
    parser.add_argument("csv_file", type=Path, help="Canonical CSV to upload")
    parser.add_argument(
        "--credentials",
        type=Path,
        required=True,
        help="Path to a Google service account JSON credentials file",
    )
    parser.add_argument(
        "--spreadsheet-id",
        help="Existing spreadsheet ID to update. If omitted, a new spreadsheet is created.",
    )
    parser.add_argument(
        "--spreadsheet-title",
        default="Experiment Sheet",
        help="Spreadsheet title to use when creating a new sheet",
    )
    parser.add_argument(
        "--worksheet-title",
        default="Sheet1",
        help="Tab title to use for the uploaded CSV",
    )
    parser.add_argument(
        "--share-with",
        action="append",
        default=[],
        help="Email address to share the spreadsheet with. Repeat for multiple recipients.",
    )
    parser.add_argument(
        "--share-role",
        choices=["writer", "reader", "commenter"],
        default="writer",
        help="Permission role used with --share-with",
    )
    return parser.parse_args()


def build_services(credentials_path: Path):
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    sheets_service = build("sheets", "v4", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    return sheets_service, drive_service


def read_csv_values(path: Path) -> List[List[str]]:
    with path.open(newline="") as handle:
        return [row for row in csv.reader(handle)]


def create_spreadsheet(sheets_service, title: str) -> str:
    body = {"properties": {"title": title}}
    response = sheets_service.spreadsheets().create(body=body).execute()
    return response["spreadsheetId"]


def get_sheet_metadata(sheets_service, spreadsheet_id: str) -> dict:
    return sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()


def ensure_first_sheet_title(
    sheets_service,
    spreadsheet_id: str,
    worksheet_title: str,
    column_count: int,
) -> int:
    metadata = get_sheet_metadata(sheets_service, spreadsheet_id)
    first_sheet = metadata["sheets"][0]
    sheet_id = first_sheet["properties"]["sheetId"]
    current_title = first_sheet["properties"]["title"]

    requests = []
    if current_title != worksheet_title:
        requests.append(
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "title": worksheet_title,
                    },
                    "fields": "title",
                }
            }
        )

    requests.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }
    )
    requests.append(
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": max(column_count, 1),
                }
            }
        }
    )

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()
    return sheet_id


def replace_sheet_values(sheets_service, spreadsheet_id: str, worksheet_title: str, values: List[List[str]]) -> None:
    clear_range = f"'{worksheet_title}'"
    sheets_service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=clear_range,
        body={},
    ).execute()

    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{worksheet_title}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def share_spreadsheet(drive_service, spreadsheet_id: str, email: str, role: str) -> None:
    drive_service.permissions().create(
        fileId=spreadsheet_id,
        body={
            "type": "user",
            "role": role,
            "emailAddress": email,
        },
        fields="id",
        sendNotificationEmail=False,
    ).execute()


def main() -> int:
    args = parse_args()
    values = read_csv_values(args.csv_file)
    if not values:
        raise ValueError("The CSV file is empty.")

    sheets_service, drive_service = build_services(args.credentials)
    spreadsheet_id = args.spreadsheet_id or create_spreadsheet(
        sheets_service,
        args.spreadsheet_title,
    )
    ensure_first_sheet_title(
        sheets_service,
        spreadsheet_id,
        args.worksheet_title,
        column_count=len(values[0]),
    )
    replace_sheet_values(sheets_service, spreadsheet_id, args.worksheet_title, values)

    for email in args.share_with:
        share_spreadsheet(drive_service, spreadsheet_id, email, args.share_role)

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    print(f"Spreadsheet ready: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
