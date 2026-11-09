# نصب آزمایشی و بازیابی SaneQueue 2.1.0-rc.1

هدف این نسخه میزبان Issabel 5، Rocky Linux 8 و Asterisk 20 است. پیش از نصب، یک ماشین آزمایشی مستقل با نسخه و چیدمان مشابه آماده کنید. دسترسی به ترانک و مقصدهای بیرونی را در ماشین آزمایشی محدود کنید. نسخهٔ پشتیبان ماشین را همراه با شناسهٔ ماشین و تاریخ ثبت کنید. برای CDR/CEL از حساب SQL محلی و فقط‌خواندنی استفاده کنید.

## بررسی و نصب روی ماشین آزمایشی

فایل‌های `SaneQueue-2.1.0-rc.1.tar.gz` و `SHA256SUMS-rc1` را از بستهٔ تحویل به یک پوشه منتقل کنید. هش را با نسخه‌ای که از مسیر مورد اعتماد دریافت کرده‌اید تطبیق دهید. پیش‌بررسی به Python 3.10 تا 3.12 با venv، باینری Redis، systemd و شنوندهٔ محلی AMI نیاز دارد.

```bash
sha256sum --ignore-missing -c SHA256SUMS-rc1
test -f SaneQueue-2.1.0-rc.1.tar.gz
tar -xzf SaneQueue-2.1.0-rc.1.tar.gz
cd SaneQueue-2.1.0-rc.1
sudo bash scripts/install.sh --preflight
```

در Rocky از مخزن مورد تأیید سازمان برای نصب پیش‌نیازهای سیستم استفاده کنید. برای نصب آفلاین، روی ماشین ساختِ هم‌معماری و هم‌نسخهٔ Python، wheelها را با دستور زیر جمع‌آوری کنید. پوشهٔ wheelها و هش آن‌ها را از مسیر معتبر به ماشین آزمایشی انتقال دهید.

```bash
python3.11 -m pip download --only-binary=:all: --dest wheelhouse \
  -r requirements/modern.txt -r requirements/reporting.txt
(cd wheelhouse && sha256sum -- *.whl > SHA256SUMS)
```

ابتدا گواهی و نام HTTPS محیط آزمایشی را در پراکسی معکوس آماده کنید و درخواست‌های HTTPS و WebSocket را به `127.0.0.1:5000` بفرستید. نام نمونه را با نام واقعی محیط آزمایش عوض کنید. نصب از ترمینال، گذرواژهٔ نخستین مدیر را با ورودی مخفی می‌گیرد. در ارتقا حساب‌ها حفظ می‌شوند. نصب نیاز به PBX بدون کانال فعال دارد.

```bash
sudo env SANEQUEUE_PUBLIC_ORIGIN=https://sq-lab.example.test bash scripts/install.sh
sudo sanequeuectl status
sudo systemctl is-active sanequeue sanequeue-collector sanequeue-redis
sudo /opt/sanequeue/.venv/bin/python -m pip check
curl --fail --silent --show-error --output /dev/null http://127.0.0.1:5000/login
```

برای حالت آفلاین، ابتدا `(cd /path/to/wheelhouse && sha256sum -c SHA256SUMS)` را اجرا کنید و به فرمان نصب `SANEQUEUE_WHEELHOUSE=/path/to/wheelhouse` را اضافه کنید. نصب محل پشتیبان خصوصی را چاپ می‌کند. آزمون سلامت نصب، تکمیل نمونهٔ اولیهٔ collector و پاسخ صفحهٔ ورود را بررسی می‌کند. در نصب تازه فعال‌سازی تلفنی یک مرحلهٔ جدا با پرچم `SANEQUEUE_ACTIVATE_TELEPHONY=1` است. در ارتقا، زمان‌سنج فعالِ قبلی دوباره راه می‌افتد. وضعیت اجرای آن را در `/run/sanequeue/pbx-status.json` بررسی کنید.

پس از ورود مدیر، بازهٔ واحدی را برای گزارش صف و گزارش PBX انتخاب کنید. ابتدا پوشش منابع و زمان آخرین نمونه را بررسی کنید. گزارش صف هر مراجعه را می‌شمارد و گزارش PBX هر بخش ثبت‌شدهٔ CDR را. با یک حساب ناظر، دامنهٔ صف‌ها و پوشاندن شماره را بررسی کنید. با یک حساب مشاهده‌گر، دسترسی به گزارش کل PBX باید رد شود. خروجی و ضبط را فقط برای حساب‌های دارای مجوز مربوط بررسی کنید.

## بازیابی

در صورت شکست نصب پس از تهیهٔ نسخهٔ پشتیبان، نصاب به‌طور خودکار بازگشت را آغاز می‌کند. وضعیت موفق را از خروجی نصاب و وضعیت سرویس‌ها بررسی کنید. فایل‌های نوشته‌شده در تلاش ناموفق در پوشه‌های خصوصی `.sanequeue*-rollback-*` کنار پوشهٔ اصلی نگه داشته می‌شوند. از کپی‌کردن فایل SQLite روی فرایند فعال خودداری کنید.

```bash
sudo ls -ld /var/backups/sanequeue/*-installer
sudo readlink -f /opt/sanequeue
sudo sanequeuectl status
sudo systemctl is-active asterisk sanequeue sanequeue-collector sanequeue-redis
sudo journalctl -u sanequeue -u sanequeue-collector --since '-15 min' --no-pager
```

اگر پس از نصب موفق به بازگشت نیاز دارید، راه قابل بازبینی این نسخه بازگرداندن snapshot کامل همان ماشین آزمایشی است. مثال زیر فقط برای ماشین آزمایشی تحت libvirt با snapshot داخلی معتبر و همهٔ دیسک‌های لازم است. نام ماشین را به مقدار ثبت‌شده تغییر دهید. بازگشت snapshot تغییرات پس از آن را از دیسک فعال خارج می‌کند. در صورت نیاز ابتدا دادهٔ جدید را از ماشین آزمایشی جداگانه نگه دارید.

```bash
# روی هایپروایزر آزمایشی، قبل از نصب و پس از خاموشی منظم مهمان
virsh domstate sq-rc1-lab
virsh snapshot-create-as sq-rc1-lab sanequeue-before-rc1 --atomic
virsh snapshot-info sq-rc1-lab sanequeue-before-rc1
virsh start sq-rc1-lab

# هنگام بازگشت، پس از خاموشی منظم مهمان و تأیید حالت shut off
virsh domstate sq-rc1-lab
virsh snapshot-info sq-rc1-lab sanequeue-before-rc1
virsh snapshot-revert sq-rc1-lab sanequeue-before-rc1 --running
```

پس از بازگشت، سلامت Asterisk، نسخهٔ مقصد `/opt/sanequeue`، صفحهٔ ورود و بازهٔ گزارش را بررسی کنید. مسیر snapshot برای هایپروایزرهای دیگر به سازوکار پشتیبان‌گیری همان محیط وابسته است. پیش‌بررسی میزبان و آزمون نرم‌افزار به‌تنهایی نصب کامل، بازیابی دیسک، تماس زنده و ظرفیت تماس هم‌زمان را تأیید نمی‌کند.
