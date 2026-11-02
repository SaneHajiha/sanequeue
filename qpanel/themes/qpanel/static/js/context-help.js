/* Local help only. No network requests, PBX actions or background polling. */
'use strict';
(() => {
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b;
 const entries={
  live_danger:[t('تماس رهاشده در صف','Abandoned queue calls'),t('تماس‌گیرنده وارد صف شده و پیش از پاسخ کارشناس، تماس را قطع کرده است.','The caller entered a queue and hung up before an agent answered.'),t('در حالت «امروز»، فقط رخدادهای ثبت‌شدهٔ امروز پنل شمارش می‌شوند. در حالت تجمیعی، عدد از شمارندهٔ صف مرکز تلفن می‌آید؛ زمان آخرین ریست آن مشخص نیست.','Today uses the panel’s observed daily events. Cumulative mode uses the PBX queue counter; its reset time is unknown.'),t('مثال: مشتری ۲۰ ثانیه منتظر می‌ماند و قطع می‌کند؛ یک رهاشدن برای آن صف ثبت می‌شود.','Example: a caller waits 20 seconds and hangs up: one abandonment for that queue.'),t('این عدد، تعداد زنگ‌های بی‌پاسخ هر کارشناس یا همهٔ تماس‌های از دست‌رفتهٔ مرکز نیست. یک مکالمه می‌تواند بیش از یک بار وارد صف شود.','This is not an agent’s unanswered ringing attempts or every missed call in the PBX. One conversation can visit queues more than once.')],
  live_warning:[t('تماس منتظر','Waiting calls'),t('تماس‌هایی که همین حالا در صف هستند و هنوز به کارشناس وصل نشده‌اند.','Calls currently waiting in the queue, not yet connected to an agent.'),t('این عدد لحظه‌ای است؛ فیلتر صف روی مجموع نمایش‌داده‌شده اثر می‌گذارد.','This is a live count; the queue filter affects the displayed total.')],
  live_active:[t('عضویت‌های درگیر تماس','Busy memberships'),t('اعضای صف در مکالمه، در حال زنگ‌خوردن یا وضعیت مشغول.','Queue memberships talking, ringing or busy.'),t('یک کارشناسِ عضو چند صف ممکن است در چند عضویت شمرده شود؛ این عدد، تعداد مکالمهٔ یکتا نیست.','An agent in multiple queues can count in multiple memberships; this is not a unique-call count.')],
  live_ready:[t('کارشناس آماده','Ready membership'),t('عضو صف که متوقف نیست و وضعیت دستگاهش آماده گزارش شده است.','A queue member who is not paused and whose device is reported ready.'),t('صورت: عضویت‌های آماده؛ مخرج: کل عضویت‌های صف‌های انتخابی. عضویت‌ها را با تعداد افراد یکتا اشتباه نگیرید.','Numerator: ready memberships. Denominator: all memberships in selected queues; memberships are not unique people.')],
  live_wait:[t('میانگین انتظار','Average waiting time'),t('میانگین مدت انتظار ثبت‌شده؛ زمان انتظارِ بیشترین تماس فعلی نیست.','The mean recorded waiting time, not the longest current wait.'),t('در حالت امروز از زمان‌های ثبت‌شدهٔ تماس‌های پاسخ‌داده محاسبه می‌شود. در حالت تجمیعی، مقدار گزارش‌شدهٔ مرکز تلفن است و ممکن است با تأخیر به‌روز شود.','Today uses recorded waits for answered calls. Cumulative mode uses the PBX-reported value, which can lag.'),t('مثال: انتظار ۱۰ و ۳۰ ثانیه برای دو تماس، میانگین ۲۰ ثانیه می‌دهد. خط تیره یعنی مقدار معتبر موجود نیست.','Example: waits of 10 and 30 seconds average 20 seconds. A dash means no valid value.')],
  live_sla:[t('سطح خدمت زنده (SL)','Live service level (SL)'),t('درصد پاسخ‌گویی در آستانهٔ زمانی تعیین‌شده؛ برای مقایسه، تعریف و بازه را یکسان انتخاب کنید.','The percentage answered within the configured time target; compare only matching definitions and periods.'),t('حالت امروز: پاسخ‌های داخل آستانه ÷ مجموع پاسخ‌داده و رهاشدهٔ ثبت‌شده. حالت تجمیعی: شاخص ارسالی مرکز تلفن. تعریف گزارش تاریخی جداست.','Today: answers within target / observed answered plus abandoned calls. Cumulative mode: the PBX value. Historical reporting has a separate definition.')],
  visits:[t('مراجعه به صف','Queue visits'),t('هر ورود به یک صف، یک مراجعه است؛ الزاماً یک تماس یا مشتری یکتا نیست.','Each entry into a queue is one visit, not necessarily one unique call or customer.'),t('بازهٔ گزارش بر اساس زمان ورود به صف و منطقهٔ زمانی تهران انتخاب می‌شود.','The report range uses queue-entry time in the Tehran timezone.'),t('مثال: یک تماس از صف فروش به پشتیبانی می‌رود؛ دو مراجعه و یک مکالمه دارد.','Example: one call visits sales then support: two visits, one conversation.')],
  answered:[t('مراجعهٔ پاسخ‌داده','Answered visits'),t('مراجعه‌ای که برای آن شواهد پاسخ ثبت شده است؛ انتقال پس از پاسخ، پاسخ قبلی را حذف نمی‌کند.','A visit with recorded answer evidence; a later transfer does not remove that answer.'),t('زمان ورود به صف، مبنای قرارگرفتن در بازه است؛ نه زمان پایان تماس.','Queue-entry time determines the selected period, not call end time.')],
  abandoned:[t('رهاشده در گزارش','Abandoned visits'),t('خروج با قطع تماس‌گیرنده پیش از پاسخ، بر اساس رخداد ثبت‌شدهٔ صف.','The caller hung up before answer, according to recorded queue evidence.'),t('خروج با کلید، پایان مهلت و خروج به‌علت صف خالی نتیجه‌های جداگانه‌اند و خودکار رهاشده محسوب نمی‌شوند.','Key exits, timeouts and empty-queue exits are distinct outcomes; they are not automatically classified as abandonment.'),t('بی‌پاسخ ماندن یک بار زنگ کارشناس، اگر مشتری هنوز در صف بماند یا بعداً پاسخ بگیرد، رهاشدن مشتری نیست.','An unanswered agent ringing attempt is not abandonment if the caller stays in queue or is answered later.')],
  incomplete:[t('پوشش ناقص','Incomplete evidence'),t('بخشی از شواهد شروع یا پایان مراجعه موجود نیست؛ این وضعیت به معنی تماس ناموفق نیست.','Some entry or end evidence is missing; this does not itself mean a failed call.'),t('ممکن است ثبت دیر شروع شده، منبع قطع بوده یا داده هنوز کامل نشده باشد. مقدار نامشخص صفر فرض نمی‌شود.','Observation may have started late, a source may have disconnected, or evidence may still be incomplete. Unknown values are not assumed to be zero.')],
  report_sla:[t('سطح خدمت گزارش','Historical service level'),t('پاسخ‌های حداکثر ۲۰ ثانیه ÷ پاسخ‌هایی که زمان انتظارشان مشخص است، ضربدر ۱۰۰.','Answers within 20 seconds / answered visits with a known wait, multiplied by 100.'),t('تماس رهاشده در مخرج این گزارش نیست؛ به همین دلیل با شاخص زندهٔ امروز الزاماً برابر نیست.','Abandoned visits are not in this report’s denominator; it need not match today’s live SL.'),t('مثال: ۸ پاسخ از ۱۰ پاسخِ دارای انتظار مشخص، داخل ۲۰ ثانیه بوده‌اند؛ SL برابر ۸۰٪ است.','Example: 8 of 10 answers with known waits met 20 seconds: SL is 80%.')],
  report_wait:[t('میانگین انتظار گزارش','Report average wait'),t('میانگین زمان‌های انتظارِ معلوم در مراجعه‌های همین بازه.','The mean of known waiting durations in visits within this range.'),t('فقط مقادیر ثبت‌شده میانگین‌گیری می‌شوند؛ انتظار تماس رهاشده هم اگر معلوم باشد در این میانگین می‌آید. این شاخص با میانگین زندهٔ پاسخ‌ها تعریف یکسانی ندارد.','Only known values are averaged; abandoned waits are included when known. This differs from the live answered-call average.')],
  talk:[t('مدت مکالمهٔ بخش صف','Queue-segment talk time'),t('زمان مکالمهٔ ثبت‌شده برای بخش مربوط به همان صف؛ زمان مشورت یا ادامهٔ تماس پس از انتقال الزاماً داخل آن نیست.','Recorded talk time for that queue segment; consultation or post-transfer time is not necessarily included.'),t('میانگین فقط از مقادیر معلوم محاسبه می‌شود. این مقدار AHT کامل شامل کار پس از تماس نیست.','The average uses known values only. This is not full AHT including after-call work.')],
  hangup:[t('قطع‌کنندهٔ بخش صف','Queue-segment hangup party'),t('طرفی که طبق شواهد صف، بخش مربوط به همان صف را پایان داده است.','The party that ended this queue segment according to queue evidence.'),t('پس از انتقال، این برچسب لزوماً قطع‌کنندهٔ نهایی کل مکالمه نیست. خط تیره یعنی مدرک کافی نداریم.','After transfer, this is not necessarily the final conversation hangup party. A dash means insufficient evidence.')],
  duty:[t('کارکرد و توقف','Duty and pauses'),t('کارکرد یکتا، اجتماع بازه‌های مشاهده‌شدهٔ کارشناس در صف‌های مجاز است؛ زمان هم‌زمان صف‌ها دوبار جمع نمی‌شود.','Unique duty is the union of observed agent intervals across authorized queues; concurrent queue time is not counted twice.'),t('مدت عضویت و توقف هر صف جداست. فاصلهٔ قطع مانیتورینگ، کارکرد محسوب نمی‌شود.','Membership and pause durations remain queue-specific; monitoring gaps do not count as work.')],
  pause_calls:[t('تماس حین توقف','Calls during pauses'),t('بخش CDR که شروع آن داخل بازهٔ توقف ثبت‌شدهٔ کارشناس بوده است.','A CDR segment starting inside an observed agent-pause interval.'),t('داخلی و بیرونی از فیلتر جدا انتخاب می‌شوند. مدت مکالمه، کل بخش است و ممکن است از پایان توقف عبور کند؛ هر ردیف الزاماً یک مکالمهٔ یکتا نیست.','Internal and external calls use separate filters. Talk time covers the whole segment and may extend past pause end; one row is not necessarily a unique conversation.')],
  export:[t('خروجی گزارش','Report export'),t('دریافت گزارش با بازه و فیلترهای فعلی و دسترسی همین حساب.','Download the report using the current dates, filters and account permissions.'),t('Excel و CSV فوری تا ۲۰۰ مراجعهٔ صف دارند. اگر نتیجه بزرگ‌تر باشد، بازه یا صف را محدود کنید. دریافت گزارش با دانلود فایل صوتی دو مجوز جدا هستند.','Immediate Excel/CSV exports support up to 200 queue visits; narrow the dates or queue for larger results. Report export and audio download are separate permissions.')],
  spy:[t('شنود','Listen'),t('تلفن اختصاصی سرپرست زنگ می‌خورد؛ پس از پاسخ، مکالمهٔ انتخابی را می‌شنود.','The supervisor’s assigned phone rings; answering monitors the selected call.'),t('در این حالت سرپرست نباید صدایی به طرفین ارسال کند. تماس زنده، داخلی اختصاصی و مجوز شنود لازم است.','This mode does not send supervisor speech to the parties. A live call, assigned extension and monitoring permission are required.')],
  whisper:[t('نجوا','Whisper'),t('سرپرست مکالمه را می‌شنود و راهنمایی او فقط برای کارشناس است.','The supervisor listens and coaches the agent without the caller hearing the supervisor.'),t('نیازمند تلفن سرپرست، مجوز شنود و مسیر تلفنی سازگار است. پیش از استفاده، نتیجهٔ صوت را در محیط خود آزمایش کنید.','Requires a supervisor phone, monitoring permission and a compatible telephony path. Verify audio behavior in your own environment.')],
  barge:[t('ورود به مکالمه','Barge in'),t('سرپرست وارد مکالمهٔ فعال می‌شود و می‌تواند با طرفین صحبت کند.','The supervisor joins the active call and can speak to the parties.'),t('با شنود و نجوا فرق دارد؛ طرفین می‌توانند صدای سرپرست را بشنوند.','Unlike listen or whisper, both parties can hear the supervisor.')],
  pause:[t('توقف و ادامهٔ کارشناس','Pause and resume'),t('توقف، دریافت تماس‌های جدید همین عضویت صف را موقتاً متوقف می‌کند؛ علت آن ثبت می‌شود.','Pausing temporarily stops new inbound calls for this queue membership and records a reason.'),t('تماس فعلی قطع نمی‌شود و عضویت صف‌های دیگر مستقل است. ادامه، این توقف را برمی‌دارد؛ آماده‌بودن دستگاه هم لازم است.','It does not hang up the current call. Other queue memberships are independent. Resume removes the pause; the device must also be available.')],
  membership:[t('عضویت صف','Queue membership'),t('افزودن یا حذف عضویت پویا برای داخلی شناسایی‌شده در صف انتخابی.','Add or remove a dynamic membership for a discovered extension in the selected queue.'),t('مجوز عضویت لازم است. اعضای ثابت و سیاست حداقل نیروی آماده ممکن است اجازهٔ این عملیات را ندهند.','Requires membership permission; static members or minimum-ready staffing rules can prevent the action.')],
  transfer:[t('انتقال مستقیم','Blind transfer'),t('تماس انتخابی بدون گفت‌وگوی مشورتی قبلی به داخلی مقصد هدایت می‌شود.','Redirect the selected call to a destination extension without a consultation first.'),t('سمت انتخابی تماس و مقصد را در پیام تأیید بررسی کنید.','Check the selected call leg and destination in the confirmation.')],
  attended_transfer:[t('انتقال با مشورت','Attended transfer'),t('ابتدا با مقصد مشورت می‌شود و سپس انتقال تکمیل می‌شود.','Consult the destination first, then complete the transfer.'),t('با پاسخ مقصد، فقط تلفن انتقال‌دهنده را طبق جریان تأییدشده قطع کنید؛ تماس‌گیرنده و مقصد باید متصل بمانند. مسیر انتقال به پشتیبانی مرکز تلفن وابسته است.','After the destination answers, hang up only the transferring phone according to the validated flow; caller and destination remain connected. Support depends on the PBX path.')],
  park:[t('پارک تماس','Park call'),t('طرف مقابلِ مبدأ انتخاب‌شده در محل پارک قرار می‌گیرد تا بازیابی شود.','Park the other party of the selected initiator so the call can be retrieved.'),t('مثال: برای پارک مشتریِ متصل به ۱۰۰، مبدأ کارشناس ۱۰۰ را انتخاب کنید. پس از پایان مهلت، برگشت به مبدأ تابع تنظیمات مرکز تلفن است.','Example: to park the customer connected to 100, select agent 100 as initiator. Timeout return depends on PBX settings.')],
  retrieve:[t('بازیابی تماس پارک‌شده','Retrieve parked call'),t('تلفن اختصاصی حساب شما زنگ می‌خورد و پس از پاسخ، به تماس پارک‌شده متصل می‌شود.','Your account’s assigned phone rings; answering connects it to the parked call.'),t('محل پارک باید هنوز معتبر باشد و مجوز پارک داشته باشید.','The parking slot must still be valid and parking permission is required.')],
  pickup:[t('برداشتن تماس','Pickup'),t('تماسی که هنوز روی داخلی دیگری زنگ می‌خورد، از تلفن مجاز برداشته می‌شود.','Answer a call that is still ringing on another extension from an authorized phone.'),t('برای تماس پاسخ‌داده‌شده نیست. وضعیت زنگ و مقصد را پیش از تأیید بررسی کنید.','This is not for an already answered call. Check ringing state and destination before confirming.')],
  hangup_action:[t('قطع تماس','Hang up'),t('سمت انتخاب‌شدهٔ تماس قطع می‌شود؛ ممکن است مکالمهٔ مرتبط نیز پایان یابد.','Disconnect the selected call leg; the related conversation may end as a result.'),t('این یک راهنماست و دستوری ارسال نمی‌کند. برای اجرای واقعی، تماس و پیام تأیید عملیات را جدا بررسی کنید.','Reading this help sends no command. To act, separately check the target call and action confirmation.')],
  priority:[t('اولویت تماس منتظر','Waiting-call priority'),t('اولویت یا جایگاه درخواست‌شدهٔ تماس منتظر در همان صف را تغییر می‌دهد.','Change the requested priority or position of a waiting call in that queue.'),t('معادل پاسخ فوری نیست و توزیع تماس همچنان تابع تنظیمات صف و کارشناس آماده است.','This does not answer the call immediately; queue strategy and available agents still govern delivery.')],
  dial:[t('تماس از پنل','Dial from panel'),t('ابتدا تلفن اختصاصی شما زنگ می‌خورد؛ پس از پاسخ، مقصد شماره‌گیری می‌شود.','Your assigned phone rings first; answering dials the destination.'),t('تماس بیرونی به مجوز Dial، اجازهٔ تماس بیرونیِ صف و مسیر خروجی مرکز تلفن نیاز دارد. ذخیرهٔ شماره در دفترچه به‌تنهایی مجوز تماس نمی‌دهد.','External calls require Dial permission, the queue’s external-directory policy and an outbound route. Saving a contact alone does not grant permission.')],
  actions:[t('راهنمای عملیات سرپرست','Supervisor action guide'),t('شنود: فقط شنیدن. نجوا: صحبت فقط با کارشناس. ورود: صحبت با طرفین.','Listen: monitoring only. Whisper: coach the agent. Barge: speak to both parties.'),t('توقف: نپذیرفتن تماس جدید در یک صف. انتقال مستقیم: هدایت به مقصد. انتقال با مشورت: گفت‌وگو با مقصد پیش از انتقال. پارک: نگهداری طرف مقابل در محل پارک.','Pause: stop new calls for one membership. Blind transfer: redirect to destination. Attended transfer: consult before handoff. Park: hold the other party in a parking slot.'),t('با مکث ماوس یا فوکوس روی دکمه، معنی همان دکمه را می‌بینید. روی دکمهٔ فوکوس‌شده F1 را بزنید تا راهنمایش باز بماند. خواندن راهنما هیچ تماس یا تغییری ایجاد نمی‌کند.','Hover or focus an action for its meaning; press F1 on the focused button to keep its guide open. Reading help never places a call or changes telephony state.')]
 };
 entries.penalty=[t('وزن کارشناس در صف','Queue member penalty'),
  t('مقدار penalty همین عضویت صف را تغییر می‌دهد؛ افزودن یا حذف عضو نیست.','Change this queue membership’s penalty; this does not add or remove a member.'),
  t('اثر آن بر ترتیب توزیع تماس به استراتژی و قواعد صف بستگی دارد. عدد فعلی و سیاست صف را پیش از تأیید بررسی کنید.','Its effect on call distribution depends on queue strategy and rules. Check the current value and queue policy before confirming.')];
 for(const key of ['spy','whisper','barge'])entries[key+'_shortcut']=[entries[key][0],
  t('این میانبر صفحهٔ تماس‌ها را باز می‌کند؛ اجرای عملیات نیازمند انتخاب تماس و تأیید جداگانه است.','This shortcut opens the calls view; executing the operation requires selecting a call and a separate confirmation.'),...entries[key].slice(1)];
 const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function definition(key){
  const entry=entries[key];
  if(key==='live_danger'&&document.getElementById('kpi-period')?.value==='pbx')return [entry[0],
   t('عدد ارسالیِ شمارندهٔ رهاشدهٔ صف در مرکز تلفن است؛ طبقه‌بندی آن را با گزارش رخدادهای پنل یکی فرض نکنید.','This is the PBX queue’s reported abandoned counter; do not assume its classification matches the panel’s event-based reports.'),
   entry[2],t('زمان شروع یا آخرین بازنشانی این شمارنده مشخص نیست. برای یک بازهٔ تاریخی مشخص، گزارش‌ها را باز کنید.','The counter’s start/reset time is unknown. For a specific historical period, use Reports.'),entry[4]];
  return entry;
 }
 const button=key=>entries[key]?`<button type="button" class="sq-help-trigger" data-context-help="${key}" aria-label="${esc(t('راهنمای: ','Help: ')+entries[key][0])}" aria-expanded="false" aria-controls="sq-inline-help">${fa?'؟':'?'}</button>`:'';
 const panel=document.createElement('aside');panel.id='sq-inline-help';panel.className='sq-help-popover';panel.hidden=true;
 panel.innerHTML='<div class="sq-help-heading"><h2 id="sq-help-title"></h2><button type="button" class="sq-help-close"></button></div><div class="sq-help-body"></div>';
 const close=panel.querySelector('button');close.textContent='×';close.setAttribute('aria-label',t('بستن راهنما','Close help'));
 const title=panel.querySelector('h2'),body=panel.querySelector('.sq-help-body');
 document.body.append(panel);
 const headings={'.action-overview .panel-heading':'actions','#control-view .panel-heading':'actions',
  '#history-activity-section .panel-heading':'duty','#history-intervals-section .panel-heading':'duty',
  '#history-outbound-section .panel-heading':'pause_calls','#directory-view .panel-heading':'dial'};
 for(const [selector,key] of Object.entries(headings))document.querySelector(selector)?.insertAdjacentHTML('beforeend',
  `<span class="sq-help-heading-guide">${t('راهنما','Help')}${button(key)}</span>`);
 let anchor=null,current='',pinned=false,timer,suppressFocus=false,originalDescription=null,originScope='',originData={};
 const actions={spy:'spy',whisper:'whisper',barge:'barge',pause:'pause',add:'membership',remove:'membership',penalty:'penalty',transfer:'transfer',attended_transfer:'attended_transfer',park:'park',retrieve:'retrieve',pickup:'pickup',hangup:'hangup_action',hangup_active:'hangup_action',first:'priority',priority:'priority',dial:'dial'};
 function target(node){
  if(!(node instanceof Element))return null;
  const element=node.closest('[data-context-help],[data-help-key],[data-action],.pause-agent,#history-excel,#history-export');
  if(!element)return null;
  const key=element.dataset.contextHelp||element.dataset.helpKey||actions[element.dataset.action]||(element.matches('.pause-agent')?'pause':element.matches('#history-excel,#history-export')?'export':'');
  return entries[key]?{element,key}:null;
 }
 function position(){
  if(!anchor?.isConnected){hide();return;}
  const rect=anchor.getBoundingClientRect(),width=Math.min(368,innerWidth-24);
  panel.style.width=width+'px';panel.style.maxHeight=Math.max(120,innerHeight-24)+'px';
  const height=panel.getBoundingClientRect().height;
  const top=rect.bottom+10+height<=innerHeight-12?rect.bottom+10:Math.max(12,rect.top-height-10);
  panel.style.top=top+'px';panel.style.left=Math.max(12,Math.min(innerWidth-width-12,fa?rect.right-width:rect.left))+'px';
 }
 function hide(returnFocus=false){
  clearTimeout(timer);const previous=anchor;
  if(previous?.isConnected){if(originalDescription===null)previous.removeAttribute('aria-describedby');else previous.setAttribute('aria-describedby',originalDescription);if(previous.dataset.contextHelp)previous.setAttribute('aria-expanded','false');}
  panel.hidden=true;pinned=false;anchor=null;current='';
  if(returnFocus&&previous?.isConnected){suppressFocus=true;previous.focus({preventScroll:true});queueMicrotask(()=>{suppressFocus=false;});}
 }
 function show(element,key,pin=false){
  if(!pin&&pinned)return;
  clearTimeout(timer);
  if(anchor!==element){hide();originalDescription=element.getAttribute('aria-describedby');originScope=element.closest('.view')?.id||'';originData={...element.dataset};}
  anchor=element;current=key;pinned=pin;
  const parent=element.closest('dialog[open]')||document.fullscreenElement||document.body;
  if(panel.parentNode!==parent)parent.append(panel);
  const entry=definition(key);title.textContent=entry[0];
  const descriptions=pin?entry.slice(1):entry.slice(1,2);
  body.replaceChildren(...descriptions.map(text=>{const p=document.createElement('p');p.textContent=text;return p;}));
  if(!pin){const note=document.createElement('small');note.textContent=element.dataset.contextHelp?t('برای توضیح کامل کلیک کنید.','Click for the full explanation.'):t('F1: راهنمای کامل؛ بدون اجرای عملیات','F1: full help, without executing the action');body.append(note);}
  panel.setAttribute('role',pin?'dialog':'tooltip');panel.setAttribute('aria-labelledby','sq-help-title');
  close.hidden=!pin;panel.hidden=false;
  if(element.dataset.contextHelp)element.setAttribute('aria-expanded',String(pin));
  if(!pin)element.setAttribute('aria-describedby',[originalDescription,panel.id].filter(Boolean).join(' '));else if(originalDescription===null)element.removeAttribute('aria-describedby');else element.setAttribute('aria-describedby',originalDescription);
  position();if(pin)close.focus({preventScroll:true});
 }
 function scheduleHide(){clearTimeout(timer);timer=setTimeout(()=>{if(!pinned&&!panel.matches(':hover')&&!anchor?.matches(':hover')&&document.activeElement!==anchor&&!panel.contains(document.activeElement))hide();},160);}
 document.addEventListener('pointerover',event=>{if(event.pointerType==='touch')return;const found=target(event.target);if(found&&!pinned&&anchor!==found.element)show(found.element,found.key);});
 document.addEventListener('pointerout',event=>{if(anchor?.contains(event.target))scheduleHide();});
 panel.addEventListener('pointerenter',()=>clearTimeout(timer));panel.addEventListener('pointerleave',scheduleHide);
 document.addEventListener('focusin',event=>{if(suppressFocus||panel.contains(event.target))return;const found=target(event.target);if(found&&!pinned)show(found.element,found.key);});
 document.addEventListener('focusout',scheduleHide);
 document.addEventListener('click',event=>{
  const trigger=event.target.closest('[data-context-help]');
  if(trigger&&entries[trigger.dataset.contextHelp]){event.preventDefault();event.stopPropagation();if(pinned&&anchor===trigger)hide();else show(trigger,trigger.dataset.contextHelp,true);return;}
  if(!panel.contains(event.target))hide();
 });
 close.addEventListener('click',()=>hide(true));
 document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!panel.hidden){event.preventDefault();event.stopImmediatePropagation();hide(pinned);}
  if(event.key==='F1'){const found=target(event.target);if(found){event.preventDefault();show(found.element,found.key,true);}}
 });
 window.addEventListener('resize',()=>{if(!panel.hidden)position();});
 document.addEventListener('scroll',()=>{if(!panel.hidden)position();},true);
 new MutationObserver(()=>hide()).observe(document.body,{attributes:true,attributeFilter:['data-view']});
 window.SaneQueueHelp={button,refresh(){
  if(panel.hidden)return;
  if(!anchor?.isConnected&&current){
   const scope=(originScope&&document.getElementById(originScope))||document.body;
   const replacement=[...scope.querySelectorAll('button')].find(item=>Object.entries(originData).every(([key,value])=>item.dataset[key]===value));
   if(replacement){anchor=replacement;if(anchor.dataset.contextHelp)anchor.setAttribute('aria-expanded',String(pinned));}
  }
  if(anchor?.isConnected)position();else hide();
 }};
})();
