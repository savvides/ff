"""core/http cache behavior: freshness, the cache-forever and force-live paths,
and per-params keying. This is the mechanism that keeps us under Sleeper's rate
limit and keeps in-season data fresh, so it gets real coverage."""

import os
import time

import pytest
import responses

from ff.core import http
from ff.core.http import get_json

URL = "https://example.test/data"


@responses.activate
def test_fresh_entry_served_from_cache():
    responses.add(responses.GET, URL, json={"v": 1}, status=200)
    assert get_json(URL, ttl=100) == {"v": 1}
    assert get_json(URL, ttl=100) == {"v": 1}
    assert len(responses.calls) == 1  # second served from disk


@responses.activate
def test_expired_entry_refetches():
    responses.add(responses.GET, URL, json={"v": 1}, status=200)
    responses.add(responses.GET, URL, json={"v": 2}, status=200)
    assert get_json(URL, ttl=100) == {"v": 1}
    path = http._cache_file(URL, None)
    old = time.time() - 1000
    os.utime(path, (old, old))  # backdate the cache file past its TTL
    assert get_json(URL, ttl=100) == {"v": 2}
    assert len(responses.calls) == 2


@responses.activate
def test_ttl_none_caches_forever():
    responses.add(responses.GET, URL, json={"v": 1}, status=200)
    assert get_json(URL, ttl=None) == {"v": 1}
    path = http._cache_file(URL, None)
    old = time.time() - 10 ** 9
    os.utime(path, (old, old))
    assert get_json(URL, ttl=None) == {"v": 1}  # never expires
    assert len(responses.calls) == 1


@responses.activate
def test_use_cache_false_always_live_and_never_writes():
    responses.add(responses.GET, URL, json={"v": 1}, status=200)
    responses.add(responses.GET, URL, json={"v": 2}, status=200)
    assert get_json(URL, use_cache=False) == {"v": 1}
    assert get_json(URL, use_cache=False) == {"v": 2}
    assert len(responses.calls) == 2
    assert not http._cache_file(URL, None).exists()


@responses.activate
def test_corrupt_cache_refetches_instead_of_raising():
    responses.add(responses.GET, URL, json={"v": 1}, status=200)
    responses.add(responses.GET, URL, json={"v": 2}, status=200)
    assert get_json(URL, ttl=100) == {"v": 1}
    http._cache_file(URL, None).write_text("{ not valid json")  # corrupt it
    assert get_json(URL, ttl=100) == {"v": 2}  # silently refetched, no raise
    assert len(responses.calls) == 2


@responses.activate
def test_distinct_params_distinct_cache_files():
    responses.add(responses.GET, URL, json={"v": "a"}, status=200)
    responses.add(responses.GET, URL, json={"v": "b"}, status=200)
    a = get_json(URL, params={"p": 1})
    b = get_json(URL, params={"p": 2})
    assert a != b
    assert http._cache_file(URL, {"p": 1}) != http._cache_file(URL, {"p": 2})


@responses.activate
def test_http_error_raises():
    import requests
    responses.add(responses.GET, URL, body="not found", status=404)
    with pytest.raises(requests.exceptions.HTTPError):
        get_json(URL, use_cache=False)


@responses.activate
def test_non_json_body_raises():
    responses.add(responses.GET, URL, body="<html>nope</html>", status=200,
                  content_type="text/html")
    with pytest.raises(ValueError):
        get_json(URL, use_cache=False)
