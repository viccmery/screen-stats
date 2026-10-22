import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).parents[1] / "scripts" / "pupae_counting.py"
SPEC = importlib.util.spec_from_file_location("pupae_counting", SCRIPT)
pupae_counting = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = pupae_counting
SPEC.loader.exec_module(pupae_counting)


class ParseBatchMetadataTests(unittest.TestCase):
    def test_parses_supported_week_separators(self):
        examples = {
            "VM_2026-06-26_VRDN-screen_week1_batch5_f12": (2026, 1),
            "VM_2026-02-10-mechano-week-3_batch11_f32": (2026, 3),
            "LK_2025-12-11_split_week18-pupae": (2025, 18),
        }
        for folder, expected in examples.items():
            with self.subTest(folder=folder):
                metadata = pupae_counting.parse_batch_metadata(folder)
                self.assertEqual((metadata.year, metadata.target_week), expected)

    def test_rejects_missing_week(self):
        with self.assertRaisesRegex(ValueError, "exactly one week"):
            pupae_counting.parse_batch_metadata("VM_2026-06-26_VRDN-screen")

    def test_rejects_ambiguous_week(self):
        with self.assertRaisesRegex(ValueError, "exactly one week"):
            pupae_counting.parse_batch_metadata("VM_2026-01-30_week1-week2")

    def test_rejects_missing_year(self):
        with self.assertRaisesRegex(ValueError, "four-digit year"):
            pupae_counting.parse_batch_metadata("VM_VRDN-screen_week1")


class MergePupaeCountsTests(unittest.TestCase):
    def setUp(self):
        self.sheet = pd.DataFrame(
            {
                "condition": ["control"],
                "staging_date": ["01/01/2026"],
                "Pupae": [""],
                "pupae_batch_folder": [""],
                "last_edit": [""],
                "date": ["01-01"],
                "time": ["day"],
            }
        )
        self.pupae = pd.DataFrame(
            {
                "condition": ["control"],
                "date": ["01-01"],
                "time": ["day"],
                "Pupae": [12],
                "dataset": ["control_01-01_day_L2"],
                "pupae_batch_folder": ["batch"],
                "last_edit": ["01-01-2026"],
                "pupae_source_row": [1],
                "pupae_count": [10],
            }
        )

    def test_merge_returns_unmatched_rows_separately(self):
        self.sheet.loc[0, "Pupae"] = 11

        final_df, unmatched = pupae_counting.merge_pupae_counts(
            self.sheet, self.pupae
        )

        self.assertEqual(len(final_df), 1)
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(
            unmatched.iloc[0]["pupae_merge_safety_reason"],
            "existing Pupae already present",
        )

    def test_upload_contains_only_sheet_and_tracking_columns(self):
        final_df, unmatched = pupae_counting.merge_pupae_counts(
            self.sheet, self.pupae
        )

        self.assertTrue(unmatched.empty)
        self.assertEqual(len(final_df), 1)
        self.assertEqual(final_df.iloc[0]["Pupae"], 12)
        self.assertEqual(final_df.iloc[0]["pupae_batch_folder"], "batch")
        self.assertNotIn("dataset", final_df.columns)
        self.assertNotIn("pupae_source_row", final_df.columns)
        self.assertFalse(
            any(column.endswith("_from_pupae") for column in final_df.columns)
        )

    def test_prepare_sheet_removes_legacy_columns_and_appended_rows(self):
        polluted = pd.concat(
            [
                self.sheet.assign(
                    dataset="", raw_sheet_matches_from_pupae=""
                ),
                pd.DataFrame(
                    {
                        "condition": ["control"],
                        "staging_date": [""],
                        "Pupae": [12],
                        "dataset": ["control_01-01_day_L2"],
                        "pupae_source_row": [1],
                        "pupae_batch_folder": ["batch"],
                        "raw_sheet_matches_from_pupae": [1],
                    }
                ),
            ],
            ignore_index=True,
        )

        cleaned = pupae_counting.prepare_sheet(polluted, 2026)

        self.assertEqual(len(cleaned), 1)
        self.assertNotIn("dataset", cleaned.columns)
        self.assertNotIn("raw_sheet_matches_from_pupae", cleaned.columns)


class ManualReviewRowsTests(unittest.TestCase):
    setUp = MergePupaeCountsTests.setUp

    def test_upload_appends_review_row_with_count_filename_and_reason(self):
        self.sheet.loc[0, "Pupae"] = 11
        merged, unmatched = pupae_counting.merge_pupae_counts(self.sheet, self.pupae)
        final = pupae_counting.append_manual_review_rows(merged, unmatched)
        self.assertEqual(len(final), 2)
        self.assertEqual(final["Pupae"].tolist(), [11, 12])
        self.assertEqual(final.iloc[-1]["dataset"], "control_01-01_day_L2")
        self.assertEqual(final.iloc[-1]["manual_inspection_reason"],
                         "existing Pupae already present")
        upload = pupae_counting.values_for_upload(final)
        self.assertEqual(len(upload), 3)  # header, original row, review row
        self.assertNotIn("safe_for_pupae_merge", upload[0])

    def test_successful_match_does_not_append_review_rows(self):
        merged, unmatched = pupae_counting.merge_pupae_counts(self.sheet, self.pupae)
        final = pupae_counting.append_manual_review_rows(merged, unmatched)
        pd.testing.assert_frame_equal(final, merged)


class WeeklyIdMatchingTests(unittest.TestCase):
    setUp = MergePupaeCountsTests.setUp
    def prepare_counts(self, *names):
        return pupae_counting.prepare_pupae_counts(
            pd.DataFrame({"dataset": list(names), "pupae_count": [10] * len(names)}),
            "batch", 2026,
        )

    def test_sheet_without_staging_date_keeps_date_and_time(self):
        raw = self.sheet.drop(columns="staging_date").assign(weekly_id=7)
        result = pupae_counting.prepare_sheet(raw, 2026)
        self.assertEqual(result.loc[0, "date"], "01-01")
        self.assertEqual(result.loc[0, "time"], "day")
        self.assertEqual(result.loc[0, "weekly_id"], "7")

    def test_staging_only_fills_blanks(self):
        raw = self.sheet.assign(date="02-01", time="night")
        result = pupae_counting.prepare_sheet(raw, 2026)
        self.assertEqual(result.loc[0, "date"], "02-01")
        self.assertEqual(result.loc[0, "time"], "night")
        raw = self.sheet.assign(date="", time="", staging_date="1-2/01/2026")
        result = pupae_counting.prepare_sheet(raw, 2026)
        self.assertEqual(result.loc[0, "date"], "01-01")
        self.assertEqual(result.loc[0, "time"], "night")

    def test_numeric_and_explicit_id_filenames_resolve_condition(self):
        sheet = self.sheet.assign(weekly_id=7.0)
        for name in ["7_1-1_day_L2", "weekly_id-7_01-01_day_L2"]:
            with self.subTest(name=name):
                counts = self.prepare_counts(name)
                self.assertTrue(pd.isna(counts.loc[0, "condition"]))
                final, unmatched = pupae_counting.merge_pupae_counts(sheet, counts)
                self.assertTrue(unmatched.empty)
                self.assertEqual(final.loc[0, "condition"], "control")
                self.assertEqual(final.loc[0, "Pupae"], 12)

    def test_condition_does_not_fall_back_to_csv_weekly_id(self):
        sheet = self.sheet.assign(weekly_id="7")
        counts = self.prepare_counts("unknown_01-01_day_L2").assign(weekly_id="7")
        final, unmatched = pupae_counting.merge_pupae_counts(sheet, counts)
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(final.loc[0, "Pupae"], "")

    def test_condition_wins_when_both_columns_present(self):
        counts = self.prepare_counts("control_01-01_day_L2").assign(weekly_id="999")
        final, unmatched = pupae_counting.merge_pupae_counts(
            self.sheet.assign(weekly_id="7"), counts
        )
        self.assertTrue(unmatched.empty)
        self.assertEqual(final.loc[0, "Pupae"], 12)

    def test_duplicate_weekly_ids_do_not_match(self):
        sheet = pd.concat([self.sheet, self.sheet.assign(condition="split-2")], ignore_index=True)
        sheet["weekly_id"] = "7"
        final, unmatched = pupae_counting.merge_pupae_counts(
            sheet, self.prepare_counts("7_01-01_day_L2")
        )
        self.assertEqual(len(unmatched), 1)
        self.assertIn("duplicate weekly_id", unmatched.iloc[0]["pupae_merge_safety_reason"])
        self.assertTrue(final["Pupae"].eq("").all())

    def test_weekly_ids_can_be_reused_on_other_dates(self):
        sheet = pd.concat([self.sheet, self.sheet.assign(date="02-01")], ignore_index=True)
        sheet["weekly_id"] = "7"
        final, unmatched = pupae_counting.merge_pupae_counts(
            sheet, self.prepare_counts("7_02-01_day_L2")
        )
        self.assertTrue(unmatched.empty)
        self.assertEqual(final["Pupae"].tolist(), ["", 12])

    def test_condition_and_weekly_id_collision_requires_review(self):
        final, unmatched = pupae_counting.merge_pupae_counts(
            self.sheet.assign(weekly_id="7"),
            self.prepare_counts("control_01-01_day_L2", "7_01-01_day_L2"),
        )
        self.assertEqual(len(unmatched), 2)
        self.assertEqual(final.loc[0, "Pupae"], "")

    def test_id_does_not_overwrite_existing_count(self):
        final, unmatched = pupae_counting.merge_pupae_counts(
            self.sheet.assign(weekly_id="7", Pupae=15),
            self.prepare_counts("7_01-01_day_L2"),
        )
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(final.loc[0, "Pupae"], 15)

    def test_missing_keys_do_not_match_nulls(self):
        final, unmatched = pupae_counting.merge_pupae_counts(
            self.sheet.assign(weekly_id=pd.NA),
            self.pupae.assign(condition=pd.NA, weekly_id=pd.NA),
        )
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(final.loc[0, "Pupae"], "")

    def test_duplicate_condition_rows_elsewhere_do_not_break_merge(self):
        sheet = pd.concat([self.sheet, self.sheet.assign(condition="other"),
                           self.sheet.assign(condition="other")], ignore_index=True)
        final, unmatched = pupae_counting.merge_pupae_counts(sheet, self.pupae)
        self.assertTrue(unmatched.empty)
        self.assertEqual(len(final), 3)
        self.assertEqual(final["Pupae"].tolist(), [12, "", ""])

    def test_weekly_ids_remain_scoped_to_time(self):
        sheet = pd.concat([self.sheet, self.sheet.assign(time="night")], ignore_index=True)
        sheet["weekly_id"] = "7"
        final, unmatched = pupae_counting.merge_pupae_counts(
            sheet, self.prepare_counts("7_01-01_night_L2")
        )
        self.assertTrue(unmatched.empty)
        self.assertEqual(final["Pupae"].tolist(), ["", 12])

    def test_unparseable_filename_requires_review(self):
        with self.assertRaisesRegex(ValueError, "source row"):
            self.prepare_counts("no-condition-date-or-id_L2")

    def test_invalid_calendar_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "source row"):
            self.prepare_counts("7_31-02_day_L2")

    def test_duplicate_id_counts_do_not_expand_sheet(self):
        final, unmatched = pupae_counting.merge_pupae_counts(
            self.sheet.assign(weekly_id="7"),
            self.prepare_counts("7_01-01_day_L2", "7_01-01_day_L3"),
        )
        self.assertEqual(len(final), 1)
        self.assertEqual(len(unmatched), 2)
        self.assertEqual(final.loc[0, "Pupae"], "")

    def test_actual_week_seven_alphanumeric_filename(self):
        sheet = self.sheet.assign(weekly_id=" b2 ", date="29-07", time="night")
        counts = self.prepare_counts("B2_29-07_night_L0.mp4.json")
        self.assertTrue(pd.isna(counts.loc[0, "condition"]))
        self.assertEqual(counts.loc[0, "weekly_id"], "b2")
        final, unmatched = pupae_counting.merge_pupae_counts(sheet, counts)
        self.assertTrue(unmatched.empty)
        self.assertEqual(final.loc[0, "condition"], "control")
        self.assertEqual(final.loc[0, "Pupae"], 10)

    def test_alphanumeric_id_is_local_to_supplied_weekly_sheet(self):
        counts = self.prepare_counts("B2_29-07_night_L0.mp4.json")
        week_seven = self.sheet.assign(weekly_id="b2", date="29-07", time="night")
        week_eight = week_seven.assign(condition="split-2")
        first, _ = pupae_counting.merge_pupae_counts(week_seven, counts)
        second, _ = pupae_counting.merge_pupae_counts(week_eight, counts)
        self.assertEqual(first.loc[0, "condition"], "control")
        self.assertEqual(second.loc[0, "condition"], "split-2")

    def test_condition_filename_retains_full_condition(self):
        counts = self.prepare_counts("split-2_29-07_night_L0.mp4.json")
        self.assertEqual(counts.loc[0, "condition"], "split-2")
        self.assertTrue(pd.isna(counts.loc[0, "weekly_id"]))


class VoidPupaeCountsTests(unittest.TestCase):
    def test_thresholds_existing_comments_and_missing_counts(self):
        raw = pd.DataFrame({
            "Pupae": [99, 100, 250, 251, "", None, "not counted", "80"],
            "amendments": [0] * 8,
            "comments": ["changed pi", "keep", "keep", "changed pi", "", "", "", ""],
        })
        final = pupae_counting.flag_void_pupae_counts(raw)
        self.assertEqual(final["amendments"].tolist(), [-1, 0, 0, -1, 0, 0, 0, -1])
        self.assertEqual(final["comments"].tolist(), [
            "changed pi, not enough pupae", "keep", "keep", "changed pi, too many pupae",
            "", "", "", "not enough pupae",
        ])
        self.assertEqual(raw.loc[0, "comments"], "changed pi")

    def test_creates_missing_columns_and_does_not_repeat_reasons(self):
        raw = pd.DataFrame({"Pupae": [50, 300]})
        first = pupae_counting.flag_void_pupae_counts(raw)
        second = pupae_counting.flag_void_pupae_counts(first)
        pd.testing.assert_frame_equal(first, second)
        self.assertEqual(first["comments"].tolist(), ["not enough pupae", "too many pupae"])
        self.assertEqual(first["amendments"].tolist(), [-1, -1])

    def test_handles_nullable_text_columns_and_missing_comments(self):
        raw = pd.DataFrame({
            "Pupae": [251, 99, 300],
            "amendments": pd.Series(["0", "", "1"], dtype="string"),
            "comments": pd.Series([pd.NA, "", "changed pi, Too Many Pupae"], dtype="string"),
        })
        final = pupae_counting.flag_void_pupae_counts(raw)
        self.assertEqual(final["amendments"].tolist(), [-1, -1, -1])
        self.assertEqual(final["comments"].tolist(), [
            "too many pupae", "not enough pupae", "changed pi, Too Many Pupae",
        ])

    def test_applies_to_appended_review_rows(self):
        fixture = MergePupaeCountsTests()
        fixture.setUp()
        fixture.sheet.loc[0, "Pupae"] = 150
        fixture.sheet["comments"] = "changed pi"
        fixture.pupae.loc[0, "Pupae"] = 300
        merged, unmatched = pupae_counting.merge_pupae_counts(fixture.sheet, fixture.pupae)
        final = pupae_counting.flag_void_pupae_counts(
            pupae_counting.append_manual_review_rows(merged, unmatched)
        )
        self.assertEqual(final.iloc[0]["comments"], "changed pi")
        self.assertEqual(final.iloc[-1]["amendments"], -1)
        self.assertEqual(final.iloc[-1]["comments"], "too many pupae")


if __name__ == "__main__":
    unittest.main()
