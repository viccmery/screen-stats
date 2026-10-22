# %%
from pathlib import Path
import sys

import pandas as pd


repo_root = Path.cwd()
if not (repo_root / "scripts").exists():
    repo_root = repo_root.parent

sys.path.append(str(repo_root / "scripts"))

from generate_experiment_sheet import (  # noqa: E402
    CANONICAL_COLUMNS,
    build_output_rows,
    read_google_sheet_rows,
    repeated_conditions,
    rows_to_sheet_values,
)


# %%
# Fill these in before running the notebook.
SPREADSHEET_ID = "PASTE_SOURCE_SPREADSHEET_ID_HERE"
SOURCE_RANGE = "'Sheet1'!A:ZZ"
CREDENTIALS = repo_root / "secrets/google-service-account.json"

# This can be the Google Sheet title, worksheet title, or any label containing
# the Monday reference date as YYYY-MM-DD.
REFERENCE_NAME = "2026-04-20_top-up-week-4_sensory-deprivation-week-2"


# %%
source_rows = read_google_sheet_rows(
    spreadsheet_id=SPREADSHEET_ID,
    sheet_range=SOURCE_RANGE,
    credentials_path=CREDENTIALS,
)

source_df = pd.DataFrame(source_rows)
source_df.head()


# %%
source_df[["collector", "condition"]].head(40)


# %%
duplicate_conditions = repeated_conditions(source_rows)

if duplicate_conditions:
    print("Repeated conditions found:")
    for condition, count in duplicate_conditions.items():
        print(f"- {condition}: {count}")
else:
    print("No repeated conditions found.")


# %%
generated_rows = build_output_rows(
    source_rows,
    REFERENCE_NAME,
    plugcamera_start=1,
    staging_start_offset=8,
    repeat_source="always",
    prefill_health_value="n/d",
)

generated_df = pd.DataFrame(generated_rows, columns=CANONICAL_COLUMNS)
generated_df.head()


# %%
generated_df.groupby(["date", "time"], sort=False).size()


# %%
generated_df[
    [
        "plugcamera",
        "collector",
        "condition",
        "date",
        "time",
        "mon_pm_mortality_n",
        "fri_pm_mortality_n",
    ]
].head(80)


# %%
# Optional: write the generated result back to a separate tab.
# Keep WRITE_BACK as False while exploring.
WRITE_BACK = False
DESTINATION_RANGE = "'generated-preview'!A1"

if WRITE_BACK:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    destination_tab = DESTINATION_RANGE.split("!")[0].strip("'")
    creds = Credentials.from_service_account_file(
        str(CREDENTIALS),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    service = build("sheets", "v4", credentials=creds)
    values = rows_to_sheet_values(generated_rows)
    metadata = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    existing_tabs = {
        sheet["properties"]["title"]
        for sheet in metadata.get("sheets", [])
    }

    if destination_tab not in existing_tabs:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": destination_tab}}}]},
        ).execute()

    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{destination_tab}'",
        body={},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=DESTINATION_RANGE,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
