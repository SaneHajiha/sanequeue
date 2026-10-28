import {readFileSync,writeFileSync} from 'node:fs';
const base=new URL('../src/',import.meta.url);
const tokens=JSON.parse(readFileSync(new URL('tokens.json',base),'utf8'));
const css=['/* Generated from tokens.json. Run npm run tokens after editing. */'];
for(const theme of ['light','dark'])css.push(`[data-theme="${theme}"]{${Object.entries(tokens[theme]).map(([key,value])=>`--sq-${key}:${value}`).join(';')}}`);
css.push(`.sq-workbench{${['spacing','radius'].flatMap(group=>Object.entries(tokens[group]).map(([key,value])=>`--sq-${group}-${key}:${value}px`)).join(';')}}`);
writeFileSync(new URL('tokens.css',base),css.join('\n')+'\n');
