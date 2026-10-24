"""HTTP API. Пока один метод: расчёт юнит-экономики для мгновенного пересчёта в таблице."""

from __future__ import annotations

from decimal import Decimal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from torpeda.calc import UnitInput, calculate, price_for_target_margin
from torpeda.calc.unit_economics import price_before_discount_for

app = FastAPI(title="Торпеда", version="0.1.0")


class UnitRequest(BaseModel):
    price_before_discount: Decimal = Field(ge=0)
    discount_pct: Decimal = Field(ge=0, lt=100)
    cost: Decimal = Field(ge=0)
    commission_pct: Decimal = Field(ge=0, le=100)
    logistics_per_unit: Decimal = Field(ge=0)
    acquiring_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)
    tax_pct: Decimal = Field(default=Decimal(0), ge=0, le=100)
    advertising_per_unit: Decimal = Field(default=Decimal(0), ge=0)
    storage_per_unit: Decimal = Field(default=Decimal(0), ge=0)
    defect_per_unit: Decimal = Field(default=Decimal(0), ge=0)
    spp_pct: Decimal = Field(default=Decimal(0), ge=0, lt=100)
    target_margin_pct: Decimal | None = None


class UnitResponse(BaseModel):
    seller_price: Decimal
    price_with_spp: Decimal
    commission: Decimal
    acquiring: Decimal
    tax: Decimal
    logistics: Decimal
    advertising: Decimal
    storage: Decimal
    defect: Decimal
    cost: Decimal
    profit: Decimal
    roi_pct: Decimal | None
    margin_pct: Decimal | None
    is_loss: bool
    target_price_before_discount: Decimal | None = None


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/calc/unit", response_model=UnitResponse)
def calc_unit(req: UnitRequest) -> UnitResponse:
    inp = UnitInput(**req.model_dump(exclude={"target_margin_pct"}))
    r = calculate(inp)
    target = None
    if req.target_margin_pct is not None:
        p = price_for_target_margin(inp, req.target_margin_pct)
        p0 = price_before_discount_for(p, inp.discount_pct) if p is not None else None
        target = p0.quantize(Decimal("0.01")) if p0 is not None else None
    rounded = r.rounded()
    return UnitResponse(**rounded.__dict__, is_loss=r.is_loss, target_price_before_discount=target)
