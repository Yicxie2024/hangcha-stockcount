/* Hangcha StockCount Offline v0.3.4: floor-first contextual navigation; no external libraries or network API. */
'use strict';
const DB_NAME='hangcha-stockcount-01'; let db;let catalog=[];let meta={};let records=[];
const STEPS=['floor','col','row','level','slot','partition','suffix','part','measure','qty','note'];
const TITLES=['选择物理楼层','选择货架列','选择行号','选择层号','选择格号','选择箱子层号','输入备注号','确认零件','尺寸与重量','实际数量','填写备注'];
const STAGE={floor:0,col:1,row:2,level:3,slot:4,partition:5,suffix:6,part:7,measure:8,qty:9,note:10};
const FIELDS=['col','row','level','slot','partition','suffix'];
const empty=()=>({floor:0,col:'',row:'',level:'',slot:'',partition:'',suffix:'',partKey:'',erp:'',partNo:'',partName:'',lengthCm:'',widthCm:'',heightCm:'',weightKg:'',qty:'',mode:'normal',originalLocation:'',note:''});
let form=empty(),step=0,lastLocation=null,editId=null,workingFloor=0;let shelves=[];let partSearch='', searchTimer=null;
const $=id=>document.getElementById(id);
// All displayed locations are derived from the same form state.
function floorFromLevel(level){const n=Number(level);return n>=1&&n<=12?Math.ceil(n/4):0}
function currentFloor(){return Number(form.floor)||floorFromLevel(form.level)||0}
function validFloor(f){return Number.isInteger(Number(f))&&Number(f)>=1&&Number(f)<=3}
function resetDependentData(){
  form.partKey='';form.erp='';form.partNo='';form.partName='';
  for(const k of ['lengthCm','widthCm','heightCm','weightKg'])form[k]='';
  form.qty='';form.note='';partSearch='';
}
function clearSelectedPart(){form.partKey='';form.erp='';form.partNo='';form.partName=''}
function updateLocationView(){
  const preview=$('locPreview');if(preview)preview.textContent=canonical(form)||'—';
  const floorText=$('floorContext');if(floorText)floorText.textContent=currentFloor()?`工作楼层：${currentFloor()}F · ${form.level?'库位层号已确定':'尚未选择具体层号'}`:'先选择物理楼层（不属于库位编号）';
  const change=$('changeFloor');if(change)change.textContent=currentFloor()?`切换 ${currentFloor()}F`:'选楼层';
  renderTrail();renderRackPreview();
}
function setLocationField(field,value){
  if(form[field]===value)return;
  form[field]=value;
  const index=FIELDS.indexOf(field);
  for(let i=index+1;i<FIELDS.length;i++)form[FIELDS[i]]='';
  resetDependentData();
}
function lastLocationField(){
  for(let i=FIELDS.length-1;i>=0;i--)if(String(form[FIELDS[i]]||'').trim())return i;
  return -1;
}
function jumpToStage(target){
  if(target<0||target>STAGE.suffix)return;
  if(target!==STAGE.floor&&!validFloor(form.floor)){step=STAGE.floor;renderStep();return;}
  // Jump is for editing: do not erase a value until the employee changes it.
  step=target;renderStep();
}
function renderTrail(){
  const host=$('locationTrail');if(!host)return;
  host.replaceChildren();
  const crumbs=[['floor',currentFloor()?currentFloor()+'F':'楼层'],['col',form.col||'列'],['row',form.row||'行'],['level',form.level||'层']];
  for(let i=0;i<crumbs.length;i++){
    const [stage,label]=crumbs[i];if(i>0&&(!validFloor(form.floor)||(i>1&&!form.col)||(i>2&&!form.row)))break;
    if(i)host.append(element('span',{class:'trail-sep'},'›'));
    const x=element('button',{type:'button',class:'trail-item'+(step===STAGE[stage]?' trail-current':'')+(label.length>2&&i>0?' trail-empty':''),onclick:()=>jumpToStage(STAGE[stage])},label);
    x.title='返回修改'+TITLES[STAGE[stage]];host.append(x);
  }
}
async function chooseFloor(f){
  if(!validFloor(f))return;
  const n=Number(f), old=currentFloor();
  if(old!==n){
    // A physical floor has 4 rack levels; changing floors cannot retain a stale level.
    for(let i=2;i<FIELDS.length;i++)form[FIELDS[i]]='';
    resetDependentData();
  }
  form.floor=n;workingFloor=n;
  try{await req('metadata','put',{key:'workingFloor',value:n});meta.workingFloor=n}
  catch(e){showToast('楼层偏好保存失败，请检查浏览器存储');console.error(e)}
  step=STAGE.col;renderStep();
}
function backStep(){
  if(step===STAGE.floor){go('home');return;}
  if(step===STAGE.part){ // Back to the deepest *actual* location field; preserve it for editing.
    step=Math.max(STAGE.col,lastLocationField()+1);renderStep();return;
  }
  if(step>=STAGE.col&&step<=STAGE.suffix){
    // 'Back' deletes the last entered component and every descendant.
    const here=step-1;const clearFrom=String(form[FIELDS[here]]||'').trim()?here:here-1;
    if(clearFrom>=0){for(let i=clearFrom;i<FIELDS.length;i++)form[FIELDS[i]]='';resetDependentData()}
  }
  step--;renderStep();
}
function renderFloorOverview(host){
  const stack=element('div',{class:'scene-floor-stack'});
  for(const floor of [3,2,1]){
    const item=element('div',{class:'scene-floor-slab'+(currentFloor()===floor?' scene-selected':'')});
    item.append(element('b',{},floor+'F'),element('small',{},pad2((floor-1)*4+1)+'–'+pad2(floor*4)));
    stack.append(item);
  }
  host.append(stack);
}
function renderColumnScene(host){
  const strip=element('div',{class:'scene-columns'});
  for(const letter of 'ABCDEFGHIJKLMNOP'){
    const cube=element('div',{class:'scene-col-cube'+(form.col===letter?' scene-selected':'')});
    cube.append(element('span',{},letter));strip.append(cube);
  }
  host.append(strip);
}
function renderRowScene(host){
  const max=form.col==='H'?13:['F','G'].includes(form.col)?8:12;
  const strip=element('div',{class:'scene-rows'});
  for(let i=1;i<=max;i++){
    const name=pad2(i),cube=element('div',{class:'scene-row-cube'+(form.row===name?' scene-selected':'')});
    cube.append(element('span',{},name));strip.append(cube);
  }
  host.append(strip);
}
function renderRackStack(host){
  const illustration=element('div',{class:'rack-stack'});
  const level=Number(form.level||0), floor=currentFloor();
  for(let f=3;f>=1;f--){
    const block=element('div',{class:'rack-floor'+(floor===f?' floor-active':'')});
    const cells=element('div',{class:'rack-cells'});
    for(let n=f*4;n>=f*4-3;n--){
      const cell=element('span',{class:'rack-cell'+(level===n?' level-active':'')});
      cell.title='货架层号 '+pad2(n);cells.append(cell);
    }
    block.append(cells,element('span',{class:'rack-floor-label'},f+'F'));
    illustration.append(block);
  }
  host.append(illustration);
}
function renderRackPreview(){
  const host=$('rackVisual');if(!host)return;host.replaceChildren();
  const floor=currentFloor(),col=form.col,row=form.row,level=Number(form.level||0);
  const wrap=element('div',{class:'rack-preview scene-preview'+(step>=STAGE.part?' scene-compact':'')});
  const pic=element('div',{class:'scene-illustration'});
  let heading='',detail='';
  if(step===STAGE.floor){
    renderFloorOverview(pic);heading='仓库三层总览';detail='先选工作楼层；下一条记录会记住本楼层。';
  }else if(step===STAGE.col){
    renderColumnScene(pic);heading=floor+'F · 选择 A–P 货架列';detail='16列概览，按下方大按钮选择，选中后自动进入行号。';
  }else if(step===STAGE.row){
    renderRowScene(pic);heading=floor+'F · '+col+'列';detail=['F','G'].includes(col)?'本列01–08，01靠近横向通道/楼梯方向。':col==='H'?'H列共13行。':'当前列共12行。';
  }else{
    renderRackStack(pic);heading=col+(row||'')+(level?(' · 层'+pad2(level)):' · 选择层号');
    detail=`物理${floor}F，对应层号 ${pad2((floor-1)*4+1)}–${pad2(floor*4)}。`;
    if(level)detail+='已定位本楼层第'+((level-1)%4+1)+'货架层。';
    if(form.slot)detail+=' 格号'+form.slot+'。';
    if(form.partition)detail+=' 箱子层'+form.partition+'。';
    if(form.suffix)detail+=' 备注号'+form.suffix+'。';
  }
  const copy=element('div',{class:'rack-description'});
  copy.append(element('b',{},heading),element('span',{},detail));
  wrap.append(pic,copy);host.append(wrap);
  host.setAttribute('role','img');host.setAttribute('aria-label',heading+'。'+detail+' 示意图只用于理解位置，具体选择请使用下方按钮。');
}

function showToast(str){const el=$('toast');el.textContent=str;el.classList.add('show');clearTimeout(showToast.t);showToast.t=setTimeout(()=>el.classList.remove('show'),3300)}
function openDB(){return new Promise((resolve,reject)=>{const q=indexedDB.open(DB_NAME,2);q.onupgradeneeded=()=>{const d=q.result;if(!d.objectStoreNames.contains('records'))d.createObjectStore('records',{keyPath:'id'});if(!d.objectStoreNames.contains('catalog'))d.createObjectStore('catalog',{keyPath:'key'});if(!d.objectStoreNames.contains('metadata'))d.createObjectStore('metadata',{keyPath:'key'});if(!d.objectStoreNames.contains('shelves'))d.createObjectStore('shelves',{keyPath:'id'})};q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error)})}
function req(store,method,...args){return new Promise((resolve,reject)=>{const tx=db.transaction(store,'readwrite');const op=tx.objectStore(store)[method](...args);op.onsuccess=()=>resolve(op.result);op.onerror=()=>reject(op.error)})}
function all(store){return req(store,'getAll')}
async function load(){records=(await all('records')).filter(r=>!r.deleted);catalog=await all('catalog');shelves=await all('shelves');const m=await all('metadata');meta=Object.fromEntries(m.map(x=>[x.key,x.value]));$('worker').value=localStorage.getItem('worker')||'';$('session').value=localStorage.getItem('session')||new Date().getFullYear()+'年度盘库';lastLocation=meta.lastLocation||null;workingFloor=validFloor(meta.workingFloor)?Number(meta.workingFloor):(validFloor(lastLocation?.floor)?Number(lastLocation.floor):floorFromLevel(lastLocation?.level));refreshStats()}
function refreshStats(){const stats={shelfCount:shelves.filter(x=>!x.deleted).length,recordCount:records.length,catalogCount:catalog.length,catalogInfo:meta.catalogName?`${meta.catalogName} · ${catalog.length} 行 · ${meta.snapshotId||''}`:'尚未导入库存基准'};for(const [id,value] of Object.entries(stats)){const el=$(id);if(el)el.textContent=value;else console.warn('Missing optional UI element:',id)}}
function go(view){for(const e of document.querySelectorAll('.view'))e.classList.toggle('active',e.id===view);for(const e of document.querySelectorAll('nav button'))e.classList.toggle('active',e.dataset.view===view);if(view==='history'){renderHistory();renderShelves()}if(view==='count')renderStep();window.scrollTo({top:0,behavior:'instant'})}
function pad2(s){const n=String(s).trim();return /^\d{1,2}$/.test(n)?n.padStart(2,'0'):n}
function canonical(x){const base=(x.col||'')+(x.row||'')+(x.level||'')+(x.slot||'');return base+(x.partition?'-'+x.partition:'')+(x.suffix?'-'+x.suffix:'')}
function prefix(x){return (x.col||'')+(x.row||'')+(x.level||'')+(x.slot||'')}
function validLocation(){if(!validFloor(form.floor)||!form.col)return false;if(form.row){const r=Number(form.row);if(r<1||r>(['F','G'].includes(form.col)?8:form.col==='H'?13:12))return false;}if(form.level&&(Number(form.level)<1||Number(form.level)>12||floorFromLevel(form.level)!==Number(form.floor)))return false;return true}
function candidateRows(){
 const query=canonical(form).toUpperCase();if(!query)return {rows:[],exact:0,descendants:0};
 const ranked=[];
 for(const c of catalog){
   const locs=c.locations?.length?c.locations:[c.location];
   let rank=0;
   for(const raw of locs){
     const loc=String(raw||'').toUpperCase().trim();
     if(loc===query){rank=2;break}
     // A prefix may only match at a component boundary, not across a numeric field.
     const base=prefix(form).toUpperCase();
     if(query===base && !form.partition && !form.suffix){
       if(loc.startsWith(base) && (loc.length===base.length || (base.length===1? /^\d/.test(loc.slice(1)) : (base.length===3?/^\d/.test(loc.slice(3)):base.length===5? /^\d|-/.test(loc.slice(5)): loc[base.length]==='-')))) rank=Math.max(rank,1);
     }else if(loc.startsWith(query+'-')) rank=Math.max(rank,1);
   }
   if(rank)ranked.push({c,rank});
 }
 ranked.sort((a,b)=>b.rank-a.rank);
 return {rows:ranked.slice(0,80).map(x=>({...x.c,_matchRank:x.rank})),exact:ranked.filter(x=>x.rank===2).length,descendants:ranked.filter(x=>x.rank===1).length,more:ranked.length>80};
}
function uniqueParts(rows){let d=new Map();for(const r of rows){const k=r.erp+'|'+r.partNo;if(!d.has(k))d.set(k,r)}return [...d.values()]}
function element(tag,props={},text){const e=document.createElement(tag);for(const[k,v]of Object.entries(props)){if(k==='class')e.className=v;else if(k==='onclick')e.addEventListener('click',v);else e.setAttribute(k,v)}if(text!==undefined)e.textContent=text;return e}
function blockTitle(name,hint){const d=element('div');d.append(element('h2',{class:'step-title'},name),element('p',{class:'step-hint'},hint));return d}
function keyGrid(values,selected,fn,three=false){const d=element('div',{class:'keys'+(three?' three':'')});for(const s of values){const b=element('button',{class:'key'+(s===selected?' selected':''),type:'button',onclick:()=>{fn(s);if(step>=STAGE.col&&step<=STAGE.partition)step++;renderStep()}},s);d.append(b)}return d}
function entry(current,placeholder,handler,type='text'){const d=element('div',{class:'entry-block'});const x=element('input',{placeholder,type,autocapitalize:'off',autocomplete:'off'});x.value=current;x.addEventListener('input',()=>{handler(x.value);updateLocationView()});d.append(x);return d}
function selection(label,detail,selected,fn){const e=element('div',{class:'choice'+(selected?' selected':''),onclick:fn});const circle=element('span',{},selected?'◉':'◯');circle.style.color=selected?'#2777b2':'#8a99a5';const txt=element('div');txt.append(element('b',{},label));if(detail)txt.append(element('small',{},detail));e.append(circle,txt);return e}
function normalizeCode(v){return String(v??'').toUpperCase().replace(/[^A-Z0-9]/g,'')}
function locationRank(c){
 const query=canonical(form).toUpperCase();if(!query)return 0;
 const base=prefix(form).toUpperCase();let rank=0;
 for(const raw of (c.locations?.length?c.locations:[c.location])){
  const loc=String(raw||'').toUpperCase().trim();
  if(loc===query)return 2;
  if(query===base&&!form.partition&&!form.suffix){
   if(loc.startsWith(base)&&(loc.length===base.length||(base.length===1?/^\d/.test(loc.slice(1)):base.length===3?/^\d/.test(loc.slice(3)):base.length===5?/^\d|-/.test(loc.slice(5)):loc[base.length]==='-')))rank=1;
  }else if(loc.startsWith(query+'-'))rank=1;
 }
 return rank;
}
function selectPart(c){
 const changed=form.partKey!==(c.erp+'|'+c.partNo);
 form.partKey=c.erp+'|'+c.partNo;form.erp=c.erp||'';form.partNo=c.partNo||'';form.partName=c.name||'';
 if(changed)for(const k of ['lengthCm','widthCm','heightCm','weightKg'])form[k]='';
 step=STAGE.measure;renderStep();
}
function renderPartResults(host){
 if(!host||!host.isConnected)return;
 host.replaceChildren();
 const q=normalizeCode(partSearch);
 if(partSearch.trim()&&q.length<2){host.append(element('p',{class:'mini muted'},'至少输入2个有效字母或数字开始全库搜索。'));return}
 let candidates=[];let total=0;
 if(q){
  for(const c of catalog){
   const erp=c._erpSearch||(c._erpSearch=normalizeCode(c.erp));
   const pn=c._partSearch||(c._partSearch=normalizeCode(c.partNo));
   if(erp.includes(q)||pn.includes(q)){
    const locRank=locationRank(c);
    const matchRank=(erp===q||pn===q)?3:(erp.startsWith(q)||pn.startsWith(q))?2:1;
    candidates.push({c,locRank,matchRank});total++;
   }
  }
  candidates.sort((a,b)=>b.locRank-a.locRank||b.matchRank-a.matchRank||(a.c.erp||a.c.partNo).localeCompare(b.c.erp||b.c.partNo));
 }else{
  const matches=candidateRows();
  candidates=uniqueParts(matches.rows).map(c=>({c,locRank:c._matchRank||locationRank(c),matchRank:0}));
  total=matches.exact+matches.descendants;
 }
 const seen=new Set(),unique=[];
 for(const hit of candidates){const c=hit.c,key=(c.erp||'')+'|'+(c.partNo||'');if(seen.has(key))continue;seen.add(key);unique.push(hit);if(unique.length>=20)break}
 host.append(element('p',{class:'mini muted'},q?`全仓库共找到 ${total} 行匹配记录；优先展示当前库位，最多显示20种零件。`:`当前库位相关记录 ${total} 行；如未找到，可输入部分 ERP / Part No. 在全仓库搜索。`));
 for(const {c,locRank} of unique){
  const match=locRank===2?'✓ 当前位置精确匹配':locRank===1?'△ 更细库位候选':'其他 ERP 登记库位';
  const item=selection(c.erp||c.partNo||'未编号',`${match} · Part: ${c.partNo||'—'} · ${c.name||''} · 登记位置 ${c.location||'未知'}`,form.partKey===(c.erp+'|'+c.partNo),()=>selectPart(c));
  item.setAttribute('role','button');item.setAttribute('tabindex','0');item.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectPart(c)}});
  host.append(item);
 }
 if(!unique.length)host.append(element('p',{class:'mini muted'},q?'没有匹配结果。可在下方手动输入编号，并保留当前实际库位。':'该库位无已登记候选，可输入部分零件编号搜索。'));
}
function parsedReference(c){
 const result={lengthCm:'',widthCm:'',heightCm:'',weightKg:''};
 const dims=String(c.referenceDimensions||'').trim().match(/^(\d+(?:[.,]\d+)?)\s*[*x×X]\s*(\d+(?:[.,]\d+)?)\s*[*x×X]\s*(\d+(?:[.,]\d+)?)$/);
 if(dims){for(let i=0;i<3;i++){const n=Number(dims[i+1].replace(',','.'));if(Number.isFinite(n)&&n>0)result[['lengthCm','widthCm','heightCm'][i]]=String(n)}}
 const weight=String(c.referenceWeight||'').trim().match(/^(\d+(?:[.,]\d+)?)\s*(kg|g)$/i);
 if(weight){const n=Number(weight[1].replace(',','.'))/(weight[2].toLowerCase()==='g'?1000:1);if(Number.isFinite(n)&&n>0)result.weightKg=String(Number(n.toFixed(6)))}
 return result;
}
function measurementValue(v){const s=String(v??'').trim().replace(',','.');return s===''?null:Number(s)}
function validMeasurements(){for(const [field,label] of [['lengthCm','长'],['widthCm','宽'],['heightCm','高'],['weightKg','重量']]){
 const text=String(form[field]??'').trim();if(!text)continue;
 if(!/^(?:\d+(?:[.,]\d+)?|[.,]\d+)$/.test(text)||!Number.isFinite(measurementValue(text))||measurementValue(text)<=0||measurementValue(text)>1000000){showToast(label+'请输入大于0的数字，或留空');return false}
 }return true}
function renderStep(){
  const key=STEPS[step];
  document.body.classList.toggle('floor-stage',key==='floor');
  $('stepNumber').textContent=`${step+1} / ${STEPS.length}`;
  $('stepName').textContent=TITLES[step];
  $('progressFill').style.width=(step+1)/STEPS.length*100+'%';
  updateLocationView();
  $('lastPreview').textContent=lastLocation?'上一个库位：'+canonical(lastLocation):'';
  const a=$('stepArea');a.replaceChildren();
  $('backBtn').style.visibility='visible';
  $('backBtn').textContent=step===STAGE.part?'← 修改库位':'← 上一步';
  $('skipBtn').style.display=(step>=STAGE.row&&step<=STAGE.suffix&&form.col)||step===STAGE.measure?'block':'none';
  $('skipBtn').textContent=step===STAGE.measure?'跳过尺寸重量':'库位到此结束';
  $('nextBtn').textContent=step===STAGE.note?'保存并继续 ✓':step===STAGE.suffix?'确认库位 →':step===STAGE.measure?'下一步：数量 →':'继续 →';
  $('nextBtn').style.display=(step<=STAGE.partition)?'none':'flex';
  $('nextBtn').disabled=false;
  $('completeShelf').style.display=(step>=STAGE.row&&step<=STAGE.suffix&&form.col&&form.row)?'flex':'none';
  if(key==='floor'){
    a.append(blockTitle('选择物理楼层','首次选一次，后续自动记住；你可以随时点击上方「切换楼层」。'));
    const d=element('div',{class:'floor-choice-grid'});
    for(const f of [1,2,3]){
      const b=element('button',{class:'floor-choice'+(currentFloor()===f?' selected':''),type:'button',onclick:()=>chooseFloor(f)});
      b.append(element('b',{},f+'F'),element('small',{},`货架层 ${pad2((f-1)*4+1)}–${pad2(f*4)}`));d.append(b);
    }
    a.append(d);
  }
  if(key==='col'){
    a.append(blockTitle(`选择 ${currentFloor()}F 的货架列`,'A–P，按一下自动进入行号。当前楼层会继续保留。'));
    a.append(keyGrid('ABCDEFGHIJKLMNOP'.split(''),form.col,v=>setLocationField('col',v)));
  }
  if(key==='row'){
    a.append(blockTitle(`${currentFloor()}F · ${form.col}列：选择行号`,['F','G'].includes(form.col)?'F/G列只有01–08，01靠近横向通道方向。':form.col==='H'?'H列为01–13。':'普通列为01–12。'));
    const max=['F','G'].includes(form.col)?8:form.col==='H'?13:12;
    a.append(keyGrid(Array.from({length:max},(_,i)=>pad2(i+1)),form.row,v=>setLocationField('row',v),true));
  }
  if(key==='level'){
    a.append(blockTitle(`${currentFloor()}F · 选择具体货架层`,'本楼层只有四个层号，点选自动前进；也可以提前结束库位。'));
    const start=(currentFloor()-1)*4+1;
    a.append(keyGrid(Array.from({length:4},(_,i)=>pad2(start+i)),form.level,v=>setLocationField('level',v),true));
  }
  if(key==='slot'){
    a.append(blockTitle('选择格号','01–05；不需要时可点击「库位到此结束」。'));
    a.append(keyGrid(['01','02','03','04','05'],form.slot,v=>setLocationField('slot',v),true));
  }
  if(key==='partition'){
    a.append(blockTitle('选择箱子层号','仅有 I、II、III；没有时点击「库位到此结束」。'));
    a.append(keyGrid(['I','II','III'],form.partition,v=>setLocationField('partition',v),true));
  }
  if(key==='suffix'){
    a.append(blockTitle('输入备注号（物理库位第六级）','备注号是存储位置的一部分，不是下面的自由备注。'));
    a.append(entry(form.suffix,'例如 1 / AB12 / 001',v=>setLocationField('suffix',v.trim().toUpperCase())));
  }
 if(key==='part'){
  a.append(blockTitle('查找并选择零件','支持 ERP No. 或 Part No. 任意片段；当前库位匹配优先，搜索始终覆盖全仓库。'));
  const wrap=element('div',{class:'part-search'});
  const label=element('label',{},'ERP / Part No. 部分编号搜索');
  const search=element('input',{type:'search',placeholder:'例如 920268 / ABS200 / 110025',autocapitalize:'off',autocomplete:'off',inputmode:'search'});
  search.value=partSearch;
  const results=element('div',{class:'part-results'});
  search.addEventListener('input',()=>{
    partSearch=search.value;
    clearSelectedPart();
    clearTimeout(searchTimer);
    searchTimer=setTimeout(()=>renderPartResults(results),130);
  });
  search.addEventListener('keydown',e=>{if(e.key==='Enter')e.preventDefault()});
  wrap.append(label,search,results);a.append(wrap);
  renderPartResults(results);
  const manual=element('details',{class:'manual-part'});
  if(!catalog.length)manual.open=true;
  manual.append(element('summary',{},'未找到？手工填写 ERP No. / Part No.'));
  manual.append(element('label',{},'ERP No.'));
  manual.append(entry(form.erp,'ERP No.（至少填写一种）',v=>{form.erp=v.trim();form.partKey=''}));
  manual.append(element('label',{},'Part No.'));
  manual.append(entry(form.partNo,'Part No.',v=>{form.partNo=v.trim();form.partKey=''}));
  a.append(manual);
 }
 if(key==='measure'){
  a.append(blockTitle('尺寸与重量（可选）','长、宽、高单位 cm；重量单位 kg。无需逐项确认；没有测量值可直接跳过。'));
  const selected=catalog.find(c=>c.erp===form.erp&&c.partNo===form.partNo&&locationRank(c)>0)||catalog.find(c=>c.erp===form.erp&&c.partNo===form.partNo);
  if(selected&&(selected.referenceDimensions||selected.referenceWeight)){
    const info=element('p',{class:'reference-hint'},'ERP 参考（不自动写入实测）：'+
      (selected.referenceDimensions?'尺寸 '+selected.referenceDimensions+'；':'')+
      (selected.referenceWeight?'重量 '+selected.referenceWeight:'')
    );a.append(info);
    const ref=parsedReference(selected);
    if(Object.values(ref).some(v=>v!=='')){
      const use=element('button',{class:'secondary ref-use',type:'button',onclick:()=>{
        for(const [k,v] of Object.entries(ref))if(v!=='')form[k]=v;
        renderStep();showToast('已填入可明确识别的ERP参考值，请核对后继续');
      }},'↙ 一键填入可识别的 ERP 参考数值');
      a.append(use);
    }
  }
  const group=element('div',{class:'measure-grid'});
  for(const [key,label,unit] of [['lengthCm','长','cm'],['widthCm','宽','cm'],['heightCm','高','cm'],['weightKg','重量','kg']]){
    const wrap=element('label',{class:'measure-field'});
    wrap.append(element('span',{},label+' ('+unit+')'));
    const input=element('input',{type:'text',inputmode:'decimal',autocomplete:'off',placeholder:'选填',enterkeyhint:key==='weightKg'?'done':'next'});
    input.value=String(form[key]??'');
    input.addEventListener('input',()=>{form[key]=input.value.trim()});
    input.addEventListener('keydown',e=>{
      if(e.key!=='Enter')return;e.preventDefault();
      const others=[...group.querySelectorAll('input')];const index=others.indexOf(input);
      if(index<others.length-1)others[index+1].focus();else {input.blur();next()}
    });
    wrap.append(input);group.append(wrap);
  }
  a.append(group);
  a.append(element('p',{class:'step-hint'},'支持小数点或逗号（如 12.5 或 12,5）。留空代表未测量，不能当作 0。'));
 }
if(key==='qty'){a.append(blockTitle('实际点到多少个？','输入 0 表示已经检查、确认没有货；未盘点与 0 不同。'));a.append(entry(form.qty,'数量，例如 12',v=>form.qty=v,'number'));const plus=element('div',{class:'keys three'});for(const n of ['1','2','3','4','5','6','7','8','9','清除','0','⌫']){plus.append(element('button',{class:'key',onclick:()=>{if(n==='清除')form.qty='';else if(n==='⌫')form.qty=form.qty.slice(0,-1);else form.qty+=n;renderStep()}},n))}a.append(plus)}
if(key==='note'){a.append(blockTitle('备注（可选）','这是自由文本，例如包装破损、库存标签异常。'));const t=element('textarea',{placeholder:'输入备注，不需要可留空',rows:'4'});t.value=form.note;t.addEventListener('input',()=>form.note=t.value);a.append(t);const s=element('div',{class:'panel'});const dims=['lengthCm','widthCm','heightCm'].map(k=>form[k]||'—').join(' × ');s.append(element('h3',{},'保存前核对'),element('p',{class:'mini'},`库位：${canonical(form)}\n零件：${form.erp||form.partNo}\n长×宽×高：${dims} cm · 重量：${form.weightKg||'—'} kg\n数量：${form.qty}`));s.style.whiteSpace='pre-line';a.append(s)}
}
function validStep(){
  const k=STEPS[step];
  if(k==='floor'&&!validFloor(form.floor)){showToast('请先选择物理楼层');return false}
  if(k==='col'&&!form.col){showToast('请选择货架列');return false}
  if(k==='row'&&form.row&&!validLocation()){showToast('行号超出该货架有效范围');return false}
  if(k==='level'&&form.level&&!validLocation()){showToast('层号不属于当前物理楼层，请重新选择');return false}
  if(k==='slot'&&form.slot&&!['01','02','03','04','05'].includes(form.slot)){showToast('格号只允许01–05');return false}
  if(k==='partition'&&form.partition&&!['I','II','III'].includes(form.partition)){showToast('箱子层号只允许 I、II、III');return false}
  if(k==='part'&&!form.erp&&!form.partNo){showToast('请选择或输入 ERP No. / Part No.');return false}
  if(k==='measure'&&!validMeasurements())return false;
  if(k==='qty'&&(!/^(0|[1-9]\d*)$/.test(String(form.qty))||!Number.isSafeInteger(Number(form.qty)))){showToast('请输入非负整数数量');return false}
  return true;
}
async function next(){if(!validStep())return;if(step===STAGE.note){await saveRecord();return}step++;renderStep()}
function stopLocation(){
  if(!form.col||!validLocation()){showToast('请先选有效库位');return}
  const i=step-1;
  const from=String(form[FIELDS[i]]||'').trim()?i+1:i;
  for(let j=Math.max(0,from);j<FIELDS.length;j++)form[FIELDS[j]]='';
  resetDependentData();step=STAGE.part;renderStep();
}
function keepPrefix(){
  const prev={...form};form=empty();form.floor=Number(prev.floor)||workingFloor;
  form.col=prev.col;form.row=prev.row;lastLocation=prev;partSearch='';
  step=form.col&&form.row?STAGE.level:form.col?STAGE.row:form.floor?STAGE.col:STAGE.floor;
}
async function saveRecord(){const wasEditing=Boolean(editId);let who=$('worker').value.trim();if(!who){showToast('请先在首页填写盘点人');go('home');return}const duplicate=records.filter(r=>r.id!==editId&&r.session===$('session').value.trim()&&r.worker===who&&r.location===canonical(form)&&(!r.physicalFloor||Number(r.physicalFloor)===currentFloor())&&(((form.erp||'').trim()&&(r.erp||'').trim()&&normalizeCode(r.erp)===normalizeCode(form.erp))||((form.partNo||'').trim()&&(r.partNo||'').trim()&&normalizeCode(r.partNo)===normalizeCode(form.partNo))));if(duplicate.length&&!confirm(`提醒：你已经在同一批次记录过这个库位和零件 ${duplicate.length} 次。\n仍要保留这次新盘点吗？系统不会覆盖旧记录。`))return;let now=new Date().toISOString();let data={id:editId||crypto.randomUUID(),schemaVersion:1,session:$('session').value.trim(),worker:who,snapshotId:meta.snapshotId||'',location:canonical(form),physicalFloor:currentFloor(),locationFields:Object.fromEntries(FIELDS.map(x=>[x,form[x]])),erp:form.erp.trim(),partNo:form.partNo.trim(),partName:form.partName||'',lengthCm:measurementValue(form.lengthCm),widthCm:measurementValue(form.widthCm),heightCm:measurementValue(form.heightCm),weightKg:measurementValue(form.weightKg),qty:Number(form.qty),mode:form.mode,originalLocation:form.originalLocation.trim(),note:form.note.trim(),updatedAt:now,createdAt:editId?records.find(r=>r.id===editId)?.createdAt||now:now,deleted:false};if(editId){const original=records.find(r=>r.id===editId);if(original){data.revisions=[...(original.revisions||[]),{updatedAt:original.updatedAt,location:original.location,erp:original.erp,partNo:original.partNo,qty:original.qty,lengthCm:original.lengthCm??null,widthCm:original.widthCm??null,heightCm:original.heightCm??null,weightKg:original.weightKg??null,note:original.note}]}}await req('records','put',data);
if(!wasEditing){await req('metadata','put',{key:'lastLocation',value:{...form}});lastLocation={...form}}
editId=null;await load();
if(wasEditing){
  // Editing a historical record on another floor does NOT silently change the
  // worker's current floor or ongoing shelf location.
  form=empty();form.floor=workingFloor;
  const lastFloor=Number(lastLocation?.floor)||floorFromLevel(lastLocation?.level);
  if(lastLocation&&lastFloor===workingFloor){form.col=lastLocation.col||'';form.row=lastLocation.row||''}
  step=form.col&&form.row?STAGE.level:form.col?STAGE.row:form.floor?STAGE.col:STAGE.floor;
}else keepPrefix();
renderStep();showToast(wasEditing?'修订已保存；已恢复原工作楼层':`已保存；继续在${currentFloor()}F盘点，沿用货架列和行号`)}
function startNew(){
  const who=$('worker').value.trim();if(!who){showToast('请先填写盘点人');return}
  localStorage.setItem('worker',who);localStorage.setItem('session',$('session').value.trim());
  form=empty();form.floor=workingFloor;editId=null;partSearch='';
  if(lastLocation){
    const originalFloor=Number(lastLocation.floor)||floorFromLevel(lastLocation.level);
    if(!workingFloor||!originalFloor||workingFloor===originalFloor){
      form.col=lastLocation.col||'';form.row=lastLocation.row||'';
    }
  }
  step=form.floor?(form.col&&form.row?STAGE.level:form.col?STAGE.row:STAGE.col):STAGE.floor;
  go('count');
}
function renderHistory(){const list=$('recordsList');list.replaceChildren();for(const r of [...records].sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt))){const e=element('div',{class:'rec'}),top=element('div',{class:'top'});top.append(element('strong',{},r.location),element('b',{},r.qty+' 个'));e.append(top,element('div',{class:'meta'},`${r.erp||'-'} / ${r.partNo||'-'}\n${r.physicalFloor?r.physicalFloor+'F · ':''}${r.worker} · ${r.updatedAt.slice(0,16).replace('T',' ')}${[r.lengthCm,r.widthCm,r.heightCm,r.weightKg].some(v=>v!==null&&v!==undefined&&v!=='')?'\n长×宽×高：'+[r.lengthCm,r.widthCm,r.heightCm].map(v=>v??'—').join('×')+' cm，重量 '+(r.weightKg??'—')+' kg':''} ${r.note?'\n备注：'+r.note:''}`));e.querySelector('.meta').style.whiteSpace='pre-line';const bs=element('div',{class:'buttons'});bs.append(element('button',{onclick:()=>editRecord(r)},'修改'),element('button',{onclick:()=>deleteRecord(r)},'撤销'));e.append(bs);list.append(e)}if(!records.length)list.append(element('p',{class:'muted'},'还没有本地盘点记录。'))}
function editRecord(r){form={...empty(),...r.locationFields,floor:Number(r.physicalFloor)||floorFromLevel(r.locationFields?.level)||workingFloor,erp:r.erp,partNo:r.partNo,partName:r.partName,lengthCm:r.lengthCm??'',widthCm:r.widthCm??'',heightCm:r.heightCm??'',weightKg:r.weightKg??'',qty:String(r.qty),mode:r.mode,originalLocation:r.originalLocation,note:r.note};editId=r.id;partSearch='';step=STAGE.part;go('count');showToast('编辑旧记录：保留修订历史，不新增重复盘点')}
async function deleteRecord(r){if(!confirm(`确定撤销 ${r.location} / ${r.erp||r.partNo} / ${r.qty} 的记录？`))return;await req('records','put',{...r,deleted:true,updatedAt:new Date().toISOString()});await load();renderHistory();showToast('记录已撤销（导出时不会计算）')}
function download(name,obj){const blob=new Blob([JSON.stringify(obj,null,2)],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob);const a=element('a',{href:url,download:name});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000)}
async function exportRecords(){const raw=await all('records');const finished=await all('shelves');if(!raw.length&&!finished.length){showToast('尚无记录');return}const who=(localStorage.getItem('worker')||'employee').replace(/[^\w\u4e00-\u9fff-]/g,'_');const date=new Date().toISOString().slice(0,10);download(`stockcount_${date}_${who}.json`,{format:'hangcha-stockcount-export',version:2,exportedAt:new Date().toISOString(),snapshotId:meta.snapshotId||'',records:raw,shelfCompletions:finished});showToast('已生成 JSON 文件，请通过手机分享给电脑')}
function currentShelf(){const c=form.col||'';const r=form.row||'';return c&&r?c+r:''}
async function completeShelf(){const shelf=currentShelf();if(!shelf){showToast('请先选择货架列和行号');return}const worker=$('worker').value.trim();const session=$('session').value.trim();if(!worker){showToast('请先填写盘点人');return}if(!confirm(`确认 ${currentFloor()}F · ${shelf} 的盘点已完成？\n这只是完成标记，不代表所有货物数量正确，也不阻止后续补盘。`))return;const id=crypto.randomUUID(),now=new Date().toISOString();await req('shelves','put',{id,shelf,physicalFloor:currentFloor(),worker,session,snapshotId:meta.snapshotId||'',completedAt:now,updatedAt:now,deleted:false});await load();showToast(`${currentFloor()}F · ${shelf} 已标记完成，导出时会一并提交`)}
function renderShelves(){const list=$('shelfList');if(!list)return;list.replaceChildren();for(const t of shelves.filter(x=>!x.deleted).sort((a,b)=>b.completedAt.localeCompare(a.completedAt)).slice(0,30)){const d=element('div',{class:'rec'});d.append(element('strong',{},`${t.physicalFloor?t.physicalFloor+'F · ':''}${t.shelf}`),element('p',{class:'mini muted'},`${t.worker} · ${t.session} · ${t.completedAt.slice(0,16).replace('T',' ')}`));d.append(element('button',{class:'tiny',onclick:async()=>{if(!confirm(`撤销 ${t.shelf} 的已完成标记？`))return;await req('shelves','put',{...t,deleted:true,updatedAt:new Date().toISOString()});await load();renderShelves()}},'撤销标记'));list.append(d)}}
async function importCatalog(file){if(!file)return;try{const data=JSON.parse(await file.text());if(data.format!=='hangcha-stockcount-catalog'||!Array.isArray(data.items))throw Error('库存文件格式不正确，请用电脑工具生成');if(data.items.length>120000)throw Error('库存行数超出安全限制');if(!confirm(`导入 ${data.items.length} 条库存记录？将替换手机当前库存基准，但不删除已盘点数据。`))return;const tx=db.transaction(['catalog','metadata'],'readwrite');tx.objectStore('catalog').clear();data.items.forEach((r,i)=>tx.objectStore('catalog').put({key:i,erp:String(r.erp||''),partNo:String(r.partNo||''),name:String(r.name||''),location:String(r.location||'').trim().toUpperCase(),locations:Array.isArray(r.locations)?r.locations.map(x=>String(x).trim().toUpperCase()):[],bookQty:r.bookQty??null,referenceDimensions:String(r.referenceDimensions||''),referenceWeight:String(r.referenceWeight||'')}));tx.objectStore('metadata').put({key:'catalogName',value:file.name});tx.objectStore('metadata').put({key:'snapshotId',value:data.snapshotId||''});await new Promise((res,rej)=>{tx.oncomplete=res;tx.onerror=()=>rej(tx.error)});await load();showToast('库存基准已缓存在手机中，可离线联想')}catch(e){alert('导入失败：'+e.message)}}
async function init(){try{db=await openDB()}catch(e){alert('无法打开手机本地数据库（IndexedDB）。请确认不是无痕浏览，并在普通 Safari/Chrome 中重试。错误：'+(e?.message||e));return}try{await load()}catch(e){console.error('StockCount initialization failed:',e);alert('盘库 App 初始化失败（不一定是 IndexedDB 问题），请先备份已有记录，再检查版本或联系管理员。错误：'+(e?.message||e));return}for(const el of document.querySelectorAll('nav button'))el.addEventListener('click',()=>go(el.dataset.view));$('start').onclick=startNew;$('catalogFile').onchange=e=>importCatalog(e.target.files[0]);$('nextBtn').onclick=next;$('completeShelf').onclick=completeShelf;$('skipBtn').onclick=()=>{if(step===STAGE.measure){for(const k of ['lengthCm','widthCm','heightCm','weightKg'])form[k]='';step=STAGE.qty;renderStep()}else stopLocation()};$('backBtn').onclick=backStep;$('changeFloor').onclick=()=>jumpToStage(STAGE.floor);for(const id of ['exportHome','exportHistory','exportSettings'])$(id).onclick=exportRecords;$('persistBtn').onclick=async()=>{if(!navigator.storage?.persist){$('persistStatus').textContent='当前浏览器不支持存储持久化请求';return}const yes=await navigator.storage.persist();$('persistStatus').textContent=yes?'浏览器已允许持久化存储（仍建议备份）':'浏览器未授予持久化，请频繁导出备份'};$('clearRecords').onclick=async()=>{if(!confirm('危险：这将删除本机全部盘点记录。确定已经备份到电脑？'))return;if(prompt('再次输入 DELETE 确认')!=='DELETE')return;const tx=db.transaction(['records','shelves'],'readwrite');tx.objectStore('records').clear();tx.objectStore('shelves').clear();await new Promise((r,j)=>{tx.oncomplete=r;tx.onerror=j});await load();showToast('本机盘点记录已清空')};$('worker').addEventListener('change',()=>localStorage.setItem('worker',$('worker').value.trim()));$('session').addEventListener('change',()=>localStorage.setItem('session',$('session').value.trim()));if('serviceWorker'in navigator&&location.protocol!=='file:')navigator.serviceWorker.register('./sw.js').catch(()=>{});}
init();
