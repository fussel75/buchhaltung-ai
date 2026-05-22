from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import extraction as extraction_service
from app.services.extraction import _build_extraction_result


TENANT_PROFILE = {
    "assignment_code_label": "Bauvorhaben",
    "assignment_label_singular": "Bauvorhaben",
    "assignment_label_plural": "Bauvorhaben",
    "assignment_code_prefix": "BV",
}


UBL_INVOICE = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
    xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
    xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>XR-2026-1001</cbc:ID>
  <cbc:IssueDate>2026-05-21</cbc:IssueDate>
  <cbc:DueDate>2026-06-20</cbc:DueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cbc:BuyerReference>FRISTD-001</cbc:BuyerReference>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>Beispiel Lieferant GmbH</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:Delivery>
    <cac:DeliveryLocation>
      <cac:Address>
        <cbc:StreetName>Weseler Weg</cbc:StreetName>
        <cbc:BuildingNumber>20</cbc:BuildingNumber>
        <cbc:PostalZone>22045</cbc:PostalZone>
        <cbc:CityName>Hamburg</cbc:CityName>
      </cac:Address>
    </cac:DeliveryLocation>
  </cac:Delivery>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Software Abo</cbc:Name></cac:Item>
  </cac:InvoiceLine>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">119.00</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>
"""


class ExtractionXmlTests(TestCase):
    def test_standalone_ubl_invoice_is_structured_extraction(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "invoice.xml").write_bytes(UBL_INVOICE)
            document = {
                "tenant_id": "demo-mandant",
                "original_filename": "invoice.xml",
                "content_type": "application/xml",
                "storage_path": "invoice.xml",
                "size_bytes": len(UBL_INVOICE),
                "sha256": "abc",
            }

            with (
                patch.object(extraction_service, "get_settings", return_value=SimpleNamespace(storage_root=root)),
                patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
                patch.object(extraction_service, "find_supplier_rule", return_value=None),
                patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
            ):
                result = _build_extraction_result(document)

        self.assertEqual(result["source"], "standalone_xml")
        self.assertEqual(result["xml_format"], "ubl")
        self.assertEqual(result["invoice_number"], "XR-2026-1001")
        self.assertEqual(result["invoice_date"], "2026-05-21")
        self.assertEqual(result["due_date"], "2026-06-20")
        self.assertEqual(result["supplier_name"], "Beispiel Lieferant GmbH")
        self.assertEqual(result["customer_number"], "FRISTD-001")
        self.assertEqual(result["product_name"], "Software Abo")
        self.assertEqual(result["net_amount"], Decimal("100.00"))
        self.assertEqual(result["tax_amount"], Decimal("19.00"))
        self.assertEqual(result["gross_amount"], Decimal("119.00"))
        self.assertEqual(result["document_type"], "incoming_invoice")
        self.assertEqual(result["confidence"], Decimal("1.00"))
        self.assertEqual(result["structured_validation"]["status"], "passed")
        self.assertEqual(result["structured_validation_errors"], [])
        self.assertEqual(result["payment_terms"][0]["amount"], Decimal("119.00"))
        self.assertTrue(result["normalized_filename"].endswith(".xml"))

    def test_standalone_ubl_invoice_flags_structured_validation_errors(self):
        broken_invoice = UBL_INVOICE.replace(
            b"<cbc:TaxInclusiveAmount currencyID=\"EUR\">119.00</cbc:TaxInclusiveAmount>",
            b"<cbc:TaxInclusiveAmount currencyID=\"EUR\">118.00</cbc:TaxInclusiveAmount>",
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "invoice.xml").write_bytes(broken_invoice)
            document = {
                "tenant_id": "demo-mandant",
                "original_filename": "invoice.xml",
                "content_type": "application/xml",
                "storage_path": "invoice.xml",
                "size_bytes": len(broken_invoice),
                "sha256": "abc",
            }

            with (
                patch.object(extraction_service, "get_settings", return_value=SimpleNamespace(storage_root=root)),
                patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
                patch.object(extraction_service, "find_supplier_rule", return_value=None),
                patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
            ):
                result = _build_extraction_result(document)

        self.assertEqual(result["source"], "standalone_xml")
        self.assertEqual(result["xml_format"], "ubl")
        self.assertEqual(result["gross_amount"], Decimal("118.00"))
        self.assertEqual(result["confidence"], Decimal("0.90"))
        self.assertEqual(result["structured_validation"]["status"], "failed")
        self.assertEqual(
            result["structured_validation_errors"],
            ["Summenprüfung fehlgeschlagen: Netto plus USt passt nicht zu Brutto."],
        )
        self.assertIn(
            "E-Rechnungsvalidierung: Summenprüfung fehlgeschlagen: Netto plus USt passt nicht zu Brutto.",
            result["warnings"],
        )
