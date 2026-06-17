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
