# App Review Monitor — App Store & Google Play in one run

Fetch customer reviews for any mobile app from **both Apple App Store and Google Play** with a single Actor. Every review comes out with the **same field set** regardless of store, so the results drop straight into your dashboard, sheet, or LLM prompt — no post-processing.

## Why this Actor

- **Two stores, one schema.** Most review scrapers cover a single store. Here you get App Store and Google Play reviews in the same run, with identical field names. Store-specific fields (like Google Play's developer reply) are simply `null` where a store doesn't have them.
- **Monitoring-friendly.** Set `sinceDays: 1` and schedule the Actor daily: each run keeps only the reviews from the last 24 hours, and you pay only for those. The window moves with every run — no input editing needed.
- **Any storefront.** Works for the US, Japan, Germany, or any other country, including non-Latin languages (Japanese, Korean, ...).
- **Paste URLs or IDs.** `https://apps.apple.com/jp/app/line/id443904275` and `443904275` both work; same for Google Play package names and URLs.

## Input example

```json
{
    "appStoreApps": ["https://apps.apple.com/jp/app/line/id443904275"],
    "googlePlayApps": ["jp.naver.line.android"],
    "country": "jp",
    "language": "ja",
    "maxReviewsPerApp": 200,
    "sinceDays": 7
}
```

## Output example

One dataset item per review. **Both stores emit exactly these fields:**

```json
{
    "store": "googleplay",
    "appId": "com.example.app",
    "country": "jp",
    "lang": "ja",
    "reviewId": "aa0000bb-1111-2222-3333-ccc444ddd555",
    "userName": "T. S.",
    "rating": 2,
    "title": null,
    "text": "アップデートで使いにくくなりました",
    "appVersion": "26.11.0",
    "date": "2026-08-14T22:09:32Z",
    "thumbsUp": 5,
    "replyText": null
}
```

Field notes:
- `title` is always `null` for Google Play (its reviews have no title).
- `thumbsUp`, `replyText` (developer reply), and `lang` are always `null` for App Store — those concepts exist only on Google Play.
- `date` is ISO 8601. App Store dates carry the store's timezone offset; Google Play dates are UTC.

## Typical uses

- **Daily review monitoring** for your own app: schedule with `sinceDays: 1` and pipe new reviews to Slack, a spreadsheet, or an LLM for summarization.
- **Competitor watching**: track ratings and complaints for competing apps across both stores.
- **ASO / product research**: pull recent reviews of any category's top apps and mine them for feature requests and pain points.
- **AI agents**: this Actor can be called from the Apify MCP server, so your agent can look up "what do users complain about in app X" on demand.

## Limits

- **App Store**: the public RSS feed serves roughly the latest 500 reviews per storefront (10 pages × 50). That is plenty for monitoring new reviews, but this Actor is not a tool for bulk-downloading a full multi-year review history.
- **Google Play**: reviews are fetched newest-first with pagination; `maxReviewsPerApp` caps the depth.
- Rarely, a review has no parseable date. With `sinceDays`/`sinceDate` set, such reviews are kept (and charged) rather than silently dropped.

Note: store pages display counts of *ratings*, which include ratings without review text — so your review count will be lower than the store's headline number. That is normal.

## Pricing

You are charged per review delivered to the dataset (the `app-review` event) plus a small Actor-start fee — see the Pricing tab for current rates. With `sinceDays` monitoring, a typical daily run delivers only the handful of reviews an app received that day.

## FAQ

**Which apps can I fetch?** Any app publicly listed in the App Store or Google Play. No login, no cookies, no API key.

**Can I fetch multiple apps in one run?** Yes — pass any mix of App Store and Google Play apps.

**Can I fetch multiple countries in one run?** Partly. `country` applies to the whole run, but an App Store URL containing a country code (e.g. `apps.apple.com/de/...`) overrides it for that app. Google Play apps always use the run's `country`, so run once per country there.

**What does `language` do?** It sets the review language for Google Play only. App Store reviews follow the storefront country automatically.

**What happens if one app fails?** The failure is logged and the run continues with the remaining apps, so one bad ID never costs you the whole run.

**Where do the reviews come from?** App Store reviews come from Apple's public RSS feed; Google Play reviews come from the same unauthenticated endpoint the Play website itself uses (unofficial, so Google-side changes can require an Actor update — monitored and maintained).
