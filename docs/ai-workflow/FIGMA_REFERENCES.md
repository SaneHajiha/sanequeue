# مرجع Figma و کد

فایل ایجادشده و تأیید اتصال: https://www.figma.com/design/eKxCAaXf89ch2xu2KppEM5

صفحه: 0:1 · Foundations & component reference

| مرجع | Node |
|---|---|
| Foundations light | 2:28 |
| Foundations dark | 2:69 |
| Button | 3:10 |
| KPI | 3:31 |
| AgentStatus | 3:56 |
| DataTable | 3:89 |

۲۴ متغیر رنگ به fill/stroke متن و کامپوننت‌ها bind شده‌اند؛ WEB syntax به var(--sq-...) اشاره دارد. به دلیل محدودیت یک mode طرح Starter، روشن و تیره collection جدا دارند. مرجع کد: tools/ui-workbench/src/tokens.json و components.js. ۸ توکن فاصله/شعاع نیز در collection هندسه ایجاد و به ۳۰ variant کامپوننت متصل شدند. CSS تولیدی همان توکن‌ها را از JSON می‌خواند. همگام‌سازی تغییرات بعدی فعلاً دستی است.

تفاوت فونت: runtime از Vazirmatn محلی استفاده می‌کند؛ در فهرست بررسی‌شدهٔ Figma این فونت موجود نبود و نمونهٔ فارسی با Noto Sans Arabic ساخته شد. بنابراین برابری پیکسلی فونت‌ها ادعا نمی‌شود. فایل فعلاً component reference است، نه طرح نهایی تمام صفحات.

Screenshot واقعی خانوادهٔ وضعیت، بریدگی برچسب بلند را نشان داد؛ اندازهٔ component set به Auto تغییر کرد و screenshot دوم رفع بریدگی را نشان داد. داده‌ها ساختگی و فاقد اطلاعات مشتری‌اند. هیچ طرح عملیاتی گسترده‌ای هنوز تأیید نشده است.

## مرجع دامنهٔ ماژول‌ها

صفحهٔ 02 · Module scope & pilot boundary با ID `7:2` و فریم `7:3` اضافه شد. چهار instance از KPI موجود و متغیرهای رنگ/هندسه استفاده شدند؛ screenshot واقعی فریم بررسی شد. این یک مرجع معنایی قابل ویرایش از گروه‌ها و مرز پذیرش است، نه کپی پیکسلی صفحهٔ عملیاتی یا تأیید UX audit زنده.

مرجع دامنهٔ `7:3` پس از افزودن Diagnostics به ۳۷ ماژول، ۹ built، ۱۵ partial و ۱۳ planned به‌روزرسانی و screenshot آن بررسی شد. فقط متن/شمارندهٔ مرجع تغییر کرد؛ طرح کامل Diagnostics ایجاد یا تأیید نشده است.
