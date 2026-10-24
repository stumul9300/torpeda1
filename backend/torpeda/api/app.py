"""HTTP API для интерфейса: расчёт, таблица товаров, себестоимость, акции, загрузка из WB."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from torpeda import config, costs_excel, pricing, services
from torpeda.calc import UnitInput, calculate, price_for_target_margin
from torpeda.calc.unit_economics import price_before_discount_for
from torpeda.config import BACKEND_DIR, get_settings, masked_keys, save_keys
from torpeda.db import DEFAULT_ACCOUNT_ID, init_db, make_engine
from torpeda.db.models import DEFAULT_SETTINGS, CostPrice, Order, Price, Product, Promotion, ReportRow, Setting
from torpeda.reports import Table, finance, orders
from torpeda.sync import sync_all, sync_orders, sync_report, sync_sales
from torpeda.wb_api.client import WBClient, WBError

app = FastAPI(title="Торпеда", version="0.2.0")
ACC = DEFAULT_ACCOUNT_ID


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return init_db(make_engine(get_settings().database_url))


def get_session() -> Iterator[Session]:
    with session_factory()() as s:
        yield s


def get_wb_client() -> Iterator[WBClient]:
    try:
        client = WBClient(get_settings().wb_api_token)
    except WBError as e:
        raise HTTPException(400, str(e)) from e
    with client:
        yield client


def get_wb_prices_client() -> Iterator[WBClient]:
    try:
        client = WBClient(get_settings().wb_prices_token)
    except WBError as e:
        raise HTTPException(400, "Не задан ключ для изменения цен. Вставьте его на вкладке «Настройки».") from e
    with client:
        yield client


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


# --- таблица товаров ---


@app.get("/api/products")
def list_products(s: Session = Depends(get_session)) -> list[dict]:
    return services.product_rows(s)


class CostRequest(BaseModel):
    cost: Decimal = Field(ge=0)
    valid_from: date | None = None  # по умолчанию сегодня


@app.get("/api/costs.xlsx")
def export_costs(s: Session = Depends(get_session)) -> Response:
    return Response(
        costs_excel.export_costs(s),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="torpeda-costs-{date.today()}.xlsx"'},
    )


@app.post("/api/costs/import")
async def import_costs(file: UploadFile, s: Session = Depends(get_session)) -> dict:
    try:
        return costs_excel.import_costs(s, await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/products/{nm_id}/cost")
def set_cost(nm_id: int, req: CostRequest, s: Session = Depends(get_session)) -> dict:
    if s.get(Product, (ACC, nm_id)) is None:
        raise HTTPException(404, "Товар не найден")
    s.add(CostPrice(account_id=ACC, nm_id=nm_id, cost=req.cost, valid_from=req.valid_from or date.today()))
    s.commit()
    return {"nm_id": nm_id, "cost": req.cost}


class CalcPriceRequest(BaseModel):
    price: Decimal | None = Field(default=None, ge=0)  # None — сбросить расчётную цену
    discount_pct: Decimal | None = Field(default=None, ge=0, lt=100)


@app.put("/api/products/{nm_id}/calc-price")
def set_calc_price(nm_id: int, req: CalcPriceRequest, s: Session = Depends(get_session)) -> dict:
    price = s.get(Price, (ACC, nm_id))
    if price is None:
        raise HTTPException(404, "Цена товара ещё не загружена из WB")
    price.calc_price = req.price
    price.calc_discount_pct = req.discount_pct
    s.commit()
    return {"nm_id": nm_id, "calc_price": price.calc_price, "calc_discount_pct": price.calc_discount_pct}


# --- акции ---


@app.get("/api/promotions")
def list_promotions(s: Session = Depends(get_session)) -> list[dict]:
    promos = s.query(Promotion).filter(Promotion.account_id == ACC).order_by(Promotion.start_at).all()
    return [{"id": p.id, "name": p.name, "type": p.type, "start_at": p.start_at, "end_at": p.end_at} for p in promos]


@app.get("/api/promotions/{promotion_id}")
def promotion_analysis(promotion_id: int, s: Session = Depends(get_session)) -> dict:
    result = services.promotion_rows(s, promotion_id)
    if result is None:
        raise HTTPException(404, "Акция не найдена")
    return result


# --- настройки ---


@app.get("/api/settings")
def read_settings(s: Session = Depends(get_session)) -> dict[str, str]:
    return services.get_settings(s)


@app.put("/api/settings")
def update_settings(values: dict[str, str], s: Session = Depends(get_session)) -> dict[str, str]:
    unknown = set(values) - set(DEFAULT_SETTINGS)
    if unknown:
        raise HTTPException(422, f"Неизвестные настройки: {', '.join(sorted(unknown))}")
    for key, value in values.items():
        s.merge(Setting(account_id=ACC, key=key, value=value))
    s.commit()
    return services.get_settings(s)


# --- ключи WB ---


@app.get("/api/info")
def info() -> dict:
    return {"data_dir": str(config.DATA_DIR)}


@app.get("/api/keys")
def read_keys() -> dict[str, str | None]:
    return masked_keys()


class KeysRequest(BaseModel):
    read: str | None = None  # ключ «только чтение»; None — не менять, "" — удалить
    prices: str | None = None  # ключ для цен


@app.put("/api/keys")
def update_keys(req: KeysRequest) -> dict[str, str | None]:
    save_keys({k: v for k, v in req.model_dump().items() if v is not None})
    return masked_keys()


# --- Wildberries ---


@app.get("/api/wb/check")
def wb_check(client: WBClient = Depends(get_wb_client)) -> dict[str, str]:
    return client.ping()


@app.post("/api/wb/sync")
def wb_sync(days: int = 30, client: WBClient = Depends(get_wb_client)) -> dict:
    return sync_all(client, session_factory(), days=days)


class PeriodRequest(BaseModel):
    date_from: date
    date_to: date


@app.post("/api/wb/sync-report")
def wb_sync_report(req: PeriodRequest, client: WBClient = Depends(get_wb_client)) -> dict:
    """Финотчёты за выбранный период (WB отдаёт детализацию медленно: 1 запрос в минуту)."""
    if req.date_from > req.date_to:
        raise HTTPException(400, "Дата «с» позже даты «по»")
    with session_factory()() as s:
        try:
            n = sync_report(client, s, req.date_from, req.date_to)
            s.commit()
        except WBError as e:
            raise HTTPException(502, str(e)) from e
    return {"rows": n}


@app.post("/api/wb/sync-orders")
def wb_sync_orders(req: PeriodRequest, client: WBClient = Depends(get_wb_client)) -> dict:
    """Заказы и продажи с даты (WB хранит заказы 90 дней)."""
    with session_factory()() as s:
        try:
            n_orders = sync_orders(client, s, req.date_from)
            n_sales = sync_sales(client, s, req.date_from)
            s.commit()
        except WBError as e:
            raise HTTPException(502, str(e)) from e
    return {"orders": n_orders, "sales": n_sales}


class PlanRequest(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    nm_id: int = 0  # 0 — весь кабинет
    qty: int | None = Field(default=None, ge=0)
    revenue: Decimal | None = Field(default=None, ge=0)


@app.put("/api/plans")
def put_plan(req: PlanRequest, s: Session = Depends(get_session)) -> dict:
    orders.save_plan(s, req.month, req.nm_id, req.qty, req.revenue)
    return req.model_dump()


# --- отчёты ---


@app.get("/api/reports/range")
def reports_range(s: Session = Depends(get_session)) -> dict:
    lo, hi = s.execute(select(func.min(ReportRow.rr_dt), func.max(ReportRow.rr_dt))).one()
    o_lo, o_hi = s.execute(select(func.min(Order.date), func.max(Order.date))).one()
    return {
        "date_from": lo,
        "date_to": hi,
        "orders_from": o_lo.date() if o_lo else None,
        "orders_to": o_hi.date() if o_hi else None,
    }


REPORTS = finance.REPORTS | orders.REPORTS


def _report(name: str, s: Session, date_from: date, date_to: date, group: str | None) -> Table:
    fn = REPORTS.get(name)
    if fn is None:
        raise HTTPException(404, "Нет такого отчёта")
    return fn(s, date_from, date_to, group) if group else fn(s, date_from, date_to)


@app.get("/api/reports/{name}.xlsx")
def report_xlsx(
    name: str, date_from: date, date_to: date, group: str | None = None, s: Session = Depends(get_session)
) -> Response:
    table = _report(name, s, date_from, date_to, group)
    return Response(
        table.to_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="torpeda-{name}-{date_from}-{date_to}.xlsx"'},
    )


@app.get("/api/reports/{name}")
def report(name: str, date_from: date, date_to: date, group: str | None = None, s: Session = Depends(get_session)):
    return _report(name, s, date_from, date_to, group).to_json()


# --- отправка цен в WB: предпросмотр → подтверждение ---


class ChangeModel(BaseModel):
    nm_id: int
    old_price: int
    old_discount: int
    new_price: int
    new_discount: int

    def to_change(self) -> pricing.Change:
        return pricing.Change(**self.model_dump())


class PreviewRequest(BaseModel):
    nm_ids: list[int] | None = None  # None — все товары с расчётной ценой
    revert_change_ids: list[int] | None = None  # вернуть цены до этих отправок


class SendRequest(BaseModel):
    items: list[ChangeModel]
    confirm_token: str


@app.post("/api/prices/preview")
def prices_preview(req: PreviewRequest, s: Session = Depends(get_session)) -> dict:
    if req.revert_change_ids:
        changes = pricing.changes_for_revert(s, req.revert_change_ids)
    else:
        changes = pricing.changes_from_calc_prices(s, req.nm_ids)
    try:
        return pricing.preview(s, changes)
    except pricing.PricingError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/prices/send")
def prices_send(
    req: SendRequest, s: Session = Depends(get_session), client: WBClient = Depends(get_wb_prices_client)
) -> dict:
    try:
        return pricing.send(s, client, [i.to_change() for i in req.items], req.confirm_token)
    except pricing.PricingError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/prices/history")
def prices_history(s: Session = Depends(get_session)) -> list[dict]:
    return pricing.history(s)


# Интерфейс: статические файлы из frontend/, открывается на http://127.0.0.1:8000/
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
