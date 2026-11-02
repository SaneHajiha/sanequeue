# Reporting phase 2 — historical views and secure recordings

## فارسی

این مرحله روی هستهٔ آرشیو فاز اول ساخته شده است. نسخهٔ آزمایشی روی پورت **۱۸۸۹۷** اجرا می‌شود؛ نصب پایدار روی پورت ۵۰۰۰ تغییر نکرده است.

### قابلیت‌های پیاده‌شده

- منوی مستقل «گزارش‌ها و مکالمات» با دسترسی سمت سرور و تنظیم منو برای هر کاربر.
- بازهٔ حداکثر ۳۶۶ روز، منطقهٔ زمانی تهران، نمایش تاریخ شمسی در فارسی و میلادی در انگلیسی. ورودی تاریخ مرورگر از قالب استاندارد میلادی استفاده می‌کند؛ عنوان زیر آن تاریخ فارسی را نشان می‌دهد.
- شمارش مراجعه‌های صف، پاسخ، رهاشدن، انتقال، میانگین انتظار و مکالمه، سطح خدمت و شواهد ناقص.
- فیلتر صف و نتیجه، صفحه‌بندی با نشانگر، مسیر رویدادهای صف و مشخص‌کردن قطع‌کنندهٔ **بخش صف**.
- جدول عملکرد کارشناس به تفکیک صف: پاسخ، مجموع/میانگین مکالمه و طرف قطع‌کنندهٔ بخش صف.
- پخش و دانلود ضبط از رفرنس CDR، با شناسهٔ پایگاه داده و کنترل دسترسی مجدد در هر درخواست؛ بدون URL عمومیِ مسیر فایل.
- سه مجوز مستقل `recording_play`، `recording_download` و `report_export` در مدیریت کاربران؛ شمارهٔ کامل همچنان به `caller_details` نیاز دارد.
- درخواست Range برای جلو/عقب بردن صوت، خواندن تکه‌ای فایل، ردکردن symlink و مسیر خارج از ریشهٔ مجاز. نام فایل خروجی شامل شمارهٔ مشتری نیست.
- CSV فارسی با BOM و خنثی‌سازی فرمول‌های اکسل؛ خروجی فوری حداکثر ۲۰۰ ردیف است و گزارش بزرگ بدون اخطار ناقص صادر نمی‌شود.
- پردازشگر مستقل با دسته‌های محدود، توقف با SIGTERM، پشتیبانی از فایل توقف اضطراری و checkpoint غیرمسدودکنندهٔ PASSIVE.

### نحوهٔ استفاده

۱. مدیر وارد «کاربران و دسترسی‌ها» شود؛ منوی گزارش‌ها و صف‌های مجاز را انتخاب کند. برای پخش، دانلود و خروجی هر مجوز را جداگانه فعال کند. انتخاب منو به‌تنهایی مجوز صوت نمی‌دهد.

۲. در «گزارش‌ها و مکالمات»، تاریخ ابتدا و انتها را انتخاب کرده و «نمایش گزارش» را بزند. روز انتهایی شامل کل آن روز به وقت تهران است. فیلتر نتیجه روی جدول مراجعه‌ها اعمال می‌شود؛ خلاصهٔ صف تمام نتیجه‌ها را مقایسه می‌کند.

۳. «مسیر و صوت» را باز کند. برچسب قطع فقط دربارهٔ بخش صف است. فایل ضبط‌شدهٔ همان زنجیره، در صورت وجود و مجوز، برای پخش یا دریافت نمایش داده می‌شود.

۴. نبودِ رفرنس، نبودِ فایل و نداشتن مجوز یکسان نیستند. WAV/MP3/OGG مستقیم پخش می‌شوند؛ فرمت‌های دیگر ممکن است فقط دانلود شوند. نبود داده با خط تیره نمایش داده می‌شود، نه صفر ساختگی.

### تعریف دقیق شاخص‌ها

واحد شمارش **مراجعه به صف** است؛ یک تماس منتقل‌شده ممکن است چند مراجعه و چند ردیف CDR داشته باشد. تعداد CDR را تعداد مکالمهٔ یکتا محسوب نمی‌کنیم.

سطح خدمت این گزارش = پاسخ‌های دارای انتظار ثبت‌شدهٔ حداکثر ۲۰ ثانیه ÷ همهٔ پاسخ‌های دارای انتظار مشخص. این تعریف با شمارندهٔ زنده یا تعریف سازمانیِ شامل تماس‌های رهاشده الزاماً یکی نیست.

میانگین انتظار از مراجعه‌های دارای مقدار انتظار و میانگین مکالمه از مقادیر مکالمهٔ ثبت‌شده محاسبه می‌شود. زمان مشورتِ انتقال بدون شواهد به‌عنوان مکالمهٔ مشتری منظور نمی‌شود.

### راه‌اندازی پردازشگر

این نمونه‌ها باید با کاربر سرویس و مسیر خصوصیِ آماده‌شده توسط مدیر سیستم اجرا شوند. وب‌سرور آرشیو را ایجاد یا وارد نمی‌کند.

```sh
python -m sanequeue.reporting --database /var/lib/sanequeue/history.sqlite3 initialize
python -m sanequeue.reporting.worker \
  --database /var/lib/sanequeue/history.sqlite3 \
  --queue-log /var/log/asterisk/queue_log \
  --disabled-file /var/lib/sanequeue/module.disabled
```

برای واردکردن CDR/CEL، فایل JSONL باید snapshot ثابت و خصوصی باشد. تغییر محتویات همان فایل رد می‌شود؛ snapshot بعدی باید مسیر جدیدی داشته باشد. موقعیت واردسازی قابل ادامه و رویدادهای تکراری قابل تشخیص‌اند.

```sh
python -m sanequeue.reporting.worker \
  --database /var/lib/sanequeue/history.sqlite3 \
  --cdr-json /private/cdr-snapshot.jsonl \
  --cel-json /private/cel-snapshot.jsonl --once
```

### مرزهای این مرحله

**این مرحله تکمیل کل نقشهٔ گزارش‌گیری یا تأیید آمادگی تولید نیست.** پیش‌نمایش از snapshot واقعیِ آزمایشی استفاده می‌کند. آداپتور دائمی SQL، نصب خودکار آن و ورود خودکار تاریخچهٔ حضور هنوز به این مرحله متصل نشده‌اند. worker فایل صف را دنبال می‌کند؛ گزینه‌های JSONL معادل اتصال زندهٔ SQL نیستند.

خروجی حجیم پس‌زمینه، PDF، زمان‌بندی، امتیازدهی QA، گزارش آماده‌به‌کار/شیفت و تماس خروجی هنگام توقف، موج صوتی و هم‌ترازی ضبط، تحلیل VIP/Blacklist و پردازش AI هنوز تکمیل نشده‌اند. پردازش AI یا ارسال صوت به سرویس بیرونی در این نسخه فعال نشده است.

### خروجی قابل استفاده در Excel

برای Excel از دکمهٔ **Excel ↓** استفاده کنید: فایل XLSX با سرستون زبان پنل، راست‌به‌چپ در فارسی، ردیف ثابت، فیلتر و عرض ستون مناسب ساخته می‌شود. شماره‌ها و شناسه‌ها متن هستند تا صفر ابتدایی یا ارقام طولانی تغییر نکنند. تاریخ فارسی شمسی برای سال‌های میلادی ۱۹۰۰ تا ۲۰۹۹ و تاریخ انگلیسی میلادی است؛ بیرون این محدوده، تاریخ میلادی با برچسب صریح نمایش داده می‌شود. زمان نامعلوم خالی می‌ماند. تاریخ‌ها متن خوانا هستند و سلول تاریخ عددی Excel محسوب نمی‌شوند.

CSV نیز تاریخ و عنوان خوانا دارد، اما تشخیص خودکار نوع شماره در Excel به تنظیمات همان برنامه وابسته است؛ برای حفظ نوع داده، XLSX را انتخاب کنید. خروجی فنی قبلی با `export.csv?layout=raw` قابل دریافت است. هر دو خروجی همان محدودیت ۲۰۰ مراجعه و همان مجوز مستقل خروجی را دارند. کتابخانهٔ پردازشی سنگین یا موتور Office روی سرور نصب نمی‌شود.

در انتقال با مشورت، CEL فقط وقتی برای تصحیح نتیجهٔ مراجعه استفاده می‌شود که شناسهٔ زنجیره، مبدأ کارشناس و بازهٔ فعال همان مراجعه تطبیق کنند. انتقال روی شاخهٔ دیگری از تماس به کارشناس صف نسبت داده نمی‌شود. تغییر نسخهٔ الگوریتم، بازسازی افزایشیِ دادهٔ مشتق‌شده را خودکار از ابتدا انجام می‌دهد؛ شواهد خام و موقعیت واردسازی حذف نمی‌شوند.

آرشیوِ واردشده حذف خودکار ندارد. کش قدیمیِ حضور/تماس همچنان محدودیت ۹۰ روزه دارد؛ تا اتصال واردساز آن، این محدودیت نباید به کاربر «تاریخچهٔ کامل حضور» معرفی شود. فایل صوتی اصلی توسط این ماژول حذف نمی‌شود؛ سیاست حذف خود مرکز تلفن مستقل است.

دادهٔ CEL این سرور در بسیاری از رویدادهای انتقال و قطع، `eventextra` ندارد. قطع نهایی مکالمه و زمان مشورت در چنین مواردی نامشخص می‌مانند. از روی آخرین HANGUP حدس نمی‌زنیم.

پیش‌نمایش، کوکی جدا و درخواست‌های تغییردهندهٔ مسدودشده دارد؛ workerهای کنترل/کال‌بک/پیام‌رسان نسخهٔ اصلی را دوباره اجرا نمی‌کند.

## English

Phase 2 adds queue-visit reporting, scoped agent metrics, queue-event journeys, authenticated recording playback/download and bounded CSV export over the phase-1 local archive. HTTP handlers never import source data or contact AMI. The lab preview runs separately on port 18897, with an independent cookie and disabled mutations/background call controls.

Use **Reports & recordings**, choose an inclusive Tehran date range of at most 366 days, then run the report. Persian captions use the Persian calendar; browser date inputs use Gregorian ISO values. Queue filtering applies to the summary and details; outcome filtering applies to the visit table. Open **Journey & audio** for evidence and recording references.

Playback, downloads and exports have separate queue-scoped permissions: `recording_play`, `recording_download`, `report_export`. Unmasked numbers additionally require `caller_details`. Every detail/audio/export request rechecks authorization. The agent role is restricted to assigned interfaces and the assignment cutoff. CSV neutralizes spreadsheet formulas and refuses more than 200 rows instead of silently truncating the export.

Counts represent **queue visits**, not unique conversations or CDR rows. SL uses answered visits with known waiting time as its denominator. Missing values stay null. COMPLETEAGENT/COMPLETECALLER identifies the queue segment's terminating party, not necessarily the terminating party of a later transferred conversation. Consultation duration and recording alignment remain unknown without supporting evidence.

The separate worker follows queue_log and imports immutable CDR/CEL JSONL snapshots in bounded batches. It does **not** yet provide continuous SQL replication or automatic production provisioning. Imported archive history has no automatic deletion; existing live activity/call caches still have their documented 90-day bounds until the historical activity adapter is connected. Original recording retention remains controlled by the PBX independently.

Bounded XLSX export provides localized headers, readable Tehran dates (Persian calendar for 1900–2099 in Persian, explicitly labeled Gregorian fallback outside that range), text phone/ID cells, right-to-left layout, frozen headers and filters. Dates are readable text rather than Excel date serials. CSV now has readable localized columns; `layout=raw` retains machine-oriented CSV. Both formats enforce the same 200-visit limit and export permission, without an Office runtime or heavy spreadsheet dependency on the PBX.

CEL attended/blind transfer evidence corrects a visit only when conversation identity, source endpoint and active interval match. Consultation duration and final hangup remain unknown without supporting evidence. Projection algorithm upgrades automatically replay derived facts in bounded batches; raw evidence and source checkpoints remain intact.

Pending work includes continuous SQL ingestion, activity/shift/outbound reporting, asynchronous large exports/PDF/schedules, QA, waveform/alignment, VIP/blacklist analytics and optional AI processing. No audio has been sent to an external AI provider. This increment must not be represented as the complete reporting roadmap or a universal production-readiness certification.
