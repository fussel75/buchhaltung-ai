from decimal import Decimal
from unittest import TestCase
from uuid import uuid4

from pydantic import ValidationError

from app.routes.documents import BookingSuggestionUpdate
from app.services.database import _booking_suggestions_from_extraction


class BookingSuggestionTests(TestCase):
    def test_split_suggestions_allocate_tax_proportionally(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "RE1574023.pdf",
        }
        extraction = {
            "supplier_name": "Luechau Baustoffe GmbH",
            "currency": "EUR",
            "net_amount": "278.92",
            "tax_amount": "52.99",
            "gross_amount": "331.91",
            "raw_result": {
                "document_type": "incoming_invoice",
                "cost_category": "material",
                "item_summary": "PE-Folie 200 my",
                "allocation_lines": [
                    {
                        "amount": "78.78",
                        "assignment_code": "Wewe20",
                        "assignment_kind": "construction_project",
                        "description": "Weseler Weg 20",
                    },
                    {
                        "amount": "200.14",
                        "assignment_code": "Hk92",
                        "assignment_kind": "construction_project",
                        "description": "Heukoppel 92",
                    },
                ],
            },
        }

        suggestions = _booking_suggestions_from_extraction(document, extraction)

        self.assertEqual(len(suggestions), 2)
        self.assertEqual(suggestions[0]["assignment_code"], "Wewe20")
        self.assertEqual(suggestions[0]["net_amount"], Decimal("78.78"))
        self.assertEqual(suggestions[0]["tax_amount"], Decimal("14.97"))
        self.assertEqual(suggestions[0]["gross_amount"], Decimal("93.75"))
        self.assertEqual(suggestions[1]["assignment_code"], "Hk92")
        self.assertEqual(suggestions[1]["net_amount"], Decimal("200.14"))
        self.assertEqual(suggestions[1]["tax_amount"], Decimal("38.02"))
        self.assertEqual(suggestions[1]["gross_amount"], Decimal("238.16"))

    def test_single_suggestion_keeps_negative_credit_note_amounts(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "755904-605.pdf",
        }
        extraction = {
            "supplier_name": "Rolf Dammers oHG",
            "currency": "EUR",
            "net_amount": "-220.00",
            "tax_amount": "-41.80",
            "gross_amount": "-261.80",
            "raw_result": {
                "document_type": "credit_note",
                "cost_category": "material",
                "assignment_code": "Wewe20",
                "assignment_kind": "construction_project",
            },
        }

        suggestions = _booking_suggestions_from_extraction(document, extraction)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["booking_type"], "credit_note")
        self.assertEqual(suggestions[0]["net_amount"], Decimal("-220.00"))
        self.assertEqual(suggestions[0]["tax_amount"], Decimal("-41.80"))
        self.assertEqual(suggestions[0]["gross_amount"], Decimal("-261.80"))

    def test_booking_update_rejects_unknown_cost_category(self):
        with self.assertRaises(ValidationError):
            BookingSuggestionUpdate(
                booking_type="incoming_invoice",
                cost_category="material_and_subcontractor",
                net_amount="100.00",
                tax_amount="19.00",
                gross_amount="119.00",
            )

    def test_booking_update_rejects_too_long_assignment_code(self):
        with self.assertRaises(ValidationError):
            BookingSuggestionUpdate(
                booking_type="incoming_invoice",
                assignment_code="x" * 81,
                net_amount="100.00",
                tax_amount="19.00",
                gross_amount="119.00",
            )
