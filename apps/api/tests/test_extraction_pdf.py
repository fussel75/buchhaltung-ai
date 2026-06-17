from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from app.services import extraction as extraction_service
from app.services.extraction import _build_pdf_text_result


TENANT_PROFILE = {
    "assignment_code_label": "Bauvorhaben",
    "assignment_label_singular": "Bauvorhaben",
    "assignment_label_plural": "Bauvorhaben",
    "assignment_code_prefix": "BV",
}


class ExtractionPdfTests(TestCase):
    def test_af_elektro_invoice_reads_reverse_charge_discount_and_project_address(self):
        text = """
        AF-Elektro GmbH
        E-mail: info@af-elektro.de / Tel.:+49(170)4020717
        Rechnung
        Sehr geehrte Damen und Herren,Vielen Dank für Ihren Auftrag, den wir wie folgt in Rechnung stellen:Bauvorhaben:Neusurenland 5122159 Hamburg
        FriStD-Bau ZuB GmbH & Co. KG
        Sachbearbeiter/-in: Artur Franz
        Rechnungs-Nr.: 22198
        Datum: 04.03.2026
        Kunden-Nr.: 1000012214
        Anzahl Bezeichnung Einzelpreis GesamtpreisEinheitPos.
        2. Abschlagsrechnung, gemäß Angebot Nr. 20260009 vom 30.01.2026
        1 560,13 € 560,13 €1 Stk.
        Elektroinstallation gemäß Installationsplan des Küchenbauers
        Summe 3.819,92 €
        Gesamtbetrag 3.819,92 €
        Sie können 3% Skonto abziehen, wenn Sie die Rechnung innerhalb von 5 Tagen auf die unten angegebene Bankverbindung
        überweisen. Zahlbar binnen 10 Tagen ab Rechnungsdatum.
        Steuerschuldnerschaft des Leistungsempfängers: Die Rechnung ist gemäß §13b Umsatzsteuergesetz netto.
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "22198.pdf",
            "content_type": "application/pdf",
            "storage_path": "af-elektro.pdf",
            "size_bytes": 367000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "AF-Elektro GmbH")
        self.assertEqual(result["invoice_number"], "22198")
        self.assertEqual(result["customer_number"], "1000012214")
        self.assertEqual(result["invoice_date"], "2026-03-04")
        self.assertEqual(result["due_date"], "2026-03-14")
        self.assertEqual(result["discount_due_date"], "2026-03-09")
        self.assertEqual(result["discount_percent"], Decimal("3.00"))
        self.assertEqual(result["discount_amount"], Decimal("114.60"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("3705.32"))
        self.assertEqual(result["delivery_address"], "Neusurenland 51, 22159 Hamburg")
        self.assertEqual(result["cost_category"], "subcontractor")
        self.assertEqual(result["product_name"], "2. Abschlagsrechnung, gemäß Angebot Nr. 20260009 vom 30.01.2026")
        self.assertEqual(result["net_amount"], Decimal("3819.92"))
        self.assertEqual(result["tax_amount"], Decimal("0.00"))
        self.assertEqual(result["gross_amount"], Decimal("3819.92"))
        self.assertNotIn("MwSt", " ".join(result["warnings"]))

    def test_a_franz_invoice_reads_reverse_charge_due_date_and_product(self):
        text = """
        A. Franz Elektrotechnik
        E-mail: info@af-elektro.de
        Rechnung
        Sehr geehrte Damen und Herren,Vielen Dank für Ihren Auftrag, den wir wie folgt in Rechnung stellen:Bauvorhabem:Süderfeldstraße 46a 22529 Hamburg
        FriStD-Bau ZuB GmbH & Co. KG
        Rechnungs-Nr.: 21953
        Datum: 03.11.2025
        Kunden-Nr.: 1000012214
        Anzahl Bezeichnung Einzelpreis GesamtpreisEinheitPos.
        1,5 49,50 € 74,25 €1 Std.
        Überprüfung und Fehlersuche am Heizkreisverteiler
        Summe 129,25 €
        Gesamtbetrag 129,25 €
        Bitte überweisen Sie den Betrag von 129,25 € bis zum 10.11.2025, ohne Skontoabzug auf das unten angegebene Konto.
        Steuerschuldnerschaft des Leistungsempfängers: Die Rechnung ist gemäß §13b Umsatzsteuergesetz netto.
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "21953.pdf",
            "content_type": "application/pdf",
            "storage_path": "a-franz.pdf",
            "size_bytes": 359000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "A. Franz Elektrotechnik")
        self.assertEqual(result["invoice_number"], "21953")
        self.assertEqual(result["invoice_date"], "2025-11-03")
        self.assertEqual(result["due_date"], "2025-11-10")
        self.assertEqual(result["delivery_address"], "Süderfeldstraße 46a, 22529 Hamburg")
        self.assertEqual(result["cost_category"], "subcontractor")
        self.assertEqual(result["product_name"], "Überprüfung und Fehlersuche am Heizkreisverteiler")
        self.assertEqual(result["net_amount"], Decimal("129.25"))
        self.assertEqual(result["tax_amount"], Decimal("0.00"))
        self.assertEqual(result["gross_amount"], Decimal("129.25"))
        self.assertNotIn("MwSt", " ".join(result["warnings"]))

    def test_eindruck24_invoice_reads_glued_header_totals_and_first_item(self):
        text = """
        Ch. Werner - Eindruck24Eimsbütteler Straße 3422769 HamburgDeutschland
        Eindruck24 · Eimsbütteler Straße 34 · 22769 HamburgFriStD-Bau ZuB GmbH & Co.KG
        Eindruck24BuchhaltungEimsbütteler Straße 3422769 HamburgTel: 04072379500E-Mail: buchhaltung@eindruck24.de
        RechnungPos.MengeArt.-Nr.BezeichnungMwSt.Preis nettoG.Preis netto13,00StkSTTU171C0021LSparker 2.0 Black - L19,00 %8,94 €26,81 €26,00StkE241199DTG Druck bis DIN-A4 mitVorbehandlung19,00 %5,67 €34,02 €31,00SPS - UPS Standard19,00 %8,50 €8,50 €
        Gesamt Netto (19,00 %)69,34 €zzgl. MwSt (19,00 %)13,17 €Rechnungsbetrag82,51 €Zahlbetrag82,51 €
        Rechnungs-Nr:E24-12568-REDatum:06.01.2026Leistungs- / Lieferdatum:06.01.2026Kunden-Nr:E24-1071-KDAuftrag:E24-17451-AT
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Invoice E24-12568-RE.pdf",
            "content_type": "application/pdf",
            "storage_path": "eindruck24.pdf",
            "size_bytes": 116639,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Eindruck24")
        self.assertEqual(result["invoice_number"], "E24-12568-RE")
        self.assertEqual(result["customer_number"], "E24-1071-KD")
        self.assertEqual(result["invoice_date"], "2026-01-06")
        self.assertEqual(result["cost_category"], "general_overhead")
        self.assertEqual(result["product_name"], "Sparker 2.0 Black - L")
        self.assertEqual(result["net_amount"], Decimal("69.34"))
        self.assertEqual(result["tax_amount"], Decimal("13.17"))
        self.assertEqual(result["gross_amount"], Decimal("82.51"))
        self.assertEqual(result["assignment_type"], "general_cost")
        self.assertEqual(
            result["normalized_filename"],
            "ERg E24-12568-RE, Allgemeine Kosten, Eindruck24, Sparker 2.0 Black - L, 2026-01-06.pdf",
        )
        self.assertEqual(result["warnings"], [])

    def test_eindruck24_invoice_reads_flex_item(self):
        text = """
        Ch. Werner - Eindruck24Eimsbütteler Straße 3422769 HamburgDeutschland
        Eindruck24BuchhaltungEimsbütteler Straße 3422769 HamburgTel: 04072379500E-Mail: buchhaltung@eindruck24.de
        RechnungPos.MengeArt.-Nr.BezeichnungMwSt.Preis nettoG.Preis netto13,00StkE241262Flex Medium 2C bis DIN-A3+19,00 %12,50 €37,50 €21,00SPS - UPS Standard19,00 %8,50 €8,50 €
        Gesamt Netto (19,00 %)46,00 €zzgl. MwSt (19,00 %)8,74 €Rechnungsbetrag54,75 €Zahlbetrag54,75 €
        Rechnungs-Nr:E24-12540-REDatum:29.12.2025Leistungs- / Lieferdatum:29.12.2025Kunden-Nr:E24-1071-KDAuftrag:E24-17354-AT
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Invoice E24-12540-RE.pdf",
            "content_type": "application/pdf",
            "storage_path": "eindruck24-flex.pdf",
            "size_bytes": 116538,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["invoice_number"], "E24-12540-RE")
        self.assertEqual(result["invoice_date"], "2025-12-29")
        self.assertEqual(result["product_name"], "Flex Medium 2C bis DIN-A3+")
        self.assertEqual(result["net_amount"], Decimal("46.00"))
        self.assertEqual(result["tax_amount"], Decimal("8.74"))
        self.assertEqual(result["gross_amount"], Decimal("54.75"))

    def test_ibe_primecard_invoice_reads_mixed_tax_totals_and_product(self):
        text = """
        I.B.E. Institut für betriebliches Entgeltmanagement GmbH | Marienstr. 14-16 | 80331 München
        FriStD-Bau ZuB GmbH & Co.KG
        Haldesdorfer Straße 44
        22179 Hamburg
        München, 28.01.2026
        Rechnungsnummer: SU01764-26-01a
        Kundennummer: U01764
        Leistungszeitraum: Januar 2026 / Benefitbuchung: Januar 2026
        Nr. Beschreibung Anzahl Einzelpreis Gesamtpreis MwSt
        1. Ladebetrag PRIMECARD - Sachbezug 4 50,00 € 200,00 € 0 %
        2. Ladegebühr PRIMECARD - Sachbezug 4 2,50 € 10,00 € 19 %
        Nettobetrag 0 % 200,00 €
        Nettobetrag 19 % 10,00 €
        Mehrwertsteuer 19 % 1,90 €
        Rechnungsbetrag 211,90 €
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung-SU01764-26-01a.pdf",
            "content_type": "application/pdf",
            "storage_path": "ibe-primecard.pdf",
            "size_bytes": 16722,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "I.B.E. Institut für betriebliches Entgeltmanagement GmbH")
        self.assertEqual(result["invoice_number"], "SU01764-26-01a")
        self.assertEqual(result["customer_number"], "U01764")
        self.assertEqual(result["invoice_date"], "2026-01-28")
        self.assertIsNone(result["due_date"])
        self.assertEqual(result["product_name"], "Ladebetrag PRIMECARD - Sachbezug")
        self.assertEqual(result["cost_category"], "general_overhead")
        self.assertEqual(result["assignment_type"], "general_cost")
        self.assertEqual(result["net_amount"], Decimal("210.00"))
        self.assertEqual(result["tax_amount"], Decimal("1.90"))
        self.assertEqual(result["gross_amount"], Decimal("211.90"))
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            result["normalized_filename"],
            "ERg SU01764-26-01a, Allgemeine Kosten, I.B.E. Institut für betriebliches Entgeltmanagement GmbH, Ladebetrag PRIMECARD - Sachbezug, 2026-01-28.pdf",
        )

    def test_ibe_primecard_gift_invoice_reads_low_mixed_tax_total(self):
        text = """
        I.B.E. Institut für betriebliches Entgeltmanagement GmbH | Marienstr. 14-16 | 80331 München
        München, 28.01.2026
        Rechnungsnummer: SU01764-26-01b
        Kundennummer: U01764
        Nr. Beschreibung Anzahl Einzelpreis Gesamtpreis MwSt
        1. Ladebetrag PRIMECARD - Geschenk 1 60,00 € 60,00 € 0 %
        2. Ladegebühr PRIMECARD - Geschenk 1 2,50 € 2,50 € 19 %
        Nettobetrag 0 % 60,00 €
        Nettobetrag 19 % 2,50 €
        Mehrwertsteuer 19 % 0,48 €
        Rechnungsbetrag 62,98 €
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung-SU01764-26-01b.pdf",
            "content_type": "application/pdf",
            "storage_path": "ibe-primecard-gift.pdf",
            "size_bytes": 16716,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["invoice_number"], "SU01764-26-01b")
        self.assertEqual(result["product_name"], "Ladebetrag PRIMECARD - Geschenk")
        self.assertEqual(result["net_amount"], Decimal("62.50"))
        self.assertEqual(result["tax_amount"], Decimal("0.48"))
        self.assertEqual(result["gross_amount"], Decimal("62.98"))

    def test_roggemann_invoice_reads_header_totals_discount_and_assignment_hint(self):
        text = """
        Enno Roggemann GmbH & Co. KG
        www.roggemann.de
        Datum
        RechnungsNr.: 26107466 26.05.26
        Kunden-Nr. .: 0088163
        R e c h n u n g
        Betr.Lieferscheinnr.: 008118 vom/am 22.05.26 Auftragsnr.: 015012/00/26 / las
        Ihre Kommission: Weseler Weg
        Anlieferung . .:
        0178/6665994
        Weseler Weg 20                      D   22045   Hamburg
        0020 303015340191055 1
        Cape Cod Unterschlagsprofil    13,7cm   19,0mm
        Zahlung . . . .:
        bis 17.06.26 mit 3 % Skonto    =     1325,35  EURNetto-Betrag EUR      1145,96
        bis 26.06.26 netto             =     1363,69  EUR 19,00 % MWSt EUR       217,73
        Gesamtbetrag EUR      1363,69
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "R-26107466-0088163.pdf",
            "content_type": "application/pdf",
            "storage_path": "roggemann.pdf",
            "size_bytes": 270000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Enno Roggemann GmbH & Co. KG")
        self.assertEqual(result["document_type"], "incoming_invoice")
        self.assertEqual(result["invoice_number"], "26107466")
        self.assertEqual(result["customer_number"], "0088163")
        self.assertEqual(result["invoice_date"], "2026-05-26")
        self.assertEqual(result["due_date"], "2026-06-26")
        self.assertEqual(result["discount_due_date"], "2026-06-17")
        self.assertEqual(result["discount_amount"], Decimal("38.34"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("1325.35"))
        self.assertEqual(result["delivery_address"], "Weseler Weg 20, 22045 Hamburg")
        self.assertEqual(result["customer_reference"], "Weseler Weg")
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["product_name"], "Cape Cod Unterschlagsprofil 13,7cm 19,0mm")
        self.assertEqual(result["net_amount"], Decimal("1145.96"))
        self.assertEqual(result["tax_amount"], Decimal("217.73"))
        self.assertEqual(result["gross_amount"], Decimal("1363.69"))

    def test_roggemann_credit_note_reads_negative_amounts_and_pickup_address(self):
        text = """
        Enno Roggemann GmbH & Co. KG
        www.roggemann.de
        Datum
        RechnungsNr.: 25117978 10.12.25
        Kunden-Nr. .: 0088163
        Rücklieferungs Gutschrift
        Abholung  . . .:
        0174/2778822
        Bucheckerweg 4                      D   22175   Hamburg
        0020 303021051221036 1
        Fasebretter    12,1cm   22,5mm
        Zahlung . . . .:
        bis  1.01.26 mit 3 % Skonto    =       47,37- EURNetto-Betrag EUR        41,04-
        bis 10.01.26 netto             =       48,84- EUR 19,00 % MWSt EUR         7,80-
        Gesamtbetrag EUR        48,84-
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "R-25117978-0088163.pdf",
            "content_type": "application/pdf",
            "storage_path": "roggemann-credit.pdf",
            "size_bytes": 268000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Enno Roggemann GmbH & Co. KG")
        self.assertEqual(result["document_type"], "credit_note")
        self.assertEqual(result["invoice_number"], "25117978")
        self.assertEqual(result["invoice_date"], "2025-12-10")
        self.assertEqual(result["due_date"], "2026-01-10")
        self.assertEqual(result["discount_due_date"], "2026-01-01")
        self.assertEqual(result["discount_amount"], Decimal("-1.47"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("-47.37"))
        self.assertEqual(result["delivery_address"], "Bucheckerweg 4, 22175 Hamburg")
        self.assertEqual(result["product_name"], "Fasebretter 12,1cm 22,5mm")
        self.assertEqual(result["net_amount"], Decimal("-41.04"))
        self.assertEqual(result["tax_amount"], Decimal("-7.80"))
        self.assertEqual(result["gross_amount"], Decimal("-48.84"))

    def test_bueroshop24_invoice_reads_header_totals_and_product(self):
        text = """
        GiroCode
        FriStD-Bau ZuB GmbH & Co. KG
        Haldesdorfer Str. 44
        22179 Hamburg
        büroshop24 GmbH
        www.bueroshop24.de
        kundenservice@bueroshop24.de
        Rechnung
        Rechnungs-Nr. Kunden-Nr. Rg.-/Liefer-Datum Auftrags-Nr. Besteller/Bestell-Nr. Paket-Nr.
        Ronny Friedrich
        150975289 56348194 16.06.2026 807391992 228614358
        Zahlung per PayPal
        Bestell-Nr. Menge Artikelbezeichnung Einzelpreis Gesamtpreis USt.
        KZ
        Bemerkung
        371 409-79 2 EPSON Tinte M 35/T3583 26,99 53,98 1
        Versandkosten 5,29
        Zahlartgebühr Warenwert Netto Gesamt-Netto USt.-Betrag % USt. Rg.-Betrag EUR
        53,98 59,27 11,26 19 70,53 1
        Verwendungszweck:
        Rg. 150975289, Kd. 56348194
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung_0150975289.pdf",
            "content_type": "application/pdf",
            "storage_path": "bueroshop.pdf",
            "size_bytes": 88000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "büroshop24 GmbH")
        self.assertEqual(result["invoice_number"], "150975289")
        self.assertEqual(result["customer_number"], "56348194")
        self.assertEqual(result["invoice_date"], "2026-06-16")
        self.assertEqual(result["net_amount"], Decimal("59.27"))
        self.assertEqual(result["tax_amount"], Decimal("11.26"))
        self.assertEqual(result["gross_amount"], Decimal("70.53"))
        self.assertIsNone(result["assignment_code"])
        self.assertEqual(result["assignment_type"], "general_cost")
        self.assertEqual(result["cost_category"], "general_overhead")
        self.assertEqual(result["product_name"], "EPSON Tinte M 35/T3583")

    def test_bueroshop24_invoice_reads_due_date_when_present(self):
        text = """
        büroshop24 GmbH
        www.bueroshop24.de
        Rechnung
        Rechnungs-Nr. Kunden-Nr. Rg.-/Liefer-Datum Auftrags-Nr. Besteller/Bestell-Nr. Paket-Nr.
        Ronny Friedrich
        147460802 56348194 03.09.2025 804733702 223465245
        Bestell-Nr. Menge Artikelbezeichnung Einzelpreis Gesamtpreis USt.
        KZ
        Bemerkung
        371 409-79 1 EPSON Tinte M 35/T3583 26,99 26,99 1
        Versandkosten 4,19
        Kleinmengenzuschlag 2,99
        Zahlartgebühr Warenwert Netto Gesamt-Netto USt.-Betrag % USt. Rg.-Betrag EUR
        Zahlbar bis
        26,99 34,17 6,49 19 40,66 1 03.10.2025
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung_0147460802.pdf",
            "content_type": "application/pdf",
            "storage_path": "bueroshop.pdf",
            "size_bytes": 88000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["invoice_number"], "147460802")
        self.assertEqual(result["invoice_date"], "2025-09-03")
        self.assertEqual(result["due_date"], "2025-10-03")
        self.assertEqual(result["net_amount"], Decimal("34.17"))
        self.assertEqual(result["tax_amount"], Decimal("6.49"))
        self.assertEqual(result["gross_amount"], Decimal("40.66"))

    def test_arens_stitz_invoice_reads_header_totals_and_assignment(self):
        text = """
        R E C H N U N G
        Bei Schriftwechsel bitte angeben
        KD-Nr. Rechn.Nr.   Datum    Blatt
        480 FRHA05   8221927 03.06.2026   1
        FriStD-Bau ZuB GmbH & Co. KG
        kevin.thon@gc-gruppe.de
        Artikel                           Menge     ME       Preis    Pos/Wert
        Lieferung 108 51141749-001 vom 03.06.2026 Abholung
        Kommissions Pflicht !!!!
        AUFTR.TEXT: Heukoppel 92
        AUFTR.NR. : --
        CTS230N      4,000 ST      10,62       42,48
        COSMO Standard Stellantrieb 230V IP54 Netto
        M30x1,5mm, stroml. zu, man. Arretierung
        Transportsicherung         0,64 *
        Zahlbar bis 19.06.2026  2,00% Skt= 50,28 Warenwert :       43,12 EUR
        Zahlbar bis 05.07.2026 ohne Abzug  19,00%MWST:        8,19 EUR
        Skontofähiger Betrag :        51,31 ------------
            Gesamt:       51,31 EUR
        05.06.2026 ============
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "RG_480_FRHA05_8221927.pdf",
            "content_type": "application/pdf",
            "storage_path": "stitz.pdf",
            "size_bytes": 88000,
            "sha256": "abc",
        }
        assignment = {
            "code": "Hk92",
            "label": "Heukoppel 92",
            "kind": "construction_project",
            "project_number": "26-00007",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text == "Heukoppel 92":
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Arens & Stitz KG")
        self.assertEqual(result["invoice_number"], "8221927")
        self.assertEqual(result["customer_number"], "FRHA05")
        self.assertEqual(result["customer_reference"], "Heukoppel 92")
        self.assertEqual(result["assignment_code"], "Hk92")
        self.assertEqual(result["project_number"], "26-00007")
        self.assertEqual(result["invoice_date"], "2026-06-03")
        self.assertEqual(result["discount_due_date"], "2026-06-19")
        self.assertEqual(result["due_date"], "2026-07-05")
        self.assertEqual(result["net_amount"], Decimal("43.12"))
        self.assertEqual(result["tax_amount"], Decimal("8.19"))
        self.assertEqual(result["gross_amount"], Decimal("51.31"))
        self.assertEqual(result["discount_base"], Decimal("51.31"))
        self.assertEqual(result["discount_percent"], Decimal("2.00"))
        self.assertEqual(result["discount_amount"], Decimal("1.03"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("50.28"))
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["product_name"], "COSMO Standard Stellantrieb 230V IP54 Netto")

    def test_pietsch_invoice_reads_commission_and_discount_terms(self):
        text = """
        Pos Material Menge ME E-Preis PE Betrag
        Lieferschein: 721674439 Lieferung: 11.06.2026
        Auftrag: 116527756 Bestelldatum: 10.06.2026
        Projekt:
        Kommissionsangaben: Weseler Weg 20
        Lieferadresse:
        FriStD-Bau ZuB GmbH & Co. KG
        Weseler Weg 20
        22045 Hamburg
        10 320101000                5 M         6,33 1         31,65  EUR
        RAL Kupferrohr 15 x 1,0 mm, korr.-gesch.
        halbhart, DVGW, (Stange: 5 Meter), je M.
        Pietsch Hamburg-Ost Damaschke GmbH & Co. KG
        Rechnung Datum Seite
        407437077 17.06.2026 1  /  2
        Kunde: 321940
        Gesamtwert        82,60  EUR
        Umsatzsteuer     19,00 % auf       82,60        15,69  EUR
        Endbetrag        98,29  EUR
        auf den skontierfähigen Betrag (     96,17  EUR )
        Zahlbetrag bis 01.07.2026 3,000 % Skonto                95,40  EUR
        Zahlbetrag bis 17.07.2026 ohne Abzug                98,29  EUR
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung_407437077 an FriStD-Bau ZuB GmbH Co. KG.pdf",
            "content_type": "application/pdf",
            "storage_path": "pietsch.pdf",
            "size_bytes": 236119,
            "sha256": "abc",
        }
        assignment = {
            "code": "Wewe20",
            "label": "Weseler Weg 20",
            "kind": "construction_project",
            "project_number": "25-00008",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text == "Weseler Weg 20":
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Pietsch Hamburg-Ost Damaschke GmbH & Co. KG")
        self.assertEqual(result["invoice_number"], "407437077")
        self.assertEqual(result["customer_number"], "321940")
        self.assertEqual(result["customer_reference"], "Weseler Weg 20")
        self.assertEqual(result["assignment_code"], "Wewe20")
        self.assertEqual(result["project_number"], "25-00008")
        self.assertEqual(result["invoice_date"], "2026-06-17")
        self.assertEqual(result["due_date"], "2026-07-17")
        self.assertEqual(result["discount_due_date"], "2026-07-01")
        self.assertEqual(result["net_amount"], Decimal("82.60"))
        self.assertEqual(result["tax_amount"], Decimal("15.69"))
        self.assertEqual(result["gross_amount"], Decimal("98.29"))
        self.assertEqual(result["discount_base"], Decimal("96.17"))
        self.assertEqual(result["discount_percent"], Decimal("3.00"))
        self.assertEqual(result["discount_amount"], Decimal("2.89"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("95.40"))
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["product_name"], "RAL Kupferrohr 15 x 1,0 mm, korr.-gesch.")

    def test_pietsch_credit_note_keeps_negative_amounts(self):
        text = """
        Pos Material Menge ME E-Preis PE Betrag
        Kommissionsangaben: Heukoppel 92
        10 659422000                1 ST      369,00- 1        369,00- EUR
        REMS Gewindeschneidkluppe eva Set R *
        m. Schneidk. 1/2-3/4-1-1 1/4" # 520015
        Gesamtwert       369,00- EUR
        Umsatzsteuer     19,00 % auf      369,00-        70,11- EUR
        Endbetrag       439,11- EUR
        auf den skontierfähigen Betrag (    439,11  EUR )
        Zahlbetrag bis 14.06.2026 3,000 % Skonto               425,94- EUR
        Zahlbetrag bis 30.06.2026 ohne Abzug               439,11- EUR
        Pietsch Hamburg-Ost Damaschke GmbH & Co. KG
        Retourgutschrift Datum Seite
        407403955 31.05.2026 1  /  1
        Kunde: 321940
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung_407403955 an FriStD-Bau ZuB GmbH Co. KG.pdf",
            "content_type": "application/pdf",
            "storage_path": "pietsch-credit.pdf",
            "size_bytes": 236119,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["document_type"], "credit_note")
        self.assertEqual(result["invoice_number"], "407403955")
        self.assertEqual(result["invoice_date"], "2026-05-31")
        self.assertEqual(result["net_amount"], Decimal("-369.00"))
        self.assertEqual(result["tax_amount"], Decimal("-70.11"))
        self.assertEqual(result["gross_amount"], Decimal("-439.11"))
        self.assertEqual(result["discount_amount"], Decimal("-13.17"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("-425.94"))
        self.assertEqual(result["payment_terms"][0]["label"], "Gutschrift verrechnen")
        self.assertEqual(result["payment_terms"][1]["label"], "Verrechnung mit Skonto")

    def test_dammers_invoice_reads_digital_pdf_text(self):
        text = """
        Auslieferungslager : Barmbek
        Firma                            RECHNUNG
        FriStD-Bau ZuB  GmbH & Co KG
        Haldesdorfer Str. 44
        Nummer         :            773934-606
        Datum          :    05.06.2026 - 14:24
        Kundennummer   :           0515834/086
        ART-NR BEZEICHNUNG                   MENGE    EINZELPREIS RAB    NETTOWERT
        51680                                15,00 m     13,40 m           201,00
        Alu-Dachtraufprofil DP 80
        Hoehe 80 mm Breite 140 mm  3 m
        51681                                    2 St     2,10 St            4,20
        Alu-Stossverbinder f. DP 80
        Summe Warenwert                                            EUR     205,20
        + 19,00 % Mwst.                                            EUR      38,99
        Rechnungsbetrag (zahlbar bis spätestens 06.07.26 o. Abzug) EUR     244,19
        zahlbar bis zum 16.06.26 abzüglich EUR 7,33 Skonto
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "773934-606.pdf",
            "content_type": "application/pdf",
            "storage_path": "dammers.pdf",
            "size_bytes": 236119,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Rolf Dammers oHG")
        self.assertEqual(result["invoice_number"], "773934-606")
        self.assertEqual(result["customer_number"], "0515834/086")
        self.assertEqual(result["invoice_date"], "2026-06-05")
        self.assertEqual(result["due_date"], "2026-07-06")
        self.assertEqual(result["discount_due_date"], "2026-06-16")
        self.assertEqual(result["net_amount"], Decimal("205.20"))
        self.assertEqual(result["tax_amount"], Decimal("38.99"))
        self.assertEqual(result["gross_amount"], Decimal("244.19"))
        self.assertEqual(result["discount_base"], Decimal("244.19"))
        self.assertEqual(result["discount_amount"], Decimal("7.33"))
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["product_name"], "Alu-Dachtraufprofil DP 80")

    def test_foerch_invoice_uses_filename_and_derives_net_amount(self):
        text = """
        THEO FOERCH GmbH & Co. KG
        Auftragsnummer 108413169
        Kundenreferenz Neusurenland 51
        Kundennummer 425590
        Artikel Schrauben und Befestigungsmaterial
        Rechnungsbetrag 8,77
        MwSt 1,40
        Bei Zahlung bis     Skonto %     Skonto netto €     Skonto MwSt. €     Skonto brutto €     Zahlungsziel Netto bis
        31.05.2026          3,0          0,22                 0,04                0,26                 20.06.2026
        Vielen Dank fuer Ihren Einkauf.
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "FOERCH_Rechnung_3161691971_21.05.2026.PDF",
            "content_type": "application/pdf",
            "storage_path": "foerch.pdf",
            "size_bytes": 37000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Theo Foerch GmbH & Co. KG")
        self.assertEqual(result["invoice_number"], "3161691971")
        self.assertEqual(result["customer_number"], "425590")
        self.assertEqual(result["invoice_date"], "2026-05-21")
        self.assertEqual(result["net_amount"], Decimal("7.37"))
        self.assertEqual(result["tax_amount"], Decimal("1.40"))
        self.assertEqual(result["gross_amount"], Decimal("8.77"))
        self.assertEqual(result["due_date"], "2026-06-20")
        self.assertEqual(result["discount_due_date"], "2026-05-31")
        self.assertEqual(result["discount_percent"], Decimal("3.00"))
        self.assertEqual(result["discount_base"], Decimal("7.37"))
        self.assertEqual(result["discount_net_amount"], Decimal("0.22"))
        self.assertEqual(result["discount_tax_amount"], Decimal("0.04"))
        self.assertEqual(result["discount_gross_amount"], Decimal("0.26"))
        self.assertEqual(result["discount_amount"], Decimal("0.26"))
        self.assertEqual(result["payment_terms"][0]["due_date"], "2026-06-20")
        self.assertEqual(result["payment_terms"][1]["due_date"], "2026-05-31")
        self.assertEqual(result["payment_terms"][1]["amount"], Decimal("8.51"))
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["confidence"], Decimal("0.88"))
        self.assertEqual(result["warnings"], [])

    def test_foerch_invoice_reads_customer_number_and_interleaved_discount_table(self):
        text = """
        THEO FOERCH GmbH & Co. KG
        Kundennummer 425590
        Rechnungsbetrag 8,77
        MwSt 1,40
        Bei Zahlung bis
        31.05.2026
        Skonto %
        3,0
        Skonto netto €
        0,22
        Skonto MwSt. €
        0,04
        Skonto brutto €
        0,26
        Zahlungsziel Netto bis
        20.06.2026
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "FOERCH_Rechnung_3161691971_21.05.2026.PDF",
            "content_type": "application/pdf",
            "storage_path": "foerch.pdf",
            "size_bytes": 37000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["customer_number"], "425590")
        self.assertEqual(result["due_date"], "2026-06-20")
        self.assertEqual(result["discount_due_date"], "2026-05-31")
        self.assertEqual(result["discount_percent"], Decimal("3.00"))
        self.assertEqual(result["discount_net_amount"], Decimal("0.22"))
        self.assertEqual(result["discount_tax_amount"], Decimal("0.04"))
        self.assertEqual(result["discount_gross_amount"], Decimal("0.26"))
        self.assertEqual(result["discount_amount"], Decimal("0.26"))
        self.assertEqual(result["payment_terms"][1]["amount"], Decimal("8.51"))

    def test_customer_reference_assigns_known_construction_project(self):
        text = """
        THEO FOERCH GmbH & Co. KG
        Kundenreferenz
        Neusurenland 51
        Kunden-Nr. Auftraggeber 425590
        Artikel Schrauben und Befestigungsmaterial
        Rechnungsbetrag 8,77
        MwSt 1,40
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "FOERCH_Rechnung_3161691971_21.05.2026.PDF",
            "content_type": "application/pdf",
            "storage_path": "foerch.pdf",
            "size_bytes": 37000,
            "sha256": "abc",
        }
        assignment = {
            "code": "Neula51",
            "label": "Neusurenland 51",
            "kind": "construction_project",
            "project_number": None,
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text == "Neusurenland 51":
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(
                extraction_service,
                "find_supplier_rule",
                return_value={
                    "supplier_name": "Theo Foerch GmbH & Co. KG",
                    "customer_number": None,
                    "default_cost_category": ["material"],
                    "default_assignment_code": "Wewe20",
                },
            ),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
            patch.object(extraction_service, "get_assignment_unit_by_code") as get_by_code,
        ):
            result = _build_pdf_text_result(document)

        get_by_code.assert_not_called()
        self.assertEqual(result["customer_number"], "425590")
        self.assertEqual(result["customer_reference"], "Neusurenland 51")
        self.assertEqual(result["assignment_code"], "Neula51")
        self.assertEqual(result["assignment_label"], "Neusurenland 51")
        self.assertEqual(result["assignment_type"], "assigned")
        self.assertEqual(result["project_code"], "Neula51")

    def test_supplier_rule_default_assignment_does_not_assign_project(self):
        text = """
        Holz Junge GmbH
        Rechnung 26206401
        Kundennummer 109324
        Netto 1.210,95
        MwSt 230,08
        Gesamtbetrag 1.441,03
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Kreditrechnung_26206401_P8X0U9.pdf",
            "content_type": "application/pdf",
            "storage_path": "holz-junge.pdf",
            "size_bytes": 715000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(
                extraction_service,
                "find_supplier_rule",
                return_value={
                    "supplier_name": "Holz Junge GmbH",
                    "customer_number": "109324",
                    "default_cost_category": ["material"],
                    "default_assignment_code": "Wewe20",
                },
            ),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
            patch.object(extraction_service, "get_assignment_unit_by_code") as get_by_code,
        ):
            result = _build_pdf_text_result(document)

        get_by_code.assert_not_called()
        self.assertIsNone(result["assignment_code"])
        self.assertEqual(result["assignment_type"], "general_cost")

    def test_foerch_reads_customer_reference_from_column_text(self):
        text = """
        THEO FOERCH GmbH & Co. KG
        Kundennummer
        Kundenreferenz
        425590
        Neusurenland 51
        Rechnungsbetrag 8,77
        MwSt 1,40
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "FOERCH_Rechnung_3161691971_21.05.2026.PDF",
            "content_type": "application/pdf",
            "storage_path": "foerch.pdf",
            "size_bytes": 37000,
            "sha256": "abc",
        }
        assignment = {
            "code": "Neula51",
            "label": "Neusurenland 51",
            "kind": "construction_project",
            "project_number": None,
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text == "Neusurenland 51":
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["customer_number"], "425590")
        self.assertEqual(result["customer_reference"], "Neusurenland 51")
        self.assertEqual(result["assignment_code"], "Neula51")
