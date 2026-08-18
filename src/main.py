"""App Review Monitor — Apify Actor本体。

入力のアプリ一覧（ID/パッケージ名/URLどれでも）を正規化し、両ストアのレビューを取得して
datasetへ出力する。課金は「出力した1レビュー＝1課金イベント」のみ
（apify-default-dataset-item の自動イベントは使わない＝二重課金の既知の罠を避ける）。

差分監視は sinceDays（相対・スケジュール実行向き）と sinceDate（絶対）の2本立て。
sinceDays を優先する——固定日付だけだと、毎日のスケジュール実行で取得範囲が
日ごとに広がり課金が膨らむ（公開前の独立批評で指摘された購入者の実損リスク）。
"""
import re
from datetime import datetime, timedelta, timezone

from apify import Actor

from .fetchers import appstore_reviews, googleplay_reviews

APPSTORE_URL = re.compile(r"apps\.apple\.com/(?:([a-z]{2})/)?[^/]*/?(?:app/)?[^/]*/?id(\d+)")
GOOGLEPLAY_URL = re.compile(r"play\.google\.com/store/apps/details\?[^ ]*\bid=([\w.]+)")


def parse_appstore(entry, default_country):
    entry = str(entry).strip()
    m = APPSTORE_URL.search(entry)
    if m:
        return m.group(2), (m.group(1) or default_country)
    digits = re.sub(r"^id", "", entry)
    return (digits, default_country) if digits.isdigit() else (None, None)


def parse_googleplay(entry):
    entry = str(entry).strip()
    m = GOOGLEPLAY_URL.search(entry)
    if m:
        return m.group(1)
    return entry if re.fullmatch(r"[\w.]+", entry) else None


def resolve_since(since_days, since_date):
    """sinceDays（相対）優先。sinceDateが不正な形式なら分かるエラーで止める。"""
    if since_days:
        return datetime.now(timezone.utc) - timedelta(days=float(since_days))
    if not since_date:
        return None
    try:
        dt = datetime.fromisoformat(str(since_date).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(
            f"sinceDate must be an ISO date like 2026-08-15, got: {since_date!r}")
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def newer_than(review, since):
    if since is None:
        return True
    raw = review.get("date")
    if not raw:
        return True  # 日付が取れない場合は捨てない（取りこぼしより過剰の方が安全）
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")) >= since
    except ValueError:
        return True


async def main():
    async with Actor:
        inp = await Actor.get_input() or {}
        country = (inp.get("country") or "us").lower()
        language = (inp.get("language") or "en").lower()
        max_per_app = int(inp.get("maxReviewsPerApp") or 100)
        since = resolve_since(inp.get("sinceDays"), inp.get("sinceDate"))

        targets = []
        for entry in inp.get("appStoreApps") or []:
            app_id, cc = parse_appstore(entry, country)
            if app_id:
                targets.append(("appstore", app_id, cc))
            else:
                Actor.log.warning(f"App Storeの指定を解釈できません: {entry!r}")
        for entry in inp.get("googlePlayApps") or []:
            package = parse_googleplay(entry)
            if package:
                targets.append(("googleplay", package, country))
            else:
                Actor.log.warning(f"Google Playの指定を解釈できません: {entry!r}")

        if not targets:
            raise ValueError(
                "No apps to fetch. Provide appStoreApps and/or googlePlayApps.")

        total = 0
        empty_targets = []
        for store, app_id, cc in targets:
            Actor.log.info(f"fetching {store}:{app_id} ({cc})")
            try:
                if store == "appstore":
                    pages = min(10, -(-max_per_app // 50))
                    reviews = appstore_reviews(app_id, country=cc,
                                               max_pages=pages, since=since)
                else:
                    reviews = googleplay_reviews(app_id, lang=language, country=cc,
                                                 max_reviews=max_per_app, since=since)
            except Exception as exc:
                Actor.log.exception(f"{store}:{app_id} の取得に失敗: {exc}")
                continue
            reviews = [r for r in reviews if newer_than(r, since)][:max_per_app]
            if reviews:
                await Actor.push_data(reviews)
                await Actor.charge(event_name="app-review", count=len(reviews))
            total += len(reviews)
            Actor.log.info(f"{store}:{app_id} -> {len(reviews)}件")
            if not reviews:
                empty_targets.append(f"{store}:{app_id}({cc})")

        if empty_targets:
            # 0件は「新着が無い」だけのこともあるが、ストア側が空を返し続けている場合もある。
            # 黙って0件を返すと利用者は障害に気づけないので、必ずログに残す（0件なので課金はしない）。
            Actor.log.warning(
                "レビューを1件も取得できなかった対象があります: "
                + ", ".join(empty_targets)
                + "。sinceDate以降に新着が無いか、ストア側が一時的に空を返している可能性があります。")
        Actor.log.info(f"done: {len(targets)}アプリ / {total}レビュー")
