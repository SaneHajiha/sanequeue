# Reporting lab acceptance / آزمون گزارش‌ها روی مرکز تلفن آزمایشی

Date: 2026-10-25. Environment: Asterisk 20.12, isolated reporting preview on port 18897. These results are limited to this lab and do not certify other PBX versions or production capacity.

## آزمون تلفنی با پاسخ انسانی

| سناریو | شاهد اصلی queue_log | نتیجهٔ تطبیق با API گزارش |
| --- | --- | --- |
| پاسخ و قطع توسط تماس‌گیرنده | COMPLETECALLER؛ انتظار ۲ و مکالمه ۲۰ ثانیه | مطابق؛ یک مراجعه |
| پاسخ و قطع توسط کارشناس | COMPLETEAGENT؛ انتظار ۳ و مکالمه ۱۶ ثانیه | مطابق؛ یک مراجعه |
| قطع در صف بدون پاسخ | ABANDON؛ انتظار ۲۰ ثانیه | مطابق؛ بدون پاسخ و مکالمهٔ ساختگی |
| انتقال از کارشناس اول به داخلی دیگر | CONNECT → TRANSFER → COMPLETEAGENT | پس از اصلاح، یک مراجعهٔ منتقل‌شده؛ بدون ردیف پاسخ تکراری |

آزمون انتقال یک ایراد را آشکار کرد: پایان دیرهنگام Queue بعد از انتقال به‌اشتباه مراجعهٔ جدید ایجاد می‌کرد. اکنون این رویداد در شواهد خام باقی می‌ماند، اما شمارش مراجعه را افزایش نمی‌دهد. مدت اعلام‌شده در آن رویداد ممکن است مکالمهٔ بعد از انتقال را هم شامل شود؛ بنابراین به کارشناس اول نسبت داده نمی‌شود. آزمون رگرسیون، ورود واقعی مجدد به صف را نیز از این حالت جدا می‌کند.

کاربر پایان تماس انتقالی را از تلفن مقصد تأیید کرد. چون شواهد فعلی CEL برای تعیین مطمئن قطع‌کنندهٔ نهایی کامل نیست، گزارش این فیلد را نامشخص نگه می‌دارد. تأیید انسانی را نباید به‌جای قابلیت تشخیص خودکار معرفی کرد.

اصلاح فقط روی پیش‌نمایش گزارش اعمال شد؛ ۹۰۳۲ رویداد برای بازسازی دادهٔ مشتق‌شده پردازش شدند. تاریخچهٔ خام حذف نشد و شناسهٔ پردازش Asterisk تغییر نکرد.

رفرنس صوت هر چهار تماس از API بررسی شد. سه تماس پاسخ‌داده‌شده WAV دارای داده و پاسخ صحیح HTTP Range داشتند؛ تماس رهاشده WAV خالی ۴۴ بایتی داشت. چند CDR به همان فایل اشاره می‌کردند؛ فهرست ضبط‌ها اکنون رفرنس یکسان را فقط یک بار نمایش می‌دهد. این آزمون دریافت بایت فایل را بررسی می‌کند؛ شنیدن کامل محتوا و کیفیت صدا آزمونی جداست.

## English

Four human-operated calls were compared with actual queue_log evidence and the authenticated reporting API: caller hangup (2 s wait, 20 s talk), agent hangup (3 s wait, 16 s talk), abandonment (20 s wait), and transfer followed by delayed Queue completion. Each produced exactly one queue visit after the transfer regression was fixed.

A COMPLETE event following TRANSFER must not create a second answered visit. Its duration can include the downstream conversation and must not be attributed to the first agent. Raw evidence remains intact. A subsequent ENTERQUEUE still creates a genuine new visit. Final conversation hangup remains unknown when CEL does not support attribution, even when the human tester confirms which phone they used.

These tests do not establish RTP quality under load, compatibility with other Asterisk versions, continuous SQL ingestion readiness, or completion of the full reporting roadmap. No customer audio or identifiers are included in this document.
