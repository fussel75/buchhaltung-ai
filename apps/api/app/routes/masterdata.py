from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.routes.users import require_admin, require_tenant_access
from app.services.database import (
    create_accounting_rule,
    create_assignment_unit,
    create_supplier_rule,
    ensure_tenant_profile,
    get_tenant_profile,
    list_accounting_rules,
    list_assignment_units,
    list_supplier_rules,
    tenant_profile_template,
    update_accounting_rule,
    update_assignment_unit,
    update_supplier_rule,
    upsert_tenant_profile,
)

router = APIRouter()


class AssignmentUnitRequest(BaseModel):
    code: str
    label: str
    kind: str = "cost_object"
    project_number: str | None = None
    revenue_relevant: bool = False
    aliases: list[str] = []
    is_active: bool = True


class AssignmentUnitUpdateRequest(BaseModel):
    code: str
    label: str
    kind: str = "cost_object"
    project_number: str | None = None
    revenue_relevant: bool = False
    aliases: list[str] = []
    is_active: bool = True


class SupplierRuleRequest(BaseModel):
    match_text: str
    supplier_name: str
    customer_number: str | None = None
    default_cost_category: str | list[str] | None = None
    default_assignment_code: str | None = None
    is_active: bool = True


class AccountingRuleRequest(BaseModel):
    name: str
    supplier_match_text: str | None = None
    cost_category: str | None = None
    debit_account: str
    credit_account: str
    tax_key: str | None = None
    tax_rate: Decimal | None = None
    discount_account: str | None = None
    is_active: bool = True


class TenantProfileRequest(BaseModel):
    display_name: str
    industry: str = "general"
    assignment_label_singular: str | None = None
    assignment_label_plural: str | None = None
    assignment_code_label: str | None = None
    assignment_code_prefix: str | None = None
    default_assignment_kind: str | None = None
    allow_multiple_assignments: bool | None = None


def _normalize_tenant_id(tenant_id: str) -> str:
    normalized = tenant_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return normalized


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
        revenue_relevant=payload.revenue_relevant,
        aliases=payload.aliases,
        is_active=payload.is_active,
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="assignment unit not found")
    return {"assignment_unit": assignment}


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
