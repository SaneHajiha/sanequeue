// Own the Vite instance directly: avoids Windows shell/taskkill teardown hangs.
import {createServer} from 'vite';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import './generate-tokens.mjs';
const root=fileURLToPath(new URL('..',import.meta.url));
const server=await createServer({root,server:{host:'127.0.0.1',port:18910,strictPort:true}});
await server.listen();
let exitCode=1;
try {
  exitCode=await new Promise((resolve,reject)=>{
    const child=spawn(process.execPath,[fileURLToPath(new URL('../node_modules/@playwright/test/cli.js',import.meta.url)),'test',...process.argv.slice(2)],{cwd:root,stdio:'inherit',windowsHide:true,env:{...process.env,UI_EXTERNAL_SERVER:'1'}});
    child.once('error',reject);child.once('exit',code=>resolve(code??1));
  });
} finally {await server.close();}
process.exitCode=exitCode;
