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
  'هر تماس می‌تواند چند کانال SIP/PJSIP/Local داشته باشد؛ تعداد کانال با تعداد مکالمه یکی نیست.','One call can contain multiple SIP/PJSIP/Local channel legs; channel counts are not conversation counts.'),
 'waiting':guide('تماس‌های منتظر با جایگاه و مدت انتظار نمایش داده می‌شوند.','Waiting callers are listed with queue position and elapsed wait.',
  ['برای دیدن شمارهٔ کامل باید مجوز نمایش شماره داشته باشید.','افزایش اولویت ترتیب صف را تغییر می‌دهد؛ ظرفیت پاسخ‌گویی را بیشتر نمی‌کند.','قطع تماس فقط بعد از بررسی تماس انتخاب‌شده انجام شود.'],
  ['Full caller numbers require a separate caller-details permission.','Priority changes queue ordering; it does not add answering capacity.','Review the selected caller before hanging up.']),
 'agents':guide('آماده، زنگ‌خور، در مکالمه، توقف و پس از تماس از هم جدا هستند.','Ready, ringing, talking, paused and wrap-up states are distinct.',
  ['علت توقف را انتخاب و سپس توقف را ثبت کنید.','برای بازگشت به پاسخ‌گویی، ادامه را بزنید.','کارشناس فقط وضعیت خودش را تغییر می‌دهد؛ سرپرست به مجوز صف و عملیات نیاز دارد.'],
  ['Choose a pause reason before pausing.','Resume when ready to receive calls again.','Agents can change only their own status; supervisors need queue and action grants.'],
  'شناسهٔ Local عضویت صف است؛ آن را با داخلی واقعی SIP یا PJSIP اشتباه نگیرید.','A Local interface is a queue membership path, not necessarily the actual SIP/PJSIP device.'),
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
 'wallboard':guide('نمای مناسب مانیتور بزرگ برای سرپرست و مدیر.','A large-screen view for supervisors and managers.',
  ['صف‌های موردنظر را انتخاب کنید و نمای تمام‌صفحه را بزنید.','با Escape از تمام‌صفحه خارج شوید.','در نمایش عمومی شماره‌ها پوشیده‌اند؛ شمارهٔ کامل فقط با مجوز و انتخاب نمای خصوصی سرپرست نمایش داده می‌شود.'],
  ['Choose queues and enter fullscreen.','Press Escape to exit fullscreen.','Public display masks caller numbers; private supervisor detail requires permission and explicit selection.']),
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
 'policies':guide('قواعد هر صف مستقل از صف‌های دیگر است.','Each queue has its own independent rules.',
  ['مثال: برای شلوغی صف، آستانهٔ تعداد را روی ۵ تنظیم کنید.','برای انتظار طولانی، ۵ دقیقه را به صورت ۳۰۰ ثانیه وارد کنید.','تلگرام و بله را مستقل انتخاب کنید؛ فاصلهٔ ارسال، تکرار هشدار فعال را محدود می‌کند.','سقف خروج کارشناس به برنامهٔ نفرات و حداقل افراد حاضر وابسته است.'],
  ['Example: set a waiting-count threshold of 5 for a crowded queue.','Enter 300 seconds for a five-minute wait threshold.','Select Telegram and Bale independently; cooldown limits repeated active alerts.','Agent departure limits depend on configured roster and minimum on-duty staff.']),
 'shifts':guide('برنامهٔ حضور تیم؛ با ذخیرهٔ شیفت وضعیت تلفن خودکار تغییر نمی‌کند.','Plan team presence; saving a shift does not automatically change phone state.',
  ['صف، کارشناس و زمان شروع/پایان را مشخص کنید.','تداخل شیفت‌ها را قبل از ذخیره بررسی کنید.','توقف و عضویت واقعی از بخش کارشناسان و کنترل صف انجام می‌شوند.'],
  ['Choose queue, agent, start and end time.','Review overlaps before saving.','Use agent and queue controls to change actual pause or membership.']),
 'directory':guide('دفترچهٔ مشترک مخاطبانِ مرتبط با صف‌های مجاز؛ برای ثبت نام، شماره و یادداشت کاری.','A shared directory scoped to authorized queues, storing contact names, numbers and work notes.',
  ['صف مربوط به مخاطب را مشخص کنید تا دسترسی همان صف رعایت شود.','نام و شماره را برای جست‌وجو و شناخت مخاطب ثبت کنید.','این دفترچه خودش تماس ایجاد نمی‌کند و جای CDR یا CRM کامل نیست.'],
  ['Assign the contact to a queue so its access scope applies.','Record a name and number for lookup and recognition.','The directory does not automatically place calls and is not a full CRM or CDR system.']),
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
