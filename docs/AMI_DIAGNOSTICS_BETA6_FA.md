# بررسی دقیق Actionهای AMI در Asterisk 20.12.0

روی **سرور تست** اجرا کنید؛ دستورات فقط خواندنی‌اند:

```bash
asterisk -rx "manager show user sq"
for action in QueueStatus CoreShowChannels PJSIPShowEndpoints PJSIPShowContacts PJSIPShowRegistrationsOutbound ParkedCalls QueuePause QueueAdd QueueRemove QueuePenalty Hangup Originate; do
  echo "===== $action ====="
  asterisk -rx "manager show command $action" | grep -E "Privilege|Synopsis|not found|not registered|^=+" || true
done
asterisk -rx "module show like res_pjsip_manager"
asterisk -rx "module show like res_pjsip"
```

در اسکرین‌شات ثبت‌شده، `QueueStatus`, `CoreShowChannels`, `Hangup`, `Originate`, `ListCommands`, `ParkedCalls` در فهرست حساب دیده می‌شدند؛ `PJSIPShowEndpoints` و `PJSIPShowContacts` مجاز نبودند یا Action نبودند. این دو Action در Asterisk 20 وجود دارند، اما باید کلاس مجوز و ماژول روی **همین build** بررسی شود. معمولاً کلاس `system` برای اجرای این Actionها لازم است؛ اضافه کردن `write=system` قدرت بیشتری شامل مدیریت سیستم می‌دهد و نباید برای حساب عمومی یا سرور عملیاتی استفاده شود. اگر واقعاً برای آزمایش لازم شد فقط در حساب **موقت و جداگانه آزمایشگاهی** با ACL محدود اجرا و پس از تست حذف کنید.

`read` برای رویدادهای بازگشتی با `write` مجوز اجرای Action متفاوت است. اگر فرمان در ListCommands ظاهر شد ولی EventListComplete نیامد، مجوز read و ماژول را بررسی کنید. `write=all` و `write=command` برای این تست توصیه نمی‌شود.

برای اتصال مستقیم AMI از `192.168.2.2:5038`، حساب فقط IP کامپیوتر ویندوز را Permit کند و ترافیک در LAN تست باشد. روش بهتر تونل SSH محدود به 127.0.0.1:15038 است. رمز قبلاً افشاشده را بچرخانید و در چت منتشر نکنید.
