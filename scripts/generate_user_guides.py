"""Generate both manuals from the same content rendered by contextual UI help."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qpanel.user_help import GUIDES

TITLES={'telephony':('ماژول‌های تلفنی','Telephone modules'),
 'live':('مرکز عملیات','Overview'),'queues':('صف‌ها','Queues'),'calls':('تماس‌های جاری','Active calls'),
 'waiting':('تماس‌های منتظر','Waiting calls'),'agents':('کارشناسان','Agents'),'presence':('داخلی‌ها و حضور','Presence'),
 'pbx':('سلامت PBX و ترانک‌ها','PBX and trunk health'),'control':('کنترل تماس سرپرست','Supervisor call control'),
 'wallboard':('دیوار نمایش','Wallboard'),'alerts':('هشدارها','Alerts'),'audit':('ثبت عملیات','Audit trail'),
 'settings':('تنظیمات و پیام‌رسان‌ها','Settings and messaging'),'users':('کاربران و دسترسی‌ها','Users and permissions'),
 'policies':('قوانین صف','Queue policies'),'shifts':('برنامه شیفت','Shift planning'),
 'directory':('دفترچه تلفن','Contact directory'),'features':('قابلیت‌ها و محدودیت‌ها','Capabilities and limits')}


def main():
    root=Path(__file__).resolve().parents[1]
    for language,index in (('fa',0),('en',1)):
        title='راهنمای کاربردی SaneQueue' if language=='fa' else 'SaneQueue user guide'
        note='این راهنما با راهنمای داخل پنل از یک منبع ساخته می‌شود. اسکرین‌شات‌ها نمونهٔ رابط‌اند؛ آمار محیط شما متفاوت است.' if language=='fa' else 'This manual and in-panel help share one source. Screenshots illustrate the interface; your live values will differ.'
        lines=['# '+title,'',note,'',('![راهنمای داخل پنل](images/help-fa-beta22.png)' if language=='fa' else '![In-panel help](images/help-en-dark-beta22.png)'),'', '## '+('فهرست بخش‌ها' if language=='fa' else 'Sections'),'']
        lines.extend('- ['+TITLES[key][index]+'](#'+key+')' for key in GUIDES)
        for key,translations in GUIDES.items():
            text=translations[language]
            lines.extend(['',f'<a id="{key}"></a>','', '## '+TITLES[key][index],'',text['intro'],''])
            lines.extend(f'{i}. {step}' for i,step in enumerate(text['steps'],1))
            if text['note']:lines.extend(['','> '+text['note']])
            if key=='control':lines.extend(['','![Supervisor controls](images/control-en-beta21.png)'])
            for section,asset in (('users','users-beta22.png'),('settings','organization-fa-beta22.png'),('wallboard','wallboard-load-beta22.png')):
                if key==section:lines.extend(['',f'![{TITLES[key][index]}](images/{asset})'])
        lines.extend(['','## '+('پروفایل و رمز عبور' if language=='fa' else 'Profile and password'),'',
            'از «پروفایل و وضعیت من» نام، نام خانوادگی، داخلی و عکس خود را مدیریت کنید. وضعیت عضویت خود و کارکرد روزانه را از همین بخش ببینید. تاریخچهٔ شخصی با تغییر داخلی فقط از زمان تخصیص جدید قابل مشاهده است. تماس کلیکی ابتدا تلفن خودتان را زنگ می‌زند و به مجوز همان صف نیاز دارد. برای تغییر رمز یا داخلی، رمز فعلی را وارد کنید. با این تغییر، تمام نشست‌های قبلی حساب بسته می‌شوند. عکس PNG/JPEG/WebP/AVIF حداکثر ۵۱۲ کیلوبایت و ۴ مگاپیکسل پذیرفته می‌شود و اطلاعات اضافی تصویر حذف می‌شوند.' if language=='fa' else 'Use My profile & status to manage first/last name, assigned phone and picture, change your queue status, and view daily activity. Personal history is clipped to the current phone assignment. Click-to-call rings your own phone first and requires a queue Dial grant. Password or phone changes require the current password and revoke existing account sessions. PNG/JPEG/WebP/AVIF images up to 512 KB and 4 megapixels are decoded, resized and stripped of metadata.','',
            '![Profile](images/profile-en-beta22.png)','',
            '## '+('منابع اتصال پیام‌رسان' if language=='fa' else 'Messaging references'),'','- [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)','- [Bale Bot API](https://docs.bale.ai/)',''])
        (root/'docs'/f'USER_GUIDE.{language}.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':main()
