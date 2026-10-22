# Google Sheets Workflow

This repo now has two small scripts:

1. `scripts/generate_experiment_sheet.py`
   Converts a weekly `.csv` or `.xlsx` experiment list into one canonical CSV with your fixed columns.
2. `scripts/sync_google_sheet.py`
   Creates or updates a Google Sheet from that canonical CSV.

## 1. Create a local Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-google-sheets.txt
```

## 2. Create Google credentials

Use a Google Cloud service account for the first version of this workflow.

1. Create or select a Google Cloud project.
2. Enable the Google Sheets API.
3. Enable the Google Drive API.
4. Create a service account.
5. Create a JSON key for that service account and download it.

Keep the JSON file outside git, or store it somewhere like `secrets/google-service-account.json`.

## 3. Share access

For an existing spreadsheet:

1. Open the target Google Sheet.
2. Share it with the service account email from the JSON file.

For a new spreadsheet:

1. Let the script create it.
2. Optionally pass `--share-with your_email@domain.com` so your Google account can open it right away.

## 4. Generate the canonical CSV

The generator can now start from a one-round ordered list of `collector` and
`condition` rows and expand it into the full six-round week.

- It looks for a `YYYY-MM-DD` date in the filename.
- It starts the first experiment round `8` days later by default.
- It repeats the source rows six times, preserving the source row order.
- It assigns consecutive `date` / `time` blocks:
  `night`, `day`, `night`, `day`, `night`, `day`.
- The date advances as:
  first Tuesday night, Wednesday day, Wednesday night, Thursday day,
  Thursday night, Friday day.
- It fills blank mortality and egg-removal columns with `n/d`.

Example:

```bash
python3 scripts/generate_experiment_sheet.py \
  "/Users/meryv/Downloads/2026-04-20_top-up-week-4_sensory-deprivation-week-2 - Sheet1.csv" \
  "final-sheets/2026-04-20_top-up-week-4_sensory-deprivation-week-2.csv"
```

For that filename date, the first round starts on `2026-04-28`, so the generated
rounds are:

```text
28-04 night
29-04 day
29-04 night
30-04 day
30-04 night
01-05 day
```

If your real start offset is `10` days rather than `8`, you can override it:

```bash
python3 scripts/generate_experiment_sheet.py \
  "/Users/meryv/Downloads/2026-04-20_top-up-week-4_sensory-deprivation-week-2 - Sheet1.csv" \
  "final-sheets/2026-04-20_top-up-week-4_sensory-deprivation-week-2.csv" \
  --staging-start-offset 10
```

By default, `--repeat-source auto` repeats one-round templates and avoids
repeating files that already look like complete six-round weeks. You can force a
choice with `--repeat-source always` or `--repeat-source never`.

## 5. Explore from a Google Sheet in a notebook

The original source sheet can stay in Google Sheets. Open
`notebooks/generate_experiment_sheet_exploration.py` as a notebook-style Python
file and fill in:

- `SPREADSHEET_ID`
- `SOURCE_RANGE`, for example `'Sheet1'!A:ZZ`
- `CREDENTIALS`
- `REFERENCE_NAME`, which just needs to contain the Monday date as `YYYY-MM-DD`

The notebook reads the source tab, generates the six-round sheet in memory, and
previews it as a DataFrame. It does not write back to Google Sheets unless you
set `WRITE_BACK = True`, and the write-back cell targets a separate
`generated-preview` tab by default, creating that tab if needed.

The source tab only needs a header row and the one-round ordered list. The
important columns are `collector` and `condition`; any matching extra columns
such as `experimenter`, `condition_comments`, `Other name`, or `location` will
be carried through.

## 6. Upload to Google Sheets

Create a new spreadsheet:

```bash
python3 scripts/sync_google_sheet.py \
  "final-sheets/2026-04-24_mechano-screen-week-13.csv" \
  --credentials "secrets/google-service-account.json" \
  --spreadsheet-title "2026-04-24 mechano screen week 13" \
  --worksheet-title "week-13" \
  --share-with "your.name@gmail.com"
```

Update an existing spreadsheet:

```bash
python3 scripts/sync_google_sheet.py \
  "final-sheets/2026-04-24_mechano-screen-week-13.csv" \
  --credentials "secrets/google-service-account.json" \
  --spreadsheet-id "YOUR_SPREADSHEET_ID" \
  --worksheet-title "week-13"
```

## Notes

- The upload script clears the first worksheet and rewrites it from `A1`.
- The first row is frozen automatically.
- Column widths are auto-resized.
- If you want this to become one command later, the next easy step is a wrapper script that runs generation and upload together.
