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
    def test_foerch_invoice_uses_filename_and_derives_net_amount(self):
        text = """
        THEO FOERCH GmbH & Co. KG
        Artikel Schrauben und Befestigungsmaterial
        Rechnungsbetrag 8,77
        MwSt 1,40
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
        self.assertEqual(result["invoice_date"], "2026-05-21")
        self.assertEqual(result["net_amount"], Decimal("7.37"))
        self.assertEqual(result["tax_amount"], Decimal("1.40"))
        self.assertEqual(result["gross_amount"], Decimal("8.77"))
        self.assertEqual(result["discount_base"], None)
        self.assertEqual(result["cost_category"], "material")
        self.assertEqual(result["confidence"], Decimal("0.88"))
        self.assertEqual(result["warnings"], [])

    def test_customer_reference_assigns_known_construction_project(self):
        text = """
        THEO FOERCH GmbH & Co. KG
        Kundenreferenz
        Neusurenland 51
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
        self.assertEqual(result["customer_reference"], "Neusurenland 51")
        self.assertEqual(result["assignment_code"], "Neula51")
        self.assertEqual(result["assignment_label"], "Neusurenland 51")
        self.assertEqual(result["assignment_type"], "assigned")
        self.assertEqual(result["project_code"], "Neula51")
