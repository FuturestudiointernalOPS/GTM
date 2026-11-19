"""Tests for URL/handle normalization and the database-first store."""

from processing.deduplication import (
    JsonRecordStore,
    normalize_handle,
    normalize_url,
    partition_new,
)


def test_normalize_url_removes_noise():
    assert normalize_url("https://www.VK.com/red/") == "vk.com/red"
    assert normalize_url("vk.com/red") == "vk.com/red"
    assert normalize_url("HTTP://Example.com/") == "example.com/"
    assert (
        normalize_url("https://example.com/p?utm_source=x&a=1&fbclid=y")
        == "example.com/p?a=1"
    )
    assert normalize_url("   ") is None


def test_normalize_handle_strips_the_at_sign_and_lowers():
    assert normalize_handle("@Red") == "red"
    assert normalize_handle("Red") == "red"
    assert normalize_handle("  ") is None


def test_store_persists_and_reloads(tmp_path):
    path = tmp_path / "records.json"
    store = JsonRecordStore(path)
    store.add(urls=["https://vk.com/red"], handles=["@red"])

    assert store.contains_url("VK.com/red")
    assert store.contains_handle("RED")
    assert not store.contains_url("https://example.com")

    reloaded = JsonRecordStore(path)
    assert reloaded.contains_url("https://vk.com/red")
    assert reloaded.contains_handle("@red")


def test_partition_new_splits_by_url_and_handle():
    store = JsonRecordStore()
    store.add(urls=["https://vk.com/red"], handles=["@red"])
    items = [
        {"url": "https://vk.com/red", "handle": None},
        {"url": "https://t.me/blue", "handle": None},
        {"url": None, "handle": "@red"},
        {"url": None, "handle": "@new"},
    ]

    fresh, known = partition_new(items, store)

    assert fresh == [items[1], items[3]]
    assert known == [items[0], items[2]]
