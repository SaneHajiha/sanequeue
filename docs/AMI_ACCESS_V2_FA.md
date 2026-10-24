# تنظیم دسترسی AMI برای تست SaneQueue beta.5

روی Asterisk 20.12.0 حساب **جداگانه و موقت** `sq` یا `sq_supervisor_test` بسازید. پیش از ویرایش فایل سفارشی از آن بکاپ بگیرید. **رمزهای قبلاً فرستاده‌شده در چت را تعویض کنید.**

```ini
[sq_supervisor_test]
secret = REPLACE_WITH_LONG_UNIQUE_ASCII_PASSWORD
; first deny everyone, then permit only an authorized source
; for an SSH tunnel: 127.0.0.1
; for direct LAN: an explicit WINDOWS_LAN_IP/32, on isolated test network only
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
; permit = WINDOWS_LAN_IP/255.255.255.255
read = agent,call,system,reporting,command
write = agent,call,originate,reporting
```

**تفاوت حیاتی**: در AMI، `write` مجوز اجرای **Action** است، حتی وقتی آن Action فقط اطلاعات می‌خواند. `read` مجوز دریافت **Event** است. 

- معمولاً `reporting` برای فرمان‌های اطلاعاتی نظیر CoreShowChannels لازم می‌شود؛ مجوز واقعی نسخه نصب‌شده را با `manager show command CoreShowChannels` بررسی کنید.
- PJSIP/Registration رویدادهای طبقه `command` دارد و ممکن است `read=command` برای دریافت آن‌ها لازم باشد. `read=command` با `write=command` فرق دارد.
- **`write=command` و `write=all` پیشنهاد نمی‌شود**؛ زیرا اجرای دستورات گسترده CLI را فعال می‌کنند. اگر ListCommands نشان داد Action تخصصی بدون آن در دسترس نیست، از SSH محدود برای دریافت اطلاعات یا یک راهکار جایگزین با دسترسی محدود استفاده کنید.
- `write=system` نیز ممکن است توانایی مدیریت ماژول داشته باشد؛ خودکار اضافه نکنید.
- مجوز AMI در سطح کلاس است، نه محدود به صف؛ بنابراین در این نسخه مانیتورینگ همه صف‌ها با `*` مجاز است، ولی فرمان‌های تغییردهنده تنها بعد از انتخاب یک صف واقعی و تأیید صریح ۳۰ دقیقه‌ای فعال می‌شوند.

سپس:

```bash
asterisk -rx 'manager reload'
asterisk -rx 'manager show user sq_supervisor_test'
```

قبل از افزودن هر کلاس ناشناخته، در صفحه **سلامت PBX → مجوزهای واقعی AMI** فهرست مجوزهای آن حساب را با `ListCommands` ببینید. اگر `CoreShowChannels` در فهرست نیست، مشکل Action authorization یا نصب ماژول است؛ اگر در فهرست هست ولی پاسخ نرسید، مجوز read مربوط به رویداد یا پایان فهرست را بررسی کنید.

**برای آزمایش عملی** یک صف و داخلی آزمایشی واقعی بسازید؛ تا وقتی تماس تستی با رضایت طرفین موجود نیست، `Hangup`, `Originate`, `Listen`, `Whisper`, `Barge` را اجرا نکنید. مانیتورینگ همه صف‌ها ربطی به آزادکردن همه فرمان‌ها ندارد.

**محدودیت این نسخه**: امکان نمایش و تشخیص مجوزها و چند سلامت‌سنج جدید وجود دارد؛ انتقال تماس، پارک، Softphone و سایر امکانات برنامه توسعه هنوز پیاده‌سازی کامل نشده‌اند.
