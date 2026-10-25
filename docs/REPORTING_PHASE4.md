# تماس هنگام فعالیت خارج از صف / Calls during out-of-queue activities

## استفاده

در **گزارش‌ها و مکالمات** بازه و صف را انتخاب کنید. فیلتر **نوع تماس حین توقف** دو حالت جدا دارد:

- **بیرونی از ترانک:** مبدأ باید داخلی شناخته‌شده و مقصد، کانال یک ترانک شناخته‌شده باشد.
- **داخلی به داخلی:** هر دو کانال باید داخلی شناخته‌شده باشند؛ برای نظرسنجی داخلی و آزمون بدون ترانک کاربرد دارد. این داده به آمار بیرونی اضافه نمی‌شود.

در بخش **تماس‌های آغازشده هنگام توقف**، کارشناس، مقصد، زمان شروع، صف و علت توقف، نتیجهٔ CDR، مدت بخش و زمان مکالمهٔ همان بخش نمایش داده می‌شود. شروع تماس باید داخل بازهٔ توقف مشاهده‌شده باشد. بازهٔ علت نیز کنار صف نشان داده می‌شود. تماس پیش از شروع توقف، صرفاً به علت ادامه‌یافتن در آن بازه، به این جدول نسبت داده نمی‌شود.

**هر ردیف یک بخش CDR است؛ الزاماً یک مکالمهٔ یکتا نیست.** زمان مکالمه، `billsec` همان بخش است و ممکن است از پایان توقف عبور کند؛ آن را مدت کارکرد یا زمان هم‌پوشانی با توقف تلقی نکنید. عضویت هم‌زمان در چند صف، همان ردیف CDR را تکرار نمی‌کند؛ علت‌های مجاز به‌صورت وابسته‌های همان ردیف نمایش داده می‌شوند. دکمهٔ موارد بعدی صفحه‌بندی پایدار دارد.

اگر ضبط موجود باشد و مجوز آن را داشته باشید، دکمهٔ **فایل صوتی** پخش/دریافت اصل ضبط را باز می‌کند. منوی گزارش، صف، نقش و مجوز مستقل پخش/دانلود در هر درخواست بررسی می‌شوند. نقش کارشناس صوت دریافت نمی‌کند. مقصد طبق مجوز نمایش شماره، کامل یا ماسک‌شده است؛ مسیر فایل و شناسه‌های خام زنجیره تماس به جدول ارسال نمی‌شوند.

## تشخیص و پوشش

نوع تماس از نام کانال واقعی و فهرست مشاهده‌شدهٔ داخلی/ترانک استخراج می‌شود؛ از طول شماره، Caller ID یا شباهت نام حدس نمی‌زنیم. نبود یک جفت کانال شناخته‌شده، `unknown` می‌دهد. کانال Local بدون شواهد کافی به تماس بیرونی تبدیل نمی‌شود. تعریف‌ها مربوط به فهرست مشاهده‌شده هنگام ساخت دادهٔ مشتق‌شده‌اند؛ این فهرست به‌تنهایی اثبات نمی‌کند که تنظیم تاریخی یک سرور قدیمی همیشه همان بوده است.

ردیف‌ها فقط از تقاطع صف‌های مجاز، رابط‌های اختصاص‌یافته و زمان اختصاص کاربر با بازهٔ توقف آرشیوشده به دست می‌آیند. استفاده از snapshot کوتاه خواندن، از تغییر هم‌زمان صف/علت بین دو پرس‌وجو جلوگیری می‌کند. سقف پنج‌ثانیه‌ای و صفحه‌بندی محدود حفظ می‌شوند؛ HTTP هیچ دستور AMI یا SQL روی مرکز تلفن اجرا نمی‌کند.

در سرور آزمایشی ترانک خارجی قابل‌تماس موجود نیست. آزمون با داخلی‌ها، ثبت توقف و همبستگی تماس را بررسی می‌کند؛ موفقیت مسیر خروجی یا کیفیت صوت بیرونی محسوب نمی‌شود. آزمون خودکار، داخلی/بیرونی/ورودی/نامشخص، عضویت چندصفی بدون تکرار، مرز شروع/پایان توقف، مرز اختصاص کاربر، ماسک مقصد، مجوز صوت و HTTP Range را پوشش می‌دهد.

## English

In **Reports & recordings**, select the date/queue and **Pause call type**. External calls require an observed extension-to-trunk channel pair. Internal calls require two known extensions and remain separate; they support internal surveys and testing without a trunk.

The table shows CDR segments whose start falls within an observed pause. It includes agent, destination, start, authorized queue/reason intervals, disposition, duration and billsec. A call starting before the pause is not attributed merely because it continues during the pause. A CDR segment is not necessarily a unique conversation, and full-segment billsec is not pause-overlap time. Multiple queue memberships do not duplicate the segment row.

Audio playback/download rechecks report menu, role, queue scope and the independent audio capability on every request. Agent-role users cannot retrieve audio. Destinations are masked unless the caller-details capability permits full display. Private recording paths and raw conversation identifiers are not returned by the table API.

Classification uses exact channel endpoints backed by observed definitions, never phone-number length or Caller ID. Missing pairs and unsupported Local-channel identity remain unknown. Current observed inventory is not proof of a historical configuration. Short consistent read snapshots prevent mismatched call/pause joins while allowing WAL writers to proceed. HTTP performs no PBX SQL or AMI calls.

The lab has no callable external trunk. Internal acceptance cannot certify external routing or external audio. Automated tests cover direction boundaries, no multi-queue row duplication, pause and assignment cutoffs, keyset pagination, destination masking, audio authorization and byte ranges.

## آزمون واقعی داخلی / Internal lab acceptance

با حفظ قانون حداقل نیروی صف، داخلی ۳۰۰ موقتاً از فرم پنل عضو صف شد. توقف ۱۰۰ با علت نظرسنجی، سپس تماس دستی ۱۰۰ به ۲۰۰ و بازگشت ۱۰۰ و حذف عضویت موقت ۳۰۰، از پنل/تلفن‌های آزمایشی انجام شدند. گزارشِ حالت داخلی یک بخش پاسخ‌داده‌شده با مدت ۳۰ ثانیه و billsec برابر ۲۸ نشان داد. بازهٔ علت در حضور، CDR و جدول تماس حین توقف تطبیق کرد. پخش صوت از کنترل مرورگر جلو رفت (مدت رسانه ۲۸٫۷۲ ثانیه، readyState=4، بدون خطا). این تماس به آمار بیرونی اضافه نشد. همهٔ تغییرات موقت عضویت و توقف برگشتند.

The human-operated extension-to-extension call produced one answered CDR segment: duration 30 seconds, billsec 28. Observed pause bounds and the survey reason matched the report. Playback advanced through the actual panel control (28.72-second media, readyState 4, no media error). The temporary membership and pause changes were restored through the panel. This was not an external-trunk test.
