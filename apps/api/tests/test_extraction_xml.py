from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import extraction as extraction_service
from app.services.extraction import _build_extraction_result, _build_structured_xml_result


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


DATEV_CII_INVOICE = """<?xml version="1.0" encoding="utf-8"?>
<rsm:CrossIndustryInvoice xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100" xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">
  <rsm:ExchangedDocument>
    <ram:ID>31813772026</ram:ID>
    <ram:IssueDateTime><udt:DateTimeString format="102">20260331</udt:DateTimeString></ram:IssueDateTime>
    <ram:IncludedNote><ram:Content>Beraternummer: 1060182</ram:Content></ram:IncludedNote>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct>
        <ram:SellerAssignedID>95138</ram:SellerAssignedID>
        <ram:Name>DATEV Unternehmen online</ram:Name>
      </ram:SpecifiedTradeProduct>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>DATEV eG</ram:Name></ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:ID>1060182</ram:ID><ram:Name>FriStD-Bau ZuB GmbH &amp; Co. KG</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradePaymentTerms>
        <ram:Description>Der Betrag in Höhe von 41,27 Euro wird voraussichtlich am 15.04.2026 per Lastschrift eingezogen.</ram:Description>
        <ram:DueDateDateTime><udt:DateTimeString format="102">20260415</udt:DateTimeString></ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>34.68</ram:LineTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">6.59</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>41.27</ram:GrandTotalAmount>
        <ram:DuePayableAmount>41.27</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
""".encode("utf-8")


class ExtractionXmlTests(TestCase):
    def test_embedded_datev_cii_invoice_uses_xml_due_date_without_cash_discount(self):
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "1060182_20260331.pdf",
            "content_type": "application/pdf",
            "storage_path": "datev.pdf",
            "size_bytes": len(DATEV_CII_INVOICE),
            "sha256": "abc",
        }
        text = """
        DATEV-Rechnung
        März 2026
        Beraternummer: 1060182
        Kontonummer: 41399752 Rechnungsnummer: 31813772026 Rechnungsdatum: 31.03.2026
        DATEV Unternehmen online März 2026
        Rechnungsendbetrag 41,27
        Der Betrag in Höhe von 41,27 Euro wird voraussichtlich am 15.04.2026 per Lastschrift eingezogen.
        """

        with (
            patch.object(extraction_service, "ensure_tenant_profile", return_value=TENANT_PROFILE),
            patch.object(extraction_service, "find_supplier_rule", return_value=None),
            patch.object(extraction_service, "find_assignment_unit_by_text", return_value=None),
        ):
            result = _build_structured_xml_result(document, "factur-x.xml", DATEV_CII_INVOICE, text)

        self.assertEqual(result["source"], "embedded_xml")
        self.assertEqual(result["xml_format"], "cii")
        self.assertEqual(result["supplier_name"], "DATEV eG")
        self.assertEqual(result["invoice_number"], "31813772026")
        self.assertEqual(result["customer_number"], "1060182")
        self.assertEqual(result["invoice_date"], "2026-03-31")
        self.assertEqual(result["due_date"], "2026-04-15")
        self.assertIsNone(result["discount_due_date"])
        self.assertEqual(result["product_name"], "DATEV Unternehmen online")
        self.assertEqual(result["cost_category"], "software_subscription")
        self.assertEqual(result["net_amount"], Decimal("34.68"))
        self.assertEqual(result["tax_amount"], Decimal("6.59"))
        self.assertEqual(result["gross_amount"], Decimal("41.27"))
        self.assertEqual(result["payment_terms"][0]["due_date"], "2026-04-15")
        self.assertEqual(len(result["payment_terms"]), 1)
        self.assertEqual(
            result["normalized_filename"],
            "ERg 31813772026, Allgemeine Kosten, DATEV eG, DATEV Unternehmen online, 2026-03-31.pdf",
        )

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
