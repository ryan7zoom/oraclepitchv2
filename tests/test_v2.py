"""Offline tests for engine/v2. Uses invented matches only."""

import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data.model import Match
from engine.v2 import builder, form, goals, markets, render, sim
from engine.v2.features import TeamBook
from engine.v2.injuries import InjuryBook
from engine.v2.injuries_fpl import importance
from engine.v2.power import Power


def make_history(n=30):
    ms = []
    d0 = date(2026, 1, 1)
    for i in range(n):
        d = d0 + timedelta(days=7 * i)
        hg, ag = (2, 1) if i % 3 else (1, 1)
        ms.append(Match("epl", 2026, d, "Alpha", "Beta", ft_h=hg, ft_a=ag,
                        ht_h=hg // 2, ht_a=ag // 2, sh_h=14, sh_a=10, sot_h=5, sot_a=4,
                        co_h=6, co_a=4, yc_h=2, yc_a=3, rc_h=0, rc_a=0, of_h=2, of_a=1,
                        xg_h=1.7, xg_a=1.1))
        ms.append(Match("epl", 2026, d + timedelta(days=1), "Gamma", "Delta", ft_h=1, ft_a=2,
                        ht_h=0, ht_a=1, sh_h=9, sh_a=15, sot_h=3, sot_a=6,
                        co_h=3, co_a=7, yc_h=3, yc_a=1, rc_h=0, rc_a=0, of_h=1, of_a=2,
                        xg_h=0.9, xg_a=1.8))
    return ms


class TestV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ms = make_history()
        cls.book = TeamBook({"epl": cls.ms})
        cls.as_of = date(2026, 10, 1)
        cls.power = Power(cls.book, cls.as_of, use_clubelo=False)
        cls.model = goals.GoalModel(cls.book, cls.power, cls.as_of)

    def test_grid_normalised(self):
        p = self.model.predict("epl", "Alpha", "Beta")
        self.assertAlmostEqual(float(p.grid.sum()), 1.0, places=6)
        r = p.result()
        self.assertAlmostEqual(sum(r.values()), 1.0, places=6)
        self.assertGreater(p.lam_h, 0)
        self.assertGreater(p.lam_a, 0)

    def test_handicap_opposites_sum_to_one(self):
        p = self.model.predict("epl", "Alpha", "Beta")
        for line in (-1.0, -0.5, 0.0, 0.5, 1.0):
            h = p.handicap("home", line)
            a = p.handicap("away", -line)
            self.assertAlmostEqual(h + a, 1.0, places=6)

    def test_markets_include_totals_and_no_handicaps_in_builder(self):
        p = self.model.predict("epl", "Alpha", "Beta")
        ms = markets.build(p)
        self.assertTrue(any(m.kind == "total" and m.line == 2.5 for m in ms))
        self.assertTrue(any(m.kind == "team" for m in ms))
        self.assertTrue(any(m.kind == "handicap" for m in ms))

    def test_sim_and_builder(self):
        p = self.model.predict("epl", "Alpha", "Beta")
        corr = sim.estimate_corr(self.book, "epl", self.as_of)
        sm = sim.simulate(p, self.book.expected("epl", "Alpha", "Beta", self.as_of),
                          corr, n=3000, seed=1)
        self.assertEqual(sm.data.shape, (3000, 10))
        ms = markets.build(p)
        cands = form.candidates(self.book, "epl", "Alpha", "Beta", self.as_of, sm)
        slips = builder.build(p, ms, cands, sm, max_legs=5)
        best = slips["best"]
        self.assertLessEqual(len(best.legs), 5)
        self.assertGreater(best.joint, 0)
        self.assertLessEqual(best.joint, min(l.prob for l in best.legs) + 1e-6)
        groups = [l.group for l in best.legs]
        self.assertEqual(len(groups), len(set(groups)))

    def test_injury_factor_neutral_without_file(self):
        ib = InjuryBook([])
        self.assertEqual(ib.factor("epl", "Alpha", self.as_of), 1.0)

    def test_fpl_importance_is_bounded(self):
        self.assertEqual(importance(0, 0), 0.0)
        self.assertLessEqual(importance(40, 2.0), 1.0)
        self.assertGreater(importance(30, 0.5), 0.5)

    def test_form_ladders_are_match_specific(self):
        low = form.ladder(20, "shots", "total")
        high = form.ladder(28, "shots", "total")
        self.assertLess(min(low), min(high))
        self.assertGreaterEqual(min(low), 0.5)
        self.assertIn(8.5, form.ladder(8.0, "sot", "total"))

    def test_render_contains_prediction_and_builder(self):
        p = self.model.predict("epl", "Alpha", "Beta")
        sm = sim.simulate(p, self.book.expected("epl", "Alpha", "Beta", self.as_of),
                          sim.estimate_corr(self.book, "epl", self.as_of), n=1000, seed=2)
        ms = markets.build(p)
        cands = form.candidates(self.book, "epl", "Alpha", "Beta", self.as_of, sm)
        slips = builder.build(p, ms, cands, sm)
        card = {"league": "epl", "date": "2026-10-02", "kickoff": "20:00",
                "home": "Alpha", "away": "Beta", "pred": p, "markets": ms,
                "main_total": markets.main_total(p), "builder": slips,
                "notes": form.notes(self.book, "epl", "Alpha", "Beta", self.as_of, sm),
                "most": [], "pick": "Alpha win", "form": {"home": "WWDLW", "away": "LDWLL"}}
        html = render.render([card], __import__("datetime").datetime(2026, 10, 1),
                             "2026-09-30", "local Elo", [])
        self.assertIn("Bet builder", html)
        self.assertIn("Form says", html)
        self.assertIn("Alpha", html)


if __name__ == "__main__":
    unittest.main()
