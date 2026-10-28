# زمینهٔ پروژه

پس از تأیید کاربر در ۲۰۲۶/۱۰/۲۸، AGENTS.md و اسناد گردش کار ثبت و ابزارهای توسعهٔ محلی نصب شدند. کد عملیاتی و سرور تلفنی در این مرحله تغییر نکردند؛ Push انجام نشده است.

مخزن: https://github.com/SaneHajiha/sanequeue

Workspace بررسی‌شده: work/review-20261024. origin همان مخزن است. شاخهٔ محلی feature/realtime-operations و HEAD محلی e977516398db5b04309ddae11dffb3dbec4f09d9 است؛ تعداد زیادی تغییر staged/unstaged و فایل untracked وجود دارد. شاخهٔ منتشرشده feature/reporting-phase2 در commit 3e60acfdeaf6d992ee74b40ad4327d9a7f9e9e36 است. این اختلاف باید پیش از تغییر/همگام‌سازی بعدی حل شود؛ checkout/reset دسته‌جمعی پیشنهاد نمی‌شود.

پیش‌نمایش آزمایشی: http://192.168.2.2:18897/operations. پورت ۵۰۰۰ در مرحلهٔ اخیر به‌روزرسانی نشده است. تنظیمات/کلیدها/دادهٔ خصوصی جزو بسته نیستند.

معماری: Python/Flask/Jinja برای HTML، JavaScript معمولی و CSS محلی؛ runtime ASGI/WebSocket و collector مستقل. package.json اسکریپت و وابستگی فرانت ندارد و نسخهٔ آن beta.12 قدیمی است؛ این نسخه را با release runtime یکی نگیرید. ۳۱ فایل JS و ۹ CSS در پوستهٔ فعلی دیده شد. پروژه React/Vue نیست. پیشنهادِ سازگار: ابزارهای طراحی و تست توسعه‌ای جدا، با استفاده از همان CSS/HTML/JS محصول و fixtureهای مصنوعی؛ نصب روی سرور تماس لازم نیست.

## افزودهٔ فعلی — Diagnostics

پس از تأیید گزارش تشخیصی، هستهٔ API/Store/worker آرشیوی و اصلاحات ingest/projection ایجاد شد؛ docs/DIAGNOSTICS_PHASE1.fa.md محدودهٔ واقعی را مشخص می‌کند. این تغییرات تازه در محیط محلی‌اند و روی PBX نصب/فعال نشده‌اند. قاعدهٔ قدیمی «package.json بدون script» شرح پیش از راه‌اندازی است؛ اکنون اسکریپت‌های ui:* و کارگاه مستقل وجود دارند.

## وضعیت جاری گزارش‌گیری

خروجی حجیم/برنامهٔ سفارشی و رتبه‌بندی دوشاخصی اکنون در سورس محلی وجود دارند. fixtureماهانه30هزارشناسه روی سرور در /var/tmp/sanequeue-report-month-fecf0bce، مستقل ازapplicationآزمایش شد. منبع آرشیو اصلی/نسخهٔ پنل جاری تغییر نکرد. گزارش منابع و gapها در REPORTING_MONTHLY_VALIDATION وREPORTING_COMPLETION_CHECKLIST به‌روز شده است.
