from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, field_validator

from app.config import get_settings
from app.routes.users import require_admin, require_tenant_access
from app.services.cost_categories import CostCategory, invalid_cost_category_values
from app.services.database import (
    create_accounting_rule,
    create_assignment_unit,
    create_bwa_import,
    create_supplier_rule,
    ensure_tenant_profile,
    get_tenant_profile,
    list_accounting_rules,
    list_assignment_units,
    list_bwa_imports,
    list_supplier_rules,
    tenant_profile_template,
    update_accounting_rule,
    update_assignment_unit,
    update_supplier_rule,
    upsert_tenant_profile,
)
from app.services.bwa import analyze_bwa_file
from app.services.storage import UploadRejectedError, delete_stored_document, store_bwa_document

router = APIRouter()


class AssignmentUnitRequest(BaseModel):
    code: str
    label: str
    kind: str = "cost_object"
    project_number: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    external_id: str | None = None
    revenue_relevant: bool = False
    aliases: list[str] = []
    is_active: bool = True


class AssignmentUnitUpdateRequest(BaseModel):
    code: str
    label: str
    kind: str = "cost_object"
    project_number: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    external_id: str | None = None
    revenue_relevant: bool = False
    aliases: list[str] = []
    is_active: bool = True


class AssignmentUnitSyncRequest(BaseModel):
    assignment_units: list[AssignmentUnitRequest]


class SupplierRuleRequest(BaseModel):
    match_text: str
    supplier_name: str
    customer_number: str | None = None
    default_cost_category: str | list[str] | None = None
    default_assignment_code: str | None = None
    is_active: bool = True

    @field_validator("default_cost_category")
    @classmethod
    def validate_default_cost_category(cls, value: str | list[str] | None) -> str | list[str] | None:
        if value == "":
            return None
        invalid = invalid_cost_category_values(value)
        if invalid:
            raise ValueError(f"Unbekannte Kostenart: {', '.join(invalid)}")
        return value


class AccountingRuleRequest(BaseModel):
    name: str
    supplier_match_text: str | None = None
    cost_category: CostCategory | None = None
    debit_account: str
    credit_account: str
    tax_key: str | None = None
    tax_rate: Decimal | None = None
    discount_account: str | None = None
    is_active: bool = True

    @field_validator("cost_category", mode="before")
    @classmethod
    def normalize_optional_cost_category(cls, value: str | None) -> str | None:
        return None if value == "" else value


class TenantProfileRequest(BaseModel):
    display_name: str
    industry: str = "general"
    assignment_label_singular: str | None = None
    assignment_label_plural: str | None = None
    assignment_code_label: str | None = None
    assignment_code_prefix: str | None = None
    default_assignment_kind: str | None = None
    allow_multiple_assignments: bool | None = None
    accounting_framework: str | None = None
    default_credit_account: str | None = None
    default_tax_key: str | None = None
    default_tax_rate: Decimal | None = None
    default_discount_account: str | None = None


def _normalize_tenant_id(tenant_id: str) -> str:
    normalized = tenant_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return normalized


def _require_admin_or_sync_token(request: Request, tenant_id: str) -> str:
    settings = get_settings()
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
    token_tenant_id = _tenant_id_for_sync_token(settings.partner_sync_tokens, token)
    if token_tenant_id:
        return token_tenant_id
    require_admin(request)
    require_tenant_access(request, tenant_id)
    return tenant_id


def _tenant_id_for_sync_token(token_mapping: str | None, token: str) -> str | None:
    if not token_mapping or not token:
        return None
    for entry in token_mapping.split(","):
        tenant_id, separator, expected_token = entry.partition(":")
        if separator and tenant_id.strip() and expected_token.strip() and token == expected_token.strip():
            return _normalize_tenant_id(tenant_id)
    return None


@router.get("/bwa-imports")
def get_bwa_imports(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    require_admin(request)
    require_tenant_access(request, normalized_tenant_id)
    return {"bwa_imports": list_bwa_imports(normalized_tenant_id)}


@router.post("/bwa-imports", status_code=status.HTTP_201_CREATED)
async def post_bwa_import(
    request: Request,
    file: UploadFile = File(...),
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    require_admin(request)
    require_tenant_access(request, normalized_tenant_id)
    try:
        stored = await store_bwa_document(file=file, tenant_id=normalized_tenant_id)
        analysis = analyze_bwa_file(
            storage_path=str(stored.storage_path),
            original_filename=stored.original_filename,
            content_type=stored.content_type,
        )
        bwa_import, inserted = create_bwa_import(
            tenant_id=normalized_tenant_id,
            stored=stored,
            period=analysis.period,
            account_hints=analysis.account_hints,
            warnings=analysis.warnings,
            text_excerpt=analysis.text_excerpt,
        )
    except UploadRejectedError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except Exception:
        if "stored" in locals():
            delete_stored_document(stored)
        raise
    return {"bwa_import": bwa_import, "duplicate": not inserted}


@router.get("/tenant-profile")
def get_profile(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    require_tenant_access(request, normalized_tenant_id)
    return {"tenant_profile": get_tenant_profile(normalized_tenant_id) or ensure_tenant_profile(normalized_tenant_id)}


@router.put("/tenant-profile")
def put_profile(
    payload: TenantProfileRequest,
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    require_admin(request)
    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    template = tenant_profile_template(payload.industry)
    profile = upsert_tenant_profile(
        tenant_id=normalized_tenant_id,
        display_name=payload.display_name,
        industry=payload.industry,
        assignment_label_singular=payload.assignment_label_singular or template["assignment_label_singular"],
        assignment_label_plural=payload.assignment_label_plural or template["assignment_label_plural"],
        assignment_code_label=payload.assignment_code_label or template["assignment_code_label"],
        assignment_code_prefix=payload.assignment_code_prefix
        if payload.assignment_code_prefix is not None
        else template["assignment_code_prefix"],
        default_assignment_kind=payload.default_assignment_kind or template["default_assignment_kind"],
        allow_multiple_assignments=(
            payload.allow_multiple_assignments
            if payload.allow_multiple_assignments is not None
            else template["allow_multiple_assignments"]
        ),
        accounting_framework=payload.accounting_framework or template["accounting_framework"],
        default_credit_account=payload.default_credit_account
        if payload.default_credit_account is not None
        else template["default_credit_account"],
        default_tax_key=payload.default_tax_key
        if payload.default_tax_key is not None
        else template["default_tax_key"],
        default_tax_rate=payload.default_tax_rate
        if payload.default_tax_rate is not None
        else template["default_tax_rate"],
        default_discount_account=payload.default_discount_account
        if payload.default_discount_account is not None
        else template["default_discount_account"],
    )
    return {"tenant_profile": profile}


@router.get("/assignment-units")
def get_assignment_units(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    require_admin(request)
    return {"assignment_units": list_assignment_units(_normalize_tenant_id(tenant_id))}


@router.post("/assignment-units", status_code=status.HTTP_201_CREATED)
def post_assignment_unit(
    payload: AssignmentUnitRequest,
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    require_admin(request)
    assignment = create_assignment_unit(
        tenant_id=_normalize_tenant_id(tenant_id),
        code=payload.code,
        label=payload.label,
        kind=payload.kind,
        project_number=payload.project_number,
        address_line=payload.address_line,
        postal_code=payload.postal_code,
        city=payload.city,
        external_id=payload.external_id,
        revenue_relevant=payload.revenue_relevant,
        aliases=payload.aliases,
        is_active=payload.is_active,
    )
    return {"assignment_unit": assignment}


@router.patch("/assignment-units/{assignment_id}")
def patch_assignment_unit(
    assignment_id: UUID,
    payload: AssignmentUnitUpdateRequest,
    request: Request,
) -> dict:
    require_admin(request)
    assignment = update_assignment_unit(
        assignment_id=assignment_id,
        code=payload.code,
        label=payload.label,
        kind=payload.kind,
        project_number=payload.project_number,
        address_line=payload.address_line,
        postal_code=payload.postal_code,
        city=payload.city,
        external_id=payload.external_id,
        revenue_relevant=payload.revenue_relevant,
        aliases=payload.aliases,
        is_active=payload.is_active,
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="assignment unit not found")
    return {"assignment_unit": assignment}


@router.post("/assignment-units/sync")
def sync_assignment_units(
    payload: AssignmentUnitSyncRequest,
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    normalized_tenant_id = _require_admin_or_sync_token(request, _normalize_tenant_id(tenant_id))
    synced = [
        create_assignment_unit(
            tenant_id=normalized_tenant_id,
            code=assignment.code,
            label=assignment.label,
            kind=assignment.kind,
            project_number=assignment.project_number,
            address_line=assignment.address_line,
            postal_code=assignment.postal_code,
            city=assignment.city,
            external_id=assignment.external_id,
            revenue_relevant=assignment.revenue_relevant,
            aliases=assignment.aliases,
            is_active=assignment.is_active,
        )
        for assignment in payload.assignment_units
    ]
    return {"assignment_units": synced, "synced_count": len(synced)}


@router.get("/supplier-rules")
def get_supplier_rules(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    require_admin(request)
    return {"supplier_rules": list_supplier_rules(_normalize_tenant_id(tenant_id))}


@router.post("/supplier-rules", status_code=status.HTTP_201_CREATED)
def post_supplier_rule(
    payload: SupplierRuleRequest,
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    require_admin(request)
    rule = create_supplier_rule(
        tenant_id=_normalize_tenant_id(tenant_id),
        match_text=payload.match_text,
        supplier_name=payload.supplier_name,
        customer_number=payload.customer_number,
        default_cost_category=payload.default_cost_category,
        default_assignment_code=payload.default_assignment_code,
        is_active=payload.is_active,
    )
    return {"supplier_rule": rule}


@router.patch("/supplier-rules/{rule_id}")
def patch_supplier_rule(
    rule_id: UUID,
    payload: SupplierRuleRequest,
    request: Request,
) -> dict:
    require_admin(request)
    rule = update_supplier_rule(
        rule_id=rule_id,
        match_text=payload.match_text,
        supplier_name=payload.supplier_name,
        customer_number=payload.customer_number,
        default_cost_category=payload.default_cost_category,
        default_assignment_code=payload.default_assignment_code,
        is_active=payload.is_active,
    )
    if not rule:
        raise HTTPException(status_code=404, detail="supplier rule not found")
    return {"supplier_rule": rule}


@router.get("/accounting-rules")
def get_accounting_rules(
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    require_admin(request)
    return {"accounting_rules": list_accounting_rules(_normalize_tenant_id(tenant_id))}


@router.post("/accounting-rules", status_code=status.HTTP_201_CREATED)
def post_accounting_rule(
    payload: AccountingRuleRequest,
    request: Request,
    tenant_id: str = Query("demo-mandant", min_length=1),
) -> dict:
    require_admin(request)
    rule = create_accounting_rule(
        tenant_id=_normalize_tenant_id(tenant_id),
        name=payload.name,
        supplier_match_text=payload.supplier_match_text,
        cost_category=payload.cost_category,
        debit_account=payload.debit_account,
        credit_account=payload.credit_account,
        tax_key=payload.tax_key,
        tax_rate=payload.tax_rate,
        discount_account=payload.discount_account,
        is_active=payload.is_active,
    )
    return {"accounting_rule": rule}


@router.patch("/accounting-rules/{rule_id}")
def patch_accounting_rule(
    rule_id: UUID,
    payload: AccountingRuleRequest,
    request: Request,
) -> dict:
    require_admin(request)
    rule = update_accounting_rule(
        rule_id=rule_id,
        name=payload.name,
        supplier_match_text=payload.supplier_match_text,
        cost_category=payload.cost_category,
        debit_account=payload.debit_account,
        credit_account=payload.credit_account,
        tax_key=payload.tax_key,
        tax_rate=payload.tax_rate,
        discount_account=payload.discount_account,
        is_active=payload.is_active,
    )
    if not rule:
        raise HTTPException(status_code=404, detail="accounting rule not found")
    return {"accounting_rule": rule}
