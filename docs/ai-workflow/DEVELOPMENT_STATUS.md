# Current pilot deployment — 2026-10-28

beta.27 is installed on lab port5000 and read-only preview18897. Shared archive uses one canonical importer/export/plans set. Actual existing login, charts/calendar, CSV/XLSX/PDF downloads and plans systemd condition were verified. Projection-copy migration retained17603events and reachedversion10. Monthly private engine passed53.4swall/13.3sCPU/~32MiBRSS at25%onecore after fixing repeated identity scans. Legacy state alias and private-output upgrade permissions were corrected after observed rollback. Source publication is on feature/reporting-phase2/PR14. See ../PILOT_BETA27.fa.md. This supersedes earlier not-deployed statements; explicit reporting development gaps remain.

# وضعیت راه‌اندازی — ۲۰۲۶/۱۰/۲۸

| ابزار | وضعیت واقعی |
|---|---|
| AGENTS / اسناد | متن تأییدشده در ریشه و docs/ai-workflow ثبت شد |
| UI UX Pro Max | CLI 2.15.0 با init --ai universal --offline؛ skill پروژه در .agents/skills/ui-ux-pro-max؛ قواعد وضعیت، برچسب و کیبورد بررسی شدند |
| Figma | فایل جدید قابل ویرایش ساخته شد؛ ۲۴ متغیر رنگ، دو مرجع روشن/تیره و چهار خانواده با مجموع ۳۰ variant؛ اندازه‌گذاری برچسب بلند پس از screenshot اصلاح شد |
| Storybook | HTML/Vite 10.6.5؛ build واقعی موفق؛ stories حالت‌ها و چهار خانواده |
| Workbench | Vite 8.3.5؛ build واقعی موفق؛ localhost:18910؛ فقط دادهٔ ساختگی |
| Playwright | 1.64.1، Chromium headless shell 156، axe 4.14.0؛ آزمون مرورگر واقعی محلی؛ شواهد در TEST_RESULTS.md |
| Product Design | skill خوانده شد؛ audit کامل محصول زنده هنوز انجام نشده |
| CUA | bootstrap پیشین خطا داشت؛ تست Playwright مستقل مجاز اجرا شد؛ رفع CUA ادعا نمی‌شود |
| Canva | برای پایه‌های کدی این مرحله asset تازه‌ای لازم نبود؛ هیچ طرح یا همگام‌سازی Canva ادعا نمی‌شود |

وابستگی‌ها فقط در tools/ui-workbench هستند؛ مرورگر در cache محلی work است. چیزی روی PBX نصب نشده است. فایل‌های node_modules/build/report از Git مستثنا و تصاویر مرجع ساختگی قابل ثبت‌اند.

راهنمای اجرا: tools/ui-workbench/README.md. نشست Figma و نگاشت کامپوننت‌ها در FIGMA_REFERENCES.md و design-manifest.json آمده است. همگام‌سازی Figma فعلاً دستی و بازبینی‌شده است؛ Code Connect یا sync دوطرفه نصب/ادعا نشده است.

گام بعد: بازبینی و تأیید یک صفحهٔ واقعی بر اساس این پایه‌ها، سپس ادغام تدریجی در Flask/Jinja. این مرحله تکمیل گزارش‌گیری، تست زیر بار یا تأیید سازگاری تمام سرورهای تلفنی نیست. موارد توسعهٔ باقی‌مانده در FEATURE_INVENTORY و REPORTING_COMPLETION_CHECKLIST همچنان معتبرند. پیش از Push/نصب و بازطراحی گسترده، تأیید مطابق AGENTS لازم است.

## پیشرفت Diagnostics پس از تأیید گزارش

مرحلهٔ پایهٔ API/ذخیره/worker و قراردادهای مجوز/سیاست آمادهٔ بررسی است. منبع جاری از روی heartbeat ارزیابی می‌شود؛ سرویس inactive و آخرین تماس قدیمی به‌تنهایی توقف ingest را ثابت نمی‌کنند. projection10 اصلاح نسخه‌های منبع، snapshot قدیمی را حفظ می‌کند و replay محدود لازم دارد. هیچ rollout یا capture تازه‌ای برای این مرحله انجام نشد. UI اختصاصی و رسانه/تماس مستقل داخلی هنوز برنامهٔ توسعه‌اند.

نتیجهٔ نهایی رگرسیون Diagnostics:926passed/18skipped/306subtests؛49تست اختصاصی و15Playwright موفق. محدودیت‌ها و فرمان اجرا در DIAGNOSTICS_PHASE1.fa.md ثبت شدند.

## مرحلهٔ گزارش‌گیری و حجم ماهانه

خروجی و زمان‌بندی سفارشی دقیق، مقایسه/نمودار کارشناس و تفکیک راهبری گزارش‌ها در کد تکمیل شد. آزمون30هزار تماس ساختگی روی سرور با65بررسی و60رتبه‌بندی روزانه موفق بود؛ نتیجه در REPORTING_MONTHLY_VALIDATION ثبت شد. CSV/XLSX کامل و فارسی قابل بررسی‌اند. رتبه‌بندی/حضور ماهانهٔ بزرگ، تجمیع پس‌زمینه می‌خواهند و هنوز توسعهٔ بازند. رگرسیون نهایی984passed/18skipped؛ یک شکست گذرای قبلی CLI بازتولید نشد و علت آن تأیید نشده است. پنل جاری/شاخهٔ عمومی به کد تازه ارتقا نیافته‌اند.
# Latest UI verification — 2026-10-28

Shared report charts now support paged bar/time-series views, honest gaps, responsive redraw and theme-frozen PNG/SVG. Persian calendar has direct month/year selection, keyboard/focus, canonical ISO submission and quick ranges. Local consumer/template integration is present. Chromium regression: 30 passed; scoped Flask/menu tests: 12 passed; all frontend harnesses passed; Vite/Storybook builds passed. No server rollout or push. Full product-page/installed-runtime acceptance remains, as do monthly agent aggregation and the explicit reporting development gaps. Details: `../REPORTING_VISUAL_QA_20261028.fa.md`. Earlier statements that no real screenshot audit was performed describe the previous stage, not this one.

