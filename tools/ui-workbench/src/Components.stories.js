import {button,kpi,statusBadge,agentTable,statePanel} from './components.js';
export default {title:'SaneQueue/Components',args:{locale:'fa',theme:'light'},argTypes:{locale:{control:'select',options:['fa','en']},theme:{control:'select',options:['light','dark']}},decorators:[(story,context)=>{const wrapper=document.createElement('main');wrapper.className='sq-workbench';wrapper.dataset.theme=context.args.theme;wrapper.dir=context.args.locale==='fa'?'rtl':'ltr';wrapper.lang=context.args.locale;wrapper.append(story());return wrapper;}]};
export const Button={render:({locale})=>button(locale==='fa'?'ذخیره':'Save')};
export const DisabledButton={render:({locale})=>button(locale==='fa'?'ذخیره':'Save',{disabled:true})};
export const Metric={render:({locale})=>kpi(locale)};
export const UnknownMetric={render:({locale})=>kpi(locale,true)};
export const AgentStates={render:({locale})=>{const list=document.createElement('div');list.className='sq-toolbar';for(const state of ['available','ringing','oncall','paused','wrapup','offline'])list.append(statusBadge(state,locale));return list;}};
export const DataTable={render:({locale})=>agentTable(locale)};
export const PermissionDenied={render:({locale})=>statePanel('denied',locale)};
