# Reporting lab acceptance / آزمون گزارش‌ها روی مرکز تلفن آزمایشی

Date: 2026-10-25. Environment: Asterisk 20.12, isolated reporting preview on port 18897. These results are limited to this lab and do not certify other PBX versions or production capacity.

## آزمون تلفنی با پاسخ انسانی

| سناریو | شاهد اصلی queue_log | نتیجهٔ تطبیق با API گزارش |
| --- | --- | --- |
| پاسخ و قطع توسط تماس‌گیرنده | COMPLETECALLER؛ انتظار ۲ و مکالمه ۲۰ ثانیه | مطابق؛ یک مراجعه |
| پاسخ و قطع توسط کارشناس | COMPLETEAGENT؛ انتظار ۳ و مکالمه ۱۶ ثانیه | مطابق؛ یک مراجعه |
| قطع در صف بدون پاسخ | ABANDON؛ انتظار ۲۰ ثانیه | مطابق؛ بدون پاسخ و مکالمهٔ ساختگی |
| انتقال از کارشناس اول به داخلی دیگر | CONNECT → TRANSFER → COMPLETEAGENT | پس از اصلاح، یک مراجعهٔ منتقل‌شده؛ بدون ردیف پاسخ تکراری |
| انتقال با مشورت از دکمهٔ خود پنل | CEL: ATTENDEDTRANSFER؛ ادامهٔ تماس روی مقصد پس از قطع کارشناس اول | پس از اصلاح همبستگی، «منتقل‌شده» در جدول و رویداد «انتقال با مشورت» در جزئیات |

آزمون انتقال یک ایراد را آشکار کرد: پایان دیرهنگام Queue بعد از انتقال به‌اشتباه مراجعهٔ جدید ایجاد می‌کرد. اکنون این رویداد در شواهد خام باقی می‌ماند، اما شمارش مراجعه را افزایش نمی‌دهد. مدت اعلام‌شده در آن رویداد ممکن است مکالمهٔ بعد از انتقال را هم شامل شود؛ بنابراین به کارشناس اول نسبت داده نمی‌شود. آزمون رگرسیون، ورود واقعی مجدد به صف را نیز از این حالت جدا می‌کند.

کاربر پایان تماس انتقالی را از تلفن مقصد تأیید کرد. چون شواهد فعلی CEL برای تعیین مطمئن قطع‌کنندهٔ نهایی کامل نیست، گزارش این فیلد را نامشخص نگه می‌دارد. تأیید انسانی را نباید به‌جای قابلیت تشخیص خودکار معرفی کرد.

اصلاح فقط روی پیش‌نمایش گزارش اعمال شد؛ ۹۰۳۲ رویداد برای بازسازی دادهٔ مشتق‌شده پردازش شدند. تاریخچهٔ خام حذف نشد و شناسهٔ پردازش Asterisk تغییر نکرد.

رفرنس صوت هر چهار تماس از API بررسی شد. سه تماس پاسخ‌داده‌شده WAV دارای داده و پاسخ صحیح HTTP Range داشتند؛ تماس رهاشده WAV خالی ۴۴ بایتی داشت. چند CDR به همان فایل اشاره می‌کردند؛ فهرست ضبط‌ها اکنون رفرنس یکسان را فقط یک بار نمایش می‌دهد. این آزمون دریافت بایت فایل را بررسی می‌کند؛ شنیدن کامل محتوا و کیفیت صدا آزمونی جداست.

## آزمون رابط کاربری پس از اصلاح

انتقال با مشورت، پارک و بازیابی از فرم خود پنل انجام شدند. در آزمون نخست پارک، انتخاب سمت تماس‌گیرنده باعث پارک کارشناس شد؛ این رفتار تابع معنای مبدأ در AMI بود، اما فرم آن را روشن نمی‌کرد. عنوان هدف و پنجرهٔ تأیید اصلاح شدند تا صریحاً بگویند «طرف مقابل مبدأ پارک می‌شود». آزمون مجدد با مبدأ صحیح، پارک در محل ۷۱ و اتصال تماس‌گیرنده به تلفن سرپرست را با تأیید انسانی نشان داد. پنجرهٔ تأیید و انصراف اکنون داخل خود پنل است؛ فقط تأیید نهایی فرمان می‌فرستد و مقادیر انتخاب‌شده پیش از تأیید ثابت می‌مانند.

دکمهٔ پخش روی ضبط تماس واقعی در مرورگر آزمایش شد: زمان پخش جلو رفت، `readyState=4` و خطای رسانه وجود نداشت. این نتیجه به معنی ارزیابی شنیداری یا کیفیت RTP نیست. CSV دو ردیف منتقل‌شده را صادر کرد؛ پس از مشاهدهٔ خروجی فنی نامناسب در Excel، XLSX و CSV خوانا اضافه شدند. XLSX فارسی از دکمهٔ پنل دانلود و در Excel توسط کاربر باز شد؛ خواندن مستقل فایل نیز دو ردیف منتقل‌شده، تاریخ شمسی، شمارهٔ متنی، RTL و ثابت‌بودن سرستون‌ها را تأیید کرد.

پایان دانلود فایل صوتی در مرورگر هنوز تأیید نشده است. ابزار صفحهٔ داخلی دانلودهای Chrome را طبق سیاست امنیتی خود مسدود کرد؛ این محدودیت نباید به‌عنوان موفقیت یا خرابی قطعی دانلود محصول گزارش شود. دریافت بایت و مجوزهای صوت جداگانه آزموده شده‌اند.

## English UI acceptance

Attended transfer, park and retrieve were exercised through the panel forms. Parking initially targeted the wrong party because the initiator semantics were unclear; the new label and in-panel confirmation explicitly explain that the opposite party is parked and returns to the initiator on timeout. Retesting the correct initiator parked the caller in slot 71 and retrieved it to the supervisor, confirmed by the human tester. Cancel closes the confirmation without submitting a command; confirmed payload values are captured before the dialog opens.

The real recording's play control advanced playback with readyState 4 and no media error. This is player acceptance, not an auditory/RTP quality test. Two transferred rows were exported through the UI. The user opened the new Persian XLSX in Excel; an independent reader verified its two outcomes, Persian date text, string phone cells, RTL and frozen headers. Browser completion of original-audio download remains unverified: the browser tool blocked access to Chrome's internal downloads page. No bypass was attempted.

Four human-operated calls were compared with actual queue_log evidence and the authenticated reporting API: caller hangup (2 s wait, 20 s talk), agent hangup (3 s wait, 16 s talk), abandonment (20 s wait), and transfer followed by delayed Queue completion. Each produced exactly one queue visit after the transfer regression was fixed.

A COMPLETE event following TRANSFER must not create a second answered visit. Its duration can include the downstream conversation and must not be attributed to the first agent. Raw evidence remains intact. A subsequent ENTERQUEUE still creates a genuine new visit. Final conversation hangup remains unknown when CEL does not support attribution, even when the human tester confirms which phone they used.

These tests do not establish RTP quality under load, compatibility with other Asterisk versions, continuous SQL ingestion readiness, or completion of the full reporting roadmap. No customer audio or identifiers are included in this document.
