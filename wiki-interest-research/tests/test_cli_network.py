import json

from wiki_interest import cli
from wiki_interest.net import Client, NetworkError


def test_blocked_network_returns_domains_to_allow(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("WPV_CACHE_DIR", str(tmp_path))

    def blocked(self, url, params=None):
        raise NetworkError("HTTP 403 for https://www.wikidata.org/w/api.php: blocked by proxy policy")
    monkeypatch.setattr(Client, "get_json", blocked)
    code = cli.main(["resolve", "--topic", "astronomy", "--langs", "uk"])
    out = json.loads(capsys.readouterr().out)
    assert code == 4 and out["network_blocked"] is True
    assert "www.wikidata.org" in out["hint"] and "*.wikipedia.org" in out["hint"]
    assert "Do not retry" in out["hint"]
