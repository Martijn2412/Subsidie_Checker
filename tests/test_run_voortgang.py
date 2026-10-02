"""Test of een run die halverwege stopt (crash, tijd op) zijn werk bewaart en de volgende
run verdergaat waar hij bleef. Alles nagebootst: geen internet, geen taalmodel.
Draaien: python -m unittest discover tests"""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import types
import unittest

HIER = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent / "scraper"))

# Nep-'google.genai', zodat run.py te importeren is zonder pakket of sleutel.
_g = types.ModuleType("google"); _genai = types.ModuleType("google.genai"); _types = types.ModuleType("google.genai.types")
_genai.Client = lambda **kw: None; _types.HttpOptions = lambda **kw: None; _genai.types = _types; _g.genai = _genai
sys.modules.update({"google": _g, "google.genai": _genai, "google.genai.types": _types})
os.environ.setdefault("GEMINI_API_KEY", "test")
import run  # noqa: E402

GEMEENTEN = ["Aadorp", "Beekdorp", "Ceedorp", "Deedorp", "Eedorp"]
TEKST = "Subsidie voor isolatie van de eigen woning door de eigenaar. Dak, vloer en gevel."


class Basis(unittest.TestCase):
    """Nep-omgeving: tijdelijke map, nagebootst CVDR en taalmodel."""

    def setUp(self):
        self.map = pathlib.Path(tempfile.mkdtemp())
        (self.map / "data").mkdir()
        self.oud = {k: getattr(run, k) for k in
                    ["ROOT", "OUT", "DATA", "STATE", "DEKKING", "LOG_ALL", "LOG_LAST", "ZOEKSTATUS", "WEB_STATE",
                     "OVERZICHT", "VOORTGANG", "MAX_RUN_SEC", "zoek_cvdr", "is_vervallen", "haal_tekst",
                     "is_relevant", "extraheer", "gemeentelijst", "schrijf_overzicht", "GEMEENTE_SITES"]}
        self.oud_web = {k: getattr(run.webbronnen, k) for k in ["verzamel", "haal_roo", "vind_site"]}
        for k in ["OUT", "STATE", "DEKKING", "LOG_ALL", "LOG_LAST", "ZOEKSTATUS", "WEB_STATE", "OVERZICHT", "VOORTGANG",
                  "GEMEENTE_SITES"]:
            setattr(run, k, self.map / getattr(run, k).relative_to(run.ROOT))
        run.ROOT, run.DATA = self.map, self.map / "data"
        run.gemeentelijst = lambda: [{"naam": n, "provincie": "Test"} for n in GEMEENTEN]
        run.zoek_cvdr = self.nep_cvdr
        run.is_vervallen = lambda cid: False
        run.haal_tekst = lambda url, pagina=None: TEKST
        run.is_relevant = lambda titel, tekst: True
        run.extraheer = self.nep_extraheer
        run.schrijf_overzicht = lambda *a: None
        # internet: geen pagina's gevonden (het zoeken op internet zelf wordt in test_webbronnen getest)
        run.webbronnen.verzamel = lambda *a, **kw: {"paginas": [], "verslag": {
            "site": None, "site_bron": None, "site_urls": 0, "kandidaten": 0, "partners": [], "ai_gezocht": False,
            "paginas": []}}
        run.webbronnen.haal_roo = lambda: {}
        run.webbronnen.vind_site = lambda *a, **kw: None
        self.gezocht, self.uitgelezen, self.crash_bij, self.tijd_op_na, self.budget_op_bij = [], [], None, None, None

    def tearDown(self):
        for k, v in self.oud.items():
            setattr(run, k, v)
        for k, v in self.oud_web.items():
            setattr(run.webbronnen, k, v)
        shutil.rmtree(self.map)

    def nep_cvdr(self, naam, trefwoorden=None):
        self.gezocht.append(naam)
        if self.tijd_op_na is not None and len(self.gezocht) > self.tijd_op_na:
            run.MAX_RUN_SEC = -1          # vanaf nu is de tijd op
        cid = "CVDR" + str(GEMEENTEN.index(naam) + 1)
        return {cid: {"versie": "1", "titel": f"Subsidieregeling isolatie woningen {naam}", "gewijzigd": "2026-01-01",
                      "xml_url": "x"}}

    def nep_extraheer(self, tekst):
        if self.crash_bij and self.gezocht[-1] == self.crash_bij:
            raise KeyboardInterrupt("nagebootste onderbreking")
        if self.budget_op_bij and self.gezocht[-1] == self.budget_op_bij:
            raise run.LimietOp("402 credits op")
        self.uitgelezen.append(self.gezocht[-1])
        return {"naam": f"Isolatiesubsidie {self.gezocht[-1]}", "bedrag": "max. € 1.000",
                "looptijd_eind": "2030-12-31", "criteria": {"eigenaar_bewoner": True}}

    def regelingen(self):
        return sorted(r["gemeente"] for r in json.loads(run.OUT.read_text()))

    def voortgang(self):
        return json.loads(run.VOORTGANG.read_text())["volgende"]


class TestVoortgang(Basis):
    def test_crash_bewaart_werk_en_volgende_run_gaat_verder(self):
        self.crash_bij = "Ceedorp"
        with self.assertRaises(KeyboardInterrupt):
            run.main()
        self.assertEqual(self.regelingen(), ["Aadorp", "Beekdorp"])     # werk van vóór de crash is bewaard
        self.assertEqual(self.voortgang(), "Ceedorp")
        self.assertIn("gestopt", run.LOG_LAST.read_text())
        self.assertTrue((self.map / "tios" / "subsidies.json").exists())  # export ook bijgewerkt

        self.crash_bij, self.gezocht, self.uitgelezen = None, [], []
        run.main()
        self.assertEqual(self.gezocht[0], "Ceedorp")                      # begint waar hij bleef
        self.assertEqual(self.uitgelezen, ["Ceedorp", "Deedorp", "Eedorp"])  # A en B niet opnieuw uitgelezen
        self.assertEqual(self.regelingen(), GEMEENTEN)
        self.assertIsNone(self.voortgang())                               # rond: volgende keer weer vooraan

    def test_budget_op_stopt_en_volgende_run_gaat_daar_verder(self):
        self.budget_op_bij = "Ceedorp"
        run.main()                                                        # geen fout: netjes gestopt
        self.assertEqual(self.gezocht, ["Aadorp", "Beekdorp", "Ceedorp"])  # niet doorgegaan na het budget
        self.assertEqual(self.regelingen(), ["Aadorp", "Beekdorp"])
        self.assertEqual(self.voortgang(), "Ceedorp")
        self.assertIn("AI-budget of daglimiet op", run.LOG_LAST.read_text())

        self.budget_op_bij, self.gezocht, self.uitgelezen = None, [], []  # volgende dag: nieuw budget
        run.main()
        self.assertEqual(self.gezocht[0], "Ceedorp")
        self.assertEqual(self.uitgelezen, ["Ceedorp", "Deedorp", "Eedorp"])
        self.assertEqual(self.regelingen(), GEMEENTEN)
        self.assertIsNone(self.voortgang())

    def test_resultaat_per_gemeente_in_samenvatting(self):
        samenvatting = self.map / "summary.md"
        os.environ["GITHUB_STEP_SUMMARY"] = str(samenvatting)
        try:
            self.budget_op_bij = "Ceedorp"
            run.main()
        finally:
            del os.environ["GITHUB_STEP_SUMMARY"]
        tekst = samenvatting.read_text()
        self.assertIn("| ✅ | Aadorp | voorwaarden opgehaald", tekst)
        self.assertIn("| 🛑 | Ceedorp |", tekst)
        self.assertIn("verder bij **Ceedorp**", tekst)

    def test_tijd_op_stopt_netjes(self):
        self.tijd_op_na = 2
        run.main()                                                        # geen fout: netjes gestopt
        self.assertEqual(self.regelingen(), ["Aadorp", "Beekdorp", "Ceedorp"])
        self.assertEqual(self.voortgang(), "Deedorp")
        self.assertIn("tijd van de run op", run.LOG_LAST.read_text())

    def test_tussentijds_opslaan(self):
        oud_interval = run.BEWAAR_ELKE_SEC
        run.BEWAAR_ELKE_SEC = -1                                          # na elke gemeente opslaan
        try:
            self.crash_bij = "Eedorp"
            bewaard = []
            echte_schrijf = run.schrijf
            run.schrijf = lambda p, obj: (bewaard.append(p.name), echte_schrijf(p, obj))[1]
            with self.assertRaises(KeyboardInterrupt):
                run.main()
            self.assertGreaterEqual(bewaard.count("regelingen.json"), 4)  # 3 tussentijds + 1 bij de crash
        finally:
            run.BEWAAR_ELKE_SEC = oud_interval
            run.schrijf = echte_schrijf


if __name__ == "__main__":
    unittest.main()
