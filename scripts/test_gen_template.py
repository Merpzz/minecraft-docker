"""Offline tests for tools/gen_template.py. Run: python3 -m unittest discover -s scripts"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import gen_template as g  # noqa: E402

XML = '<Container>\n  <Config Name="EULA" Default="false|true">false</Config>\n' \
      '  <Config Name="MC_VERSION" Target="MC_VERSION" Default="old" Mode="">1.21.1</Config>\n</Container>\n'


class Generator(unittest.TestCase):
    def test_cutoff(self):
        self.assertEqual(g.offered_versions(["26.3", "1.8", "1.7.10", "1.7.2"]), ["26.3", "1.8", "1.7.10"])
        self.assertEqual(g.offered_versions(["1.8"]), ["1.8"])   # cutoff missing: keep all

    def test_dropdown_only_touches_mc_version(self):
        out = g.update_dropdown(XML, ["26.3", "1.21.1"])
        self.assertIn('Name="MC_VERSION" Target="MC_VERSION" Default="latest|26.3|1.21.1" Mode="">1.21.1<', out)
        self.assertIn('Name="EULA" Default="false|true"', out)
        with self.assertRaises(SystemExit):
            g.update_dropdown("<Container/>", ["1.21.1"])

    def test_rows(self):
        rows = g.build_rows(
            ["26.3", "1.21.1", "1.12.2"], {"26.3", "1.21.1"}, "0.19.5",
            {"26.3": ["66.0.2"], "1.21.1": ["52.0.1", "52.1.10", "52.1.0"], "1.12.2": ["14.23.5.2859"]},
            {"1.21.1-recommended": "52.1.0", "1.12.2-recommended": "14.23.5.2859"},
            {"26.3": ["26.3.0.6-beta", "26.3.0.7-beta"], "1.21.1": ["21.1.1", "21.1.250", "21.1.251-beta"]})
        self.assertEqual(rows, [
            ("26.3", "0.19.5", "66.0.2 (latest)", "26.3.0.7-beta (beta)"),
            ("1.21.1", "0.19.5", "52.1.0 (recommended)", "21.1.250"),
            ("1.12.2", "-", "14.23.5.2859 (recommended)", "-")])

    def test_markdown(self):
        md = g.render_md([("1.21.1", "0.19.5", "52.1.0 (recommended)", "21.1.250")], "2026-09-20")
        self.assertIn("| 1.21.1 | 0.19.5 | 52.1.0 (recommended) | 21.1.250 |", md)


if __name__ == "__main__":
    unittest.main()
