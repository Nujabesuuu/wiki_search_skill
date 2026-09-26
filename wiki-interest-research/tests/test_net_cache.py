import json
from datetime import date

import pytest

from wiki_interest.cache import Cache, merge_intervals, subtract_intervals
from wiki_interest.net import Client, NetworkError, NotFound, quote_title

D = date.fromisoformat


# ---------------------------------------------------------------- intervals

def test_subtract_intervals_finds_gaps():
    covered = [(D("2024-01-10"), D("2024-01-20")), (D("2024-02-01"), D("2024-02-05"))]
    gaps = subtract_intervals(covered, D("2024-01-01"), D("2024-02-10"))
    assert gaps == [(D("2024-01-01"), D("2024-01-09")),
                    (D("2024-01-21"), D("2024-01-31")),
                    (D("2024-02-06"), D("2024-02-10"))]


def test_subtract_intervals_fully_covered():
    assert subtract_intervals([(D("2024-01-01"), D("2024-12-31"))], D("2024-03-01"), D("2024-04-01")) == []


def test_merge_intervals_joins_adjacent_days():
    merged = merge_intervals([(D("2024-01-01"), D("2024-01-10")), (D("2024-01-11"), D("2024-01-20"))])
    assert merged == [(D("2024-01-01"), D("2024-01-20"))]


# ---------------------------------------------------------------- cache

def test_cache_roundtrip_and_fresh_tail_stays_uncovered(tmp_path):
    cache = Cache(tmp_path / "c.sqlite", today=D("2024-03-10"))
    rows = {D("2024-03-01"): 5, D("2024-03-09"): 7}
    cache.store_daily("en.wikipedia", "X", "all-access", D("2024-03-01"), D("2024-03-09"), rows)
    assert cache.load_daily("en.wikipedia", "X", "all-access", D("2024-03-01"), D("2024-03-09")) == rows
    # last 3 days are still "fresh" and must be refetched next time
    assert cache.missing_ranges("en.wikipedia", "X", "all-access", D("2024-03-01"), D("2024-03-09")) == [
        (D("2024-03-08"), D("2024-03-09"))]


def test_cache_totals_skip_incomplete_months(tmp_path):
    cache = Cache(tmp_path / "c.sqlite", today=D("2024-03-02"))
    cache.store_totals("en.wikipedia", {"2024-01": 100, "2024-02": 200})
    # Feb is not final on Mar 2 (fresh window reaches back into February)
    assert cache.load_totals("en.wikipedia", ["2024-01", "2024-02"]) == {"2024-01": 100}


def test_json_cache_ttl(tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    cache.put_json("k", {"a": 1})
    assert cache.get_json("k") == {"a": 1}
    assert cache.get_json("k", ttl=-1) is None


# ---------------------------------------------------------------- client

def _fake(responses):
    calls = []

    def transport(url, timeout):
        calls.append(url)
        return responses.pop(0)
    return transport, calls


def test_client_retries_then_succeeds():
    transport, calls = _fake([(503, b"", {}), (429, b"", {"Retry-After": "1"}), (200, b'{"ok": 1}', {})])
    sleeps = []
    client = Client(transport, sleep=sleeps.append, rate=0)
    assert client.get_json("https://x", {"a": "b c"}) == {"ok": 1}
    assert calls[0] == "https://x?a=b+c" and len(calls) == 3
    assert sleeps[1] >= 1.0  # honoured Retry-After


def test_client_404_raises_notfound_without_retry():
    transport, calls = _fake([(404, b"{}", {})])
    with pytest.raises(NotFound):
        Client(transport, sleep=lambda s: None, rate=0).get_json("https://x")
    assert len(calls) == 1


def test_client_gives_up_with_network_error():
    transport, _ = _fake([(500, b"", {})] * 3)
    with pytest.raises(NetworkError):
        Client(transport, retries=2, sleep=lambda s: None, rate=0).get_json("https://x")


def test_quote_title_escapes_slash_and_spaces():
    assert quote_title("AC/DC band") == "AC%2FDC_band"
    assert quote_title("Астрономія") == "%D0%90%D1%81%D1%82%D1%80%D0%BE%D0%BD%D0%BE%D0%BC%D1%96%D1%8F"
