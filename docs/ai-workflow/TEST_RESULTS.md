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

