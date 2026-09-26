"""Download pageviews (through the cache) for resolved articles and project totals."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

from .cache import Cache
from .langs import project
from .net import Client, NotFound, quote_title
from .resolve import Article
from .stats import month_bounds

PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
DATA_START = date(2015, 7, 1)   # first day of the pageviews API (agent=user split)


class UnknownProject(LookupError):
    pass


class Fetcher:
    def __init__(self, client: Client, cache: Cache, workers: int = 8):
        self.client = client
        self.cache = cache
        self.workers = workers

    # ---------------------------------------------------------------- per article
    def _download(self, lang: str, title: str, access: str, start: date, end: date) -> dict[date, int]:
        url = (f"{PAGEVIEWS}/per-article/{project(lang)}/{access}/user/{quote_title(title)}/daily/"
               f"{start:%Y%m%d}/{end:%Y%m%d}")
        try:
            items = self.client.get_json(url).get("items", [])
        except NotFound:          # no views at all in range (or brand-new article)
            return {}
        return {date(int(i["timestamp"][:4]), int(i["timestamp"][4:6]), int(i["timestamp"][6:8])): int(i["views"])
                for i in items}

    def prefetch(self, requests: list[tuple[str, str, str]], start: date, end: date) -> None:
        """Fill the cache for all (lang, title, access) in parallel, downloading only gaps."""
        jobs = []
        for lang, title, access in dict.fromkeys(requests):
            for s, e in self.cache.missing_ranges(project(lang), title, access, start, end):
                jobs.append((lang, title, access, s, e))
        if not jobs:
            return
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            results = list(pool.map(lambda j: self._download(*j), jobs))
        for (lang, title, access, s, e), rows in zip(jobs, results):
            self.cache.store_daily(project(lang), title, access, s, e, rows)

    def daily(self, lang: str, title: str, access: str, start: date, end: date) -> dict[date, int]:
        self.prefetch([(lang, title, access)], start, end)
        return self.cache.load_daily(project(lang), title, access, start, end)

    def article_bundle(self, articles: list[Article], start: date, end: date) -> dict[str, dict[date, int]]:
        """Daily views: 'total' = articles + their redirects (all access methods);
        'main' / 'main_desktop' = main articles only (used for the desktop-share bot check)."""
        out: dict[str, dict[date, int]] = {"total": {}, "main": {}, "main_desktop": {}}

        def add(key: str, rows: dict[date, int]) -> None:
            for d, v in rows.items():
                out[key][d] = out[key].get(d, 0) + v

        for a in articles:
            main = self.cache.load_daily(project(a.lang), a.title, "all-access", start, end)
            add("total", main)
            add("main", main)
            add("main_desktop", self.cache.load_daily(project(a.lang), a.title, "desktop", start, end))
            for r in a.redirects:
                add("total", self.cache.load_daily(project(a.lang), r, "all-access", start, end))
        return out

    @staticmethod
    def requests_for(articles: list[Article]) -> list[tuple[str, str, str]]:
        reqs = []
        for a in articles:
            reqs.append((a.lang, a.title, "all-access"))
            reqs.append((a.lang, a.title, "desktop"))
            reqs.extend((a.lang, r, "all-access") for r in a.redirects)
        return reqs

    # ---------------------------------------------------------------- project totals
    def project_totals(self, lang: str, months: list[str]) -> dict[str, int]:
        cached = self.cache.load_totals(project(lang), months)
        todo = [m for m in months if m not in cached]
        if todo:
            start, _ = month_bounds(todo[0])
            _, end = month_bounds(todo[-1])
            url = (f"{PAGEVIEWS}/aggregate/{project(lang)}/all-access/user/monthly/"
                   f"{start:%Y%m%d}00/{end:%Y%m%d}00")
            try:
                items = self.client.get_json(url).get("items", [])
            except NotFound:
                raise UnknownProject(
                    f"No pageview data for '{project(lang)}'. Is '{lang}' a valid Wikipedia language code?")
            fresh = {f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}": int(i["views"]) for i in items}
            self.cache.store_totals(project(lang), fresh)
            cached.update(fresh)
        return cached
