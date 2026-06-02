from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import call, patch
from uuid import uuid4

from pydantic import ValidationError
from fastapi import HTTPException

from app.routes import documents as documents_route
from app.routes import masterdata as masterdata_route
from app.services import bulk_jobs as bulk_job_service
from app.services import database as database_service
from app.services import extraction as extraction_service
from app.services.extraction import _cost_category_for_supplier_rule, _normalized_invoice_filename, _payment_terms, run_mock_extraction
from app.routes.documents import BookingSuggestionUpdate, _download_filename
from app.routes.users import user_can_access_tenant
from app.services.database import (
    _booking_suggestions_from_extraction,
    build_booking_export_rows,
    find_accounting_rule,
    validate_document_review,
    validate_document_review_details,
)


class RecordingCursor:
    def __init__(self, fetchone_result=None, fetchall_result=None):
        self.statements = []
        self.fetchone_result = fetchone_result
        self.fetchall_result = fetchall_result or []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((" ".join(statement.split()), params))

    def fetchone(self):
        return self.fetchone_result

    def fetchall(self):
        return self.fetchall_result


class RecordingConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


class SequenceCursor(RecordingCursor):
    def __init__(self, fetchone_results=None, fetchall_result=None):
        super().__init__(fetchall_result=fetchall_result)
        self.fetchone_results = list(fetchone_results or [])

    def fetchone(self):
        if not self.fetchone_results:
            return None
        return self.fetchone_results.pop(0)


class TenantProfileTests(TestCase):
    def test_tenant_profile_route_passes_accounting_framework(self):
        request = SimpleNamespace(state=SimpleNamespace(user={"role": "admin"}))
        payload = masterdata_route.TenantProfileRequest(
            display_name="Demo",
            industry="construction",
            assignment_label_singular="Bauvorhaben",
            assignment_label_plural="Bauvorhaben",
            assignment_code_label="Bauvorhaben",
            assignment_code_prefix="BV",
            default_assignment_kind="construction_project",
            allow_multiple_assignments=True,
            accounting_framework="SKR04",
        )
        saved_profile = {
            "tenant_id": "demo-mandant",
            "display_name": "Demo",
            "industry": "construction",
            "assignment_label_singular": "Bauvorhaben",
            "assignment_label_plural": "Bauvorhaben",
            "assignment_code_label": "Bauvorhaben",
            "assignment_code_prefix": "BV",
            "default_assignment_kind": "construction_project",
            "allow_multiple_assignments": True,
            "accounting_framework": "SKR04",
        }

        with (
            patch.object(masterdata_route, "require_admin") as require_admin,
            patch.object(masterdata_route, "upsert_tenant_profile", return_value=saved_profile) as upsert_profile,
        ):
            result = masterdata_route.put_profile(payload, request, tenant_id=" demo-mandant ")

        require_admin.assert_called_once_with(request)
        upsert_profile.assert_called_once()
        self.assertEqual(upsert_profile.call_args.kwargs["tenant_id"], "demo-mandant")
        self.assertEqual(upsert_profile.call_args.kwargs["accounting_framework"], "SKR04")
        self.assertEqual(result["tenant_profile"]["accounting_framework"], "SKR04")

    def test_upsert_tenant_profile_normalizes_accounting_framework(self):
        now = datetime.now(UTC)
        row = {
            "tenant_id": "demo-mandant",
            "display_name": "Demo",
            "industry": "construction",
            "assignment_label_singular": "Bauvorhaben",
            "assignment_label_plural": "Bauvorhaben",
            "assignment_code_label": "Bauvorhaben",
            "assignment_code_prefix": "BV",
            "default_assignment_kind": "construction_project",
            "allow_multiple_assignments": True,
            "accounting_framework": "SKR04",
            "created_at": now,
            "updated_at": now,
        }
        cursor = RecordingCursor(fetchone_result=row)

        with patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)):
            profile = database_service.upsert_tenant_profile(
                tenant_id="demo-mandant",
                display_name="Demo",
                industry="construction",
                assignment_label_singular="Bauvorhaben",
                assignment_label_plural="Bauvorhaben",
                assignment_code_label="Bauvorhaben",
                assignment_code_prefix="BV",
                default_assignment_kind="construction_project",
                allow_multiple_assignments=True,
                accounting_framework="skr04",
            )

        self.assertEqual(profile["accounting_framework"], "SKR04")
        self.assertEqual(cursor.statements[0][1][9], "SKR04")


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

    def test_manual_normalized_filename_keeps_document_suffix(self):
        document = {
            "tenant_id": "demo-mandant",
            "original_filename": "invoice.xml",
            "storage_path": "demo-mandant/invoice.xml",
        }
        extraction = {
            "supplier_name": "XML Lieferant GmbH",
            "invoice_number": "X-1",
            "invoice_date": "2026-05-21",
            "raw_result": {"item_summary": "E-Rechnung", "assignment_type": "general_cost"},
        }

        with (
            patch.object(
                database_service,
                "ensure_tenant_profile",
                return_value={
                    "assignment_label_singular": "Bauvorhaben",
                    "assignment_label_plural": "Bauvorhaben",
                    "assignment_code_prefix": "BV",
                },
            ),
            patch.object(database_service, "get_assignment_unit_by_code", return_value=None),
        ):
            filename = database_service._manual_normalized_invoice_filename(document, extraction)

        self.assertEqual(filename, "ERg X-1, Allgemeine Kosten, XML Lieferant GmbH, E-Rechnung, 2026-05-21.xml")

    def test_manual_assignment_type_keeps_split_and_unresolved(self):
        self.assertEqual(
            database_service._manual_assignment_type(
                {"allocation_lines": [{"assignment_code": "Wewe20"}, {"assignment_code": "Hk92"}]},
                None,
            ),
            "assignment_split",
        )
        self.assertEqual(
            database_service._manual_assignment_type({"assignment_type": "assignment_unresolved"}, None),
            "assignment_unresolved",
        )

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

    def test_approve_review_requires_review_ready_status(self):
        document_id = uuid4()
        document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "extracted",
            "extraction": {"invoice_number": "RE1574023"},
            "booking_suggestions": [{"id": str(uuid4()), "status": "reviewed"}],
        }

        with patch.object(database_service, "get_document", return_value=document):
            with self.assertRaises(database_service.ReviewApprovalError) as context:
                database_service.approve_document_review(document_id, actor="admin@example.com")

        self.assertIn("Status Vorschlag", context.exception.errors[0])

    def test_approve_review_allows_review_ready_status(self):
        document_id = uuid4()
        document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "review_ready",
            "extraction": {"invoice_number": "RE1574023"},
            "booking_suggestions": [{"id": str(uuid4()), "status": "reviewed"}],
        }
        approved_document = {**document, "status": "review_approved"}
        cursor = RecordingCursor()

        with (
            patch.object(database_service, "get_document", side_effect=[document, approved_document]),
            patch.object(database_service, "validate_document_review", return_value=[]),
            patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)),
            patch.object(database_service, "insert_audit_event") as audit_event,
        ):
            result = database_service.approve_document_review(document_id, actor="admin@example.com")

        self.assertEqual(result["status"], "review_approved")
        self.assertTrue(any("status = 'approved'" in statement for statement, _ in cursor.statements))
        self.assertTrue(any("status = 'review_approved'" in statement for statement, _ in cursor.statements))
        audit_event.assert_called_once()
        self.assertEqual(audit_event.call_args.kwargs["event_type"], "document.review_approved")

    def test_review_validation_route_returns_details_without_approval(self):
        document_id = uuid4()
        document = {"id": str(document_id), "tenant_id": "demo-mandant", "status": "review_ready"}
        details = [
            {
                "code": "missing_accounting_rule",
                "message": "Zeile 1: Kontierungsregel fehlt.",
                "line_no": 1,
            }
        ]

        with (
            patch.object(documents_route, "require_document_access", return_value=document) as require_access,
            patch.object(documents_route, "validate_document_review_details", return_value=details) as validate_details,
        ):
            result = documents_route.get_review_validation(document_id, SimpleNamespace(state=SimpleNamespace()))

        require_access.assert_called_once()
        validate_details.assert_called_once_with(document)
        self.assertFalse(result["is_ready"])
        self.assertEqual(result["errors"], ["Zeile 1: Kontierungsregel fehlt."])
        self.assertEqual(result["details"], details)

    def test_review_validation_route_blocks_non_ready_status(self):
        document_id = uuid4()
        document = {"id": str(document_id), "tenant_id": "demo-mandant", "status": "extracted"}

        with (
            patch.object(documents_route, "require_document_access", return_value=document),
            patch.object(documents_route, "validate_document_review_details", return_value=[]),
        ):
            result = documents_route.get_review_validation(document_id, SimpleNamespace(state=SimpleNamespace()))

        self.assertFalse(result["is_ready"])
        self.assertEqual(result["details"][0]["code"], "invalid_review_status")
        self.assertIn("Status Vorschlag", result["errors"][0])

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

    def test_supplier_rule_update_can_clear_default_assignment(self):
        rule_id = uuid4()
        row = {
            "id": rule_id,
            "tenant_id": "demo-mandant",
            "match_text": "Holz Junge",
            "supplier_name": "Holz Junge GmbH",
            "customer_number": "109324",
            "default_cost_category": "material",
            "default_assignment_code": None,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }
        cursor = RecordingCursor(fetchone_result=row)

        with patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)):
            rule = database_service.update_supplier_rule(
                rule_id=rule_id,
                match_text="Holz Junge",
                supplier_name="Holz Junge GmbH",
                customer_number="109324",
                default_cost_category="material",
                default_assignment_code="",
                is_active=True,
            )

        params = cursor.statements[0][1]
        self.assertIsNone(params[4])
        self.assertIsNone(rule["default_assignment_code"])

    def test_supplier_rule_update_accepts_multiple_cost_categories(self):
        rule_id = uuid4()
        row = {
            "id": rule_id,
            "tenant_id": "demo-mandant",
            "match_text": "konzept 54",
            "supplier_name": "konzept 54 GmbH & Co.KG",
            "customer_number": "10019",
            "default_cost_category": "material,subcontractor",
            "default_assignment_code": None,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }
        cursor = RecordingCursor(fetchone_result=row)

        with patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)):
            rule = database_service.update_supplier_rule(
                rule_id=rule_id,
                match_text="konzept 54",
                supplier_name="konzept 54 GmbH & Co.KG",
                customer_number="10019",
                default_cost_category=["material", "subcontractor"],
                default_assignment_code=None,
                is_active=True,
            )

        params = cursor.statements[0][1]
        self.assertEqual(params[3], "material,subcontractor")
        self.assertEqual(rule["default_cost_categories"], ["material", "subcontractor"])

    def test_multi_cost_supplier_rule_uses_detected_allowed_category(self):
        rule = {"default_cost_category": "material,subcontractor"}

        subcontractor = _cost_category_for_supplier_rule(
            supplier_rule=rule,
            supplier_name="konzept 54 GmbH & Co.KG",
            product_name="Malerarbeiten",
            text="Ausführung Fremdleistung Maler",
            assignment_type="assigned",
        )
        unclear = _cost_category_for_supplier_rule(
            supplier_rule=rule,
            supplier_name="konzept 54 GmbH & Co.KG",
            product_name="Eingangsrechnung",
            text="Monatliche Verwaltungspauschale",
            assignment_type="general_cost",
        )

        self.assertEqual(subcontractor, "subcontractor")
        self.assertIsNone(unclear)

    def test_accounting_rule_update_can_clear_optional_fields(self):
        rule_id = uuid4()
        row = {
            "id": rule_id,
            "tenant_id": "demo-mandant",
            "name": "Material Standard",
            "supplier_match_text": None,
            "cost_category": None,
            "debit_account": "3400",
            "credit_account": "70000",
            "tax_key": None,
            "tax_rate": None,
            "discount_account": None,
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }
        cursor = RecordingCursor(fetchone_result=row)

        with patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)):
            rule = database_service.update_accounting_rule(
                rule_id=rule_id,
                name="Material Standard",
                supplier_match_text="",
                cost_category="",
                debit_account="3400",
                credit_account="70000",
                tax_key="",
                tax_rate=None,
                discount_account="",
                is_active=True,
            )

        params = cursor.statements[0][1]
        self.assertIsNone(params[1])
        self.assertIsNone(params[2])
        self.assertIsNone(params[5])
        self.assertIsNone(params[7])
        self.assertIsNone(rule["supplier_match_text"])
        self.assertIsNone(rule["discount_account"])

    def test_extraction_blocks_review_ready_documents(self):
        document_id = uuid4()
        document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "review_ready",
            "original_filename": "rechnung.pdf",
        }

        with (
            patch.object(extraction_service, "get_document", return_value=document),
            patch.object(extraction_service, "insert_audit_event") as insert_audit_event,
        ):
            with self.assertRaises(HTTPException) as context:
                run_mock_extraction(document_id)

        self.assertEqual(context.exception.status_code, 409)
        insert_audit_event.assert_not_called()

    def test_extraction_blocks_already_extracted_documents(self):
        document_id = uuid4()
        document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "extracted",
            "original_filename": "rechnung.pdf",
        }

        with (
            patch.object(extraction_service, "get_document", return_value=document),
            patch.object(extraction_service, "save_document_extraction") as save_document_extraction,
        ):
            with self.assertRaises(HTTPException) as context:
                run_mock_extraction(document_id)

        self.assertEqual(context.exception.status_code, 409)
        save_document_extraction.assert_not_called()

    def test_force_reextract_allows_existing_extraction_and_audits(self):
        document_id = uuid4()
        document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "review_ready",
            "original_filename": "rechnung.pdf",
            "processing_job_id": None,
            "extraction": {"id": str(uuid4())},
        }
        extraction = {
            "supplier_name": "Theo Foerch GmbH & Co. KG",
            "invoice_number": "3161691971",
            "invoice_date": "2026-05-21",
            "service_period": "2026-05",
            "net_amount": Decimal("7.37"),
            "tax_amount": Decimal("1.40"),
            "gross_amount": Decimal("8.77"),
            "currency": "EUR",
            "confidence": Decimal("0.88"),
            "warnings": [],
            "normalized_filename": None,
        }
        saved_document = {**document, "status": "extracted"}

        with (
            patch.object(extraction_service, "get_document", return_value=document),
            patch.object(extraction_service, "_build_extraction_result", return_value=extraction),
            patch.object(extraction_service, "save_document_extraction", return_value=saved_document) as save_extraction,
            patch.object(extraction_service, "insert_audit_event") as insert_audit_event,
        ):
            result = run_mock_extraction(document_id, force=True, actor="admin@example.com")

        self.assertEqual(result["status"], "extracted")
        save_extraction.assert_called_once()
        insert_audit_event.assert_called_once()
        self.assertEqual(insert_audit_event.call_args.kwargs["event_type"], "document.reextraction_started")
        self.assertEqual(insert_audit_event.call_args.kwargs["actor"], "admin@example.com")
        self.assertEqual(insert_audit_event.call_args.kwargs["details"], {"previous_status": "review_ready"})

    def test_force_reextract_blocks_documents_without_existing_extraction(self):
        document_id = uuid4()
        document = {
            "id": str(document_id),
            "tenant_id": "demo-mandant",
            "status": "review_pending",
            "original_filename": "rechnung.pdf",
            "processing_job_id": None,
            "extraction": None,
        }

        with (
            patch.object(extraction_service, "get_document", return_value=document),
            patch.object(extraction_service, "save_document_extraction") as save_extraction,
            patch.object(extraction_service, "insert_audit_event") as insert_audit_event,
        ):
            with self.assertRaises(HTTPException) as context:
                run_mock_extraction(document_id, force=True)

        self.assertEqual(context.exception.status_code, 409)
        save_extraction.assert_not_called()
        insert_audit_event.assert_not_called()

    def test_reextract_route_requires_explicit_confirmation(self):
        request = SimpleNamespace(
            state=SimpleNamespace(user={"role": "admin", "email": "admin@example.com", "allowed_tenant_ids": ["*"]})
        )
        payload = documents_route.DocumentReextractRequest(confirm=False)

        with self.assertRaises(HTTPException) as context:
            documents_route.reextract_document(uuid4(), payload, request)

        self.assertEqual(context.exception.status_code, 400)

    def test_save_extraction_clears_stale_payment_decision(self):
        document_id = uuid4()
        tenant_id = "demo-mandant"
        now = datetime.now(UTC)
        extraction_row = {
            "id": uuid4(),
            "document_id": document_id,
            "tenant_id": tenant_id,
            "supplier_name": "Theo Foerch GmbH & Co. KG",
            "invoice_number": "3161691971",
            "invoice_date": "2026-05-21",
            "service_period": "2026-05",
            "net_amount": Decimal("7.37"),
            "tax_amount": Decimal("1.40"),
            "gross_amount": Decimal("8.77"),
            "currency": "EUR",
            "confidence": Decimal("0.88"),
            "warnings": [],
            "raw_result": {},
            "created_at": now,
            "updated_at": now,
        }
        document_row = {
            "id": document_id,
            "tenant_id": tenant_id,
            "original_filename": "rechnung.pdf",
            "normalized_filename": None,
            "content_type": "application/pdf",
            "sha256": "abc",
            "size_bytes": 123,
            "storage_path": "demo-mandant/abc.pdf",
            "status": "extracted",
            "processing_job_id": None,
            "processing_started_at": None,
            "duplicate_of": None,
            "created_at": now,
            "updated_at": now,
            "extraction": None,
            "booking_suggestions": [],
            "payment_decision": None,
        }
        cursor = SequenceCursor(fetchone_results=[extraction_row, document_row])

        with (
            patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)),
            patch.object(database_service, "insert_audit_event"),
        ):
            result = database_service.save_document_extraction(
                document_id=document_id,
                tenant_id=tenant_id,
                extraction={
                    "supplier_name": "Theo Foerch GmbH & Co. KG",
                    "invoice_number": "3161691971",
                    "invoice_date": "2026-05-21",
                    "service_period": "2026-05",
                    "net_amount": Decimal("7.37"),
                    "tax_amount": Decimal("1.40"),
                    "gross_amount": Decimal("8.77"),
                    "currency": "EUR",
                    "confidence": Decimal("0.88"),
                    "warnings": [],
                },
            )

        self.assertEqual(result["status"], "extracted")
        self.assertTrue(
            any(statement == "delete from document_payment_decisions where document_id = %s" for statement, _ in cursor.statements)
        )

    def test_update_extraction_resets_review_artifacts(self):
        document_id = uuid4()
        tenant_id = "demo-mandant"
        now = datetime.now(UTC)
        document = {
            "id": str(document_id),
            "tenant_id": tenant_id,
            "storage_path": "demo-mandant/old.pdf",
            "status": "review_ready",
            "extraction": {
                "id": str(uuid4()),
                "supplier_name": "Alt GmbH",
                "invoice_number": "A-1",
                "invoice_date": "2026-05-21",
                "service_period": None,
                "net_amount": "7.37",
                "tax_amount": "1.40",
                "gross_amount": "8.77",
                "currency": "EUR",
                "confidence": 0.88,
                "warnings": ["Nicht sicher erkannt: Zahlungsdaten."],
                "raw_result": {
                    "customer_number": "111",
                    "document_type": "incoming_invoice",
                    "payment_terms": [{"type": "cash_discount", "amount": "8.51"}],
                    "project_code": "AltBV",
                },
            },
        }
        updated_document = {**document, "status": "extracted"}
        extraction_row = {
            "id": uuid4(),
            "document_id": document_id,
            "tenant_id": tenant_id,
            "supplier_name": "Theo Foerch GmbH & Co. KG",
            "invoice_number": "3161691971",
            "invoice_date": "2026-05-21",
            "service_period": None,
            "net_amount": Decimal("7.37"),
            "tax_amount": Decimal("1.40"),
            "gross_amount": Decimal("8.77"),
            "currency": "EUR",
            "confidence": Decimal("0.88"),
            "warnings": [],
            "raw_result": {"customer_number": "425590", "document_type": "incoming_invoice"},
            "created_at": now,
            "updated_at": now,
        }
        cursor = RecordingCursor(fetchone_result=extraction_row)

        with (
            patch.object(database_service, "get_document", side_effect=[document, updated_document]),
            patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)),
            patch.object(database_service, "Jsonb", side_effect=lambda value: value),
            patch.object(
                database_service,
                "ensure_tenant_profile",
                return_value={
                    "assignment_label_singular": "Bauvorhaben",
                    "assignment_label_plural": "Bauvorhaben",
                    "assignment_code_prefix": "BV",
                },
            ),
            patch.object(database_service, "get_assignment_unit_by_code", return_value=None),
            patch.object(database_service, "rename_stored_document", return_value=Path("demo-mandant/new.pdf")) as rename_file,
            patch.object(database_service, "insert_audit_event") as audit_event,
        ):
            result = database_service.update_document_extraction(
                document_id=document_id,
                values={
                    "supplier_name": "Theo Foerch GmbH & Co. KG",
                    "customer_number": "425590",
                    "assignment_code": None,
                    "due_date": date(2026, 6, 20),
                    "discount_due_date": date(2026, 5, 31),
                    "discount_amount": Decimal("0.26"),
                },
                actor="admin@example.com",
            )

        self.assertEqual(result["status"], "extracted")
        update_params = next(params for statement, params in cursor.statements if "update document_extractions" in statement)
        raw_result = update_params[10]
        self.assertEqual(update_params[8], Decimal("1.00"))
        self.assertEqual(update_params[9], [])
        self.assertEqual(raw_result["due_date"], "2026-06-20")
        self.assertEqual(raw_result["discount_due_date"], "2026-05-31")
        self.assertEqual(raw_result["discount_amount"], "0.26")
        self.assertNotIn("payment_terms", raw_result)
        self.assertNotIn("project_code", raw_result)
        self.assertIsNone(raw_result["assignment_code"])
        document_update_params = next(params for statement, params in cursor.statements if "update documents" in statement)
        self.assertEqual(
            document_update_params[0],
            "ERg A-1, Allgemeine Kosten, Theo Foerch GmbH & Co. KG, Eingangsrechnung, 2026-05-21.pdf",
        )
        self.assertEqual(document_update_params[1], "demo-mandant/new.pdf")
        rename_file.assert_called_once()
        self.assertTrue(any(statement == "delete from document_booking_suggestions where document_id = %s" for statement, _ in cursor.statements))
        self.assertTrue(any(statement == "delete from document_payment_decisions where document_id = %s" for statement, _ in cursor.statements))
        audit_event.assert_called_once()
        self.assertEqual(audit_event.call_args.kwargs["event_type"], "document.extraction_updated")

    def test_bulk_extraction_validation_blocks_non_pending_documents(self):
        document_id = uuid4()
        request = SimpleNamespace(state=SimpleNamespace(user={"role": "admin", "allowed_tenant_ids": ["*"]}))
        payload = documents_route.DocumentBulkJobRequest(
            tenant_id="demo-mandant",
            document_ids=[document_id],
        )

        with patch.object(
            documents_route,
            "require_document_access",
            return_value={
                "id": str(document_id),
                "tenant_id": "demo-mandant",
                "status": "extracted",
                "extraction": {"id": str(uuid4())},
                "booking_suggestions": [],
            },
        ):
            with self.assertRaises(HTTPException) as context:
                documents_route._validated_bulk_documents(request, payload, "extract")

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["documents"][0]["reason"], "Beleg ist nicht offen für Extraktion.")

    def test_list_bulk_jobs_route_requires_tenant_access(self):
        request = SimpleNamespace(state=SimpleNamespace(user={"role": "admin", "allowed_tenant_ids": ["*"]}))
        jobs = [
            {
                "id": str(uuid4()),
                "tenant_id": "demo-mandant",
                "action": "extract",
                "status": "completed",
                "requested_total": 3,
                "processed_count": 3,
                "succeeded_count": 3,
                "failed_count": 0,
            }
        ]

        with (
            patch.object(documents_route, "require_tenant_access") as require_access,
            patch.object(documents_route, "list_document_bulk_jobs", return_value=jobs) as list_jobs,
        ):
            result = documents_route.list_bulk_jobs(request, tenant_id=" demo-mandant ", limit=5)

        require_access.assert_called_once_with(request, "demo-mandant")
        list_jobs.assert_called_once_with(tenant_id="demo-mandant", limit=5)
        self.assertEqual(result, {"jobs": jobs})

    def test_list_document_bulk_jobs_orders_recent_jobs_for_tenant(self):
        job_id = uuid4()
        cursor = RecordingCursor(
            fetchall_result=[
                {
                    "id": job_id,
                    "tenant_id": "demo-mandant",
                    "action": "extract",
                    "status": "completed",
                    "requested_total": 2,
                    "processed_count": 2,
                    "succeeded_count": 2,
                    "failed_count": 0,
                    "error": None,
                    "created_by": "admin@example.com",
                    "created_at": "2026-05-22T09:00:00+00:00",
                    "updated_at": "2026-05-22T09:01:00+00:00",
                    "started_at": "2026-05-22T09:00:10+00:00",
                    "finished_at": "2026-05-22T09:01:00+00:00",
                }
            ]
        )

        with patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)):
            jobs = database_service.list_document_bulk_jobs("demo-mandant", limit=100)

        statement, params = cursor.statements[0]
        self.assertIn("where tenant_id = %s", statement)
        self.assertIn("order by created_at desc, id desc", statement)
        self.assertEqual(params, ("demo-mandant", 50))
        self.assertEqual(jobs[0]["id"], str(job_id))
        self.assertEqual(jobs[0]["requested_total"], 2)
        self.assertNotIn("items", jobs[0])

    def test_bulk_job_runner_records_item_failure_and_continues(self):
        job_id = uuid4()
        first_document_id = uuid4()
        second_document_id = uuid4()
        job = {
            "id": str(job_id),
            "tenant_id": "demo-mandant",
            "action": "extract",
            "status": "running",
            "items": [
                {"document_id": str(first_document_id), "status": "queued"},
                {"document_id": str(second_document_id), "status": "queued"},
            ],
        }

        with (
            patch.object(bulk_job_service, "mark_document_bulk_job_running", return_value=job),
            patch.object(bulk_job_service, "claim_document_for_bulk_job", return_value={"id": str(first_document_id)}),
            patch.object(bulk_job_service, "release_document_bulk_claim") as release_claim,
            patch.object(
                bulk_job_service,
                "run_mock_extraction",
                side_effect=[None, HTTPException(status_code=409, detail="blockiert")],
            ),
            patch.object(bulk_job_service, "mark_document_bulk_job_item") as mark_item,
            patch.object(bulk_job_service, "finish_document_bulk_job") as finish_job,
        ):
            bulk_job_service.run_document_bulk_job(job_id, actor="admin@example.com")

        mark_item.assert_has_calls(
            [
                call(job_id, first_document_id, "running"),
                call(job_id, first_document_id, "succeeded"),
                call(job_id, second_document_id, "running"),
                call(job_id, second_document_id, "failed", "blockiert"),
            ]
        )
        finish_job.assert_called_once_with(job_id, "completed")
        self.assertEqual(release_claim.call_count, 2)

    def test_bulk_job_runner_skips_document_that_cannot_be_claimed(self):
        job_id = uuid4()
        document_id = uuid4()
        job = {
            "id": str(job_id),
            "tenant_id": "demo-mandant",
            "action": "extract",
            "status": "running",
            "items": [{"document_id": str(document_id), "status": "queued"}],
        }

        with (
            patch.object(bulk_job_service, "mark_document_bulk_job_running", return_value=job),
            patch.object(bulk_job_service, "claim_document_for_bulk_job", return_value=None),
            patch.object(bulk_job_service, "run_mock_extraction") as run_extraction,
            patch.object(bulk_job_service, "mark_document_bulk_job_item") as mark_item,
            patch.object(bulk_job_service, "finish_document_bulk_job") as finish_job,
        ):
            bulk_job_service.run_document_bulk_job(job_id, actor="admin@example.com")

        mark_item.assert_has_calls(
            [
                call(job_id, document_id, "running"),
                call(job_id, document_id, "skipped", "Beleg ist nicht mehr im passenden Status."),
            ]
        )
        run_extraction.assert_not_called()
        finish_job.assert_called_once_with(job_id, "completed")

    def test_assignment_unit_update_can_edit_code_and_clear_project_number(self):
        assignment_id = uuid4()
        row = {
            "id": assignment_id,
            "tenant_id": "demo-mandant",
            "code": "Wewe20",
            "label": "Weseler Weg 20",
            "kind": "construction_project",
            "project_number": None,
            "revenue_relevant": True,
            "aliases": [],
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }
        cursor = RecordingCursor(fetchone_result=row)

        with patch.object(database_service, "_connect", return_value=RecordingConnection(cursor)):
            assignment = database_service.update_assignment_unit(
                assignment_id=assignment_id,
                code="Wewe20",
                label="Weseler Weg 20",
                kind="construction_project",
                project_number="",
                revenue_relevant=True,
                aliases=["Weseler Weg 20", ""],
                is_active=True,
            )

        params = cursor.statements[0][1]
        self.assertEqual(params[0], "Wewe20")
        self.assertIsNone(params[3])
        self.assertIsNone(assignment["project_number"])

    def test_review_validation_blocks_missing_accounting_rule_and_payment_choice(self):
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "RE1574023.pdf",
            "extraction": {
                "supplier_name": "Lüchau Baustoffe GmbH",
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
            details = validate_document_review_details(document)

        self.assertIn(
            "Zeile 1: Kontierungsregel fehlt für Kostenart Material / Lieferant Lüchau Baustoffe GmbH. "
            "Bitte unter Stammdaten -> Kontierungsregeln anlegen.",
            errors,
        )
        self.assertIn("Zahlungsentscheidung fehlt: Skonto/ohne Abzug/Gutschrift-Verrechnung muss gewählt werden.", errors)
        missing_rule = next(detail for detail in details if detail["code"] == "missing_accounting_rule")
        self.assertEqual(missing_rule["supplier_name"], "Lüchau Baustoffe GmbH")
        self.assertEqual(missing_rule["cost_category"], "material")
        self.assertEqual(missing_rule["cost_category_label"], "Material")
        self.assertEqual(missing_rule["suggested_name"], "Material Lüchau Baustoffe GmbH")

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

    def test_review_validation_details_link_existing_accounting_rule_errors(self):
        rule_id = str(uuid4())
        document = {
            "id": str(uuid4()),
            "tenant_id": "demo-mandant",
            "original_filename": "rechnung.pdf",
            "extraction": {
                "supplier_name": "Theo Foerch GmbH & Co. KG",
                "invoice_number": "3161691971",
                "invoice_date": "2026-05-21",
                "net_amount": "84.03",
                "tax_amount": "15.97",
                "gross_amount": "100.00",
                "currency": "EUR",
                "confidence": Decimal("0.90"),
                "warnings": [],
                "raw_result": {"document_type": "incoming_invoice"},
            },
            "booking_suggestions": [
                {
                    "line_no": 1,
                    "booking_type": "incoming_invoice",
                    "cost_category": "material",
                    "description": "Zargenschaum",
                    "net_amount": "84.03",
                    "tax_amount": "15.97",
                    "gross_amount": "100.00",
                    "currency": "EUR",
                }
            ],
            "payment_decision": {"payment_type": "cash_discount", "amount": "97.00"},
        }

        incomplete_rule = {
            "id": rule_id,
            "name": "Material Foerch",
            "supplier_match_text": "Foerch",
            "cost_category": "material",
            "debit_account": "",
            "credit_account": "70000",
            "tax_key": "9",
            "tax_rate": "19.00",
            "discount_account": "",
            "is_active": True,
        }
        with patch.object(database_service, "list_accounting_rules", return_value=[incomplete_rule]):
            details = validate_document_review_details(document)

        incomplete = next(detail for detail in details if detail["code"] == "incomplete_accounting_rule")
        self.assertEqual(incomplete["accounting_rule_id"], rule_id)
        self.assertEqual(incomplete["accounting_rule_name"], "Material Foerch")

        no_discount_rule = {**incomplete_rule, "debit_account": "3400", "discount_account": ""}
        with patch.object(database_service, "list_accounting_rules", return_value=[no_discount_rule]):
            details = validate_document_review_details(document)

        discount = next(detail for detail in details if detail["code"] == "missing_discount_account")
        self.assertEqual(discount["accounting_rule_id"], rule_id)
        self.assertEqual(discount["accounting_rule_name"], "Material Foerch")

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
                "warnings": ["Splittung prüfen."],
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

        self.assertIn("Offene Extraktionswarnungen müssen vor finaler Freigabe geklärt werden.", errors)
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
                        "Summenprüfung fehlgeschlagen: Netto plus USt passt nicht zu Brutto."
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
