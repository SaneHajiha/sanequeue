import {mountReportDesign} from './report-design.js';
export default {title:'SaneQueue/Reporting',args:{theme:'light'},argTypes:{theme:{control:'select',options:['light','dark']}},parameters:{layout:'fullscreen'}};
export const ChartsAndPersianCalendar={render:({theme})=>{const target=document.createElement('div');mountReportDesign({locale:'fa',theme,target}).catch(()=>{target.textContent='Unable to initialise the reporting design fixture.';target.setAttribute('role','alert');});return target;}};
