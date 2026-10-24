# مهاجرت معماری SaneQueue (باقی‌مانده)

برای کارکرد در مقیاس مرکز تماس بزرگ باید موارد زیر مستقل از beta.11 پیاده‌سازی و تأیید شوند:

1. AMI Collector دائمی با یک نشست، EventMask محدود و پردازش QueueCallerJoin, QueueCallerLeave, QueueCallerAbandon, AgentCalled, AgentConnect, AgentComplete, QueueMemberStatus, QueueMemberPause؛ ابتدا QueueStatus، سپس جریان رویدادها و resync بعد از reconnect با backoff+jitter.
2. انتشار snapshot/patch با WebSocket و کنترل backpressure، cursor و تعویض نشانه stale؛ تضمین تفکیک scope هر کاربر در سرور.
3. اتصال Channel/Bridge/Linkedid و شناسایی یکتای مکالمه، بدون اتکا به شمارش عضویت‌های Busy.
4. SQLite/PostgreSQL برای policy و audit، Redis یا lock دیتابیس برای سهمیه خروج اتمیک چندفرایندی. سیاست هماهنگ با عملیات خارج از پنل Issabel.
5. صف پایدار اعلان، retry و dead-letter برای بله؛ جلوگیری از ارسال دوباره با idempotency key.
6. دیالوگ و رویدادهای Originate/ChanSpy برای confirmed call control، TLS، RBAC production، audit و rate limit.
7. برنامه مهاجرت تدریجی واردات qpanel/ به sanequeue/ با suite کامل سبز؛ حفظ LICENSE/NOTICE تا زمانی که اثر اشتقاق کد وجود دارد.

این‌ها در beta.11 تکمیل نشده‌اند و نباید به‌عنوان امکانات فعال محصول فروخته شوند.
