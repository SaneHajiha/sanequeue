# گزارش تاریخی حضور و واردسازی SQL / Historical activity and SQL ingestion

## راهنمای کاربر

از **گزارش‌ها و مکالمات** بازهٔ تاریخ و صف را انتخاب کنید و «نمایش گزارش» را بزنید. تاریخ پایان شامل همان روز است. عنوان فارسی تاریخ شمسی دارد؛ مقدار ورودی استاندارد مرورگر میلادی است. فیلتر نتیجه فقط جدول مراجعه‌های صف را محدود می‌کند، نه کارکرد کارشناس.

بخش **کارکرد و علت‌های توقف** دو مفهوم متفاوت دارد:

- **کارکرد یکتا:** اجتماع بازه‌های حضور فعال یک داخلی بین صف‌های مجاز؛ عضویت هم‌زمان در دو صف دوبار حساب نمی‌شود.
- **جمع کارکرد/توقف عضویت‌ها:** جمع مستقل هر صف. برای تحلیل ظرفیت صف است و ممکن است از زمان واقعی سپری‌شده بیشتر باشد.

در **بازه‌های حضور و تغییر وضعیت**، زمان شروع، پایان مشاهده‌شده، صف، وضعیت و علت توقف دیده می‌شود. «بازه‌های بعدی» صفحهٔ بعد را می‌آورد. مدت بازهٔ باز فقط تا آخرین مشاهدهٔ collector محاسبه می‌شود؛ قطعی یا شروع‌نشدن ثبت، ساعت کاری فرضی تولید نمی‌کند. دادهٔ قبل از نصب collector قابل بازسازی قطعی نیست. عنوان علت از قوانین همان صف خوانده می‌شود؛ شناسهٔ علت در آرشیو باقی می‌ماند.

کارشناس فقط رابط‌های اختصاص‌یافتهٔ خود و دادهٔ پس از زمان اختصاص را می‌بیند. داخلی عددی، Local و SIP/PJSIP فقط وقتی یکی تلقی می‌شوند که فهرست داخلی‌های مرکز تلفن این تطبیق را بدون ابهام تأیید کند. ترانک یا شمارهٔ هم‌نام مبنای ادغام نیست. دسترسی صف و منوی گزارش در هر درخواست دوباره بررسی می‌شود.

## معماری و محدودیت منابع

HTTP فقط آرشیو محلی را می‌خواند. worker جداگانه queue_log، کش حضور و SQL را وارد می‌کند. شکست یک منبع، ورود منابع دیگر یا ساخت گزارش از شواهد موجود را متوقف نمی‌کند. بازگشت خطا عقب‌نشینی نمایی تا ۳۰۰ ثانیه دارد. وضعیت امن منبع در خلاصهٔ گزارش موجود است؛ رمز و مسیر خصوصی منتشر نمی‌شود.

حضور از SQLite با `mode=ro` و `query_only` خوانده می‌شود. WAL ممکن است برای هماهنگی به ساخت فایل `-shm` نیاز داشته باشد؛ سرویس باید به پوشهٔ کش محلی خودش دسترسی فایل داشته باشد. این موضوع مجوز نوشتن روی دیتابیس تلفنی یا تغییر دادهٔ حضور از طریق SQL نیست.

SQL اختیاری است و فقط اتصال محلی/socket را می‌پذیرد. وابستگی جدا: `pip install -r requirements/reporting.txt`. حساب اختصاصی باید فقط SELECT روی دو جدول CDR و CEL و حداکثر یک اتصال داشته باشد. حساب ODBC عمومی مرکز تلفن را به سرویس گزارش ندهید. رمز در فایل INI خصوصی root:sanequeue با مجوز 0640 نگهداری می‌شود. بخش `[reporting]` شامل `host`، `unix_socket`، `user`، `password`، `database`، `timezone` و در صورت نیاز `cdr_table`، `cel_table` و `generation` است. رمز واقعی را فقط مدیر نصب در سرور وارد می‌کند؛ هیچ رمز پیش‌فرض عمومی وجود ندارد.

worker با `--mysql-config` مسیر این فایل و با `--activity-cache` مسیر کش حضور را می‌گیرد. SQL حداکثر هر ۱۵ ثانیه بررسی می‌شود؛ این بازه مستقل از به‌روزرسانی زنده است. هر SELECT زمان محدود دارد: MariaDB یک ثانیه، MySQL هزار میلی‌ثانیه. صفحهٔ عادی ۲۵۰ ردیف است و هیچ‌گاه از ۵۰۰ بیشتر نمی‌شود. شاخص پیشرو CEL.id و CDR.calldate/uniqueid/linkedid لازم است؛ نبود شاخص باعث توقف همان منبع می‌شود، نه ساخت خودکار شاخص سنگین روی سرور زیر بار.

CEL بر اساس ID صحیح عددی جلو می‌رود و اثرانگشت آخرین رکورد را بررسی می‌کند. بازنشانی/جایگزینی جدول نیازمند بررسی مدیر و `generation` جدید است. CDR بر اساس گروه کامل زمان شروع صفحه‌بندی می‌شود؛ بیش‌ازحدبودن رکوردهای یک زمان خطای صریح می‌دهد و رکوردها بی‌صدا رد نمی‌شوند.

شناسهٔ پایان CEL، جست‌وجوی شاخص‌دار CDRهای دیرثبت‌شده را فعال می‌کند. درخواست بدون CDR پس از ۲۴ ساعت از صف داغ به فهرست unresolved منتقل می‌شود؛ شواهد خام حذف نمی‌شوند. همچنین پنجرهٔ ۲۴ ساعت اخیر CDR در صفحات محدود، با فاصلهٔ حداقل پنج دقیقه بین دورهای کامل، بازبینی می‌شود. دادهٔ دیررس قدیمی‌تر از این پنجره بدون CEL متناظر نیازمند بازبینی تاریخی جداست؛ پوشش کامل حدس زده نمی‌شود.

آرشیو واردشده حذف خودکار ندارد. کش زنده همچنان سیاست نگهداری مستقل دارد؛ توقف طولانی واردساز ممکن است پوشش قدیمی کش را از بین ببرد. حذف فایل صوتی توسط سیاست مستقل مرکز تلفن نیز خارج از تضمین نگهداری این آرشیو است.

## شواهد آزمایش

در سرور آزمایشی، ۱۱۹۸ CDR و ۶۳۱۹ CEL با آخرین نسخهٔ متناظر آرشیو مقایسه شدند: گمشده ۰، اختلاف محتوای فیلدهای واردشده ۰. پنل، کارکرد و علت توقف را نمایش داد و بازهٔ چندروزه از خود فرم آزمایش شد. خطای دسترسی فایل اشتراکی SQLite در sandbox سرویس پیدا و اصلاح شد. پردازش Asterisk در این ارتقا دوباره راه‌اندازی نشد. کاربر دانلود و پخش صحیح فایل صوتی اصلی را تأیید کرد.

این شواهد گواه تست صوت زیر بار، سازگاری همهٔ نسخه‌های مرکز تلفن یا تکمیل تمام نقشهٔ راه نیست. گزارش تماس خروجی هنگام توقف، شیفت/Adherence، خروجی بزرگ غیرهم‌زمان، PDF زمان‌بندی‌شده، QA و اتصال نهایی کارهای AI هنوز مراحل مستقل بعدی هستند. واردسازی SQL روی پیش‌نمایش فعال شده است؛ نصب خودکار عمومی آن هنوز به installer اصلی متصل نشده است.

## English

Choose **Reports & recordings**, an inclusive Tehran date range, and a queue. The outcome filter applies only to the visit table. **Activity & pause reasons** distinguishes unique duty time (union across authorized queues for an unambiguously mapped endpoint) from summed queue-membership duty/pause time. The latter can exceed elapsed wall-clock time. **Activity intervals** exposes observed starts, ends, state and reason with keyset pagination. Open intervals stop at the source heartbeat; monitoring gaps are not credited as working time. History before collector coverage is unavailable.

An independent worker imports queue_log, read-only activity-cache snapshots and optional local SQL. HTTP never imports data or contacts AMI. Source failures back off independently, leaving other sources and projection processing operational. Source status is redacted. SQLite WAL readers can require a writable shared-memory directory even when SQL itself is read-only; the service needs access to its own cache directory.

Install the optional pure-Python SQL dependency from `requirements/reporting.txt`. Use a dedicated local database user with SELECT only on the CDR/CEL tables and one connection. Keep `[reporting]` connection settings in a root:sanequeue 0640 INI file and pass its path using `--mysql-config`. Never reuse the PBX ODBC writer credentials. `--activity-cache` enables the activity adapter. Public automatic installer provisioning is not yet wired to this optional adapter.

SQL runs at most every 15 seconds with bounded pages and server-side statement deadlines. Required leading indexes are checked rather than created on a busy database. CEL uses an integer ID cursor plus an anchor; a replaced/reset source requires an operator-approved generation. Legacy CDR pagination consumes complete timestamp groups and refuses excessive same-timestamp density instead of skipping records. Ended CEL identities trigger indexed late-CDR reconciliation. Unresolved identities are retained outside the hot retry queue after 24 hours. A bounded 24-hour CDR overlap scan is repeated no sooner than five minutes after completion; older late records without CEL evidence require separate historical reconciliation.

Imported raw history has no automatic deletion. Existing live-cache and PBX recording-retention policies remain independent. Agent access is limited to assigned interfaces, assignment cutoff, allowed queues and the report menu. Local/numeric/SIP/PJSIP aliases require unambiguous extension-inventory evidence; trunks are not merged by name.

Lab comparison matched all 1,198 CDR and 6,319 CEL records against their latest archived versions with zero missing or differing imported payloads. The activity panel and multi-day form were exercised. A service-sandbox SQLite shared-memory failure was found and corrected. Asterisk was not restarted. Original recording download/playback was confirmed by the user. These results do not certify voice quality under load, other PBX versions, or completion of outbound-pause analytics, shifts/adherence, large asynchronous exports, scheduled PDF, QA and AI jobs.
