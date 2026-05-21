from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.services import database as database_service
from app.services.extraction import _normalized_invoice_filename, _payment_terms
from app.routes.documents import BookingSuggestionUpdate, _download_filename
from app.services.database import _booking_suggestions_from_extraction


class RecordingCursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((" ".join(statement.split()), params))


class RecordingConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


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

    def test_normalized_invoice_filename_is_windows_safe(self):
        filename = _normalized_invoice_filename(
            invoice_number="RE1574023",
            assignment=None,
            assignment_type="assignment_split",
            tenant_profile={
                "assignment_label_singular": "Bauvorhaben",
                "assignment_label_plural": "BV",
                "assignment_code_prefix": "BV",
            },
            supplier_name="Luechau Baustoffe GmbH",
            product_name="PE-Folie 200 my / Baustoffe",
            invoice_date="2026-05-07",
        )

        self.assertEqual(
            filename,
            "ERg RE1574023, BV aufgeteilt, Luechau Baustoffe GmbH, PE-Folie 200 my Baustoffe, 2026-05-07.pdf",
        )
        self.assertFalse(any(character in filename for character in '<>:"/\\|?*'))

    def test_download_filename_is_windows_safe_for_existing_rows(self):
        filename = _download_filename(
            {
                "id": str(uuid4()),
                "normalized_filename": "ERg RE1574023, BV aufgeteilt, Luechau Baustoffe GmbH, PE-Folie 200 my / Baustoffe, 2026-05-07.pdf",
                "original_filename": "RE1574023.pdf",
            }
        )

        self.assertEqual(
            filename,
            "ERg RE1574023, BV aufgeteilt, Luechau Baustoffe GmbH, PE-Folie 200 my Baustoffe, 2026-05-07.pdf",
        )
        self.assertFalse(any(character in filename for character in '<>:"/\\|?*'))

    def test_reopen_approved_review_unlocks_existing_suggestions(self):
        document_id = uuid4()
        suggestion_id = uuid4()
        approved_document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "review_approved",
            "extraction": {"invoice_number": "RE1574023"},
            "booking_suggestions": [{"id": str(suggestion_id), "status": "approved"}],
        }
        reopened_document = {
            **approved_document,
            "status": "review_ready",
            "booking_suggestions": [{"id": str(suggestion_id), "status": "reviewed"}],
        }
        cursor = RecordingCursor()

        with (
            patch.object(database_service, "get_document", side_effect=[approved_document, reopened_document]),
            patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)),
            patch.object(database_service, "insert_audit_event") as audit_event,
        ):
            result = database_service.reopen_document_review(document_id, actor="admin@example.com")

        self.assertEqual(result["status"], "review_ready")
        self.assertTrue(any("status = 'reviewed'" in statement for statement, _ in cursor.statements))
        self.assertTrue(any("status = 'review_ready'" in statement for statement, _ in cursor.statements))
        audit_event.assert_called_once()
        self.assertEqual(audit_event.call_args.kwargs["event_type"], "document.review_reopened")

    def test_payment_terms_for_incoming_invoice_discount(self):
        terms = _payment_terms(
            gross_amount=Decimal("1441.03"),
            due_date="2026-06-05",
            discount_due_date="2026-05-20",
            discount_base=Decimal("1200.54"),
            discount_percent=Decimal("3.00"),
            discount_amount=Decimal("36.02"),
            discounted_payable_amount=Decimal("1405.01"),
            is_credit_note=False,
        )

        self.assertEqual(terms[0]["type"], "full_amount")
        self.assertEqual(terms[0]["amount"], Decimal("1441.03"))
        self.assertEqual(terms[1]["type"], "cash_discount")
        self.assertEqual(terms[1]["discount_amount"], Decimal("36.02"))
        self.assertEqual(terms[1]["amount"], Decimal("1405.01"))

    def test_payment_terms_for_credit_note_keep_discount_effect_negative(self):
        terms = _payment_terms(
            gross_amount=Decimal("-261.80"),
            due_date=None,
            discount_due_date="2026-05-15",
            discount_base=Decimal("340.00"),
            discount_percent=Decimal("3.00"),
            discount_amount=Decimal("12.14"),
            discounted_payable_amount=None,
            is_credit_note=True,
        )

        self.assertEqual(terms[0]["type"], "full_amount")
        self.assertEqual(terms[0]["amount"], Decimal("-261.80"))
        self.assertEqual(terms[1]["type"], "credit_note_settlement")
        self.assertEqual(terms[1]["discount_amount"], Decimal("-12.14"))
        self.assertEqual(terms[1]["amount"], Decimal("-273.94"))
