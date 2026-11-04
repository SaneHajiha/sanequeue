# PBX call report visual QA

Final result: blocked.

The approved reference was supplied by the user. The existing PBX call report
has been adjusted locally for a denser date/filter area, KPI cards, charts and
table. The default daily time range is 00:00:00–23:59:59.

The checked-in `tests/render_pbx_visual_fixture.py` and
`tests/pbx_report_visual.cjs` render the real operations and report templates
and serve local assets without connecting to the PBX. In Chromium they
exercised reporting navigation, ten fixture rows and five cards, validated the
24-hour default values in the request, reset and invalid-time behavior, the
additional-filter disclosure, dark-mode activation and mobile page overflow.
The report chart frontend tests and 43 Python reporting tests also passed.

Visual comparison at the source's 1487 × 1058 viewport still finds differences
from the approved mock, including the global sidebar and header, KPI icons,
and some spacing and chart details. The endpoint chart now uses stacked,
independently inspectable series with five rows per page; a missing series does
not display a fabricated total. Extra filters and chart tools remain available.
The reference uses sample user identities and controls that must not be
presented as real data or capabilities without supporting backend evidence.
The offline screenshot uses the same viewport and synthetic records. The
reference is a generated mock, so its sample names, trends and absolute data
cannot be used as evidence about the live PBX.

The earlier test-server connection was rejected by the execution environment.
Network access was subsequently granted; a separate preview rollout and live
verification are required. Do not claim visual equivalence until verified.
