"""Tests for the batch page reader. No network, HTML is mocked."""
import httpx
import pytest
import respx
from tenacity import wait_none

from integrations import webreader

HTML = (
    "<html><head><title>Page</title></head>"
    "<body><script>var x = 1;</script><p>Hello world.</p></body></html>"
)


@pytest.fixture(autouse=True)
def no_real_wait():
    webreader._read_with_retry.retry.wait = wait_none()


@respx.mock
def test_reads_and_strips_html():
    respx.get("https://a.example").mock(return_value=httpx.Response(200, text=HTML))

    (read,) = webreader.read_urls(["https://a.example"], max_chars=1000)

    assert read.url == "https://a.example"
    assert read.status == 200
    assert read.title == "Page"
    assert read.text == "Hello world."
    assert read.error is None


@respx.mock
def test_a_failure_is_isolated_per_url():
    respx.get("https://a.example").mock(return_value=httpx.Response(200, text=HTML))
    respx.get("https://b.example").mock(return_value=httpx.Response(404))

    reads = webreader.read_urls(["https://a.example", "https://b.example"])

    assert reads[0].text == "Hello world."
    assert reads[1].status == 404
    assert reads[1].error == "http error"


@respx.mock
def test_a_transient_error_is_retried():
    route = respx.get("https://a.example").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, text=HTML)]
    )

    (read,) = webreader.read_urls(["https://a.example"])

    assert read.text == "Hello world."
    assert route.call_count == 2


@respx.mock
def test_text_is_truncated():
    body = "<p>" + "a" * 5000 + "</p>"
    respx.get("https://a.example").mock(return_value=httpx.Response(200, text=body))

    (read,) = webreader.read_urls(["https://a.example"], max_chars=100)

    assert len(read.text) == 100


def test_a_batch_is_capped():
    with pytest.raises(ValueError, match="at most"):
        webreader.read_urls([f"https://{index}.example" for index in range(11)])
