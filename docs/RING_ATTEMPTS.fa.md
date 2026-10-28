# گزارش زنگ داخلی بدون پاسخ

مسیر: گزارش‌ها ← زنگ داخلی بدون پاسخ. بازهٔ حداکثر ۳۱ روز و صف را از فیلتر اصلی انتخاب و «محاسبهٔ گزارش» را بزنید. فیلتر نتیجهٔ مراجعه روی این گزارش اثر ندارد.

هر ردیف یک رویداد `RINGNOANSWER` ثبت‌شده است، نه مشتری یکتا، مکالمهٔ یکتا یا تماس رهاشده. یک تماس ممکن است برای چند داخلی و در چند صف پیشنهاد شود. عدم پاسخ از این رویداد اثبات می‌شود؛ علت انسانی یا تقصیر کارشناس از آن استنتاج نمی‌شود. `RINGCANCELED` در این شمارش نیست.

جمع‌بندی و گروه‌بندی صف/داخلی کل بازه را می‌خوانند؛ ریز، صفحه‌های حداکثر ۱۰۰تایی دارد. نمودار از همان گروه‌بندی است و خروجی SVG/PNG محلی دارد. شناسهٔ کانال و شمارهٔ مشتری در این گزارش منتشر نمی‌شوند. داخلی ناشناخته با نامعلوم نمایش داده می‌شود. این نسخه مخصوص مدیر/سرپرست مجاز است؛ حساب کارشناس تا اثبات انتساب تاریخی عضو صف، دسترسی مستقیم ندارد.

مدت منبع میلی‌ثانیه است و به ثانیه تبدیل می‌شود. صفر معتبر با مدت نامعلوم فرق دارد. میانگین فقط مدت‌های معلوم را محاسبه می‌کند و تعداد آن‌ها مخرج است. چندعضویتی کارشناس، پیشنهادهای واقعی صف را حذف نمی‌کند؛ هیچ جمع پیشنهاد به‌عنوان مکالمهٔ یکتا نام‌گذاری نشده است.

ارتباط با مراجعه فقط با PBX، صف، شناسهٔ تماس و بازهٔ زمانی یکتای اثبات‌شده پذیرفته می‌شود. شروع ناقص، پاسخ هم‌زمان، ورود مجدد مبهم و تأخیر پردازش نامعلوم می‌مانند. پیوند مراجعه مجوز پخش صوت نیست.

## محدودیت منابع و شواهد

هیچ AMI، SQL مرکز تلفن یا DDL در درخواست وب اجرا نمی‌شود. خواندن از شاخص زمانی موجود آرشیو است. سقف: ۵ ثانیه یا مهلت کمتر آرشیو، ۱۰هزار رویداد منبع در کل بازه (حتی غیر RINGNOANSWER)، ۴MiB payload مرتبط، ۴KiB برای هر payload، ۱۰۰۰ گروه، ۱۰۰۰ مراجعه برای هر هویت و ۱۰هزار کاندید انتساب در کل گزارش. عبور از سقف خطای صریح می‌دهد و جمع ناقص تحویل نمی‌دهد. در آرشیو شلوغ باید بازه را کوتاه‌تر کرد؛ این مسیر به‌عنوان گزارش نامحدودِ میلیون‌ها رویداد تأیید نشده است.

API: `GET /api/history/ring-attempts?from=YYYY-MM-DD&to=YYYY-MM-DD&queue=8001`؛ همان مجوز و تاریخ تهران گزارش اصلی. نسخه‌های اصلاح‌شدهٔ منبع دوبار شمرده نمی‌شوند. نبود رویداد یا سلامت فعلی منبع، پوشش کامل گذشته را اثبات نمی‌کند. صفحه‌بندی، snapshot خروجی ثابت نیست؛ دادهٔ تازه می‌تواند نتیجهٔ بازخوانی را تغییر دهد.

تست: `python -m pytest tests/test_reporting_ring_attempts.py tests/test_reporting_ring_attempts_api.py` و `node tests/reporting_frontend.cjs`. تست مصنوعی، آزمون تلفنی و مقیاس واقعی را جایگزین نمی‌کند.

مرجع معنای رویداد و واحد مدت: [مستند رسمی Queue Logs](https://docs.asterisk.org/Operation/Logging/Queue-Logs/).


CSV summary: /api/history/ring-attempts.csv uses the same complete filtered groups (not the visible detail page), at most 1000 groups/512 KiB, with a fresh report_export grant on every selected queue. A denied export does not remove permitted viewing. Unknown numeric values are blank; spreadsheet formulas are neutralized. The UI hides stale export controls on filter/view changes. CSV is recomputed at download time, not a pinned asynchronous export snapshot. Standard queue-visit Excel/CSV controls now live inside the queue-visit report, so another report is not accidentally exported as visits.
