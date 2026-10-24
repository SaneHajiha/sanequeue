# اتصال ایمن به AMI در ایزابل آزمایشی (Asterisk 20)

## دلیل خطای نسخه قبلی

نسخه پیشین SaneQueue آدرس AMI را فقط `127.0.0.1` قبول می‌کرد. در نسخه `2.1.0-beta.3` میزبان‌های IPv4 خصوصی RFC1918 و localhost پذیرفته می‌شوند و می‌توان صف مجازِ خواندن را مشخص کرد. **قوانین امنیتی Asterisk و فایروال مستقل هستند.**

## تنظیمات Asterisk تست

برای بررسی بدون تغییر:

```bash
asterisk -rx 'manager show settings'
asterisk -rx 'manager show user sq'
asterisk -rx 'queue show 8001'
ss -lntp | grep ':5038'
```

کاربر `sq` در `manager_custom.conf` باید رمز **چرخش‌داده‌شده** داشته باشد و برای خواندن صف حداقل رویدادهای مناسب agent/call در اختیار داشته باشد. برای تونل فقط این ACL کافی است:

```ini
[sq]
secret = REPLACE_WITH_NEW_RANDOM_SECRET_ON_PBX
read = agent,call
write =
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
```

برای روش مستقیم LAN، **علاوه‌بر** loopback فقط IP کامپیوترِ مجاز ویندوز را (نه IP خود سرور!) به‌صورت /32 اضافه کنید:

```ini
permit = YOUR_WINDOWS_LAN_IPV4/255.255.255.255
```

روی ویندوز برای یافتن IP از `ipconfig` استفاده کنید. سپس روی سرور، ابتدا از فایل موجود بکاپ بگیرید؛ با ویرایشگر تغییر دهید و اجرا کنید:

```bash
asterisk -rx 'manager reload'
asterisk -rx 'manager show user sq'
```

**امنیت:** TLS برای AMI خاموش است؛ در حالت مستقیم ترافیک رمزگذاری نشده است. اگر شبکه تست ایزوله نیست، این روش را استفاده نکنید. به اینترنت port-forward نکنید، فایروال را به تمام شبکه باز نکنید، `permit=0.0.0.0` نگذارید، و مجوز `write=all` ندهید. دستورهای تغییردهنده فقط با حساب جداگانه آزمایشی با دسترسی کنترل‌شده انجام شوند.

### عیب‌یابی سریع ویندوز

```powershell
Test-NetConnection 192.168.2.2 -Port 5038
Test-NetConnection 127.0.0.1 -Port 15038
```

`TcpTestSucceeded=True` فقط نشان می‌دهد TCP باز است، **نه اینکه AMI Login موفق است**. نتیجه قطعی را از Test Connection در پنل بگیرید. 

## ویژگی‌های جدید پنل

- انتخاب Host خصوصی و Queue خواندنی، با اعتبارسنجی روی سرور
- Probe مستقل ورود/QueueStatus، سپس Parser داده زنده
- ذخیره فقط Host, Port, User و Queue؛ رمز AMI فقط در RAM
- حفظ مقادیر فرم در صورت خطا
- هیچ فرمان تغییر تماس در تست اتصال صادر نمی‌شود
