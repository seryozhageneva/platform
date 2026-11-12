import asyncio
import base64

import httpx
import pytest
from mcp import Client

from mcp_servers.cloud.server import build_server
from mcp_servers.cloud.testing import TOKEN, FakeDisk, fake_server
from mcp_servers.cloud.yandex_disk import MAX_FILE_SIZE, YandexDisk, disk_path

LECTURE = b"%PDF-1.4 lecture about fractions"


def _call(server, path="/Лекции/лекция.pdf"):
    async def call():
        async with Client(server) as client:
            [tool] = (await client.list_tools()).tools
            assert tool.name == "get_file"
            assert tool.annotations is not None and tool.annotations.read_only_hint is True
            return await client.call_tool("get_file", {"path": path})

    return asyncio.run(call())


def test_file_is_downloaded_with_path_in_meta():
    disk = FakeDisk({"disk:/Лекции/лекция.pdf": LECTURE})
    result = _call(fake_server(disk))
    assert not result.is_error, result.content
    answer = result.structured_content
    assert answer["outcome"] == "ok"
    file = answer["file"]
    assert (file["name"], file["kind"], file["media_type"]) == (
        "лекция.pdf",
        "document",
        "application/pdf",
    )
    assert base64.b64decode(file["content_base64"]) == LECTURE
    assert file["size"] == len(LECTURE)
    assert file["meta"] == {"cloud_path": "disk:/Лекции/лекция.pdf"}


def test_token_goes_only_to_disk_api():
    disk = FakeDisk({"disk:/Лекции/лекция.pdf": LECTURE})
    assert not _call(fake_server(disk)).is_error
    for request in disk.requests:
        sent = request.headers.get("authorization")
        if request.url.host == "cloud-api.yandex.net":
            assert sent == f"OAuth {TOKEN}"
        else:
            assert sent is None


@pytest.mark.parametrize("path", ["/Лекции/лекция.pdf", "disk:/Лекции/лекция.pdf"])
def test_both_path_forms_are_accepted(path):
    disk = FakeDisk({"disk:/Лекции/лекция.pdf": LECTURE})
    assert _call(fake_server(disk), path).structured_content["outcome"] == "ok"


def test_missing_file_is_an_outcome_not_an_error():
    result = _call(fake_server(FakeDisk()))
    assert not result.is_error
    assert result.structured_content["outcome"] == "missing"
    assert result.structured_content.get("file") is None


def test_folder_is_refused_with_clear_message():
    disk = FakeDisk()
    disk.folders.add("disk:/Лекции/лекция.pdf")
    result = _call(fake_server(disk))
    assert result.is_error and "папка" in str(result.content)


def test_wrong_token_is_explained_without_token():
    result = _call(fake_server(FakeDisk({"disk:/Лекции/лекция.pdf": LECTURE}), "y0_other"))
    assert result.is_error and "не принял токен" in str(result.content)
    assert "y0_other" not in str(result.content)


@pytest.mark.parametrize("path", ["", "Лекции/лекция.pdf", "/", "disk:/", "/a\nb"])
def test_bad_path_is_refused_before_network(path):
    disk = FakeDisk()
    assert _call(fake_server(disk), path).is_error
    assert disk.requests == []


def test_path_form():
    assert disk_path(" /Лекции/a.pdf ") == "disk:/Лекции/a.pdf"


def _server_with(reply):
    client = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    return build_server(lambda: YandexDisk(TOKEN, client))


def _api_then(download):
    """API Диска отвечает как обычно, а скачивание — как скажет `download`."""

    def reply(request):
        if request.url.path == "/v1/disk/resources":
            return httpx.Response(200, json={"type": "file", "name": "a.pdf", "size": 10})
        if request.url.path == "/v1/disk/resources/download":
            return httpx.Response(200, json={"href": "https://downloader.disk.yandex.ru/d/1"})
        return download(request)

    return reply


def test_download_link_to_foreign_site_is_not_followed():
    calls = []

    def download(request):
        calls.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://evil.example/file"})

    result = _call(_server_with(_api_then(download)))
    assert result.is_error and "чужой сайт" in str(result.content)
    assert calls == ["downloader.disk.yandex.ru"]


def test_redirect_inside_yandex_is_followed():
    def download(request):
        if request.url.host == "downloader.disk.yandex.ru":
            return httpx.Response(302, headers={"location": "https://s1.storage.yandex.net/f"})
        return httpx.Response(200, content=b"%PDF")

    result = _call(_server_with(_api_then(download)))
    assert not result.is_error, result.content
    assert base64.b64decode(result.structured_content["file"]["content_base64"]) == b"%PDF"


def test_too_big_file_is_refused_by_size_and_by_content():
    def big_by_size(request):
        return httpx.Response(
            200, json={"type": "file", "name": "a.pdf", "size": MAX_FILE_SIZE + 1}
        )

    result = _call(_server_with(big_by_size))
    assert result.is_error and "10 МиБ" in str(result.content)

    result = _call(
        _server_with(
            _api_then(lambda request: httpx.Response(200, content=b"x" * (MAX_FILE_SIZE + 1)))
        )
    )
    assert result.is_error and "10 МиБ" in str(result.content)


@pytest.mark.parametrize("status", [500, 503])
def test_disk_failure_is_a_plain_message(status):
    result = _call(_server_with(lambda request: httpx.Response(status, text=TOKEN)))
    assert result.is_error and "не ответил" in str(result.content)
    assert TOKEN not in str(result.content)
