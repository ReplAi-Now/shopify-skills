# PageSpeed Insights

Google PageSpeed Insights (PSI) runs Lighthouse on a public URL and also returns real-user data from Chrome when Google has enough traffic for the site. It is free and works without a key for light use (a few requests per minute). For heavy use the merchant can create a free API key in Google Cloud; keep it in an environment variable, never in setup files or chat logs.

## Request

Run it for the home page and one top product page, both strategies:

```
https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=<URL-encoded page>&strategy=mobile&category=performance
https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=<URL-encoded page>&strategy=desktop&category=performance
```

- Use the agent's fetch or browser tool (or `curl -s "<url>" -o psi-home-mobile.json`). Each call takes 10-60 seconds.
- Save each response as a file, then summarise all of them in one run, home page first: `python3 scripts/psi_summary.py psi-home-mobile.json psi-home-desktop.json psi-product-mobile.json psi-product-desktop.json`. S1-S5 come from the first mobile file; the product page appears as its own rows.
- Use only the public storefront URL. Never put customer data or a preview token in the URL.
- If the store is password protected, PSI cannot test it. Say so and mark S1-S5 `unknown`.
- If the API answers 429 (too many requests), read the message. "Queries per day" means the shared no-key quota is used up for everyone (common): do not retry, add `&key=<key>` if the merchant has a key, otherwise use pagespeed.web.dev as below. "Queries per minute": wait a minute and retry once. Then mark `unknown` and give the merchant the link `https://pagespeed.web.dev/` to run it themselves and paste the scores.
- No fetch tool at all: ask the merchant to open `https://pagespeed.web.dev/`, test the home page, and send a screenshot of the mobile and desktop tabs.

## Fields the script reads

| What | JSON path |
|---|---|
| Strategy | `lighthouseResult.configSettings.formFactor` |
| Performance score (0-1, shown as 0-100) | `lighthouseResult.categories.performance.score` |
| Lab LCP, CLS, TBT, FCP, Speed Index | `lighthouseResult.audits["largest-contentful-paint" / "cumulative-layout-shift" / "total-blocking-time" / "first-contentful-paint" / "speed-index"].numericValue` |
| Field (real users, 75th percentile) | `loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS.percentile` (ms), `INTERACTION_TO_NEXT_PAINT.percentile` (ms), `CUMULATIVE_LAYOUT_SHIFT_SCORE.percentile` (CLS x 100) |
| Opportunities | audits with score under 0.9 that save time or bytes: `details.overallSavingsMs` / `details.overallSavingsBytes`, or for Lighthouse 12+ insight audits (`image-delivery-insight`, `render-blocking-insight`) `metricSavings.LCP` or `FCP` and `details.debugData.wastedBytes` |

Field data beats lab data when both exist: it is what real shoppers felt over the last 28 days. Lab data is one simulated mid-range phone on a slow connection.

## Explaining the numbers to the merchant (first time they appear)

- **Speed score (0-100)**: Google's overall rating from a test on a simulated phone. 90+ is good, under 50 is poor. Desktop is always higher; phones matter most because most shoppers in Egypt and the Gulf buy on phones.
- **LCP**: how many seconds until the main picture or headline shows. Good is 2.5 s or less.
- **CLS**: how much the page jumps while loading (people tap the wrong thing). Good is 0.1 or less.
- **INP**: how fast the page reacts after a tap. Good is 200 ms or less. When Google has no real-user data, use TBT (time the page is frozen during load) as a stand-in.

Never promise a sales increase from a speed fix. Say faster pages usually convert better and that the merchant should compare conversion rate in Shopify Analytics for 2-4 weeks before and after.
