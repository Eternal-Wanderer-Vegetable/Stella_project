// GitNexus presentation-only audit harness. Never changes the installed package.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
const dir=path.dirname(new URL(import.meta.url).pathname);
const meta=JSON.parse(fs.readFileSync('.gitnexus/meta.json','utf8'));
const original=path.join(path.dirname(path.dirname(meta.runnerIdentity.invokedArtifact.path)),'mcp/local/local-backend.js');
const raw=fs.readFileSync(original,'utf8');
const old='const DETECT_CHANGES_MAX_LISTED_SYMBOLS = 1000;';
if(raw.split(old).length!==2)throw Error('unexpected tool source');
let expanded=raw.replace(old,'const DETECT_CHANGES_MAX_LISTED_SYMBOLS = 20000;');
expanded=expanded.replace(/(from\s*|import\s*\(\s*)(['"])(\.[^'"]+)\2/g,(whole,start,quote,spec)=>start+quote+pathToFileURL(path.resolve(path.dirname(original),spec)).href+quote);
expanded=expanded.replaceAll('import.meta.url',JSON.stringify(pathToFileURL(original).href));
const local=path.join(dir,'local-backend-expanded.mjs');fs.writeFileSync(local,expanded);
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
fs.writeFileSync(path.join(dir,'expanded-listing-provenance.json'),JSON.stringify({original,original_sha256:sha(raw),temporary_sha256:sha(expanded),only_semantic_change:'DETECT_CHANGES_MAX_LISTED_SYMBOLS 1000 -> 20000; all other replacements resolve relative imports to original files',installed_tool_modified:false},null,2)+'\n');
const {LocalBackend}=await import(pathToFileURL(local).href);const backend=new LocalBackend();await backend.init();
for(const scope of ['all','compare']){
 const args={repo:'Stella_project',scope,...(scope==='compare'?{base_ref:'main'}:{})};
 for(let i=0;i<3;i++){
  const d=await backend.callTool('detect_changes',args);const key=`detect-${scope}-complete${i?'-retry'+i:''}`;
  fs.writeFileSync(path.join(dir,key+'.json'),JSON.stringify(d,null,2)+'\n');fs.writeSync(1,JSON.stringify({scope,attempt:i,summary:d.summary,listed:d.changed_symbols?.length,partial:d.partial,truncated:d.truncated})+'\n');
  if(d.error)throw Error(d.error);
  if(!d.partial&&!d.truncated){
   if(d.changed_symbols.length!==d.summary.changed_count)throw Error('incomplete symbol listing');
   const prior=path.join(dir,`detect-${scope}-structured.json`);
   if(fs.existsSync(prior)){const p=JSON.parse(fs.readFileSync(prior,'utf8'));if(JSON.stringify(p.summary)!==JSON.stringify(d.summary))throw Error('summary changed during audit');}
   break;
  }
  if(i===2)process.exit(2);
 }
}
process.exit(0);
