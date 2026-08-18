"""アプリレビュー取得の中核。Apify Actor本体からもスモークテストからも同じ関数を使う。

依存は requests のみ。
- App Store: 公式RSSフィード (GET, JSON) — 2026-08-16にクラウドIPで200を実測済み
- Google Play: batchexecute エンドポイント (POST・無認証だが非公式) — google-play-scraper と同方式

両ストアの出力はキー集合を完全に一致させる（無い概念は None で埋める）。
これはREADMEの中核の売り文句「same field set」の実装保証なので崩さないこと。
"""
import json
import re
import time
from datetime import datetime, timezone

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

EMPTY_RETRIES = 2  # 空応答を引いたときに引き直す回数

FIELDS = ["store", "appId", "country", "lang", "reviewId", "userName", "rating",
          "title", "text", "appVersion", "date", "thumbsUp", "replyText"]


def _norm(d):
    return {k: d.get(k) for k in FIELDS}


def _parse_dt(raw):
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def appstore_reviews(app_id, country="us", max_pages=10, since=None, session=None):
    """App Store公式RSSからレビューを取る。1ページ50件・最大10ページ（RSS側の上限）。
    新着順なので、ページ全体が since より古くなったら打ち切る（無駄な取得をしない）。"""
    s = session or requests.Session()
    out = []
    for page in range(1, max_pages + 1):
        url = (f"https://itunes.apple.com/{country}/rss/customerreviews/"
               f"id={app_id}/sortby=mostrecent/page={page}/json")
        # Appleのフィードは散発的に「HTTP 200・中身が空」を返す（2026-08-18に100件中12件を実測）。
        # 正体はCDNが空応答をキャッシュしていること：同じURLは待っても空のまま（15秒待ちで0/12件）、
        # ダミークエリでキャッシュキーを変えると必ず返った（12/12件）。空を鵜呑みにすると
        # ページ打ち切りでそのアプリが丸ごと欠落するので、キーを変えて引き直す。
        entries = []
        for attempt in range(EMPTY_RETRIES + 1):
            u = url if attempt == 0 else f"{url}?cb={time.time_ns()}"
            r = s.get(u, headers={"User-Agent": UA}, timeout=30)
            if r.status_code != 200:
                entries = []
                break
            try:
                entries = r.json().get("feed", {}).get("entry", [])
            except ValueError:
                entries = []
                break
            if isinstance(entries, dict):  # 1件だけのときdictで返る
                entries = [entries]
            if entries:
                break
        got, page_dates = 0, []
        for e in entries:
            if "im:rating" not in e:  # フィード先頭にアプリ情報が混ざる形式への防御
                continue
            date = (e.get("updated") or {}).get("label")
            page_dates.append(_parse_dt(date))
            out.append(_norm({
                "store": "appstore",
                "appId": str(app_id),
                "country": country,
                "reviewId": (e.get("id") or {}).get("label"),
                "userName": ((e.get("author") or {}).get("name") or {}).get("label"),
                "rating": int(e["im:rating"]["label"]),
                "title": (e.get("title") or {}).get("label"),
                "text": (e.get("content") or {}).get("label"),
                "appVersion": (e.get("im:version") or {}).get("label"),
                "date": date,
            }))
            got += 1
        if got == 0:
            break
        if since is not None:
            known = [d for d in page_dates if d is not None]
            if known and max(known) < since:  # このページ全体が対象期間より古い
                break
    return out


_GP_URL = "https://play.google.com/_/PlayStoreUi/data/batchexecute"
# sort: 1=関連度順 2=新着順 3=評価順
def _gp_body(app_id, count, sort, token):
    inner = [None, None, [2, sort, [count, None, token], None, [None, 2]], [app_id, 7]]
    envelope = [[["UsvDTd", json.dumps(inner), None, "generic"]]]
    return {"f.req": json.dumps(envelope)}


def googleplay_reviews(app_id, lang="en", country="us", max_reviews=200,
                       sort=2, since=None, session=None):
    """Google Playのレビューを batchexecute (POST) で取る。ページングはトークン方式。
    新着順（sort=2）のとき、ページ全体が since より古くなったら打ち切る。"""
    s = session or requests.Session()
    out, token = [], None
    while len(out) < max_reviews:
        count = min(199, max_reviews - len(out))
        r = s.post(
            _GP_URL,
            params={"hl": lang, "gl": country},
            data=_gp_body(app_id, count, sort, token),
            headers={"User-Agent": UA,
                     "Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        r.raise_for_status()
        m = re.search(r"\)\]\}'\n\n?(.*)", r.text, re.DOTALL)
        data = json.loads(m.group(1) if m else r.text)
        payload = data[0][2]
        if not payload:
            break
        parsed = json.loads(payload)
        reviews = parsed[0] or []
        page_dates = []
        for rv in reviews:
            mapped = _gp_map(rv, app_id, lang, country)
            page_dates.append(_parse_dt(mapped["date"]))
            out.append(mapped)
        token = None
        try:
            token = parsed[-1][-1]
        except (IndexError, TypeError):
            pass
        if not reviews or not token:
            break
        if since is not None and sort == 2:
            known = [d for d in page_dates if d is not None]
            if known and max(known) < since:
                break
    return out


def _gp_map(rv, app_id, lang, country):
    def g(path):
        cur = rv
        for p in path:
            try:
                cur = cur[p]
            except (IndexError, KeyError, TypeError):
                return None
        return cur

    ts = g([5, 0])
    return _norm({
        "store": "googleplay",
        "appId": app_id,
        "country": country,
        "lang": lang,
        "reviewId": g([0]),
        "userName": g([1, 0]),
        "rating": g([2]),
        "title": None,  # Google Playのレビューにタイトルは無い
        "text": g([4]),
        "appVersion": g([10]),
        "date": (datetime.fromtimestamp(ts, tz=timezone.utc)
                 .isoformat().replace("+00:00", "Z"))
                if isinstance(ts, (int, float)) else None,
        "thumbsUp": g([6]),
        "replyText": g([7, 1]),
    })
