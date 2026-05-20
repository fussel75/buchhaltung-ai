from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.routes.users import require_admin
from app.services.database import (
    create_assignment_unit,
    create_supplier_rule,
    list_assignment_units,
    list_supplier_rules,
    update_assignment_unit,
    update_supplier_rule,
)

router = APIRouter()


class AssignmentUnitRequest(BaseModel):
    code: str
    label: str
    kind: str = "cost_object"
    revenue_relevant: bool = False
    aliases: list[str] = []
    is_active: bool = True


class AssignmentUnitUpdateRequest(BaseModel):
    label: str
    kind: str = "cost_object"
    revenue_relevant: bool = False
    aliases: list[str] = []
    is_active: bool = True


class SupplierRuleRequest(BaseModel):
    match_text: str
    supplier_name: str
    customer_number: str | None = None
    default_cost_category: str | None = None
    default_assignment_code: str | None = None
    is_active: bool = True


def _normalize_tenant_id(tenant_id: str) -> str:
    normalized = tenant_id.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    return normalized


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
        label=payload.label,
        kind=payload.kind,
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
