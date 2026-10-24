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
from torpeda.wb_api.client import WBClient


class FakeWB:
    """Отвечает на запросы к хостам WB данными, похожими на настоящие."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.uploaded: list[dict] = []
        self.fail_upload = False

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
                                "type": "auto",
                                "startDateTime": "2026-10-29T00:00:00Z",
                                "endDateTime": "2026-11-05T23:59:59Z",
                            }
                        ]
                    }
                },
            )
        if path == "/api/v1/calendar/promotions/nomenclatures":
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
        if path == "/api/v2/upload/task":
            if self.fail_upload:
                return httpx.Response(400, json={"error": True, "errorText": "bad price"})
            self.uploaded.append(json.loads(request.content))
            return httpx.Response(200, json={"data": {"id": 777, "alreadyExists": False}, "error": False})
        return httpx.Response(404, json={"error": "not mocked", "path": path})


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
