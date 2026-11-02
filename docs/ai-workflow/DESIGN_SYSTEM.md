# پیشنهاد Design System — هنوز تأیید نشده

ابتدا توکن‌های موجود --bg/--card/--ink/--muted/--line/--accent و وضعیت‌ها از CSS استخراج و ناهماهنگی‌ها ثبت شوند. سپس رنگ معنایی آماده/زنگ/مکالمه/توقف/آفلاین، فونت فارسی/انگلیسی، فاصله، اندازه کنترل، شعاع، سایه، focus و motion در یک منبع نسخه‌دار تصویب شوند. رنگ تنها حامل وضعیت نباشد؛ برچسب و آیکون لازم است.

کامپوننت‌ها: KPI با تعریف/بازه/منبع، Queue card، Agent state، Waiting row، Active call row، Table/Filter/Pagination، Chart/legend، Dialog/confirmation، Input/error، Button/toolbar، Alert، Help popover و Permission state.

برای هر کامپوننت حالت عادی، loading، empty، error، success، disabled و denied با FA/EN و RTL/LTR و تم روشن/تیره ساخته شود. جدول پرتراکم دو سطح خلاصه/جزئیات داشته باشد؛ در موبایل کنترل‌ها خوانا و قابل لمس باشند. مدل داده و مجوزهای Backend مبنای rendering باشند. Wrap-up ثبت‌نشده، SLA بدون مخرج و دادهٔ فاقد پوشش با نامعلوم نمایش داده شوند، نه صفر.

هدف اولیهٔ آزمون responsive: موبایل ۳۹۰، تبلت ۷۶۸، دسکتاپ ۱۴۴۰ و wallboard ۱۹۲۰ پیکسل؛ این‌ها پیشنهادند، نه طرح نهایی. داده و ساعت fixture ثابت، reduced motion و دسترسی صفحه‌کلید بررسی شوند. طراحی Figma پس از capture واقعی و تحلیل UX انجام می‌شود، نه از روی تصور.

## پیاده‌سازی پایهٔ v1

منبع قابل اجرا: tools/ui-workbench/src/tokens.json، tokens.css تولیدشده و components.js. رنگ‌های اصلی از محصول گرفته شده‌اند؛ muted/status و مرزها برای خوانایی نمونه تقویت شده‌اند. فعلاً runtime محصول از این فایل‌ها import نمی‌کند. فرم، توضیح شاخص، Unknown، وضعیت متنی، کیبورد، تم و زبان در fixtureها وجود دارد. مرجع Figma و تفاوت فونت در FIGMA_REFERENCES.md مستند است. طرح تمام صفحات و یکسان‌سازی بصری محصول هنوز مرحلهٔ بعد از تأیید است.
