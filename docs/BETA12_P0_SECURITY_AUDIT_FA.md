# SaneQueue 2.1.0-beta.12 — نتیجه اعمال ممیزی امنیتی

مبنای اصلاح: ممیزی فنی/امنیتی beta.11 ارائه‌شده توسط مالک پروژه؛ این سند گزارش اجرای کد در محیط آفلاین است، نه ادعای تست عملی روی ایزابل.

## ایرادهایی که بازتولید و اصلاح شدند

| اولویت | مورد | وضعیت beta.12 |
| --- | --- | --- |
| P0 | نشت Channel از کلیدهای `entries` برای viewer | اصلاح؛ شناسه عمومی `entry_N` در پاسخ viewer؛ تست منفی برای Channel/Uniqueid/Linkedid |
| P0 | در نبود PolicyStore دسترسی خام پیش‌فرض | اصلاح؛ `scope_data` خالی و `can_access_queue` False؛ نبود gate همیشه Deny |
| P0 | مسیر گزارش خام `/stats/...` | مسدود با HTTP 410 در لایه قبل از route؛ `/api/reports` هم RBAC و default-deny شد |
| P0 | گیت کنترل مشترک بدون مالک | به user + signed-session nonce + queue + explicit allowed_actions + TTL وابسته شد؛ کاربر/نشست دیگر نمی‌تواند از آن استفاده کند؛ گیت هنوز تک‌فرایندی است |
| P0 | Docker/systemd قدیمی بدون امنیت نسخه ویندوز | اجرا عمداً غیرفعال شد؛ تا ساخت app factory یکپارچه قابل استقرار نیست |
| P1 | Busy و Ringing به‌عنوان Ready در حداقل نیرو | اصلاح؛ حداقل Ready فقط Status=1، نه Paused و نه InCall. `on_duty` عمداً جداست |
| P2 | داده قبلی پس از قطع AMI به ظاهر زنده | UI وضعیت stale و قفل کنترل‌ها را روشن می‌کند؛ داده قبلی برای اطلاع با نشانه کاهش اعتبار می‌ماند |

## نیمه‌کاره و باقی‌مانده (نباید Production اعلام شود)

- **AMI Read/Control**: در این نسخه هنوز دو نشست/هویت AMI کاملاً جدا نشده‌اند. حساب AMI باید IP/مجوز محدود داشته باشد؛ `write=all` مجاز نکن.
- **کنترل نهایی Action**: پاسخ Accepted هنوز معادل تأیید نهایی Originate/Spy/Hangup نیست؛ به ActionID + رویداد و Channel/Bridge correlation نیاز است.
- **Collector دائمی**: هنوز polling با snapshot کوتاه‌عمر انجام می‌شود؛ EventListener، reconnect/backoff، resync و state مشترک باید ساخته شوند.
- **گیت و ظرفیت چندپردازشی**: محدودیت خروج و nonce در همان فرایند است؛ برای چند worker/host نیازمند DB transaction/lock مشترک و state مرکزی است.
- **هشدار بله**: ارسال best-effort است و outbox/retry/idempotency پایدار ندارد.
- **UI**: منوی مبتنی بر نقش، modal focus management، keyboard/screenreader و آزمون واقعی موبایل هنوز باقی است.
- **محرمانگی داده**: viewer key leak اصلاح شد؛ کل APIها و فایل‌های log/CSV برای PII باید تست end-to-end شوند.
- **Login**: rate limiting/MFA/TLS و session store پایدار نیازمند تکمیل است.
- **تست کامل**: suite قدیمی تست‌های منسوخ برای نسخه‌ها/پورت‌ها و وابستگی‌های Flask/Asterisk دارد؛ تا اصلاح آن نتیجه full suite سبز اعلام نمی‌شود.
- **گزارش تاریخی**: طبق خواسته مالک هنوز غیرفعال است. تبدیل اجباری log استریسک به DB ایزابل توصیه نمی‌شود.

## نکته حقوقی
SaneQueue می‌تواند برند و رابط کاملاً اختصاصی داشته باشد؛ با باقی‌ماندن کد مشتق‌شده از QPanel، حفظ اعلان‌های مجوز و حق‌نشر موجود در LICENSE/NOTICE ضروری است. بازنویسی مستقل باید پروژه دیگری با تست و review حقوقی باشد.
