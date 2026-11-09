# تصمیم‌ها

| تصمیم | وضعیت |
|---|---|
| ادامهٔ همین پروژه و حفظ قابلیت‌ها | دستور قطعی کاربر |
| توقف تغییر عملیاتی/نصب/Push تا گزارش اولیه و تأیید | دستور قطعی کاربر در ۲۰۲۶/۱۰/۲۸ |
| حفظ Flask/Jinja/Vanilla JS | پیشنهاد برای تأیید؛ نیاز به بازنویسی دیده نشد |
| Storybook HTML/Vite در tools/ui-workbench | پیشنهاد؛ نصب نشده |
| Playwright Test با fixture مصنوعی و mock HTTP/WebSocket | پیشنهاد؛ اجرا/نصب نشده |
| یکپارچه‌سازی توکن‌ها و ثبت در Figma | پیشنهاد؛ فایل هدف/اجازه ویرایش مشخص نیست |
| ایجاد AGENTS.md از پیش‌نویس پیوست | منتظر تأیید؛ فایل اصلی ایجاد نشده |
| ورود اسناد به docs/ai-workflow پس از تأیید | پیشنهاد؛ فعلاً پیش‌نویس خروجی است |

هر تصویب بعدی باید تاریخ، محدوده و لینک طرح/commit داشته باشد. نبود ابزار نباید به‌عنوان اجرای موفق آن گزارش شود.


## تأیید کاربر — ۲۰۲۶/۱۰/۲۸

کاربر دستور «اکی شروع کن همرو نصب و راه اندازی کن و یکسان سازی کن» داد. ثبت AGENTS و اسناد، نصب/پیکربندی ابزارهای توسعه‌ای، Workbench و پایهٔ یکسان‌سازی تأیید شد. طرح بصری گسترده، تغییر معماری runtime، Push و نصب روی سرور تماس هنوز در محدودهٔ این مرحله نیستند. فایل Figma جدید برای کار طراحی آماده می‌شود؛ نبود دسترسی باید صریح ثبت شود.

## نتیجهٔ اجرا — ۲۰۲۶/۱۰/۲۸

ابزارها محلی نصب شدند، چهار خانوادهٔ reference در Figma و stories ساخته شدند. از collectionهای جدا برای روشن/تیره در Starter استفاده شد. کارگاه vanilla و مستقل باقی ماند؛ runtime/framework عوض نشد. برای رفع توقف teardown ویندوز، runner Vite مستقیم نوشته شد. ۱۱ تست نهایی موفق است. ابزارهای build و browser در سرور تماس نصب نشدند. CI به صورت فایل آماده است ولی هنوز اجرا/Push نشده است. به‌روزرسانی Figma دستی و قابل بازبینی است؛ sync خودکار ادعا نمی‌شود. گام بعد نیازمند تصویب صفحهٔ واقعی پیش از ادغام گسترده است.

## ادامهٔ تأییدشده — فهرست کامل ماژول‌ها و آمادگی پایلوت

کاربر پس از مشاهدهٔ workbench گفت «اکی هست ادامه رو برو جلو» و فهرست کامل منابع/ماژول‌ها، Product Design و بستن پنج حوزهٔ پایلوت را خواست. اصلاح محتوای صفحهٔ موجود و fixture آن انجام شد؛ بازطراحی گسترده یا انتشار روی سرور واقعی انجام نشد. بر اساس درخواست صریح workflow، دو بررسی مستقل انجام و خروجی آن‌ها با کد/تست تطبیق شد. Figma صفحهٔ 02 با مرجع معنایی محدوده ایجاد شد؛ این مرجع جای تأیید بصری محصول زنده نیست. CUA هنوز bootstrap error دارد.

PDF: تست سراسری نشان داد سه وابستگی از قبل pin شدهٔ requirements/reporting.txt در venv محلی نصب نیستند؛ نصب همان نسخه‌های موجود برای اجرای آزمون PDF انجام شد. وابستگی جدیدی به runtime اضافه نشد و سرور تلفنی تغییر نکرد.

## تأیید Diagnostics — ۲۰۲۶/۱۰/۲۸

پس از ارائهٔ ADVANCED_CALL_DIAGNOSTICS_ASSESSMENT.fa.md، کاربر گفت «شروع کن». محدودهٔ آغاز: مرحلهٔ ۰ تا ۲ با دادهٔ موجود، اصلاح انتقال فیلدهای CEL، سلامت منبع، storage/API محدود و worker مشکوک‌یابی با fixture؛ بدون debug/capture جدید، فرمان کنترل تماس یا فعال‌سازی خودکار سرویس PBX. ساخت UI کامل و پذیرش live/load جداست.

## ادامهٔ گزارش‌گیری و fixture سرور

کاربر «بریم برای تکمیل کردن گزارش گیری» سپس تفکیک مرکز تلفن/کال‌سنتر، رتبه‌بندی/نمودار و «1000تا تماس ... روزانه ...1ماه» را خواست. fixtureجدا و محدود روی سرور آزمایشی صریحاً مجاز بود و اجرا شد؛ هیچ تماس زنده یا اتصال پنل اصلی به دادهٔ ساختگی انجام نشد. به‌جای افزایش سقف خواندن، partialindex رخداد زنگ اضافه شد؛ هزینهٔ ساخت اولیه روی آرشیو موجود باید پیش از rollout سنجیده شود. نمودار رتبه‌بندی جدول دقیق، حداقل نمونه و راهنمای تفسیر دارد؛ امتیاز کیفیت یا رتبهٔ ماهانهٔ کامل ادعا نمی‌شود. معماری Flask/Jinja/vanilla حفظ شد و وابستگی تازه نصب نشد.
# Reporting visual correction — 2026-10-28

User explicitly requested better charts, Persian calendar and browser/visual tests. Continue approved isolated Product Design/workbench workflow using existing vanilla product modules, no new runtime dependency. Preserve API dates and Gregorian bucket semantics, distinguish unknown from zero, use paged rendering rather than sampling and keep real PBX screenshots/session private. Figma reference is provisional because final screenshot quota was unavailable. No server deployment/push is included in this local stage. Completed reviewable evidence and remaining scope are in REPORTING_VISUAL_QA_20261028.fa.md and TEST_RESULTS.md.

# Authorized pilot publication — 2026-10-28

User explicitly requested GitHub publication, deployment on the existing test server and an install script with independent module controls. This authorizes the reviewed pilot changes and release publication; it does not authorize another company's PBX or a disruptive restart. Plan: publish beta.27 on the reporting branch with exact commit instructions, back up the preview and archive, validate the projection migration on a copy, replace the preview release with rollback, and keep Asterisk/MariaDB running. CPU-heavy AI remains opt-in. Loaded production and cross-version acceptance remain explicit, not certified by lab success.


## شمارهٔ یکتای مراجعهٔ صف — ۲۰۲۶/۱۱/۰۱
کاربر شمارش یکتای تماس‌گیرنده و ادامهٔ گزارش‌گیری را صریحاً خواست. واحد این مرحله شمارهٔ نرمال‌شدهٔ مشاهده‌شده در مراجعه‌های صف است؛ معادل شخص، تماس ورودی کل مرکز تلفن یا ادغام شماره‌های با پیش‌شمارهٔ متفاوت نیست. برای همهٔ صف‌های انتخاب‌شده مجوز مشاهدهٔ شماره و نقش مدیر/سرپرست لازم است. پاسخ فقط آمار دارد؛ نامعلوم و ورودِ فاقد شاهد تفکیک می‌شوند. سقف تعاملی ۵۰هزار مراجعه و مهلت reader حفظ شده است؛ دادهٔ ناقصِ بالای سقف منتشر نمی‌شود. بدون polling و بدون تغییر PBX.

## گزارش پاسخ و خروج بدون پاسخ — ۲۰۲۶/۱۱/۰۱
به درخواست صریح کاربر دو نمای مستقل مراجعه صف اضافه شد. پاسخ، خروج بدون پاسخ و حالت باز یا متناقض متقابلاً مجزا هستند؛ ورود فاقد شاهد از مخرج کنار گذاشته می‌شود. رویداد خروج صف خالی اثبات قطعی غیبت کارشناس نیست. نرخ از نتیجه‌های معلوم محاسبه می‌شود. شمارش بیشتر از ۵۰هزار مراجعه رد می‌شود و در هر فرایند وب یک محاسبه هم‌زمان پذیرفته می‌شود. این مرحله مسیر مجوز، AMI و دادهٔ PBX را تغییر نمی‌دهد.

## خروجی ریز پاسخ و خروج بدون پاسخ — ۲۰۲۶/۱۱/۰۱
خروجی CSV/XLSX/PDF از پردازشگر خصوصی موجود و نسخهٔ ثابت مراجعه‌ها استفاده می‌کند. فیلتر دسته همان قرارداد طبقه‌بندی نمایش است؛ وضعیت کار و دانلود فقط با مجوز جاری تمام صف‌ها انجام می‌شود. خروجی هنگام درخواست snapshot تازه می‌گیرد و تغییر داده پس از نمایش می‌تواند عدد را تغییر دهد. برای PDF سقف اختصاصی و برای Excel/CSV سقف‌های قبلی برقرار است. خروجی ریز جای خروجی تجمیعی هر جدول نیست.

## PBX call report — selected visual reference (2026-11-02)
The user approved the light RTL PBX call report reference and requested paired Persian dates followed by paired times, a grouped filter panel, five factual metrics, trend and extension charts, and separate duration and recording columns. Preserve current queue reports and do not invent unit access, call reasons, individual identity or audio ownership. The reference is a layout target, not a source of production values.
# 2026-11-04 — organizational access and optional AI report

The user explicitly requested implementation of organizational access and an AI report. This authorizes development, not deployment on the operational PBX. The prototype enforces historical, inventory-evidenced CDR endpoint ownership, uses independent capability grants, and defaults the external AI provider to disabled. The OpenAI Responses API receives only a redacted question for intent classification; report data and authorization stay server-side. Only a small set of aggregate intents is implemented. This decision does not authorize sending operational customer data or installing the prototype.
# 2026-11-09 lab deployment approval

The user explicitly authorized installation on the existing test server at `192.168.2.2` and continuation of the full redesign. Use the versioned release installer, retain the existing site origin, back up the active release and state, and keep the pre-install PBX idle check. Design work stays in the existing Jinja, CSS and JavaScript stack with the current role and report boundaries.

## RC6 report and access refinement

The user requested more legible charts, number-only extension search, a dropdown for long extension lists, and a single organizational access panel. The extension chart uses a stacked result bar and a labeled total. A number matches only observed SIP/PJSIP endpoints with that exact number. The picker can distinguish both technologies when necessary. The access form reuses the existing scoped permission model and commits organization, membership, assignment and grant changes together. Retain standalone revocation and assignment history under the supplementary controls.

## RC7 access center

The user requested a simpler design for creating accounts and granting access, with examples from other products. Use a directory-first layout and a three-step account editor. Keep organizational membership separately reviewable and hand off the selected account to that workflow. Use the existing permission ceilings and transaction boundaries. The previous authorization for installation on the existing test server applies to the reviewed access center update.
