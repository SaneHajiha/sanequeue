# SaneQueue 2.1.0-beta.25

## فارسی

- بازطراحی مرکز عملیات و کارت صف: هویت رنگی ثابت، هشدار مستقل، ظرفیت پاسخ‌گویی، وضعیت اعضا، حلقه سطح خدمت و انتظار فعلی. صف بدون کارشناس آماده دیگر «عادی» معرفی نمی‌شود. چیدمان موبایل، روشن/تیره و خلاصه تمام‌صفحه اصلاح شد.
- بازه انتخابی «امروز» از دفتر ثبت مشاهده‌شده ماژول؛ شمارنده تجمیعی PBX جدا و با توضیح محدوده نامعلوم بازنشانی. داده ناموجود به‌صورت خط تیره نمایش داده می‌شود.
- پیام تلگرام و بله با انتخاب فارسی/انگلیسی/هر دو، کشف مقصد و راهنمای تنظیم. هشدار قطعی ترانک، قطع جمع‌آوری، داده سلامت قدیمی و دیسک بحرانی با جلوگیری از ارسال تکراری.
- اصلاح ذخیره دفترچه، ارقام فارسی/عربی، نام مخاطب در مسیرهای تحت مدیریت و آپلود لوگوی AVIF. نام دفترچه تنها در مسیر نام‌گذاری فعال و با شروع تماس جدید روی تلفن اثر می‌گذارد.
- ماژول اختیاری انتظار داخلی، کال‌بک و اصلاح شماره: FastAGI محلی محدود، صف درخواست ماندگار، تنظیمات وب، آپلود صوت و بسته صوت پیش‌فرض با کنترل SHA256.
- گزارش کال‌بک پذیرش درخواست، پاسخ درخواست‌کننده، اتصال واقعی مقصد، پایان و مدت مشاهده‌شده را جدا می‌کند. رکورد قدیمی فاقد شواهد، زمان ساختگی نمی‌گیرد.
- فعالیت روزانه کارشناس و تماس خروجی در توقف با دلیل؛ محدودسازی تاریخچه به مجوز و زمان انتساب داخلی.
- غیرفعال‌سازی وب فوراً مسیر ماژول تلفنی را نیز غیرفعال می‌کند؛ بازیابی فایل اصلی و مالکیت/مجوز آن بدون restart مرکز تلفن آزمایش شد.

این نسخه برای پایلوت کنترل‌شده است. آزمون واقعی روی همه نسخه‌های هدف و آزمون مکالمه RTP هنوز لازم است. راهنمای [ماژول‌های تلفنی](TELEPHONY_MODULES.fa.md)، [کاربری](USER_GUIDE.fa.md) و [شواهد آزمون](AUDIT_BETA25.md).

## English

- Reworked operations and queue cards: stable queue identity, separate health/threshold states, staffing, agent states, service-level rings and live waiting pressure. No-ready-agent queues no longer appear healthy. Mobile, light/dark and fullscreen summary layouts were checked.
- Explicit observed-today metrics versus cumulative PBX counters; coverage and unknown reset boundaries remain visible. Missing evidence is not rendered as zero.
- Telegram/Bale language selection (Persian, English or both), destination discovery and setup instructions. Debounced trunk, collector, inventory-age and disk alerts.
- Directory editing/number normalization and AVIF logo support. Managed caller-name hooks apply on new calls; a saved directory record alone does not update an existing handset display.
- Optional bounded local FastAGI callback/waiting and caller-ID modules, durable callback jobs, web configuration and constrained audio upload. The default owner-supplied prompt is bundled and integrity checked.
- Callback acceptance, requester answer, verified target bridge and observed end/talk duration are distinct. Legacy rows keep unknown timing.
- Scoped observed daily agent activity and outbound calls during reasoned pauses.
- Web disable immediately bypasses telephone-module behavior. Original dialplan content, ownership and mode restoration was exercised without restarting Asterisk.

Controlled-pilot beta; the target installation matrix and real RTP capacity still require site-specific acceptance. See [telephone modules](TELEPHONY_MODULES.en.md), [user guide](USER_GUIDE.en.md) and [validation evidence](AUDIT_BETA25.md).
