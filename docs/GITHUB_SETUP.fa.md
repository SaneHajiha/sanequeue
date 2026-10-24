# ادامه امن پروژه SaneQueue در GitHub

## کد کامل

این ZIP دارای سورس بازیابی‌شده و طراحی beta.3 است. GitHub فعلاً فقط مستندات را در [Pull Request #1](https://github.com/SaneHajiha/sanequeue/pull/1) دارد؛ **کد جدید هنوز در GitHub منتشر نشده** تا هنگام sync اشتباهی در مخزن رخ ندهد.

1. ZIP را در پوشه جدیدی در ویندوز استخراج کنید؛ **روی نسخه نصب‌شده ایزابل overwrite نکنید**.
2. برای انتقال از Git for Windows استفاده کنید؛ ورود GitHub در مرورگر Git Credential Manager انجام می‌شود. هیچ رمزی را داخل اسکریپت یا ChatGPT قرار ندهید.
3. PowerShell را در پوشه SaneQueue باز کنید و ابتدا اجرای خشک را بزنید:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\SYNC_GITHUB_WINDOWS.ps1
```

4. اسکریپت یک پوشه staging مستقل کنار پوشه سورس ایجاد می‌کند. `git diff --cached` را مرور کنید و به‌ویژه فایل‌های حساس/مشتری/تنظیمات را حذف کنید. پوشه staging را نگه دارید.
5. بعد از تأیید تغییرات و نبود اطلاعات محرمانه، **در همان پوشه staging** دستورهای زیر را اجرا کنید (اسکریپت فوق فقط dry run انجام می‌دهد):

```powershell
cd ..\sanequeue-github-staging
git status --short
git diff --cached --stat
git diff --cached --check
git commit -m "feat(monitoring): recover SaneQueue 2.0 beta.3 live operations"
git push origin work-recovery-2026-10-22
```

6. [Pull Request #1](https://github.com/SaneHajiha/sanequeue/pull/1) را بررسی کنید و قبل از merge تست‌های CI و امنیت را تأیید کنید.

توجه: `-Push` در اسکریپت تنها زمانی قابل استفاده است که پوشه staging هنوز وجود نداشته باشد. روش دستی از همان staging برای مرور دقیق‌تر امن‌تر است.

## پروفایل GitHub

متن حرفه‌ای در `docs/GITHUB_PROFILE_DRAFT.md` قرار دارد. برای نمایش آن در صفحه GitHub نیاز به یک مخزن عمومی **دقیقاً به نام `SaneHajiha`** در حساب `SaneHajiha` دارید:

1. GitHub > New repository > Repository name: `SaneHajiha` > Public > Add README.
2. محتوای `docs/GITHUB_PROFILE_DRAFT.md` را در `README.md` این مخزن قرار دهید.
3. بخش About حساب را با عنوان `IT & Network Infrastructure Manager | Consultant | VoIP & Security` و وب‌سایت `https://sanehajiha.ir` تنظیم کنید.
4. مخزن `sanequeue` را پس از انتشار امن نسخه بتا پین کنید.

اطلاعات خصوصی رزومه مانند شماره تماس و معرف‌ها وارد README عمومی نشده‌اند.

> فایل‌های فونت همراه بسته ارائه نمی‌شوند. رابط از فونت سیستم استفاده می‌کند؛ در صورت نصب Vazirmatn روی ویندوز، قلم فارسی همان خواهد بود.
