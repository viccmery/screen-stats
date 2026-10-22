from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.weekly_screen_stats import load_mapping, read_weekly_sheets, summarise, plot_successful


class WeeklyScreenStatsTests(unittest.TestCase):
    def test_aliases_zero_lines_and_unscored_trials(self):
        mapping = pd.DataFrame({"key": ["alias-a", "a", "b"], "line": ["a", "a", "b"]})
        actual = pd.DataFrame({
            "condition": [" ALIAS-A ", "A", "a", "a", "unknown"],
            "amendments": ["0", "-1", "", "bad", "0"],
            "week": ["2", "2", "10", "10", "10"],
        })
        counts, totals, unmapped = summarise(actual, mapping)
        totals = totals.set_index("line")
        self.assertEqual(totals.loc["a"].tolist(), [1, 1, 2])
        self.assertEqual(totals.loc["b"].tolist(), [0, 0, 0])
        self.assertEqual(unmapped, ["unknown"])
        self.assertEqual(len(counts), 6)
        _, legacy, _ = summarise(actual, mapping, blank_is_successful=True)
        self.assertEqual(legacy.set_index("line").loc["a", "successful"], 2)
        import matplotlib.pyplot as plt
        fig, ax = plot_successful(counts, "Test")
        self.assertEqual([t.get_text() for t in ax.get_xticklabels()], ["a", "b", "unknown"])
        self.assertEqual(ax.get_legend_handles_labels()[1], ["Target: 18", "Week 2", "Week 10"])
        plt.close(fig)

    def test_mapping_screen_filter_aliases_and_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.csv"
            path.write_text("condition,condition_2,screen\nA,,mechano-screen\na,Canonical,mechano-screen\nB,B,VRDN-screen\n")
            mapping = load_mapping(path, "mechano-screen")
            self.assertEqual(mapping.to_dict("records"), [{"key": "a", "line": "canonical"}])
            path.write_text("condition,condition_2\nA,X\na,Y\n")
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                load_mapping(path, "mechano-screen")

    def test_csv_and_all_excel_tabs_without_intermediate_sheets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mechano_week-2.csv").write_text("condition,amendments\nA,0\n")
            with pd.ExcelWriter(root / "VRDN_week10.xlsx") as writer:
                pd.DataFrame({"condition": ["B"], "amendments": [-1]}).to_excel(writer, sheet_name="trials", index=False)
                pd.DataFrame({"condition": ["C"], "amendments": [0]}).to_excel(writer, sheet_name="more trials", index=False)
                pd.DataFrame({"notes": ["ignore"]}).to_excel(writer, sheet_name="notes", index=False)
            actual = read_weekly_sheets(root)
            self.assertEqual(len(actual), 3)
            self.assertEqual(set(actual["week"]), {"2", "10"})
            mapping = pd.DataFrame({"key": ["a", "b", "c"], "line": ["a", "b", "c"]})
            _, totals, _ = summarise(actual, mapping)
            self.assertEqual(totals["successful"].sum(), 2)


if __name__ == "__main__":
    unittest.main()
