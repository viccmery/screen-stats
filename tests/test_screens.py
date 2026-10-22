from pathlib import Path
import tempfile
import unittest

import screens


class ScreenInventoryTests(unittest.TestCase):
    def test_actual_name_variants(self):
        for name, subgroup, week in [
            ("VM_2026-08-07_VRDN-screen-week6_batch5_f41", "vrdn", "6"),
            ("LK_2026-02-27-mechano-week-5_batch5_f19", "mechano", "5"),
            ("LK_2026-04-15_split-sensory-top-up-week-2_batch1_f31", "split-sensory-top-up", "2"),
            ("VM_2026-04-27_mechano-screen-week-11.1_batch1_f10", "mechano", "11.1"),
        ]:
            with self.subTest(name=name):
                parsed = screens.parse_folder_name(name)
                self.assertEqual(parsed["screen"], subgroup)
                self.assertEqual(parsed["week"], week)

    def test_invalid_or_ambiguous_dates_are_not_selected(self):
        for name in ["VM_2026-02-30_mechano-week1", "VM_2026-01-01_2025-02-02_mechano-week1",
                     "VM_2026-01-01_mechano-week1-week2"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                screens.parse_folder_name(name)

    def test_raw_and_csv_readiness_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "VM_2026-08-07_VRDN-screen-week6_batch5_f41"
            raw = folder / "pupae" / "raw_data"
            predictions = folder / "pupae" / "predictions"
            raw.mkdir(parents=True)
            predictions.mkdir()
            (folder / ".DS_Store").write_bytes(b"metadata")
            self.assertEqual(screens.inspect_folder(folder)["status"], "empty")
            (raw / "zero.mp4").touch()
            self.assertFalse(screens.inspect_folder(folder)["raw_ready"])
            (raw / "recording.mp4").write_bytes(b"recording")
            self.assertEqual(screens.inspect_folder(folder)["status"], "raw_only")
            counts = predictions / "pupae_counts.csv"
            counts.write_text("dataset,pupae_count\n")
            self.assertEqual(screens.inspect_folder(folder)["status"], "csv_needs_attention")
            counts.write_text("dataset,pupae_count\nSS38036_23-07_night_L0.mp4.json,175\n")
            result = screens.inspect_folder(folder)
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["raw_recordings"], 1)
            self.assertEqual(result["csv_rows"], 1)
            (raw / "recording.mp4").unlink()
            self.assertEqual(screens.inspect_folder(folder)["status"], "csv_only")
            (predictions / "extra.csv").write_text(counts.read_text())
            self.assertFalse(screens.inspect_folder(folder)["csv_ready"])

    def test_invalid_csv_does_not_hide_other_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for batch, contents in [(1, "dataset,pupae_count\ncontrol_31-02_day_L0,3\n"),
                                    (2, "dataset,pupae_count\ncontrol_01-02_day_L0,3\n")]:
                predictions = root / f"VM_2026-08-07_VRDN-screen-week6_batch{batch}" / "pupae" / "predictions"
                predictions.mkdir(parents=True)
                (predictions / "counts.csv").write_text(contents)
            (root / "other-experiment").mkdir()
            rows = screens.scan_instruments(root)
            self.assertEqual([r["status"] for r in rows], ["csv_needs_attention", "csv_only", "unrecognized"])


if __name__ == "__main__":
    unittest.main()
