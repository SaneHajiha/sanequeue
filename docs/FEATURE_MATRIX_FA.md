# نقشه امکانات حرفه‌ای SaneQueue در مقایسه با OpDesk / FOP2 / ویپینگ

منابع: [OpDesk](https://github.com/Ibrahimgamal99/OpDesk)، [FOP2](https://www.fop2.com/)، [ویپینگ](https://voiping.ir/product/ماژول-گزارشات-و-مانیتورینگ-آنلاین-صف/)، [مستندات رسمی Asterisk](https://docs.asterisk.org/Asterisk_20_Documentation/API_Documentation/AMI_Actions/).

**پایه نرم‌افزار:** مشتق متن‌باز QPanel با مجوز MIT. از سورس، تصاویر و دارایی‌های OpDesk یا محصولات تجاری کپی نشده است. OpDesk با GPLv3 منتشر می‌شود؛ ترکیب کدهای آن نیازمند بررسی شرایط مجوز است.

| ماژول | وضعیت فعلی | نکته |
|---|---|---|
| داشبورد با ۶ KPI | آماده تست | Asterisk QueueStatus |
| نمودار انتظار و آماده‌بودن | آماده تست | فقط روند نمونه‌برداری از زمان بازشدن صفحه، بدون دیتای تاریخی |
| دونات وضعیت کارشناسان | آماده تست | بر اساس عضویت در صف، نه افراد یکتا |
| صف‌ها، انتظار، SLA و میانگین Hold | آماده تست | شمارنده‌های Asterisk از آخرین reset |
| وضعیت اپراتورها، Pause/Resume | بتا، تست PBX لازم | محدودیت ۳۰ دقیقه، صف 8001 |
| عضویت پویا و Penalty | بتا، تست PBX لازم | جلوگیری از حذف اعضای static |
| اولویت تماس، Hangup | بتا، تست PBX لازم | فقط تماس حاضر در صف آزمایشی |
| Listen/Whisper/Barge | بتا، تست PBX لازم | تماس تست با رضایت و داخلی مشخص |
| هشدارها، صدا و Wallboard | آماده تست | هشدار مبتنی بر قواعد، نه AI |
| فهرست کانال‌ها و سلامت PBX | بتا، فقط خواندنی | نتیجه فقط با مجوز AMI و درخواست کاربر |
| وضعیت PJSIP و ParkedCalls | بتا، فقط خواندنی | Asterisk module و مجوز لازم |
| Transfer/Attended Transfer/Pickup | برنامه توسعه | عملیات واقعی هنوز پیاده‌سازی نشده |
| Park/Retrieve/Conference | برنامه توسعه | فقط ParkedCalls read-only اولیه موجود |
| Trunk status/SIP Registration | برنامه توسعه | آداپتور جدا لازم |
| کیفیت RTP/MOS/Jitter/Packet Loss | برنامه توسعه | RTCP/RTP telemetry لازم |
| DND/Presence همه داخلی‌ها | برنامه توسعه | رویدادهای device/presence و RBAC |
| WebRTC Softphone | برنامه توسعه | WSS/SIP.js/HTTPS/TLS |
| CRM/دفترچه تلفن/Click-to-call | برنامه توسعه | پایگاه داده + API |
| API/اعلان موبایل/Push | برنامه توسعه | auth/role/event bus |
| AI Supervisor Copilot و STT | برنامه توسعه | اختیاری، local-first، privacy-first |
| چندسازمانی/سطح دسترسی واقعی | برنامه توسعه | Demo Login کنونی برای مشتری مناسب نیست |
| گزارش تاریخی/Excel/CDR | خارج از فاز فعلی | مطابق تصمیم مالک پروژه |

**معیار رسیدن به نسخه Production:** احراز هویت واقعی، لاگ بدون اطلاعات حساس، جداکردن queue scopes برای هر کاربر، تست‌های امنیت و بار، تست عملیاتی روی Asterisk 20، CI/CD، فرایند rollback و نصب استاندارد.
