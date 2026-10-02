"""Test van de keten van taalmodellen: is de ene aanbieder op, dan de volgende; te lange tekst wordt overgeslagen.
Nagebootst: geen internet. Draaien: python -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import test_run_voortgang  # noqa: E402,F401  (zet de nep-'google.genai' klaar)
run = sys.modules["run"]


class Antw:
    def __init__(self, status, json_=None, tekst="", koppen=None):
        self.status_code, self._json, self.text, self.headers = status, json_, tekst, koppen or {}

    def json(self):
        return self._json


def ok(tekst):
    return Antw(200, {"choices": [{"message": {"content": tekst}}]})


class TestAanbieders(unittest.TestCase):
    def setUp(self):
        self.oud = {k: getattr(run, k) for k in ["client", "START_AANBIEDER", "PAUZE"]}
        self.oud_cfg = run.CFG.get("reserve_aanbieders")
        self.oud_post, self.oud_sleep = run.requests.post, run.time.sleep
        run.client, run.START_AANBIEDER = None, None          # geen Gemini-sleutel
        run.time.sleep = lambda s: None
        run.UITGEPUT.clear()
        run.CFG["reserve_aanbieders"] = [
            {"naam": "github", "basis_url": "https://gh.test", "sleutel_env": "TEST_GH",
             "modellen": {"filter": "mini", "extractie": "mini"}, "max_invoer_tekens": 100},
            {"naam": "zonder_sleutel", "basis_url": "https://x.test", "sleutel_env": "BESTAAT_NIET",
             "modellen": {"filter": "x", "extractie": "x"}},
            {"naam": "groot", "basis_url": "https://groot.test", "sleutel_env": "TEST_GROOT",
             "modellen": {"filter": "g", "extractie": "g"}}]
        os.environ["TEST_GH"], os.environ["TEST_GROOT"] = "a", "b"
        self.aanroepen = []

    def tearDown(self):
        for k, v in self.oud.items():
            setattr(run, k, v)
        run.CFG["reserve_aanbieders"] = self.oud_cfg
        run.requests.post, run.time.sleep = self.oud_post, self.oud_sleep
        run.UITGEPUT.clear()
        del os.environ["TEST_GH"], os.environ["TEST_GROOT"]

    def nep(self, antwoorden):
        def post(url, headers=None, json=None, timeout=None):
            self.aanroepen.append((url, json["model"], "response_format" in json))
            return antwoorden[url].pop(0)
        run.requests.post = post

    def test_volgende_aanbieder_als_limiet_op(self):
        self.nep({"https://gh.test/chat/completions": [Antw(429, tekst="Rate limit of 150 per 86400s exceeded")],
                  "https://groot.test/chat/completions": [ok('{"a": 1}'), ok("JA")]})
        self.assertEqual(run.llm("extractie", "kort", json_uit=True), '{"a": 1}')
        self.assertIn("github", run.UITGEPUT)
        self.assertEqual(run.llm("filter", "kort"), "JA")       # github wordt niet meer geprobeerd
        self.assertEqual([u for u, _, _ in self.aanroepen].count("https://gh.test/chat/completions"), 1)
        self.assertTrue(self.aanroepen[0][2])                   # JSON-modus gevraagd

    def test_te_lange_tekst_naar_groter_model(self):
        self.nep({"https://groot.test/chat/completions": [ok("JA")]})
        self.assertEqual(run.llm("filter", "x" * 500), "JA")
        self.assertEqual([u for u, _, _ in self.aanroepen], ["https://groot.test/chat/completions"])

    def test_alles_op_geeft_limietop_en_te_lang_geeft_later(self):
        self.nep({"https://gh.test/chat/completions": [Antw(429)], "https://groot.test/chat/completions": [Antw(429)]})
        with self.assertRaises(run.LimietOp):
            run.llm("filter", "kort")
        run.UITGEPUT.clear()
        self.nep({"https://groot.test/chat/completions": [Antw(429)]})
        with self.assertRaises(RuntimeError) as e:              # te lang voor github, groot is op: later opnieuw
            run.llm("filter", "x" * 500)
        self.assertNotIsInstance(e.exception, run.LimietOp)

    def test_zoeken_kan_alleen_met_hoofdaanbieder(self):
        with self.assertRaises(run.LimietOp):
            run.llm("zoeken", "zoek", zoeken=True, met_bronnen=True)
        self.assertIsNone(run.ai_zoekfunctie("zoek"))           # zonder Gemini: geen AI-zoekactie, run gaat door

    def test_beginnen_bij_gekozen_aanbieder(self):
        run.START_AANBIEDER = "groot"
        self.assertEqual([a["naam"] for a in run.reserve_aanbieders()], ["groot"])


if __name__ == "__main__":
    unittest.main()
