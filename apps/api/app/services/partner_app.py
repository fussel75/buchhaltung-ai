from ipaddress import ip_address
from json import JSONDecodeError, loads
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.config import Settings, get_settings


class PartnerAppConfigError(ValueError):
    pass


class PartnerAppFetchError(RuntimeError):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None


def fetch_partner_assignment_units(settings: Settings | None = None) -> list[dict[str, Any]]:
    resolved_settings = settings or get_settings()
    if not resolved_settings.partner_app_api_base_url:
        raise PartnerAppConfigError("PARTNER_APP_API_BASE_URL ist nicht konfiguriert.")
    if not resolved_settings.buha_api_key:
        raise PartnerAppConfigError("BUHA_API_KEY ist nicht konfiguriert.")

    _validate_partner_base_url(resolved_settings.partner_app_api_base_url)
    url = urljoin(resolved_settings.partner_app_api_base_url.rstrip("/") + "/", "api/buha/projects")
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "x-api-key": resolved_settings.buha_api_key,
        },
    )
    try:
        opener = build_opener(_NoRedirectHandler)
        with opener.open(request, timeout=20) as response:
            payload = loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise PartnerAppFetchError(f"Partner-App antwortet mit HTTP {error.code}.") from error
    except URLError as error:
        raise PartnerAppFetchError(f"Partner-App ist nicht erreichbar: {error.reason}") from error
    except TimeoutError as error:
        raise PartnerAppFetchError("Partner-App hat nicht rechtzeitig geantwortet.") from error
    except (JSONDecodeError, UnicodeDecodeError) as error:
        raise PartnerAppFetchError("Partner-App liefert keine gültigen JSON-Projektdaten.") from error
    except OSError as error:
        raise PartnerAppFetchError(f"Partner-App-Abruf ist fehlgeschlagen: {error}") from error

    return [_project_to_assignment_unit(project) for project in _extract_projects(payload)]


def _validate_partner_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise PartnerAppConfigError("PARTNER_APP_API_BASE_URL muss eine HTTPS-Adresse sein.")
    if not parsed.hostname:
        raise PartnerAppConfigError("PARTNER_APP_API_BASE_URL braucht einen Hostnamen.")
    host = parsed.hostname.casefold()
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        raise PartnerAppConfigError("PARTNER_APP_API_BASE_URL darf nicht auf lokale Hosts zeigen.")
    try:
        address = ip_address(host)
    except ValueError:
        return
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        raise PartnerAppConfigError("PARTNER_APP_API_BASE_URL darf nicht auf private oder lokale IP-Adressen zeigen.")


def _extract_projects(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise PartnerAppFetchError("Partner-App liefert kein unterstütztes Projektformat.")
    for key in ("projects", "items", "data", "assignment_units"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    raise PartnerAppFetchError("Partner-App liefert keine Projektliste.")


def _project_to_assignment_unit(project: dict[str, Any]) -> dict[str, Any]:
    project_number = _first_text(project, "projectNumber", "project_number", "number")
    explicit_code = _first_text(
        project,
        "assignmentCode",
        "assignment_code",
        "projectCode",
        "project_code",
        "shortCode",
        "short_code",
        "code",
        "abbreviation",
        "projectAbbreviation",
        "project_abbreviation",
    )
    label = _first_text(project, "name", "projectName", "project_name", "title", "label")
    code = explicit_code or label or project_number
    if not code or not label:
        raise PartnerAppFetchError("Partner-App-Projekt ohne Code/Projektnummer oder Name gefunden.")

    address_line = _first_text(project, "projectAddress", "project_address", "address", "addressLine", "address_line")
    postal_code = _first_text(project, "postalCode", "postal_code", "zip", "zipCode")
    city = _first_text(project, "city", "town")
    if address_line and (not postal_code or not city):
        parsed_address = _split_german_address(address_line)
        if parsed_address:
            address_line = parsed_address["address_line"]
            postal_code = postal_code or parsed_address["postal_code"]
            city = city or parsed_address["city"]
    order_number = _first_text(project, "orderNumber", "order_number")
    customer_number = _first_text(project, "customerNumber", "customer_number")
    description = _first_text(project, "description")
    client_name = _first_text(project, "clientName", "client_name")
    aliases = _unique_texts(
        [
            project_number,
            label,
            address_line,
            description,
            client_name,
            order_number,
            customer_number,
            *_list_texts(project.get("aliases")),
        ]
    )
    source_status = _first_text(project, "status")
    return {
        "code": code,
        "label": label,
        "kind": _first_text(project, "kind", "assignmentKind", "assignment_kind") or "construction_project",
        "project_number": project_number,
        "order_number": order_number,
        "customer_number": customer_number,
        "description": description,
        "client_name": client_name,
        "source_status": source_status,
        "address_line": address_line,
        "postal_code": postal_code,
        "city": city,
        "external_id": _first_text(project, "id", "externalId", "external_id"),
        "revenue_relevant": _bool_value(project.get("revenueRelevant"), default=True),
        "aliases": aliases,
        "is_active": _project_is_active(source_status, project),
    }


def _first_text(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _list_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _split_german_address(value: str) -> dict[str, str] | None:
    match = re.match(r"^(?P<line>.*?)[,\s]+(?P<postal_code>\d{5})\s+(?P<city>.+)$", value.strip())
    if not match:
        return None
    line = match.group("line").strip(" ,")
    city = match.group("city").strip(" ,")
    if not line or not city:
        return None
    return {
        "address_line": line,
        "postal_code": match.group("postal_code"),
        "city": city,
    }


def _unique_texts(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _project_is_active(status: str | None, project: dict[str, Any] | None = None) -> bool:
    project = project or {}
    for key in ("isActive", "is_active", "active"):
        if key in project:
            return _bool_value(project.get(key), default=True)
    for key in ("isInactive", "is_inactive", "completed", "complete", "isCompleted", "is_completed", "closed"):
        if key in project:
            return not _bool_value(project.get(key), default=False)
    for key in ("closedAt", "closed_at", "completedAt", "completed_at", "archivedAt", "archived_at"):
        if _first_text(project, key):
            return False

    normalized = _normalize_status(status)
    if not normalized:
        end_date = _first_text(project, "endDate", "end_date", "completedDate", "completed_date")
        return not bool(end_date)
    inactive_statuses = {
        "archived",
        "archive",
        "deleted",
        "cancelled",
        "canceled",
        "inactive",
        "closed",
        "complete",
        "completed",
        "done",
        "finished",
        "abgeschlossen",
        "beendet",
        "fertig",
        "erledigt",
    }
    return normalized not in inactive_statuses


def _normalize_status(status: str | None) -> str:
    if not status:
        return ""
    return " ".join(status.strip().casefold().split())


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "ja", "y"}
    return bool(value)
