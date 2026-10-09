"""Boundary and failure tests for the automated public profile."""

from contextlib import redirect_stderr
from copy import deepcopy
from datetime import date, timedelta
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_github_data as fetch
import render_profile as renderer

PROFILE = {"username": "example", "name": "Fábio & <Luiz>",
           "headline": "Web & APIs", "location": "Brasília"}


def snapshot():
    end = date(2024, 3, 1)  # Includes February 29 and a year boundary.
    start = end - timedelta(days=364)
    return {"username": "example", "as_of": end.isoformat(), "timezone": "UTC",
            "from": start.isoformat(), "to": end.isoformat(), "public_repositories": 3,
            "days": [{"date": (start + timedelta(days=i)).isoformat(),
                      "count": 1 if i % 3 else 0, "level": 1 if i % 3 else 0}
                     for i in range(365)]}


def calendar(data):
    reverse = {value: key for key, value in fetch.LEVELS.items()}
    return {"totalContributions": sum(day["count"] for day in data["days"]),
            "weeks": [{"contributionDays": [
                {"date": day["date"], "contributionCount": day["count"],
                 "contributionLevel": reverse[day["level"]]}
                for day in data["days"]]}]}


class StatisticsTests(unittest.TestCase):
    def stats(self, counts):
        return renderer.statistics([{"count": count} for count in counts])

    def test_empty_and_inactive_calendars(self):
        for counts in ([], [0, 0, 0]):
            self.assertEqual(self.stats(counts),
                             {"total": 0, "active": 0, "longest": 0, "current": 0})

    def test_in_progress_today_preserves_yesterday_streak(self):
        self.assertEqual(self.stats([0, 4, 2, 0])["current"], 2)

    def test_two_inactive_days_break_current_streak(self):
        self.assertEqual(self.stats([3, 2, 0, 0])["current"], 0)

    def test_gap_separates_runs_and_counts_contributions(self):
        self.assertEqual(self.stats([2, 3, 1, 0, 9, 1]),
                         {"total": 16, "active": 5, "longest": 3, "current": 2})

    def test_full_period_streak(self):
        self.assertEqual(self.stats([1] * 365)["longest"], 365)

    def test_monthly_chart_keeps_years_and_partial_months_separate(self):
        days = [{"date": "2023-12-31", "count": 2},
                {"date": "2024-01-01", "count": 4},
                {"date": "2024-01-02", "count": 3},
                {"date": "2024-12-01", "count": 1}]
        self.assertEqual(renderer.monthly_activity(days),
                         [("2023-12", 2), ("2024-01", 7), ("2024-12", 1)])
        self.assertEqual(sum(total for _, total in renderer.monthly_activity(days)), 10)

    def test_average_counts_only_active_days_and_best_day_breaks_ties_by_date(self):
        days = [{"date": "2024-01-01", "count": 6},
                {"date": "2024-01-02", "count": 0},
                {"date": "2024-01-03", "count": 6}]
        result = renderer.activity_details(days)
        self.assertEqual(result["average"], 6)
        self.assertEqual(result["best"], days[0])

    def test_empty_activity_has_no_fictitious_best_day(self):
        for days in ([], [{"date": "2024-01-01", "count": 0}]):
            result = renderer.activity_details(days)
            self.assertIsNone(result["best"])
            self.assertEqual(result["average"], 0)


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.data = snapshot()
        self.start = date.fromisoformat(self.data["from"])
        self.end = date.fromisoformat(self.data["to"])

    def test_complete_leap_year_calendar(self):
        result = fetch.normalize(calendar(self.data), self.start, self.end)
        self.assertEqual(result, self.data["days"])
        self.assertIn("2024-02-29", [day["date"] for day in result])

    def test_workflow_token_sends_graphql_as_json(self):
        payload = {"query": "query { viewer { login } }"}
        with patch.dict(fetch.os.environ, {"GITHUB_TOKEN": "test-only"}, clear=True), \
                patch.object(fetch, "urlopen") as open_request:
            open_request.return_value.__enter__.return_value = StringIO('{"data": {}}')
            self.assertEqual(fetch.api("graphql", payload), {"data": {}})
            request = open_request.call_args.args[0]
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Content-type"), "application/json")
            self.assertEqual(json.loads(request.data), payload)

    def test_missing_and_duplicate_dates_are_rejected(self):
        for bad in (self.data["days"][:-1], self.data["days"] + [self.data["days"][0]]):
            data = deepcopy(self.data)
            data["days"] = bad
            with self.assertRaises(ValueError):
                fetch.normalize(calendar(data), self.start, self.end)

    def test_inconsistent_total_is_rejected(self):
        response = calendar(self.data)
        response["totalContributions"] += 1
        with self.assertRaises(ValueError):
            fetch.normalize(response, self.start, self.end)

    def test_negative_or_boolean_counts_and_wrong_colors_are_rejected(self):
        for count, level in ((-1, "NONE"), (True, "FIRST_QUARTILE"), (0, "FOURTH_QUARTILE")):
            response = calendar(self.data)
            day = response["weeks"][0]["contributionDays"][0]
            day.update(contributionCount=count, contributionLevel=level)
            with self.assertRaises(ValueError):
                fetch.normalize(response, self.start, self.end)

    def test_partial_graphql_errors_do_not_call_rest(self):
        with patch.object(fetch, "api", return_value={"errors": [{"message": "unavailable"}]}) as api:
            with self.assertRaises(ValueError):
                fetch.collect("example", self.end)
            self.assertEqual(api.call_count, 1)

    def test_failed_collection_preserves_previous_snapshot(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "github.json"
            output.write_text("previous snapshot", encoding="utf-8")
            with patch.object(sys, "argv", ["fetch", "--output", str(output)]), \
                    patch.object(fetch, "collect", side_effect=OSError("unavailable")), \
                    redirect_stderr(StringIO()):
                self.assertEqual(fetch.main(), 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous snapshot")


class RenderTests(unittest.TestCase):
    def test_svg_is_valid_and_untrusted_text_is_escaped(self):
        assets = renderer.render(snapshot(), PROFILE)
        namespace = {"s": "http://www.w3.org/2000/svg"}
        for content in assets.values():
            root = ET.fromstring(content)
            self.assertIn(root.attrib["viewBox"].split()[2], ("860", "430"))
            self.assertIsNotNone(root.find("s:title", namespace))
            self.assertIsNotNone(root.find("s:desc", namespace))
            self.assertEqual(root.findall(".//s:script", namespace), [])
            self.assertNotIn("<Luiz>", content)
        self.assertIn("Fábio &amp; &lt;Luiz&gt;", assets["identity.svg"])

    def test_all_365_cells_fit_inside_the_canvas(self):
        # Seven possible weekdays, including a leap day and partial edge weeks.
        for offset in range(7):
            data = snapshot()
            for day in data["days"]:
                day["date"] = (date.fromisoformat(day["date"]) + timedelta(days=offset)).isoformat()
            data["from"] = data["days"][0]["date"]
            data["as_of"] = data["to"] = data["days"][-1]["date"]
            assets = renderer.render(data, PROFILE)
            for name, max_x, max_y in (("contributions.svg", 828, 236),
                                       ("contributions-mobile.svg", 400, 393)):
                root = ET.fromstring(assets[name])
                cells = [rect for rect in root.iter("{http://www.w3.org/2000/svg}rect")
                         if rect.attrib.get("class") == "cell"]
                self.assertEqual(len(cells), 365)
                for cell in cells:
                    self.assertLess(float(cell.attrib["x"]) + float(cell.attrib["width"]), max_x)
                    self.assertLess(float(cell.attrib["y"]) + float(cell.attrib["height"]), max_y)

    def test_rendering_is_deterministic(self):
        self.assertEqual(renderer.render(snapshot(), PROFILE), renderer.render(snapshot(), PROFILE))

    def test_wrong_account_or_missing_day_is_rejected(self):
        for mutate in (lambda data: data.update(username="other"),
                       lambda data: data["days"].pop()):
            data = snapshot()
            mutate(data)
            with self.assertRaises(ValueError):
                renderer.render(data, PROFILE)

    def test_invalid_snapshot_does_not_replace_existing_artwork(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "stats.svg"
            target.write_text("previous artwork", encoding="utf-8")
            data = snapshot()
            data["username"] = "other"
            source = directory / "github.json"
            source.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(sys, "argv", ["render", "--data", str(source),
                                           "--output-dir", str(directory)]), \
                    redirect_stderr(StringIO()):
                self.assertEqual(renderer.main(), 1)
            self.assertEqual(target.read_text(encoding="utf-8"), "previous artwork")


if __name__ == "__main__":
    unittest.main()
