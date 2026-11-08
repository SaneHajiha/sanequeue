# ممیزی تطبیقی SaneQueue در برابر Connect Stats

**تاریخ بررسی:** 2026-11-08
**منبع محصول:** https://voipiran.io/connect-stats/
**وضعیت سند:** بررسی مستندات/تصاویر عمومی و کد SaneQueue؛ نه تأیید آزمایش مستقل محصول تجاری VOIPIRAN یا استقرار جدید SaneQueue.
**شاخه بررسی SaneQueue:** master, 2.1.0-beta.26. این سند روی شاخه طراحی منتشر می‌شود، بدون تغییر عملکرد PBX.

## حدود داده‌های موجود

صفحه رسمی Connect Stats پنج نمای گزارش را صریحاً مستند کرده است:
1. تماس‌های توزیع‌شده؛
2. تماس‌های پاسخ‌داده‌شده؛
3. تماس‌های بدون پاسخ؛
4. گزارش کارشناسان (Login/Logout، تعداد تماس، میانگین‌ها، تغییر وضعیت)؛
5. جست‌وجو در گزارش‌ها با شماره، داخلی، صف و زمان.

بازه‌های سریع صفحه: امروز، دیروز، این هفته، هفته گذشته، این ماه و سه ماه گذشته؛ بازه سفارشی شروع/پایان نیز ذکر شده است. فیلتر صف و کارشناس و بروزرسانی نمودارها/جداول با فیلتر در متن آمده است.

گالری موجود شامل dashboard، stats-distributed، stats-answered و stats-agents است. این تصاویر اثبات پیاده‌سازی رابط هستند، نه آزمون صحت SQL، اتصال واقعی تلفن یا قابلیت کلیک همه دکمه‌ها.

**احتیاط درباره خروجی:** اسکرین‌شات‌ها آیکون‌های خروجی را نشان می‌دهند، اما متن راهنمای همان صفحه خروجی Excel/PDF را قابلیت نسخه‌های آینده نامیده است؛ پس ارائه «خروجی تکمیل‌شده محصول رقیب» از شواهد موجود نتیجه نمی‌شود.

## ماتریس قابلیت و شواهد

تعاریف:
- `LIVE`: در رابط فعلی SaneQueue با شواهد تست زنده/مستند موجود است؛ به معنی پشتیبانی همه نصب‌ها نیست.
- `PARTIAL`: شواهد زنده یا آرشیوی جزئی هست ولی گزارش حرفه‌ای قابل استفاده کامل نیست.
- `NOT_READY`: پنل/منطق گزارش تاریخی آماده یا پذیرفته نشده است.
- `UNKNOWN`: امکان رقیب بر پایه متن/تصویر ثابت نشده است.

| # | قابلیت دیده‌شده/مستند در Connect Stats | SaneQueue | وضعیت پیاده‌سازی و آزمون |
|---|---|---|---|
| 01 | داشبورد تماس/صف و KPI لحظه‌ای | LIVE | QueueStatus، WebSocket/Redis، اتصال، انتظار و سطح خدمت؛ نمودارهای فعلی مرورگرمحور هستند |
| 02 | تماس‌های توزیع‌شده، کل ورودی به صف | PARTIAL | queue_log importer تاریخی اولیه موجود؛ گزارش کامل queue visit و بازه در UI ندارد |
| 03 | تفکیک پاسخ‌داده و بدون پاسخ | PARTIAL | شمارنده زنده، دلایل queue_log و شواهد archive؛ نتیجه تاریخی کامل و reconciliation ندارد |
| 04 | جزئیات پاسخ: زمان پاسخ، مکالمه، صف و داخلی | PARTIAL | داده‌های زنده و CDR/CEL/queue_log archive پایه؛ API جست‌وجوی تاریخی و نمایش نهایی ندارد |
| 05 | بدون پاسخ: مدت انتظار و دلیل خروج | PARTIAL | باید abandon، timeout، exit key، no-member، RINGNOANSWER و agent dump را جدا نگه دارد |
| 06 | گزارش Login/Logout و مدت حضور کارشناسان | PARTIAL | فعالیت روزانه مشاهده‌شده و pause reason موجود است؛ backfill و union-of-intervals لازم |
| 07 | تعداد پاسخ هر کارشناس و AHT | PARTIAL | آمار زنده و observed activity؛ محاسبه آرشیوی و تفکیک تلاش/تماس یکتا آماده نیست |
| 08 | فیلتر شماره، داخلی، صف و تاریخ | NOT_READY | پنل تاریخی و RBAC جست‌وجوی آرشیو تکمیل نشده |
| 09 | انتخاب هم‌زمان چند صف/کارشناس | NOT_READY | فیلتر فعلی مانیتورینگ گزارش تاریخی multi-select نیست |
| 10 | امروز/دیروز/این هفته/هفته پیش/ماه/سه ماه/دلخواه | NOT_READY | کنترل انتخاب بازه بر مبنای history/API و timezone کامل نیست |
| 11 | نمودار ساعتی/روزانه و نسبت پاسخ | NOT_READY | نمودار live مرورگر جایگزین series archive نیست |
| 12 | جداول جزئی و drill-down تماس | NOT_READY | archive evidence graph اولیه بدون UI report/recording |
| 13 | CSV/Excel/PDF | NOT_READY | هیچ ادعای پذیرش export تاریخی SaneQueue وجود ندارد؛ خروجی رقیب نیز در راهنمای رسمی آینده عنوان شده |
| 14 | خوانایی فارسی/RTL | LIVE | فارسی/انگلیسی، فونت محلی، Dark/Light؛ بازطراحی در PR #15 در جریان است |
| 15 | امکانات عمیق تماس، transfer/park/journey | PARTIAL | AMI live + CEL evidence اولیه، بدون اثبات علت نهایی قطع تماس پس از انتقال |
| 16 | ضبط صوت همراه رکورد گزارش | NOT_READY | CDR recordingfile و نمونه فایل آزمایشگاهی وجود داشته؛ مسیر امن پخش/دانلود، permission و audit هنوز نه |
| 17 | گزارش PBX-wide: تماس‌های داخلی و خروجی خارج صف | NOT_READY | خواسته محصول SaneQueue جدا از گزارش تخصصی صف؛ باید CDR-wide داشته باشد |
| 18 | سنجش کیفیت صوت یک‌طرفه/قطع | PARTIAL | RTCP read-only samples و live journey؛ packet capture/SIP-RTP correlate لازم است؛ MOS یا علت قطعی نباید ساخته شود |

## تفاوت مفهومی با صفحه محصول

در تصاویر چند جدول بزرگ و نمودارهای عمودی پشت‌سرهم دیده می‌شود؛ صرف تکثیر آنها تجربه بهتری ایجاد نمی‌کند. رابط پیشنهادی SaneQueue باید:
- برای هر دسته «نمای خلاصه -> نمودار/مقایسه -> جدول ریزتماس -> پنل شواهد تماس» فراهم کند؛
- فیلترهای مشترک بالا/سمت صفحه داشته باشد و همه کارت‌ها/جداول از یک filter state استفاده کنند؛
- نوع واحد اندازه‌گیری، SLA denominator، timezone و محدوده داده جمع‌آوری‌شده را نشان دهد؛
- خروجی CSV/XLSX/PDF فقط از داده واقعاً فیلترشده، scope-safe و با audit ارائه شود؛
- نمودار بدون داده یا نمونه‌برداری ناقص را صفر یا موفقیت نشان ندهد.

## مشکلات عمومی گزارش‌شده توسط کاربران VOIPIRAN و کنترل متناظر ما

این بخش از GitHub Issues عمومی پروژه‌های دیگر VOIPIRAN است، نه از کانال تلگرام و نه اثبات وجود ایراد در Connect Stats:
- VOIZ #14: بعد از نصب، PJSIP در میزکار دیده نمی‌شود؛ SaneQueue inventory PJSIP را در آزمون واقعی دیده است، اما باید هر Issabel 5/4 جدا تست شود.
- voiz-issabel-monitoring #3: نصب موفق ولی stuck on loading؛ SaneQueue اتصال stale و fail-closed دارد، اما آزمون cold start و disconnect/resume پس از استقرار الزامی است.
- voiz-issabel-monitoring #4: ازبین‌رفتن layout/areas بعد upgrade؛ SaneQueue باید حفظ allowed_sections، preferences و ذخیره گرافیکی را با migration contract تست کند.
- VOIZ #12: به‌جای صفحه صف directory listing؛ SaneQueue باید HTTPS reverse proxy، routing و مسیر static درست و directory listing غیرفعال را در تست استقرار بررسی کند.
- VOIZ #11: کندی، Webphone، English UI و مؤلفه‌های Issabel؛ SaneQueue از runtime جدا و Redis collector بهره می‌گیرد اما full webphone ندارد؛ تست load و browser matrix لازم است.
- VOIZ #1: در CDR خروجی calleridِ trunk در ستون source جای داخلی ثبت می‌شود؛ در SaneQueue مدل تاریخی نباید `src` را «داخلی» فرض کند؛ inventory و channel/dialplan evidence باید source extension را تعیین یا نامشخص ثبت کند.

## اقدامات پیشنهادی در اولویت

### P0 — صحت و امنیت داده‌ها (قبل از افزودن گزارش)
1. Importer تولیدی read-only برای CDR/CEL و queue_log با cursor/checkpoint، backfill، rotation، late records، coverage watermark و independent worker.
2. تعریف `conversation`, `leg`, `queue_visit`, `ring_attempt`, `membership_session`؛ Linkedid تنها مرجع قطعی conversation نیست.
3. مخرج‌های دقیق ASA, AHT, SLA, abandoned rate؛ صفر و نامشخص تفکیک شوند.
4. نقش‌محوری در query و export (شماره‌های mask شده، محدوده صف و داخلی)؛ عدم اجازه lookup ID بیرون scope.
5. مقیاس‌پذیری: index query، محدودیت صفحه، زمان، bytes، retention بدون حذف خودکار، ظرفیت ذخیره‌سازی و backup.

### P1 — پنل گزارش تماس صف
1. Report workspace با سربرگ: نمای مدیریتی، توزیع تماس، پاسخ، بی‌پاسخ، کارشناس، جست‌وجو و Drilldown.
2. فیلتر واحد: بازه‌های سریع/سفارشی تهران، انتخاب چند صف/کارشناس، شماره/داخلی (scope-aware)، مسیر و نتیجه.
3. جدول صف با دسته‌بندی reason صریح `COMPLETEAGENT`, `COMPLETECALLER`, `ABANDON`, `EXITWITHTIMEOUT`, `RINGNOANSWER`, `EXITWITHKEY` و «نامشخص».
4. نمودار ساعت/روز، روند پاسخ، پیک صف، توزیع انتظار و login/logout/pause، همراه data table و drill-down.
5. خروجی CSV/XLSX با permission, bounded generation, formula injection protection و audit.

### P2 — گزارش کل PBX و عیب‌یابی کیفیت
1. گزارش CDR و تماس‌های داخلی/خروجی/ورودی غیرصف؛ DID، ترانک، شماره، source extension فقط با شاهد معتبر.
2. تاریخچه مسیر انتقال/park/pickup/bridge با CEL، ادغام تماس کنترل‌شده، علت/طرف قطع فقط با شواهد.
3. پخش و دانلود فایل‌های ضبط از allowlisted recording roots با ACL، audit، عدم path traversal و وجود/صحت فایل.
4. صفحه Troubleshooting برای تماس یک‌طرفه یا قطع پس از transfer با SIP/RTCP/CEL و **برچسب احتمالی** بودن تشخیص، بدون نتیجه‌گیری قطعی از RTCP.
5. گزارش‌های برنامه‌ریزی‌شده و PDF پس از تثبیت داده و خروجی.

## معیار پذیرش عملی

- Fixtureهای queue_log/CDR/CEL با چند انتقال و یک مشتری مشترک: counts برای calls/visits/legs برابر مبنای دستی، بدون duplicate.
- داده‌های timestamp عبوری از نیمه‌شب و DST مبدا: زمان تهران و میلادی و فیلتر inclusive/exclusive صریح.
- Login/Logout/Pause با همپوشانی دو صف: ساعت کاری یکتا (union) بدون double counting.
- تماس بی‌پاسخ و retry: تمایز unique caller در برابر missed attempts.
- source callerid مربوط به trunk با internal source extension تفکیک شود.
- test unauthorized user: هیچ report/export/recording بیرون scope باز نشود.
- backfill/rotation/copy-truncate و disk-pressure: fail-closed، عدم تغییر PBX، partial-coverage UI.
- 1440/1024/768/390 px، FA RTL/EN LTR، Dark/Light، keyboard و printing.
- تنها پس از تست روی آزمایشگاه Issabel با داده مصنوعی/مجاز و سپس پایلوت زنده ادعای «آماده» شود.

## منابع

- Connect Stats: https://voipiran.io/connect-stats/
- Gallery sample distributed: https://voipiran.io/wp-content/uploads/2025/09/stats-distributed-scaled.webp
- Gallery sample answered: https://voipiran.io/wp-content/uploads/2025/09/stats-answered-scaled.webp
- Gallery sample agents: https://voipiran.io/wp-content/uploads/2025/09/stats-agents-scaled.webp
- SaneQueue feature matrix: docs/FEATURES.md
- SaneQueue archive foundation: docs/REPORTING_PHASE1.md
- SaneQueue reporting design: docs/REPORTING_RESEARCH.fa.md
- Public VOIZ issues: https://github.com/voipiran/VOIZ/issues
- Public monitoring issues: https://github.com/voipiran/voiz-issabel-monitoring/issues
