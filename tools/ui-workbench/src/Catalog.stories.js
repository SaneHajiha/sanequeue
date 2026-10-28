import {renderCatalog} from './catalog.js';
export default {title:'SaneQueue/Module catalog',render:args=>renderCatalog(args),args:{locale:'fa',theme:'light'},argTypes:{locale:{control:'select',options:['fa','en']},theme:{control:'select',options:['light','dark']}}};
export const PersianLight={};
export const PersianDark={args:{theme:'dark'}};
export const EnglishLight={args:{locale:'en'}};
export const EnglishDark={args:{locale:'en',theme:'dark'}};
