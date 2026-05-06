from pathlib import Path


def run_mock_extraction(original_filename: str) -> dict:
    stem = Path(original_filename).stem.replace("_", " ").replace("-", " ").strip()
    vendor = stem.title() if stem else "Unbekannter Rechnungssteller"

    return {
        "provider": "mock-extractor-v1",
        "status": "completed",
        "fields": {
            "vendor_name": vendor,
            "invoice_number": None,
            "invoice_date": None,
            "net_amount": None,
            "vat_amount": None,
            "gross_amount": None,
            "currency": "EUR",
        },
        "warnings": [
            "Mock-Extraktion: Werte muessen manuell geprueft werden.",
            "Noch keine echte OCR/E-Rechnungs-Auslesung aktiv.",
        ],
        "confidence": 0.25,
    }
