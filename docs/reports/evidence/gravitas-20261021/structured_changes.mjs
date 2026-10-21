import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd();
const meta=JSON.parse(fs.readFileSync(path.join(root,'.gitnexus/meta.json'),'utf8'));
const dist=path.dirname(path.dirname(meta.runnerIdentity.invokedArtifact.path));
const {LocalBackend}=await import(pathToFileURL(path.join(dist,'mcp/local/local-backend.js')).href);
const backend=new LocalBackend();await backend.init();
for (const scope of ['all','compare']) {
 const args={repo:'Stella_project',scope,...(scope==='compare'?{base_ref:'main'}:{})};
 for(let i=0;i<3;i++) {
  const d=await backend.callTool('detect_changes',args);
  const key=`detect-${scope}-structured${i?'-retry'+i:''}`;
  fs.writeFileSync(path.join(path.dirname(new URL(import.meta.url).pathname),key+'.json'),JSON.stringify(d,null,2)+'\n');
  fs.writeSync(1,JSON.stringify({scope,attempt:i,summary:d.summary,partial:d.partial,truncated:d.truncated,error:d.error})+'\n');
  if(d.error)process.exit(1);
  if(!d.partial&&!d.truncated)break;
  if(i===2)process.exit(2);
 }
}
process.exit(0);
