from typing import Literal


CostCategory = Literal[
    "material",
    "subcontractor",
    "disposal",
    "fuel_vehicle",
    "software_subscription",
    "security_subscription",
    "general_overhead",
]

VALID_COST_CATEGORIES: set[str] = {
    "material",
    "subcontractor",
    "disposal",
    "fuel_vehicle",
    "software_subscription",
    "security_subscription",
    "general_overhead",
}

COST_CATEGORY_LABELS = {
    "material": "Material",
    "subcontractor": "Fremdleistung",
    "disposal": "Entsorgung",
    "fuel_vehicle": "Fahrzeug/Tanken",
    "software_subscription": "Software/Abo",
    "security_subscription": "Überwachung/Abo",
    "general_overhead": "Sonstige Gemeinkosten",
    "payment_discount": "Skonto/Zahlungsdifferenz",
}


def split_cost_category_values(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = value.replace(";", ",").split(",")
    return [item.strip() for item in raw_values if item and item.strip()]


def invalid_cost_category_values(value: str | list[str] | None) -> list[str]:
    return [item for item in split_cost_category_values(value) if item not in VALID_COST_CATEGORIES]
