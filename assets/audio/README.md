# Telephone prompts / پیام‌های تلفنی

`callback-menu-fa.wav` is the existing Persian callback menu supplied by the project owner from the authorized test PBX. It is included unchanged; the installer verifies its SHA-256 and WAV format before installation. No telephone recordings or call audio are included.

فایل منوی فارسی کال‌بک با درخواست مالک پروژه از سرور آزمایشی برداشته شده و بدون تغییر در بسته قرار دارد؛ این فایل ضبط مکالمه نیست. نصب‌کننده پیش از نصب، هش و قالب صوت را بررسی می‌کند.

- PCM signed 16-bit, mono, 8,000 Hz; about 14.84 seconds.
- Installed as `/var/lib/asterisk/sounds/custom/sanequeue/callback-menu-fa.wav`.
- Existing `/var/lib/asterisk/sounds/custom/callback.wav` is never overwritten.
- Organization uploads remain private in the server state directory and are never added to the repository or replaced on upgrade.
- Defaults can be restored per slot in Telephone modules. Returning to the bundled menu does not delete uploaded recordings.

صدای پیش‌فرض در مسیر مستقل ماژول نصب می‌شود؛ فایل قدیمی سرور بازنویسی نمی‌شود. صداهای آپلودی هر سازمان خصوصی باقی می‌مانند و در ارتقا جایگزین نمی‌شوند. پیش از استفاده عملی، پیام را پخش کنید و مطابقت توضیح کلیدهای ۱ و ۲ با گزینه‌های فعال را تأیید کنید.
