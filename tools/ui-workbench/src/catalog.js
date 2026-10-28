import catalog from '../../../qpanel/themes/qpanel/static/data/module-catalog.json';
import '../../../qpanel/themes/qpanel/static/js/module-catalog.js';
import '../../../qpanel/themes/qpanel/static/css/module-catalog.css';
import './tokens.css';
import './style.css';
export function renderCatalog({locale='fa',theme='light'}={}){
 const root=document.createElement('main');root.className='sq-workbench';root.lang=locale;root.dir=locale==='fa'?'rtl':'ltr';root.dataset.theme=theme;
 for(const name of ['ink','bg','card','line','accent','muted'])root.style.setProperty('--'+name,'var(--sq-'+name+')');
 const title=document.createElement('h1');title.textContent=locale==='fa'?'وضعیت و قابلیت‌های SaneQueue':'SaneQueue module scope and status';root.append(title);
 const note=document.createElement('p');note.textContent=locale==='fa'?'فهرست کد و برنامهٔ توسعه؛ این صفحه هیچ ماژولی را فعال نمی‌کند.':'Code inventory and roadmap. This page does not activate modules.';root.append(note);
 const content=document.createElement('div');root.append(content);window.SaneQueueCatalog.mount(content,catalog,{fa:locale==='fa'});return root;
}
