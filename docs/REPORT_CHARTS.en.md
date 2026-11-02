# Lightweight report charts

This standalone helper renders complete, authorized static report data as a bar or time-series line chart and an equivalent table. It makes no network, PBX or HTML-table requests, uses no external libraries and has no animation. Axes start at zero. Keep counts, percentages and durations in separate charts; agent answers and AHT must not share an axis.

## Integration

Load `static/css/report-charts.css` and `static/js/report-charts.js` through the current theme's `theme_static`; defer the script before its callers. Loading the helper alone does not activate charts in existing reports.

```javascript
const host = document.getElementById('history-queue-wait-chart');
SaneQueueReportCharts.clear(host); // before each fresh request
// Caller must first validate its response generation, period and current grants.
SaneQueueReportCharts.render(host, {
  title: 'Queue average wait',
  subtitle: '2026-10-01 to 2026-10-02 · Asia/Tehran · permitted queues 8001, 8002',
  labels: ['8001', '8002'],
  series: [{label: 'Answered-call average wait', values: [0, null]}],
  unit: 'seconds'
});
// Also clear(host) on error, denied/incomplete results or view disposal.
```

`render(host, {title, subtitle, labels, series:[{label,values}], unit, maximum?, type?, x?, gaps?})` returns true when rendered, false on hidden/inactive hosts or invalid input. `clear(host)` removes the chart and download controls. Hosts must be connected, in `body.dataset.view === 'reports'`, and outside any `[hidden]` ancestor. No particular host ID is required.

## Data contract

- Each series has exactly as many values as the original labels array. Text limits: title 160, subtitle 1000, category 512, series label 120, unit 40 characters.
- Values must be finite nonnegative numbers up to `1e12`, or explicit null. Strings, undefined, sparse array slots, negative values and NaN are rejected. Null renders as a dash/Unknown; a reported zero has a zero marker. Unknown is never converted into zero or inferred.
- Input is bounded to 1000 categories. Bars paginate 12 categories per window; lines paginate 60 points. Only the first 4 series are displayed, with explicit disclosure if more are supplied. Current-window range, navigation and table are visible. This is neither ranking nor sampling. `type` defaults to `bar`; `line` accepts strictly increasing finite numeric `x` coordinates and optional boolean `gaps` (break before the point). Nulls break lines; zero remains a real point.
- Optional nonnegative `maximum` can extend the axis but never clip actual values. When nothing positive is known, the 0–1 drawing scale creates no data.
- The equivalent table is always available inside the labelled accessible-values disclosure. Full category labels appear there; long graphical labels are shortened. Display rounds to at most two decimal places; the helper computes no metrics or unit conversions.
- Supply denominator definitions, known-duration sample counts and coverage from the backend. The subtitle must identify the period, timezone, filters and partial/complete status. This helper invents neither missing statistics nor denominators. Numbers must already be masked by the backend.

## Data lifetime and downloads

The chart clears on the central `history-filters` input/change/submit events, `sanequeue:reports-loaded`, leaving reports, section hiding or host removal. Exports recheck visibility, view and a snapshot of current form values. PNG rechecks before drawing and again when its blob is ready. Changing and restoring a filter after its event cannot restore the cleared chart.

Callers must still abort obsolete requests and reject stale response generations. They must clear on errors and local filters outside the central form. This helper cannot stop a caller rendering a late response. No reusable report dataset is kept globally; its WeakMap holds only host validity metadata.

SVG exports are self-contained static images with title, period, units, legend and values. Optional PNG uses the same local SVG through browser Canvas/Image; unsupported rendering reports an error. Persian fonts use available browser/system fonts, with no external font fetch or embedded font. These are image exports, not official PDF/Excel exports or full-dataset downloads. A downloaded image cannot be recalled after permission revocation. Charts grant no additional access.

Run `node tests/report_charts_frontend.cjs` for the actual-script synthetic harness, without a server. It verifies values, bounds, safe text, export freshness and lifecycle; it is not a pixel/rendered-page browser acceptance test. Integrated page layout still needs visual review.


Integrated reports: answered/abandoned trends, queue ASA/wait percentiles, agent queue-segment answer counts and AHT (separate units), CDR trunk/DID aggregate traffic, elapsed shift evidence, full-period pause-call outcomes and temporal VIP volume/SLA. Null denominators/unknown durations remain unknown. These use the same response as the corresponding tables and introduce no extra HTTP/AMI queries. Input/change/submit, local CDR filters and the VIP SLA threshold invalidate pending charts. The screen inherits theme colors; image exports freeze the current theme background and colors. Empty scope displays no-data text and no image-export controls. Category labels allow up to 512 characters; the original table retains complete names.


2026-10-28: shared browser resize/theme lifecycle, keyboard inspection, Persian calendar integration and real image-download QA are documented in REPORTING_VISUAL_QA_20261028.fa.md. Existing synthetic node tests validate logic; the separate Chromium suite validates browser behavior. These do not certify every installed product page.
