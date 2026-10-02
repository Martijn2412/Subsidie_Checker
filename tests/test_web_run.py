"""Test van de internetstap in run.py: regelingen van de gemeentesite en partners komen in regelingen.json
en de Excel, dezelfde regeling als in het CVDR wordt niet dubbel opgenomen, onjuist 'bewijs' verlaagt de
betrouwbaarheid, en ongewijzigde pagina's gaan niet opnieuw naar het taalmodel.
Alles nagebootst: geen internet, geen taalmodel. Draaien: python -m unittest discover tests"""
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

HIER = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
import test_run_voortgang  # noqa: E402,F401  (zet de nep-'google.genai' klaar)
run = sys.modules["run"]

SITE = "https://www.testdorp.nl/subsidie-isolatie"
LOKET = "https://testdorp.regionaalenergieloket.nl/isolatieacties"
TEKST_SITE = "Subsidie isolatie. Woningeigenaren krijgen maximaal € 1.500 voor isolatie van de eigen woning."
TEKST_LOKET = "Isolatieactie Testdorp: 30% korting op spouwmuurisolatie voor eigenaar-bewoners. Aanmelden tot 1 maart 2027."
CVDR_TEKST = "Subsidie voor isolatie van de eigen woning door de eigenaar. Maximaal € 1.500 per woning."


class TestWebRun(unittest.TestCase):
    def setUp(self):
        self.map = pathlib.Path(tempfile.mkdtemp())
        (self.map / "data").mkdir()
        namen = ["ROOT", "OUT", "DATA", "STATE", "DEKKING", "LOG_ALL", "LOG_LAST", "ZOEKSTATUS", "WEB_STATE",
                 "OVERZICHT", "VOORTGANG", "GEMEENTE_SITES", "zoek_cvdr", "is_vervallen", "haal_tekst",
                 "is_relevant", "extraheer", "extraheer_web", "gemeentelijst"]
        self.oud = {k: getattr(run, k) for k in namen}
        self.oud_web = {k: getattr(run.webbronnen, k) for k in ["verzamel", "haal_roo", "vind_site"]}
        self.oud_cfg = dict(run.CFG)
        for k in ["OUT", "STATE", "DEKKING", "LOG_ALL", "LOG_LAST", "ZOEKSTATUS", "WEB_STATE", "OVERZICHT", "VOORTGANG",
                  "GEMEENTE_SITES"]:
            setattr(run, k, self.map / getattr(run, k).relative_to(run.ROOT))
        run.ROOT, run.DATA = self.map, self.map / "data"
        run.gemeentelijst = lambda: [{"naam": "Testdorp", "provincie": "Gelderland"}]
        run.zoek_cvdr = lambda naam, trefwoorden=None: {"CVDR1": {
            "versie": 1, "titel": "Subsidieregeling isolatie eigen woning Testdorp 2025", "gewijzigd": "2025-01-01",
            "xml_url": "x"}}
        run.is_vervallen = lambda cid: False
        run.haal_tekst = lambda url, pagina=None: CVDR_TEKST
        run.is_relevant = lambda titel, tekst: True
        run.extraheer = lambda tekst: {"naam": "Subsidieregeling isolatie eigen woning Testdorp 2025",
                                       "bedrag": "max. € 1.500", "looptijd_eind": "2030-12-31",
                                       "criteria": {"eigenaar_bewoner": True},
                                       "bewijs": {"bedrag": "Maximaal € 1.500 per woning"}}
        self.web_aanroepen = 0
        run.extraheer_web = self.nep_extraheer_web
        run.webbronnen.verzamel = lambda *a, **kw: {
            "paginas": [{"url": SITE, "tekst": TEKST_SITE, "bron": "gemeentesite"},
                        {"url": LOKET, "tekst": TEKST_LOKET, "bron": "partner: Regionaal Energieloket"}],
            "verslag": {"site": "https://www.testdorp.nl", "site_bron": "sitemap", "site_urls": 120, "kandidaten": 9,
                        "partners": ["Regionaal Energieloket"], "ai_gezocht": False,
                        "paginas": [{"url": SITE, "bron": "gemeentesite"},
                                    {"url": LOKET, "bron": "partner: Regionaal Energieloket"}]}}
        run.webbronnen.haal_roo = lambda: {}
        run.webbronnen.vind_site = lambda *a, **kw: "https://www.testdorp.nl"

    def tearDown(self):
        for k, v in self.oud.items():
            setattr(run, k, v)
        for k, v in self.oud_web.items():
            setattr(run.webbronnen, k, v)
        run.CFG.clear()
        run.CFG.update(self.oud_cfg)
        shutil.rmtree(self.map)

    def nep_extraheer_web(self, gemeente, tekst, bekend):
        self.web_aanroepen += 1
        self.assertIn("Subsidieregeling isolatie eigen woning Testdorp 2025", bekend)
        return [
            {"naam": "Subsidie isolatie", "zelfde_als": "Subsidieregeling isolatie eigen woning Testdorp 2025",
             "bron_url": SITE, "bedrag": "max. € 1.500"},
            {"naam": "Isolatieactie spouwmuur Testdorp", "type": "korting", "bron_url": LOKET,
             "uitvoerder": "Regionaal Energieloket", "bedrag": "30% korting", "looptijd_eind": "2027-03-01",
             "criteria": {"eigenaar_bewoner": True},
             "bewijs": {"bedrag": "30% korting op spouwmuurisolatie", "looptijd_eind": "Aanmelden tot 1 juni 2027"}},
        ]

    def test_internetregelingen_zonder_dubbelen_en_met_bewijscontrole(self):
        run.main()
        regs = {r["id"]: r for r in json.loads(run.OUT.read_text())}
        self.assertEqual(len(regs), 2)                        # CVDR-regeling + één nieuwe van het loket
        cvdr = next(r for r in regs.values() if r["bron"] == "cvdr")
        web = next(r for r in regs.values() if r["bron"] == "web")
        self.assertEqual(cvdr["extra_bronnen"], [SITE])        # gemeentesite noemt dezelfde regeling
        self.assertEqual(cvdr["bewijs_controle"]["niet_gevonden"], [])
        self.assertEqual(web["bron_type"], "partner: Regionaal Energieloket")
        self.assertEqual(web["bron_url"], LOKET)
        self.assertEqual(web["bewijs_controle"]["niet_gevonden"], ["looptijd_eind"])   # "1 juni" staat er niet
        self.assertEqual(web["betrouwbaarheid"], "laag")
        pr = run.LOG_LAST.read_text()
        self.assertIn("Isolatieactie spouwmuur Testdorp", pr)
        self.assertIn("bewijs niet teruggevonden voor looptijd_eind", pr)
        zs = json.loads(run.ZOEKSTATUS.read_text())["gemeenten"][0]
        self.assertEqual(zs["partners"], ["Regionaal Energieloket"])
        self.assertTrue(zs["gemeentesite_doorzocht"])
        self.assertEqual(json.loads(run.DEKKING.read_text())["Testdorp"]["bronnen_gecheckt"],
                         ["CVDR", "gemeentesite", "partners"])

        # volgende run, pagina's ongewijzigd: niet opnieuw naar het taalmodel, uitkomst blijft gelijk
        run.CFG["web_zoeken_elke_dagen"] = 0
        run.main()
        self.assertEqual(self.web_aanroepen, 1)
        regs2 = {r["id"]: r for r in json.loads(run.OUT.read_text())}
        self.assertEqual(set(regs2), set(regs))
        self.assertEqual(next(r for r in regs2.values() if r["bron"] == "cvdr")["extra_bronnen"], [SITE])

    def test_cvdr_onbereikbaar_internet_toch_doorzocht(self):
        run.main()                                            # eerste run: alles gaat goed
        zs = json.loads(run.ZOEKSTATUS.read_text())
        zs["gemeenten"][0]["wacht_op_uitlezen"] = [{"cvdr_id": "CVDR9", "titel": "Isolatieregeling", "gewijzigd": None,
                                                    "bron_url": "https://lokaleregelgeving.overheid.nl/CVDR9/1"}]
        run.ZOEKSTATUS.write_text(json.dumps(zs))

        def stuk(*a, **kw):
            raise ConnectionError("CVDR plat")
        run.zoek_cvdr = stuk
        run.CFG["web_zoeken_elke_dagen"] = 0
        run.main()
        regs = json.loads(run.OUT.read_text())
        self.assertEqual(sorted(r["bron"] for r in regs), ["cvdr", "web"])   # CVDR-regeling blijft, web ook
        self.assertNotIn("Niet meer gevonden", next(r for r in regs if r["bron"] == "cvdr").get("opmerkingen") or "")
        zs = json.loads(run.ZOEKSTATUS.read_text())["gemeenten"][0]
        self.assertEqual(len(zs["wacht_op_uitlezen"]), 1)      # wachtrij niet kwijt
        self.assertEqual(zs["internet_gezocht"], run.VANDAAG)

    def test_excel_laat_zien_wat_doorzocht_is(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest("openpyxl niet geïnstalleerd")
        run.main()
        wb = load_workbook(run.OVERZICHT)
        regels = list(wb["Regelingen"].values)
        kop = regels[0]
        rijen = [dict(zip(kop, r)) for r in regels[1:]]
        web = next(r for r in rijen if r["Bron"] == "partner: Regionaal Energieloket")
        self.assertTrue(web["Bewijs gecontroleerd"].startswith("niet gevonden"))
        cvdr = next(r for r in rijen if r["Bron"] == "CVDR")
        self.assertEqual(cvdr["Ook vermeld op"], SITE)
        g = dict(zip(list(wb["Gemeenten"].values)[0], list(wb["Gemeenten"].values)[1]))
        self.assertEqual(g["Bronnen doorzocht"], "CVDR, gemeentesite, partners")
        self.assertEqual(g["Partners met regeling"], "Regionaal Energieloket")
        self.assertEqual(g["Conclusie"], "regeling gevonden")


if __name__ == "__main__":
    unittest.main()
