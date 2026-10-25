# SaneQueue 2.1.0-beta.26

اصلاح نصب روی Rocky/EL8: تغییر مالکیت و مجوز حالت خصوصی از طریق `O_NOFOLLOW`، `fchown` و `fchmod` روی یک فایل باز انجام می‌شود؛ به پشتیبانی `chmod(..., follow_symlinks=False)` وابسته نیست. آزمون برگشت نصب beta.25 حفظ فرایند Asterisk را تأیید کرد. برای نصب جدید از beta.26 استفاده کنید.

Fix Rocky/EL8 installation: private-state permissions use one no-follow file descriptor with `fchown`/`fchmod`, avoiding unsupported `lchmod` behavior. The failed beta.25 lab upgrade rolled back without restarting Asterisk. Use beta.26 for installation.

All queue visual, observed metric and telephone module changes from [beta.25](RELEASE_BETA25.md) are included. See [validation evidence and remaining pilot gates](AUDIT_BETA26.md).
