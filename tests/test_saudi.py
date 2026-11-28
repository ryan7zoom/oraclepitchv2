"""Offline tests for the ESPN-only Saudi Pro League path. Invented data only."""

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from engine.data import fotmob, update
from engine.data.espn import EspnEvent
from engine.data.model import Match
from engine.data.store import Store
from engine.data.teams import TeamResolver
from engine.v2 import goals, shapes, sim
from engine.v2.features import LEAGUES, TeamBook
from engine.v2.power import Power

TODAY = date(2026, 11, 28)
CLUBS = ["Al Hilal", "Al Nassr", "Al Ahli", "Al Ittihad", "Al Fayha", "Damac"]


class FakeEspn:
    """Scoreboards for a few days; summaries only for some matches."""
    used = 0
    last_ok = True

    def __init__(self):
        self.calls = []
        self.events = {}
        d0 = TODAY - timedelta(days=40)
        i = 0
        for k in range(12):
            d = d0 + timedelta(days=3 * k)
            h, a = CLUBS[k % 6], CLUBS[(k + 2) % 6]
            self.events[d] = [EspnEvent(str(100 + k), d, True, h, a, 2 + k % 2, 1, None)]
            i += 1
        # one spelling variant that must merge with the same club
        d = TODAY - timedelta(days=2)
        self.events[d] = [EspnEvent("200", d, True, "Al-Fayha", "Al Hilal", 0, 3, None)]

    def scoreboard(self, league, day):
        self.calls.append(day)
        return list(self.events.get(day, []))

    def summary(self, league, event_id):
        if int(event_id) % 2 == 0:
            return {"sh_h": 12, "sh_a": 9, "sot_h": 5, "sot_a": 3, "co_h": 6, "co_a": 4}
        return None      # ESPN has no stats for this one


class TestOpenResolver(unittest.TestCase):
    def test_spelling_variants_merge_but_clubs_do_not(self):
        r = TeamResolver("saudi", [])
        a = r.resolve("Al Fayha")
        self.assertEqual(r.resolve("Al-Fayha"), a)
        self.assertEqual(r.resolve("Al Akhdoud"), "Al Okhdood")
        names = {r.resolve(n) for n in ("Al Fateh", "Al Fayha", "Al Najma", "Al Nassr", "Al Ahli", "Al Hazem")}
        self.assertEqual(len(names), 6)

    def test_lookup_never_registers(self):
        r = TeamResolver("saudi", ["Al Hilal"])
        self.assertIsNone(r.lookup("Totally New FC"))
        self.assertNotIn("Totally New FC", r.canon)

    def test_five_leagues_unchanged(self):
        r = TeamResolver("epl", ["Man United", "Arsenal"])
        self.assertEqual(r.resolve("Manchester United"), "Man United")
        self.assertIsNone(r.resolve("Mystery FC"))


class TestEspnOnlyUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = config.MATCH_DATA_DIR
        config.MATCH_DATA_DIR = self.tmp.name

    def tearDown(self):
        config.MATCH_DATA_DIR = self._old
        self.tmp.cleanup()

    def _run(self, espn):
        store = Store("saudi", os.path.join(self.tmp.name, "saudi.csv"))
        store.load()
        report = {"errors": []}
        update.update_espn(store, "saudi", TODAY, espn, report)
        store.save()
        return store, report

    def test_backfill_keeps_matches_even_without_stats(self):
        store, rep = self._run(FakeEspn())
        self.assertEqual(len(store.rows), 13)
        with_stats = [m for m in store.rows if m.sh_h is not None]
        self.assertTrue(0 < len(with_stats) < len(store.rows))
        # the hyphenated spelling merged into one club
        fayha = [n for n in store.names() if "fayha" in n.lower()]
        self.assertEqual(len(fayha), 1)             # one club, whichever spelling came first
        self.assertEqual(len(store.names()), 6)

    def test_second_run_does_not_rescan_old_days_or_duplicate(self):
        e1 = FakeEspn()
        self._run(e1)
        e2 = FakeEspn()
        store, rep = self._run(e2)
        self.assertEqual(len(store.rows), 13)
        old_calls = [d for d in e2.calls if d < TODAY - timedelta(days=config.ESPN_RECENT_DAYS)]
        self.assertEqual(old_calls, [])           # already scanned, no requests spent
        self.assertLess(len(e2.calls), len(e1.calls))

    def test_offseason_is_skipped(self):
        e = FakeEspn()
        self._run(e)
        self.assertTrue(all(d.month not in (6, 7) or (TODAY - d).days < config.ESPN_RECENT_DAYS
                            for d in e.calls))

    def test_failed_day_is_not_marked_scanned(self):
        class Flaky(FakeEspn):
            def scoreboard(self, league, day):
                self.last_ok = day.day % 5 != 0
                return [] if not self.last_ok else super().scoreboard(league, day)
        e = Flaky()
        self._run(e)
        scanned = update._load_scanned("saudi")
        for d in e.calls:
            if d.day % 5 == 0 and d < TODAY - timedelta(days=config.ESPN_RECENT_DAYS):
                self.assertNotIn(d.isoformat(), scanned)


class TestFotmob(unittest.TestCase):
    DAY = {"leagues": [
        {"ccode": "KSA", "name": "Saudi Pro League", "id": 1, "matches": [
            {"id": 11, "home": {"name": "Al Hilal"}, "away": {"name": "Al-Fayha"}, "status": {"finished": True}}]},
        {"ccode": "ENG", "name": "Premier League", "id": 2, "matches": [
            {"id": 12, "home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}, "status": {"finished": True}}]}]}
    DETAILS = {"content": {"stats": {"Periods": {"All": {"stats": [
        {"title": "Top stats", "key": "top_stats", "stats": [
            {"title": "Expected goals (xG)", "key": "expected_goals", "stats": ["2.31", "0.54"]},
            {"title": "Shots", "key": "total_shots", "stats": [14, 6]}]}]}}}}}

    def test_parsers(self):
        ms = fotmob.parse_day(self.DAY, "KSA")
        self.assertEqual([(m.id, m.home_name) for m in ms], [("11", "Al Hilal")])
        self.assertEqual(fotmob.parse_xg(self.DETAILS), (2.31, 0.54))
        self.assertIsNone(fotmob.parse_xg({"content": {}}))
        bad = {"x": {"key": "expected_goals", "stats": ["99", "1"]}}
        self.assertIsNone(fotmob.parse_xg(bad))      # implausible value ignored

    def _store(self):
        st = Store("saudi", os.path.join(tempfile.gettempdir(), "x_saudi_unused.csv"))
        d = TODAY - timedelta(days=3)
        st.upsert_fd(Match("saudi", 2026, d, "Al Hilal", "Al Fayha", ft_h=3, ft_a=0))
        return st, d

    def test_fill_xg_and_decimals_kept(self):
        outer = self
        class Client:
            def matches_on(self, day, ccode):
                return fotmob.parse_day(outer.DAY, ccode)
            def xg(self, mid):
                return fotmob.parse_xg(outer.DETAILS)
        with tempfile.TemporaryDirectory() as tmp:
            old, config.MATCH_DATA_DIR = config.MATCH_DATA_DIR, tmp
            try:
                st, d = self._store()
                rep = {}
                fotmob.fill_xg(st, "saudi", TODAY, Client(), TeamResolver("saudi", st.names()), rep)
                m = st.rows[0]
                self.assertEqual((m.xg_h, m.xg_a), (2.31, 0.54))
                self.assertEqual(rep["fotmob_xg_filled"], 1)
            finally:
                config.MATCH_DATA_DIR = old

    def test_blocked_is_not_fatal_and_changes_nothing(self):
        class Blocked:
            def matches_on(self, day, ccode):
                raise fotmob.FotmobBlocked("HTTP 403")
        with tempfile.TemporaryDirectory() as tmp:
            old, config.MATCH_DATA_DIR = config.MATCH_DATA_DIR, tmp
            try:
                st, d = self._store()
                rep = {}
                fotmob.fill_xg(st, "saudi", TODAY, Blocked(), TeamResolver("saudi", st.names()), rep)
                self.assertIsNone(st.rows[0].xg_h)
                self.assertIn("blocked", rep["fotmob_status"])
            finally:
                config.MATCH_DATA_DIR = old

    def test_gives_up_after_max_tries(self):
        class Empty:
            def matches_on(self, day, ccode):
                return []
        with tempfile.TemporaryDirectory() as tmp:
            old, config.MATCH_DATA_DIR = config.MATCH_DATA_DIR, tmp
            try:
                st, d = self._store()
                for _ in range(config.FOTMOB_MAX_TRIES + 1):
                    fotmob.fill_xg(st, "saudi", TODAY, Empty(), TeamResolver("saudi", st.names()), {})
                calls = []
                class Counting(Empty):
                    def matches_on(self, day, ccode):
                        calls.append(day)
                        return []
                fotmob.fill_xg(st, "saudi", TODAY, Counting(), TeamResolver("saudi", st.names()), {})
                self.assertEqual(calls, [])
            finally:
                config.MATCH_DATA_DIR = old


class TestSaudiModel(unittest.TestCase):
    def test_league_registered_and_rated_locally(self):
        self.assertIn("saudi", LEAGUES)
        ms = []
        d0 = date(2026, 1, 1)
        for k in range(40):
            h, a = CLUBS[k % 6], CLUBS[(k + 1 + k // 6) % 6]
            if h == a:
                continue
            ms.append(Match("saudi", 2026, d0 + timedelta(days=4 * k), h, a, ft_h=2 + (k % 2), ft_a=1))
        book = TeamBook({"saudi": ms})
        as_of = date(2026, 11, 28)
        power = Power(book, as_of, use_clubelo=False)
        self.assertEqual(power.source_for("saudi"), "local Elo")
        model = goals.GoalModel(book, power, as_of)
        p = model.predict("saudi", "Al Hilal", "Al Nassr")
        self.assertAlmostEqual(float(p.grid.sum()), 1.0, places=6)
        self.assertEqual(p.elo_source, "local Elo")
        # a club with no history still gets a sane prediction
        q = model.predict("saudi", "Brand New FC", "Al Nassr")
        self.assertGreater(q.lam_h, 0)

    def test_underdog_picks_can_be_hidden(self):
        ms = [Match("saudi", 2026, date(2026, 1, 1) + timedelta(days=3 * k), CLUBS[k % 6],
                    CLUBS[(k + 2) % 6], ft_h=2, ft_a=1) for k in range(40)]
        book = TeamBook({"saudi": ms})
        as_of = date(2026, 11, 28)
        model = goals.GoalModel(book, Power(book, as_of, use_clubelo=False), as_of)
        p = model.predict("saudi", "Al Hilal", "Al Nassr")
        sm = sim.simulate(p, book.expected("saudi", "Al Hilal", "Al Nassr", as_of),
                          sim.estimate_corr(book, "saudi", as_of), n=2000, seed=1)
        hidden = shapes.build(p, sm, "Al Hilal", "Al Nassr", include_underdog=False)
        self.assertEqual({l.side for l in hidden["pick"].legs}, {"favourite"})
        self.assertFalse(hidden["underdog_shown"])
        shown = shapes.build(p, sm, "Al Hilal", "Al Nassr")
        self.assertTrue(shown["underdog_shown"])
        self.assertGreaterEqual(len(shown["pick"].legs), 2)


if __name__ == "__main__":
    unittest.main()
