"""One bilingual source for contextual panel help and published user manuals."""


def guide(fa,en,fa_steps,en_steps,fa_note='',en_note=''):
    return {'fa':{'intro':fa,'steps':fa_steps,'note':fa_note},'en':{'intro':en,'steps':en_steps,'note':en_note}}


GUIDES={
 'live':guide('نمای سریعِ فشار صف و ظرفیت پاسخ‌گویی. شمارنده‌ها از زمان بازنشانی Asterisk هستند.','A quick view of queue pressure and staffing. Counters start at the last Asterisk queue reset.',
  ['صف یا کارشناس را با فیلتر بالای صفحه پیدا کنید.','کارت منتظر و طولانی‌ترین انتظار را با ظرفیت کارشناسان مقایسه کنید.','نمودار روند فقط نمونه‌های همین مرورگر را نشان می‌دهد.'],
  ['Filter the queue or agent at the top.','Compare waiting callers and longest wait with agent availability.','Trend charts use samples collected by this browser only.'],
  'پیام دادهٔ قدیمی یعنی وضعیت لحظه‌ای قابل اتکا نیست؛ تا اتصال مجدد کنترل تماس انجام ندهید.','A stale-data warning means the live state cannot be trusted; wait for reconnection before controlling calls.'),
 'queues':guide('هر کارت، وضعیت صف، اعضا و هشدار همان صف را کنار هم نشان می‌دهد.','Each card combines queue metrics, members and queue-specific alerts.',
  ['روی جزئیات صف بزنید تا شاخص‌ها و تعریف آن‌ها را ببینید.','SLA درصد پاسخ در مهلت تعیین‌شدهٔ خود Asterisk است.','میانگین انتظار و مکالمه مربوط به تماس‌های پاسخ‌داده‌شده‌اند.'],
  ['Open queue details for metrics and their definitions.','SLA is the percentage answered within the Asterisk service-level target.','Average wait and talk refer to answered calls.']),
 'calls':guide('تماس‌ها را با کارشناس، صف و زمان مکالمه دنبال کنید.','Follow conversations by agent, queue and talk duration.',
  ['صف را انتخاب و وضعیت تازگی داده را بررسی کنید.','برای عملیات، کارشناس یا تماس فعال را انتخاب کنید.','انتقال مستقیم مقصد را زنگ می‌زند؛ انتقال با مشورت ابتدا امکان صحبت با مقصد را می‌دهد.'],
  ['Select a queue and check data freshness.','Select the current agent or active call before acting.','Blind transfer rings the destination; attended transfer permits consultation first.'],
  'هر تماس می‌تواند چند کانال داشته باشد. مسیر IVR فقط برای منوهای ivr-* و رویدادهای مشاهده‌شده از زمان اتصال ثبت می‌شود؛ کلیدهای حین مکالمه ذخیره نمی‌شوند. عامل پایانِ بخش صف فقط با شواهد صریح ثبت می‌شود؛ پس از انتقال یا در نبود شواهد، نامشخص است.',
  'One call can contain multiple channel legs. IVR entry/selection is observed only in ivr-* menus after collector connection; in-call DTMF is not stored. Queue-leg hangup party requires explicit evidence; after transfer or without evidence it remains unknown.'),
 'waiting':guide('تماس‌های منتظر با جایگاه و مدت انتظار نمایش داده می‌شوند.','Waiting callers are listed with queue position and elapsed wait.',
  ['برای دیدن شمارهٔ کامل باید مجوز نمایش شماره داشته باشید.','افزایش اولویت ترتیب صف را تغییر می‌دهد؛ ظرفیت پاسخ‌گویی را بیشتر نمی‌کند.','قطع تماس فقط بعد از بررسی تماس انتخاب‌شده انجام شود.'],
  ['Full caller numbers require a separate caller-details permission.','Priority changes queue ordering; it does not add answering capacity.','Review the selected caller before hanging up.']),
 'agents':guide('وضعیت و کارکرد هر عضویت صف جداگانه ثبت می\u200cشود.',
  'State and observed daily activity are tracked separately for each queue membership.',
  ['از «پروفایل و وضعیت من» وضعیت عضویت خود را تغییر دهید؛ برای توقف، کارت علت را انتخاب کنید.', 'سرپرستِ دارای مجوز عضویت می\u200cتواند داخلی واقعی را از فهرست به صف اضافه یا عضو پویا را حذف کند.', '«کارکرد روزانه و دلایل توقف» زمان فعال، توقف با هر علت و خروج از عضویت را با تاریخ انتخابی نشان می\u200cدهد.'],
  ['Open My profile & status to change your own membership; select a reason card when pausing.', 'A supervisor with membership permission can add a discovered extension or remove a dynamic member.', 'Open Daily activity & pause reasons to select a date and inspect on-duty, paused-by-reason and removed intervals.'],
  'زمان صف\u200cهای هم\u200cزمان با هم جمع نمی\u200cشود. تاریخچه فقط از آغاز ثبت مشاهدات است و قطعی شنودگر کارکرد محسوب نمی\u200cشود. برای خروج موقت عضو ثابت، از توقف استفاده کنید.',
  'Concurrent memberships are not summed as work hours. History starts when observation recording is enabled; collector gaps are not credited. Pause static members for temporary departures.'),
 'presence':guide('عضویت و وضعیت تلفنی داخلی‌ها را برای صف‌های مجاز ببینید.','Inspect telephony states and memberships within your authorized queues.',
  ['یک داخلی ممکن است عضو چند صف باشد.','توقف در یک صف لزوماً به معنی توقف در همهٔ صف‌ها نیست.','Wrap-up زمان آماده‌سازی پس از تماس است و با آفلاین بودن فرق دارد.'],
  ['An extension can belong to several queues.','A pause in one queue does not necessarily pause every membership.','Wrap-up is after-call preparation time, not an offline state.']),
 'pbx':guide('داخلی‌ها، ترانک‌ها و مجوزهای AMI را بدون تغییر PBX بررسی کنید.','Inspect extensions, trunks and AMI capabilities without changing the PBX.',
  ['داخلی‌ها از ترانک‌ها جدا هستند، حتی اگر نام ترانک عددی باشد.','آداپتور محلی هر ۳۰ ثانیه فهرست را به‌روزرسانی می‌کند.','Unavailable با Unknown فرق دارد؛ Unknown یعنی دادهٔ کافی نداریم.'],
  ['Extensions and trunks are separate even when a trunk name is numeric.','The local adapter refreshes inventory every 30 seconds.','Unavailable differs from Unknown: Unknown means insufficient observations.'],
  'RTT و افت بسته فقط با RTCP معتبر قابل نمایش‌اند؛ نبود داده را کیفیت خوب فرض نکنید. جیتر بدون نرخ ساعت کدک به میلی‌ثانیه تبدیل نمی‌شود.','RTT and loss need valid RTCP. Missing data does not imply good quality. Jitter requires the codec clock rate before conversion to milliseconds.'),
 'control':guide('کنترل تماس نیازمند داخلی اختصاصی سرپرست، مجوز صف و تماس زنده است.','Call control requires an assigned supervisor phone, queue grants and a current call.',
  ['شنود: سرپرست فقط صدای مکالمه را می‌شنود.','نجوا: صدای سرپرست باید فقط به کارشناس برسد؛ ورود به مکالمه برای گفت‌وگوی سه‌طرفه است.','پارک تماس را در جایگاه نگه می‌دارد؛ بازیابی آن را روی داخلی سرپرست می‌آورد.','Pickup برای تماسِ هنوز در حال زنگ‌خوردن است، نه مکالمهٔ پاسخ‌داده‌شده.'],
  ['Listen: the supervisor hears the conversation silently.','Whisper should be audible only to the agent; barge joins all participants.','Park holds a call in a slot; retrieve connects it to the supervisor phone.','Pickup is for a ringing call, not an answered conversation.'],
  'پذیرفته‌شدن درخواست AMI، تأیید کیفیت صوت نیست. وضعیت unknown را بدون بررسی تماس دوباره ارسال نکنید.','AMI acceptance does not verify audio quality. Do not blindly repeat a command whose outcome is unknown.'),
 'wallboard':guide('نمای کامل سرپرست با خلاصهٔ وضعیت داخل خود صفحهٔ تمام\u200cصفحه.',
  'A supervisor display whose status summary remains inside the fullscreen stage.',
  ['صف\u200cها را انتخاب و تمام\u200cصفحه را فعال کنید؛ خروج با دکمه یا Escape است.', 'خلاصه\u200cها، آماده/مشغول/زنگ\u200cخور/توقف، شماره صف، منتظرها و زمان انتظار را مقایسه کنید.', 'با مجوز شماره مشتری، نمای خصوصی را فعال کنید؛ شماره\u200cها در نمایشگر عمومی پنهان\u200cاند.', 'بیش از ۱۲ منتظر به صورت صفحه\u200cهای چرخان ۱۵ ثانیه\u200cای نمایش داده می\u200cشوند.'],
  ['Choose queues and enter fullscreen; use Exit or Escape to leave.', 'Compare totals, ready/talking/ringing/paused agents, queue identity, waiting callers and timers.', 'Enable private mode only when caller-details permission is available; public displays hide numbers.', 'More than 12 waiting callers rotate in pages every 15 seconds.'],
  'رنگ ثابت، هویت صف را نشان می\u200cدهد؛ قرمز همراه علامت هشدار نشان\u200cدهندهٔ عبور از قانون همان صف است. وضعیت قطع ارتباط جداگانه نمایش داده می\u200cشود.',
  'Stable colors identify queues; red plus a warning symbol identifies a queue-rule breach. Connection loss is shown separately.'),
 'alerts':guide('هشدارهای فعال و وضعیت ارسال پیام‌رسان‌ها را بررسی کنید.','Review current threshold alerts and notification delivery status.',
  ['برای تنظیم آستانه به قوانین صف بروید.','صدای مرورگر باید با کلیک کاربر فعال شود؛ محدودیت خود مرورگر است.','شمارندهٔ ارسال به معنی پذیرش توسط API پیام‌رسان است؛ گفت‌وگوی مقصد را نیز بررسی کنید.'],
  ['Configure thresholds in queue policies.','Browser audio needs a user gesture to enable sound.','Delivery counts mean provider API acceptance; verify the destination conversation too.']),
 'audit':guide('ردپای عملیات مدیریتی؛ این قسمت گزارش تاریخی عملکرد تماس نیست.','A supervisor action trail, separate from historical call performance reporting.',
  ['کاربر، صف، نوع عمل و نتیجه را کنار هم بررسی کنید.','فرمان pending هنوز نتیجهٔ نهایی ندارد.','برای فرمان unknown ابتدا وضعیت فعلی تماس را بررسی کنید.'],
  ['Review actor, queue, action and result together.','Pending commands have no final observed outcome yet.','For an unknown result, inspect the current call before retrying.']),
 'settings':guide('سلامت اتصال و پیام‌رسان‌ها از این بخش مدیریت می‌شوند.','Manage connection diagnostics and alert messaging here.',
  ['نصب مدیریت‌شده، اتصال Collector را روی سرور می‌سازد.','ربات تلگرام یا بله را در حساب مقصد شروع کنید.','توکن و شناسهٔ عددی مقصد را ذخیره و یک پیام آزمایشی ارسال کنید.','برای هشدار واقعی، ارسال هر صف را در قوانین صف فعال کنید.'],
  ['Managed installation provisions the collector on the server.','Start your Telegram or Bale bot from the destination account.','Save the token and numeric chat ID, then send a test notification.','Enable each queue in queue policies for actual alerts.'],
  'خالی‌گذاشتن توکن، توکن قبلی را حفظ می‌کند. توکن را در اسکرین‌شات، تیکت یا مخزن عمومی قرار ندهید.','A blank token keeps the previous secret. Do not include tokens in screenshots, tickets or public repositories.'),
 'users':guide('دسترسی از سه لایه تشکیل می‌شود: نقش، بخش‌های پنل، و مجوز صف/عملیات.','Access has three layers: role, panel sections, and queue/action grants.',
  ['مدیر: کاربران و تنظیمات؛ سرپرست: عملیات مجاز صف؛ کارشناس: توقف/ادامهٔ خودش؛ مشاهده‌گر: فقط مشاهده.','داخلی واقعی را انتخاب کنید؛ یک داخلی به دو حساب اختصاص داده نمی‌شود.','منوهای موردنیاز، صف‌ها و عملیات را تیک بزنید و یک‌بار ذخیره کنید.','رمز جدید هنگام ویرایش اختیاری است؛ حداقل ۱۲ نویسه لازم دارد.'],
  ['Admin manages users/settings; supervisors control granted queues; agents pause/resume themselves; viewers are read-only.','Choose the actual extension; one phone cannot belong to two accounts.','Select sections, queues and actions, then save once.','A new password is optional when editing and must contain at least 12 characters.']),
 'policies':guide('هشدارها، محدودیت ظرفیت، علت\u200cهای توقف و اجازه تماس بیرونی به تفکیک صف تنظیم می\u200cشوند.',
  'Configure alerts, staffing limits, pause reasons and outbound directory dialing independently per queue.',
  ['صف را از فهرست زنده انتخاب کنید؛ فرم زیر فقط متعلق به همان صف است.', 'شرط تعداد و شرط زمان را مستقل روشن یا خاموش کنید و در صورت نیاز ترکیب «یا/و» را انتخاب کنید.', 'هشدار کمبود نیروی آماده مستقل از ترکیب تعداد/زمان است.', 'محدودیت ظرفیت اختیاری است؛ فقط با فعال\u200cسازی آن، تعداد ثابت نیروها و سقف خروج اعمال می\u200cشود.', 'برای اضافه\u200cکردن علت توقف فقط عنوان را وارد کنید؛ شناسه فنی خودکار ساخته می\u200cشود.', 'ارسال تلگرام و بله را برای هر صف انتخاب کنید؛ اتصال ربات\u200cها در تنظیمات انجام می\u200cشود.'],
  ['Choose a queue from live inventory; the form applies only to that queue.', 'Enable count and wait-time conditions independently; combine them with OR or AND when needed.', 'The low-ready threshold operates independently of count/time matching.', 'Staffing limits are optional. Enable them and define a fixed roster before enforcing departure limits.', 'Add a pause-reason label; its technical identifier is generated automatically.', 'Select Telegram and Bale delivery for each queue; configure bot connections under Settings.'],
  'ذخیره هشدار صف، محدودیت ظرفیت را خودکار فعال نمی\u200cکند. تماس بیرونی از دفترچه پیش\u200cفرض خاموش است و به مجوز Dial کاربر و مسیر خروجی تلفنی نیاز دارد.',
  'Saving alert rules does not enable staffing restrictions. External directory dialing is off by default and requires a user Dial grant and a PBX outbound route.'),
 'shifts':guide('برنامهٔ حضور تیم؛ با ذخیرهٔ شیفت وضعیت تلفن خودکار تغییر نمی‌کند.','Plan team presence; saving a shift does not automatically change phone state.',
  ['صف، کارشناس و زمان شروع/پایان را مشخص کنید.','تداخل شیفت‌ها را قبل از ذخیره بررسی کنید.','توقف و عضویت واقعی از بخش کارشناسان و کنترل صف انجام می‌شوند.'],
  ['Choose queue, agent, start and end time.','Review overlaps before saving.','Use agent and queue controls to change actual pause or membership.']),
 'directory':guide('دفترچهٔ مشترک هر صف، مخاطب را در تماس منتظر شناسایی و امکان شروع تماس را فراهم می\u200cکند.',
  'A shared per-queue directory identifies waiting callers and supports permissioned callback dialing.',
  ['مخاطب را با صف، نام و شماره ثبت کنید؛ قالب شماره را با Caller ID ورودی یکسان بگذارید.', 'در تماس\u200cهای منتظر همان صف، نام ذخیره\u200cشده کنار شماره نمایش داده می\u200cشود؛ به\u200cروزرسانی نام تا ۱۵ ثانیه زمان می\u200cبرد.', 'دکمه تماس به مجوز Dial و داخلی اختصاصی حساب نیاز دارد؛ ابتدا تلفن شما زنگ می\u200cخورد و پس از پاسخ مقصد گرفته می\u200cشود.', 'داخلی\u200cها به\u200cصورت پیش\u200cفرض قابل تماس\u200cاند؛ مدیر می\u200cتواند تماس با مخاطبان بیرونی همان صف را در قوانین مجاز کند.'],
  ['Save the contact with a queue, name and phone; match the incoming Caller ID number format.', 'A matching caller in that queue displays the saved name; name updates may take up to 15 seconds.', 'Call requires a Dial grant and your assigned phone. Your phone rings first; answer it to dial the contact.', 'Internal destinations are allowed by default; an administrator can authorize outbound saved contacts per queue.'],
  'ثبت مخاطب به\u200cتنهایی هیچ تماسی برقرار نمی\u200cکند و نام مخاطب خارج از صف مجاز نمایش داده نمی\u200cشود. این دفترچه جای CRM کامل نیست.',
  'Saving a contact never starts a call. Names remain within the authorized queue. This directory is not a full CRM.'),
 'features':guide('وضعیت واقعی قابلیت‌ها و محدودیت‌های هر بخش.','Actual feature availability and implementation limits.',
  ['آماده یعنی قابلیت پیاده‌سازی شده؛ همچنان محیط شما باید پیش‌نیازهای آن را داشته باشد.','بتا نیازمند آزمون پذیرش در همان PBX است.','برنامهٔ توسعه به معنی قابلیت فعال و قابل استفاده نیست.'],
  ['Available means implemented; your environment must still meet prerequisites.','Beta features need acceptance testing on your PBX.','Planned means the feature is not available yet.']),
}


GUIDES['settings']['fa']['steps'].extend([
 'نام، عنوان و لوگوی سازمان را در هویت سازمان ذخیره کنید؛ صفحهٔ ورود نیز به‌روز می‌شود.',
 'برای آزمایش روی سرور واقعی، غیرفعال‌کردن مانیتورینگ دریافت AMI و کنترل این ماژول را متوقف می‌کند؛ تماس‌های PBX ادامه دارند.',
 'اگر پنل باز نیست: sudo sanequeuectl disable. برای بازگشت: sudo sanequeuectl enable. حذف سرویس‌ها با حفظ داده: sudo sanequeuectl uninstall --yes.'
])
GUIDES['settings']['en']['steps'].extend([
 'Save your organization name, subtitle and logo; the sign-in page uses the same identity.',
 'Disable monitoring to stop this module’s AMI reception and call controls while PBX calls continue.',
 'Panel unavailable: sudo sanequeuectl disable. Restore: sudo sanequeuectl enable. Remove services while retaining data: sudo sanequeuectl uninstall --yes.'
])

GUIDES['alerts']['fa']['steps'].append('برجسته‌سازی انتظار در نوار بالا فقط نمایش شخصی است؛ در نصب پایدار، هشدار صف و صدای آن از قوانین همان صف پیروی می‌کنند.')
GUIDES['alerts']['en']['steps'].append('The toolbar wait highlight is a personal display setting. In persistent mode, queue alarms and their sound follow server-side queue rules.')

GUIDES['telephony']=guide(
 'ماژول‌های مستقل انتظار داخلی، تماس برگشتی و اصلاح شماره؛ فقط مدیر دارای دسترسی این منو می‌تواند آن‌ها را تغییر دهد.',
 'Independent extension waiting, callback and caller-number formatting; restricted to administrators with this menu grant.',
 ['در ماژول‌های تلفنی، منوی داخلی مشغول و کلیدهای ۱/۲ موردنیاز را فعال کنید.', 'برای انتظار، سقف ثانیه و برای کال‌بک، اعتبار درخواست و فاصله بررسی آزاد بودن را تعیین و ذخیره کنید.', 'فایل منوی فارسی پیش‌فرض همراه نصب است. برای تغییر هر پیام، فایل صوتی حداکثر ۶۰ ثانیه و ۸ مگابایت آپلود و نتیجه را پخش کنید.', 'برای اصلاح شماره، کد کشور، پیش‌شماره و قواعد اپراتور را انتخاب کنید و چند شماره واقعی را پیش‌نمایش بگیرید.', 'بازخوانی کنید تا وضعیت اعمال موفق دیده شود؛ تغییر ساختار مسیر تماس در صورت وجود تماس فعال به زمان خلوت موکول می‌شود.'],
 ['Enable the busy-extension menu and required keys 1/2 in Telephone modules.', 'Set maximum wait, callback expiry and availability check interval; save.', 'The installer includes the default Persian menu. Upload a recording up to 60 seconds and 8 MB for each slot, then preview it.', 'Set country/national prefixes and optional provider rules. Preview representative real trunk numbers.', 'Refresh to verify successful application. Dialplan replacement is deferred while calls are active.'],
 'کال‌بک فقط بین داخلی‌های شناخته‌شده است؛ ابتدا درخواست‌کننده زنگ می‌خورد. پذیرش AMI به معنی پاسخ مقصد نیست. مسیرهای ناشناخته خودکار بازنویسی نمی‌شوند؛ خطای آداپتور را بررسی کنید.',
 'Callbacks are internal-only and ring the requester first. AMI acceptance does not prove destination answer. Unknown dialplans are refused instead of overwritten; check adapter status.')
GUIDES['settings']['fa']['steps'].extend(['در بخش پیام‌رسان‌ها، برای تلگرام و بله جداگانه زبان فارسی، انگلیسی یا هر دو را انتخاب کنید.','ربات را در پیام‌رسان ایجاد کنید؛ توکن را فقط در فرم پنل وارد کنید. به ربات Start بفرستید یا آن را عضو گروه مقصد کنید؛ سپس یافتن مقصد را بزنید، مقصد را انتخاب و ذخیره کنید.','اگر ربات وب‌هوک فعال دارد، یافتن مقصد آن را تغییر نمی‌دهد؛ شناسه عددی مقصد را دستی وارد کنید. آزمون اتصال را جداگانه برای هر پیام‌رسان بزنید.','قطع ترانک، قطع مانیتورینگ، قدیمی بودن سلامت و پرشدن دیسک در هشدارهای حساس تنظیم می‌شوند؛ هشدار هر صف در قوانین همان صف است.'])
GUIDES['settings']['en']['steps'].extend(['Choose Persian, English or both independently for Telegram and Bale.','Create the bot in the messenger and enter its token only in the panel. Send Start to the bot or add it to the destination group; discover, select and save the destination.','Discovery refuses active webhooks without changing them; enter the numeric destination ID manually. Test each provider separately.','Configure trunk failures, monitoring outages, stale inventory and disk thresholds under critical alerts. Queue thresholds remain per-queue policies.'])
GUIDES['live']['fa']['steps'].append('بازه شاخص‌ها را از بالای صفحه انتخاب کنید: تجمیعی PBX با زمان ریست نامعلوم، یا امروزِ تهران بر اساس تماس‌های ثبت‌شده از آغاز پوشش ماژول. بازخوانی صفحه ریست نمی‌کند.')
GUIDES['live']['en']['steps'].append('Select the KPI period: cumulative PBX counters with unknown reset time, or Tehran today from module-observed calls since recording coverage began. Refresh never resets counters.')
GUIDES['directory']['fa']['steps'].append('برای نام روی تلفن کارشناس، گزینه نمایش نام مخاطب در ماژول‌های تلفنی و آداپتور مسیر تماس باید فعال باشند؛ فقط نام همان صف اعمال می‌شود.')
GUIDES['directory']['en']['steps'].append('Agent-phone contact names require the Telephone modules directory option and a supported dial adapter; only the matching queue contact is used.')
GUIDES['alerts']['fa']['steps'].extend(['برای تعریف شرط: قوانین صف ← انتخاب صف ← هشدار تعداد، انتظار یا آمادگی؛ هر شرط مستقل فعال یا غیرفعال می‌شود.','رنگ صف و صدا در همین قوانین تنظیم می‌شوند؛ ارسال تلگرام/بله نیازمند فعال بودن پیام‌رسان هم در قانون و هم در تنظیمات سازمان است.'])
GUIDES['alerts']['en']['steps'].extend(['Define conditions in Queue policies: choose a queue and enable count, wait or staffing rules independently.','Queue color and sound follow these rules. Telegram/Bale delivery must be enabled in both the queue rule and organization messaging settings.'])

GUIDES['telephony']['fa']['steps'].append('گزارش کال‌بک در پایین همین صفحه است: ثبت درخواست، پاسخ درخواست‌کننده، اتصال واقعی مقصد و پایان جدا هستند. مدت فقط وقتی اتصال Bridge و پایان هر دو مشاهده شده باشند نمایش داده می‌شود؛ ردیف‌های قدیمی بدون شواهد، زمان ساختگی ندارند.')
GUIDES['telephony']['en']['steps'].append('The callback report appears below the settings. Request, requester answer, verified target bridge and end are separate. Duration requires observed bridge connection and end; older rows without evidence have no invented timestamps.')
GUIDES['surveys']=guide(
 'پاسخ کلیدی واقعی مشتری پس از مکالمه؛ مستقل از گزارش فعالیت هپی‌کال کارشناس.',
 'Actual customer DTMF responses after a call, separate from agent happy-call work logs.',
 ['مدیر فنی باید صوت واقعی، نقطهٔ اتصال و نسخهٔ دقیق فرم را تأیید کند؛ ثبت فرم مسیر تماس را خودکار نصب نمی‌کند.', 'مدیر فرم را با حداکثر پنج سؤال، کلیدها و شاخه‌های رو به جلو ثبت می‌کند؛ ستاره برای انصراف است.', 'سرپرست با مجوز منوی نظرسنجی و view/survey_reports هر صف، گزارش همان صف را می‌بیند.', 'CSAT از پاسخ‌های معتبر سؤال رضایت محاسبه می‌شود؛ تعداد دعوت ثبت‌شده، همهٔ تماس‌ها نیست.'],
 ['A technical operator approves real audio, an explicit hook and the exact form version; saving a form never installs a route.', 'Administrators define up to five questions, numeric keys and forward branches; star opts out.', 'Supervisors need the survey menu plus view/survey_reports grants for each queue.', 'CSAT counts valid answers to the satisfaction question; recorded invitations are not all calls.'],
 'شواهد ناقص، انتقال یا پایان توسط مشتری باعث حدس هویت یا شماره‌گیری تازه نمی‌شود. تست واقعی تلفن و بار هنوز لازم است.',
 'Missing evidence, transfers or caller-first hangup never cause guessed attribution or a new call. Real telephone and load acceptance remain required.')
