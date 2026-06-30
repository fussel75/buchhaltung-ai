from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from app.services import extraction as extraction_service
from app.services.extraction import _build_pdf_text_result


TENANT_PROFILE = {
    "assignment_code_label": "Bauvorhaben",
    "assignment_label_singular": "Bauvorhaben",
    "assignment_label_plural": "Bauvorhaben",
    "assignment_code_prefix": "BV",
}


class ExtractionPdfTests(TestCase):
    def setUp(self):
        self.assignment_match_patcher = patch.object(
            extraction_service,
            "find_assignment_unit_match_by_text",
            return_value=None,
        )
        self.assignment_match_patcher.start()
        self.addCleanup(self.assignment_match_patcher.stop)

    def test_pdf_text_extraction_uses_pymupdf_when_pypdf_text_is_too_short(self):
        pymupdf_text = "DAMMERS\n" + ("Rechnungstext " * 12)

        with (
            patch.object(extraction_service, "_extract_pdf_text_pypdf", return_value=""),
            patch.object(extraction_service, "_extract_pdf_text_pymupdf", return_value=pymupdf_text),
        ):
            text = extraction_service._extract_pdf_text("dammers.pdf")

        self.assertEqual(text, pymupdf_text)
        self.assertEqual(text.source, "pymupdf")

    def test_pdf_text_extraction_uses_ocr_when_regular_text_is_too_short(self):
        ocr_text = "DAMMERS\n" + ("OCR Rechnungstext " * 12)

        with (
            patch.object(extraction_service, "_extract_pdf_text_pypdf", return_value=""),
            patch.object(extraction_service, "_extract_pdf_text_pymupdf", return_value=""),
            patch.object(extraction_service, "_extract_pdf_text_pymupdf_ocr", return_value=ocr_text),
        ):
            text = extraction_service._extract_pdf_text("dammers.pdf")

        self.assertEqual(text, ocr_text)
        self.assertEqual(text.source, "pymupdf_ocr")

    def test_pdf_text_extraction_keeps_regular_text_when_ocr_is_unavailable(self):
        with (
            patch.object(extraction_service, "_extract_pdf_text_pypdf", return_value="kurz"),
            patch.object(extraction_service, "_extract_pdf_text_pymupdf", return_value=""),
            patch.object(extraction_service, "_extract_pdf_text_pymupdf_ocr", return_value=""),
        ):
            text = extraction_service._extract_pdf_text("dammers.pdf")

        self.assertEqual(text, "kurz")
        self.assertEqual(text.source, "pypdf_short")

    def test_pymupdf_ocr_uses_german_and_english_languages(self):
        class FakePdf:
            def __init__(self, pages):
                self.pages = pages

            def __enter__(self):
                return self.pages

            def __exit__(self, exc_type, exc, traceback):
                return False

        with TemporaryDirectory() as tmp_dir:
            Path(tmp_dir, "scan.pdf").write_bytes(b"%PDF")
            page = Mock()
            page.get_textpage_ocr.return_value = "ocr-page"
            page.get_text.return_value = "Rechnung mit Umlauten äöü"
            fake_fitz = SimpleNamespace(open=Mock(return_value=FakePdf([page])))

            with (
                patch.dict("sys.modules", {"fitz": fake_fitz}),
                patch.object(extraction_service, "get_settings", return_value=SimpleNamespace(storage_root=Path(tmp_dir))),
            ):
                text = extraction_service._extract_pdf_text_pymupdf_ocr("scan.pdf")

        self.assertEqual(text, "Rechnung mit Umlauten äöü")
        page.get_textpage_ocr.assert_called_once_with(full=True, dpi=200, language="deu+eng")

    def test_pdf_filename_with_octet_stream_uses_pdf_extraction(self):
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "776511-606.pdf",
            "content_type": "application/octet-stream",
            "storage_path": "dammers.pdf",
            "size_bytes": 236119,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_build_embedded_xml_result", return_value=None),
            patch.object(extraction_service, "_build_pdf_text_result", return_value={"source": "pdf_text_rules"}),
            patch.object(extraction_service, "_build_mock_result", return_value={"source": "mock"}),
        ):
            result = extraction_service._build_extraction_result(document)

        self.assertEqual(result["source"], "pdf_text_rules")

    def test_scanned_dammers_invoice_uses_filename_fallback_without_mock_amounts(self):
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "776511-606.pdf",
            "content_type": "application/pdf",
            "storage_path": "dammers.pdf",
            "created_at": "2026-06-17T10:00:00+00:00",
            "size_bytes": 39494,
            "sha256": "abc",
        }
        supplier_rule = {
            "supplier_name": "Rolf Dammers oHG",
            "customer_number": "0515834/086",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=""),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=supplier_rule),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["source"], "pdf_scan_filename_rules")
        self.assertEqual(result["supplier_name"], "Rolf Dammers oHG")
        self.assertEqual(result["invoice_number"], "776511-606")
        self.assertEqual(result["customer_number"], "0515834/086")
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["assignment_type"], "assignment_unresolved")
        self.assertIsNone(result["net_amount"])
        self.assertIsNone(result["tax_amount"])
        self.assertIsNone(result["gross_amount"])
        self.assertIn("OCR", " ".join(result["warnings"]))
        self.assertEqual(result["confidence"], Decimal("0.50"))
        self.assertEqual(
            result["normalized_filename"],
            "ERg 776511-606, Bauvorhaben ungeklärt, Rolf Dammers oHG, Eingangsrechnung, ohne Datum.pdf",
        )

    def test_unreadable_pdf_does_not_create_mock_amounts(self):
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung_52595092.pdf",
            "content_type": "application/pdf",
            "storage_path": "unreadable.pdf",
            "created_at": "2026-06-17T10:00:00+00:00",
            "size_bytes": 361190,
            "sha256": "abcdef123456",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=""),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["source"], "pdf_unreadable")
        self.assertIsNone(result["net_amount"])
        self.assertIsNone(result["tax_amount"])
        self.assertIsNone(result["gross_amount"])
        self.assertFalse(str(result["invoice_number"] or "").startswith("MOCK-"))
        self.assertEqual(result["confidence"], Decimal("0.20"))
        self.assertIn("OCR", " ".join(result["warnings"]))

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

    def test_mittwald_invoice_reads_hosting_domain_totals_and_direct_debit_date(self):
        text = """
        Mittwald CM Service * Königsberger Straße 4-6 * 32339 Espelkamp
        FriStD-Bau ZuB GmbH & Co.KG
        Rechnung Kunden Nr.: 296313
        Kunden Ust-Nr.: DE276234295
        Rechnung Nr.: 6514767
        Rechnungsdatum: 27.01.2026
        Bitte nicht überweisen:
        Zahlung per Lastschriftverfahren
        Pos. Menge Artikel USt. Einzelpreis
        Netto
        Gesamtpreis
        Netto
        Zusätzliche Domains Preisstufe 1
        Domains mit einem monatlichen Preis von 1,99 EUR
        Domain: suliqua.com
        Projekt: p145339 (Webhosting XL 10.0)
        Leistungszeitraum: 27.01.2026 bis 26.01.2027
        1 12 Monate 19 % 1,99 EUR 23,88 EUR
        Zwischensumme Netto
        Zzgl. 19 % USt. (Deutschland) auf 23,88 EUR
        23,88 EUR
        4,54 EUR
        Gesamtbetrag 28,42 EUR
        Der Rechnungsbetrag wird frühestens am 29.01.2026
        von Ihrem Konto abgebucht.
        Mittwald CM Service GmbH & Co. KG
        E-Mail: info@mittwald.de
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "6514767.pdf",
            "content_type": "application/pdf",
            "storage_path": "mittwald.pdf",
            "size_bytes": 54481,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Mittwald CM Service GmbH & Co. KG")
        self.assertEqual(result["invoice_number"], "6514767")
        self.assertEqual(result["customer_number"], "296313")
        self.assertEqual(result["invoice_date"], "2026-01-27")
        self.assertEqual(result["due_date"], "2026-01-29")
        self.assertEqual(result["product_name"], "Zusätzliche Domains Preisstufe 1")
        self.assertEqual(result["cost_category"], "software_subscription")
        self.assertEqual(result["assignment_type"], "general_cost")
        self.assertEqual(result["net_amount"], Decimal("23.88"))
        self.assertEqual(result["tax_amount"], Decimal("4.54"))
        self.assertEqual(result["gross_amount"], Decimal("28.42"))
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            result["normalized_filename"],
            "ERg 6514767, Allgemeine Kosten, Mittwald CM Service GmbH & Co. KG, Zusätzliche Domains Preisstufe 1, 2026-01-27.pdf",
        )

    def test_scanned_tank_receipt_uses_filename_without_mock_amounts(self):
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "HH-FB 814, Tankbeleg LS, 2025-12-10.pdf",
            "content_type": "application/pdf",
            "storage_path": "tankbeleg.pdf",
            "created_at": "2026-06-17T10:00:00+00:00",
            "size_bytes": 493091,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=""),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["source"], "pdf_scan_filename_rules")
        self.assertEqual(result["supplier_name"], "Tankbeleg")
        self.assertEqual(result["invoice_number"], "HH-FB 814 2025-12-10")
        self.assertEqual(result["customer_reference"], "HH-FB 814")
        self.assertEqual(result["vehicle"], "HH-FB 814")
        self.assertEqual(result["driver"], "LS")
        self.assertEqual(result["invoice_date"], "2025-12-10")
        self.assertEqual(result["due_date"], "2025-12-10")
        self.assertEqual(result["cost_category"], "fuel_vehicle")
        self.assertEqual(result["assignment_type"], "general_cost")
        self.assertEqual(result["product_name"], "Diesel")
        self.assertIsNone(result["net_amount"])
        self.assertIsNone(result["tax_amount"])
        self.assertIsNone(result["gross_amount"])
        self.assertIn("OCR", " ".join(result["warnings"]))
        self.assertEqual(
            result["normalized_filename"],
            "ERg HH-FB 814 2025-12-10, Allgemeine Kosten, Tankbeleg, Diesel, 2025-12-10.pdf",
        )

    def test_scanned_tank_receipt_filename_driver_is_optional(self):
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "HH-FB 4753, Tankbeleg, PhS, 2025-11-25.pdf",
            "content_type": "application/pdf",
            "storage_path": "tankbeleg.pdf",
            "created_at": "2026-06-17T10:00:00+00:00",
            "size_bytes": 121895,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=""),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["invoice_number"], "HH-FB 4753 2025-11-25")
        self.assertEqual(result["customer_reference"], "HH-FB 4753")
        self.assertEqual(result["driver"], "PhS")
        self.assertEqual(result["invoice_date"], "2025-11-25")
        self.assertEqual(result["cost_category"], "fuel_vehicle")

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
            "content_type": "application/octet-stream",
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

    def test_dammers_invoice_uses_order_reference_for_assignment(self):
        text = """
        DAMMERS
        Alles fürs Dach
        Firma                            RECHNUNG
        FriStD-Bau ZuB  GmbH & Co KG
        Haldesdorfer Str. 44
        Nummer         :            776511-606
        Datum          :    12.06.2026 - 08:46
        Kundennr.      :           0515834/086
        Bestelldaten: Bucheckerweg 4
        ART-NR BEZEICHNUNG                   MENGE    EINZELPREIS RAB    NETTOWERT
        75556                                20,00 St     5,10 St           102,00
        Thorben Peters Dachlatte 40 x 60 S10 rot
        Summe Warenwert                                            EUR     331,88
        + 19,00 % Mwst.                                            EUR      63,06
        Rechnungsbetrag (zahlbar bis spätestens 12.07.26 o. Abzug) EUR     394,94
        zahlbar bis zum 22.06.26 abzüglich EUR 11,85 Skonto
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "776511-606.pdf",
            "content_type": "application/octet-stream",
            "storage_path": "dammers.pdf",
            "size_bytes": 236119,
            "sha256": "abc",
        }
        assignment = {
            "code": "25-00009",
            "label": "Buwg4",
            "kind": "construction_project",
            "project_number": "25-00009",
            "revenue_relevant": True,
            "is_active": True,
        }

        def assignment_lookup(_tenant_id, hint):
            if hint and "Bucheckerweg 4" in hint:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=assignment_lookup),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Rolf Dammers oHG")
        self.assertEqual(result["invoice_number"], "776511-606")
        self.assertEqual(result["customer_number"], "0515834/086")
        self.assertEqual(result["customer_reference"], "Bucheckerweg 4")
        self.assertEqual(result["assignment_code"], "Buwg4")
        self.assertEqual(result["project_name"], "Buwg4")
        self.assertEqual(result["project_number"], "25-00009")
        self.assertEqual(result["invoice_date"], "2026-06-12")
        self.assertEqual(result["net_amount"], Decimal("331.88"))
        self.assertEqual(result["tax_amount"], Decimal("63.06"))
        self.assertEqual(result["gross_amount"], Decimal("394.94"))
        self.assertEqual(result["discount_due_date"], "2026-06-22")
        self.assertEqual(result["discount_amount"], Decimal("11.85"))
        self.assertEqual(result["cost_category"], "material")
        self.assertIn("Dachlatte", result["product_name"])

    def test_dammers_invoice_tolerates_logo_spaced_text_and_filename_number(self):
        text = """
        D A M M E R S
        Alles fÃ¼rs Dach
        Firma                            RECHNUNG
        FriStD-Bau ZuB GmbH & Co KG
        Datum          :    12.06.2026 - 08:46
        Kunden Nr      :           0515834/086
        Bestelldaten: Bucheckerweg 4
        ART-NR BEZEICHNUNG                   MENGE    EINZELPREIS RAB    NETTOWERT
        75556                                20,00 St     5,10 St           102,00
        Thorben Peters Dachlatte 40 x 60 S10 rot
        Summe Warenwert                                            EUR     331,88
        + 19,00 % Mwst.                                            EUR      63,06
        Rechnungsbetrag (zahlbar bis spÃ¤testens 12.07.26 o. Abzug) EUR     394,94
        zahlbar bis zum 22.06.26 abzÃ¼glich EUR 11,85 Skonto
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "776511-606.pdf",
            "content_type": "application/octet-stream",
            "storage_path": "dammers.pdf",
            "size_bytes": 236119,
            "sha256": "abc",
        }
        assignment = {
            "code": "25-00009",
            "label": "Buwg4",
            "kind": "construction_project",
            "project_number": "25-00009",
            "revenue_relevant": True,
            "is_active": True,
        }

        def assignment_lookup(_tenant_id, hint):
            if hint and "Bucheckerweg 4" in hint:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=assignment_lookup),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Rolf Dammers oHG")
        self.assertEqual(result["invoice_number"], "776511-606")
        self.assertEqual(result["customer_number"], "0515834/086")
        self.assertEqual(result["assignment_code"], "Buwg4")
        self.assertEqual(result["project_number"], "25-00009")
        self.assertEqual(result["net_amount"], Decimal("331.88"))
        self.assertEqual(result["gross_amount"], Decimal("394.94"))

    def test_dammers_invoice_uses_reference_address_for_assignment(self):
        text = """
        DAMMERS
        Alles fÃ¼rs Dach
        Firma                            RECHNUNG
        FriStD-Bau ZuB  GmbH & Co KG
        Haldesdorfer Str. 44
        Nummer         :            776511-606
        Datum          :    12.06.2026 - 08:46
        Kundennr.      :           0515834/086
        Bestelldaten:
        Bucheckerweg 4
        22175 Hamburg
        ART-NR BEZEICHNUNG                   MENGE    EINZELPREIS RAB    NETTOWERT
        75556                                20,00 St     5,10 St           102,00
        Thorben Peters Dachlatte 40 x 60 S10 rot
        Summe Warenwert                                            EUR     331,88
        + 19,00 % Mwst.                                            EUR      63,06
        Rechnungsbetrag (zahlbar bis spÃ¤testens 12.07.26 o. Abzug) EUR     394,94
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "776511-606.pdf",
            "content_type": "application/octet-stream",
            "storage_path": "dammers.pdf",
            "size_bytes": 236119,
            "sha256": "abc",
        }
        assignment = {
            "code": "25-00009",
            "label": "Buwg4",
            "kind": "construction_project",
            "project_number": "25-00009",
            "revenue_relevant": True,
            "is_active": True,
        }

        def assignment_lookup(_tenant_id, hint):
            if hint == "Bucheckerweg 4, 22175 Hamburg":
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=assignment_lookup),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["customer_reference"], "Bucheckerweg 4")
        self.assertEqual(result["delivery_address"], "Bucheckerweg 4, 22175 Hamburg")
        self.assertEqual(result["assignment_code"], "Buwg4")
        self.assertEqual(result["project_name"], "Buwg4")
        self.assertEqual(result["project_number"], "25-00009")
        self.assertEqual(result["assignment_match"]["source"], "Lieferadresse")

    def test_dammers_invoice_uses_filename_and_customer_number_when_logo_ocr_is_missing(self):
        text = """
        Firma                            RECHNUNG
        FriStD-Bau ZuB  GmbH & Co KG
        Haldesdorfer Str. 44
        Datum          :    12.06.2026 - 08:46
        Kundennummer   :           0515834/086
        Bestelldaten: Bucheckerweg 4
        ART-NR BEZEICHNUNG                   MENGE    EINZELPREIS RAB    NETTOWERT
        75556                                20,00 St     5,10 St           102,00
        Thorben Peters Dachlatte 40 x 60 S10 rot
        Summe Warenwert                                            EUR     331,88
        + 19,00 % Mwst.                                            EUR      63,06
        Rechnungsbetrag (zahlbar bis spÃ¤testens 12.07.26 o. Abzug) EUR     394,94
        zahlbar bis zum 22.06.26 abzÃ¼glich EUR 11,85 Skonto
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "776511-606.pdf",
            "content_type": "application/octet-stream",
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
        self.assertEqual(result["invoice_number"], "776511-606")
        self.assertEqual(result["customer_number"], "0515834/086")
        self.assertEqual(result["invoice_date"], "2026-06-12")
        self.assertEqual(result["net_amount"], Decimal("331.88"))
        self.assertEqual(result["tax_amount"], Decimal("63.06"))
        self.assertEqual(result["gross_amount"], Decimal("394.94"))
        self.assertEqual(result["discount_due_date"], "2026-06-22")
        self.assertEqual(result["discount_amount"], Decimal("11.85"))

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

    def test_holz_junge_credit_note_reads_negative_table_amounts(self):
        text = """
        Holz Junge GmbH
        G U T S C H R I F T
        Rechnungs-Nr.: 26200874
        Kunden-Nr.: 109324
        Datum: 28.01.2026
        skontofähiger Betrag Netto MwSt-% MwSt Endbetrag EUR
        -632,32 -642,40 19,00 -122,06 -764,46
        11.02.2026 3,00% Skonto = -18,97
        ohne Abzug27.02.2026 -764,46
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Kreditrechnung_26200874_W5607Z.pdf",
            "content_type": "application/pdf",
            "storage_path": "holz-junge-credit.pdf",
            "size_bytes": 715000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Holz Junge GmbH")
        self.assertEqual(result["document_type"], "credit_note")
        self.assertEqual(result["net_amount"], Decimal("-642.40"))
        self.assertEqual(result["tax_amount"], Decimal("-122.06"))
        self.assertEqual(result["gross_amount"], Decimal("-764.46"))
        self.assertEqual(result["discount_amount"], Decimal("-18.97"))
        self.assertEqual(result["discount_due_date"], "2026-02-11")
        self.assertEqual(result["payment_terms"][0]["label"], "Gutschrift verrechnen")

    def test_haho_holz_invoice_reads_customer_date_totals_and_discount(self):
        text = """
        FriStD-Bau ZuB GmbH &Co.KG
        RechnungsNr. .: 25       25/ /005898 005898 30.04.25
        KundenNr.  . .:   43535
        Versandart . .: Abholung
        Reisender  . .: Lennart Werner
        R E C H N U N G
        BTR NL
        BV: Meistertwiete 5
        0020 010106020000001 1
        Fi-BSH gehob.,gefast, foliert     6,0cm       cm   20,0cm
        1 ST  1200,0cm    0,144 CBM       750,00      108,00
        Zahlung  bis 14.05.25  mit 2 % Skonto   =      2,57 EUR Netto-Betrag    EUR     108,00
                 bis  1.06.25  netto                            19,00 % Mwst    EUR      20,52
                                                                Rechnungsbetrag EUR     128,52
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "R-25005898-  43535.pdf",
            "content_type": "application/pdf",
            "storage_path": "haho-holz.pdf",
            "size_bytes": 715000,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "HaHo Holz")
        self.assertEqual(result["invoice_number"], "25005898")
        self.assertEqual(result["customer_number"], "43535")
        self.assertEqual(result["invoice_date"], "2025-04-30")
        self.assertEqual(result["due_date"], "2025-06-01")
        self.assertEqual(result["discount_due_date"], "2025-05-14")
        self.assertEqual(result["discount_percent"], Decimal("2.00"))
        self.assertEqual(result["discount_amount"], Decimal("2.57"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("125.95"))
        self.assertEqual(result["net_amount"], Decimal("108.00"))
        self.assertEqual(result["tax_amount"], Decimal("20.52"))
        self.assertEqual(result["gross_amount"], Decimal("128.52"))
        self.assertEqual(result["product_name"], "Fi-BSH gehob.,gefast, foliert 6,0cm cm 20,0cm")

    def test_luechau_credit_note_reads_header_negative_amounts_and_discount(self):
        text = """
        Lüchau Baustoffe GmbH, Rissener Str. 142, 22880 Wedel
        08.01.2026 / 12:44 / REVERSANDLUECHAU
        13803716
        08.01.2026
        GS1035164
        Seite 1
        FriStD-Bau ZuB GmbH & Co. KG
        Gutschrift
        *GS103516425*
        Ausstelllager: Wedel
        Ausstelldatum:
        Kundennummer:
        Belegdatum:
        Belegnummer:
        Lieferanschrift:
        Weseler Weg 20
        22045 Hamburg
        Rücknahme von Lieferung  LI1048490 / RE1535760
        252642 19EIN37,81RO3,000Maler-Abdeckvlies 50qm  Premium 220g/qm1
        Breite 0,97 x Länge 51,6 m -102,08[-10%]
        Zahlbar bis 22.01.2026 abzgl. 3 % Skonto EUR -3,64 = EUR -117,84
        skontierfähiger Betrag EUR -121,48
        Brutto-Betrag:MwSt.-Betrag:Netto-Betrag:
        -121,48-19,40-102,0819% MwSt.:
        Gutschriftssumme EUR: -121,48
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "GS1035164.pdf",
            "content_type": "application/pdf",
            "storage_path": "luechau-credit.pdf",
            "size_bytes": 127332,
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
            if lookup_text and "Weseler Weg 20" in lookup_text:
                return assignment
            return None

        def find_assignment_match(_tenant_id, lookup_text):
            found = find_assignment(_tenant_id, lookup_text)
            if found:
                return {"assignment": found, "score": 100, "reasons": ["Lieferadresse"]}
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
            patch.object(extraction_service, "find_assignment_unit_match_by_text", side_effect=find_assignment_match),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Lüchau Baustoffe GmbH")
        self.assertEqual(result["document_type"], "credit_note")
        self.assertEqual(result["invoice_number"], "GS1035164")
        self.assertEqual(result["customer_number"], "13803716")
        self.assertEqual(result["invoice_date"], "2026-01-08")
        self.assertEqual(result["assignment_code"], "Wewe20")
        self.assertEqual(result["project_number"], "25-00008")
        self.assertEqual(result["product_name"], "Maler-Abdeckvlies 50qm")
        self.assertEqual(result["net_amount"], Decimal("-102.08"))
        self.assertEqual(result["tax_amount"], Decimal("-19.40"))
        self.assertEqual(result["gross_amount"], Decimal("-121.48"))
        self.assertEqual(result["discount_base"], Decimal("-121.48"))
        self.assertEqual(result["discount_amount"], Decimal("-3.64"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("-117.84"))
        self.assertEqual(result["warnings"], [])

    def test_luechau_invoice_reads_glued_customer_number_and_product(self):
        text = """
        Lüchau Baustoffe GmbH, Rissener Str. 142, 22880 Wedel
        FriStD-Bau ZuB GmbH & Co. KG
        Rechnung Seite 1
        Belegnummer: RE1535760
        Belegdatum:
        AT: AT1594729
        18.12.2025
        13803716Kundennummer:
        Lieferanschrift: FriStD-Bau ZuB GmbH & Co. KG
        Weseler Weg 20
        22045 Hamburg
        42526425 Maler-Abdeckvlies 50qm  Premium 220g/qm RO 37,81 EIN 19
        Breite 0,97 x Länge 51,6 m 136,10[-10%]
        Fortsetzung Rechnung Seite 2
        Belegnummer:
        Belegdatum:
        Kundennummer:
        RE1535760
        18.12.2025
        13803716
        Netto: MwSt.: Brutto:
        19% MwSt.: 357,47 67,92 425,39
        Zahlungssumme EUR:
        425,39
        Zahlbar bis 01.01.2026 abzgl. 3 % Skonto EUR 11,26 = EUR 414,13
        skontierfähiger Betrag EUR 375,41
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "RE1535760.pdf",
            "content_type": "application/pdf",
            "storage_path": "luechau-invoice.pdf",
            "size_bytes": 120557,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_match_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Lüchau Baustoffe GmbH")
        self.assertEqual(result["invoice_number"], "RE1535760")
        self.assertEqual(result["customer_number"], "13803716")
        self.assertEqual(result["invoice_date"], "2025-12-18")
        self.assertEqual(result["product_name"], "Maler-Abdeckvlies 50qm")
        self.assertEqual(result["net_amount"], Decimal("357.47"))
        self.assertEqual(result["tax_amount"], Decimal("67.92"))
        self.assertEqual(result["gross_amount"], Decimal("425.39"))

    def test_luechau_invoice_maps_project_number_to_project_name_for_filename(self):
        text = """
        Lüchau Baustoffe GmbH, Rissener Str. 142, 22880 Wedel
        FriStD-Bau ZuB GmbH & Co. KG
        Rechnung Seite 1
        Belegnummer: RE1586258
        Belegdatum:
        AT: AT1748901
        11.06.2026
        13803716 Kundennummer:
        Ihre Referenz: Herr Schnawaber, Auftrag: 26-00007 vom 03.06.2026
        252642 Maler-Abdeckvlies 50qm Premium 220g/qm RO
        42,01 EIN
        Netto: MwSt.: Brutto:
        19% MwSt.: 50,13 9,52 59,65
        Zahlbar bis 25.06.2026 abzgl. 3 % Skonto EUR 1,79 = EUR 57,86
        skontierfähiger Betrag EUR 59,65
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "RE1586258.pdf",
            "content_type": "application/pdf",
            "storage_path": "luechau-invoice.pdf",
            "size_bytes": 120557,
            "sha256": "abc",
        }
        assignment = {
            "code": "26-00007",
            "label": "Hk92",
            "kind": "construction_project",
            "project_number": "26-00007",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment_match(_tenant_id, lookup_text):
            if lookup_text and "26-00007" in lookup_text:
                return {"assignment": assignment, "score": 100, "reasons": ["Projektnummer"]}
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_match_by_text", side_effect=find_assignment_match),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Lüchau Baustoffe GmbH")
        self.assertEqual(result["invoice_number"], "RE1586258")
        self.assertEqual(result["customer_number"], "13803716")
        self.assertEqual(result["invoice_date"], "2026-06-11")
        self.assertEqual(result["assignment_code"], "Hk92")
        self.assertEqual(result["project_name"], "Hk92")
        self.assertEqual(result["project_number"], "26-00007")
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["product_name"], "Maler-Abdeckvlies 50qm")
        self.assertEqual(result["net_amount"], Decimal("50.13"))
        self.assertEqual(result["tax_amount"], Decimal("9.52"))
        self.assertEqual(result["gross_amount"], Decimal("59.65"))
        self.assertEqual(result["discount_base"], Decimal("59.65"))
        self.assertEqual(result["discount_amount"], Decimal("1.79"))
        self.assertEqual(result["discounted_payable_amount"], Decimal("57.86"))
        self.assertEqual(
            result["normalized_filename"],
            "ERg RE1586258, BV Hk92, Lüchau Baustoffe GmbH, Maler-Abdeckvlies 50qm, 2026-06-11.pdf",
        )

    def test_roennfeld_invoice_reads_zero_tax_customer_project_and_due_date(self):
        text = """
        Rönnfeld | Kieler Str. 9 | 25451 Quickborn
        Rönnfeld ROLLLADEN UND MARKISEN GmbH
        info@ roennfeld-rollladenbau.de | www.roennfeld-rollladenbau.de
        FriStD-Bau ZuB GmbH & Co KG Zimmerei & BaufirmaHaldesdorferstraße 4422179 Hamburg
        RechnungBestellreferenz:Ihre Kundennummer Unser Vorgang DatumQ010267R25-3590518.12.2025
        Pos       BeschreibungMengeEPGP
        BV: Farmsener Landstraße 36B, Hamburg
        01Raffstore Fassadensystem - Drahtseilgeführt Lamellen gebördelt inkl. Motorbedienung 227,5 cm x 236,0 cm2687,001374,00
        Zwischensumme1702,00Rabatt: -10 %-170,2003Montage ohne E-Anschluss 2110,00220,00 Gesamtbetrag1.751,80 €zuzüglich MwSt. 0 % Endbetrag1.751,80 €
        Zahlen Sie bitte bis zum 28. Dezember 2025ohne Abzug
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "R25-35905.pdf",
            "content_type": "application/pdf",
            "storage_path": "roennfeld-invoice.pdf",
            "size_bytes": 1180072,
            "sha256": "abc",
        }
        assignment = {
            "code": "FaLastr36b",
            "label": "Farmsener Landstraße 36b",
            "kind": "construction_project",
            "project_number": "25-00006",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text and "Farmsener Landstraße" in lookup_text:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Rönnfeld ROLLLADEN UND MARKISEN GmbH")
        self.assertEqual(result["document_type"], "incoming_invoice")
        self.assertEqual(result["invoice_number"], "R25-35905")
        self.assertEqual(result["customer_number"], "Q010267")
        self.assertEqual(result["invoice_date"], "2025-12-18")
        self.assertEqual(result["due_date"], "2025-12-28")
        self.assertEqual(result["assignment_code"], "FaLastr36b")
        self.assertEqual(result["project_number"], "25-00006")
        self.assertEqual(result["cost_category"], "subcontractor")
        self.assertEqual(result["net_amount"], Decimal("1751.80"))
        self.assertEqual(result["tax_amount"], Decimal("0.00"))
        self.assertEqual(result["gross_amount"], Decimal("1751.80"))
        self.assertEqual(result["warnings"], [])

    def test_roennfeld_credit_note_reads_negative_zero_tax_amounts(self):
        text = """
        Rönnfeld ROLLLADEN UND MARKISEN GmbH
        www.roennfeld-rollladenbau.de
        Rechnungsberichtigung zur Rechnung R25-35462Ihre Kundennummer Unser Vorgang DatumQ010267R25-3584509.12.2025
        Pos       BeschreibungMengeEPGP
        BV: Eckerkamp 58, Hamburg01anteilige Gutschrift zur Rechnung R25-35462 v.30.09.20251-200,00-200,00 Gesamtbetrag-200,00 €zuzüglich MwSt. 0 % Endbetrag-200,00 €
        Verrechnen Sie bitte diese Rechnungsberichtigung mit Ihrer nächsten Zahlung.
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "R25-35845.pdf",
            "content_type": "application/pdf",
            "storage_path": "roennfeld-credit.pdf",
            "size_bytes": 1176160,
            "sha256": "abc",
        }
        assignment = {
            "code": "Ekkp58",
            "label": "Eckerkamp 58",
            "kind": "construction_project",
            "project_number": "25-00007",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text and "Eckerkamp 58" in lookup_text:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Rönnfeld ROLLLADEN UND MARKISEN GmbH")
        self.assertEqual(result["document_type"], "credit_note")
        self.assertEqual(result["invoice_number"], "R25-35845")
        self.assertEqual(result["customer_number"], "Q010267")
        self.assertEqual(result["invoice_date"], "2025-12-09")
        self.assertEqual(result["assignment_code"], "Ekkp58")
        self.assertEqual(result["product_name"], "anteilige Gutschrift zur Rechnung R25-35462")
        self.assertEqual(result["cost_category"], "subcontractor")
        self.assertEqual(result["net_amount"], Decimal("-200.00"))
        self.assertEqual(result["tax_amount"], Decimal("0.00"))
        self.assertEqual(result["gross_amount"], Decimal("-200.00"))
        self.assertEqual(result["warnings"], [])

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

    def test_rieprecht_invoice_reads_spaced_number_project_totals_and_due_date(self):
        text = """
        FriStD Bau ZuB GmbH & Co.KG
        R e c h n u n g   N r .   2 6 0 0 0 0 2
        für   Weseler Weg 20, Hamburg
        Rg.-Datum Kunden-Nr. Bestellung Vertreter/ADM Bearbeiter Seite
        09.01.2026 10501 Ronny Friedrich                    RI  1
        Pos. Artikel-Nr./Bezeichnung Menge / Einheit E-Preis €  Rabatt Mwst.% G-Preis €
        Lieferschein Nr. 2600001 vom 05.01.2026
          1Gestellung Container                    1,000 Stück             60,00        19.00        60,00
        Lieferschein Nr. 2600002 vom 05.01.2026
          1Gestellung Container                    1,000 Stück             60,00        19.00        60,00
        Warenwert
        mit  19.00% Mwst.        120,00 € Mwst. 19.00%         22,80 €
        Nettobetrag  €       120,00
        Mwst. gesamt €        22,80
        Zahlung ohne Abzug bis 19.01.2026
        Zahlbetrag   €       142,80
        Rieprecht GmbH Heinrichstr. 11, 22946 Brunsbek
        stefan@rieprecht-gmbh.de
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rg2600002_RIEP_mit_Belegen.pdf",
            "content_type": "application/pdf",
            "storage_path": "rieprecht.pdf",
            "size_bytes": 232000,
            "sha256": "abc",
        }
        assignment = {
            "code": "25-00008",
            "label": "Wewe20",
            "kind": "construction_project",
            "project_number": "25-00008",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text and "Weseler Weg 20" in lookup_text:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Rieprecht GmbH")
        self.assertEqual(result["invoice_number"], "2600002")
        self.assertEqual(result["customer_number"], "10501")
        self.assertEqual(result["invoice_date"], "2026-01-09")
        self.assertEqual(result["due_date"], "2026-01-19")
        self.assertEqual(result["delivery_address"], "Weseler Weg 20, Hamburg")
        self.assertEqual(result["assignment_code"], "Wewe20")
        self.assertEqual(result["project_number"], "25-00008")
        self.assertEqual(result["cost_category"], "subcontractor")
        self.assertEqual(result["product_name"], "Gestellung Container")
        self.assertEqual(result["net_amount"], Decimal("120.00"))
        self.assertEqual(result["tax_amount"], Decimal("22.80"))
        self.assertEqual(result["gross_amount"], Decimal("142.80"))
        self.assertEqual(result["warnings"], [])

    def test_rieprecht_invoice_reads_totals_from_second_page(self):
        text = """
        FriStD Bau ZuB GmbH & Co.KG
        R e c h n u n g   N r .   2 5 0 0 0 7 8
        für   Farmsener Landstr. 36b, Hamburg
        Rg.-Datum Kunden-Nr. Bestellung Vertreter/ADM Bearbeiter Seite
        08.09.2025 10501 Ronny Friedrich                    RI  1
          1Transport                               1,000 Stück            130,00        19.00       130,00
        Container Abholung - Tauschen
          2Plattemsand F1 0-4                      7,000 t                 24,50        19.00       171,50
          1Boden ohne Analyse                      9,680 t                 38,00        19.00       367,84
        Zwischensumme     2.323,68
        Rechnung Nr. 2500078    Seite  2
        Nettobetrag  €     2.323,68
        Mwst. gesamt €       441,50
        Zahlung ohne Abzug bis 18.09.2025
        Zahlbetrag   €     2.765,18
        Rieprecht GmbH Heinrichstr. 11, 22946 Brunsbek
        stefan@rieprecht-gmbh.de
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rg2500078_RIEP_mit_Belegen.pdf",
            "content_type": "application/pdf",
            "storage_path": "rieprecht.pdf",
            "size_bytes": 715000,
            "sha256": "abc",
        }
        assignment = {
            "code": "25-00006",
            "label": "FaLastr36b",
            "kind": "construction_project",
            "project_number": "25-00006",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text and "Farmsener Landstr. 36b" in lookup_text:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Rieprecht GmbH")
        self.assertEqual(result["invoice_number"], "2500078")
        self.assertEqual(result["customer_number"], "10501")
        self.assertEqual(result["invoice_date"], "2025-09-08")
        self.assertEqual(result["due_date"], "2025-09-18")
        self.assertEqual(result["assignment_code"], "FaLastr36b")
        self.assertEqual(result["project_number"], "25-00006")
        self.assertEqual(result["product_name"], "Boden/Plattemsand Container")
        self.assertEqual(result["net_amount"], Decimal("2323.68"))
        self.assertEqual(result["tax_amount"], Decimal("441.50"))
        self.assertEqual(result["gross_amount"], Decimal("2765.18"))
        self.assertEqual(result["warnings"], [])

    def test_konzept54_invoice_reads_project_support_totals_and_due_date(self):
        text = """
        FriStD-Bau ZuB GmbH & Co.KGHaldesdorfer Str. 4422179 Hamburg
        konzept 54 GmbH & Co.KG · Haldesdorfer Str. 44 · 22179 Hamburg
        Kunden-Nr. :
         10019Hamburg
        10.11.2025
         Rechnung 25-00056
        Bauvorhaben:
        Süderfeldstr 46a, 22529 Hamburg
        Projekt-Nr. :
        Haldesdorfer Str. 44 22179 Hamburg Tel: +49 40 386 745 70 post@konzept-54.de www.konzept-54.de
        Leistungsdatum:          05.11.2025Typ: WPF 07, Seriennummer: 232911-8871-009786
        PosMengeMEBezeichnungE-PreisG-Preis
        11,00Stdweiteres Ersatzteil: Art.: 344680Pumpen Baugruppe HPS 7.0
         193,52 193,52
        24,00StdTechnischer Wärmepumpen-SupportQualifizierter Wärmepumpenspeziallist im Kundenauftrag.
         129,00 516,00
        Nettosumme 709,52Umsatzsteuer 19 % 134,81
        Gesamtsumme 844,33
        Wir bedanken uns für Ihren Auftrag und möchten Sie bitten, den Rechnungsbetrag bis zum 17.11.2025 zu begleichen.
        Bitte mit angeben:RN 25-00056, KN 10019
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "ARg 25-00056, Materiallieferung+Kundendienst.pdf",
            "content_type": "application/pdf",
            "storage_path": "konzept54.pdf",
            "size_bytes": 202096,
            "sha256": "abc",
        }
        assignment = {
            "code": "Süfe46a",
            "label": "Süderfeldstraße 46a",
            "kind": "construction_project",
            "project_number": "25-00010",
            "revenue_relevant": True,
            "is_active": True,
        }

        def find_assignment(_tenant_id, lookup_text):
            if lookup_text and "Süderfeldstr 46a" in lookup_text:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "konzept 54 GmbH & Co.KG")
        self.assertEqual(result["invoice_number"], "25-00056")
        self.assertEqual(result["customer_number"], "10019")
        self.assertEqual(result["invoice_date"], "2025-11-10")
        self.assertEqual(result["due_date"], "2025-11-17")
        self.assertEqual(result["delivery_address"], "Süderfeldstr 46a, 22529 Hamburg")
        self.assertEqual(result["assignment_code"], "Süfe46a")
        self.assertEqual(result["project_number"], "25-00010")
        self.assertEqual(result["cost_category"], "subcontractor")
        self.assertEqual(result["product_name"], "Technischer Wärmepumpen-Support")
        self.assertEqual(result["net_amount"], Decimal("709.52"))
        self.assertEqual(result["tax_amount"], Decimal("134.81"))
        self.assertEqual(result["gross_amount"], Decimal("844.33"))
        self.assertEqual(result["warnings"], [])

    def test_boehm_invoice_uses_clean_filename_for_supplier_date_and_assignment(self):
        text = """
        Böhm Malereibetrieb GmbH
        Malerarbeiten und WDVS
        Sehr geehrter Herr Ronny Friedrich,wir danken für Ihren Auftrag und berechnen Ihnen die Ausführung im (Juni) per 25.06.2026 wie folgt:
        Pos.Bezeichnung EinzelpreisMenge EinheitGesamtpreis
        1 Baustelleneinrichtung, An- und Abfuhr aller benötigten Materialien, Geräte und Maschinen 110,00 € 1,00 Stk. 110,00 €
        Zwischensumme 3.221,03 € Abschlag vom Netto Nachlass - 3 % von 3.221,03 € - 96,63 €
        Nettosumme 3.124,40 €
        Firma FirStD-Bau ZuB GmbH & Co.KG Haldesdorferstrasse 44 D-22179 Hamburg
        Böhm Malereibetrieb GmbH * Pollhornweg 15 * 21107 Hamburg
        25.06.202612988Kunden Nummer:
        BV Weseler Weg 20 :Spachtelarbeiten im DachausbauRechnung 2600148 Original
        --- Projekt-Nummer:00014/25
        Pollhornweg 15 21107 Hamburg Telefon: 040 / 51 33 03 68 E-Mail : info@maler-boehm.de
        Zahlbar bitte per Überweisung unter Angabe der Kunden- und Rechnungs-Nummer bis spätestens zum 05.07.2026 auf unten genanntes Konto.
        Diese Rechnung wurde aus einem bereits sortierten Dateinamen importiert.
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "ERg 2600148, BV Wewe20, Maler L. Böhm, 2026-06-25.pdf",
            "content_type": "application/pdf",
            "storage_path": "boehm.pdf",
            "size_bytes": 142000,
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
            if lookup_text and "Wewe20" in lookup_text:
                return assignment
            return None

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", side_effect=find_assignment),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Böhm Malereibetrieb GmbH")
        self.assertEqual(result["invoice_number"], "2600148")
        self.assertEqual(result["customer_number"], "12988")
        self.assertEqual(result["invoice_date"], "2026-06-25")
        self.assertEqual(result["due_date"], "2026-07-05")
        self.assertEqual(result["customer_reference"], "Wewe20")
        self.assertEqual(result["assignment_code"], "Wewe20")
        self.assertEqual(result["project_number"], "25-00008")
        self.assertEqual(result["cost_category"], "subcontractor")
        self.assertEqual(result["product_name"], "Spachtelarbeiten im Dachausbau")
        self.assertEqual(result["net_amount"], Decimal("3124.40"))
        self.assertIsNone(result["tax_amount"])
        self.assertIsNone(result["gross_amount"])

    def test_europlanen_invoice_reads_object_material_totals_and_due_date(self):
        text = """
        Euro Planen Handel und Service GmbH · Große Brunnenstraße 63a · 22763 Hamburg
        Rechnung:
        50489
        Objekt:
        Industrieplanen 8x12m + 8x10m
        Wir berechnen gemäß Ihrer Bestellung wie folgt:
        FristD-Bau ZuB GmbH & Co. KG
        Haldesdorfer Straße 44 - Hinterhof
        22179 Hamburg
        Hamburg, 30.10.2025
        Projekt:
        43564
        Leistungsdatum: 23.10.2025
        Lieferschein 55317-0
        001
        1,000
        Stck
        31016: Industrieplane 8x12 trans
        110,40
        110,40
        002
        1,000
        Stck
        31015: Industrieplane 8x10 trans
        92,00
        92,00
        003
        1,000
        Stck
        Versand per Paketdienst
        44,00
        44,00
        Leistungswert netto
        246,40
        MwSt 19%
        46,82
        Gesamtleistung brutto
        293,22
        Zahlungsbedingungen:
        Zahlbar innerhalb 10 Kalendertagen, spätestens jedoch bis zum 10.11.2025, netto ohne Abzüge.
        """
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "Rechnung 50489.pdf",
            "content_type": "application/pdf",
            "storage_path": "europlanen.pdf",
            "size_bytes": 112233,
            "sha256": "abc",
        }

        with (
            patch.object(extraction_service, "_extract_pdf_text", return_value=text),
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_pdf_text_result(document)

        self.assertEqual(result["supplier_name"], "Euro Planen Handel und Service GmbH")
        self.assertEqual(result["invoice_number"], "50489")
        self.assertEqual(result["customer_reference"], "Industrieplanen 8x12m + 8x10m")
        self.assertEqual(result["invoice_date"], "2025-10-30")
        self.assertEqual(result["due_date"], "2025-11-10")
        self.assertEqual(result["assignment_type"], "general_cost")
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["product_name"], "Industrieplanen 8x12m + 8x10m")
        self.assertEqual(result["net_amount"], Decimal("246.40"))
        self.assertEqual(result["tax_amount"], Decimal("46.82"))
        self.assertEqual(result["gross_amount"], Decimal("293.22"))
        self.assertEqual(result["warnings"], [])
