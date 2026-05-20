from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from re import MULTILINE, finditer, search, sub
from xml.etree import ElementTree
from uuid import UUID

from fastapi import HTTPException
from pypdf import PdfReader

from app.config import get_settings
from app.services.database import (
    find_assignment_unit_by_text,
    find_supplier_rule,
    get_assignment_unit_by_code,
    ensure_tenant_profile,
    get_document,
    insert_audit_event,
    save_document_extraction,
)


def run_mock_extraction(document_id: UUID) -> dict:
    document = get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.extraction_started",
        document_id=document_id,
    )

    extraction = _build_extraction_result(document)
    return save_document_extraction(
        document_id=document_id,
        tenant_id=document["tenant_id"],
        extraction=extraction,
    )


def _build_extraction_result(document: dict) -> dict:
    if document["content_type"] != "application/pdf":
        return _build_mock_result(document)

    structured = _build_embedded_xml_result(document)
    if structured:
        return structured

    return _build_pdf_text_result(document)


def _build_embedded_xml_result(document: dict) -> dict | None:
    if document["content_type"] != "application/pdf":
        return None

    xml_attachment = _find_embedded_invoice_xml(document["storage_path"])
    if not xml_attachment:
        return None

    attachment_name, xml_content = xml_attachment
    text = _extract_pdf_text(document["storage_path"])
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return None
    if not root.tag.endswith("CrossIndustryInvoice"):
        return None
    ns = {
        "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
        "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
        "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    }

    invoice_number = _xml_text(root, ".//rsm:ExchangedDocument/ram:ID", ns)
    customer_number = _xml_text(root, ".//ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:ID", ns)
    invoice_date = _cii_date(
        _xml_text(root, ".//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString", ns)
    )
    supplier_name = _normalize_supplier_name(
        _xml_text(root, ".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:Name", ns)
    )
    product_name = _clean_product_name(
        _find_first_position_product_name(text)
        or _xml_text(root, ".//ram:IncludedSupplyChainTradeLineItem[1]/ram:SpecifiedTradeProduct/ram:Name", ns)
    )
    payment_description = _xml_text(
        root,
        ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradePaymentTerms/ram:Description",
        ns,
    )
    discount_due_date = _cii_date(
        _xml_text(
            root,
            ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString",
            ns,
        )
    )
    net_amount = _xml_decimal(
        root,
        ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:LineTotalAmount",
        ns,
    )
    tax_amount = _xml_decimal(
        root,
        ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:TaxTotalAmount",
        ns,
    )
    gross_amount = _xml_decimal(
        root,
        ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:GrandTotalAmount",
        ns,
    )
    due_payable_amount = _xml_decimal(
        root,
        ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:DuePayableAmount",
        ns,
    )
    discount_base = _description_decimal(payment_description, "BASISBETRAG")
    discount_percent = _description_decimal(payment_description, "PROZENT")
    visible_discount = _find_visible_discount_terms(text)
    visible_discount_base = visible_discount.get("discount_base")
    xml_discount_base = discount_base
    if visible_discount_base is not None:
        discount_base = visible_discount_base
    if visible_discount.get("discount_percent") is not None:
        discount_percent = visible_discount["discount_percent"]
    discount_amount = None
    if discount_base is not None and discount_percent is not None:
        discount_amount = (discount_base * discount_percent / Decimal("100")).quantize(Decimal("0.01"))
    is_credit_note = gross_amount is not None and gross_amount < 0
    if is_credit_note and discount_amount is not None:
        discount_amount = -discount_amount

    # Some supplier XML files do not carry construction-site delivery text,
    # so the project assignment is enriched from the human-readable PDF.
    delivery_address = _xml_delivery_address(root, ns) or _find_delivery_address(text)
    due_date = (
        visible_discount.get("due_date")
        or _find_date(text, r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+ohne Abzug")
        or _find_date(text, r"ohne Abzug\s*(\d{2}\.\d{2}\.\d{4})")
    )
    visible_discount_due_date = _find_date(text, r"verrechnen bis zum\s+(\d{2}\.\d{2}\.\d{2})")
    if visible_discount_due_date or visible_discount.get("discount_due_date"):
        discount_due_date = visible_discount_due_date or visible_discount.get("discount_due_date")
    supplier_rule = find_supplier_rule(document["tenant_id"], supplier_name, customer_number, text[:4000])
    if supplier_rule:
        supplier_name = supplier_rule["supplier_name"]
        customer_number = supplier_rule["customer_number"] or customer_number
    assignment = _assignment_unit(document["tenant_id"], delivery_address, text, supplier_rule)
    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    assignment_type = _assignment_type(delivery_address, assignment)
    cost_category = supplier_rule["default_cost_category"] if supplier_rule else None
    cost_category = cost_category or _cost_category(supplier_name, product_name, text, assignment_type)
    normalized_filename = _normalized_invoice_filename(
        invoice_number=invoice_number,
        assignment=assignment,
        assignment_type=assignment_type,
        tenant_profile=tenant_profile,
        supplier_name=supplier_name or _supplier_from_filename(Path(document["original_filename"]).stem),
        product_name=_filename_product_name(product_name or "Eingangsrechnung"),
        invoice_date=invoice_date,
    )

    missing = [
        label
        for label, value in {
            "Rechnungsnummer": invoice_number,
            "Datum": invoice_date,
            "Lieferant": supplier_name,
            "Netto": net_amount,
            "MwSt": tax_amount,
            "Gesamtbetrag": gross_amount,
        }.items()
        if not value
    ]
    warnings = []
    if delivery_address and not assignment:
        warnings.append("Nicht sicher erkannt: Zuordnung aus Mandanten-Stammdaten.")
    if visible_discount_base is not None and xml_discount_base is not None and visible_discount_base != xml_discount_base:
        warnings.append(
            f"Skonto-Basis aus sichtbarem Beleg ({visible_discount_base}) weicht von XML ({xml_discount_base}) ab."
        )
    if missing:
        warnings.append(f"Nicht sicher erkannt: {', '.join(missing)}.")

    return {
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": customer_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "discount_due_date": discount_due_date,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": delivery_address,
        "assignment_code": assignment["code"] if assignment else None,
        "assignment_label": assignment["label"] if assignment else None,
        "assignment_kind": assignment["kind"] if assignment else None,
        "assignment_revenue_relevant": assignment["revenue_relevant"] if assignment else None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": _legacy_project_code(assignment),
        "project_number": None,
        "project_name": assignment["label"] if _legacy_project_code(assignment) else None,
        "assignment_type": assignment_type,
        "cost_category": cost_category,
        "product_name": product_name,
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "gross_amount": gross_amount,
        "due_payable_amount": due_payable_amount,
        "discounted_payable_amount": visible_discount.get("discounted_payable_amount"),
        "is_credit_note": is_credit_note,
        "document_type": "credit_note" if is_credit_note else "incoming_invoice",
        "discount_base": discount_base,
        "xml_discount_base": xml_discount_base,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "currency": "EUR",
        "confidence": Decimal("1.00") if not missing else Decimal("0.90"),
        "warnings": warnings,
        "normalized_filename": normalized_filename,
        "source": "embedded_xml",
        "structured_attachment": attachment_name,
    }


def _build_pdf_text_result(document: dict) -> dict:
    text = _extract_pdf_text(document["storage_path"])
    if len(text.strip()) < 80:
        result = _build_mock_result(document)
        result["warnings"] = [
            "PDF-Text konnte nicht ausreichend gelesen werden. OCR wird fuer diesen Belegtyp benoetigt.",
        ]
        return result

    invoice_number = _find_text(text, r"Rechnungs-Nr\.:\s*(\d+)") or _find_text(
        text,
        r"Nr\.\s*\(S\)\s*:\s*([0-9-]+)",
    ) or _find_text(
        text,
        r"Belegnummer:\s*([A-Z]{1,5}\d+)",
    )
    customer_number = _find_text(text, r"Kunden-Nr\.:\s*(\d+)") or _find_text(
        text,
        r"Kundennummer\s*:\s*([0-9/.-]+)",
    ) or _find_text(
        text,
        r"([0-9/.-]+)\s*Kundennummer:",
    ) or _find_text(
        text,
        r"Kundennummer:\s*\n\s*[A-Z]{1,5}\d+\s*\n\s*\d{2}\.\d{2}\.\d{4}\s*\n\s*([0-9/.-]+)",
    )
    invoice_date = _find_date(text, r"Datum:\s*(\d{2}\.\d{2}\.\d{4})") or _find_date(
        text,
        r"Datum\s*-\s*Zeit\s*:\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Belegdatum:\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Belegdatum:\s*\n\s*Kundennummer:\s*\n\s*[A-Z]{1,5}\d+\s*\n\s*(\d{2}\.\d{2}\.\d{4})",
    )
    due_date = (
        _find_date(text, r"ohne Abzug\s*(\d{2}\.\d{2}\.\d{4})")
        or _find_date(text, r"zahlbar bis spätestens\s+(\d{2}\.\d{2}\.\d{2})")
        or _find_date(text, r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+abzgl\.")
    )
    allocation_lines = _find_allocation_lines(document["tenant_id"], text)
    visible_discount = _find_visible_discount_terms(text)
    discount_percent = _find_discount_percent(text) or visible_discount.get("discount_percent")
    discount_due_date = (
        _find_date(text, r"(\d{2}\.\d{2}\.\d{4})\s+3,00%\s+Skonto")
        or _discount_due_date_from_days(invoice_date, _find_discount_days(text))
        or visible_discount.get("discount_due_date")
    )
    totals = _find_invoice_totals(text)
    discount_base = totals.get("discount_base") or visible_discount.get("discount_base")
    net_amount = totals.get("net_amount")
    tax_amount = totals.get("tax_amount")
    gross_amount = totals.get("gross_amount")
    discount_base = discount_base or gross_amount
    discount_amount = _find_money(text, r"Skonto\s*=\s*([0-9.]+,\d{2})") or visible_discount.get(
        "discount_amount"
    )
    if discount_amount is None and discount_base is not None and discount_percent is not None:
        discount_amount = (discount_base * discount_percent / Decimal("100")).quantize(Decimal("0.01"))
    delivery_addresses = _find_delivery_addresses(text)
    delivery_address = delivery_addresses[0] if delivery_addresses else _find_delivery_address(text)
    supplier_name = _supplier_name(document, text)
    supplier_rule = find_supplier_rule(document["tenant_id"], supplier_name, customer_number, text[:4000])
    if supplier_rule:
        supplier_name = supplier_rule["supplier_name"]
        customer_number = supplier_rule["customer_number"] or customer_number
    assignment = _assignment_unit(document["tenant_id"], delivery_address, text, supplier_rule)
    if not assignment and delivery_addresses:
        assignment = _resolve_assignment_for_delivery_addresses(document["tenant_id"], delivery_addresses)
    product_name = _product_name(text)
    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    allocation_lines_resolved = bool(allocation_lines) and all(
        allocation.get("assignment_code") for allocation in allocation_lines
    )
    assignment_type = "assignment_split" if len(allocation_lines) > 1 else _assignment_type(delivery_address, assignment)
    cost_category = supplier_rule["default_cost_category"] if supplier_rule else None
    cost_category = cost_category or _cost_category(supplier_name, product_name, text, assignment_type)
    normalized_filename = _normalized_invoice_filename(
        invoice_number=invoice_number,
        assignment=assignment,
        assignment_type=assignment_type,
        tenant_profile=tenant_profile,
        supplier_name=supplier_name,
        product_name=_filename_product_name(product_name),
        invoice_date=invoice_date,
    )

    missing = [
        label
        for label, value in {
            "Rechnungsnummer": invoice_number,
            "Datum": invoice_date,
            "Netto": net_amount,
            "MwSt": tax_amount,
            "Gesamtbetrag": gross_amount,
        }.items()
        if not value
    ]
    warnings = []
    if len(delivery_addresses) > 1:
        warnings.append(
            "Mehrere Lieferadressen/Zuordnungen erkannt: bitte Zuordnung oder Splittung pruefen."
        )
    if delivery_address and not assignment and not allocation_lines_resolved:
        warnings.append("Nicht sicher erkannt: Zuordnung aus Mandanten-Stammdaten.")
    if missing:
        warnings.append(f"Nicht sicher erkannt: {', '.join(missing)}.")

    return {
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": customer_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "discount_due_date": discount_due_date,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": delivery_address,
        "delivery_addresses": delivery_addresses,
        "allocation_lines": allocation_lines,
        "assignment_code": assignment["code"] if assignment else None,
        "assignment_label": assignment["label"] if assignment else None,
        "assignment_kind": assignment["kind"] if assignment else None,
        "assignment_revenue_relevant": assignment["revenue_relevant"] if assignment else None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": _legacy_project_code(assignment),
        "project_number": None,
        "project_name": assignment["label"] if _legacy_project_code(assignment) else None,
        "assignment_type": assignment_type,
        "cost_category": cost_category,
        "product_name": product_name,
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "gross_amount": gross_amount,
        "discount_base": discount_base,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "discounted_payable_amount": visible_discount.get("discounted_payable_amount"),
        "document_type": "incoming_invoice",
        "currency": "EUR",
        "confidence": Decimal("0.88") if not missing else Decimal("0.72"),
        "warnings": warnings,
        "normalized_filename": normalized_filename,
        "source": "pdf_text_rules",
    }


def _build_mock_result(document: dict) -> dict:
    stem = Path(document["original_filename"]).stem
    supplier_name = _supplier_from_filename(stem)
    created_at = datetime.fromisoformat(document["created_at"])
    gross_amount = _mock_gross_amount(document["size_bytes"])
    net_amount = (gross_amount / Decimal("1.19")).quantize(Decimal("0.01"))
    tax_amount = (gross_amount - net_amount).quantize(Decimal("0.01"))

    warnings = [
        "Mock-Extraktion: Werte muessen fachlich geprueft werden.",
    ]

    return {
        "supplier_name": supplier_name,
        "invoice_number": f"MOCK-{document['sha256'][:8].upper()}",
        "invoice_date": created_at.astimezone(UTC).date().isoformat(),
        "service_period": f"{created_at:%Y-%m}",
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "gross_amount": gross_amount,
        "currency": "EUR",
        "confidence": Decimal("0.42"),
        "warnings": warnings,
        "normalized_filename": None,
        "source": "mock",
    }


def _extract_pdf_text(storage_path: str) -> str:
    reader = _read_pdf(storage_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _find_embedded_invoice_xml(storage_path: str) -> tuple[str, bytes] | None:
    reader = _read_pdf(storage_path)
    for name, payloads in reader.attachments.items():
        if not name.lower().endswith(".xml"):
            continue
        payload = payloads[0] if isinstance(payloads, list) else payloads
        lower_payload = payload[:2000].lower()
        if b"crossindustryinvoice" in lower_payload or b"invoice" in lower_payload:
            return name, payload
    return None


def _read_pdf(storage_path: str) -> PdfReader:
    pdf_path = get_settings().storage_root / storage_path
    return PdfReader(BytesIO(pdf_path.read_bytes()))


def _xml_text(root: ElementTree.Element, path: str, ns: dict[str, str]) -> str | None:
    node = root.find(path, ns)
    if node is None or node.text is None:
        return None
    value = sub(r"\s+", " ", node.text).strip()
    return value or None


def _xml_decimal(root: ElementTree.Element, path: str, ns: dict[str, str]) -> Decimal | None:
    value = _xml_text(root, path, ns)
    return Decimal(value).quantize(Decimal("0.01")) if value else None


def _cii_date(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) == 6 and value.isdigit():
        return f"20{value[4:6]}-{value[2:4]}-{value[:2]}"
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def _description_decimal(description: str | None, key: str) -> Decimal | None:
    if not description:
        return None
    match = search(rf"{key}=([0-9.]+(?:,\d+)?|\d+(?:\.\d+)?)", description)
    if not match:
        return None
    value = match.group(1)
    if "," in value:
        return _money_to_decimal(value)
    return Decimal(value).quantize(Decimal("0.01"))


def _xml_delivery_address(root: ElementTree.Element, ns: dict[str, str]) -> str | None:
    name = _xml_text(root, ".//ram:ApplicableHeaderTradeDelivery/ram:UltimateShipToTradeParty/ram:Name", ns)
    postcode = _xml_text(
        root,
        ".//ram:ApplicableHeaderTradeDelivery/ram:UltimateShipToTradeParty/ram:PostalTradeAddress/ram:PostcodeCode",
        ns,
    )
    city = _xml_text(
        root,
        ".//ram:ApplicableHeaderTradeDelivery/ram:UltimateShipToTradeParty/ram:PostalTradeAddress/ram:CityName",
        ns,
    )
    if name and postcode and city:
        return f"{name.strip()}, {postcode} {city}"
    return None


def _find_visible_discount_base(text: str) -> Decimal | None:
    return _find_money(
        text,
        r"(?:davon\s+skontofähig|Skontofähiger\s+Betrag|skontierfähiger\s+Betrag\s+EUR)\s*:?\s*([0-9.]+,\d{2})",
    )


def _find_visible_discount_terms(text: str) -> dict[str, Decimal | str | None]:
    discount_due_date = _find_date(
        text,
        r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+([0-9]+,[0-9]{2})%\s+Skt=",
    )
    percent_text = _find_text(
        text,
        r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+([0-9]+,[0-9]{2})%\s+Skt=",
    )
    due_date = _find_date(text, r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+ohne Abzug")
    discounted_payable_amount = _find_money(
        text,
        r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+[0-9]+,[0-9]{2}%\s+Skt=\s*([0-9.]+,\d{2})",
    ) or _find_money(
        text,
        r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+abzgl\.\s+[0-9]+(?:,\d{1,2})?\s*%\s+Skonto\s+EUR\s+[0-9.]+,\d{2}\s+=\s+EUR\s+([0-9.]+,\d{2})",
    )
    if discount_due_date is None:
        discount_due_date = _find_date(text, r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+abzgl\.")
    if percent_text is None:
        percent_text = _find_text(text, r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+abzgl\.\s+([0-9]+(?:,\d{1,2})?)\s*%\s+Skonto")
    discount_amount = _find_money(
        text,
        r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+abzgl\.\s+[0-9]+(?:,\d{1,2})?\s*%\s+Skonto\s+EUR\s+([0-9.]+,\d{2})",
    )
    return {
        "discount_due_date": discount_due_date,
        "due_date": due_date,
        "discount_percent": _money_to_decimal(percent_text) if percent_text else None,
        "discount_base": _find_visible_discount_base(text),
        "discount_amount": discount_amount,
        "discounted_payable_amount": discounted_payable_amount,
    }


def _find_text(text: str, pattern: str) -> str | None:
    match = search(pattern, text, MULTILINE)
    return match.group(1).strip() if match else None


def _find_date(text: str, pattern: str) -> str | None:
    value = _find_text(text, pattern)
    if not value:
        return None
    day, month, year = value.split(".")
    if len(year) == 2:
        year = f"20{year}"
    return f"{year}-{month}-{day}"


def _find_money_after_label(text: str, label: str) -> Decimal | None:
    pattern = rf"{label}[^\n]*?([0-9.]+,\d{{2}})"
    return _find_money(text, pattern)


def _find_invoice_totals(text: str) -> dict[str, Decimal | None]:
    luechau_total = search(
        r"\b\d{1,2}%\s+MwSt\.:\s+([0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+([0-9.]+,\d{2})",
        text,
    )
    if luechau_total:
        return {
            "discount_base": _find_visible_discount_base(text),
            "net_amount": _money_to_decimal(luechau_total.group(1)),
            "tax_amount": _money_to_decimal(luechau_total.group(2)),
            "gross_amount": _money_to_decimal(luechau_total.group(3)),
        }
    match = search(
        r"skontofähiger Betrag\s+Netto\s+MwSt-%\s+MwSt\s+Endbetrag EUR\s*\n\s*"
        r"([0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+([0-9.]+,\d{2})",
        text,
    )
    if not match:
        return {
            "discount_base": _find_money_after_label(text, "skontofähiger Betrag"),
            "net_amount": _find_money_after_label(text, "Netto")
            or _find_money_after_label(text, "Steuerpflichtiger Betrag"),
            "tax_amount": _find_money_after_label(text, "MwSt"),
            "gross_amount": _find_money_after_label(text, "Endbetrag EUR")
            or _find_money_after_label(text, "Rechnungsbetrag"),
        }
    return {
        "discount_base": _money_to_decimal(match.group(1)),
        "net_amount": _money_to_decimal(match.group(2)),
        "tax_amount": _money_to_decimal(match.group(4)),
        "gross_amount": _money_to_decimal(match.group(5)),
    }


def _find_money(text: str, pattern: str) -> Decimal | None:
    value = _find_text(text, pattern)
    if not value:
        return None
    return _money_to_decimal(value)


def _find_discount_percent(text: str) -> Decimal | None:
    percent = _find_text(text, r"\b\d+\s+Tage\s+([0-9]+(?:,\d{1,2})?)%\s+Skonto") or _find_text(
        text,
        r"abzgl\.\s+([0-9]+(?:,\d{1,2})?)\s*%\s+Skonto",
    )
    if not percent:
        return None
    return _money_to_decimal(f"{percent},00" if "," not in percent else percent)


def _find_discount_days(text: str) -> int | None:
    value = _find_text(text, r"\b(\d+)\s+Tage\s+[0-9]+(?:,\d{1,2})?%\s+Skonto")
    return int(value) if value else None


def _discount_due_date_from_days(invoice_date: str | None, days: int | None) -> str | None:
    if not invoice_date or days is None:
        return None
    return (datetime.fromisoformat(invoice_date).date() + timedelta(days=days)).isoformat()


def _money_to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", ".")).quantize(Decimal("0.01"))


def _find_delivery_address(text: str) -> str | None:
    match = search(r"Lieferanschrift:\s*(.+?)\s*\n\s*(\d{5}\s+[^\n]+)", text)
    if not match:
        addresses = _find_delivery_addresses(text)
        return addresses[0] if addresses else None
    return f"{match.group(1).strip()}, {match.group(2).strip()}"


def _find_delivery_addresses(text: str) -> list[str]:
    addresses = []
    for match in finditer(
        r"An:\s*(.+?),\s*([^\n]*?\d+[^\n]*)\s*\n\s*(\d{5}\s+[^\n]+)",
        text,
    ):
        recipient, street, city = (part.strip() for part in match.groups())
        addresses.append(f"{recipient}, {street}, {city}")
    return list(dict.fromkeys(addresses))


def _find_allocation_lines(tenant_id: str, text: str) -> list[dict[str, str | None]]:
    normalized_text = sub(r"\s+", " ", text)
    allocations = []
    for match in finditer(
        r"Zwischensumme\s+f[üu]r\s+(.+?),\s*(.+?):\s+([0-9.]+,\d{2})\s+EUR",
        normalized_text,
    ):
        recipient, address, amount_text = (part.strip() for part in match.groups())
        full_address = f"{recipient}, {address}"
        assignment = find_assignment_unit_by_text(tenant_id, full_address)
        allocations.append(
            {
                "recipient": recipient,
                "address": address,
                "delivery_address": full_address,
                "assignment_code": assignment["code"] if assignment else None,
                "assignment_label": assignment["label"] if assignment else None,
                "assignment_kind": assignment["kind"] if assignment else None,
                "project_number": None,
                "project_code": _legacy_project_code(assignment),
                "project_name": assignment["label"] if _legacy_project_code(assignment) else None,
                "amount": str(_money_to_decimal(amount_text)),
                "currency": "EUR",
            }
        )
    return allocations


def _resolve_assignment_for_delivery_addresses(tenant_id: str, delivery_addresses: list[str]) -> dict | None:
    assignments = [find_assignment_unit_by_text(tenant_id, address) for address in delivery_addresses]
    assignment_codes = {assignment["code"] for assignment in assignments if assignment}
    if len(delivery_addresses) == 1 and assignments[0]:
        return assignments[0]
    if len(assignment_codes) == 1 and len(assignments) == len([assignment for assignment in assignments if assignment]):
        return next(assignment for assignment in assignments if assignment)
    return None


def _supplier_name(document: dict, text: str) -> str:
    original = document["original_filename"].lower()
    if "lüchau baustoffe gmbh" in text.lower():
        return "Lüchau Baustoffe GmbH"
    if "rechnungar" in original and "0113042/504" in text:
        return "Georg Klindworth oHG"
    if "kreditrechnung" in original and "fermacell" in text.lower():
        return "Holz Junge GmbH"
    return _supplier_from_filename(Path(document["original_filename"]).stem)


def _normalize_supplier_name(value: str | None) -> str | None:
    if not value:
        return None
    if value == "Holz-Junge GmbH":
        return "Holz Junge GmbH"
    value = sub(r"\s+Lager\s+.+$", "", value).strip()
    return value


def _assignment_unit(
    tenant_id: str,
    delivery_address: str | None,
    text: str,
    supplier_rule: dict | None,
) -> dict | None:
    if supplier_rule and supplier_rule.get("default_assignment_code"):
        assignment = get_assignment_unit_by_code(tenant_id, supplier_rule["default_assignment_code"])
        if assignment and assignment["is_active"]:
            return assignment
    return find_assignment_unit_by_text(tenant_id, delivery_address or text[:4000])


def _legacy_project_code(assignment: dict | None) -> str | None:
    if assignment and assignment["kind"] == "construction_project":
        return assignment["code"]
    return None


def _assignment_type(delivery_address: str | None, assignment: dict | None) -> str:
    if assignment:
        return "assigned"
    if delivery_address:
        return "assignment_unresolved"
    return "general_cost"


def _cost_category(
    supplier_name: str | None,
    product_name: str | None,
    text: str,
    assignment_type: str,
) -> str:
    haystack = " ".join([supplier_name or "", product_name or "", text[:3000]]).lower()
    if any(term in haystack for term in ["maler", "elektro", "sanitÃ¤r", "subunternehmer", "fremdleistung"]):
        return "subcontractor"
    if any(term in haystack for term in ["hobotec", "fermacell", "schalung", "gipsfaserplatte", "artikel", "material"]):
        return "material"
    if assignment_type in {"assigned", "assignment_split", "assignment_unresolved", "project", "project_split", "project_unresolved"}:
        return "material"
    if any(term in haystack for term in ["tank", "diesel", "benzin", "kraftstoff", "shell", "aral"]):
        return "fuel_vehicle"
    if any(term in haystack for term in ["software", "lizenz", "microsoft", "adobe", "cloud", "hosting", "saas"]):
        return "software_subscription"
    if any(term in haystack for term in ["kamera", "camera", "ueberwachung", "überwachung", "security"]):
        return "security_subscription"
    return "general_overhead"


def _clean_product_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = sub(r"\s+", " ", value.replace("^", "")).strip()
    if cleaned.startswith("FERMACELL 10mm Gipsfaserplatte"):
        return "FERMACELL 10mm Gipsfaserplatte"
    return cleaned[:80]


def _filename_product_name(value: str) -> str:
    cleaned = _clean_product_name(value) or "Eingangsrechnung"
    return cleaned.split(",", 1)[0].strip() or cleaned


def _find_first_position_product_name(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()]
    item_line_pattern = r"^[A-Z0-9][A-Z0-9./ -]{3,}\s+\d+,\d{3}\s+(?:ST|PA|M|KG|LTR|ROL|PKT)\b"
    for index, line in enumerate(lines):
        if not search(item_line_pattern, line):
            continue
        for candidate in lines[index + 1 : index + 5]:
            if not candidate or search(item_line_pattern, candidate):
                continue
            if search(r"[A-Za-zÄÖÜäöüß]", candidate):
                return candidate
    return None


def _product_name(text: str) -> str:
    if "PE-Folie 200 my" in text:
        return "PE-Folie 200 my / Baustoffe"
    if "FERMACELL" in text and "10mm Gipsfaserplatte" in text:
        return "FERMACELL 10mm Gipsfaserplatte"
    match = search(r"Pos\. 1:\s*\n(.+?)\n(.+?)(?:\s{2,}|\n)", text)
    if not match:
        return "Eingangsrechnung"
    return " ".join(part.strip() for part in match.groups())[:80]


def _normalized_invoice_filename(
    invoice_number: str | None,
    assignment: dict | None,
    assignment_type: str,
    tenant_profile: dict,
    supplier_name: str,
    product_name: str,
    invoice_date: str | None,
) -> str:
    parts = [
        f"ERg {invoice_number or 'ohne Nummer'}",
        _filename_assignment_label(assignment, assignment_type, tenant_profile),
        supplier_name,
        product_name,
        invoice_date or "ohne Datum",
    ]
    return ", ".join(parts) + ".pdf"


def _filename_assignment_label(assignment: dict | None, assignment_type: str, tenant_profile: dict) -> str:
    if assignment:
        prefix = tenant_profile.get("assignment_code_prefix")
        if prefix:
            return f"{prefix} {assignment['code']}"
        return f"{tenant_profile['assignment_label_singular']} {assignment['code']}"
    if assignment_type == "assignment_split":
        return f"{tenant_profile['assignment_label_plural']} aufgeteilt"
    if assignment_type == "assignment_unresolved":
        return f"{tenant_profile['assignment_label_singular']} ungeklaert"
    return "Allgemeine Kosten"


def _supplier_from_filename(filename_stem: str) -> str:
    cleaned = sub(r"[_-]+", " ", filename_stem).strip()
    if not cleaned:
        return "Unbekannter Lieferant"
    return cleaned[:80]


def _mock_gross_amount(size_bytes: int) -> Decimal:
    cents = max(100, size_bytes % 50000)
    return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))
