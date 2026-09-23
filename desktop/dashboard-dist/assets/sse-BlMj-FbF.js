import{g as y}from"./index-Cj9YhfrB.js";async function w(c,l,e={}){const n={Accept:"text/event-stream"},r=y();r&&(n.Authorization=`Bearer ${r}`),e.lastEventId&&(n["Last-Event-ID"]=e.lastEventId),e.body&&(n["Content-Type"]="application/json");const s=await fetch(c,{method:e.method??"GET",body:e.body,headers:n,signal:e.signal});if(!s.ok||!s.body)throw new Error(`SSE 连接失败（${s.status}）`);const f=s.body.getReader(),h=new TextDecoder;let t="";for(;;){const{done:m,value:b}=await f.read();if(m)break;t+=h.decode(b,{stream:!0});let i;for(;(i=t.indexOf(`

`))>=0;){const u=t.slice(0,i);t=t.slice(i+2);let d="";const a=[];for(const o of u.split(`
`))o.startsWith("id:")?d=o.slice(3).trim():o.startsWith("data:")&&a.push(o.slice(5).trim());a.length>0&&l(d,a.join(`
`))}}}export{w as s};
