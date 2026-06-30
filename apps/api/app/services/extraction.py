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
from app.services.cost_categories import VALID_COST_CATEGORIES, split_cost_category_values
from app.services.database import (
    find_assignment_unit_match_by_text,
    find_assignment_unit_by_text,
    find_supplier_rule,
    get_assignment_unit_by_code,
    ensure_tenant_profile,
    get_document,
    insert_audit_event,
    save_document_extraction,
)

EXTRACTABLE_DOCUMENT_STATUSES = {"review_pending"}
REEXTRACTABLE_DOCUMENT_STATUSES = {"extracted", "review_ready"}

EXTRACTION_CAPABILITIES = [
    {
        "supplier_name": "Holz Junge GmbH",
        "status": "gut",
        "recognition": "Dateiname Kreditrechnung, Holz-Junge-Text, Kundennummer",
        "coverage": "Rechnungsdaten, Skonto, Bauvorhaben-Hinweise, Artikelkurztext",
    },
    {
        "supplier_name": "HaHo Holz",
        "status": "gut",
        "recognition": "Kundennr/Reisender/Btr NL im Beleg",
        "coverage": "Rechnungsdaten und Beträge, Projekthinweise über Text",
    },
    {
        "supplier_name": "Lüchau Baustoffe GmbH",
        "status": "gut",
        "recognition": "Lieferantenname, Kunden-/Projektbezug, PDF-Text",
        "coverage": "Rechnungsdaten, Skonto, Projektnummer/Projektname über Stammdaten",
    },
    {
        "supplier_name": "Theo Foerch GmbH & Co. KG",
        "status": "gut",
        "recognition": "Förch/Foerch im Dateinamen oder Belegtext",
        "coverage": "Rechnungsdaten, Kundennummer, Kundenreferenz, Skonto-Tabelle",
    },
    {
        "supplier_name": "Arens & Stitz KG",
        "status": "gut",
        "recognition": "FRHA05 und GC-Gruppe-Merkmale",
        "coverage": "Mehrseitige Skontodaten, Rechnungsdaten, Artikelkurztext",
    },
    {
        "supplier_name": "Rolf Dammers oHG",
        "status": "gut",
        "recognition": "Dammers/Alles fürs Dach, Lager-/Kundennummer-Merkmale",
        "coverage": "Rechnungsdaten, Kundennummer, Bestelldaten als Projekthinweis",
    },
    {
        "supplier_name": "Georg Klindworth oHG",
        "status": "gut",
        "recognition": "RechnungAR-Dateiname und Kundennummer 0113042/504",
        "coverage": "Rechnungsdaten, Skonto, Material-Kostenart",
    },
    {
        "supplier_name": "Pietsch Hamburg-Ost Damaschke GmbH & Co. KG",
        "status": "gut",
        "recognition": "Pietsch Hamburg-Ost Damaschke im Text",
        "coverage": "Rechnungsdaten und Lieferantenstandard",
    },
    {
        "supplier_name": "Rieprecht GmbH",
        "status": "gut",
        "recognition": "Rieprecht GmbH, rieprecht-gmbh.de und RIEP-Dateinamen",
        "coverage": "Rechnungsdaten, Fälligkeit, Container-/Transportpositionen und Projektzuordnung über Text",
    },
    {
        "supplier_name": "Rönnfeld ROLLLADEN UND MARKISEN GmbH",
        "status": "gut",
        "recognition": "Rönnfeld/roennfeld-rollladenbau.de und R25-Belegformat",
        "coverage": "Rechnungen und Gutschriften, 0%-USt, Kundenreferenz, BV-Hinweise",
    },
    {
        "supplier_name": "konzept 54 GmbH & Co.KG",
        "status": "gut",
        "recognition": "konzept-54.de, Kunden-Nr. 10019 und Projekt-/Supporttexte",
        "coverage": "Rechnungsdaten, Projektbezug und Kostenart nach Leistungsinhalt statt pauschal nach Lieferant",
    },
    {
        "supplier_name": "Euro Planen Handel und Service GmbH",
        "status": "gut",
        "recognition": "Euro Planen Handel und Service GmbH und Objekt-/Projektfelder",
        "coverage": "Rechnungsdaten, Fälligkeit, Objekt/Artikel und Material-Kostenart",
    },
    {
        "supplier_name": "Enno Roggemann GmbH & Co. KG",
        "status": "gut",
        "recognition": "roggemann.de und Enno Roggemann GmbH",
        "coverage": "Rechnungsdaten und Material-Kostenart",
    },
    {
        "supplier_name": "AF-Elektro GmbH / A. Franz Elektrotechnik",
        "status": "gut",
        "recognition": "AF-Elektro/A. Franz Elektrotechnik und info@af-elektro.de",
        "coverage": "Rechnungsdaten, Fremdleistungsbezug je Belegprüfung",
    },
    {
        "supplier_name": "Eindruck24",
        "status": "gut",
        "recognition": "Eindruck24 und buchhaltung@eindruck24.de",
        "coverage": "Rechnungsdaten, allgemeine Kosten/Material nach Beleg",
    },
    {
        "supplier_name": "büroshop24 GmbH",
        "status": "gut",
        "recognition": "bueroshop24.de oder büroshop24 GmbH",
        "coverage": "Rechnungsdaten, Gemeinkosten/Material nach Beleg",
    },
    {
        "supplier_name": "DATEV",
        "status": "gut",
        "recognition": "DATEV-Rechnungsformat und Dateiname",
        "coverage": "Abo-/Softwarekosten und Rechnungsdaten",
    },
    {
        "supplier_name": "Mittwald CM Service GmbH & Co. KG",
        "status": "gut",
        "recognition": "Mittwald CM Service oder info@mittwald.de",
        "coverage": "Hosting-/Softwarekosten und Rechnungsdaten",
    },
    {
        "supplier_name": "I.B.E. Institut für betriebliches Entgeltmanagement GmbH",
        "status": "gut",
        "recognition": "Institutsname oder Primecard/Mariensstraße-Merkmale",
        "coverage": "Dienstleistungs-/Gemeinkosten und Rechnungsdaten",
    },
    {
        "supplier_name": "Maison Gebäudeservice",
        "status": "gut",
        "recognition": "Maison-Gebäudeservice-Rechnungsformat/Dateiname",
        "coverage": "Fremdleistungsbelege und Rechnungsdaten",
    },
    {
        "supplier_name": "Böhm Malereibetrieb GmbH",
        "status": "gut",
        "recognition": "Böhm/Maler L. Böhm im Dateinamen oder Belegtext",
        "coverage": "Lieferant, Belegnummer, Datum, Kundennummer, Fälligkeit, Nettosumme, Leistungsbezeichnung und Bauvorhaben-Hinweis",
    },
    {
        "supplier_name": "Tankbelege",
        "status": "bedingt",
        "recognition": "Tankbeleg-/Fahrzeug-Dateiname und Scan/Fotobeleg-Fallback",
        "coverage": "Fahrzeug/Tanken, Datum/Beträge teils über Dateiname oder OCR-nahe Texterkennung",
    },
]


def list_extraction_capabilities() -> list[dict]:
    return sorted(EXTRACTION_CAPABILITIES, key=lambda item: item["supplier_name"].casefold())


def run_mock_extraction(
    document_id: UUID,
    processing_job_id: UUID | None = None,
    *,
    force: bool = False,
    actor: str = "system",
) -> dict:
    document = get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    active_job_id = document.get("processing_job_id")
    if active_job_id and active_job_id != str(processing_job_id):
        raise HTTPException(status_code=409, detail="Beleg wird gerade von einem Bulk-Job verarbeitet.")
    if force:
        if document.get("status") not in REEXTRACTABLE_DOCUMENT_STATUSES or not document.get("extraction"):
            raise HTTPException(status_code=409, detail="Neu-Extraktion blockiert: Beleg hat noch keine Extraktion.")
    elif document.get("status") not in EXTRACTABLE_DOCUMENT_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Extraktion blockiert: Beleg ist bereits im Review oder freigegeben.",
        )

    insert_audit_event(
        tenant_id=document["tenant_id"],
        event_type="document.reextraction_started" if force else "document.extraction_started",
        document_id=document_id,
        actor=actor,
        details={"previous_status": document.get("status")} if force else None,
    )

    extraction = _build_extraction_result(document)
    return save_document_extraction(
        document_id=document_id,
        tenant_id=document["tenant_id"],
        extraction=extraction,
    )


def _build_extraction_result(document: dict) -> dict:
    if _is_standalone_xml_document(document):
        structured = _build_standalone_xml_result(document)
        return structured or _build_mock_result(document)

    if _is_pdf_document(document):
        structured = _build_embedded_xml_result(document)
        if structured:
            return structured

        return _build_pdf_text_result(document)

    return _build_mock_result(document)


def _is_standalone_xml_document(document: dict) -> bool:
    content_type = str(document.get("content_type") or "").split(";", 1)[0].strip().lower()
    return content_type in {"application/xml", "text/xml"} or Path(document["original_filename"]).suffix.lower() == ".xml"


def _is_pdf_document(document: dict) -> bool:
    content_type = str(document.get("content_type") or "").split(";", 1)[0].strip().lower()
    return content_type == "application/pdf" or Path(document["original_filename"]).suffix.lower() == ".pdf"


def _structured_source(document: dict) -> str:
    return "standalone_xml" if _is_standalone_xml_document(document) else "embedded_xml"


def _normalized_structured_filename(filename: str | None, document: dict) -> str | None:
    if not filename or not _is_standalone_xml_document(document):
        return filename
    return f"{Path(filename).stem}.xml"


def _build_embedded_xml_result(document: dict) -> dict | None:
    if not _is_pdf_document(document):
        return None

    xml_attachment = _find_embedded_invoice_xml(document["storage_path"])
    if not xml_attachment:
        return None

    attachment_name, xml_content = xml_attachment
    text = _extract_pdf_text(document["storage_path"])
    return _build_structured_xml_result(document, attachment_name, xml_content, text)


def _build_standalone_xml_result(document: dict) -> dict | None:
    xml_path = get_settings().storage_root / document["storage_path"]
    return _build_structured_xml_result(document, document["original_filename"], xml_path.read_bytes(), "")


def _build_structured_xml_result(
    document: dict,
    attachment_name: str,
    xml_content: bytes,
    text: str,
) -> dict | None:
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError:
        return None

    if root.tag.endswith("CrossIndustryInvoice"):
        return _build_cii_xml_result(document, root, attachment_name, text)
    if _local_name(root.tag) in {"Invoice", "CreditNote"}:
        return _build_ubl_xml_result(document, root, attachment_name, text)
    return None


def _build_cii_xml_result(
    document: dict,
    root: ElementTree.Element,
    attachment_name: str,
    text: str,
) -> dict | None:
    if not root.tag.endswith("CrossIndustryInvoice"):
        return None
    ns = {
        "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
        "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
        "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    }

    invoice_number = _xml_text(root, ".//rsm:ExchangedDocument/ram:ID", ns)
    customer_number = _xml_text(
        root,
        ".//ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:ID",
        ns,
    ) or _find_customer_number(text)
    invoice_date = _cii_date(
        _xml_text(root, ".//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString", ns)
    )
    supplier_name = _normalize_supplier_name(
        _xml_text(root, ".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:Name", ns)
    )
    currency = _xml_text(root, ".//ram:ApplicableHeaderTradeSettlement/ram:InvoiceCurrencyCode", ns)
    product_name = _clean_product_name(
        _find_first_position_product_name(text)
        or _xml_text(root, ".//ram:IncludedSupplyChainTradeLineItem[1]/ram:SpecifiedTradeProduct/ram:Name", ns)
    )
    payment_description = _xml_text(
        root,
        ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradePaymentTerms/ram:Description",
        ns,
    )
    xml_payment_due_date = _cii_date(
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
    if discount_base is None and visible_discount.get("discount_net_amount") is not None and net_amount is not None:
        discount_base = net_amount
    if visible_discount.get("discount_percent") is not None:
        discount_percent = visible_discount["discount_percent"]
    discount_amount = visible_discount.get("discount_amount")
    if discount_amount is None and discount_base is not None and discount_percent is not None:
        discount_amount = (discount_base * discount_percent / Decimal("100")).quantize(Decimal("0.01"))
    is_credit_note = gross_amount is not None and gross_amount < 0
    discount_amount = _signed_discount_amount(discount_amount, gross_amount)

    # Some supplier XML files do not carry construction-site delivery text,
    # so the project assignment is enriched from the human-readable PDF.
    delivery_address = _xml_delivery_address(root, ns) or _find_delivery_address(text)
    customer_reference = _find_customer_reference(text) or _find_assignment_hint_from_filename(document["original_filename"])
    discount_due_date = None
    due_date = (
        visible_discount.get("due_date")
        or _find_date(text, r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+ohne Abzug")
        or _find_date(text, r"ohne Abzug\s*(\d{2}\.\d{2}\.\d{4})")
        or (xml_payment_due_date if discount_percent is None else None)
    )
    visible_discount_due_date = _find_date(text, r"verrechnen bis zum\s+(\d{2}\.\d{2}\.\d{2})")
    if visible_discount_due_date or visible_discount.get("discount_due_date"):
        discount_due_date = visible_discount_due_date or visible_discount.get("discount_due_date")
    elif discount_percent is not None and xml_payment_due_date:
        discount_due_date = xml_payment_due_date
    supplier_rule = find_supplier_rule(document["tenant_id"], supplier_name, customer_number, text[:4000])
    if supplier_rule:
        supplier_name = supplier_rule["supplier_name"]
        customer_number = supplier_rule["customer_number"] or customer_number
    assignment_match = _assignment_unit_match(document["tenant_id"], delivery_address, customer_reference, text)
    assignment = assignment_match["assignment"] if assignment_match else None
    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    assignment_type = _assignment_type(delivery_address, assignment)
    cost_category = _cost_category_for_supplier_rule(supplier_rule, supplier_name, product_name, text, assignment_type)
    normalized_filename = _normalized_invoice_filename(
        invoice_number=invoice_number,
        assignment=assignment,
        assignment_type=assignment_type,
        tenant_profile=tenant_profile,
        supplier_name=supplier_name or _supplier_from_filename(Path(document["original_filename"]).stem),
        product_name=_filename_product_name(product_name or "Eingangsrechnung"),
        invoice_date=invoice_date,
    )
    normalized_filename = _normalized_structured_filename(normalized_filename, document)
    line_count = len(root.findall(".//ram:IncludedSupplyChainTradeLineItem", ns))

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
        if not _has_value(value)
    ]
    validation_errors = _structured_xml_validation_errors(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        supplier_name=supplier_name,
        currency=currency,
        net_amount=net_amount,
        tax_amount=tax_amount,
        gross_amount=gross_amount,
        line_count=line_count,
    )
    warnings = []
    if delivery_address and not assignment:
        warnings.append("Nicht sicher erkannt: Zuordnung aus Mandanten-Stammdaten.")
    if visible_discount_base is not None and xml_discount_base is not None and visible_discount_base != xml_discount_base:
        warnings.append(
            f"Skonto-Basis aus sichtbarem Beleg ({visible_discount_base}) weicht von XML ({xml_discount_base}) ab."
        )
    if missing:
        warnings.append(f"Nicht sicher erkannt: {', '.join(missing)}.")
    warnings.extend(f"E-Rechnungsvalidierung: {error}" for error in validation_errors)

    return {
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": customer_number,
        "customer_reference": customer_reference,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "discount_due_date": discount_due_date,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": delivery_address,
        "assignment_code": _assignment_code(assignment),
        "assignment_label": assignment["label"] if assignment else None,
        "assignment_kind": assignment["kind"] if assignment else None,
        "assignment_revenue_relevant": assignment["revenue_relevant"] if assignment else None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": _legacy_project_code(assignment),
        "project_number": _project_number(assignment),
        "project_name": assignment["label"] if _legacy_project_code(assignment) else None,
        "assignment_type": assignment_type,
        "assignment_match": _assignment_match_payload(assignment_match),
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
        "discount_net_amount": visible_discount.get("discount_net_amount"),
        "discount_tax_amount": visible_discount.get("discount_tax_amount"),
        "discount_gross_amount": visible_discount.get("discount_gross_amount"),
        "payment_terms": _payment_terms(
            gross_amount=due_payable_amount or gross_amount,
            due_date=due_date,
            discount_due_date=discount_due_date,
            discount_base=discount_base,
            discount_percent=discount_percent,
            discount_amount=discount_amount,
            discounted_payable_amount=visible_discount.get("discounted_payable_amount"),
            is_credit_note=is_credit_note,
        ),
        "currency": currency or "EUR",
        "confidence": Decimal("1.00") if not missing and not validation_errors else Decimal("0.90"),
        "warnings": warnings,
        "normalized_filename": normalized_filename,
        "source": _structured_source(document),
        "structured_attachment": attachment_name,
        "xml_format": "cii",
        "structured_validation": _structured_xml_validation("cii", validation_errors),
        "structured_validation_errors": validation_errors,
    }


def _build_ubl_xml_result(
    document: dict,
    root: ElementTree.Element,
    attachment_name: str,
    text: str,
) -> dict | None:
    ns = {
        "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    }
    root_name = _local_name(root.tag)
    line_tag = "CreditNoteLine" if root_name == "CreditNote" else "InvoiceLine"
    monetary_total_tag = "RequestedMonetaryTotal" if root_name == "CreditNote" else "LegalMonetaryTotal"

    invoice_number = _xml_text(root, "./cbc:ID", ns)
    customer_number = _xml_text(root, "./cbc:BuyerReference", ns) or _find_customer_number(text)
    invoice_date = _xml_text(root, "./cbc:IssueDate", ns)
    due_date = _xml_text(root, "./cbc:DueDate", ns)
    supplier_name = _normalize_supplier_name(
        _xml_text(root, ".//cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName", ns)
        or _xml_text(root, ".//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name", ns)
    )
    product_name = _clean_product_name(
        _xml_text(root, f".//cac:{line_tag}[1]/cac:Item/cbc:Name", ns)
        or _xml_text(root, f".//cac:{line_tag}[1]/cbc:Note", ns)
    )
    currency = _xml_text(root, "./cbc:DocumentCurrencyCode", ns) or "EUR"
    net_amount = _xml_decimal(
        root,
        f".//cac:{monetary_total_tag}/cbc:LineExtensionAmount",
        ns,
    ) or _xml_decimal(root, f".//cac:{monetary_total_tag}/cbc:TaxExclusiveAmount", ns)
    tax_amount = _xml_decimal(root, ".//cac:TaxTotal/cbc:TaxAmount", ns)
    gross_amount = _xml_decimal(root, f".//cac:{monetary_total_tag}/cbc:TaxInclusiveAmount", ns)
    due_payable_amount = _xml_decimal(root, f".//cac:{monetary_total_tag}/cbc:PayableAmount", ns)
    payment_description = _xml_text(root, ".//cac:PaymentTerms/cbc:Note", ns)
    discount_base = _description_decimal(payment_description, "BASISBETRAG")
    discount_percent = _description_decimal(payment_description, "PROZENT")
    discount_amount = None
    if discount_base is not None and discount_percent is not None:
        discount_amount = (discount_base * discount_percent / Decimal("100")).quantize(Decimal("0.01"))
    is_credit_note = root_name == "CreditNote" or (gross_amount is not None and gross_amount < 0)
    discount_amount = _signed_discount_amount(discount_amount, gross_amount)

    delivery_address = _ubl_delivery_address(root, ns) or _find_delivery_address(text)
    customer_reference = _find_customer_reference(text) or _find_assignment_hint_from_filename(document["original_filename"])
    supplier_rule = find_supplier_rule(document["tenant_id"], supplier_name, customer_number, text[:4000])
    if supplier_rule:
        supplier_name = supplier_rule["supplier_name"]
        customer_number = supplier_rule["customer_number"] or customer_number
    assignment_match = _assignment_unit_match(document["tenant_id"], delivery_address, customer_reference, text)
    assignment = assignment_match["assignment"] if assignment_match else None
    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    assignment_type = _assignment_type(delivery_address, assignment)
    cost_category = _cost_category_for_supplier_rule(supplier_rule, supplier_name, product_name, text, assignment_type)
    normalized_filename = _normalized_invoice_filename(
        invoice_number=invoice_number,
        assignment=assignment,
        assignment_type=assignment_type,
        tenant_profile=tenant_profile,
        supplier_name=supplier_name or _supplier_from_filename(Path(document["original_filename"]).stem),
        product_name=_filename_product_name(product_name or "E-Rechnung"),
        invoice_date=invoice_date,
    )

    normalized_filename = _normalized_structured_filename(normalized_filename, document)
    line_count = len(root.findall(f".//cac:{line_tag}", ns))

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
        if not _has_value(value)
    ]
    validation_errors = _structured_xml_validation_errors(
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        supplier_name=supplier_name,
        currency=currency,
        net_amount=net_amount,
        tax_amount=tax_amount,
        gross_amount=gross_amount,
        line_count=line_count,
    )
    warnings = []
    if delivery_address and not assignment:
        warnings.append("Nicht sicher erkannt: Zuordnung aus Mandanten-Stammdaten.")
    if missing:
        warnings.append(f"Nicht sicher erkannt: {', '.join(missing)}.")
    warnings.extend(f"E-Rechnungsvalidierung: {error}" for error in validation_errors)

    return {
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": customer_number,
        "customer_reference": customer_reference,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "discount_due_date": None,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": delivery_address,
        "assignment_code": _assignment_code(assignment),
        "assignment_label": assignment["label"] if assignment else None,
        "assignment_kind": assignment["kind"] if assignment else None,
        "assignment_revenue_relevant": assignment["revenue_relevant"] if assignment else None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": _legacy_project_code(assignment),
        "project_number": _project_number(assignment),
        "project_name": assignment["label"] if _legacy_project_code(assignment) else None,
        "assignment_type": assignment_type,
        "assignment_match": _assignment_match_payload(assignment_match),
        "cost_category": cost_category,
        "product_name": product_name,
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "gross_amount": gross_amount,
        "due_payable_amount": due_payable_amount,
        "discounted_payable_amount": None,
        "is_credit_note": is_credit_note,
        "document_type": "credit_note" if is_credit_note else "incoming_invoice",
        "discount_base": discount_base,
        "xml_discount_base": discount_base,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "payment_terms": _payment_terms(
            gross_amount=due_payable_amount or gross_amount,
            due_date=due_date,
            discount_due_date=None,
            discount_base=discount_base,
            discount_percent=discount_percent,
            discount_amount=discount_amount,
            discounted_payable_amount=None,
            is_credit_note=is_credit_note,
        ),
        "currency": currency,
        "confidence": Decimal("1.00") if not missing and not validation_errors else Decimal("0.90"),
        "warnings": warnings,
        "normalized_filename": normalized_filename,
        "source": _structured_source(document),
        "structured_attachment": attachment_name,
        "xml_format": "ubl",
        "structured_validation": _structured_xml_validation("ubl", validation_errors),
        "structured_validation_errors": validation_errors,
    }


def _build_pdf_text_result(document: dict) -> dict:
    text = _extract_pdf_text(document["storage_path"])
    if len(text.strip()) < 80:
        tank_receipt = _build_scanned_tank_receipt_result(document)
        if tank_receipt:
            return _with_pdf_text_diagnostics(tank_receipt, text)
        dammers_invoice = _build_scanned_dammers_invoice_result(document)
        if dammers_invoice:
            return _with_pdf_text_diagnostics(dammers_invoice, text)
        return _with_pdf_text_diagnostics(_build_unreadable_pdf_result(document), text)

    invoice_number = _find_rieprecht_invoice_number(text) or _find_text(text, r"Rechnungs-Nr\.?:\s*([A-Z0-9-]+?)(?=Datum|Leistungs|Kunden|Auftrag|\s|$)") or _find_text(
        text,
        r"Rechnungsnummer:\s*([A-Z0-9-]+[a-z]?)",
    ) or _find_text(
        text,
        r"Rechnung\s+Nr\.:\s*([0-9]+)",
    ) or _find_text(
        text,
        r"\bRechnung\s+([0-9]{2}-[0-9]{5,})\b",
    ) or _find_text(
        text,
        r"Rechnung:\s*\n\s*([0-9]{4,})\b",
    ) or _find_text(
        text,
        r"RechnungsNr\.\s*:\s*([0-9]+)\s+\d{2}\.\d{2}\.\d{2,4}",
    ) or _find_text(
        text,
        r"Ihre Kundennummer Unser Vorgang Datum\s*Q[0-9]+\s*(R\d{2}-\d{5})",
    ) or _find_text(
        text,
        r"Kunde:\s*Q[0-9]+Rechnung:\s*(R\d{2}-\d{5})",
    ) or _find_text(
        text,
        r"Rechnungs-Nr\.\s+Kunden-Nr\.\s+Rg\.-/Liefer-Datum\s+Auftrags-Nr\..*?\n\s*[^\n]+\n\s*([0-9]{6,})\s+[0-9]{6,}\s+\d{2}\.\d{2}\.\d{4}",
    ) or _find_text(
        text,
        r"(?:Rechnung|Retourgutschrift)\s+Datum\s+Seite\s*\n\s*([0-9]{6,})\s+\d{2}\.\d{2}\.\d{4}",
    ) or _find_text(
        text,
        r"KD-Nr\.\s+Rechn\.Nr\.\s+Datum\s+Blatt\s*\n\s*480\s+FRHA05\s+([0-9]{6,})\s+\d{2}\.\d{2}\.\d{4}",
    ) or _find_text(
        text,
        r"\*(GS\d{6,}|RE\d{6,})\d{2}\*",
    ) or _find_text(
        text,
        r"\bNummer\s*:\s*([0-9]+-[0-9]+)",
    ) or _find_text(
        text,
        r"Nr\.\s*\(S\)\s*:\s*([0-9-]+)",
    ) or _find_text(
        text,
        r"Belegnummer:\s*([A-Z]{1,5}\d+)",
    ) or _invoice_number_from_filename(document["original_filename"])
    customer_number = _find_customer_number(text)
    invoice_date = _find_rieprecht_invoice_date(text) or _find_date(text, r"Datum\s*:\s*(\d{2}\.\d{2}\.\d{4})") or _find_date(
        text,
        r"M[üÃ¼]nchen,\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Hamburg,\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Kunden-Nr\.\s*:\s*\n\s*[0-9]+[^\n]*\n\s*(\d{2}\.\d{2}\.\d{4})\s*\n\s*Rechnung\s+[0-9]{2}-[0-9]{5,}",
    ) or _find_date(
        text,
        r"Rechnungsdatum:\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"RechnungsNr\.\s*:\s*[0-9]+\s+(\d{2}\.\d{2}\.\d{2,4})",
    ) or _find_date(
        text,
        r"RechnungsNr\.\s*\.\s*:\s*[0-9]{2}[\s\S]{0,400}?(\d{2}\.\d{2}\.\d{2,4})",
    ) or _find_date(
        text,
        r"Ihre Kundennummer Unser Vorgang Datum\s*Q[0-9]+\s*R\d{2}-\d{5}\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Kunde:\s*Q[0-9]+Rechnung:\s*R\d{2}-\d{5}Datum:\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Rechnungs-Nr\.\s+Kunden-Nr\.\s+Rg\.-/Liefer-Datum\s+Auftrags-Nr\..*?\n\s*[^\n]+\n\s*[0-9]{6,}\s+[0-9]{6,}\s+(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"(?:Rechnung|Retourgutschrift)\s+Datum\s+Seite\s*\n\s*[0-9]{6,}\s+(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"KD-Nr\.\s+Rechn\.Nr\.\s+Datum\s+Blatt\s*\n\s*480\s+FRHA05\s+[0-9]{6,}\s+(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Datum\s*-\s*Zeit\s*:\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Belegdatum:\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Belegdatum:\s*(?:\n\s*[A-Z]{1,5}\s*:\s*[A-Z0-9-]+)?\s*\n\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Belegdatum:\s*\n\s*Kundennummer:\s*\n\s*[A-Z]{1,5}\d+\s*\n\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"Kundennummer:\s*\n\s*Belegdatum:\s*\n\s*Belegnummer:\s*\n\s*[^\n]*\n\s*[0-9]{6,}\s*\n\s*(\d{2}\.\d{2}\.\d{4})",
    ) or _find_date(
        text,
        r"\n\s*[0-9]{6,}\s*\n\s*(\d{2}\.\d{2}\.\d{4})\s*\n\s*(?:GS|RE)\d{6,}",
    ) or _invoice_date_from_filename(document["original_filename"])
    due_date = (
        _find_date(text, r"ohne Abzug\s*(\d{2}\.\d{2}\.\d{4})")
        or _find_date(text, r"Zahlung ohne Abzug bis\s+(\d{2}\.\d{2}\.\d{4})")
        or _find_date(text, r"Rechnungsbetrag bis zum\s+(\d{2}\.\d{2}\.\d{4})\s+zu begleichen")
        or _find_date(text, r"sp[^\s,]*testens jedoch bis zum\s+(\d{2}\.\d{2}\.\d{4})")
        or _find_date(text, r"bis\s+sp[^\s,]*testens\s+zum\s+(\d{2}\.\d{2}\.\d{4})")
        or _find_date(text, r"zahlbar bis spätestens\s+(\d{2}\.\d{2}\.\d{2})")
        or _find_date(text, r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+abzgl\.")
        or _find_date(text, r"fr[üÃ¼]hestens am\s+(\d{2}\.\d{2}\.\d{4})")
        or _find_roennfeld_due_date(text)
    )
    allocation_lines = _find_allocation_lines(document["tenant_id"], text)
    visible_discount = _find_visible_discount_terms(text)
    pietsch_discount = _find_pietsch_discount_terms(text)
    roggemann_discount = _find_roggemann_discount_terms(text)
    af_elektro_discount = _find_af_elektro_payment_terms(text, invoice_date)
    due_date = (
        due_date
        or _find_bueroshop_due_date(text)
        or _find_dammers_due_date(text)
        or visible_discount.get("due_date")
        or pietsch_discount.get("due_date")
        or roggemann_discount.get("due_date")
        or af_elektro_discount.get("due_date")
    )
    discount_percent = (
        _find_discount_percent(text)
        or visible_discount.get("discount_percent")
        or pietsch_discount.get("discount_percent")
        or roggemann_discount.get("discount_percent")
        or af_elektro_discount.get("discount_percent")
    )
    discount_due_date = (
        _find_date(text, r"(\d{2}\.\d{2}\.\d{4})\s+3,00%\s+Skonto")
        or _discount_due_date_from_days(invoice_date, _find_discount_days(text))
        or _find_dammers_discount_due_date(text)
        or visible_discount.get("discount_due_date")
        or pietsch_discount.get("discount_due_date")
        or roggemann_discount.get("discount_due_date")
        or af_elektro_discount.get("discount_due_date")
    )
    totals = _find_invoice_totals(text)
    discount_base = (
        totals.get("discount_base")
        or visible_discount.get("discount_base")
        or pietsch_discount.get("discount_base")
        or roggemann_discount.get("discount_base")
        or af_elektro_discount.get("discount_base")
    )
    net_amount = totals.get("net_amount")
    tax_amount = totals.get("tax_amount")
    gross_amount = totals.get("gross_amount")
    discount_amount = (
        _find_dammers_discount_amount(text)
        or visible_discount.get("discount_amount")
        or pietsch_discount.get("discount_amount")
        or roggemann_discount.get("discount_amount")
        or af_elektro_discount.get("discount_amount")
        or _find_money(text, r"Skonto\s*=\s*([0-9.]+,\d{2})")
    )
    discounted_payable_amount = (
        visible_discount.get("discounted_payable_amount")
        or pietsch_discount.get("discounted_payable_amount")
        or roggemann_discount.get("discounted_payable_amount")
        or af_elektro_discount.get("discounted_payable_amount")
    )
    if net_amount is None and tax_amount is not None and gross_amount is not None:
        net_amount = (gross_amount - tax_amount).quantize(Decimal("0.01"))
    if discount_base is None and visible_discount.get("discount_net_amount") is not None and net_amount is not None:
        discount_base = net_amount
    if (
        discount_base is None
        and visible_discount.get("discount_net_amount") is None
        and gross_amount is not None
        and (discount_percent is not None or discount_amount is not None)
    ):
        discount_base = gross_amount
    if discount_amount is None and discount_base is not None and discount_percent is not None:
        discount_amount = (discount_base * discount_percent / Decimal("100")).quantize(Decimal("0.01"))
    is_credit_note = gross_amount is not None and gross_amount < 0
    discount_amount = _signed_discount_amount(discount_amount, gross_amount)
    if discounted_payable_amount is None and gross_amount is not None and discount_amount is not None:
        discounted_payable_amount = (gross_amount - discount_amount).quantize(Decimal("0.01"))
    delivery_addresses = _find_delivery_addresses(text)
    delivery_address = (
        delivery_addresses[0]
        if delivery_addresses
        else (_find_delivery_address(text) or _find_reference_delivery_address(text))
    )
    customer_reference = _find_customer_reference(text) or _find_assignment_hint_from_filename(document["original_filename"])
    supplier_name = _supplier_name(document, text)
    supplier_rule = find_supplier_rule(document["tenant_id"], supplier_name, customer_number, text[:4000])
    if supplier_rule:
        supplier_name = supplier_rule["supplier_name"]
        customer_number = supplier_rule["customer_number"] or customer_number
    assignment_match = _assignment_unit_match(document["tenant_id"], delivery_address, customer_reference, text)
    assignment = assignment_match["assignment"] if assignment_match else None
    if not assignment and delivery_addresses:
        assignment = _resolve_assignment_for_delivery_addresses(document["tenant_id"], delivery_addresses)
        if assignment:
            assignment_match = {"assignment": assignment, "score": None, "reasons": ["Lieferadresse"]}
    product_name = _product_name(text)
    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    allocation_lines_resolved = bool(allocation_lines) and all(
        allocation.get("assignment_code") for allocation in allocation_lines
    )
    assignment_type = "assignment_split" if len(allocation_lines) > 1 else _assignment_type(delivery_address, assignment)
    cost_category = _cost_category_for_supplier_rule(supplier_rule, supplier_name, product_name, text, assignment_type)
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
        if value is None or value == ""
    ]
    warnings = []
    if len(delivery_addresses) > 1:
        warnings.append(
            "Mehrere Lieferadressen/Zuordnungen erkannt: bitte Zuordnung oder Splittung prüfen."
        )
    if delivery_address and not assignment and not allocation_lines_resolved:
        warnings.append("Nicht sicher erkannt: Zuordnung aus Mandanten-Stammdaten.")
    if missing:
        warnings.append(f"Nicht sicher erkannt: {', '.join(missing)}.")

    return _with_pdf_text_diagnostics({
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": customer_number,
        "customer_reference": customer_reference,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "discount_due_date": discount_due_date,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": delivery_address,
        "delivery_addresses": delivery_addresses,
        "allocation_lines": allocation_lines,
        "assignment_code": _assignment_code(assignment),
        "assignment_label": assignment["label"] if assignment else None,
        "assignment_kind": assignment["kind"] if assignment else None,
        "assignment_revenue_relevant": assignment["revenue_relevant"] if assignment else None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": _legacy_project_code(assignment),
        "project_number": _project_number(assignment),
        "project_name": assignment["label"] if _legacy_project_code(assignment) else None,
        "assignment_type": assignment_type,
        "assignment_match": _assignment_match_payload(assignment_match),
        "cost_category": cost_category,
        "product_name": product_name,
        "net_amount": net_amount,
        "tax_amount": tax_amount,
        "gross_amount": gross_amount,
        "discount_base": discount_base,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "discount_net_amount": visible_discount.get("discount_net_amount"),
        "discount_tax_amount": visible_discount.get("discount_tax_amount"),
        "discount_gross_amount": visible_discount.get("discount_gross_amount"),
        "discounted_payable_amount": discounted_payable_amount,
        "is_credit_note": is_credit_note,
        "document_type": "credit_note" if is_credit_note else "incoming_invoice",
        "payment_terms": _payment_terms(
            gross_amount=gross_amount,
            due_date=due_date,
            discount_due_date=discount_due_date,
            discount_base=discount_base,
            discount_percent=discount_percent,
            discount_amount=discount_amount,
            discounted_payable_amount=discounted_payable_amount,
            is_credit_note=is_credit_note,
        ),
        "currency": "EUR",
        "confidence": Decimal("0.88") if not missing else Decimal("0.72"),
        "warnings": warnings,
        "normalized_filename": normalized_filename,
        "source": "pdf_text_rules",
    }, text)


def _build_mock_result(document: dict) -> dict:
    stem = Path(document["original_filename"]).stem
    supplier_name = _supplier_from_filename(stem)
    created_at = datetime.fromisoformat(document["created_at"])
    gross_amount = _mock_gross_amount(document["size_bytes"])
    net_amount = (gross_amount / Decimal("1.19")).quantize(Decimal("0.01"))
    tax_amount = (gross_amount - net_amount).quantize(Decimal("0.01"))

    warnings = [
        "Mock-Extraktion: Werte müssen fachlich geprüft werden.",
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


def _build_unreadable_pdf_result(document: dict) -> dict:
    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    stem = Path(document["original_filename"]).stem
    supplier_name = _supplier_from_filename(stem)
    invoice_number = _invoice_number_from_filename(document["original_filename"])
    invoice_date = _invoice_date_from_filename(document["original_filename"])
    normalized_filename = _normalized_invoice_filename(
        invoice_number=invoice_number,
        assignment=None,
        assignment_type="assignment_unresolved",
        tenant_profile=tenant_profile,
        supplier_name=supplier_name,
        product_name="PDF nicht lesbar",
        invoice_date=invoice_date,
    )

    return {
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": None,
        "customer_reference": None,
        "invoice_date": invoice_date,
        "due_date": None,
        "discount_due_date": None,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": None,
        "delivery_addresses": [],
        "allocation_lines": [],
        "assignment_code": None,
        "assignment_label": None,
        "assignment_kind": None,
        "assignment_revenue_relevant": None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": None,
        "project_number": None,
        "project_name": None,
        "assignment_type": "assignment_unresolved",
        "cost_category": None,
        "product_name": None,
        "net_amount": None,
        "tax_amount": None,
        "gross_amount": None,
        "discount_base": None,
        "discount_percent": None,
        "discount_amount": None,
        "discount_net_amount": None,
        "discount_tax_amount": None,
        "discount_gross_amount": None,
        "discounted_payable_amount": None,
        "is_credit_note": False,
        "document_type": "incoming_invoice",
        "payment_terms": _payment_terms(
            gross_amount=None,
            due_date=None,
            discount_due_date=None,
            discount_base=None,
            discount_percent=None,
            discount_amount=None,
            discounted_payable_amount=None,
            is_credit_note=False,
        ),
        "currency": "EUR",
        "confidence": Decimal("0.20"),
        "warnings": [
            "PDF-Text konnte nicht ausreichend gelesen werden. Bitte OCR/KI-Prüfung oder manuelle Erfassung verwenden.",
        ],
        "normalized_filename": normalized_filename,
        "source": "pdf_unreadable",
    }


def _build_scanned_tank_receipt_result(document: dict) -> dict | None:
    parsed = _tank_receipt_from_filename(document["original_filename"])
    if not parsed:
        return None

    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    supplier_name = "Tankbeleg"
    product_name = "Diesel"
    invoice_number = parsed["invoice_number"]
    invoice_date = parsed["invoice_date"]
    normalized_filename = _normalized_invoice_filename(
        invoice_number=invoice_number,
        assignment=None,
        assignment_type="general_cost",
        tenant_profile=tenant_profile,
        supplier_name=supplier_name,
        product_name=product_name,
        invoice_date=invoice_date,
    )
    vehicle = parsed["vehicle"]
    driver = parsed.get("driver")
    warnings = [
        "Scan-/Foto-Tankbeleg: Beträge, Liter und Tankstelle müssen per OCR oder manuell geprüft werden.",
    ]
    if driver:
        warnings.append(f"Fahrer-Kürzel aus Dateiname erkannt: {driver}.")

    return {
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": None,
        "customer_reference": vehicle,
        "invoice_date": invoice_date,
        "due_date": invoice_date,
        "discount_due_date": None,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": None,
        "delivery_addresses": [],
        "allocation_lines": [],
        "assignment_code": None,
        "assignment_label": None,
        "assignment_kind": None,
        "assignment_revenue_relevant": None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": None,
        "project_number": None,
        "project_name": None,
        "assignment_type": "general_cost",
        "cost_category": "fuel_vehicle",
        "product_name": product_name,
        "net_amount": None,
        "tax_amount": None,
        "gross_amount": None,
        "discount_base": None,
        "discount_percent": None,
        "discount_amount": None,
        "discount_net_amount": None,
        "discount_tax_amount": None,
        "discount_gross_amount": None,
        "discounted_payable_amount": None,
        "is_credit_note": False,
        "document_type": "incoming_invoice",
        "payment_terms": _payment_terms(
            gross_amount=None,
            due_date=invoice_date,
            discount_due_date=None,
            discount_base=None,
            discount_percent=None,
            discount_amount=None,
            discounted_payable_amount=None,
            is_credit_note=False,
        ),
        "currency": "EUR",
        "confidence": Decimal("0.62"),
        "warnings": warnings,
        "normalized_filename": normalized_filename,
        "source": "pdf_scan_filename_rules",
        "vehicle": vehicle,
        "driver": driver,
    }


def _build_scanned_dammers_invoice_result(document: dict) -> dict | None:
    parsed = _dammers_invoice_from_filename(document["original_filename"])
    if not parsed:
        return None

    tenant_profile = ensure_tenant_profile(document["tenant_id"])
    supplier_name = "Rolf Dammers oHG"
    invoice_number = parsed["invoice_number"]
    invoice_date = parsed.get("invoice_date")
    customer_number = None
    supplier_rule = find_supplier_rule(document["tenant_id"], supplier_name, None, "")
    if supplier_rule:
        supplier_name = supplier_rule["supplier_name"]
        customer_number = supplier_rule["customer_number"]
    normalized_filename = _normalized_invoice_filename(
        invoice_number=invoice_number,
        assignment=None,
        assignment_type="assignment_unresolved",
        tenant_profile=tenant_profile,
        supplier_name=supplier_name,
        product_name="Eingangsrechnung",
        invoice_date=invoice_date,
    )
    warnings = [
        "Dammers-Scan: Lieferant und Belegnummer aus Dateiname erkannt; Beträge, Datum, Skonto und Zuordnung brauchen OCR oder manuelle Prüfung.",
    ]
    if customer_number:
        warnings.append("Kundennummer aus Lieferantenregel übernommen.")

    return {
        "supplier_name": supplier_name,
        "invoice_number": invoice_number,
        "customer_number": customer_number,
        "customer_reference": None,
        "invoice_date": invoice_date,
        "due_date": None,
        "discount_due_date": None,
        "service_period": invoice_date[:7] if invoice_date else None,
        "delivery_address": None,
        "delivery_addresses": [],
        "allocation_lines": [],
        "assignment_code": None,
        "assignment_label": None,
        "assignment_kind": None,
        "assignment_revenue_relevant": None,
        "assignment_code_label": tenant_profile["assignment_code_label"],
        "assignment_label_singular": tenant_profile["assignment_label_singular"],
        "assignment_label_plural": tenant_profile["assignment_label_plural"],
        "assignment_code_prefix": tenant_profile["assignment_code_prefix"],
        "project_code": None,
        "project_number": None,
        "project_name": None,
        "assignment_type": "assignment_unresolved",
        "cost_category": "material",
        "product_name": None,
        "net_amount": None,
        "tax_amount": None,
        "gross_amount": None,
        "discount_base": None,
        "discount_percent": None,
        "discount_amount": None,
        "discount_net_amount": None,
        "discount_tax_amount": None,
        "discount_gross_amount": None,
        "discounted_payable_amount": None,
        "is_credit_note": False,
        "document_type": "incoming_invoice",
        "payment_terms": _payment_terms(
            gross_amount=None,
            due_date=None,
            discount_due_date=None,
            discount_base=None,
            discount_percent=None,
            discount_amount=None,
            discounted_payable_amount=None,
            is_credit_note=False,
        ),
        "currency": "EUR",
        "confidence": Decimal("0.50"),
        "warnings": warnings,
        "normalized_filename": normalized_filename,
        "source": "pdf_scan_filename_rules",
    }


def _dammers_invoice_from_filename(filename: str) -> dict | None:
    stem = Path(filename).stem
    match = search(r"\b([0-9]{6}-60[0-9])\b", stem)
    if not match:
        return None
    return {
        "invoice_number": match.group(1),
        "invoice_date": _invoice_date_from_filename(filename),
    }


def _tank_receipt_from_filename(filename: str) -> dict | None:
    stem = Path(filename).stem
    if "tankbeleg" not in stem.lower():
        return None
    date_match = search(r"(\d{4}-\d{2}-\d{2})", stem)
    vehicle_match = search(r"\b(HH[-\s]*FB[-\s]*\d+)\b", stem, flags=0)
    if not date_match or not vehicle_match:
        return None

    vehicle = sub(r"\s+", " ", vehicle_match.group(1).replace("-", " - ")).strip()
    vehicle = vehicle.replace("HH - FB", "HH-FB").replace(" - ", " ")
    vehicle = sub(r"\s+", " ", vehicle).strip()
    driver = _tank_receipt_driver_from_filename(stem)
    invoice_date = date_match.group(1)
    invoice_number = f"{vehicle} {invoice_date}"
    return {
        "vehicle": vehicle,
        "driver": driver,
        "invoice_date": invoice_date,
        "invoice_number": invoice_number,
    }


def _tank_receipt_driver_from_filename(stem: str) -> str | None:
    without_date = sub(r",?\s*\d{4}-\d{2}-\d{2}\s*$", "", stem).strip()
    parts = [part.strip() for part in without_date.split(",") if part.strip()]
    if not parts:
        return None
    last_part = parts[-1]
    lower_last = last_part.lower()
    if lower_last != "tankbeleg" and "tankbeleg" not in lower_last:
        return last_part
    words = last_part.split()
    if len(words) >= 2 and words[-1].isalpha():
        return words[-1]
    return None


def _extract_pdf_text(storage_path: str) -> str:
    text = _extract_pdf_text_pypdf(storage_path)
    if len(text.strip()) >= 80:
        return ExtractedPdfText(text, "pypdf")
    fallback_text = _extract_pdf_text_pymupdf(storage_path)
    if len(fallback_text.strip()) > len(text.strip()):
        return ExtractedPdfText(fallback_text, "pymupdf")
    ocr_text = _extract_pdf_text_pymupdf_ocr(storage_path)
    if len(ocr_text.strip()) > len(text.strip()):
        return ExtractedPdfText(ocr_text, "pymupdf_ocr")
    return ExtractedPdfText(text, "pypdf_short")


class ExtractedPdfText(str):
    def __new__(cls, value: str, source: str):
        obj = str.__new__(cls, value)
        obj.source = source
        return obj


def _with_pdf_text_diagnostics(result: dict, text: str) -> dict:
    result["pdf_text_source"] = getattr(text, "source", "unknown")
    result["pdf_text_length"] = len(text.strip())
    return result


def _extract_pdf_text_pypdf(storage_path: str) -> str:
    reader = _read_pdf(storage_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_pdf_text_pymupdf(storage_path: str) -> str:
    try:
        import fitz
    except ImportError:
        return ""

    pdf_path = get_settings().storage_root / storage_path
    if not pdf_path.is_file():
        return ""

    with fitz.open(pdf_path) as pdf:
        return "\n".join((page.get_text("text") or "").strip() for page in pdf)


def _extract_pdf_text_pymupdf_ocr(storage_path: str) -> str:
    try:
        import fitz
    except ImportError:
        return ""

    pdf_path = get_settings().storage_root / storage_path
    if not pdf_path.is_file():
        return ""

    page_texts = []
    try:
        with fitz.open(pdf_path) as pdf:
            for page in pdf:
                textpage = page.get_textpage_ocr(full=True, dpi=200, language="deu+eng")
                page_texts.append((page.get_text("text", textpage=textpage) or "").strip())
    except (RuntimeError, ValueError, OSError):
        return ""
    return "\n".join(page_texts)


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


def _has_value(value: object) -> bool:
    return value is not None and value != ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


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


def _ubl_delivery_address(root: ElementTree.Element, ns: dict[str, str]) -> str | None:
    street = _xml_text(root, ".//cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:StreetName", ns)
    building = _xml_text(root, ".//cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:BuildingNumber", ns)
    postcode = _xml_text(root, ".//cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:PostalZone", ns)
    city = _xml_text(root, ".//cac:Delivery/cac:DeliveryLocation/cac:Address/cbc:CityName", ns)
    if street and postcode and city:
        street_line = f"{street} {building}".strip() if building else street
        return f"{street_line}, {postcode} {city}"
    return None


def _structured_xml_validation_errors(
    *,
    invoice_number: str | None,
    invoice_date: str | None,
    supplier_name: str | None,
    currency: str | None,
    net_amount: Decimal | None,
    tax_amount: Decimal | None,
    gross_amount: Decimal | None,
    line_count: int,
) -> list[str]:
    errors = []
    required_values = {
        "Belegnummer": invoice_number,
        "Belegdatum": invoice_date,
        "Lieferant": supplier_name,
        "Währung": currency,
        "Netto": net_amount,
        "USt": tax_amount,
        "Brutto": gross_amount,
    }
    for label, value in required_values.items():
        if not _has_value(value):
            errors.append(f"Pflichtfeld fehlt: {label}.")

    if invoice_date and not _is_iso_date(invoice_date):
        errors.append("Belegdatum ist kein ISO-Datum YYYY-MM-DD.")
    if line_count < 1:
        errors.append("Mindestens eine Rechnungsposition fehlt.")
    if net_amount is not None and tax_amount is not None and gross_amount is not None:
        expected_gross = (net_amount + tax_amount).quantize(Decimal("0.01"))
        if abs(expected_gross - gross_amount) > Decimal("0.02"):
            errors.append("Summenprüfung fehlgeschlagen: Netto plus USt passt nicht zu Brutto.")

    return errors


def _structured_xml_validation(xml_format: str, errors: list[str]) -> dict[str, object]:
    return {
        "format": xml_format,
        "status": "failed" if errors else "passed",
        "errors": errors,
    }


def _is_iso_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _find_visible_discount_base(text: str) -> Decimal | None:
    match = search(
        r"(?:davon\s+skontof\S*hig|Skontof\S*higer\s+Betrag|skontierf\S*higer\s+Betrag\s+EUR)\s*:?\s*(-?[0-9.]+,\d{2})",
        text,
    )
    return _money_to_decimal_signed(match.group(1)) if match else None


def _find_visible_discount_terms(text: str) -> dict[str, Decimal | str | None]:
    tabular_terms = _find_tabular_discount_terms(text)
    haho_discount = search(
        r"Zahlung\s+bis\s+(\d{1,2}\.\d{2}\.\d{2,4})\s+mit\s+([0-9]+(?:,\d{1,2})?)\s*%\s+Skonto\s*=\s*(-?[0-9.]+,\d{2})",
        text,
    )
    haho_due_date = _find_date(text, r"bis\s+(\d{1,2}\.\d{2}\.\d{2,4})\s+(?:ohne Abzug|netto)")
    holz_junge_discount = search(
        r"(\d{2}\.\d{2}\.\d{2,4})\s+([0-9]+(?:,\d{1,2})?)%\s+Skonto\s*=\s*(-?[0-9.]+,\d{2})",
        text,
    )
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
    ) or _find_money(
        text,
        r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+abzgl\.\s+[0-9]+(?:,\d{1,2})?\s*%\s+Skonto\s+EUR\s+-?[0-9.]+,\d{2}\s+=\s+EUR\s+(-?[0-9.]+,\d{2})",
    )
    if discount_due_date is None:
        discount_due_date = _find_date(text, r"Zahlbar bis\s+(\d{2}\.\d{2}\.\d{4})\s+abzgl\.")
    if percent_text is None:
        percent_text = _find_text(text, r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+abzgl\.\s+([0-9]+(?:,\d{1,2})?)\s*%\s+Skonto")
    discount_amount = _find_money(
        text,
        r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+abzgl\.\s+[0-9]+(?:,\d{1,2})?\s*%\s+Skonto\s+EUR\s+([0-9.]+,\d{2})",
    ) or _find_money(
        text,
        r"Zahlbar bis\s+\d{2}\.\d{2}\.\d{4}\s+abzgl\.\s+[0-9]+(?:,\d{1,2})?\s*%\s+Skonto\s+EUR\s+(-[0-9.]+,\d{2})",
    )
    return {
        "discount_due_date": discount_due_date
        or (haho_discount and _date_text_to_iso(haho_discount.group(1)))
        or (holz_junge_discount and _date_text_to_iso(holz_junge_discount.group(1)))
        or tabular_terms.get("discount_due_date"),
        "due_date": due_date or haho_due_date or tabular_terms.get("due_date"),
        "discount_percent": (_money_to_decimal(percent_text) if percent_text else None)
        or (haho_discount and _percent_to_decimal(haho_discount.group(2)))
        or (holz_junge_discount and _percent_to_decimal(holz_junge_discount.group(2)))
        or tabular_terms.get("discount_percent"),
        "discount_base": _find_visible_discount_base(text),
        "discount_amount": discount_amount
        or (haho_discount and _money_to_decimal_signed(haho_discount.group(3)))
        or (holz_junge_discount and _money_to_decimal_signed(holz_junge_discount.group(3)))
        or tabular_terms.get("discount_amount"),
        "discount_net_amount": tabular_terms.get("discount_net_amount"),
        "discount_tax_amount": tabular_terms.get("discount_tax_amount"),
        "discount_gross_amount": tabular_terms.get("discount_gross_amount"),
        "discounted_payable_amount": discounted_payable_amount
        or tabular_terms.get("discounted_payable_amount"),
    }


def _find_tabular_discount_terms(text: str) -> dict[str, Decimal | str | None]:
    normalized = sub(r"\s+", " ", text).strip()
    if "Bei Zahlung bis" not in normalized or "Skonto brutto" not in normalized:
        return {}

    match = search(
        r"Bei Zahlung bis\s+Skonto\s*%\s+Skonto netto\s*(?:€|EUR)\s+Skonto MwSt\.?\s*(?:€|EUR)\s+"
        r"Skonto brutto\s*(?:€|EUR)\s+Zahlungsziel Netto bis\s+"
        r"(\d{2}\.\d{2}\.\d{4})\s+([0-9]+(?:,\d{1,2})?)\s+"
        r"([0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+(\d{2}\.\d{2}\.\d{4})",
        normalized,
    )
    if not match:
        match = search(
            r"Bei Zahlung bis\s+(\d{2}\.\d{2}\.\d{4})\s+Skonto\s*%\s+([0-9]+(?:,\d{1,2})?)\s+"
            r"Skonto netto\s*(?:€|EUR)?\s+([0-9.]+,\d{2})\s+Skonto MwSt\.?\s*(?:€|EUR)?\s+"
            r"([0-9.]+,\d{2})\s+Skonto brutto\s*(?:€|EUR)?\s+([0-9.]+,\d{2})\s+"
            r"Zahlungsziel Netto bis\s+(\d{2}\.\d{2}\.\d{4})",
            normalized,
        )
    if not match:
        return {}

    discount_due_date, percent_text, discount_net, discount_tax, discount_gross, due_date = match.groups()
    return {
        "discount_due_date": _date_text_to_iso(discount_due_date),
        "due_date": _date_text_to_iso(due_date),
        "discount_percent": _percent_to_decimal(percent_text),
        "discount_net_amount": _money_to_decimal(discount_net),
        "discount_tax_amount": _money_to_decimal(discount_tax),
        "discount_gross_amount": _money_to_decimal(discount_gross),
        "discount_amount": _money_to_decimal(discount_gross),
        "discounted_payable_amount": None,
    }


def _payment_terms(
    *,
    gross_amount: Decimal | None,
    due_date: str | None,
    discount_due_date: str | None,
    discount_base: Decimal | None,
    discount_percent: Decimal | None,
    discount_amount: Decimal | None,
    discounted_payable_amount: Decimal | None,
    is_credit_note: bool,
) -> list[dict[str, Decimal | str | None]]:
    terms = []
    gross_amount = _as_decimal(gross_amount)
    discount_amount = _signed_discount_amount(discount_amount, gross_amount)
    discounted_payable_amount = _as_decimal(discounted_payable_amount)

    if gross_amount is not None:
        terms.append(
            {
                "type": "full_amount",
                "label": "Gutschrift verrechnen" if is_credit_note else "Ohne Abzug zahlen",
                "due_date": due_date,
                "amount": gross_amount,
                "currency": "EUR",
            }
        )

    if discount_due_date and discount_amount is not None:
        if discounted_payable_amount is None and gross_amount is not None:
            discounted_payable_amount = (gross_amount - abs(discount_amount)).quantize(Decimal("0.01"))
        terms.append(
            {
                "type": "credit_note_settlement" if is_credit_note else "cash_discount",
                "label": "Verrechnung mit Skonto" if is_credit_note else "Skontozahlung",
                "due_date": discount_due_date,
                "amount": discounted_payable_amount,
                "discount_base": _as_decimal(discount_base),
                "discount_percent": _as_decimal(discount_percent),
                "discount_amount": discount_amount,
                "currency": "EUR",
            }
        )

    return terms


def _signed_discount_amount(discount_amount: Decimal | None, gross_amount: Decimal | None) -> Decimal | None:
    discount_amount = _as_decimal(discount_amount)
    gross_amount = _as_decimal(gross_amount)
    if discount_amount is None:
        return None
    if gross_amount is not None and gross_amount < 0:
        return -abs(discount_amount)
    return abs(discount_amount)


def _as_decimal(value: Decimal | str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _find_text(text: str, pattern: str) -> str | None:
    match = search(pattern, text, MULTILINE)
    return match.group(1).strip() if match else None


def _find_date(text: str, pattern: str) -> str | None:
    value = _find_text(text, pattern)
    if not value:
        return None
    return _date_text_to_iso(value)


def _date_text_to_iso(value: str) -> str:
    day, month, year = value.split(".")
    if len(year) == 2:
        year = f"20{year}"
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def _find_rieprecht_invoice_number(text: str) -> str | None:
    match = search(r"R\s*e\s*c\s*h\s*n\s*u\s*n\s*g\s+N\s*r\s*\.\s*((?:\d\s*){7,})", text)
    if not match:
        return None
    return sub(r"\s+", "", match.group(1))


def _find_rieprecht_invoice_date(text: str) -> str | None:
    return _find_date(
        text,
        r"Rg\.-Datum\s+Kunden-Nr\.[^\n]*\n\s*(\d{2}\.\d{2}\.\d{4})\s+[0-9]{5}\b",
    )


def _invoice_number_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem.lower()
    match = search(r"(?:rechnung|erg|rg)[ _-]*([0-9]{6,})", stem, flags=0)
    if match:
        return match.group(1)
    match = search(r"\b([0-9]{5,}-[0-9]{2,})\b", stem)
    if match:
        return match.group(1)
    match = search(r"\b([0-9]{8,})\b", stem)
    return match.group(1) if match else None


def _invoice_date_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    return _find_date(stem, r"(\d{2}\.\d{2}\.\d{4})") or _find_iso_date(stem)


def _find_iso_date(text: str) -> str | None:
    match = search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def _find_roennfeld_due_date(text: str) -> str | None:
    match = search(
        r"Zahlen Sie bitte bis zum\s+(\d{1,2})\.\s+([A-Za-zÄÖÜäöüß]+)\s+(\d{4})\s*ohne Abzug",
        text,
    )
    if not match:
        return None
    month = {
        "januar": "01",
        "februar": "02",
        "märz": "03",
        "maerz": "03",
        "april": "04",
        "mai": "05",
        "juni": "06",
        "juli": "07",
        "august": "08",
        "september": "09",
        "oktober": "10",
        "november": "11",
        "dezember": "12",
    }.get(match.group(2).lower())
    if not month:
        return None
    return f"{match.group(3)}-{month}-{match.group(1).zfill(2)}"


def _find_money_after_label(text: str, label: str) -> Decimal | None:
    pattern = rf"{label}[^\n]*?([0-9.]+,\d{{2}})"
    return _find_money(text, pattern)


def _find_customer_number(text: str) -> str | None:
    return (
        _find_text(text, r"Rg\.-Datum\s+Kunden-Nr\.[^\n]*\n\s*\d{2}\.\d{2}\.\d{4}\s+([0-9]{5})\b")
        or _find_text(text, r"Kunden-Nr\.?\s+Auftraggeber\s*:?\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kunden\s*-?\s*Nr\.?\s*:?\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kunden-Nr\.\s*:\s*\n\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kunden-Steuer-ID\s*:?\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Ihre Kundennummer Unser Vorgang Datum\s*(Q[0-9]+)")
        or _find_text(text, r"Kunde:\s*(Q[0-9]+)Rechnung:")
        or _find_text(text, r"([0-9]{6,})\s*Kundennummer:")
        or _find_text(text, r"\n\s*([0-9]{6,})\s*\n\s*\d{2}\.\d{2}\.\d{4}\s*\n\s*(?:GS|RE)\d{6,}")
        or _find_text(text, r"Kunden-Nr\.?:\s*([A-Z0-9-]+?)(?=Auftrag|Lieferschein|Rechnung|\s|$)")
        or _find_text(text, r"\bKunde:\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kundennummer:\s*([A-Z0-9][A-Z0-9/.-]*)")
        or _find_text(text, r"Kunden\s+Nr\.:\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kunden-Nr\.\s*\.\s*:\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Rechnungs-Nr\.\s+Kunden-Nr\.\s+Rg\.-/Liefer-Datum\s+Auftrags-Nr\..*?\n\s*[^\n]+\n\s*[0-9]{6,}\s+([0-9]{6,})\s+\d{2}\.\d{2}\.\d{4}")
        or _find_text(text, r"KD-Nr\.\s+Rechn\.Nr\.\s+Datum\s+Blatt\s*\n\s*480\s+(FRHA05)\s+[0-9]{6,}\s+\d{2}\.\d{2}\.\d{4}")
        or _find_text(text, r"Kundennummer\s*\n\s*Kundenreferenz\s*\n\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kunden-Nr\.\s*:?\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kundennr\.?\s*:?\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"KundenNr\.\s*\.\s*\.\s*:\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"Kundennummer\s*:?\s*([0-9][0-9/.-]*)")
        or _find_text(text, r"\d{2}\.\d{2}\.\d{4}\s*([0-9]{4,})\s*Kunden\s+Nummer")
        or _find_text(
            text,
            r"Kundennummer:\s*\n\s*[A-Z]{1,5}\d+\s*\n\s*\d{2}\.\d{2}\.\d{4}\s*\n\s*([0-9][0-9/.-]*)",
        )
    )


def _find_invoice_totals(text: str) -> dict[str, Decimal | None]:
    rieprecht_total = search(
        r"Nettobetrag\s*€\s*([0-9.]+,\d{2})[\s\S]*?"
        r"Mwst\.\s*gesamt\s*€\s*([0-9.]+,\d{2})[\s\S]*?"
        r"Zahlbetrag\s*€\s*([0-9.]+,\d{2})",
        text,
    )
    if rieprecht_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(rieprecht_total.group(1)),
            "tax_amount": _money_to_decimal(rieprecht_total.group(2)),
            "gross_amount": _money_to_decimal(rieprecht_total.group(3)),
        }
    roennfeld_total = search(
        r"Gesamtbetrag\s*(-?[0-9.]+,\d{2})\s*€\s*zuzüglich MwSt\.\s*0\s*%\s*Endbetrag\s*(-?[0-9.]+,\d{2})",
        text,
    )
    if roennfeld_total:
        gross_amount = _money_to_decimal_signed(roennfeld_total.group(2))
        return {
            "discount_base": None,
            "net_amount": gross_amount,
            "tax_amount": Decimal("0.00"),
            "gross_amount": gross_amount,
        }
    eindruck24_total = search(
        r"Gesamt Netto\s*\(19,00\s*%\)\s*([0-9.]+,\d{2})\s*.*?"
        r"zzgl\.\s*MwSt\s*\(19,00\s*%\)\s*([0-9.]+,\d{2})\s*.*?"
        r"Rechnungsbetrag\s*([0-9.]+,\d{2})",
        text,
    )
    if eindruck24_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(eindruck24_total.group(1)),
            "tax_amount": _money_to_decimal(eindruck24_total.group(2)),
            "gross_amount": _money_to_decimal(eindruck24_total.group(3)),
        }
    ibe_total = search(
        r"Nettobetrag\s+0\s*%\s+([0-9.]+,\d{2})\s*€?[\s\S]*?"
        r"Nettobetrag\s+19\s*%\s+([0-9.]+,\d{2})\s*€?[\s\S]*?"
        r"Mehrwertsteuer\s+19\s*%\s+([0-9.]+,\d{2})\s*€?[\s\S]*?"
        r"Rechnungsbetrag\s+([0-9.]+,\d{2})\s*€?",
        text,
    )
    if ibe_total:
        net_amount = _money_to_decimal(ibe_total.group(1)) + _money_to_decimal(ibe_total.group(2))
        return {
            "discount_base": None,
            "net_amount": net_amount.quantize(Decimal("0.01")),
            "tax_amount": _money_to_decimal(ibe_total.group(3)),
            "gross_amount": _money_to_decimal(ibe_total.group(4)),
        }
    mittwald_total = search(
        r"Zwischensumme\s+Netto[\s\S]*?"
        r"Zzgl\.\s+19\s*%\s+USt\.[^\n]*?\s+auf\s+([0-9.]+,\d{2})\s+EUR[\s\S]*?"
        r"\n\s*([0-9.]+,\d{2})\s+EUR\s*\n\s*([0-9.]+,\d{2})\s+EUR[\s\S]*?"
        r"Gesamtbetrag\s+([0-9.]+,\d{2})\s+EUR",
        text,
    )
    if mittwald_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(mittwald_total.group(2)),
            "tax_amount": _money_to_decimal(mittwald_total.group(3)),
            "gross_amount": _money_to_decimal(mittwald_total.group(4)),
        }
    konzept54_total = search(
        r"Nettosumme\s+([0-9.]+,\d{2})\s*Umsatzsteuer\s+19\s*%\s+([0-9.]+,\d{2})[\s\S]*?"
        r"Gesamtsumme\s+([0-9.]+,\d{2})",
        text,
    )
    if konzept54_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(konzept54_total.group(1)),
            "tax_amount": _money_to_decimal(konzept54_total.group(2)),
            "gross_amount": _money_to_decimal(konzept54_total.group(3)),
        }
    europlanen_total = search(
        r"Leistungswert netto\s+([0-9.]+,\d{2})[\s\S]*?"
        r"MwSt\s+19%\s+([0-9.]+,\d{2})[\s\S]*?"
        r"Gesamtleistung brutto\s+([0-9.]+,\d{2})",
        text,
    )
    if europlanen_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(europlanen_total.group(1)),
            "tax_amount": _money_to_decimal(europlanen_total.group(2)),
            "gross_amount": _money_to_decimal(europlanen_total.group(3)),
        }
    boehm_total = search(r"Nettosumme\s+([0-9.]+,\d{2})\s*€", text)
    if boehm_total and ("maler-boehm.de" in text.lower() or "malereibetrieb" in text.lower()):
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(boehm_total.group(1)),
            "tax_amount": None,
            "gross_amount": None,
        }
    af_elektro_total = search(r"Gesamtbetrag\s+([0-9.]+,\d{2})\s*€[\s\S]*?§13b", text)
    if af_elektro_total:
        gross_amount = _money_to_decimal(af_elektro_total.group(1))
        return {
            "discount_base": gross_amount,
            "net_amount": gross_amount,
            "tax_amount": Decimal("0.00"),
            "gross_amount": gross_amount,
        }
    roggemann_total = search(
        r"Netto-Betrag EUR\s+([0-9.]+,\d{2}-?)[\s\S]*?"
        r"19,00\s*%\s*MWSt EUR\s+([0-9.]+,\d{2}-?)[\s\S]*?"
        r"Gesamtbetrag EUR\s+([0-9.]+,\d{2}-?)",
        text,
    )
    if roggemann_total:
        return {
            "discount_base": _money_to_decimal_with_trailing_minus(roggemann_total.group(1)),
            "net_amount": _money_to_decimal_with_trailing_minus(roggemann_total.group(1)),
            "tax_amount": _money_to_decimal_with_trailing_minus(roggemann_total.group(2)),
            "gross_amount": _money_to_decimal_with_trailing_minus(roggemann_total.group(3)),
        }
    bueroshop_total = search(
        r"Zahlartgeb(?:ühr|Ã¼hr)\s+Warenwert\s+Netto\s+Gesamt-Netto\s+USt\.-Betrag\s+%\s+USt\.\s+Rg\.-Betrag\s+EUR[\s\S]*?"
        r"(?:Zahlbar bis\s+)?[0-9.]+,\d{2}\s+([0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+19\s+([0-9.]+,\d{2})",
        text,
    )
    if bueroshop_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(bueroshop_total.group(1)),
            "tax_amount": _money_to_decimal(bueroshop_total.group(2)),
            "gross_amount": _money_to_decimal(bueroshop_total.group(3)),
        }
    arens_stitz_total = search(
        r"Warenwert\s*:\s*([0-9.]+,\d{2})\s+EUR[\s\S]*?"
        r"19,00%MWST:\s*([0-9.]+,\d{2})\s+EUR[\s\S]*?"
        r"Skontof[Ã¤ä]higer Betrag\s*:\s*([0-9.]+,\d{2})[\s\S]*?"
        r"Gesamt:\s*([0-9.]+,\d{2})\s+EUR",
        text,
    )
    if arens_stitz_total:
        return {
            "discount_base": _money_to_decimal(arens_stitz_total.group(3)),
            "net_amount": _money_to_decimal(arens_stitz_total.group(1)),
            "tax_amount": _money_to_decimal(arens_stitz_total.group(2)),
            "gross_amount": _money_to_decimal(arens_stitz_total.group(4)),
        }
    pietsch_total = search(
        r"Gesamtwert\s+([0-9.]+,\d{2}-?)\s+EUR[\s\S]*?"
        r"Umsatzsteuer\s+19,00\s*%\s+auf\s+[0-9.]+,\d{2}-?\s+([0-9.]+,\d{2}-?)\s+EUR[\s\S]*?"
        r"Endbetrag\s+([0-9.]+,\d{2}-?)\s+EUR[\s\S]*?"
        r"skontierf[Ã¤ä]higen Betrag\s*\(\s*([0-9.]+,\d{2}-?)\s+EUR\s*\)",
        text,
    )
    if pietsch_total:
        return {
            "discount_base": _money_to_decimal_with_trailing_minus(pietsch_total.group(4)),
            "net_amount": _money_to_decimal_with_trailing_minus(pietsch_total.group(1)),
            "tax_amount": _money_to_decimal_with_trailing_minus(pietsch_total.group(2)),
            "gross_amount": _money_to_decimal_with_trailing_minus(pietsch_total.group(3)),
        }
    dammers_total = search(
        r"Summe\s+Warenwert\s+EUR\s+([0-9.]+,\d{2})[\s\S]*?"
        r"\+\s*19,00\s*%\s*Mwst\.\s+EUR\s+([0-9.]+,\d{2})[\s\S]*?"
        r"Rechnungsbetrag.*?EUR\s+([0-9.]+,\d{2})",
        text,
    )
    if dammers_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(dammers_total.group(1)),
            "tax_amount": _money_to_decimal(dammers_total.group(2)),
            "gross_amount": _money_to_decimal(dammers_total.group(3)),
        }
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
    luechau_credit_total = search(
        r"Brutto-Betrag:MwSt\.-Betrag:Netto-Betrag:\s*"
        r"(-?[0-9.]+,\d{2})(-?[0-9.]+,\d{2})(-?[0-9.]+,\d{2})\s*19%\s*MwSt\.:",
        text,
    )
    if luechau_credit_total:
        return {
            "discount_base": _find_visible_discount_base(text),
            "net_amount": _money_to_decimal_signed(luechau_credit_total.group(3)),
            "tax_amount": _money_to_decimal_signed(luechau_credit_total.group(2)),
            "gross_amount": _money_to_decimal_signed(luechau_credit_total.group(1)),
        }
    haho_total = search(
        r"Netto-Betrag\s+EUR\s+([0-9.]+,\d{2})[\s\S]*?"
        r"19,00\s*%\s*Mwst\s+EUR\s+([0-9.]+,\d{2})[\s\S]*?"
        r"Rechnungsbetrag\s+EUR\s+([0-9.]+,\d{2})",
        text,
    )
    if haho_total:
        return {
            "discount_base": None,
            "net_amount": _money_to_decimal(haho_total.group(1)),
            "tax_amount": _money_to_decimal(haho_total.group(2)),
            "gross_amount": _money_to_decimal(haho_total.group(3)),
        }
    holz_junge_signed_total = search(
        r"skontof\S*higer Betrag\s+Netto\s+MwSt-%\s+MwSt\s+Endbetrag EUR\s*\n\s*"
        r"(-?[0-9.]+,\d{2})\s+(-?[0-9.]+,\d{2})\s+([0-9.]+,\d{2})\s+(-?[0-9.]+,\d{2})\s+(-?[0-9.]+,\d{2})",
        text,
    )
    if holz_junge_signed_total:
        return {
            "discount_base": _money_to_decimal_signed(holz_junge_signed_total.group(1)),
            "net_amount": _money_to_decimal_signed(holz_junge_signed_total.group(2)),
            "tax_amount": _money_to_decimal_signed(holz_junge_signed_total.group(4)),
            "gross_amount": _money_to_decimal_signed(holz_junge_signed_total.group(5)),
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


def _find_dammers_due_date(text: str) -> str | None:
    return _find_date(text, r"zahlbar bis\s+sp\S{1,8}testens\s+(\d{2}\.\d{2}\.\d{2})")


def _find_dammers_discount_due_date(text: str) -> str | None:
    return _find_date(
        text,
        r"zahlbar bis zum\s+(\d{2}\.\d{2}\.\d{2})\s+abz\S{1,8}glich\s+EUR\s+[0-9.]+,\d{2}\s+Skonto",
    )


def _find_dammers_discount_amount(text: str) -> Decimal | None:
    return _find_money(text, r"abz\S{1,8}glich\s+EUR\s+([0-9.]+,\d{2})\s+Skonto")


def _find_pietsch_discount_terms(text: str) -> dict[str, Decimal | str | None]:
    match = search(
        r"Zahlbetrag bis\s+(\d{2}\.\d{2}\.\d{4})\s+([0-9]+(?:,\d{1,3})?)\s*%\s+Skonto\s+([0-9.]+,\d{2}-?)\s+EUR[\s\S]*?"
        r"Zahlbetrag bis\s+(\d{2}\.\d{2}\.\d{4})\s+ohne Abzug\s+([0-9.]+,\d{2}-?)\s+EUR",
        text,
    )
    if not match:
        return {}
    discount_due, percent_text, discounted_payable, due_date, gross_text = match.groups()
    gross_amount = _money_to_decimal_with_trailing_minus(gross_text)
    discounted_payable_amount = _money_to_decimal_with_trailing_minus(discounted_payable)
    discount_amount = abs(gross_amount - discounted_payable_amount).quantize(Decimal("0.01"))
    return {
        "discount_due_date": _date_text_to_iso(discount_due),
        "due_date": _date_text_to_iso(due_date),
        "discount_percent": _percent_to_decimal(percent_text),
        "discount_base": None,
        "discount_amount": discount_amount,
        "discounted_payable_amount": discounted_payable_amount,
    }


def _find_roggemann_discount_terms(text: str) -> dict[str, Decimal | str | None]:
    match = search(
        r"bis\s+(\d{1,2}\.\d{2}\.\d{2})\s+mit\s+([0-9]+(?:,\d{1,2})?)\s*%\s+Skonto\s*=\s*([0-9.]+,\d{2}-?)\s+EUR[\s\S]*?"
        r"bis\s+(\d{1,2}\.\d{2}\.\d{2})\s+netto\s*=\s*([0-9.]+,\d{2}-?)\s+EUR",
        text,
    )
    if not match:
        return {}
    discount_due, percent_text, discounted_payable, due_date, gross_text = match.groups()
    gross_amount = _money_to_decimal_with_trailing_minus(gross_text)
    discounted_payable_amount = _money_to_decimal_with_trailing_minus(discounted_payable)
    discount_amount = abs(gross_amount - discounted_payable_amount).quantize(Decimal("0.01"))
    return {
        "discount_due_date": _date_text_to_iso(discount_due),
        "due_date": _date_text_to_iso(due_date),
        "discount_percent": _percent_to_decimal(percent_text),
        "discount_base": None,
        "discount_amount": discount_amount,
        "discounted_payable_amount": discounted_payable_amount,
    }


def _find_af_elektro_payment_terms(text: str, invoice_date: str | None) -> dict[str, Decimal | str | None]:
    due_date = _find_date(text, r"bis zum\s+(\d{2}\.\d{2}\.\d{4}),\s+ohne Skontoabzug")
    percent_text = _find_text(text, r"([0-9]+(?:,\d{1,2})?)\s*%\s+Skonto")
    discount_days = _find_text(text, r"innerhalb von\s+(\d+)\s+Tagen")
    due_days = _find_text(text, r"Zahlbar binnen\s+(\d+)\s+Tagen")
    discount_due_date = _discount_due_date_from_days(invoice_date, int(discount_days)) if invoice_date and discount_days else None
    calculated_due_date = _discount_due_date_from_days(invoice_date, int(due_days)) if invoice_date and due_days else None
    return {
        "due_date": due_date or calculated_due_date,
        "discount_due_date": discount_due_date,
        "discount_percent": _percent_to_decimal(percent_text) if percent_text else None,
        "discount_base": None,
        "discount_amount": None,
        "discounted_payable_amount": None,
    }


def _find_bueroshop_due_date(text: str) -> str | None:
    return _find_date(text, r"Rg\.-Betrag EUR\s*\n\s*Zahlbar bis[\s\S]*?\b(\d{2}\.\d{2}\.\d{4})")


def _discount_due_date_from_days(invoice_date: str | None, days: int | None) -> str | None:
    if not invoice_date or days is None:
        return None
    return (datetime.fromisoformat(invoice_date).date() + timedelta(days=days)).isoformat()


def _money_to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", ".")).quantize(Decimal("0.01"))


def _money_to_decimal_signed(value: str) -> Decimal:
    stripped = value.strip()
    sign = Decimal("-1") if stripped.startswith("-") or stripped.endswith("-") else Decimal("1")
    stripped = stripped.strip("-")
    return (_money_to_decimal(stripped) * sign).quantize(Decimal("0.01"))


def _money_to_decimal_with_trailing_minus(value: str) -> Decimal:
    stripped = value.strip()
    sign = Decimal("-1") if stripped.endswith("-") else Decimal("1")
    stripped = stripped.rstrip("-")
    return (_money_to_decimal(stripped) * sign).quantize(Decimal("0.01"))


def _percent_to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", ".")).quantize(Decimal("0.01"))


def _find_delivery_address(text: str) -> str | None:
    match = search(r"Lieferanschrift:\s*(.+?)\s*\n\s*(\d{5}\s+[^\n]+)", text)
    if not match:
        addresses = _find_delivery_addresses(text)
        return addresses[0] if addresses else None
    return f"{match.group(1).strip()}, {match.group(2).strip()}"


def _find_delivery_addresses(text: str) -> list[str]:
    addresses = []
    for match in finditer(r"^\s*f[üu]r\s+([^\n,]+?\d+[A-Za-z]?,\s*[^\n]+)", text, MULTILINE):
        addresses.append(_normalize_inline_address(match.group(1).strip()))
    for match in finditer(r"Bauvorhaben:\s*([^\n]*?\d+[A-Za-z]?,\s*\d{5}\s+[^\n]+)", text):
        addresses.append(_normalize_inline_address(match.group(1).strip()))
    af_address = search(r"Bauvorhab(?:en|em):\s*(.+?)\s*\n\s*FriStD-Bau", text)
    if af_address:
        addresses.append(_normalize_inline_address(af_address.group(1).strip()))
    for match in finditer(
        r"An:\s*(.+?),\s*([^\n]*?\d+[^\n]*)\s*\n\s*(\d{5}\s+[^\n]+)",
        text,
    ):
        recipient, street, city = (part.strip() for part in match.groups())
        addresses.append(f"{recipient}, {street}, {city}")
    for match in finditer(
        r"(?:Anlieferung|Abholung)\s*(?:\.\s*)+:\s*(?:\n\s*(?:[0-9/+\- ]+|Baustelle))?\n\s*([^\n]*?\d+[^\n]*?)\s+(?:D\s+)?(\d{5})\s+([^\n]+)",
        text,
    ):
        street, postal_code, city = (part.strip() for part in match.groups())
        addresses.append(f"{street}, {postal_code} {city}")
    return list(dict.fromkeys(addresses))


def _normalize_inline_address(value: str) -> str:
    cleaned = sub(r"\s+", " ", value).strip()
    match = search(r"(.+?\d+[A-Za-zÄÖÜäöüß]?)\s*(\d{5})\s+(.+)$", cleaned)
    if match:
        street, postal_code, city = (part.strip() for part in match.groups())
        return f"{street}, {postal_code} {city}"
    return cleaned


def _find_customer_reference(text: str) -> str | None:
    match = search(r"AUFTR\.TEXT:\s*(.+?)(?:\n|$)", text) or search(
        r"Ihre Kommission:\s*(.+?)(?:\n|$)", text
    ) or search(
        r"Kommissionsangaben:\s*(.+?)(?:\n|$)", text
    ) or search(
        r"Bestelldaten:\s*(.+?)(?:\n|$)", text
    ) or search(
        r"Objekt:\s*(.+?)(?:\n|$)", text
    ) or search(
        r"(?:Ihre Referenz:.*?,\s*)?Auftrag:\s*([0-9]{2}-[0-9]{5})\b", text
    ) or search(
        r"Kundennummer\s*\n\s*Kundenreferenz\s*\n\s*[0-9][0-9/.-]*\s*\n\s*([^\n]+)",
        text,
    ) or search(
        r"Kundenreferenz\s*:?\s*(?:\n\s*)?(.+?)(?=\s+(?:Kundennummer|Kunden-Nr\.?|Auftragsnummer|"
        r"Artikel|Rechnungsbetrag|MwSt|Lieferanschrift|Sachbearbeiter)\b|\n|$)",
        text,
    )
    if not match:
        return None
    value = match.group(1).strip(" :-\t")
    return value or None


def _find_reference_delivery_address(text: str) -> str | None:
    match = search(
        r"(?:Bestelldaten|Kundenreferenz|Kommissionsangaben)\s*:?\s*\n?\s*"
        r"([^\n]*?\d+[A-Za-zÄÖÜäöüß]?)\s*\n\s*(\d{5}\s+[^\n]+)",
        text,
    )
    if not match:
        return None
    return _normalize_inline_address(f"{match.group(1).strip()} {match.group(2).strip()}")


def _find_assignment_hint_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    return _find_text(stem, r"\bBV\s+([^,]+)") or _find_text(
        stem,
        r"\b(?:Bauvorhaben|Projekt)\s+([^,]+)",
    )


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
                "assignment_code": _assignment_code(assignment),
                "assignment_label": assignment["label"] if assignment else None,
                "assignment_kind": assignment["kind"] if assignment else None,
                "project_number": _project_number(assignment),
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


def _compact_search_text(value: str) -> str:
    return sub(r"[^a-z0-9äöüß]+", "", value.lower())


def _supplier_name(document: dict, text: str) -> str:
    original = document["original_filename"].lower()
    lower_text = text.lower()
    compact_text = _compact_search_text(" ".join([document["original_filename"], text]))
    dammers_filename = _dammers_invoice_from_filename(document["original_filename"])
    if "frha05" in lower_text and "gc-gruppe.de" in lower_text:
        return "Arens & Stitz KG"
    if "rieprecht-gmbh.de" in lower_text or "rieprecht gmbh" in lower_text:
        return "Rieprecht GmbH"
    if "konzept-54.de" in lower_text or "konzept 54 gmbh" in lower_text:
        return "konzept 54 GmbH & Co.KG"
    if "euro planen handel und service gmbh" in lower_text:
        return "Euro Planen Handel und Service GmbH"
    if "af-elektro gmbh" in lower_text and "info@af-elektro.de" in lower_text:
        return "AF-Elektro GmbH"
    if "a. franz elektrotechnik" in lower_text and "info@af-elektro.de" in lower_text:
        return "A. Franz Elektrotechnik"
    if "böhm" in original or "boehm" in original or "böhmmalereibetrieb" in compact_text or "malerlböhm" in compact_text:
        return "Böhm Malereibetrieb GmbH"
    if "eindruck24" in lower_text and "buchhaltung@eindruck24.de" in lower_text:
        return "Eindruck24"
    if "mittwald cm service" in lower_text or "info@mittwald.de" in lower_text:
        return "Mittwald CM Service GmbH & Co. KG"
    if "institut für betriebliches entgeltmanagement gmbh" in lower_text or (
        "primecard" in lower_text and "marienstr. 14-16" in lower_text
    ):
        return "I.B.E. Institut für betriebliches Entgeltmanagement GmbH"
    if "roggemann.de" in lower_text and "enno roggemann gmbh" in lower_text:
        return "Enno Roggemann GmbH & Co. KG"
    if "bueroshop24.de" in lower_text or "büroshop24 gmbh" in lower_text:
        return "büroshop24 GmbH"
    if "pietsch hamburg-ost damaschke" in lower_text:
        return "Pietsch Hamburg-Ost Damaschke GmbH & Co. KG"
    if "auslieferungslager" in lower_text and "barmbek" in lower_text and "0515834/086" in text:
        return "Rolf Dammers oHG"
    if "roennfeld-rollladenbau.de" in lower_text or "rönnfeld" in lower_text:
        return "Rönnfeld ROLLLADEN UND MARKISEN GmbH"
    if dammers_filename and (
        "0515834" in text
        or "cobadach" in compact_text
        or "allesf" in compact_text
        or "auslieferungslager" in lower_text
    ):
        return "Rolf Dammers oHG"
    if (
        ("dammers" in compact_text and ("allesf" in compact_text or "dach" in compact_text))
        or ("cobadach" in compact_text and "kundennr" in compact_text)
    ):
        return "Rolf Dammers oHG"
    if "kundennr" in lower_text and "reisender" in lower_text and "btr nl" in lower_text:
        return "HaHo Holz"
    if "foerch" in original or "foerch" in text.lower() or "f\u00f6rch" in text.lower():
        return "Theo Foerch GmbH & Co. KG"
    if any(name in lower_text for name in ["lüchau baustoffe gmbh", "lã¼chau baustoffe gmbh", "luechau baustoffe gmbh"]):
        return "Lüchau Baustoffe GmbH"
    if "lüchau baustoffe gmbh" in text.lower():
        return "Lüchau Baustoffe GmbH"
    if "rechnungar" in original and "0113042/504" in text:
        return "Georg Klindworth oHG"
    if "kreditrechnung" in original and ("holz junge" in lower_text or "fermacell" in lower_text):
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
    customer_reference: str | None,
    text: str,
) -> dict | None:
    match = _assignment_unit_match(tenant_id, delivery_address, customer_reference, text)
    return match["assignment"] if match else None


def _assignment_unit_match(
    tenant_id: str,
    delivery_address: str | None,
    customer_reference: str | None,
    text: str,
) -> dict | None:
    for explicit_hint in (customer_reference, delivery_address):
        match = _find_assignment_unit_match(tenant_id, explicit_hint)
        if match and match["assignment"]["is_active"]:
            match["source"] = "Kundenreferenz" if explicit_hint == customer_reference else "Lieferadresse"
            return match
    match = _find_assignment_unit_match(tenant_id, text[:4000])
    if match:
        match["source"] = "Belegtext"
    return match


def _find_assignment_unit_match(tenant_id: str, lookup_text: str | None) -> dict | None:
    if not lookup_text:
        return None
    match = find_assignment_unit_match_by_text(tenant_id, lookup_text)
    if match:
        return match
    assignment = find_assignment_unit_by_text(tenant_id, lookup_text)
    if not assignment:
        return None
    return {"assignment": assignment, "score": None, "reasons": []}


def _assignment_match_payload(match: dict | None) -> dict | None:
    if not match:
        return None
    assignment = match.get("assignment") or {}
    return {
        "code": _assignment_code(assignment),
        "label": assignment.get("label"),
        "project_number": assignment.get("project_number"),
        "score": match.get("score"),
        "source": match.get("source"),
        "reasons": match.get("reasons") or [],
    }


def _legacy_project_code(assignment: dict | None) -> str | None:
    if assignment and assignment["kind"] == "construction_project":
        return _assignment_code(assignment)
    return None


def _assignment_code(assignment: dict | None) -> str | None:
    if not assignment:
        return None
    code = assignment.get("code")
    label = assignment.get("label")
    if code and _looks_like_project_number(code) and label and not _looks_like_project_number(label):
        return label
    return code


def _looks_like_project_number(value: str | None) -> bool:
    return bool(value and search(r"^\d{2,4}-\d{3,}$", value.strip()))


def _project_number(assignment: dict | None) -> str | None:
    if assignment and assignment.get("kind") in {"construction_project", "construction_or_dropoff_site"}:
        return assignment.get("project_number")
    return None


def _assignment_type(delivery_address: str | None, assignment: dict | None) -> str:
    if assignment:
        return "assigned"
    if delivery_address:
        return "assignment_unresolved"
    return "general_cost"


def _cost_category_for_supplier_rule(
    supplier_rule: dict | None,
    supplier_name: str | None,
    product_name: str | None,
    text: str,
    assignment_type: str,
) -> str | None:
    detected = _cost_category(supplier_name, product_name, text, assignment_type)
    allowed_categories = _split_cost_categories(supplier_rule.get("default_cost_category") if supplier_rule else None)
    if not allowed_categories:
        return detected
    if len(allowed_categories) == 1:
        return allowed_categories[0]
    if detected in allowed_categories:
        return detected
    return None


def _split_cost_categories(value: str | list[str] | None) -> list[str]:
    return list(
        dict.fromkeys(
            item
            for item in split_cost_category_values(value)
            if item in VALID_COST_CATEGORIES
        )
    )


def _cost_category(
    supplier_name: str | None,
    product_name: str | None,
    text: str,
    assignment_type: str,
) -> str:
    haystack = " ".join([supplier_name or "", product_name or "", text[:3000]]).lower()
    if any(term in haystack for term in ["rieprecht", "baumisch", "boden ohne analyse", "gestellung container", "container abholung"]):
        return "subcontractor"
    if any(term in haystack for term in ["wärmepumpen-support", "waermepumpen-support", "kundendienst"]):
        return "subcontractor"
    if any(term in haystack for term in ["böhm malereibetrieb", "boehm malereibetrieb", "maler l. böhm", "maler l. boehm"]):
        return "subcontractor"
    if any(term in haystack for term in ["rönnfeld", "roennfeld", "rollladen", "raffstore", "markisen", "sonnenschutz"]):
        return "subcontractor"
    if any(term in haystack for term in ["af-elektro", "a. franz elektrotechnik", "elektroinstallation", "heizkreisverteiler"]):
        return "subcontractor"
    if any(term in haystack for term in ["eindruck24", "druck bis", "sparker", "flex medium"]):
        return "general_overhead"
    if "datev" in haystack:
        return "software_subscription"
    if any(term in haystack for term in ["mittwald", "webhosting", "zusätzliche domains", "zusaetzliche domains", "domain:"]):
        return "software_subscription"
    if any(term in haystack for term in ["primecard", "institut für betriebliches entgeltmanagement", "institut fuer betriebliches entgeltmanagement"]):
        return "general_overhead"
    if any(term in haystack for term in ["maison gebäudeservice", "maison gebaeudeservice", "allgemeine reinigungsarbeiten"]):
        return "general_overhead"
    if any(term in haystack for term in ["euro planen", "industrieplane", "versand per paketdienst"]):
        return "material"
    if any(term in haystack for term in ["roggemann", "cape cod", "floorentino", "fasebretter", "glattkantbretter"]):
        return "material"
    if any(term in haystack for term in ["büroshop24", "bueroshop24", "epson tinte", "kleinmengenzuschlag"]):
        return "general_overhead"
    if any(term in haystack for term in ["arens & stitz", "profipress", "trinnity", "cosmo standard stellantrieb", "push-open"]):
        return "material"
    if any(term in haystack for term in ["pietsch", "profipress", "kupferrohr", "sanpress", "gewindeschneidkluppe"]):
        return "material"
    if any(term in haystack for term in ["rolf dammers", "dachtraufprofil", "alu-stossverbinder", "alu-stoßverbinder"]):
        return "material"
    if any(term in haystack for term in ["lüchau", "lã¼chau", "baustoffe", "abdeckvlies", "artikel", "material"]):
        return "material"
    if any(term in haystack for term in ["maler", "elektro", "sanitär", "subunternehmer", "fremdleistung"]):
        return "subcontractor"
    if any(term in haystack for term in ["hobotec", "fermacell", "schalung", "gipsfaserplatte", "artikel", "material"]):
        return "material"
    if assignment_type in {"assigned", "assignment_split", "assignment_unresolved", "project", "project_split", "project_unresolved"}:
        return "material"
    if any(term in haystack for term in ["tank", "diesel", "benzin", "kraftstoff", "shell", "aral"]):
        return "fuel_vehicle"
    if any(term in haystack for term in ["software", "lizenz", "microsoft", "adobe", "cloud", "hosting", "saas"]):
        return "software_subscription"
    if any(term in haystack for term in ["kamera", "camera", "überwachung", "überwachung", "security"]):
        return "security_subscription"
    return "general_overhead"


def _clean_product_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = sub(r"\s+", " ", value.replace("^", "")).strip()
    if cleaned.startswith("FERMACELL 10mm Gipsfaserplatte"):
        return "FERMACELL 10mm Gipsfaserplatte"
    if cleaned.startswith("Maler-Abdeckvlies 50qm"):
        return "Maler-Abdeckvlies 50qm"
    return cleaned[:80]


def _filename_product_name(value: str) -> str:
    cleaned = _clean_product_name(value) or "Eingangsrechnung"
    return cleaned.split(",", 1)[0].strip() or cleaned


def _find_first_position_product_name(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()]
    if "buchhaltung@eindruck24.de" in text.lower():
        product = _find_eindruck24_product_name(text)
        if product:
            return product
    if "primecard" in text.lower():
        product = _find_text(
            text,
            r"1\.\s+(Ladebetrag\s+PRIMECARD\s+-\s+.+?)\s+\d+\s+[0-9.]+,\d{2}\s*€\s+[0-9.]+,\d{2}\s*€\s+0\s*%",
        )
        if product:
            return product
    if "mittwald cm service" in text.lower() or "info@mittwald.de" in text.lower():
        product = _find_text(text, r"\n\s*(Zus[äÃ¤]tzliche Domains Preisstufe \d+)")
        if product:
            return product
    if "info@af-elektro.de" in text.lower():
        for index, line in enumerate(lines):
            if not line.startswith("Anzahl Bezeichnung"):
                continue
            for candidate in lines[index + 1 : index + 8]:
                if not candidate:
                    continue
                if candidate.startswith(("Summe", "Gesamtbetrag", "Rechnungs-Nr.")):
                    break
                if search(r"^\d+(?:,\d+)?\s+[0-9.]+,\d{2}\s*€\s+[0-9.]+,\d{2}\s*€\d+\s+\w+\.", candidate):
                    tail = sub(r"^\d+(?:,\d+)?\s+[0-9.]+,\d{2}\s*€\s+[0-9.]+,\d{2}\s*€\d+\s+\w+\.\s*", "", candidate).strip()
                    if tail:
                        return _clean_af_elektro_product_name(tail)
                    continue
                if search(r"[A-Za-zÄÖÜäöüß]", candidate):
                    return _clean_af_elektro_product_name(candidate)
    for index, line in enumerate(lines):
        if not (
            search(r"^\d{4}\s+\d{12,}\s+1(?:\s+\(\*\))?$", line)
            or search(r"^\d{12,}\s+1(?:\s+\(\*\))?$", line)
        ):
            continue
        for candidate in lines[index + 1 : index + 5]:
            if not candidate:
                continue
            if candidate.startswith(("ÜBERTRAG", "Summe Menge", "Brutto-Preis")):
                continue
            if search(r"[A-Za-zÄÖÜäöüß]", candidate):
                return candidate
    bueroshop_item = search(
        r"^\s*\d+\s+(?:\d+\s+)?\d+-\d+\s+\d+\s+(.+?)\s+[0-9.]+,\d{2}\s+[0-9.]+,\d{2}\s+\d\s*$",
        text,
        MULTILINE,
    )
    if bueroshop_item:
        return bueroshop_item.group(1).strip()
    pietsch_item_pattern = r"^\d+\s+\d{6,}\s+[-0-9,.]+\s+(?:ST|M|KG|LTR|PA|ROL|PKT)\s+[-0-9,.]+\s+\d+\s+[-0-9,.]+\s+EUR$"
    for index, line in enumerate(lines):
        if not search(pietsch_item_pattern, line):
            continue
        for candidate in lines[index + 1 : index + 4]:
            if not candidate or candidate.startswith("RGR:"):
                continue
            if search(r"[A-Za-zÄÖÜäöüß]", candidate):
                return candidate
    for index, line in enumerate(lines):
        if search(r"^\d{5,}\s+\d+,\d{2}\s+\w+\s+\d+,\d{2}\s+\w+\s+\d+,\d{2}$", line):
            for candidate in lines[index + 1 : index + 4]:
                if candidate and search(r"[A-Za-zÄÖÜäöüß]", candidate):
                    return candidate
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


def _find_eindruck24_product_name(text: str) -> str | None:
    normalized = sub(r"\s+", " ", text)
    match = search(
        r"RechnungPos\..*?G\.Preis netto1[0-9,.]+Stk(.+?)19,00\s*%",
        normalized,
    )
    if not match:
        return None
    value = match.group(1).strip()
    value = sub(r"^[A-Z0-9]{5,}?(?=[A-Z][a-zÃ¤Ã¶Ã¼ÃŸ])", "", value)
    if "Sparker" in value:
        value = value[value.index("Sparker") :]
    elif "Flex" in value:
        value = value[value.index("Flex") :]
    return value.strip()


def _clean_af_elektro_product_name(value: str) -> str:
    cleaned = value.lstrip("- ").strip()
    cleaned = sub(r"\s*-\s*Montage\b.*$", "", cleaned)
    cleaned = sub(r"\s*[A-Z]\.\s*[A-ZÄÖÜa-zäöüß]+:\d{2}\.\d{2}\.\d{4}.*$", "", cleaned)
    return cleaned.strip()


def _product_name(text: str) -> str:
    boehm_product = _find_text(text, r"BV\s+[^:\n]+:\s*([^\n]+?)(?:Rechnung|\d{2}\.\d{2}\.\d{4}|$)")
    if boehm_product and ("maler-boehm.de" in text.lower() or "malereibetrieb" in text.lower()):
        return _clean_product_name(boehm_product) or boehm_product
    roennfeld_product = search(r"(Raffstore Fassadensystem\s*-\s*[^0-9\n]+)", text)
    if roennfeld_product:
        return _clean_product_name(roennfeld_product.group(1))
    roennfeld_credit = _find_text(text, r"(anteilige Gutschrift zur Rechnung\s+R\d{2}-\d{5})")
    if roennfeld_credit:
        return roennfeld_credit
    if "PE-Folie 200 my" in text:
        return "PE-Folie 200 my / Baustoffe"
    if "Maler-Abdeckvlies 50qm" in text:
        return "Maler-Abdeckvlies 50qm"
    if "FERMACELL" in text and "10mm Gipsfaserplatte" in text:
        return "FERMACELL 10mm Gipsfaserplatte"
    lower_text = text.lower()
    if "konzept 54" in lower_text:
        if "technischer wärmepumpen-support" in lower_text:
            return "Technischer Wärmepumpen-Support"
        if "pumpen baugruppe hps" in lower_text:
            return "Pumpen Baugruppe HPS"
    if "euro planen handel und service" in lower_text:
        if "industrieplane 8x12" in lower_text and "industrieplane 8x10" in lower_text:
            return "Industrieplanen 8x12m + 8x10m"
        if "industrieplane" in lower_text:
            return "Industrieplane"
    if "rieprecht" in lower_text:
        if "baumisch" in lower_text:
            return "Baumisch Container"
        if "Gestellung Container" in text:
            return "Gestellung Container"
        if "Boden ohne Analyse" in text and "Plattemsand" in text:
            return "Boden/Plattemsand Container"
        if "Container Abholung" in text:
            return "Container Abholung"
    first_position = _find_first_position_product_name(text)
    if first_position:
        return _clean_product_name(first_position) or first_position
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
    return ", ".join(_filename_part(part) for part in parts) + ".pdf"


def _filename_part(value: str) -> str:
    cleaned = sub(r'[<>:"/\\|?*]+', " ", value)
    cleaned = sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "-"


def _filename_assignment_label(assignment: dict | None, assignment_type: str, tenant_profile: dict) -> str:
    if assignment:
        code = _assignment_code(assignment)
        prefix = tenant_profile.get("assignment_code_prefix")
        if prefix:
            return f"{prefix} {code}"
        return f"{tenant_profile['assignment_label_singular']} {code}"
    if assignment_type == "assignment_split":
        return f"{tenant_profile['assignment_label_plural']} aufgeteilt"
    if assignment_type == "assignment_unresolved":
        return f"{tenant_profile['assignment_label_singular']} ungeklärt"
    return "Allgemeine Kosten"


def _supplier_from_filename(filename_stem: str) -> str:
    cleaned = sub(r"[_-]+", " ", filename_stem).strip()
    if not cleaned:
        return "Unbekannter Lieferant"
    return cleaned[:80]


def _mock_gross_amount(size_bytes: int) -> Decimal:
    cents = max(100, size_bytes % 50000)
    return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))
