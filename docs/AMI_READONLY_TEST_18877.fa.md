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
