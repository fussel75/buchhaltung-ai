from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.services import database as database_service
from app.services.extraction import _normalized_invoice_filename, _payment_terms
from app.routes.documents import BookingSuggestionUpdate, _download_filename
from app.routes.users import user_can_access_tenant
from app.services.database import (
    _booking_suggestions_from_extraction,
    build_booking_export_rows,
    find_accounting_rule,
    validate_document_review,
)


class RecordingCursor:
    def __init__(self, fetchone_result=None):
        self.statements = []
        self.fetchone_result = fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((" ".join(statement.split()), params))

    def fetchone(self):
        return self.fetchone_result


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

    def test_select_payment_decision_uses_extracted_term_values(self):
        document_id = uuid4()
        decision_id = uuid4()
        document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "review_ready",
            "extraction": {
                "currency": "EUR",
                "raw_result": {
                    "payment_terms": [
                        {
                            "type": "full_amount",
                            "label": "Ohne Abzug zahlen",
                            "due_date": "2026-06-05",
                            "amount": "1441.03",
                            "currency": "EUR",
                        },
                        {
                            "type": "cash_discount",
                            "label": "Skontozahlung",
                            "due_date": "2026-05-20",
                            "amount": "1405.01",
                            "discount_base": "1200.54",
                            "discount_percent": "3.00",
                            "discount_amount": "36.02",
                            "currency": "EUR",
                        },
                    ]
                },
            },
        }
        selected_document = {
            **document,
            "payment_decision": {"payment_type": "cash_discount", "amount": "1405.01"},
        }
        cursor = RecordingCursor(
            fetchone_result={
                "id": decision_id,
                "document_id": document_id,
                "tenant_id": "demo-mandant",
                "payment_type": "cash_discount",
                "label": "Skontozahlung",
                "due_date": "2026-05-20",
                "amount": Decimal("1405.01"),
                "discount_base": Decimal("1200.54"),
                "discount_percent": Decimal("3.00"),
                "discount_amount": Decimal("36.02"),
                "currency": "EUR",
                "status": "selected",
                "created_at": "2026-05-21T10:00:00+00:00",
                "updated_at": "2026-05-21T10:00:00+00:00",
            }
        )

        with (
            patch.object(database_service, "get_document", side_effect=[document, selected_document]),
            patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)),
            patch.object(database_service, "insert_audit_event") as audit_event,
        ):
            result = database_service.select_payment_decision(
                document_id,
                payment_type="cash_discount",
                actor="admin@example.com",
            )

        self.assertEqual(result["payment_decision"]["payment_type"], "cash_discount")
        self.assertTrue(any("insert into document_payment_decisions" in statement for statement, _ in cursor.statements))
        saved_params = cursor.statements[0][1]
        self.assertEqual(saved_params[3], "cash_discount")
        self.assertEqual(saved_params[6], Decimal("1405.01"))
        self.assertEqual(saved_params[9], Decimal("36.02"))
        audit_event.assert_called_once()
        self.assertEqual(audit_event.call_args.kwargs["event_type"], "document.payment_decision_selected")

    def test_select_payment_decision_rejects_unavailable_option(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "status": "review_ready",
            "extraction": {"raw_result": {"payment_terms": []}},
        }

        with patch.object(database_service, "get_document", return_value=document):
            with self.assertRaises(ValueError):
                database_service.select_payment_decision(uuid4(), payment_type="cash_discount")

    def test_booking_export_rows_include_payment_adjustment_for_cash_discount(self):
        document_id = uuid4()
        with patch.object(
            database_service,
            "list_accounting_rules",
            return_value=[
                {
                    "name": "Material Standard",
                    "supplier_match_text": None,
                    "cost_category": "material",
                    "debit_account": "3400",
                    "credit_account": "70000",
                    "tax_key": "9",
                    "tax_rate": "19.00",
                    "discount_account": "3736",
                    "is_active": True,
                }
            ],
        ):
            rows = build_booking_export_rows(
                [
                    {
                        "id": str(document_id),
                        "tenant_id": "demo-mandant",
                        "original_filename": "RE1574023.pdf",
                        "normalized_filename": "ERg RE1574023.pdf",
                        "status": "review_approved",
                        "extraction": {
                            "supplier_name": "Luechau Baustoffe GmbH",
                            "invoice_number": "RE1574023",
                            "invoice_date": "2026-05-07",
                            "gross_amount": "331.91",
                            "currency": "EUR",
                            "raw_result": {"document_type": "incoming_invoice"},
                        },
                        "booking_suggestions": [
                            {
                                "line_no": 1,
                                "booking_type": "incoming_invoice",
                                "cost_category": "material",
                                "assignment_kind": "construction_project",
                                "assignment_code": "Wewe20",
                                "description": "PE-Folie",
                                "net_amount": "278.92",
                                "tax_amount": "52.99",
                                "gross_amount": "331.91",
                            }
                        ],
                        "payment_decision": {
                            "payment_type": "cash_discount",
                            "label": "Skontozahlung",
                            "due_date": "2026-05-21",
                            "amount": "324.63",
                            "discount_base": "242.66",
                            "discount_percent": "3.00",
                            "discount_amount": "7.28",
                        },
                    }
                ]
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["row_type"], "cost")
        self.assertEqual(rows[0]["gross_amount"], "331.91")
        self.assertEqual(rows[0]["debit_account"], "3400")
        self.assertEqual(rows[0]["credit_account"], "70000")
        self.assertEqual(rows[0]["tax_key"], "9")
        self.assertEqual(rows[1]["row_type"], "payment_adjustment")
        self.assertEqual(rows[1]["gross_amount"], "-7.28")
        self.assertEqual(rows[1]["payable_delta"], "-7.28")
        self.assertEqual(rows[1]["debit_account"], "3736")
        self.assertEqual(rows[1]["payment_type"], "cash_discount")

    def test_booking_export_rows_skip_unapproved_documents(self):
        rows = build_booking_export_rows(
            [
                {
                    "id": str(uuid4()),
                    "tenant_id": "demo-mandant",
                    "status": "review_ready",
                    "extraction": {"raw_result": {}},
                    "booking_suggestions": [{"line_no": 1, "gross_amount": "10.00"}],
                }
            ]
        )

        self.assertEqual(rows, [])

    def test_accounting_rule_matching_prefers_supplier_and_cost_category(self):
        rules = [
            {
                "name": "Material Standard",
                "supplier_match_text": None,
                "cost_category": "material",
                "debit_account": "3400",
                "credit_account": "70000",
                "tax_key": "9",
                "tax_rate": "19.00",
                "discount_account": None,
                "is_active": True,
            },
            {
                "name": "Luechau Material",
                "supplier_match_text": "Luechau",
                "cost_category": "material",
                "debit_account": "3425",
                "credit_account": "70001",
                "tax_key": "9",
                "tax_rate": "19.00",
                "discount_account": "3736",
                "is_active": True,
            },
        ]

        with patch.object(database_service, "list_accounting_rules", return_value=rules):
            rule = find_accounting_rule(
                tenant_id="demo-mandant",
                supplier_name="Luechau Baustoffe GmbH",
                cost_category="material",
            )

        self.assertEqual(rule["name"], "Luechau Material")

    def test_review_validation_blocks_missing_accounting_rule_and_payment_choice(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "RE1574023.pdf",
            "extraction": {
                "supplier_name": "Luechau Baustoffe GmbH",
                "invoice_number": "RE1574023",
                "invoice_date": "2026-05-07",
                "net_amount": "278.92",
                "tax_amount": "52.99",
                "gross_amount": "331.91",
                "currency": "EUR",
                "confidence": Decimal("0.88"),
                "warnings": [],
                "raw_result": {
                    "document_type": "incoming_invoice",
                    "payment_terms": [
                        {"type": "full_amount", "label": "Ohne Abzug", "amount": "331.91"},
                        {"type": "cash_discount", "label": "Skonto", "amount": "324.63", "discount_amount": "7.28"},
                    ],
                },
            },
            "booking_suggestions": [
                {
                    "line_no": 1,
                    "booking_type": "incoming_invoice",
                    "cost_category": "material",
                    "description": "PE-Folie",
                    "net_amount": "278.92",
                    "tax_amount": "52.99",
                    "gross_amount": "331.91",
                    "currency": "EUR",
                }
            ],
        }

        with patch.object(database_service, "list_accounting_rules", return_value=[]):
            errors = validate_document_review(document)

        self.assertIn("Zeile 1: Kontierungsregel fehlt.", errors)
        self.assertIn("Zahlungsentscheidung fehlt: Skonto/ohne Abzug/Gutschrift-Verrechnung muss gewaehlt werden.", errors)

    def test_review_validation_accepts_complete_review(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "RE1574023.pdf",
            "extraction": {
                "supplier_name": "Luechau Baustoffe GmbH",
                "invoice_number": "RE1574023",
                "invoice_date": "2026-05-07",
                "net_amount": "278.92",
                "tax_amount": "52.99",
                "gross_amount": "331.91",
                "currency": "EUR",
                "confidence": Decimal("0.88"),
                "warnings": [],
                "raw_result": {"document_type": "incoming_invoice"},
            },
            "booking_suggestions": [
                {
                    "line_no": 1,
                    "booking_type": "incoming_invoice",
                    "cost_category": "material",
                    "description": "PE-Folie",
                    "net_amount": "278.92",
                    "tax_amount": "52.99",
                    "gross_amount": "331.91",
                    "currency": "EUR",
                }
            ],
            "payment_decision": {"payment_type": "full_amount", "amount": "331.91"},
        }
        rules = [
            {
                "name": "Material Standard",
                "supplier_match_text": None,
                "cost_category": "material",
                "debit_account": "3400",
                "credit_account": "70000",
                "tax_key": "9",
                "tax_rate": "19.00",
                "discount_account": "3736",
                "is_active": True,
            }
        ]

        with patch.object(database_service, "list_accounting_rules", return_value=rules):
            errors = validate_document_review(document)

        self.assertEqual(errors, [])

    def test_review_validation_blocks_warnings_and_split_mismatch(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "RE1574023.pdf",
            "extraction": {
                "supplier_name": "Luechau Baustoffe GmbH",
                "invoice_number": "RE1574023",
                "invoice_date": "2026-05-07",
                "net_amount": "278.92",
                "tax_amount": "52.99",
                "gross_amount": "331.91",
                "currency": "EUR",
                "confidence": Decimal("0.88"),
                "warnings": ["Splittung pruefen."],
                "raw_result": {"document_type": "incoming_invoice", "allocation_lines": [{"amount": "278.00"}]},
            },
            "booking_suggestions": [
                {
                    "line_no": 1,
                    "booking_type": "incoming_invoice",
                    "cost_category": "material",
                    "description": "PE-Folie",
                    "net_amount": "278.00",
                    "tax_amount": "52.82",
                    "gross_amount": "330.82",
                    "currency": "EUR",
                }
            ],
            "payment_decision": {"payment_type": "full_amount", "amount": "331.91"},
        }
        rules = [
            {
                "name": "Material Standard",
                "supplier_match_text": None,
                "cost_category": "material",
                "debit_account": "3400",
                "credit_account": "70000",
                "tax_key": "9",
                "tax_rate": "19.00",
                "discount_account": "3736",
                "is_active": True,
            }
        ]

        with patch.object(database_service, "list_accounting_rules", return_value=rules):
            errors = validate_document_review(document)

        self.assertIn("Offene Extraktionswarnungen muessen vor finaler Freigabe geklaert werden.", errors)
        self.assertIn("Split-Summe Brutto passt nicht zum Beleggesamtbetrag.", errors)

    def test_review_validation_blocks_structured_xml_validation_errors(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "invoice.xml",
            "extraction": {
                "supplier_name": "Beispiel Lieferant GmbH",
                "invoice_number": "XR-2026-1001",
                "invoice_date": "2026-05-21",
                "net_amount": "100.00",
                "tax_amount": "19.00",
                "gross_amount": "118.00",
                "currency": "EUR",
                "confidence": Decimal("0.90"),
                "warnings": [],
                "raw_result": {
                    "document_type": "incoming_invoice",
                    "source": "standalone_xml",
                    "xml_format": "ubl",
                    "structured_validation_errors": [
                        "Summenpruefung fehlgeschlagen: Netto plus USt passt nicht zu Brutto."
                    ],
                },
            },
            "booking_suggestions": [
                {
                    "line_no": 1,
                    "booking_type": "incoming_invoice",
                    "cost_category": "software",
                    "description": "Software Abo",
                    "net_amount": "100.00",
                    "tax_amount": "19.00",
                    "gross_amount": "118.00",
                    "currency": "EUR",
                }
            ],
            "payment_decision": {"payment_type": "full_amount", "amount": "118.00"},
        }
        rules = [
            {
                "name": "Software Standard",
                "supplier_match_text": None,
                "cost_category": "software",
                "debit_account": "4806",
                "credit_account": "70000",
                "tax_key": "9",
                "tax_rate": "19.00",
                "discount_account": "3736",
                "is_active": True,
            }
        ]

        with patch.object(database_service, "list_accounting_rules", return_value=rules):
            errors = validate_document_review(document)

        self.assertEqual(errors, ["E-Rechnungsvalidierung ist fehlgeschlagen."])

    def test_tenant_access_requires_admin_or_explicit_assignment(self):
        self.assertTrue(user_can_access_tenant({"role": "admin", "allowed_tenant_ids": []}, "fremd-mandant"))
        self.assertTrue(
            user_can_access_tenant(
                {"role": "user", "allowed_tenant_ids": ["demo-mandant"]},
                "demo-mandant",
            )
        )
        self.assertFalse(
            user_can_access_tenant(
                {"role": "user", "allowed_tenant_ids": ["demo-mandant"]},
                "fremd-mandant",
            )
        )
