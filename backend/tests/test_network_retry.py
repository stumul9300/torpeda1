import httpx
import pytest

from torpeda.wb_api.client import NO_NETWORK_HINT, WBClient, WBError


def _client(fails: int, waits: list) -> tuple[WBClient, list]:
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) <= fails:
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=request)
        return httpx.Response(200, json={"ok": True})

    return WBClient("t", transport=httpx.MockTransport(handler), sleep=waits.append), calls


def test_retries_when_connection_fails():
    waits: list = []
    client, calls = _client(fails=2, waits=waits)
    assert client._request("GET", "https://common-api.wildberries.ru/x") == {"ok": True}
    assert len(calls) == 3 and waits == [2, 5]


def test_clear_message_when_network_is_down():
    waits: list = []
    client, calls = _client(fails=100, waits=waits)
    with pytest.raises(WBError) as e:
        client._request("GET", "https://common-api.wildberries.ru/x")
    assert NO_NETWORK_HINT in str(e.value) and "common-api.wildberries.ru" in str(e.value)
    assert len(calls) == 4
