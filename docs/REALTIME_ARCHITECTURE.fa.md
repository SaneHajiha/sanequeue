# معماری هستهٔ زندهٔ SaneQueue

فاز فعلی: Collector مستقل و آزمایش‌شده. اتصال API و WebSocket هنوز انجام نشده است. ساختار دقیق فایل‌ها، قرارداد state و راه‌اندازی در [نسخهٔ انگلیسی](REALTIME_ARCHITECTURE.md) آمده است.

انتخاب فنی، Python 3.10 تا 3.12 و asyncio برای Collector، Redis خصوصی برای state و lease، و حفظ Flask فعلی طی مهاجرت است. در گام بعد gateway مبتنی بر ASGI و WebSocket اضافه می‌شود. PostgreSQL برای دادهٔ اختصاصی گزارش‌ها پیشنهاد شده و MariaDB ایزابل فقط به‌صورت خواندنی مصرف خواهد شد. نیازی به تعویض Python سیستم، Asterisk یا رابط فعلی در همین مرحله نیست.

Collector از Flask و namespace قدیمی مستقل است. یک leader به ازای هر PBX با یک اتصال AMI کار می‌کند؛ standby اتصال تلفنی باز نمی‌کند. هر انتشار Redis با مالک lease تطبیق داده می‌شود. QueueStatus و CoreShowChannels در شروع، اتصال دوباره و هر ۱۲۰ ثانیه اجرا می‌شوند. تعداد مرورگرها نباید این فاصله را تغییر دهد. heartbeat پیش‌فرض ۱۰ ثانیه و انتشار state پیش‌فرض یک ثانیه است.

رویدادهای هم‌زمان با snapshot موقتاً در journal محدود نگه داشته می‌شوند؛ تکمیل snapshot و replay در همان event loop انجام می‌شود. frame، تعداد رویداد، state و payload سقف دارند. قطع AMI، از دست‌رفتن lease یا خطای Redis باعث بسته‌شدن جلسه و stale شدن داده می‌شود. retry با backoff و jitter انجام می‌شود. خطای خام یا credential در خروجی ثبت نمی‌شود.

state سی ثانیه و health پانزده ثانیه TTL دارند. health حتی بدون تغییر تماس تازه می‌شود. consumer باید نبودن health، generation نامنطبق، sync ناتمام یا خطای Redis را stale بداند. fallback پنهان به AMI از HTTP مجاز نیست. Pub/Sub فقط اعلان revision دارد؛ پس از قطع ارتباط باید snapshot آخر دوباره خوانده شود.

`QueueCallerLeave` پایان تماس نیست؛ Local channel خودِ تلفن کارشناس نیست؛ Uniqueid شناسهٔ leg است و Linkedid به‌تنهایی مجوز دیدن تماس نمی‌دهد. تماس پس از transfer ممکن است با leg دیگری زنده بماند. پس از reconnect، همهٔ تماس‌های پاسخ‌داده‌شده لزوماً صف قابل‌اثبات ندارند. آن‌ها نباید حدسی به کاربر scoped نشان داده شوند.

وضعیت دستگاه، paused، on-duty و ready جدا هستند. زمان pause با زمان آخرین تماس و زمان مشاهدهٔ state فرق دارد. Wrap-up فقط در صورت وجود دادهٔ معتبر محاسبه می‌شود. ServiceLevelPerf با صفر معتبر از دادهٔ ناموجود متمایز است. QueueParams میانگین و SLA لحظهٔ snapshot را دارد؛ HoldTime در AgentComplete انتظار پیش از پاسخ است، نه hold بعد از پاسخ. برای گزارش‌های زمانی دقیق به ledger پایدار queue_log نیاز داریم.

مسیر اجرای مرحله‌ای:

1. **انجام‌شده:** daemon، parser، reconnect، resync، state محدود و fencing؛ آزمون mock و Redis/PBX واقعی.
2. **گام بعد:** API خواندن Redis با scope و حذف همهٔ اتصال‌های قدیمی از مسیر عادی خواندن؛ مدل داده و schema migration.
3. **پس از آن:** کنترل‌ها با هویت AMI جدا، قفل ظرفیت چندپردازشی و وضعیت pending/confirmed/rejected/unknown.
4. **پس از آن:** WebSocket احراز هویت‌شده با Origin معتبر، بازبینی مجوز، revision و محدودیت صف ارسال؛ اتصال frontend و آزمون فشار.
5. **فاز گزارش‌گیری:** queue_log/CDR، cursor مقاوم به rotation، dedup و index در دیتابیس اختصاصی؛ alert outbox و SSO معتبر ایزابل.

جدول امتیاز و مواردی که هنوز مانع انتشار Production هستند در [ممیزی سخت‌گیرانه](AUDIT_20261024.fa.md) ثبت شده‌اند. ادعای پشتیبانی عملی Issabel 4/5 و Asterisk 16/18 تا آزمون VM واقعی مطرح نمی‌شود.
