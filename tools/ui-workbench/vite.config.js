import {defineConfig} from 'vite';
import {fileURLToPath} from 'node:url';
export default defineConfig({server:{fs:{allow:[fileURLToPath(new URL('.',import.meta.url)),...['fonts','data','js','css'].map(dir=>fileURLToPath(new URL('../../qpanel/themes/qpanel/static/'+dir,import.meta.url)))]}}});
