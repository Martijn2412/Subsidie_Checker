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
                     "is_relevant", "extraheer", "gemeentelijst", "schrijf_overzicht", "web_zoek"]}
        for k in ["OUT", "STATE", "DEKKING", "LOG_ALL", "LOG_LAST", "ZOEKSTATUS", "WEB_STATE", "OVERZICHT", "VOORTGANG"]:
            setattr(run, k, self.map / getattr(run, k).relative_to(run.ROOT))
        run.ROOT, run.DATA = self.map, self.map / "data"
        run.gemeentelijst = lambda: [{"naam": n, "provincie": "Test"} for n in GEMEENTEN]
        run.zoek_cvdr = self.nep_cvdr
        run.is_vervallen = lambda cid: False
        run.haal_tekst = lambda url, pagina=None: TEKST
        run.is_relevant = lambda titel, tekst: True
        run.extraheer = self.nep_extraheer
        run.schrijf_overzicht = lambda *a: None
        run.web_zoek = lambda g: []
        self.gezocht, self.uitgelezen, self.crash_bij, self.tijd_op_na, self.budget_op_bij = [], [], None, None, None

    def tearDown(self):
        for k, v in self.oud.items():
            setattr(run, k, v)
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


class TestWebregelingen(Basis):
    """Regelingen die via internet zijn gevonden: voorwaarden van de pagina of via het taalmodel."""
    EXT = {"relevant": True, "naam": "Isolatiesubsidie Webdorp", "bedrag": "max. € 500",
           "criteria": {"eigenaar_bewoner": True, "woz_max": 400000}}

    def test_vervolglinks_alleen_voorwaarden_op_eigen_site(self):
        h = ('<a href="/subsidie-isolatie/voorwaarden">Voorwaarden isolatiesubsidie</a>'
             '<a href="https://andere-site.nl/subsidie-voorwaarden">elders</a>'
             '<a href="/contact">Contact</a>'
             '<a href="/documenten/subsidieregeling-isolatie.pdf">Subsidieregeling (pdf)</a>')
        self.assertEqual(run.vervolglinks("https://www.gemeente.nl/nieuws/isolatie", h),
                         ["https://www.gemeente.nl/subsidie-isolatie/voorwaarden",
                          "https://www.gemeente.nl/documenten/subsidieregeling-isolatie.pdf"])

    def test_pagina_met_doorverwijzing_wordt_gelezen(self):
        opgehaald = []
        def nep_ruw(url):
            opgehaald.append(url)
            if url.endswith("/nieuws"):
                return "Nieuws: er is weer subsidie voor isolatie. " * 3, '<a href="/isolatie/voorwaarden">Bekijk de voorwaarden</a>'
            return "Voorwaarden: eigenaar-bewoner, WOZ-waarde tot 400.000 euro. " * 20, ""
        oud, run.haal_ruw = run.haal_ruw, nep_ruw
        run.extraheer = lambda tekst: dict(self.EXT) if "WOZ-waarde" in tekst else {}
        try:
            ext, methode = run.lees_webregeling("Isolatiesubsidie", "Webdorp", "https://www.webdorp.nl/nieuws")
        finally:
            run.haal_ruw = oud
        self.assertEqual(methode, "pagina")
        self.assertEqual(ext["criteria"]["woz_max"], 400000)
        self.assertEqual(opgehaald, ["https://www.webdorp.nl/nieuws", "https://www.webdorp.nl/isolatie/voorwaarden"])

    def test_geblokkeerde_pagina_dan_taalmodel_laten_zoeken(self):
        def geblokkeerd(url):
            raise RuntimeError("403 Forbidden")
        vragen = []
        oud_ruw, oud_llm = run.haal_ruw, run.llm
        run.haal_ruw = geblokkeerd
        run.llm = lambda taak, tekst, **kw: (vragen.append((taak, kw)), json.dumps(self.EXT))[1]
        try:
            ext, methode = run.lees_webregeling("Isolatiesubsidie", "Webdorp", "https://www.webdorp.nl/x")
        finally:
            run.haal_ruw, run.llm = oud_ruw, oud_llm
        self.assertEqual(methode, "zoeken")
        self.assertTrue(vragen[0][1]["zoeken"])
        self.assertTrue(run.heeft_voorwaarden(ext))

    def test_bestaande_webregeling_zonder_voorwaarden_wordt_opnieuw_gelezen(self):
        run.zoek_cvdr = lambda naam, trefwoorden=None: {}            # niets in het CVDR
        web = {"id": "aadorp-web-isolatie", "cvdr_id": None, "bron": "web", "handmatig": False,
               "gecontroleerd": False, "gemeente": "Aadorp", "provincie": "Test", "naam": "Isolatiesubsidie Aadorp",
               "bron_url": "https://www.aadorp.nl/isolatie", "peildatum": "2026-09-28", "status": "onbekend",
               "betrouwbaarheid": "laag", "criteria": {}}
        run.OUT.write_text(json.dumps([web]))
        run.WEB_STATE.write_text(json.dumps({n: {"datum": run.VANDAAG, "gevonden": 0} for n in GEMEENTEN}))
        gelezen = []
        oud = run.lees_webregeling
        run.lees_webregeling = lambda naam, g, url: (gelezen.append(url), (dict(self.EXT), "pagina"))[1]
        try:
            run.main()
            r = json.loads(run.OUT.read_text())[0]
            self.assertEqual(r["criteria"]["woz_max"], 400000)
            self.assertEqual(r["voorwaarden_gelezen"], run.VANDAAG)
            self.assertIn("voorwaarden uitgelezen (van de bronpagina", run.LOG_LAST.read_text())
            run.main()                                                # tweede keer: heeft voorwaarden, niet opnieuw
            self.assertEqual(gelezen, ["https://www.aadorp.nl/isolatie"])
        finally:
            run.lees_webregeling = oud

    def test_niet_gelukt_dan_niet_dezelfde_dag_opnieuw(self):
        run.zoek_cvdr = lambda naam, trefwoorden=None: {}
        web = {"id": "aadorp-web-isolatie", "bron": "web", "gemeente": "Aadorp", "naam": "Isolatiesubsidie Aadorp",
               "bron_url": "https://www.aadorp.nl/isolatie", "status": "onbekend", "criteria": {}}
        run.OUT.write_text(json.dumps([web]))
        run.WEB_STATE.write_text(json.dumps({n: {"datum": run.VANDAAG, "gevonden": 0} for n in GEMEENTEN}))
        pogingen = []
        oud = run.lees_webregeling
        run.lees_webregeling = lambda naam, g, url: (pogingen.append(url), ({}, None))[1]
        try:
            run.main()
            run.main()
        finally:
            run.lees_webregeling = oud
        self.assertEqual(len(pogingen), 1)
        self.assertEqual(json.loads(run.OUT.read_text())[0]["voorwaarden_gelezen"], run.VANDAAG)
