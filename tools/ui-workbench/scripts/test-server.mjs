import {createServer} from 'vite';
import './generate-tokens.mjs';
const server=await createServer({server:{host:'127.0.0.1',port:18910,strictPort:true}});
await server.listen();
for(const signal of ['SIGINT','SIGTERM'])process.once(signal,async()=>{await server.close();process.exit(0);});
