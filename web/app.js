"use strict";
const $ = id => document.getElementById(id);
const icons = {
  grid:"M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  clock:"M21 12a9 9 0 1 1-18 0 9 9 0 1 1 18 0 M12 7v5l3 2",
  server:"M3 3h18v7H3z M3 14h18v7H3z M6 6.5h2 M6 17.5h2",
  menu:"M3 6h18 M3 12h18 M3 18h18",plug:"m7 3 4 4 m3-6 4 4 M7 8l8-6 M7 8l-2 3 7 7 7-8-6-6 M9 16l-6 6",
  layers:"m12 3 9 5-9 5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5",
  routes:"M5 5v14 M5 11h8l6-6 M13 11l6 7 M3 3h4v4H3z M17 2h4v4h-4z M17 17h4v4h-4z",
  folder:"M3 6h7l2 2h9v12H3z",search:"M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0 M15 15l6 6",
  arrow:"M4 12h15 m-6-6 6 6-6 6",chevron:"m9 5 7 7-7 7"
};
function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el}
function icon(key){
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");
  const path=document.createElementNS(svg.namespaceURI,"path");path.setAttribute("d",icons[key]);svg.append(path);return svg;
}
document.querySelectorAll("[data-icon]").forEach(i=>i.append(icon(i.dataset.icon)));
document.querySelectorAll("[data-close]").forEach(b=>b.onclick=()=>$(b.dataset.close).close());
let state=null,group="",view="catalog",op=null,log=[],result=null,pending=null,running=false,connecting=false;
const badge = (s,kind=s.toLowerCase())=>node("span","badge "+kind,s);
async function api(path,payload){
  const opts=payload===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)};
  const response=await fetch("/api/"+path,opts);
  const data=await response.json();
  if(!response.ok)throw Error(data.error||"The request failed.");
  return data;
}
function setState(next){
  state=next;group="";log=[];view="catalog";$("search").value="";$("method").replaceChildren(new Option("All methods",""));
  const ops=state?.ops||[],groups=[...new Set(ops.map(o=>o.group))].sort();
  [...new Set(ops.map(o=>o.method))].sort().forEach(m=>$("method").add(new Option(m,m)));
  $("groups").replaceChildren();
  for(const g of groups){
    const b=node("button","nav");b.append(node("i","groupicon"),node("span","",g),node("small","",ops.filter(o=>o.group===g).length));
    b.onclick=()=>{group=g;changeView("catalog")};b.dataset.group=g;$("groups").append(b);
  }
  $("opcount").textContent=ops.length;$("gcount").textContent=groups.length;$("source").textContent=state?.source||"Disconnected";
  $("env").textContent=state?.sample?"Sample environment":state?"Axon environment":"Local workspace";
  $("attempts").textContent=state?.attempts?.length?"Last discovery\n"+state.attempts.join("\n"):"";
  $("disconnectLine").hidden=!state;
  const ref=state?.source==="Reference catalog";$("notice").hidden=!ref;
  $("notice").textContent=ref?"No published description was found. These reference operations come from the Axon guides. Availability depends on your installation and role.":"";
  renderHistory();changeView("catalog");
}
function changeView(v){
  view=v;document.body.classList.remove("showmenu");
  $("catalog").hidden=v!=="catalog";$("history").hidden=v!=="history";
  $("navCatalog").classList.toggle("active",v==="catalog"&&!group);$("navHistory").classList.toggle("active",v==="history");
  document.querySelectorAll("#groups button").forEach(b=>b.classList.toggle("active",v==="catalog"&&b.dataset.group===group));
  const name=v==="history"?"Request history":"Operation catalog";
  $("heading").textContent=name;$("crumb").textContent=name;
  $("sub").textContent=v==="history"?"Requests sent from this tab during the current connection.":state?.sample?"Explore Axon operations with an isolated set of sample banking records.":state?"Browse the catalog for "+state.address+".":"Connect to an Axon installation or open the local sample.";
  renderRows();
}
function renderRows(){
  const q=$("search").value.trim().toLowerCase(),m=$("method").value;
  const ops=(state?.ops||[]).filter(o=>(!group||o.group===group)&&(!m||o.method===m)&&[o.title,o.path,o.group].join(" ").toLowerCase().includes(q));
  $("listTitle").textContent=group||"All operations";$("matches").textContent=ops.length+" "+(ops.length===1?"operation":"operations");
  const frag=document.createDocumentFragment();
  for(const o of ops){
    const row=node("button","row"),name=node("span");name.append(node("span","opname",o.title),node("span","route",o.path));
    row.append(badge(o.method),name,node("span","tag",o.group),icon("chevron"));row.onclick=()=>openRunner(o);frag.append(row);
  }
  if(!ops.length)frag.append(node("p","empty",state?"No operations match these filters.":"Open Connection to choose a workspace."));
  $("rows").replaceChildren(frag);
}
function renderHistory(){
  $("hcount").textContent=log.length;$("events").replaceChildren();$("clear").disabled=!log.length;
  for(const h of log){const row=node("div","event");row.append(badge(String(h.status),h.status>=200&&h.status<300?"ok":"fail"),node("span","",h.title),node("code","route",h.method+" "+h.path),node("time","",h.time));$("events").append(row)}
  if(!log.length)$("events").append(node("p","empty","Executed requests will appear here with their status and time."));
}
$("clear").onclick=()=>{log=[];renderHistory()};$("search").oninput=renderRows;$("method").onchange=renderRows;
$("navCatalog").onclick=()=>{group="";changeView("catalog")};$("navHistory").onclick=()=>changeView("history");
$("menu").onclick=()=>document.body.classList.toggle("showmenu");
document.addEventListener("keydown",e=>{if(e.key==="/"&&!document.querySelector("dialog[open]")&&!["INPUT","SELECT","TEXTAREA"].includes(document.activeElement.tagName)){e.preventDefault();changeView("catalog");$("search").focus()}});
function authFields(){
  const a=$("auth").value;$("userLabel").hidden=a!=="login";$("username").required=a==="login";
  $("secretLabel").hidden=a==="none";$("secret").required=a!=="none";$("secretTitle").textContent={access:"Access token",refresh:"Refresh token",login:"Password"}[a]||"Credential";
}
$("auth").onchange=authFields;authFields();
$("mode").onchange=()=>{$("urlLabel").hidden=$("mode").value!=="url";$("fileLabel").hidden=$("mode").value!=="file"};
$("connection").onclick=()=>{$("cerror").textContent="";$("connectDialog").showModal()};
$("connectDialog").addEventListener("close",()=>{$("secret").value=""});
async function connect(sample){
  if(connecting)return;connecting=true;$("connectSubmit").disabled=true;$("sample").disabled=true;$("disconnect").disabled=true;
  $("cerror").textContent="";$("connectSubmit").textContent="Connecting…";
  try{
    const request=sample?{demo:true}:{address:$("address").value.trim(),auth:$("auth").value,username:$("username").value,secret:$("auth").value==="none"?"":$("secret").value};
    if(!sample&&$("mode").value==="file"){
      const file=$("specFile").files[0];if(!file)throw Error("Choose a JSON description.");request.imported=await file.text();
    }
    if(!sample&&$("mode").value==="url"){
      request.location=$("specUrl").value.trim();if(!request.location)throw Error("Enter the API description URL or path.");
    }
    setState(await api("connect",request));$("connectDialog").close();$("secret").value="";
  }catch(e){$("cerror").textContent=e.message;if(!$("connectDialog").open)$("connectDialog").showModal()}
  finally{connecting=false;$("connectSubmit").disabled=false;$("sample").disabled=false;$("disconnect").disabled=false;$("connectSubmit").textContent="Connect to Axon"}
}
$("connectForm").onsubmit=e=>{e.preventDefault();connect(false)};$("sample").onclick=()=>connect(true);
$("disconnect").onclick=async()=>{try{await api("disconnect",{nonce:state.nonce});setState(null);$("connectDialog").close()}catch(e){$("cerror").textContent=e.message}};
function field(label,input,parent){
  const l=node("label","",label);l.append(input);parent.append(l);return input;
}
function guidedSearch(body,box){
  let sample;
  try{sample=JSON.parse(body.value)}catch{return}
  if(!sample?.searchScopes?.mainFacet?.properties)return;
  const panel=node("div","guided");
  const values=[["Facet","facet",sample.mainFacet],["Page size","limit",sample.searchScopes.mainFacet.properties.limit],["Offset","offset",sample.searchScopes.mainFacet.properties.offset]];
  const controls={};
  for(const [label,key,initial] of values){
    const input=node("input");input.type=key==="facet"?"text":"number";if(key!=="facet")input.min=key==="limit"?1:0;
    input.value=initial;controls[key]=input;field(label,input,panel);
  }
  const details=node("details");details.append(node("summary","","Edit full JSON"),body.parentElement);
  function updateBody(){
    let data;
    try{data=JSON.parse(body.value)}catch{return}
    if(!data.searchScopes?.mainFacet?.properties)return;
    data.mainFacet=controls.facet.value;data.searchScopes.mainFacet.facetId=data.mainFacet;
    data.searchScopes.mainFacet.properties.limit=Number(controls.limit.value);data.searchScopes.mainFacet.properties.offset=Number(controls.offset.value);
    body.value=JSON.stringify(data,null,2);
  }
  panel.addEventListener("input",updateBody);
  body.oninput=()=>{try{const d=JSON.parse(body.value);controls.facet.value=d.mainFacet??"";controls.limit.value=d.searchScopes.mainFacet.properties.limit;controls.offset.value=d.searchScopes.mainFacet.properties.offset}catch{}};
  box.append(panel,details);
}
function guidedObject(body,box){
  let original;
  try{original=JSON.parse(body.value)}catch{return}
  if(typeof original?.object!=="object"||!original.object||Array.isArray(original.object))return;
  const panel=node("div","object-panel"),type=node("input"),rows=node("div"),add=node("button","link","Add property");
  type.placeholder="e.g. System";type.value=original.type||"";field("Axon object, relationship or role type",type,panel);
  panel.append(node("p","hint","Use the property names from your Axon template."),rows,add);
  add.type="button";
  function update(){
    let data;
    try{data=JSON.parse(body.value)}catch{return}
    data.type=type.value;
    const entries=[];
    for(const line of rows.children){
      const [key,value]=line.querySelectorAll("input");
      if(!key.value.trim())continue;
      let val=value.value;
      if(value.dataset.structured==="yes"){try{val=JSON.parse(val)}catch{}}
      entries.push([key.value.trim(),val]);
    }
    data.object=Object.fromEntries(entries);body.value=JSON.stringify(data,null,2);
  }
  function addRow(key="",value=""){
    const row=node("div","property-row"),k=node("input"),v=node("input"),remove=node("button","close","×");
    k.placeholder="Property name";k.setAttribute("aria-label","Property name");k.value=key;
    v.placeholder="Value";v.setAttribute("aria-label","Property value");v.dataset.structured=typeof value==="string"?"no":"yes";v.value=typeof value==="string"?value:JSON.stringify(value);
    remove.type="button";remove.setAttribute("aria-label","Remove property");remove.onclick=()=>{row.remove();update()};
    row.append(k,v,remove);rows.append(row);
  }
  function populate(data){rows.replaceChildren();type.value=data.type??"";Object.entries(data.object||{}).forEach(([k,v])=>addRow(k,v));if(!rows.children.length)addRow()}
  populate(original);add.onclick=()=>{addRow();rows.lastChild.querySelector("input").focus()};panel.oninput=update;
  const details=node("details");details.append(node("summary","","Edit full JSON"),body.parentElement);
  body.oninput=()=>{try{populate(JSON.parse(body.value))}catch{}};
  box.append(panel,details);
}
function formParts(o,media,box){
  box.replaceChildren();if(!media)return;
  const spec=o.formats[media];
  if(["multipart/form-data","application/x-www-form-urlencoded"].includes(media)){
    for(const p of spec.fields){
      const input=node("input");input.type=p.file?"file":"text";input.required=p.required;input.dataset.field=p.name;
      if(!p.file)input.value=p.default??"";field(p.name+(p.required?" *":""),input,box);
    }
  }else if(media==="application/octet-stream"){
    const input=node("input");input.type="file";input.id="bin";input.required=o.requiredBody;field("Request file",input,box);
  }else{
    const input=node("textarea");input.id="body";input.spellcheck=false;input.required=o.requiredBody;
    input.value=media.includes("json")?JSON.stringify(spec.example,null,2):typeof spec.example==="string"?spec.example:"";
    field(media.includes("json")?"JSON body":"Request body",input,box);
    if(o.path==="/unison/v2/facet/_search")guidedSearch(input,box);
    if(o.path==="/api/v1/object")guidedObject(input,box);
  }
}
function openRunner(o){
  op=o;result=null;pending=null;$("review").hidden=true;$("run").disabled=false;$("run").textContent="Run request";
  $("runGroup").textContent=o.group;$("runTitle").textContent=o.title;$("pathline").replaceChildren(badge(o.method),node("code","",o.path));
  $("runDescription").textContent=o.description;$("response").className="empty";$("response").textContent="Run the request to see its response.";
  $("rerror").textContent="";$("download").hidden=true;const inputs=$("inputs");inputs.replaceChildren();
  for(const p of o.params){
    let input;
    if(p.enum.length){input=node("select");input.add(new Option("Choose a value",""));p.enum.forEach(v=>input.add(new Option(v,v)))}
    else{input=node("input");input.type=["integer","number"].includes(p.type)?"number":"text";if(p.type==="number")input.step="any";if(p.type==="array")input.placeholder='["first", "second"]'}
    input.value=Array.isArray(p.default)?JSON.stringify(p.default):p.default??"";input.dataset.param=p.in+":"+p.name;input.required=p.required;
    field(p.name+" · "+p.in+(p.required?" *":""),input,inputs);
  }
  const types=Object.keys(o.formats);
  if(types.length){
    const select=node("select");select.id="media";if(!o.requiredBody)select.add(new Option("No body",""));
    types.forEach(t=>select.add(new Option(t,t)));field("Content type",select,inputs);
    const box=node("div");inputs.append(box);select.onchange=()=>formParts(o,select.value,box);select.onchange();
  }
  if(!types.length&&!o.params.length)inputs.append(node("p","hint","This operation has no request fields."));
  if(o.unsupported.length){$("rerror").textContent=o.unsupported.join("\n");$("run").disabled=true}
  $("runner").showModal();
}
async function encodeFile(file){
  if(!file||file.size>12*1024*1024)throw Error("Choose a file of 12 MiB or less.");
  const reader=new FileReader();return await new Promise((resolve,reject)=>{reader.onload=()=>resolve(reader.result.split(",")[1]);reader.onerror=()=>reject(Error("Could not read the file."));reader.readAsDataURL(file)});
}
async function build(){
  const request={nonce:state.nonce,id:op.id,values:{},form:{},media:$("media")?.value||""};
  for(const f of $("inputs").querySelectorAll("[data-param]"))request.values[f.dataset.param]=f.value;
  if($("body")){request.body=$("body").value;if(request.body&&request.media.includes("json"))JSON.parse(request.body)}
  if($("bin")?.files[0])request.binary=await encodeFile($("bin").files[0]);
  for(const f of $("inputs").querySelectorAll("[data-field]")){
    if(f.type!=="file")request.form[f.dataset.field]=f.value;
    else if(f.files[0])request.form[f.dataset.field]={name:f.files[0].name,data:await encodeFile(f.files[0])};
  }
  return request;
}
function review(on){
  $("review").hidden=!on;$("inputs").inert=on;$("run").textContent=on?"Confirm and send":"Run request";
  if(!on)pending=null;
}
$("cancelReview").onclick=()=>review(false);
$("runner").addEventListener("close",()=>{review(false)});
$("runner").addEventListener("cancel",e=>{if(running)e.preventDefault()});
$("runForm").onsubmit=async e=>{
  e.preventDefault();if(running)return;running=true;$("run").disabled=true;
  $("runner").querySelector(".close").disabled=true;$("rerror").textContent="";
  try{
    const request=pending||await build();
    if(!["GET","HEAD","OPTIONS"].includes(op.method)&&!pending){
      pending=request;
      let actualPath=op.path;
      for(const p of op.params.filter(p=>p.in==="path"))actualPath=actualPath.replace("{"+p.name+"}",encodeURIComponent(request.values["path:"+p.name]));
      $("reviewText").textContent=op.method+" "+actualPath+" will be sent to "+state.address+".";
      review(true);return;
    }
    request.confirmed=!!pending;$("run").textContent="Sending…";$("download").hidden=true;
    $("response").textContent="Waiting for Axon…";
    result=await api("run",request);review(false);showResult();
    log.unshift({status:result.status,title:op.title,method:op.method,path:op.path,time:new Date().toLocaleTimeString()});log=log.slice(0,100);renderHistory();
  }catch(e){review(false);result=null;$("download").hidden=true;$("rerror").textContent=e.message;$("response").textContent="No response to display."}
  finally{running=false;$("run").disabled=false;$("runner").querySelector(".close").disabled=false}
};
function showResult(){
  const r=result, box=$("response"),meta=node("div","meta");meta.append(badge("HTTP "+r.status,r.status>=200&&r.status<300?"ok":"fail"),node("span","",r.ms+" ms · "+r.bytes.toLocaleString()+" bytes · "+r.type));
  box.className="";box.replaceChildren(meta);
  let text=r.binary?"Binary response · "+r.filename:r.body||"Empty response body.";
  if(!r.binary&&r.type.includes("json")){
    try{
      const data=JSON.parse(r.body);text=JSON.stringify(data,null,2);
      const items=Array.isArray(data)?data:(data?.items??data?.entries);
      if(Array.isArray(items)&&items.length&&items.every(x=>x&&typeof x==="object"&&!Array.isArray(x))){
        const cols=[...new Set(items.slice(0,50).flatMap(Object.keys))].filter(k=>items.slice(0,50).every(x=>x[k]==null||typeof x[k]!=="object")).slice(0,8);
        if(cols.length){
          const wrap=node("div","tablewrap"),table=node("table"),head=node("tr");cols.forEach(c=>head.append(node("th","",c)));table.append(head);
          items.slice(0,50).forEach(item=>{const row=node("tr");cols.forEach(c=>row.append(node("td","",item[c]??"")));table.append(row)});
          wrap.append(table);box.append(wrap);
          const raw=node("details");raw.append(node("summary","","View JSON response"),node("pre","output",text.slice(0,120000)));box.append(raw);$("download").hidden=!r.bytes;return;
        }
      }
    }catch{}
  }
  box.append(node("pre","output",text.slice(0,120000)+(text.length>120000?"\n… Save the response for the full content.":"")));
  $("download").hidden=!r.bytes;
}
$("download").onclick=()=>{
  const r=result;if(!r)return;const data=r.binary?Uint8Array.from(atob(r.body),c=>c.charCodeAt(0)):r.body;
  const url=URL.createObjectURL(new Blob([data],{type:"application/octet-stream"})),a=node("a");a.href=url;a.download=r.filename.split(/[\\/]/).pop()||"response.bin";a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
};
(async()=>{
  try{const info=await api("state");$("address").value=info.defaultAddress||info.state?.address||"";if(info.state?.sample)$("address").value=info.defaultAddress||"";
    if(info.state)setState(info.state);else await connect(true);
  }catch(e){setState(null);$("notice").hidden=false;$("notice").textContent=e.message}
})();
