# %%
# Run after the notebook's `dirs = {...}` cell.
from pathlib import Path

import pandas as pd


screen_folders = [
    Path(dirs[name])
    for name in ("mechano-screen", "split-screen", "top-up-screen")
]
output_csv = Path(dirs["fly-lines"]) / "all_screen_conditions_mapping.csv"

condition_names = []

for folder in screen_folders:
    for file in sorted(folder.rglob("*")):
        try:
            if file.suffix.lower() == ".csv":
                sheets = [pd.read_csv(file, dtype="string")]
            elif file.suffix.lower() in {".xlsx", ".xls"}:
                sheets = pd.read_excel(
                    file,
                    sheet_name=None,
                    dtype="string",
                ).values()
            else:
                continue

            for sheet in sheets:
                sheet.columns = sheet.columns.str.strip().str.lower()
                if "condition" in sheet.columns:
                    condition_names.extend(sheet["condition"].dropna())
        except Exception as error:
            print(f"Skipped {file.name}: {error}")

# Use a lowercase key to prevent repeats such as SS53257 and ss53257.
new = pd.DataFrame({"condition_new": condition_names})
new["condition_new"] = (
    new["condition_new"]
    .astype("string")
    .str.replace(r"\s+", " ", regex=True)
    .str.strip()
)
new = new[new["condition_new"].ne("")]
new["_key"] = new["condition_new"].str.casefold()
new = new.drop_duplicates("_key")

# Keep mappings already entered in the output CSV.
if output_csv.exists():
    existing = pd.read_csv(output_csv, dtype="string").fillna("")
    if "mapping" not in existing.columns:
        existing["mapping"] = ""

    existing["condition"] = existing["condition"].str.strip()
    existing["mapping"] = existing["mapping"].str.strip()
    existing["_key"] = existing["condition"].str.casefold()

    # Prefer the duplicate row that already has a mapping.
    existing["_mapped"] = existing["mapping"].ne("")
    existing = (
        existing.sort_values("_mapped", ascending=False)
        .drop_duplicates("_key")
        [["_key", "condition", "mapping"]]
    )
else:
    existing = pd.DataFrame(columns=["_key", "condition", "mapping"])

updated = new.merge(existing, on="_key", how="outer")
updated["condition"] = updated["condition"].replace("", pd.NA)
updated["condition"] = updated["condition"].fillna(updated["condition_new"])
updated["mapping"] = updated["mapping"].fillna("")
updated = (
    updated[["condition", "mapping"]]
    .sort_values("condition", key=lambda values: values.str.casefold())
    .reset_index(drop=True)
)

output_csv.parent.mkdir(parents=True, exist_ok=True)
updated.to_csv(output_csv, index=False)

print(f"Updated {output_csv} with {len(updated)} unique conditions.")
updated
