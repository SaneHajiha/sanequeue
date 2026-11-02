# Background service controls / کنترل سرویس‌های پس‌زمینه

These commands require root on the Linux installation. They control installed
SaneQueue workers, not user permissions, web-menu visibility or a guarantee that
every functional module is installed. Status reports missing units explicitly;
enable/disable refuses an incomplete installation.

این فرمان‌ها با دسترسی root روی سرور لینوکس اجرا می‌شوند. منظور از `--module`
گروه سرویس پس‌زمینه است؛ مجوز کاربر، نمایش منو و تنظیمات قابلیت تلفنی تغییر
نمی‌کند. نبودن سرویس در وضعیت مشخص می‌شود و عملیات روی نصب ناقص رد می‌شود.

| Name | Scope / محدوده | Dependency / وابستگی |
|---|---|---|
| monitoring | Collector and inventory timer/service; web and Redis stay running / جمع‌آورنده و موجودی داخلی‌ها | — |
| reporting | Historical archive importer / واردکردن رویدادهای تاریخی | — |
| exports | Background CSV/XLSX/PDF export worker / خروجی پس‌زمینه | reporting |
| plans | Scheduled export dispatcher / زمان‌بندی گزارش | exports → reporting |
| ai | Speech transcription worker / تبدیل صوت به متن | reporting |
| generative | Text-analysis worker / تحلیل متن | ai → reporting |
| surveys | Post-call survey adapter / آداپتور نظرسنجی پس از تماس | — |
| media | Incident media worker / پردازش صوت رخدادها | — |

## Commands / فرمان‌ها

```bash
sudo sanequeuectl status
sudo sanequeuectl status --module reporting
sudo sanequeuectl disable --module reporting --cascade --dry-run
sudo sanequeuectl disable --module reporting --cascade
sudo sanequeuectl enable --module reporting
sudo sanequeuectl enable --module exports
sudo sanequeuectl enable --module plans
```

Disabling a parent refuses enabled-intent installed dependents unless `--cascade`
is explicit. Cascade records each dependent's disabled state; enabling the parent
does **not** automatically re-enable children. Enable dependencies first, then the
specific worker. `--dry-run` performs validation without writing files or calling
systemd. Global emergency disable must be lifted before enabling one worker.

غیرفعال‌کردن والد، بدون `--cascade` در صورت وجود وابستهٔ نصب‌شده و غیرفعال‌نشده
رد می‌شود. فعال‌کردن والد، فرزندان را خودکار فعال نمی‌کند؛ ترتیب بالا را رعایت
کنید. `--dry-run` هیچ فایل یا سرویسی را تغییر نمی‌دهد. تا توقف اضطراری سراسری
برقرار است، فعال‌کردن یک سرویس مجاز نیست.

```bash
sudo sanequeuectl disable                 # emergency stop / توقف اضطراری کل پنل
sudo sanequeuectl enable                  # preserves individual disabled states
sudo sanequeuectl disable --module monitoring
sudo sanequeuectl enable --module monitoring
```

Global disable deliberately leaves the shared FastAGI listener running so it does
not terminate in-flight AGI sessions. Both disabled flags prevent new feature
dispatch; status may therefore show FastAGI active while the module is disabled.
Global uninstall first verifies the PBX is idle before changing flags/services,
restores the managed dialplan while FastAGI remains available, and only then
stops that listener. A failed restore leaves FastAGI running for safety.
If global resume fails, both disabled flags are restored and partial background
starts are stopped; FastAGI is preserved even if that resume just started it.

توقف سراسری، FastAGI مشترک را برای درخواست‌های در حال اجرا روشن نگه می‌دارد؛
نشانگرهای توقف، اجرای جدید قابلیت‌ها را می‌بندند. بنابراین فعال‌بودن FastAGI در
وضعیت توقف سراسری عمدی است. حذف کامل ابتدا بی‌تماس‌بودن مرکز تلفن را بررسی
می‌کند، سپس dialplan مدیریت‌شده را با FastAGI فعال برمی‌گرداند و در پایان آن
سرویس را متوقف می‌کند. شکست بازگردانی، FastAGI را متوقف نمی‌کند.
اگر فعال‌سازی سراسری شکست بخورد نیز هر دو نشانگر توقف برمی‌گردند، اما FastAGI
حتی اگر تازه اجرا شده باشد برای حفظ درخواست‌های در حال اجرا روشن می‌ماند.

Historical data is retained. Stopping reporting makes the archive stale; it does
not delete reports or hide existing history. Stopping exports/plans may leave
queued work pending; existing worker lease/recovery behavior applies on resume.
These service controls do not deny new API jobs or hide their menus. Monitoring
disable deliberately removes live monitoring; the web process can remain up.

دادهٔ تاریخی حذف نمی‌شود. با توقف گزارش‌گیری، واردکردن اطلاعات تازه متوقف می‌شود
و گزارش قبلی ممکن است قدیمی باشد. کارهای صف‌شده پس از فعال‌سازی بر اساس قواعد
بازیابی worker ادامه می‌یابند. این فرمان‌ها منو را پنهان یا ثبت درخواست API را
ممنوع نمی‌کنند. توقف monitoring یعنی اطلاعات زنده دیگر تازه نمی‌شود.

## Persistence, safeguards and rollback / ماندگاری و بازیابی

- Disabled markers: `/etc/sanequeue/modules/<name>.disabled`.
- Managed unit drop-ins: `/etc/systemd/system/<unit>.d/70-sanequeue-service-control.conf`.
- The additional `ConditionPathExists=!…` survives reboot and unit-file upgrades;
  it does not replace existing unit conditions. Global enable and the installer
  also filter individually disabled workers and their dependencies.
- The local controller serializes changes with a bounded five-second lock wait.
  Stop/start/reload failure restores prior managed file contents and prior
  service enable/active states where possible. `rollback_incomplete` means manual
  intervention is needed; inspect `systemctl status` and the journal. A stopped
  in-flight operation cannot be undone by restoring service state.
- No Asterisk/MariaDB restart, AMI action, dialplan reload or customer call is
  performed by **per-service** controls. Global uninstall is a different existing
  operation: it restores managed PBX configuration and requires an idle PBX.

نشانگر و drop-in با راه‌اندازی مجدد و تعویض فایل سرویس باقی می‌مانند. اگر عملیات
موفق نشود، فایل‌ها و وضعیت قبلی سرویس‌ها تا حد امکان برگردانده می‌شوند؛ پیام
`rollback_incomplete` به معنی نیاز به بررسی دستی است. بازیابی وضعیت سرویس، کار
در حال اجرایی را که قطع شده به عقب برنمی‌گرداند. کنترل تک‌سرویس، استریسک را
ری‌استارت یا dialplan را reload نمی‌کند.

AI, generative analysis and surveys require their existing explicit opt-in marker
and private configuration. The controller never creates tokens, models, bindings
or opt-ins. Enabling a service verifies that systemd considers it active, not that
its external provider, model, telephone flow or business result has passed a live
test.

## Callback, waiting and caller ID / کال‌بک، انتظار و شناسه تماس‌گیرنده

There is no independent callback/caller-ID service switch. They share FastAGI;
stopping it could affect multiple telephone features. Use the existing PBX
feature settings in the panel. Unsupported names such as `callback` are rejected
by this CLI; they are never mapped to an unsafe shared-service stop.

برای کال‌بک، انتظار داخلی و اصلاح شماره از تنظیمات قابلیت‌های تلفنی داخل پنل
استفاده کنید. آن‌ها FastAGI مشترک دارند؛ این CLI سرویس مشترک را به اسم یک
قابلیت متوقف نمی‌کند.

## Installer behavior / رفتار نصب و ارتقا

The installer preserves service-disabled markers and starts only allowed groups.
When monitoring is intentionally disabled, collector acceptance is skipped rather
than reported as a live-health pass. Core HTTP/collector acceptance runs before
telephone application. The final PBX adapter stage keeps its existing idle guard;
busy calls leave it pending and its timer retries. This is reported separately
from successful web installation. An already-running FastAGI process is preserved
during upgrade; adopting changed FastAGI code may require a later controlled
service restart during an idle maintenance window.

نصب وب به معنی اعمال موفق dialplan نیست. روی مرکز تلفن مشغول، تغییر تلفنی تا
آزادشدن تماس‌ها معوق می‌ماند و وضعیت آداپتور باید جدا بررسی شود. FastAGI فعال
هنگام ارتقا قطع نمی‌شود؛ اجرای کد تازهٔ آن ممکن است به راه‌اندازی مجدد کنترل‌شده
در زمان بدون تماس نیاز داشته باشد. آزمون واقعیِ systemd، راه‌اندازی مجدد سرور،
مدل AI و مسیرهای تلفنی باید روی سرور آزمایشی/پایلوت انجام شود؛ آزمون واحد از
systemd ساختگی استفاده می‌کند.
