"""Общие заготовки: база в памяти и поддельный WB, отвечающий как настоящий API."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from torpeda import config
from torpeda.db import init_db
from torpeda.wb_api.client import FINANCE_FIELDS, WBClient


class FakeWB:
    """Отвечает на запросы к хостам WB данными, похожими на настоящие."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.uploaded: list[dict] = []
        self.fail_upload = False
        self.finance_enabled = True  # False — у ключа нет категории «Финансы», работает запасной способ
        self.analytics_enabled = True  # False — у ключа нет категории «Аналитика»
        self.advert_enabled = True  # False — у ключа нет категории «Продвижение»
        self.base_token = False  # True — ключ типа «Базовый»: быстрый метод остатков WB не пускает
        self.marketplace_enabled = True  # False — у ключа нет категории «Маркетплейс»
        self.tariffs_coefs = True  # False — новый адрес коэффициентов недоступен, работает запасной
        self.task_polls: dict[str, int] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/ping":
            return httpx.Response(200, json={"TS": "2026-10-24T09:00:00Z", "Status": "OK"})
        if path == "/content/v2/get/cards/list":
            return httpx.Response(
                200,
                json={
                    "cards": [
                        {
                            "nmID": 418020031,
                            "vendorCode": "8447",
                            "title": "Поло женское",
                            "brand": "Stilly",
                            "subjectID": 192,
                            "subjectName": "Поло",
                            "dimensions": {"length": 25, "width": 15, "height": 7},
                            "sizes": [{"chrtID": 11, "techSize": "44"}, {"chrtID": 12, "techSize": "46"}],
                            "photos": [{"big": "https://img.example/big.webp", "tm": "https://img.example/tm.webp"}],
                        }
                    ],
                    "cursor": {"updatedAt": "2026-10-20T10:00:00Z", "nmID": 418020031, "total": 1},
                },
            )
        if path == "/api/v2/list/goods/filter":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "listGoods": [
                            {
                                "nmID": 418020031,
                                "vendorCode": "8447",
                                "sizes": [{"sizeID": 1, "price": 5123, "discountedPrice": 3073.8}],
                                "discount": 40,
                                "clubDiscount": 0,
                            }
                        ]
                    }
                },
            )
        if path == "/api/v1/tariffs/commission":
            return httpx.Response(
                200,
                json={
                    "report": [
                        {"subjectID": 192, "subjectName": "Поло", "paidStorageKgvp": 43.5, "kgvpMarketplace": 48}
                    ]
                },
            )
        if path.startswith("/api/analytics/v1/stocks-report/") and self.base_token:
            return httpx.Response(403, json={"status": 403, "title": "Forbidden",
                                             "detail": "token does not satisfy additional requirements"})  # fmt: skip
        if path.startswith("/api/v3/") and not self.marketplace_enabled:
            return httpx.Response(401, json={"title": "unauthorized", "detail": "token scope not allowed"})
        if path == "/api/v3/warehouses":
            return httpx.Response(200, json=[{"id": 77, "name": "Мой склад", "officeId": 1}])
        if path == "/api/v3/stocks/77":
            ids = json.loads(request.content)["chrtIds"]
            stocks = [{"chrtId": i, "amount": {11: 4, 12: 0}.get(i, 0)} for i in ids]
            return httpx.Response(200, json={"stocks": stocks})
        if path == "/api/analytics/v1/stocks-report/wb-warehouses":
            item = {
                "nmId": 418020031,
                "chrtId": 1,
                "warehouseId": -999999,
                "warehouseName": "Склад WB",
                "regionName": "Склад WB",
                "quantity": 45,
                "inWayToClient": 3,
                "inWayFromClient": 0,
            }
            return httpx.Response(200, json={"data": {"items": [item]}})
        if path == "/api/analytics/v1/stocks-report/seller-warehouses":
            item = {
                "nmId": 418020031,
                "chrtId": 1,
                "warehouseId": 123,
                "warehouseName": "Мой склад",
                "regionName": "Центральный",
                "quantity": 7,
            }
            return httpx.Response(200, json={"data": {"items": [item]}})
        if path == "/api/v1/supplier/orders":
            return httpx.Response(
                200,
                json=[
                    {
                        "srid": "o1",
                        "nmId": 418020031,
                        "date": "2026-10-20T10:00:00",
                        "warehouseName": "Коледино",
                        "priceWithDisc": 3073.8,
                        "finishedPrice": 2182,
                        "spp": 29,
                        "isCancel": False,
                    }
                ],
            )
        if path == "/api/v1/supplier/sales":
            return httpx.Response(
                200,
                json=[
                    {
                        "saleID": "S1",
                        "srid": "o1",
                        "nmId": 418020031,
                        "date": "2026-10-21T10:00:00",
                        "priceWithDisc": 3073.8,
                        "finishedPrice": 2182,
                        "forPay": 1700,
                        "spp": 29,
                    }
                ],
            )
        if path.startswith("/api/finance/") and not self.finance_enabled:
            return httpx.Response(401, text="token scope not allowed")
        if path == "/api/finance/v1/sales-reports/detailed":
            if json.loads(request.content)["rrdId"] != 0:
                return httpx.Response(204)
            to_new = {old: new for new, old in FINANCE_FIELDS.items()}
            # деньги finance-api отдаёт строками
            money = lambda v: str(v) if isinstance(v, float) else v  # noqa: E731
            rows = [{to_new.get(k, k): money(v) for k, v in r.items()} for r in report_rows()]
            return httpx.Response(200, json=rows)
        if path == "/api/finance/v1/sales-reports/list":
            head = {"reportId": 5, "dateFrom": "2026-10-13", "dateTo": "2026-10-19", "createDate": "2026-10-20",
                    "reportType": 1, "forPaySum": "15300", "deliveryServiceSum": "4347.82", "paidStorageSum": "1.2",
                    "bankPaymentSum": "10950.98"}
            return httpx.Response(200, json=[head])
        if path == "/api/v5/supplier/reportDetailByPeriod":
            if request.url.params.get("rrdid") != "0":
                return httpx.Response(204)
            return httpx.Response(200, json=report_rows())
        if path == "/api/v1/calendar/promotions":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "promotions": [
                            {
                                "id": 1001,
                                "name": "11.11",
                                "type": "regular",
                                "startDateTime": "2026-10-29T00:00:00Z",
                                "endDateTime": "2026-11-05T23:59:59Z",
                            },
                            {  # автоакция: список товаров WB не отдаёт
                                "id": 1002,
                                "name": "Автоакция",
                                "type": "auto",
                                "startDateTime": "2026-10-29T00:00:00Z",
                                "endDateTime": "2026-11-05T23:59:59Z",
                            },
                            {  # обычная акция, на которую WB почему-то отвечает 422
                                "id": 1003,
                                "name": "Закрытая",
                                "type": "regular",
                                "startDateTime": "2026-10-29T00:00:00Z",
                                "endDateTime": "2026-11-05T23:59:59Z",
                            },
                        ]
                    }
                },
            )
        if path == "/api/v1/calendar/promotions/nomenclatures":
            if request.url.params.get("promotionID") != "1001":
                return httpx.Response(422, json={"errorText": "Unprocessable entity"})
            in_action = request.url.params.get("inAction") == "true"
            items = (
                []
                if in_action
                else [
                    {
                        "id": 418020031,
                        "inAction": False,
                        "price": 5123,
                        "discount": 40,
                        "planPrice": 5123,
                        "planDiscount": 60,
                    }
                ]
            )
            return httpx.Response(200, json={"data": {"nomenclatures": items}})
        if path in ("/api/tariffs/v1/acceptance/coefficients", "/api/v1/acceptance/coefficients"):
            if path.startswith("/api/tariffs") and not self.tariffs_coefs:
                return httpx.Response(404, json={"title": "not found"})
            row = {"warehouseName": "Коледино", "warehouseID": 507, "boxTypeName": "Короба", "boxTypeID": 2,
                   "allowUnload": True, "storageCoef": "160", "deliveryCoef": "205", "isSortingCenter": False}
            return httpx.Response(200, json=[
                row | {"date": "2026-10-25T00:00:00Z", "coefficient": 0},
                row | {"date": "2026-10-26T00:00:00Z", "coefficient": 2},
                row | {"date": "2026-10-27T00:00:00Z", "coefficient": -1, "allowUnload": False},
                row | {"date": "2026-10-25T00:00:00Z", "coefficient": 1, "warehouseName": "Тула", "warehouseID": 206},
                row | {"date": "2026-10-25T00:00:00Z", "coefficient": 0, "boxTypeID": 5, "boxTypeName": "Монопаллеты"},
            ])  # fmt: skip
        if path.startswith("/adv/"):
            if not self.advert_enabled:
                return httpx.Response(401, json={"title": "unauthorized", "detail": "token scope not allowed"})
            return self.advert(request, path)
        if path.startswith(("/api/analytics/v3/", "/api/v1/paid_storage", "/api/v1/acceptance_report",
                            "/api/v1/warehouse_remains")):  # fmt: skip
            if not self.analytics_enabled:
                return httpx.Response(403, json={"title": "Forbidden", "detail": "token scope not allowed"})
            return self.analytics(request, path)
        if path == "/api/v2/upload/task":
            if self.fail_upload:
                return httpx.Response(400, json={"error": True, "errorText": "bad price"})
            self.uploaded.append(json.loads(request.content))
            return httpx.Response(200, json={"data": {"id": 777, "alreadyExists": False}, "error": False})
        return httpx.Response(404, json={"error": "not mocked", "path": path})


    def advert(self, request: httpx.Request, path: str) -> httpx.Response:
        if path == "/adv/v1/promotion/count":
            return httpx.Response(200, json={"all": 3, "adverts": [
                {"type": 9, "status": 9, "count": 1,
                 "advert_list": [{"advertId": 101, "changeTime": "2026-10-10T10:00:00Z"}]},
                {"type": 9, "status": 7, "count": 2, "advert_list": [
                    {"advertId": 102, "changeTime": "2026-10-05T10:00:00Z"},
                    {"advertId": 103, "changeTime": "2025-01-05T10:00:00Z"}]},
                {"type": 9, "status": 4, "count": 1, "advert_list": [{"advertId": 104}]},
            ]})  # fmt: skip
        if path == "/adv/v3/fullstats":
            ids = [int(x) for x in request.url.params["ids"].split(",")]
            day = request.url.params["beginDate"]

            def nm(n, views, clicks, spend, orders, price):
                return {"nmId": n, "views": views, "clicks": clicks, "atbs": 1, "orders": orders, "shks": orders,
                        "sum": spend, "sum_price": price}  # fmt: skip

            out = []
            for i in ids:
                apps = [{"appType": 1, "nms": [nm(418020031, 1000, 50, 250.5, 2, 6000)]},
                        {"appType": 32, "nms": [nm(418020031, 500, 25, 100, 1, 3000), nm(555, 100, 5, 49.5, 0, 0)]}]
                out.append({"advertId": i, "days": [{"date": f"{day}T00:00:00Z", "apps": apps}]})  # fmt: skip
            return httpx.Response(200, json=out)
        if path == "/adv/v1/upd":
            start = request.url.params["from"]
            return httpx.Response(200, json=[
                {"updNum": 1, "updTime": f"{start}T12:00:00+03:00", "updSum": 400, "advertId": 101,
                 "campName": "Поло поиск", "advertType": 9, "paymentType": "Баланс", "advertStatus": 9},
                {"updNum": 2, "updTime": f"{start}T13:00:00+03:00", "updSum": 300, "advertId": 102,
                 "campName": "Поло авто", "advertType": 8, "paymentType": "Счёт", "advertStatus": 7},
            ])  # fmt: skip
        return httpx.Response(404, json={"error": "not mocked", "path": path})

    def analytics(self, request: httpx.Request, path: str) -> httpx.Response:
        if path == "/api/analytics/v3/sales-funnel/products":
            body = json.loads(request.content)
            period = body["selectedPeriod"]
            stat = {"period": period, "openCount": 1000, "cartCount": 100, "orderCount": 40, "orderSum": 80000,
                    "buyoutCount": 30, "buyoutSum": 60000, "cancelCount": 10, "cancelSum": 20000, "addToWishlist": 15}
            item = {"product": {"nmId": 418020031, "vendorCode": "8447"}, "statistic": {"selected": stat}}
            return httpx.Response(200, json={"data": {"products": [item]}, "currency": "RUB"})  # fmt: skip
        kind = path.split("/")[3]
        if path == f"/api/v1/{kind}":
            q = request.url.params
            task = f"{kind}:{q.get('dateFrom', '')}:{q.get('dateTo', '')}"
            return httpx.Response(200, json={"data": {"taskId": task}})
        task = path.split("/")[5]
        if path.endswith("/status"):
            self.task_polls[task] = self.task_polls.get(task, 0) + 1
            status = "done" if self.task_polls[task] > 1 else "processing"
            return httpx.Response(200, json={"data": {"id": task, "status": status}})
        _, start, _end = task.split(":")
        if kind == "warehouse_remains":
            assert request.url.params.get("groupByNm") is None  # параметры — только при создании
            rows = [{"nmId": 418020031, "vendorCode": "8447", "techSize": "42", "warehouses": [
                {"warehouseName": "В пути до получателей", "quantity": 3},
                {"warehouseName": "В пути возвраты на склад WB", "quantity": 1},
                {"warehouseName": "Всего находится на складах", "quantity": 45},
                {"warehouseName": "Коледино", "quantity": 40},
                {"warehouseName": "Тула", "quantity": 5}]}]  # fmt: skip
        elif kind == "paid_storage":
            rows = [{"date": start, "warehouse": "Коледино", "nmId": 418020031, "size": "42", "volume": 2.5,
                     "warehousePrice": 7.65, "barcodesCount": 3, "calcType": "короба"}]  # fmt: skip
        else:
            rows = [{"count": 40, "giCreateDate": start, "incomeId": 11834106, "nmID": 418020031,
                     "shkCreateDate": start, "subjectName": "Поло", "total": 873.04}]  # fmt: skip
        return httpx.Response(200, json=rows)


def report_rows() -> list[dict]:
    """10 продаж и 1 возврат товара 418020031: логистика 4 347,82 = 434,78 × 10 шт."""
    rows = []
    for i in range(10):
        rows.append(
            {
                "rrd_id": i + 1,
                "realizationreport_id": 5,
                "nm_id": 418020031,
                "rr_dt": "2026-10-20",
                "doc_type_name": "Продажа",
                "supplier_oper_name": "Продажа",
                "quantity": 1,
                "retail_price_withdisc_rub": 3073.8,
                "retail_amount": 2182,
                "ppvz_for_pay": 1700,
                "acquiring_fee": 74.08,
            }
        )
    rows.append(
        {
            "rrd_id": 11,
            "realizationreport_id": 5,
            "nm_id": 418020031,
            "rr_dt": "2026-10-20",
            "doc_type_name": "Возврат",
            "supplier_oper_name": "Возврат",
            "quantity": 1,
            "retail_price_withdisc_rub": 3073.8,
            "retail_amount": 2182,
            "ppvz_for_pay": 1700,
            "acquiring_fee": 0,
        }
    )
    rows.append(
        {
            "rrd_id": 12,
            "realizationreport_id": 5,
            "nm_id": 418020031,
            "rr_dt": "2026-10-20",
            "doc_type_name": "",
            "supplier_oper_name": "Логистика",
            "quantity": 0,
            "delivery_rub": 4347.82,
            "delivery_amount": 30,
            "return_amount": 20,
        }
    )
    rows.append(
        {
            "rrd_id": 13,
            "realizationreport_id": 5,
            "nm_id": 418020031,
            "rr_dt": "2026-10-20",
            "doc_type_name": "",
            "supplier_oper_name": "Хранение",
            "quantity": 0,
            "storage_fee": 1.2,
        }
    )
    return rows


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Тесты не трогают настоящую папку с ключами и базой."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "KEYS_FILE", tmp_path / "data" / "keys.json")
    monkeypatch.setattr(config, "OLD_DATA_DIR", tmp_path / "old")
    monkeypatch.delenv("WB_API_TOKEN", raising=False)
    monkeypatch.delenv("WB_PRICES_TOKEN", raising=False)
    return tmp_path / "data"


@pytest.fixture
def fake_wb() -> FakeWB:
    return FakeWB()


@pytest.fixture
def wb_client(fake_wb) -> WBClient:
    return WBClient("test-token", transport=httpx.MockTransport(fake_wb.handler), sleep=lambda _: None)


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return init_db(engine)


@pytest.fixture
def api(factory, wb_client):
    from torpeda.api import app as app_module

    def session():
        with factory() as s:
            yield s

    def client():
        yield wb_client

    app_module.app.dependency_overrides = {
        app_module.get_session: session,
        app_module.get_wb_client: client,
        app_module.get_wb_prices_client: client,
    }
    app_module.session_factory.cache_clear()
    original = app_module.session_factory
    app_module.session_factory = lambda: factory
    yield TestClient(app_module.app)
    app_module.session_factory = original
    app_module.app.dependency_overrides = {}
