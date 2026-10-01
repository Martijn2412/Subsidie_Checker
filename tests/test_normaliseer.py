"""Draaien: python -m unittest discover tests"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scraper"))
from normaliseer import getal, normaliseer  # noqa: E402


class TestGetal(unittest.TestCase):
    def test_bedragen(self):
        for invoer, verwacht in [("500000", 500000), ("€ 390.000", 390000), ("€ 390.000,-", 390000),
                                 (477000.0, 477000), ("€ 500.000,00", 500000), ("€ 6,2 mln", 6200000),
                                 (350000, 350000), ("geen", None), (None, None)]:
            self.assertEqual(getal(invoer), verwacht, invoer)


class TestNormaliseer(unittest.TestCase):
    def test_criteria(self):
        r = normaliseer({"id": "x", "criteria": {"woz_max": "500000", "eigenaar_bewoner": "ja", "vve": "Nee",
                                                 "isolatiestaat": {"regels": [{"labels": ["d", "geen"], "bouwdelen_min": "2"}]}}})
        c = r["criteria"]
        self.assertEqual(c["woz_max"], 500000)
        self.assertIs(c["eigenaar_bewoner"], True)
        self.assertEqual(c["vve"], "nee")
        self.assertEqual(c["isolatiestaat"]["regels"], [{"labels": ["D", "geen"], "bouwdelen_min": 2}])

    def test_spuk_definitie(self):
        r = normaliseer({"criteria": {"isolatiestaat": {"omschrijving": "Slecht geïsoleerde woning zoals gedefinieerd in de Regeling SPUK LAI", "regels": []}}})
        iso = r["criteria"]["isolatiestaat"]
        self.assertEqual(iso["regels"], [{"labels": ["D", "E", "F", "G"]}, {"bouwdelen_min": 2}])
        self.assertIn("afgeleid", iso)

    def test_zonder_criteria_ongemoeid(self):
        r = {"id": "web-1", "naam": "x"}
        self.assertEqual(normaliseer(r), r)


if __name__ == "__main__":
    unittest.main()
