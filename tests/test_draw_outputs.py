"""Guard the STAR rows produced by the parametric builders."""

import hashlib
import json
from pathlib import Path
import runpy
import unittest


DRAW = runpy.run_path(str(Path(__file__).resolve().parents[1] / "src" / "draw.py"))


class DrawOutputTests(unittest.TestCase):
    def test_builder_outputs(self):
        outer = DRAW["build_cilia_lines_star_rows"]
        central = DRAW["build_central_pair_star_rows"]
        ift = DRAW["build_ift_star_rows"]
        cases = {
            "outer": (
                outer(9, 9000, 1000, 960, "TS_001", 1, twist_per_layer_deg=5, z_offset_ang=250),
                90, "1d15d14ecd60179c725f77508fd2e5fb9522ee7c0221b74082073fce146b2113",
            ),
            "outer_random": (
                outer(6, 5100, 960, 960, "TS_001", 1, random_spacing=True,
                      random_max_diff=200, rng_seed=123, twist_per_layer_deg=3),
                36, "ef319d52ae74e9475c4c10482a51b1f0d258007446e81ff5cdc7c9431189135b",
            ),
            "central": (
                central(9000, 333, "TS_001", 1, z_offset_ang=100),
                28, "7ca21e7bdd37811cb6f718f507867cd6ba3adeedfce7788c8c4ee6b6391cd0a3",
            ),
            "central_random": (
                central(7500, 333, "TS_001", 1, random_spacing=True,
                        random_max_diff=80, rng_seed=456),
                23, "6b1c608abcaace9222bd30631889464cab2529f212b8adff44a510235c33cc8d",
            ),
            "ift_line": (
                ift(9, 50, 9000, 960, 200, "TS_001", 1, line_mode=True, rng_seed=789),
                50, "fd56b448bcbf7e658f6041e16eae5787a8a15fad4b08cb043c7b86cd00ce64d5",
            ),
            "ift_scatter": (
                ift(9, 50, 9000, 960, 200, "TS_001", 1, line_mode=False, rng_seed=789),
                50, "948433fc505d00f31bb4ad779cb0e5dc579b4a300a4eda35b0d15430526a9c22",
            ),
        }
        for name, (rows, count, digest) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(len(rows), count)
                data = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
