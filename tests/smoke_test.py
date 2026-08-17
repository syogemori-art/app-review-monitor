"""スモークテスト：GitHubランナー（クラウドIP）から両ストアの実レビューが取れるかを実測する。
結果は relay-results/ にmarkdownで書き、ワークフローがコミットで返す。
題材アプリ＝LINE（日本のレビューが確実に毎日つく）。
"""
import datetime
import json
import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fetchers import appstore_reviews, googleplay_reviews  # noqa: E402

lines = ["# app-review-monitor smoke test（GitHubランナー実測）", ""]


def section(title, fn):
    lines.append(f"## {title}")
    try:
        reviews = fn()
        ok = len(reviews)
        with_text = sum(1 for r in reviews if r.get("text"))
        with_rating = sum(1 for r in reviews if isinstance(r.get("rating"), int))
        with_date = sum(1 for r in reviews if r.get("date"))
        uniq = len({r.get("reviewId") for r in reviews})
        lines.append(f"- 取得 {ok}件 / 本文あり {with_text} / 評価あり {with_rating} "
                     f"/ 日付あり {with_date} / reviewId重複なし {uniq}")
        for r in reviews[:2]:
            lines.append("```json")
            lines.append(json.dumps(r, ensure_ascii=False, indent=1)[:800])
            lines.append("```")
        return ok > 0 and with_rating == ok and uniq == ok
    except Exception:
        lines.append("```")
        lines.append(traceback.format_exc()[-1500:])
        lines.append("```")
        return False


results = {
    "appstore(jp/LINE)": section(
        "App Store: LINE (jp, 2ページ)",
        lambda: appstore_reviews(443904275, country="jp", max_pages=2)),
    "googleplay(jp/LINE)": section(
        "Google Play: LINE (jp, 最大120件)",
        lambda: googleplay_reviews("jp.naver.line.android", lang="ja",
                                   country="jp", max_reviews=120)),
    "googleplay(us/WhatsApp)": section(
        "Google Play: WhatsApp (us, 最大60件)",
        lambda: googleplay_reviews("com.whatsapp", lang="en",
                                   country="us", max_reviews=60)),
}

lines.append("## 判定")
for name, ok in results.items():
    lines.append(f"- {name}: {'✅' if ok else '❌'}")

out = pathlib.Path("relay-results")
out.mkdir(exist_ok=True)
ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
path = out / f"{ts}-actor-smoke.md"
path.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {path}")
sys.exit(0 if all(results.values()) else 1)
