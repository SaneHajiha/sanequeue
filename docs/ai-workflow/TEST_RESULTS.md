# beta.27 installed pilot acceptance — 2026-10-28

Full local regression checkpoint:1010passed,20skipped,334subtests in287.31s. Later installer/control changes receive separate targeted/Linux checks; no claim that this full run tested code written afterward. Existing30Chromium tests remain valid for unchanged shared frontend. Actual installed login/chart/calendar/API passed with no pageerrors; light/mobile had no horizontal overflow. Real UI downloads:CSV81272bytes(491data rows),XLSX58838bytes(491data+4header/metadata rows),PDF179182bytes(50pages; file signature/page structure checked, not all-page visual approval). Actual plans disable→restartblocked(ConditionResult=no)→enablepassed. Raw projection migration17603before/after,version10,cursor17603,10.7157swall/2.6754sCPU/23260KiBRSS. Corrected monthlyCLI scanned146790rows,validated endpointcounts/means and unionedpresence in53.3994swall/13.3087sCPU/32296KiBRSS atCPUQuota25%,MemoryMax256M. Initial repeatedidentityscan hit120s deadline; interval coalescing fixed the measured quadratic path without raising budgets. Existing-source installer failed safely and rollback was observed before legacy-alias/private-output fixes; mainlab installation then passed. Private recordings/data/screenshots/credentials remain outside source. No concurrent-call/RTP certification or host reboot.

# شواهد راه‌اندازی ابزارها — ۲۰۲۶/۱۰/۲۸

## مبنا و محدوده

Workspace: work/review-20261024. HEAD محلی e977516398db5b04309ddae11dffb3dbec4f09d9 روی feature/realtime-operations، با تغییرات انباشتهٔ قبلی؛ مبنای منتشرشدهٔ گزارش‌گیری 3e60acfdeaf6d992ee74b40ad4327d9a7f9e9e36 است. تغییرات این مرحله هنوز commit/push نشده‌اند. فایل‌های عملیاتی Flask/Jinja/AMI/PBX در این راه‌اندازی ویرایش نشدند. نتیجهٔ قبلی CI با ۸۳۱ تست متعلق به source منتشرشده است و اینجا مجدداً اجرا نشده است.

## اجراهای واقعی

| آزمون | نتیجه |
|---|---|
| npm ls --prefix tools/ui-workbench --depth=0 | پنج وابستگی pin شده نصب و تأیید شدند |
| npm run build --prefix tools/ui-workbench | موفق؛ بستهٔ مستقل Vite، JS حدود 6.54KB، CSS حدود 3.45KB و فونت محلی 50.68KB |
| npm run build-storybook --prefix tools/ui-workbench | موفق؛ ۱۶ story در index.json |
| npm test --prefix tools/ui-workbench | **11 passed (22.0s)، exit 0؛ بدون skipped** |
| screenshot regression | ۸ تصویر ثابت Windows: FA/EN × روشن/تیره × عرض 390/1280؛ مقایسهٔ دوباره موفق |
| axe | WCAG 2A/2AA/2.1AA در هشت ترکیب و حالت‌های بارگذاری/خالی/خطا/نبود مجوز/غیرفعال؛ بدون violation گزارش‌شده |
| تعامل | فیلتر ۶ به ۳ ردیف، راهنمای KPI، نام الزامی/تمرکز/موفقیت، retry، disabled و skip link |
| Storybook runtime | Story دکمه از iframe خروجی build در مرورگر واقعی باز و دیده شد |
| Figma | ساخت فایل و ۲۴ رنگ + ۸ توکن هندسه؛ ۳۰ variant؛ screenshot واقعی وضعیت و اصلاح بریدگی برچسب |
| npm audit --prefix tools/ui-workbench --json | total vulnerabilities: 0؛ گواه نبود تمام آسیب‌پذیری‌ها نیست |
| node --check | components.js و scripts/test.mjs موفق |
| git diff --check scoped | موفق؛ بررسی فقط فایل‌های مرتبط tracked |

نسخه‌ها: Node 24.22.1، npm 11.19.1، Storybook/html-vite 10.6.5، Vite 8.3.5، Playwright 1.64.1، axe-core/playwright 4.14.0، Chromium headless shell 156.0.8078.4 / build1248.

فرمان محیط اجرای فعلی (قبل از npm test):

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH='C:/Users/SaNe/Documents/Codex/2026-10-22/new-chat-3/work/playwright-browsers'
```

## ایرادهای کشف و رفع‌شده

- فونت در Vite dev با 403 می‌آمد: allow-list فقط به ریشهٔ workbench و پوشهٔ فونت موجود محدود شد؛ آزمون بارگذاری فونت و پاسخ‌های HTTP اضافه شد.
- locator نام مشترک select/region ابهام داشت: انتخاب به role=combobox محدود شد.
- component set در Figma برچسب بلند را می‌برید: Auto sizing و screenshot دوم رفع را تأیید کردند.
- بستن webServer از shell ویندوز معطل می‌ماند: runner مالک مستقیم Vite شد و پس از پایان Playwright آن را می‌بندد؛ اجرای نهایی exit 0 داشت. اجراهای اولیه با Ctrl+C متوقف و به عنوان اجرای کامل حساب نشدند.

## محدودیت‌ها

Storybook امکان نوشتن تنظیمات اختیاری global در C:/Users/SaNe/.storybook نداشت؛ build موفق بود و مجوزی برای آن درخواست/تغییر داده نشد. هشدار chunk بزرگ preview Storybook مربوط به ابزار dev است، نه بستهٔ عملیاتی. فایل workflow CI اضافه شده ولی هنوز Push/اجرای GitHub آن انجام نشده است. CI Linux مقایسهٔ تصویری Windows را اجرا نمی‌کند؛ UI_SKIP_VISUAL=1 خروجی تصویر می‌گیرد و تست عملکرد/axe را اجرا می‌کند.

نمونه دادهٔ ساختگی است. هیچ تماس، AMI، SQL، ضبط خصوصی یا ارسال پیام‌رسان برای این تست استفاده نشد؛ چیزی روی PBX نصب نشده است. Firefox/WebKit، پذیرش بصری همهٔ صفحات محصول، سناریوهای واقعی تلفنی و تست زیر بار در این مرحله اجرا نشده‌اند. تصاویر تازهٔ این workbench تأیید مستقل طراحی محصول نیستند. فونت Figma با runtime تفاوت مستند دارد. هیچ ادعای «۱۰/۱۰» یا «صفر باگ کل پروژه» نداریم.

# آغاز Diagnostics — شواهد مستقل این مرحله

- ذخیره‌ساز، worker، health و API با SQLite/Flask واقعی و دادهٔ ساختگی آزموده شدند. هیچ تماس، debug یا packet capture ایجاد نشد.
- source سلامت جدید به‌صورت کد فقط‌خواندنی روی آرشیو واقعی preview اجرا شد؛ CEL و queue_log heartbeat تازه، CDR unknown، media unavailable بود. این آزمون نصب API/worker روی سرور نیست.
- اصلاح CEL: userdeftype اختیاری، anchor v2 سازگار با نسخهٔ قبلی، Local END محافظه‌کار. backfill قبل از cursor انجام نمی‌شود.
- اصلاح جداگانهٔ reporting: source revision تا watermark batch، حفظ snapshot خروجی قدیمی، projection10 و bounded replay. تست EXPLAIN استفادهٔ rq_call را تأیید کرد.
- رگرسیون مرتبط گزارش‌گیری: 134 passed و26 subtests. کل‌پروژه پیش از اصلاحات نهایی بازبینی API:917 passed،18 skipped و304 subtests.
- پس از بازبینی،44 تست اختصاصی Diagnostics و28 subtests در9.19ثانیه موفق شدند؛ شامل سلب دسترسی در آخرین خواندن، افت نقش، متن خصوصی، صفحات پنهان، JSON عمیق، version اجباری و حالت‌های سلامت منبع.
- Playwright:15 passed در38.0ثانیه، شامل فهرست جدید37ماژولی، FA/EN،RTL/LTR،روشن/تیره،موبایل،axe و baselineهای قبلی. این تست، UI اختصاصی Diagnostics نیست. Build و Storybook مجدداً موفق شدند.
- وضعیت انتشار: تغییرات تازهٔ Diagnostics وprojection10 محلی‌اند؛ Push،فعال‌سازی worker،تغییر Dialplan یا rollout آن‌ها روی PBX انجام نشده است. تست 50/100تماس وRTP/چندنسخه‌ای باقی است.

اجرای سراسری بعد از اصلاحات بازبینی: **922 passed،18 skipped،304 subtests در177.36ثانیه**. بعد از آن فقط علامت‌گذاری partial/refresh_required برای افت دسترسی نهایی و تست آن افزوده شد. اجرای هم‌زمان targeted در بار محلی دو شکست init/CLI داشت؛ علت در حال بررسی است و از نتیجه حذف نمی‌شود.

بازبینی دو شکست موازی: در تست مستقل، گذشت۲ثانیه درDDL مشکل مهلت۱ثانیه‌ای schema را بازتولید کرد. بودجهٔ schema به۵ثانیه جدا شد، نوشتن۱ و خواندن۰٫۵ حفظ شدند. تست شروع۲ثانیه‌ای، توقف>۵ثانیه وrollback نوشتن دیرهنگام موفق‌اند. اجرای نهایی اختصاصی: **49 passed،30 subtests در9.66ثانیه**. شکست‌های قبلی ثبت شدند و نتیجهٔ جدید جای آن‌ها را برای کد اصلاح‌شده می‌گیرد.

## نتیجهٔ نهایی کد ثابت

پس از اصلاح مهلت schema و آخرین علامت partial، اجرای سراسری نهایی `python -m pytest tests --ignore=tests/historical -q` با **926 passed،18 skipped،306 subtests passed در154.79ثانیه** وexit0 پایان یافت. تست‌های انجام‌نشدهٔ محیطی جای پذیرش لینوکس/Redis/تلفنی نیستند. تست تخصصی49مورد ومرورگر15مورد نیز موفق بودند. هیچ نصب Diagnostics،راه‌اندازی worker،capture،کنترل تماس یا تست بار روی PBX انجام نشد.

## گزارش‌ساز سفارشی و آزمون ماهانه — ۲۰۲۶/۱۰/۲۸

- پیاده‌سازی: خروجی CSV/XLSX و برنامهٔ دوره‌ای مطابق تعریف سفارشی؛ snapshot/watermark اتمیک؛ حفظ تعریف هنگام ویرایش برنامه؛ دسترسی چندصفی مستقل از فیلتر نمایش؛ کنترل پاسخ دیررس، CSRF و اندازهٔ درخواست؛ رتبه‌بندی دوشاخصی و نمودار؛ تفکیک راهبری مرکز تلفن/کال‌سنتر؛ ایندکس جزئی RINGNOANSWER با fallback قدیمی.
- اجرای سراسری پیش از ایندکس: **970 passed،18 skipped،327 subtests** در168.58ثانیه. بعد از ایندکس و ابزار ماهانه: یک اجرا **1 failed،983 passed،18 skipped،327 subtests** در243.30ثانیه؛ تنها شکست، بازگشت deferred از CLI Diagnostics بود. علت واقعی از خروجی قبلی معلوم نشد. هیچ deadline تولیدی افزایش نیافت؛12تکرار همان تست و34تست مرتبط موفق شدند. assertion تست برای نمایش خروجی ساختاریافته اصلاح شد.
- اجرای نهایی آرام با ثبت موقت استثنا خارج مخزن: `python -m pytest tests --ignore=tests/historical -q -p diagnostics_probe`؛ **984 passed،18 skipped،327 subtests در173.09ثانیه**،exit0. این نتیجه علت شکست قبلی را اثبات یا رفع نمی‌کند. فایل‌های تولیدی Diagnostics در طول بررسی ثابت بودند.
-11harness اسکریپت واقعی frontend موفق: reports،builder،builderCSV،plans،rankings،navigation،charts،surveys،voice-feedback،generative وincident. CI برای موارد تازه به‌روز شد؛ CI راه دور اجرا یا Push نشده است.
-4تست Playwright/axe کاتالوگ در FA/EN و روشن/تیره در26.8ثانیه موفق بودند؛ این پذیرش تصویری صفحهٔ جدید رتبه‌بندی یا پنل زنده نیست.
- سرور آزمایشی:30هزار شناسهٔ تماس،33330مراجعه و193500رویداد ساختگی؛65بررسی اصلی و60تطبیق رتبه‌بندی روزانه موفق. CSV وXLSX هرکدام33330شناسهٔ مراجعهٔ یکتا داشتند. Excel فارسی نیز33330تاریخ شمسی، عنوان فارسی وRTL را تأیید کرد.
- parser خصوصی اولیهٔ آزمون فارسی، سلول‌های تهی حذف‌شده از OOXML را اشتباه می‌خواند. خواندن مختصات سلول اصلاح و همان فایل دوباره تأیید شد؛ فایل تولیدی تغییر نکرد.
- عدم پاسخ ماه:30رویداد،60ثانیه و30انتساب صحیح. نمودار روزانه30بازه و نقشهٔ ساعات جمع33330مراجعه را حفظ کردند. رتبه‌بندی و حضور ماهانه صریحاً محدود شدند؛ تکمیل آن‌ها به تجمیع پس‌زمینه نیاز دارد.
- تولید:331.055ثانیه،CPU89.166ثانیه وRSS27268KiB؛ verifier:83.709ثانیه،CPU40.141ثانیه وRSS34020KiB. سهم CPU نیم‌هسته و MemoryMax برابر256MiB بود؛ RSS با page cache مربوط به cgroup متفاوت است.
- PID استریسک133041 قبل و بعد ثابت ماند. هیچ restart، تماس، فرمان AMI یا تغییر Dialplan اجرا نشد. دو سرویس پنل در پایان active بودند.
- مسیر جدا: `/var/tmp/sanequeue-report-month-fecf0bce`. نسخهٔ جدید برنامه روی5000/18897 نصب نشد و دادهٔ ساختگی به پنل جاری متصل نیست.
- گزارش بازتولید: `REPORTING_MONTHLY_VALIDATION.fa.md` و `.en.md`؛ هش منابع: `REPORTING_BATCH_20261028_SHA256.json`. صوت واقعی،CDR/CEL،RTP،تماس هم‌زمان،پذیرش نصب چندنسخه‌ای وUI زنده از این آزمون نتیجه نمی‌شوند.
# UI reporting verification — 2026-10-28

Local branch `feature/realtime-operations`, base HEAD `e977516398db5b04309ddae11dffb3dbec4f09d9`, dirty source tree. This is not a pushed commit or deployed release. File-level evidence: `REPORTING_UI_20261028_SHA256.json`.

- `npm run build` in `tools/ui-workbench`: exit 0.
- `npm run build-storybook`: exit 0; optional global settings EPERM and manager bundle-size warnings remain. No PBX dependency installation.
- Chromium command from that folder: `UI_EXTERNAL_SERVER=1`, existing local Vite, workspace `PLAYWRIGHT_BROWSERS_PATH`, `node node_modules/@playwright/test/cli.js test`: **30 passed, 1.7 minutes, no retries/skips**, no snapshot-update flag. Includes existing catalog/workbench, new reporting matrix and both built Storybook stories.
- Prior intentional snapshot refresh: reporting-only **14 passed, 1.2 minutes**. Latest FA mobile light calendar, FA desktop dark charts, FA mobile light charts and EN desktop dark calendar inspected; prior captures also inspected. Updating baselines is not itself independent visual approval.
- Python: `../venv/Scripts/python.exe -m pytest tests/test_reporting_theme_integration.py tests/test_product_catalog.py tests/test_beta17_full_menu.py -q`: **12 passed, 33 subtests passed, 2.31s**. Scoped writable TEMP/TMP used.
- Every `tests/*frontend.cjs` executed sequentially with fail-fast: exit 0. Includes real shared chart, date-picker, periods and existing report/survey lifecycle harnesses.
- Fresh pre-change live UI screenshots and browser-only postload component injection with real report data reviewed. The latter is not installed runtime verification. Private session and actual PBX images remain outside the repository.

CUA bootstrap remains unavailable; approved standalone Playwright tests supplied browser evidence. Codex preview-open returned queued. Figma draft screenshot verification was quota-blocked. No push, server application deployment, Asterisk restart or PBX control occurred in this UI stage. See `../REPORTING_VISUAL_QA_20261028.fa.md` for scope and remaining acceptance.


## Queue unique-number increment — 2026-11-01
Local targeted pytest: 28 passed, 9 subtests before final edge-case addition; browser UI: 2 Chromium tests passed (FA/EN). Synthetic isolated 30-day server fixture: first attempt hit the 5-second read deadline while sorting; removing the unnecessary cross-queue sort succeeded at 10% one-core CPU / 128 MiB cgroup, 33,330 visits in 6.8 seconds including processing, 30 daily buckets. This is not a live-call or concurrency/load certification. Final targeted pytest after the edge-case and query-order changes: 29 passed, 9 subtests.

Installed-panel smoke uncovered a report-loaded race that cleared the independent result; the handler now invalidates on filter changes/submit, not on another request completing. Regression: 2 Chromium FA/EN cases passed including delayed report completion; 4 targeted backend tests passed.

Final installed-lab check at source c6d56630705d: the real report completed, day/queue tables and localized chart rendered; the main-report completion race was reproduced and fixed, then exercised twice in the installed Chrome harness. Queue fixture and real lab data remain private. Latest code was deployed only to the authorized laboratory; Asterisk PID was unchanged.

## Queue outcome views — 2026-11-01
A synthetic 33,330-visit, 30-day isolated lab archive completed in 14.903 seconds at a 10% single-core CPU quota and 128 MiB memory cap: 30,000 observed entries, 20,010 answered, 6,660 unanswered, 3,330 unresolved, plus 3,330 missing entries. Totals matched day and queue aggregations. This is not a live-call load test. Final local scoped Python: 34 passed, 11 subtests; Chromium: 7 passed for FA/EN, both categories, busy guard and distinct callers. Installed-runtime acceptance remains to be run.

Installed lab source 5cc8a9c0083b: 52 Linux tests passed before switching; Asterisk PID unchanged. Chrome smoke loaded both sections, their queue/day tables, four unanswered reasons and charts without page errors. On the same date/queue scope as overview, aggregates matched 491 visits, 43 answered and 448 abandoned; no entry was missing. Screenshot of the installed unanswered section was privately inspected. GitHub Tests and UI workbench both succeeded for the same source. This does not prove all report features or operational load acceptance.

Queue category export: 56 Python tests and 15 subtests passed across snapshot, existing export, PDF, builder API and outcome tests; XLSX/CSV/PDF counts matched summary for both categories, masked numbers remained masked, snapshot stayed stable after correction, CSRF and conflicting filters were rejected. Eight Chromium tests passed for outcome/unique interfaces including export request/CSRF. Theme rendering passed 4 tests and 2 subtests. A proposed command for a non-existent report_exports_frontend.cjs was not a test and failed with MODULE_NOT_FOUND; the actual browser/API export tests above were used. Installed-runtime export validation remains pending.

Final combined regression after outcome exports: 68 passed, 26 subtests; 8 Chromium tests passed. Included category snapshot correction, format/metadata checks, CSRF and conflict rejection, and existing exports/builder/PDF compatibility. Installed-runtime acceptance pending.

### آزمون سرور آزمایشی خروجی دسته‌های صف — 2026-11-01

نسخهٔ کد `0356b6b9a177e9d99950fb1a4c636c2a04329f6e` روی سرور آزمایشی نصب شد؛ ۹۶ آزمون لینوکسی موفق بود و شناسهٔ فرایند Asterisk تغییر نکرد. آزمون مرورگر از خود پنل برای بازهٔ 2026-10-23 تا 2026-10-27: CSV پاسخ‌داده‌شده ۴۳ ردیف، XLSX بدون پاسخ ۴۴۸ ردیف و PDF پاسخ‌داده‌شده ۴۳ ردیف ساخت و دانلود کرد؛ خطای JavaScript صفحه مشاهده نشد. تعدادها با خلاصهٔ همان بازه مطابقت داشتند. هر دو گردش GitHub Actions برای این commit موفق شدند. این آزمون‌ها تأیید تمام سناریوها و سازگاری محیط‌های عملیاتی نیستند.

نمودارهای روزانه و روز هفته برای گزارش‌های پاسخ‌داده و بدون پاسخ: شش آزمون مرورگر فارسی/انگلیسی شامل بررسی روز هفته، مقدار نمودار، تغییر فیلتر و بازنمایی مجدد موفق؛ ۱۱ آزمون یکپارچگی قالب و گزارش نیز موفق شد. این نتایج محلی هستند و به‌تنهایی تأیید محیط عملیاتی محسوب نمی‌شوند.

آزمون نسخهٔ نصب‌شده `0c823af492b42145f7a9437365ce53f15b8b0306` در سرور آزمایشی: ۹۶ آزمون لینوکسی موفق، فرایند Asterisk بدون تغییر، و مرورگر واقعی در هر دو نمای پاسخ‌داده و بدون پاسخ هر سه نمودار ساعتی، روزانه و روز هفته را بدون خطای JavaScript نمایش داد. این آزمون معادل ارزیابی کامل بصری یا تأیید کارکرد در همهٔ محیط‌ها نیست.

ریز مراجعه‌های پاسخ‌داده و بدون پاسخ با فیلتر دستهٔ مشترک، صفحه‌بندی و بررسی دوبارهٔ دامنهٔ دسترسی اضافه شد. ۳۴ آزمون سرویس و کوئری، و ۷ آزمون مرورگر از جمله صفحه‌بندی، خروجی HTML امن و تغییر فیلتر موفق بودند؛ این نتایج محلی هستند.

نمودار میانگین زمانی ساعتی به هر دو نمای صف اضافه شد؛ هفت آزمون مرورگر با رابط فارسی و انگلیسی و نمایش مقادیر نامعلوم موفق بود.

روی سرور آزمایشی، نسخهٔ `7c6347f8ffba5ae70384f7bbfcea5cbd46ea2e6b` پس از مطابقت SHA-256 بستهٔ دریافتی نصب شد؛ ۹۷ آزمون لینوکسی موفق و فرایند Asterisk بدون تغییر بود. آزمون مرورگر واقعی نمایش ۴۳ ردیف پاسخ‌داده و دو صفحهٔ متوالی ۱۰۰ تایی بدون پاسخ و هر چهار نمودار در هر نما را بدون خطای JavaScript تأیید کرد. گردش‌های Tests و UI workbench برای همین commit در GitHub موفق شدند.

PDF گزارش‌ساز صف برای ریز، گروه‌بندی و زمان‌بندی اضافه شد. آزمون محلی: ۸۳ مورد، ۲۸ زیرآزمون، و کنترل رابط زمان‌بندی موفق. اطلاعات تکمیل‌شدهٔ این بخش به‌تنهایی به معنی تکمیل همهٔ گزارش‌گیری یا تأیید محیط عملیاتی نیست.

نسخهٔ `d2a2a2920d201807fefa1365d42ab10b69807132` روی سرور آزمایشی نصب شد: ۱۲۱ آزمون لینوکسی موفق، PID استریسک بدون تغییر. از فرم گزارش‌ساز در مرورگر یک PDF گروه‌بندی‌شده ساخته و دانلود شد (۱ گروه، ۱۶۵۵۱ بایت)، بدون خطای JavaScript؛ هر دو CI همین commit موفق شدند. زمان‌بندی PDF سفارشی در تست یکپارچهٔ محلی، شامل ثبت برنامه، ثبت job با تعریف ثابت و ساخت فایل، موفق بود؛ زمان‌بندی واقعی روی سرور در این آزمون اجرا نشد.

گزارش شمارش شماره‌های یکتای ورودی CDR و محافظت سرشمارهٔ DID در خلاصهٔ تجمیعی اضافه شد. ۱۶ آزمون محلی و ۸ زیرآزمون برای طبقه‌بندی، مجوز، پوشاندن شماره، عدم نمایش دادهٔ خام، سقف و قالب موفق بود؛ دو آزمون مرورگر فارسی/انگلیسی نیز فیلتر جهت ورودی و پاک‌شدن نتیجه پس از تغییر فیلتر را تأیید کردند.

نسخهٔ `ef705463736e59afa2b9558a4f10237b6305068f` روی سرور آزمایشی نصب شد؛ ۱۳۳ آزمون لینوکسی موفق و PID استریسک بدون تغییر بود. هر دو CI همین commit موفق شدند. در آزمون پنل واقعی، گزارش CDR یکتا با بازهٔ آزمون صفر بخش ورودیِ ثبت‌شده نشان داد و رابط وضعیت خالی را بدون خطای JavaScript نمایش داد. به دلیل نبود ترانک خارجی، این مشاهده تأیید تماس ورودی واقعی نیست؛ دادهٔ ساختگی در آزمون‌های جداگانه مسیر تکرار، نامعلوم و محدودیت را پوشش داد.

حریم خصوصی نمای پیگیری رهاشدن: ۲۱ آزمون پایتون و ۱۰ زیرآزمون شامل لغو مجوز در حین خواندن، و آزمون مرورگر تغییر فیلتر، خروج از صفحه و پاسخ دیررس موفق شدند. ثبت عملیات پیگیری و ارتباط اثبات‌شده با تماس خروجی همچنان تکمیل نشده است.

نسخهٔ `0d1ec8fad1989600008c99e1dbd4c11bc8008a4d` روی سرور آزمایشی با ۱۴۳ آزمون لینوکسی موفق نصب شد و PID استریسک تغییر نکرد. در مرورگر واقعی، صفحهٔ پیگیری با ۱۰۰ ردیف خوانده و پس از تغییر فیلتر پاک شد؛ خطای JavaScript نبود. آزمون لغو دسترسی و پاسخ دیررس به‌صورت محلی شبیه‌سازی شد. هر دو CI این commit موفق شدند. این اصلاح جایگزین توسعهٔ ثبت عملیات پیگیری و اثبات ارتباط تماس خروجی نیست.

ثبت اقدام دستی پیگیری مراجعهٔ رهاشده: ۴۴ آزمون و ۲۸ زیرآزمون محلی شامل CSRF، محدودهٔ صف، مجوز شماره، تکرار امن درخواست، تغییرناپذیری سوابق و عدم ادعای اثبات تماس؛ دو آزمون مرورگر شامل خروجی متن امن، ارسال CSRF و پاک‌شدن هنگام تغییر فیلتر موفق شدند. اتصال اثبات‌شده به CDR و آزمون ترانک خارجی هنوز باز است.

نسخهٔ `c54916ce3b9a621456f06f2de41e852b8849b904` روی سرور آزمایشی نصب شد؛ ۱۵۶ آزمون لینوکسی موفق و PID استریسک بدون تغییر بود. پیش از نصب، از history و quality نسخهٔ پشتیبان SQLite گرفته شد. در مرورگر واقعی مشاهدهٔ فرم و تاریخچه، و پاک‌سازی با تغییر فیلتر، بدون خطای JavaScript بررسی شد؛ ثبت POST در آزمون یکپارچهٔ محلی انجام شد و برای جلوگیری از افزودن یادداشت ساختگی به آرشیو سرور، POST زنده اجرا نشد. هر دو CI همین commit موفق شدند.

اتصال دستی شواهد احتمالی CDR خروجی به اقدام پیگیری: ۴۶ آزمون و ۲۸ زیرآزمون محلی شامل جهت خروجی، تطبیق شماره، بازه، رد شواهد ناقص، مجوز مدیر سراسری، CSRF، تکرار امن و عدم ادعای رابطهٔ قطعی؛ سه آزمون مرورگر شامل اتصال و پاک‌سازی پس از تغییر فیلتر موفق شدند. تطبیق شماره رابطهٔ علّی یا هویت شخص را اثبات نمی‌کند.

نسخهٔ `a58aa685e6ab76a1fb330eee87e6dc7e0b419ca0` روی سرور آزمایشی با ۱۵۸ آزمون لینوکسی موفق نصب شد؛ PID استریسک تغییر نکرد و پیش از نصب از آرشیو و quality نسخهٔ SQLite گرفته شد. آزمون واقعی پنل و جست‌وجوی کاندید برای یک رهاشدن با نتیجهٔ صفر و بدون خطای JavaScript موفق شد. پیوند POST و شواهد دارای CDR در تست مستقل با دادهٔ ساختگی و آزمون مرورگر شبیه‌سازی‌شده بررسی شد، چون سرور ترانک خارجی ندارد؛ این نتیجه اثبات تماس بیرونی واقعی نیست. هر دو CI همین commit موفق شدند. یک آزمون محلی اضافه نیز ثابت کرد اصلاح بعدی CDR، شاهد ثبت‌شده را تغییر نمی‌دهد و درخواست تکراری با محتوای تغییرکرده رد می‌شود.

گزارش‌ساز مستقل و محدود CDR برای مدیر سراسری: ستون و گروه مجاز، پیش‌نمایش و CSV، بررسی دوبارهٔ مجوزها و پوشاندن شماره، سقف‌های شمارش/بایت و خنثی‌سازی فرمول. ۴۶ آزمون و ۲۱ زیرآزمون پایتون شامل دامنه، خروجی و محدودیت‌ها و دو آزمون مرورگر فارسی/انگلیسی موفق شدند. Excel/PDF/خروجی پس‌زمینه و زمان‌بندی CDR هنوز توسعه‌اند.

نسخهٔ `342c4aa6b731ae44bc9fe31eb2a4a7273a1fba04` روی سرور آزمایشی نصب شد؛ ۱۷۵ آزمون لینوکسی موفق و PID استریسک بدون تغییر بود. در مرورگر واقعی، گزارش‌ساز CDR بازهٔ آزمایشی ۱۲۰۲ بخش را در دو گروه نمایش و CSV را دانلود کرد، بدون خطای JavaScript. نمودار گروهی جدید جداگانه با دو آزمون مرورگر فارسی/انگلیسی بررسی شد. این نتیجه معادل آزمون بار همزمان یا تأیید ترانک خارجی نیست.

آزمون محلی جداگانهٔ `python tools/benchmark_cdr_builder.py` روی پایگاه موقت ساختگی، ۳۰هزار بخش و یک گروه را با مجموع و میانگین موردانتظار در ۰٫۵۴۷ ثانیه زمان دیواری و ۰٫۴۸۴ ثانیه CPU روی همین رایانه پردازش کرد. این عدد تخمینی برای سرور تلفنی یا بار همزمان نیست و دیتابیس واقعی را لمس نمی‌کند.

نسخهٔ `8f7c3baa1de7dc09ba4f889c9eada40e660ba28f` روی سرور آزمایشی نصب شد؛ ۱۷۵ آزمون لینوکسی موفق و فرایند Asterisk بدون تغییر بود. در مرورگر واقعی، دو گروه CDR در نمودار و جدول نشان داده شدند؛ مجموع گروه‌ها با ۱۲۰۲ بخش منبع برابر بود و CSV با موفقیت دریافت شد. هر دو گردش CI همین commit موفق شدند. این بررسی به معنی تست زیر بار همزمان یا سازگاری تمام نسخه‌ها نیست.

خروجی پس‌زمینهٔ CDR در قالب‌های CSV، Excel و PDF روی snapshot زمان شروع پردازش اضافه شد. مجوز مدیر سراسری و تغییر فهرست صف‌ها پیش از انتشار و دریافت مجدداً بررسی می‌شود. ۸۴ آزمون و ۳۴ زیرآزمون محلی، شامل قالب‌ها، ثابت‌ماندن داده پس از خواندن، لغو دسترسی و سقف‌ها، و سه آزمون مرورگر موفق شدند. زمان‌بندی CDR هنوز اضافه نشده است.

خروجی پس‌زمینهٔ CDR اکنون تعریف و فیلتر را در صف ذخیره می‌کند و یک تصویر واحد از داده را هنگام شروع کارگر می‌خواند؛ فایل ممکن است با پیش‌نمایش زودتر تفاوت داشته باشد. اطلاعات فیلتر در مرکز خروجی و فایل Excel/PDF نمایش داده می‌شوند. مجوز مدیر، سطح نمایش شماره و مجموعهٔ صف‌ها تا زمان انتشار و دریافت بازبینی می‌شود. آزمون محلی نهایی: ۸۸ آزمون و ۳۴ زیرآزمون شامل لغو دسترسی پس از خواندن؛ سه آزمون مرورگر موفق. زمان‌بندی CDR هنوز اضافه نشده است.

نسخهٔ `b6796ba9ef26fc6303825f9963fb548618e31498` روی سرور آزمایشی نصب شد؛ ۱۹۲ آزمون لینوکسی موفق و PID استریسک بدون تغییر بود. در مرورگر واقعی برای گزارش CDR گروه‌بندی‌شده، Excel و PDF پس‌زمینه ساخته و دانلود شدند؛ هر کدام دو ردیف داشتند و خطای JavaScript ثبت نشد. هر دو CI همین commit موفق شدند. این آزمون معادل بار واقعی همزمان یا ترانک خارجی نیست.
# Last observed queue answer — test server

Outbound aggregate CSV export local validation: 33 tests and 11 subtests passed, including totals reconciliation for all three tables, CSRF, masking, export grant and revocation after generation; 3 browser workbench tests covered Persian/English and a CSRF-authenticated download. This does not validate external trunks or production load.

Outbound aggregate XLSX/PDF local validation: 55 tests and 23 subtests across outbound, PDF, XLSX and existing background exporters, plus a subsequent 10-test outbound rerun including PDF permission revocation. Five browser workbench tests passed for Persian/English and CSV/XLSX/PDF selection. One synthetic Persian PDF page was rendered and visually inspected. PDF is limited to 100 rows, 20 pages and 4 MiB. This evidence does not establish production load safety.

On lab revision 0c1dd74, 44 targeted Linux tests passed and Asterisk remained running. Browser downloaded XLSX, but PDF fetch returned an intermediary 204 even though direct server requests returned 200. The client export path was changed to an extensionless endpoint; its local regression passed (26 tests and 4 subtests; 5 browser tests), but live browser revalidation is still required.

Revisions f051b8e and d0e5dfa each passed targeted Linux tests and preserved the Asterisk PID. Browser PDF fetch still returned an intermediary 204 with both the extensionless route and generic attachment MIME; direct authenticated requests returned a valid PDF. This is not accepted as a successful browser PDF download. The standard PDF MIME was restored; the cause in the browser/network path remains unconfirmed.

Revision 5f928cd passed 14 targeted Linux tests and both CI workflows; Asterisk PID remained unchanged. On the lab browser, all three CSV and all three XLSX files downloaded. Authenticated direct requests returned valid PDF signatures for all three tables; browser PDF fetch remained unaccepted due to the previously recorded 204. The selected period had no recorded outbound segments, so non-empty values remain validated with synthetic fixtures only.

An additional native-form browser PDF download attempt on b7938d5 did not resolve the issue; it was reverted, preserving the original header-based CSRF contract and visible failure feedback. Wait-distribution CSV was added for authorized admin/supervisor scope; 34 targeted tests and 10 subtests and 13 browser workbench tests passed locally, including aggregate reconciliation, CSRF and revoked-export permission. Lab verification remains pending.

Lab revision 107b5e2 passed 25 targeted Linux tests with Asterisk PID unchanged. Authenticated browser downloaded both answered and unanswered wait CSVs; each contained seven buckets plus the unknown row and produced no page errors. This does not resolve the separately documented browser PDF response issue.

Lab revision 301a9e5 passed 15 targeted Linux tests, preserved the Asterisk PID, and the authenticated browser downloaded all three aggregate CSV files with UTF-8 BOM and Persian headers without page errors. The selected archive period had no observed outbound segments, so nonempty values were verified only with synthetic fixtures. Both CI workflows passed for 301a9e5.

Outbound dashboard local validation: 40 tests and 17 subtests passed across CDR, access, builder and theme integration, including permission revocation after archive read. Two browser workbench tests passed in Persian and English with a synthetic dataset and escaped content. These results do not validate external trunks, human contact or production load.

Outbound test-server installation: 5ec1c9 passed 270 Linux tests; the UI-only follow-up 7cc317 passed 10 targeted Linux tests. Asterisk retained the same PID during both switches. The authenticated browser opened the outbound menu without page errors; the selected lab period had zero observed outbound segments, so only the empty state was validated on that archive. Non-empty arithmetic was checked using isolated synthetic fixtures; no external trunk was available.

Queue wait distributions: local queue outcomes/analytics/query suite 32 passed and 15 subtests, plus a boundary rerun with 9 passed and 6 subtests. Seven browser workbench tests covered Persian and English, answered and unanswered views, unknown waits, redraw and clearing on filter change. All use local synthetic data; this entry does not assert telephony or production-load acceptance.

Ready-agent alert: 27 policy/outbox/messaging/system-alert tests and 3 subtests passed locally, including an explicitly empty member set, missing member field and transition deduplication. Actual message delivery and stale collector transitions were not tested in this increment.

On the lab server revision 734b119 passed 264 Linux tests; the existing Asterisk process remained unchanged. The authenticated browser displayed both wait distributions against the lab archive: 43 answered and 448 unanswered known waits, each reconciling with seven buckets, with no page errors. This does not demonstrate actual messaging delivery, external trunks or production load behavior.

Revision 61d11c5 adds the latest observed queue answer per agent and queue for visits entering the selected range. Targeted tests covered overlapping agent membership and different ranges; 38 passed and 2 subtests passed locally. The test server passed 236 Linux tests, Asterisk retained the same PID, and the authenticated browser displayed the column and four rows without page errors. This is not the last call across non-queue calls or evidence of complete historical coverage.

# CDR scheduled custom reports — local validation

The CDR plan freezes its definition and non-date filters, rechecks global scope and current permissions, and uses the background worker-start snapshot. Local targeted reporting suite: 128 passed and 36 subtests passed; plan frontend checks and 3 browser workbench tests passed. On the test server, revision 98d93d2 passed 217 Linux tests; Asterisk remained running with the same PID. The actual panel saved a disabled CDR plan, manually dispatched a grouped PDF with two rows, downloaded it, and archived the plan, without browser errors. Automatic firing at the scheduled wall-clock time was not tested in the live server. These results do not prove cross-version telephony compatibility or production load safety.


Outbound dashboard filters: 28 targeted backend tests and 4 subtests passed; 6 browser workbench tests passed. They use controlled fixtures and mocked downloads; they do not prove the real browser PDF download or live trunk behavior.

On the lab, revision 60f396e passed 27 Linux tests with the Asterisk PID unchanged. An authenticated Chrome session on port 5000 applied origin/status filters and downloaded the days CSV with filter metadata and no page errors. The selected range had zero outbound segments, so nonempty real-trunk data and real browser PDF export remain unverified.

Queue outcome aggregate CSV: 36 local tests and 18 subtests passed for outcome, analytics and query suites; 9 browser workbench tests passed. Covered per-queue/day/reason reconciliation, CSRF, scope, permission revocation, empty data and mocked browser download. This does not establish real trunk or operational load acceptance.

On the lab, revision 0c51483 passed 29 Linux tests; Asterisk PID remained unchanged. An authenticated Chrome session on port 5000 downloaded five queue/day/reason CSV files for answered and unanswered visits and each file count reconciled to the API summary, with no page errors. This verifies the selected archived lab interval only, not external trunks or production load.

Queue outcome hourly table and CSV: 36 targeted backend tests with 20 subtests and 9 browser workbench tests passed locally; hours reconcile to the same category totals with existing access checks. Fixture tests do not establish actual PBX load acceptance.

On the lab, revision 76a9947 passed 29 Linux tests with Asterisk PID unchanged. Authenticated Chrome on port 5000 displayed hourly tables and downloaded both hourly CSV files; each had 14 rows and counts reconciled with the category API totals, without browser page errors. This is evidence for the selected lab archive interval, not production load or external trunk acceptance.

Queue outcome weekday table/CSV: 37 targeted tests and 22 subtests passed, including Tehran day-boundary and weighted sample checks; 9 browser workbench tests passed. This fixture evidence does not establish real trunk or operational load acceptance.

On the lab, revision cbef95d passed 30 Linux tests with the Asterisk PID unchanged. Authenticated Chrome on port 5000 displayed both weekday tables and downloaded both CSVs; each had four rows, and the category totals reconciled with the report API. No page errors. This verifies the chosen lab archive interval, not real external trunk behavior or production load.

EXITWITHKEY queue_log parser fix: 49 tests and 22 subtests passed locally across queries, outcomes, archive, analytics. Four-field EXITWITHKEY uses recorded wait, missing fourth field stays unknown, timeout and empty-queue events remain correctly parsed. Lab read-only inspection found zero EXITWITHKEY rows; pre-existing projections on other installations require controlled remediation, not an automatic full replay. Source format: https://docs.asterisk.org/Operation/Logging/Queue-Logs/

On the test server revision 6030d6a passed 50 Linux tests including the EXITWITHKEY parser regression. The Asterisk PID remained unchanged. No EXITWITHKEY events existed in the lab archive when inspected, so a live queue-exit scenario and remediation for older projections remain open.

Bounded EXITWITHKEY repair: 37 targeted tests and 17 subtests passed locally; tests cover continuation, small batch caps, failure rollback and pinned historical export snapshot. No automatic background full replay is started. Production load, upgrade scheduling and cross-version PBX behavior are not established.

On the lab, revision d7d80a2 passed 33 Linux tests, including repair continuation and rollback on isolated test databases; Asterisk PID remained unchanged. No repair was applied to the lab archive because read-only inspection found no EXITWITHKEY records. Large-archive performance and automatic maintenance scheduling remain unverified.

Queue positions: 40 local tests and 17 subtests passed for explicit entry/exit, conflicts, unknowns, re-entry, authorized queue scope and bounded backfill; 9 UI workbench tests passed. Values are current projections and are not in pinned background exports. No cross-version live acceptance or large-archive load claim.

On the lab, revision 6988731 passed 36 Linux tests with Asterisk PID unchanged. Authenticated Chrome displayed entry/exit column headings in both queue outcome detail views with no page errors. Bounded historical position repair was started and checkpointed on the lab archive in small batches; it was not yet complete at the end of this run. Individual legacy positions and production-scale completion remain unverified.

