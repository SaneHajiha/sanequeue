# مجوز AMI برای تست ایزابل Asterisk 20.12.0

**دو کاربر موقت** پیشنهاد می‌شود. به‌جای تغییر حساب فعلی `sq`، از کاربران تازه با گذرواژه‌های مستقل و قوی استفاده کنید.

در `/etc/asterisk/manager_custom.conf` (در صورت تأیید `#include` شدن آن):

```ini
[sq_monitor]
secret = NEW_RANDOM_MONITOR_PASSWORD
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = agent,call,system,reporting
write =

[sq_supervisor_test]
secret = DIFFERENT_RANDOM_SUPERVISOR_PASSWORD
deny = 0.0.0.0/0.0.0.0
permit = 127.0.0.1/255.255.255.255
read = agent,call,system,reporting
write = agent,call,originate
```

تونل SSH روی ویندوز: `ssh -N -L 127.0.0.1:15038:127.0.0.1:5038 root@192.168.2.2`؛ ترجیحاً با کاربر SSH بدون دسترسی root. برای اتصال مستقیم LAN باید فقط `permit = YOUR_WINDOWS_IP/255.255.255.255` را به ACL هر کاربر مورد استفاده اضافه کنید. **`permit = 0.0.0.0/0.0.0.0` خطرناک است.** TLS فعلاً خاموش است، پس مستقیم فقط در شبکه کاملاً ایزوله آزمایشی.

قبل از تغییر فایل، با `cp -a /etc/asterisk/manager_custom.conf /etc/asterisk/manager_custom.conf.bak.$(date +%Y%m%d-%H%M%S)` بکاپ بگیرید.

```bash
asterisk -rx "manager reload"
asterisk -rx "manager show user sq_supervisor_test"
for action in QueueStatus QueuePause QueueAdd QueueRemove QueuePenalty QueueChangePriorityCaller Hangup Originate Redirect BlindTransfer Park; do
  echo "===== $action ====="
  asterisk -rx "manager show command $action" | grep -Ei "Privilege|Synopsis"
done
```

**مجوز AMI سراسری در سطح کلاس است، نه در سطح صف.** حساب `sq_supervisor_test` در ایزابل آزمایشی و با مجوز موقت محلی استفاده شود، نه production. کلاس‌های `all` و `command` یا `config` را اضافه نکنید. UI SaneQueue نیز فقط Queue 8001 و Agent `Local/100@from-queue/n` (PJSIP/100) و Supervisor `PJSIP/101` را برای کنترل مجاز می‌داند. تغییر دیگری در سرور لازم نیست، مگر اینکه لاگ‌ها خلاف آن نشان دهند. شنود و ورود به مکالمه تنها در تماس آزمایشی با رضایت. پس از تست، حساب سرپرست را حذف یا دسترسی آن را غیرفعال کنید و `manager reload` کنید.

هیچ رمزی را در GitHub، فایل تست خروجی، تصویر یا چت منتشر نکنید.
