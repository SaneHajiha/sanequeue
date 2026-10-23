# SaneQueue beta.4 — راهنمای امن AMI روی Asterisk 20

**وضعیت:** این سند برای نسخه آزمایشی 2.0.0-beta.4 است؛ سورس کامل beta.4 هنوز فقط در بسته محلی است، نه در GitHub.

## پورت‌های تفکیک‌شده

- نسخه‌های قدیمی پیش‌نمایش: `127.0.0.1:8765` و `127.0.0.1:8766`
- نسخه beta.4: `http://127.0.0.1:18877/operations`
- بررسی نسخه: `http://127.0.0.1:18877/__sanequeue__/build`
- خروجی خلاصه AMI محلی: `http://127.0.0.1:18877/__sanequeue__/ami-snapshot`

در beta.4 رابط اصلی همچنان با دادهٔ آزمایشی است و عملیات تغییر تماس سروری قفل است. Snapshot نتیجهٔ یک اجرای مشخص ابزار CLI است، نه مانیتورینگ مداوم.

## سرور تست

خروجی فعلی: Asterisk 20.12.0، PJSIP/100 دارای Contact=Avail و hint Idle، اما عضو Local/100@from-queue/n در صف 8001 برابر Unavailable. علت این اختلاف هنوز روشن نیست. قبل از هر تغییر، این فرمان‌های خواندنی بررسی شود:

```bash
asterisk -rx "queue show 8001"
asterisk -rx "manager show command QueueStatus"
asterisk -rx "manager show command CoreShowChannels"
grep -n '^[[:space:]]*#include[[:space:]]*manager_custom.conf' /etc/asterisk/manager.conf
```

## حساب AMI و اتصال

در صورت وجود include، یک کاربر **موقت** در `/etc/asterisk/manager_custom.conf` بسازید:

```ini
[sq_readonly]
secret = REPLACE_LOCALLY_WITH_LONG_RANDOM_PASSWORD
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = agent,call
write =
```

ابتدا نسخهٔ پشتیبان از فایل تنظیمات بگیرید. روی سرور **تست** `asterisk -rx "manager reload"` و سپس `asterisk -rx "manager show user sq_readonly"` اجرا کنید. **هیچ رمز، کلید SSH یا تنظیمات خام را به چت نفرستید.** AMI روی 5038 بدون TLS است؛ دسترسی از راه اینترنت ممنوع.

روی ویندوز یک SSH tunnel محدود به loopback ایجاد کنید:

```powershell
ssh -N -L 127.0.0.1:15038:127.0.0.1:5038 root@PBX_PRIVATE_IP
```

در بستهٔ محلی، `TEST_AMI_TUNNEL_WINDOWS.bat` با Python و بدون کتابخانه خارجی فقط `Login`، `QueueStatus` و `Logoff` اجرا می‌کند. رمز فقط در همان ترمینال به‌صورت مخفی دریافت می‌شود. نتیجه تنها شامل تعداد صف و عضو، کد وضعیت و تعداد منتظر است؛ نام و شماره مشتری منتقل نمی‌شود. مرورگر متصل به ChatGPT می‌تواند **JSON خلاصه‌شده** را بعد از اجرای ابزار مشاهده کند.

**هشدار مهم:** «read» و «write» در AMI به دسته‌های event/action مربوط‌اند، نه لزوماً به ماهیت بی‌خطر دستور. اگر `QueueStatus` با write خالی مجاز نبود، مجوز `agent` را کورکورانه به write اضافه نکنید؛ این دسته امکان تغییر عضویت صف را هم می‌دهد. ابتدا `manager show command QueueStatus` را روی همین نسخه بررسی کنید.

ورود به تماس، شنود، قطع یا جابه‌جایی تماس در این مرحله انجام نمی‌شود.


## رفع خطای وب‌سرور beta.4 — ۲۲ اکتبر ۲۰۲۶

در گزارش واقعی ویندوز، ۱۹ تست اجرا شدند و فقط تست `test_monitoring_tabs_render_without_reports` خطا داد، زیرا هنوز رشتهٔ نسخهٔ قدیمی `2.0.0-beta.2` را در HTML انتظار داشت؛ درحالی‌که HTML نسخه `2.0.0-beta.4` را برمی‌گرداند. اسکریپت راه‌انداز در صورت شکست تست قبل از شروع Flask متوقف می‌شد؛ در نتیجه `ERR_CONNECTION_REFUSED` روی `127.0.0.1:18877` دیده می‌شد. این خطا مستقل از اتصال موفق AMI بود.

در بستهٔ محلی `SaneQueue_2.0.0-beta.4_18877_WEB_HOTFIX.zip`:

- تست به‌جای رشتهٔ ثابت، `qpanel.__version__` را بررسی می‌کند.
- پنج تست متمرکز ایمنی/نسخه هنگام راه‌اندازی باقی مانده‌اند؛ کل تست‌های واحد به فایل مستقل `RUN_ALL_TESTS_WINDOWS.bat` منتقل شدند.
- `START_WEB_AND_SNAPSHOT_18877.bat` وب‌سرور را در پنجرهٔ CMD جداگانه باز می‌کند و وضعیت آن را با آدرس `/__sanequeue__/build` صحت‌سنجی می‌کند.
- با `OPEN_SNAPSHOT_OFFLINE.bat` می‌توان Snapshot را بدون وب‌سرور در Notepad دید.
- آرشیو سالم است و پنج تست متمرکز در محیط توسعه موفق بوده‌اند؛ اجرای همهٔ ۱۹ تست با Flask روی ویندوز کاربر هنوز باید بررسی شود.
- سرور AMI و رمز قبلی تغییری نمی‌کنند؛ لازم است Snapshot پاک‌سازی‌شده با اجرای دوباره ابزار در پوشه جدید یا انتقال `ami_snapshot.json` منتقل شود.

**کد کامل این hotfix هنوز روی GitHub push نشده است؛ شاخهٔ master بدون تغییر باقی مانده.**
