import {renderWorkbench} from './components.js';
const params=new URLSearchParams(location.search);
const options={locale:params.get('locale')==='en'?'en':'fa',theme:params.get('theme')==='dark'?'dark':'light'};
if(params.get('view')==='report-design')import('./report-design.js').then(({mountReportDesign})=>mountReportDesign(options));
else if(params.get('view')==='catalog')import('./catalog.js').then(({renderCatalog})=>document.querySelector('#app').append(renderCatalog(options)));
else document.querySelector('#app').append(renderWorkbench(options));
