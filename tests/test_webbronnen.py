"""Test van het zoeken buiten het CVDR (scraper/webbronnen.py) met een nagebootst internet:
gemeentesite met sitemap, partners, doorgelinkte pdf, AI-zoekactie en de controle op verzinnen.
Draaien: python -m unittest discover tests"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scraper"))
import webbronnen as wb  # noqa: E402


def maak_pdf(tekst):
    """Een minimale pdf met één regel tekst (genoeg voor pypdf)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({tekst}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    uit, plekken = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        plekken.append(len(uit))
        uit += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(uit)
    uit += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    uit += b"".join(b"%010d 00000 n \n" % p for p in plekken)
    uit += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return uit


class Antwoord:
    def __init__(self, url, body, soort="text/html", status=200):
        self.url, self.status_code = url, status
        self.content = body if isinstance(body, bytes) else body.encode()
        self.text = self.content.decode("utf-8", "ignore")
        self.headers = {"content-type": soort}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error")


PAGINA = "<html><head><title>{t}</title></head><body><nav>menu subsidie isolatie</nav><main>{m}</main></body></html>"
VULLING = " Lees hier alles over deze regeling voor inwoners." * 20

WEB = {
    "https://www.testdorp.nl/robots.txt": ("text/plain", "User-agent: *\nSitemap: https://www.testdorp.nl/sm-index.xml"),
    "https://www.testdorp.nl/sm-index.xml": ("application/xml",
        "<sitemapindex><sitemap><loc>https://www.testdorp.nl/sm-1.xml</loc></sitemap></sitemapindex>"),
    "https://www.testdorp.nl/sm-1.xml": ("application/xml", "<urlset>" + "".join(
        f"<url><loc>https://www.testdorp.nl/{p}</loc></url>" for p in
        ["wonen/subsidie-isolatie-eigen-woning", "afval/containers", "nieuws/raadsvergadering",
         "wonen/duurzaam-wonen", "ondernemen/subsidie-isolatie-bedrijfspand"]) + "</urlset>"),
    "https://www.testdorp.nl/wonen/subsidie-isolatie-eigen-woning": ("text/html", PAGINA.format(
        t="Subsidie isolatie eigen woning", m="<h1>Subsidie voor isolatie</h1><p>Woningeigenaren in Testdorp krijgen "
        "maximaal € 1.500 subsidie voor het isoleren van de eigen woning. De WOZ-waarde is maximaal € 450.000.</p>"
        '<a href="/wonen/voorwaarden-isolatiesubsidie.pdf">Voorwaarden isolatiesubsidie (pdf)</a>'
        '<a href="/afval">Afval</a>' + VULLING)),
    "https://www.testdorp.nl/wonen/voorwaarden-isolatiesubsidie.pdf": ("application/pdf",
        maak_pdf("Aanvragen kan tot en met 31 december 2027 voor isolatie van de woning")),
    "https://www.testdorp.nl/wonen/duurzaam-wonen": ("text/html", PAGINA.format(
        t="Duurzaam wonen", m="<p>Tips om energie te besparen in huis." + VULLING + "</p>")),
    "https://regionaalenergieloket.nl/gemeenten": ("text/html", PAGINA.format(t="Gemeenten", m=(
        '<a href="https://testdorp.regionaalenergieloket.nl/">Testdorp</a>'
        '<a href="https://anderdorp.regionaalenergieloket.nl/">Anderdorp</a>'))),
    "https://testdorp.regionaalenergieloket.nl/": ("text/html", PAGINA.format(
        t="Energieloket Testdorp", m="<p>Isolatieactie Testdorp: inwoners krijgen korting op spouwmuurisolatie van hun "
        "woning. Aanmelden via het loket.</p>" + VULLING)),
    "https://anderdorp.regionaalenergieloket.nl/": ("text/html", PAGINA.format(
        t="Energieloket Anderdorp", m="<p>Isolatieactie Anderdorp met korting voor de woning.</p>" + VULLING)),
}


def nep_haal(url, timeout=30):
    if url not in WEB:
        return Antwoord(url, "niet gevonden", status=404)
    soort, body = WEB[url]
    return Antwoord(url, body, soort)


class TestWebbronnen(unittest.TestCase):
    def setUp(self):
        self.echt, self.pauze = wb.haal, wb.PAUZE
        wb.haal, wb.PAUZE = nep_haal, 0

    def tearDown(self):
        wb.haal, wb.PAUZE = self.echt, self.pauze

    def test_register_overheidsorganisaties(self):
        xml = ("<p:organisaties><p:organisatie p:id='1'><p:naam>Gemeente Testdorp</p:naam>"
               "<p:internetadres><p:url>https://www.testdorp.nl/</p:url></p:internetadres></p:organisatie>"
               "<p:organisatie p:id='2'><p:naam>Gemeenteraad Testdorp</p:naam><p:url>https://raad.nl</p:url></p:organisatie>"
               "<p:organisatie p:id='3'><p:naam>Gemeente Súdwest-Fryslân</p:naam><p:url>https://sudwestfryslan.nl</p:url>"
               "</p:organisatie></p:organisaties>")
        sites = wb.lees_roo(xml)
        self.assertEqual(sites["testdorp"], "https://www.testdorp.nl")
        self.assertEqual(sites["sudwest fryslan"], "https://sudwestfryslan.nl")
        self.assertEqual(len(sites), 2)   # de gemeenteraad is geen gemeente
        self.assertEqual(wb.vind_site("Súdwest-Fryslân", sites), "https://sudwestfryslan.nl")

    def test_sitemap_kiest_isolatiepagina(self):
        urls, bron, aantal = wb.kandidaten_gemeentesite("https://www.testdorp.nl")
        self.assertEqual(bron, "sitemap")
        self.assertEqual(aantal, 5)
        self.assertEqual(urls[0], "https://www.testdorp.nl/wonen/subsidie-isolatie-eigen-woning")
        self.assertNotIn("https://www.testdorp.nl/afval/containers", urls)
        self.assertNotIn("https://www.testdorp.nl/ondernemen/subsidie-isolatie-bedrijfspand", urls)

    def test_rondgang_zonder_sitemap(self):
        WEB["https://www.zondersitemap.nl"] = ("text/html", PAGINA.format(t="Home", m=(
            '<a href="/subsidies/isolatie">Subsidie isolatie</a><a href="/afval">Afval</a>')))
        try:
            urls, bron, aantal = wb.kandidaten_gemeentesite("https://www.zondersitemap.nl")
        finally:
            del WEB["https://www.zondersitemap.nl"]
        self.assertEqual(bron, "rondgang")
        self.assertEqual(urls, ["https://www.zondersitemap.nl/subsidies/isolatie"])

    def test_verzamel_site_partner_en_pdf(self):
        partners = wb.Partners([{"naam": "Regionaal Energieloket", "index": ["https://regionaalenergieloket.nl/gemeenten"],
                                 "sjablonen": ["https://{slug}.regionaalenergieloket.nl/isolatieacties"]}])
        uit = wb.verzamel("Testdorp", "Gelderland", "https://www.testdorp.nl", partners)
        urls = [p["url"] for p in uit["paginas"]]
        self.assertIn("https://www.testdorp.nl/wonen/subsidie-isolatie-eigen-woning", urls)
        self.assertIn("https://testdorp.regionaalenergieloket.nl/", urls)          # partner via de lijst van gemeenten
        self.assertNotIn("https://anderdorp.regionaalenergieloket.nl/", urls)      # andere gemeente niet
        self.assertNotIn("https://www.testdorp.nl/wonen/duurzaam-wonen", urls)     # geen geld voor isolatie
        self.assertEqual(uit["verslag"]["partners"], ["Regionaal Energieloket"])
        self.assertFalse(uit["verslag"]["ai_gezocht"])
        site = next(p for p in uit["paginas"] if "testdorp.nl/wonen" in p["url"])
        self.assertIn("31 december 2027", site["tekst"])                          # pdf met voorwaarden is meegelezen
        self.assertNotIn("menu subsidie", site["tekst"])                           # menu niet
        tekst = wb.samengevoegd(uit["paginas"])
        self.assertIn("=== Pagina: https://www.testdorp.nl/wonen/subsidie-isolatie-eigen-woning", tekst)
        self.assertEqual(wb.tekst_hash(uit["paginas"]), wb.tekst_hash(list(reversed(uit["paginas"]))))

    def test_ai_zoekactie_alleen_als_niets_gevonden_en_met_echte_bronnen(self):
        vragen = []

        def zoek(prompt):
            vragen.append(prompt)
            return ('{"regelingen": [{"naam": "Verzonnen", "url": "https://verzonnen.nl/regeling"}]}',
                    ["https://testdorp.regionaalenergieloket.nl/"])
        uit = wb.verzamel("Testdorp", "Gelderland", None, None, zoek_functie=zoek, parse_json=__import__("json").loads)
        self.assertEqual(len(vragen), 1)
        self.assertIn("Regionaal Energieloket", vragen[0])
        self.assertTrue(uit["verslag"]["ai_gezocht"])
        self.assertEqual([p["url"] for p in uit["paginas"]], ["https://testdorp.regionaalenergieloket.nl/"])  # verzonnen link valt af
        # wel iets gevonden op de site: geen AI-zoekactie (tenzij ai_altijd)
        vragen.clear()
        wb.verzamel("Testdorp", "Gelderland", "https://www.testdorp.nl", None, zoek_functie=zoek, parse_json=__import__("json").loads)
        self.assertEqual(vragen, [])

    def test_bewijs_controle(self):
        tekst = "Woningeigenaren krijgen maximaal € 1.500 subsidie. De WOZ-waarde is maximaal € 450.000 (peildatum 1-1-2025)."
        rec = {"bewijs": {"bedrag": "maximaal €1.500 subsidie", "criteria.woz_max": "De WOZ-waarde is maximaal 450.000",
                          "looptijd_eind": "aanvragen kan tot 1 juli 2026"}}
        uit = wb.controleer_bewijs(rec, tekst)
        self.assertEqual(uit["gecontroleerd"], 3)
        self.assertEqual(uit["niet_gevonden"], ["looptijd_eind"])
        self.assertEqual(wb.controleer_bewijs({}, tekst), {"gecontroleerd": 0, "niet_gevonden": []})

    def test_dezelfde_regeling_herkennen(self):
        self.assertTrue(wb.lijkt_op("Subsidieregeling isolatie eigen woning Testdorp 2025",
                                    "Subsidie isolatie eigen woning", "Testdorp"))
        self.assertFalse(wb.lijkt_op("Duurzaamheidslening", "Subsidie isolatie eigen woning", "Testdorp"))

    def test_slug_en_norm(self):
        self.assertEqual(wb.slug("Bergen op Zoom"), "bergen-op-zoom")
        self.assertEqual(wb.slug("'s-Hertogenbosch"), "s-hertogenbosch")
        self.assertEqual(wb.norm("Hengelo (O)"), "hengelo")


if __name__ == "__main__":
    unittest.main()
