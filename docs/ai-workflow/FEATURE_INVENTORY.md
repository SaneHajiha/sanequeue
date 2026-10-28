# فهرست قابلیت‌ها — ارزیابی کد، نه گواه کامل بودن

| حوزه | قابلیت‌ها | مبنای کد | وضعیت/مرز |
|---|---|---|---|
| پایش زنده | صف، انتظار، تماس جاری، کارت خلاصه، وضعیت کارشناس و وال‌برد | sanequeue/realtime/ · qpanel/operations.py | کد موجود؛ پذیرش بصری/چندنسخه‌ای باقی است |
| کنترل سرپرست | شنود، نجوا، ورود به مکالمه، انتقال، پارک/بازیابی، Pickup، قطع و اولویت | sanequeue/actions/ · qpanel/operations.py | کد و پذیرش تلفنی برخی سناریوها؛ تمام سناریوها دوباره تأیید نشده‌اند |
| عضویت و وضعیت کارشناس | ورود/خروج صف، توقف/ادامه، علت توقف و زمان‌ها | sanequeue/realtime/ · qpanel/queue_policies.py | کد موجود؛ منبع صریح Wrap-up/ACW در همهٔ سامانه‌ها تضمین نشده |
| گزارش اصلی صف | مراجعه، پاسخ/رهاشدن، SLA، ASA، انتظار/مکالمه، نمودار و نقشه ساعت | sanequeue/reporting/analytics.py · queries.py | کد و تطبیق واقعی آرشیو؛ واحد مراجعه است |
| گزارش کارشناس چندصفی | عملکرد، اجتماع حضور، علت توقف، شیفت و AHT/اشغال مشروط | activity_queries.py · agent_metrics.py · adherence.py | کد موجود؛ مجهول‌ها صفر نمی‌شوند |
| زنگ داخلی بدون پاسخ | RINGNOANSWER، ریز/گروه/نمودار و CSV کل بازه | ring_attempts.py · api/ring_attempts.py | کد، CI و تطبیق ۴۴ رویداد واقعی؛ بازه/منابع محدود |
| CDR و ترافیک خطوط | مبدأ واقعی، CID، DID/ترانک، جستجوی طرف تماس و فیلتر زمان/شماره | cdr_queries.py · api/reports.py | کد و تطبیق آرشیو؛ پذیرش ترانک خارجی باقی است |
| مسیر تماس | IVR ثبت‌شده، Local، انتقال و قطع‌کننده با شواهد | journey.py · correlate.py | کد موجود؛ مسیر پیش از صف RingGroup و انتساب‌های پیچیده ناقص‌اند |
| ضبط و دسترسی | پخش، Range، دانلود و تاریخچه درخواست صوت | audio.py · recording_scope.py · access_audit.py | کد و پذیرش برخی صوت‌ها؛ انتساب چندمرحله‌ای نیازمند تکمیل |
| هپی‌کال و نظرسنجی کاری | دورهٔ صریح کار، تماس‌های هنگام توقف، جزئیات و صوت مجاز | work_sessions.py · outbound.py | کد و آزمون داخلی؛ اعلام دوره با مشاهدهٔ حضور فرق دارد |
| کیفیت مکالمه | فرم نسخه‌دار، امتیاز انسانی و یادداشت زمان‌دار صوت | quality.py | کد موجود؛ بازبینی کامل جریان کاربر باقی است |
| رضایت مشتری | فرم شاخه‌ای، پاسخ DTMF و CSAT؛ بازخورد صوتی دستی | sanequeue/surveys/ | کد؛ hook اختیاری/دریافت تلفنی خودکار همهٔ مسیرها کامل نیست |
| VIP و مسدودی | برچسب تاریخ‌دار، SLA تفکیکی و مشاهدات واردشده | customer_segments.py | کد؛ منبع خودکار مسدودی و قواعد مسیر تماس نیست |
| خروجی و گزارش‌ساز | CSV/XLSX/PDF ثابت، قالب/زمان‌بندی؛ preview سفارشی | export_jobs.py · report_builder.py · report_plans.py | CSV/XLSX پس‌زمینه و زمان‌بندی سفارشی اکنون موجود؛ dataset مستقل CDR/PDF سفارشی باقی است |
| متن و هوش مصنوعی | ASR خصوصی، جستجوی متن و تحلیل مولد اختیاری | ai_worker.py · transcript_search.py · generative_worker.py | کد موجود؛ مدل مولد پیش‌فرض غیرفعال؛ دقت فارسی تأیید نشده |
| هشدار و پیام‌رسان | آستانهٔ هر صف، هشدار دیداری/صوتی، تلگرام/بله و سلامت | qpanel/queue_policies.py · qpanel/operations.py | کد؛ نیازمند تنظیم معتبر و بازآزمایی دریافت/زبان |
| سلامت مرکز تلفن | داخلی/ترانک، قطع منبع، کیفیت ثبت‌شده و RTCP/QoS | sanequeue/realtime/ · reporting/quality.py | منبع و سناریوی صوت واقعی تعیین‌کننده‌اند؛ گواه زیر بار نیست |
| هویت و دسترسی | نقش، منوی کاربر، مجوز صف، صوت و خروجی مستقل | sanequeue/security/permissions.py · qpanel/local_accounts.py | کد؛ بازطراحی نباید این مجوزها را تغییر دهد |
| پروفایل و دفترچه | نام/داخلی/عکس/رمز، مخاطب و شماره‌گیری مجاز | sanequeue/security/profile.py · qpanel/operations.py | کد موجود؛ پذیرش کامل نام روی تلفن و مسیر بیرونی باقی است |
| ماژول‌های تلفنی | انتظار داخلی، کال‌بک، اصلاح Caller ID و صدای قابل تنظیم | sanequeue/pbx/features.py · callbacks.py | کد و پذیرش قبلی برخی تماس‌های آزمایشی |
| تنظیمات و بهره‌برداری | برند سازمان، تنظیم اتصال، نصب/ارتقا/غیرفعال‌سازی و آرشیو | scripts/provision.py · module_control.py · reporting/backup.py | کد؛ پشتیبان فعلی فقط آرشیو است، بازیابی کامل نصب نیست |
| ماژول‌های برنامه‌ریزی‌شده | فکس، paging، کمپین، رزرو و توسعه‌های مستند | docs/MODULE_PROGRAM.fa.md | برنامهٔ توسعه؛ وجود در سند به معنی پیاده‌سازی نیست |

فهرست تکمیلی مسیرهای ثابت API در ROUTE_INVENTORY.json و اهداف منو در NAVIGATION_INVENTORY.json آمده است. این استخراج AST است؛ ثبت مسیر در runtime یا پذیرش هر عمل را به‌تنهایی ثابت نمی‌کند. نام نمایشی کارشناس و صرف نام فایل ضبط نیز اثبات مجوز نیست.

## ابزارهای توسعهٔ نصب‌شده

کارگاه مستقل HTML/Vite، Storybook، Playwright/axe و مرجع Figma اضافه شدند. این ابزارها قابلیت تلفنی تازه یا پذیرش کامل قابلیت‌های جدول بالا محسوب نمی‌شوند. اجرای هیچ تست این کارگاه به PBX نیاز ندارد.

## Diagnostics — هستهٔ اولیه

Store خصوصی، API گزارش دستی مبتنی بر visit، سلامت heartbeat و worker تاریخی قطعات کوتاه صف پیاده شد. مشکوک/نیازمند بررسی است؛ نه تشخیص صدای یک‌طرفه، علت قطعی، SIP capture یا UI کامل. فهرست محصول اکنون ۳۷ ماژول و ۱۵۴ زیرقابلیت دارد. مرجع: docs/DIAGNOSTICS_PHASE1.fa.md.

## تکمیل گزارش‌ساز و مقایسهٔ کارشناس

خروجی حجیم دقیق و زمان‌بندی نسخه‌دار سفارشی، تفکیک راهبری مرکز تلفن/کال‌سنتر و رتبه‌بندی دوشاخصی با حداقل نمونه و نمودار اضافه شدند. fixture جدا و قابل تکرار روی سرور آزمایشی اجرا و عددها تطبیق شدند. پنل جاری به این fixture متصل نشده است؛ توسعه‌های باز در REPORTING_COMPLETION_CHECKLIST.fa.md باقی‌اند.
# Reporting UI delta — 2026-10-28

Shared calendar/ISO date-range controls, exact time-series gaps, paged comparisons, responsive/theme redraw and real image exports are implemented locally and browser-tested. Gregorian monthly source buckets are explicitly labelled; Persian monthly grouping is not implemented by a Persian date picker. No catalog capability or telephony acceptance status is upgraded merely by these visual changes.

