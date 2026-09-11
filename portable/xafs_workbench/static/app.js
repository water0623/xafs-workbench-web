const colors=['#075985','#c2410c','#047857','#7c3aed'];
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
let lastFit=null;
let lastBatch=null;
let lastAthena=null;
let processController=null;
let e0Timer=null;
let rememberedShift=Number(localStorage.getItem('xafs.energyShift')||0);
let pickingSamplePeak=false;
let lastRData=null;
let lastMulti=null;
let calibratedS02=Number(localStorage.getItem('xafs.calibratedS02'));
let generatedFeff=null;
let fitHistory=[];
let backendIsRemote=false;
let backendConnected=false;
const isGitHubPages=location.hostname.endsWith('.github.io');
const queryApiBase=new URLSearchParams(location.search).get('api');
const publicLanding=isGitHubPages&&!queryApiBase;
let apiBase=normalizeApiBase(queryApiBase||'');
let accessToken=sessionStorage.getItem('xafs.accessToken')||'';
if(isGitHubPages&&!queryApiBase)accessToken='';

function normalizeApiBase(value){return String(value||'').trim().replace(/\/+$/,'')}
function apiUrl(path){
  if(!path||/^(?:https?:|blob:|data:)/i.test(path))return path;
  return apiBase?`${apiBase}${path.startsWith('/')?'':'/'}${path}`:path;
}
function apiIsCrossOrigin(){try{return Boolean(apiBase)&&new URL(apiBase).origin!==location.origin}catch{return true}}

function message(id,text,type=''){const el=$(id);el.textContent=text;el.className=`message ${type}`}
function metrics(id,items){$(id).innerHTML=items.map(([k,v])=>`<div class="metric"><span>${k}</span><b>${v}</b></div>`).join('')}
function escapeHtml(s){return String(s).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}

function nearestIndex(values,target){
  let lo=0,hi=values.length-1;
  while(lo<hi){const mid=Math.floor((lo+hi)/2);if(values[mid]<target)lo=mid+1;else hi=mid}
  if(lo>0&&Math.abs(values[lo-1]-target)<Math.abs(values[lo]-target))return lo-1;
  return lo;
}

function addPlotInteraction(root,svg,series,scale){
  const NS='http://www.w3.org/2000/svg',layer=document.createElementNS(NS,'g');
  layer.setAttribute('class','cursor-layer');layer.style.display='none';
  const cross=document.createElementNS(NS,'line');cross.setAttribute('class','cursor-crosshair');cross.setAttribute('y1',scale.top);cross.setAttribute('y2',scale.bottom);layer.appendChild(cross);
  const dots=document.createElementNS(NS,'g'),tip=document.createElementNS(NS,'g');layer.appendChild(dots);layer.appendChild(tip);svg.appendChild(layer);
  let pinned=false;
  function update(event){
    const rect=svg.getBoundingClientRect(),sx=(event.clientX-rect.left)/rect.width*scale.width;
    if(sx<scale.left||sx>scale.right)return;
    const xValue=scale.xmin+(sx-scale.left)/(scale.right-scale.left)*(scale.xmax-scale.xmin);
    cross.setAttribute('x1',sx);cross.setAttribute('x2',sx);dots.replaceChildren();tip.replaceChildren();
    const readings=[];
    for(const [i,s] of series.entries()){
      const idx=nearestIndex(s.x,xValue),x=s.x[idx],y=s.y[idx];if(!Number.isFinite(y))continue;
      readings.push({name:s.name,x,y,color:s.color||colors[i%colors.length]});
      const dot=document.createElementNS(NS,'circle');dot.setAttribute('cx',scale.X(x));dot.setAttribute('cy',scale.Y(y));dot.setAttribute('r','4');dot.setAttribute('fill',s.color||colors[i%colors.length]);dot.setAttribute('stroke','#fff');dot.setAttribute('stroke-width','1.5');dots.appendChild(dot);
    }
    if(!readings.length)return;
    const lines=[`${scale.xlabel}: ${readings[0].x.toFixed(3)}`,...readings.map(r=>`${r.name}: ${Number(r.y).toPrecision(7)}`)];
    const boxW=Math.min(280,Math.max(170,Math.max(...lines.map(t=>t.length))*7.1+20)),boxH=12+lines.length*18;
    let boxX=sx+12;if(boxX+boxW>scale.right)boxX=sx-boxW-12;let boxY=scale.top+10;
    const bg=document.createElementNS(NS,'rect');bg.setAttribute('x',boxX);bg.setAttribute('y',boxY);bg.setAttribute('width',boxW);bg.setAttribute('height',boxH);bg.setAttribute('rx','6');bg.setAttribute('class','cursor-tooltip-bg');tip.appendChild(bg);
    lines.forEach((line,i)=>{const t=document.createElementNS(NS,'text');t.setAttribute('x',boxX+10);t.setAttribute('y',boxY+18+i*18);t.setAttribute('class','cursor-tooltip-text');t.textContent=line;tip.appendChild(t)});
    layer.style.display='block';
  }
  svg.addEventListener('mousemove',event=>{if(!pinned)update(event)});
  svg.addEventListener('click',event=>{
    const rect=svg.getBoundingClientRect(),sx=(event.clientX-rect.left)/rect.width*scale.width;
    const picked=scale.xmin+(sx-scale.left)/(scale.right-scale.left)*(scale.xmax-scale.xmin);
    if(sx>=scale.left&&sx<=scale.right&&typeof scale.onPick==='function')scale.onPick(picked);
    pinned=!pinned;update(event);svg.classList.toggle('plot-pinned',pinned);
  });
  svg.addEventListener('mouseleave',()=>{if(!pinned)layer.style.display='none'});
  root.title='移动鼠标查看实时数值；单击锁定或解除读数';
}

function drawPlot(id,series,xlabel,ylabel,options={}){
  const root=$(id), W=800,H=300,p={l:62,r:20,t:20,b:45};
  const valid=series.filter(s=>s.x?.length&&s.y?.length);
  if(!valid.length){root.innerHTML='<p class="hint">无可绘制数据</p>';return}
  const xs=valid.flatMap(s=>s.x),ys=valid.flatMap(s=>s.y).filter(Number.isFinite);
  let xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
  if(Number.isFinite(options.ymin))ymin=Number(options.ymin);if(Number.isFinite(options.ymax))ymax=Number(options.ymax);
  if(ymin===ymax){ymin-=1;ymax+=1}
  const X=x=>p.l+(x-xmin)/(xmax-xmin)*(W-p.l-p.r),Y=y=>H-p.b-(y-ymin)/(ymax-ymin)*(H-p.t-p.b);
  const bands=(options.bands||[]).map(b=>{const x1=X(Math.max(xmin,b.from)),x2=X(Math.min(xmax,b.to));return x2>x1?`<rect x="${x1}" y="${p.t}" width="${x2-x1}" height="${H-p.t-p.b}" fill="${b.color}" opacity="${b.opacity||.16}"/><text class="plot-note" x="${(x1+x2)/2}" y="${p.t+14}" text-anchor="middle">${escapeHtml(b.label||'')}</text>`:''}).join('');
  const vlines=(options.vlines||[]).filter(v=>v.x>=xmin&&v.x<=xmax).map(v=>`<line x1="${X(v.x)}" y1="${p.t}" x2="${X(v.x)}" y2="${H-p.b}" stroke="${v.color||'#b91c1c'}" stroke-width="1.4" stroke-dasharray="5 4"/><text class="plot-note" x="${X(v.x)+5}" y="${p.t+29}">${escapeHtml(v.label||'')}</text>`).join('');
  const paths=valid.map((s,i)=>{const n=Math.min(s.x.length,s.y.length);let d='';for(let j=0;j<n;j++){if(!Number.isFinite(s.y[j]))continue;d+=`${d?'L':'M'}${X(s.x[j]).toFixed(1)},${Y(s.y[j]).toFixed(1)}`}return `<path d="${d}" fill="none" stroke="${s.color||colors[i%colors.length]}" stroke-width="1.6"/>`}).join('');
  const ticks=[0,.25,.5,.75,1];
  const grid=ticks.map(t=>{const x=p.l+t*(W-p.l-p.r),y=p.t+t*(H-p.t-p.b);return `<line x1="${x}" y1="${p.t}" x2="${x}" y2="${H-p.b}" stroke="#e2e8f0"/><text x="${x}" y="${H-20}" text-anchor="middle">${(xmin+t*(xmax-xmin)).toFixed(2)}</text><line x1="${p.l}" y1="${y}" x2="${W-p.r}" y2="${y}" stroke="#e2e8f0"/><text x="${p.l-8}" y="${y+4}" text-anchor="end">${(ymax-t*(ymax-ymin)).toPrecision(3)}</text>`}).join('');
  const legend=valid.map((s,i)=>`<span><i class="swatch" style="background:${s.color||colors[i%colors.length]}"></i>${escapeHtml(s.name)}</span>`).join('')+'<span class="interaction-hint">⌖ 移动查看数值 · 单击锁定</span>';
  root.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img">${bands}<g font-size="11" fill="#64748b">${grid}<text x="${W/2}" y="${H-3}" text-anchor="middle">${xlabel}</text><text transform="translate(14 ${H/2}) rotate(-90)" text-anchor="middle">${ylabel}</text></g>${vlines}${paths}</svg><div class="legend">${legend}</div>`;
  addPlotInteraction(root,root.querySelector('svg'),valid,{width:W,left:p.l,right:W-p.r,top:p.t,bottom:H-p.b,xmin,xmax,X,Y,xlabel,onPick:options.onPick});
}

async function apiFetch(url,opts={}){if(publicLanding)throw new Error('公开页不执行本机计算。请先启动 Windows 桌面版，再点击“打开本机工作台”。');const headers=new Headers(opts.headers||{});if(accessToken)headers.set('X-XAFS-Access-Token',accessToken);return fetch(apiUrl(url),{...opts,headers})}
async function jsonFetch(url,opts={}){const res=await apiFetch(url,opts);let data;try{data=await res.json()}catch{throw new Error(`后端返回了非 JSON 响应（HTTP ${res.status}）`)}if(!res.ok)throw new Error(data.error||`HTTP ${res.status}`);return data}
async function downloadFromApi(url,fallbackName='download'){const res=await apiFetch(url);if(!res.ok){let detail='';try{detail=(await res.json()).error||''}catch{}throw new Error(detail||`下载失败（HTTP ${res.status}）`)}const blob=await res.blob(),disposition=res.headers.get('Content-Disposition')||'',match=disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)/i),name=match?decodeURIComponent(match[1]):fallbackName;const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
async function fitFetchWithRecovery(formData){try{return await jsonFetch('/api/artemis',{method:'POST',body:formData})}catch(err){if(!String(err.message).toLowerCase().includes('fetch'))throw err;message('#fit-message','本地服务连接瞬时中断，正在检查并自动重试一次…');await new Promise(resolve=>setTimeout(resolve,1200));await jsonFetch('/api/status');return jsonFetch('/api/artemis',{method:'POST',body:formData})}}

function renderNativeTools(nativeTools){
  const toolList=$('#native-tool-list');if(!toolList)return;
  toolList.innerHTML=Object.values(nativeTools).map(tool=>{
    const stateClass=tool.running?'running':(tool.available?'available':'missing');
    const detail=tool.running?`正在运行 · PID ${tool.process_ids.join(', ')}`:(tool.available?`已安装 · ${tool.source}`:'尚未检测到本机程序');
    const disabled=tool.running||!tool.available||apiIsCrossOrigin()||backendIsRemote;
    const label=tool.running?'已运行':'启动';
    const title=(apiIsCrossOrigin()||backendIsRemote)&&!tool.running?'远程客户端不能启动服务机程序；请在服务机本地启动':'';
    return `<article class="native-tool ${stateClass}"><div><strong>${escapeHtml(tool.label)}</strong><span>${escapeHtml(tool.role)}</span><small>${escapeHtml(detail)}</small></div><div class="toolbar"><a class="secondary" href="${escapeHtml(tool.homepage)}" target="_blank" rel="noopener">官方主页</a><button class="secondary native-launch" data-tool="${escapeHtml(tool.name)}" type="button" title="${escapeHtml(title)}" ${disabled?'disabled':''}>${label}</button></div></article>`;
  }).join('');
}

function renderDisconnectedNativeTools(detail='请在本机或局域网工作台中查看真实状态'){
  const tools=[
    ['Athena (Demeter)','Athena 数据处理'],
    ['Artemis (Demeter)','FEFF/IFEFFIT 路径拟合'],
    ['Hephaestus (Demeter)','元素与吸收边数据'],
    ['HAMA Fortran','Morlet 小波变换'],
  ];
  $('#native-tool-list').innerHTML=tools.map(([label,role])=>`<article class="native-tool missing"><div><strong>${label}</strong><span>${role}</span><small>${escapeHtml(detail)}</small></div></article>`).join('');
}

function lockPublicInterface(){
  $$('.panel').forEach(panel=>{
    panel.classList.add('public-locked');
    panel.querySelectorAll('input,select,textarea,button').forEach(control=>{control.disabled=true});
  });
}

async function refreshNativeTools(){
  if(!backendConnected){await boot();return}
  const result=await jsonFetch('/api/native/status');renderNativeTools(result.tools||{});
  const running=Object.values(result.tools||{}).filter(tool=>tool.running);
  message('#native-tool-message',running.length?`已检测到 ${running.length} 个正在运行的原生程序：${running.map(tool=>tool.label).join('、')}`:'没有检测到正在运行的原生程序',running.length?'ok':'');
}

$$('.tab').forEach(b=>b.onclick=()=>{$$('.tab,.panel').forEach(x=>x.classList.remove('active'));b.classList.add('active');$('#'+b.dataset.tab).classList.add('active')});

async function loadRecentFits(){
  const root=$('#recent-fit-list');
  if(!root)return;
  try{
    const data=await jsonFetch('/api/artemis/results');
    const rows=data.results||[];
    root.className='recent-fit-list';
    root.innerHTML=rows.length?rows.map(row=>`<div class="recent-fit-row"><span><strong>${escapeHtml(row.sample||row.result_id)}</strong><small>${escapeHtml(row.created_at||'')} · ${escapeHtml(row.backend||'')}</small></span><span class="toolbar"><button class="secondary api-download" data-url="${escapeHtml(row.data_download_url)}" data-name="fit-data.csv" type="button">数据 CSV</button><button class="secondary api-download" data-url="${escapeHtml(row.wavelet_download_url)}" data-name="wavelet.zip" type="button">小波 ZIP</button><button class="primary api-download" data-url="${escapeHtml(row.download_url)}" data-name="fit-result.zip" type="button">完整结果</button></span></div>`).join(''):'尚无已保存记录。';
  }catch(err){root.className='message error';root.textContent=`读取历史记录失败：${err.message}`}
}

async function boot(){
  backendConnected=false;
  if(isGitHubPages)$('#public-launch').hidden=false;
  $('#api-base-url').value=apiBase;
  $('#api-access-token').value=accessToken;
  if(publicLanding){
    lockPublicInterface();
    renderDisconnectedNativeTools();
    $('#refresh-native-tools').disabled=true;
    $('#backend-status').textContent='公开说明页 · 未连接原生计算服务';
    $('#backend-status').classList.add('warn');
    message('#api-base-message','桌面版运行后，点击上方“打开本机工作台”即可自动读取四个程序的安装与运行状态。');
    message('#native-tool-message','当前为公开入口：计算控件已锁定，不会向 GitHub Pages 提交实验数据。');
    message('#athena-message','公开页不执行计算，因此不会再出现 HTTP 405。请进入本机或局域网工作台后处理数据。');
    return;
  }
  $('#refresh-native-tools').disabled=false;
  message('#api-base-message',`正在连接 ${apiBase||location.origin}…`);
  const status=await jsonFetch('/api/status');
  const files=await jsonFetch('/api/datasets');
  backendConnected=true;
  const st=$('#backend-status');
  const nativeTools=status.native_tools||{},nativeReady=status.native_mode_ready;
  backendIsRemote=Boolean(status.remote_client);
  st.textContent=nativeReady?'Demeter / IFEFFIT 数据处理就绪 · XrayLarch 已禁用':'未检测到 Demeter / IFEFFIT 后端';
  st.classList.toggle('warn',!nativeReady||!status.artemis_ready);
  message('#api-base-message',`已连接计算服务：${apiBase||location.origin} · ${status.athena_backend}`,'ok');
  renderNativeTools(nativeTools);
  $$('.dataset-select').forEach(sel=>sel.innerHTML=files.map(f=>`<option>${escapeHtml(f)}</option>`).join(''));
  $('#batch-datasets').innerHTML=files.map(f=>`<option>${escapeHtml(f)}</option>`).join('');
  $('#athena-multi-datasets').innerHTML=files.map(f=>`<option>${escapeHtml(f)}</option>`).join('');
  $('[name="ref1"]').value='Ir-foil';$('[name="ref2"]').value='IrO2_foil.xdi';
  $('#reference-dataset').value=files.includes('Ir-foil')?'Ir-foil':files[0];
  $('#remembered-shift').value=rememberedShift.toFixed(2);$('#batch-energy-shift').value=rememberedShift.toFixed(2);
  $('#saved-s02').textContent=Number.isFinite(calibratedS02)?calibratedS02.toFixed(4):'尚未标定';
  await loadRecentFits();
}

$('#save-api-base').onclick=()=>{
  apiBase=normalizeApiBase($('#api-base-url').value);
  accessToken=$('#api-access-token').value.trim();
  localStorage.setItem('xafs.apiBase',apiBase);
  if(accessToken)sessionStorage.setItem('xafs.accessToken',accessToken);else sessionStorage.removeItem('xafs.accessToken');
  boot().catch(err=>{message('#api-base-message',`连接失败：${err.message}`,'error');message('#athena-message','请确认后端已启动，并检查后端地址。','error')});
};
$('#use-page-api').onclick=()=>{if(isGitHubPages){message('#api-base-message','GitHub Pages 不包含计算服务，请填写已配置 HTTPS 的后端域名。','error');return}$('#api-base-url').value=location.origin;$('#save-api-base').click()};

document.addEventListener('click',async event=>{
  const download=event.target.closest('.api-download');
  if(download){download.disabled=true;try{await downloadFromApi(download.dataset.url,download.dataset.name)}catch(err){message('#fit-message',err.message,'error')}finally{download.disabled=false}return}
  const button=event.target.closest('.native-launch');if(!button)return;
  button.disabled=true;message('#native-tool-message',`正在启动 ${button.dataset.tool}…`);
  try{const result=await jsonFetch('/api/native/launch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tool:button.dataset.tool})});message('#native-tool-message',`${result.tool.label} 已启动。`,'ok');setTimeout(()=>refreshNativeTools().catch(()=>{}),1500)}
  catch(err){message('#native-tool-message',err.message,'error')}
  finally{button.disabled=false}
});
function handleBootFailure(err){
  backendConnected=false;
  renderDisconnectedNativeTools();
  $('#backend-status').textContent='尚未连接本机计算服务';
  $('#backend-status').classList.add('warn');
  message('#api-base-message',err.message,'error');
  message('#native-tool-message','启动本机 XAFS Workbench 后，点击“重新检测本机服务与软件状态”。');
  message('#athena-message','计算后端尚未连接，请先启动本机 XAFS Workbench 服务。','error');
  if(!isGitHubPages)$('#manual-backend-connector').hidden=false;
}
$('#refresh-native-tools').onclick=()=>refreshNativeTools().catch(handleBootFailure);
setInterval(()=>{if(backendConnected)refreshNativeTools().catch(()=>{})},8000);

async function runProcess(form,quiet=false){
  if(processController)processController.abort();
  processController=new AbortController();
  if(!quiet)message('#athena-message','正在处理…');
  try{
    const d=await jsonFetch('/api/athena',{method:'POST',body:new FormData(form),signal:processController.signal});
    lastAthena=d;$('#download-energy').hidden=false;$('#download-project').hidden=false;$('#send-to-fit').hidden=false;updateFitRangeMode();
    $('#fit-source').innerHTML=`<strong>已自动接收：</strong>${escapeHtml(d.source_name)} · E₀ ${d.e0.toFixed(2)} eV · ΔE ${Number(d.energy_shift).toFixed(3)} eV · kmax ${d.kmax_used.toFixed(2)} Å⁻¹`;
    message('#athena-message',`${d.source_name} · ${d.signal_description} · ${d.backend}`,'ok');
    metrics('#athena-metrics',[['E₀',`${d.e0.toFixed(2)} eV`],['Edge step',d.edge_step.toPrecision(5)],['归一化',d.normalization_mode],['白线',`${d.white_line_energy.toFixed(2)} eV / ${d.white_line_height.toFixed(3)}`],['清除点数',d.removed_points],['kmax',`${d.kmax_used.toFixed(2)} Å⁻¹`],['后端',d.backend]]);
    const formData=new FormData(form),e0=d.e0,pre1=Number(formData.get('pre1')),pre2=Number(formData.get('pre2')),norm1=Number(formData.get('norm1')),norm2=Number(formData.get('norm2')),kmin=Number(formData.get('kmin')),kmax=Number(formData.get('kmax'));
    $('#e0-live-value').textContent=`${e0.toFixed(1)} eV`;
    const slider=$('#e0-slider');slider.min=Math.floor(Math.min(...d.energy));slider.max=Math.ceil(Math.max(...d.energy));
    if(formData.get('auto_e0')){$('#e0-number').value=e0.toFixed(2);slider.value=e0}
    $('#energy-ranges').innerHTML=`<span class="range-chip"><i class="range-dot" style="background:#38bdf8"></i>Pre-edge ${(e0+pre1).toFixed(1)}–${(e0+pre2).toFixed(1)} eV</span><span class="range-chip"><i class="range-dot" style="background:#f59e0b"></i>Normalization ${(e0+norm1).toFixed(1)}–${(e0+norm2).toFixed(1)} eV</span><span class="range-chip"><i class="range-dot" style="background:#b91c1c"></i>E₀ ${e0.toFixed(2)} eV</span>`;
    const shownNorm=d.display_norm||d.flat||d.norm,normLabel=d.normalization_mode==='Athena flattened'?'normalized · flattened':'normalized';
    drawPlot('#plot-energy',[{name:'raw μ(E)',x:d.energy,y:d.mu},{name:normLabel,x:d.energy,y:shownNorm},{name:'pre-edge',x:d.energy,y:d.pre_edge},{name:'post-edge',x:d.energy,y:d.post_edge}], 'Energy (eV)','absorption',{bands:[{from:e0+pre1,to:e0+pre2,label:'Pre-edge',color:'#38bdf8'},{from:e0+norm1,to:e0+norm2,label:'Normalization',color:'#f59e0b'}],vlines:[{x:e0,label:`E₀ ${e0.toFixed(1)} eV`}],onPick:x=>{if(!pickingSamplePeak)return;const rawX=x-Number(d.energy_shift||0);$('#sample-peak').value=rawX.toFixed(2);pickingSamplePeak=false;$('#pick-sample-peak').classList.remove('pick-active');message('#alignment-message',`已从图中选取样品原始峰 ${rawX.toFixed(2)} eV；点击“计算并应用峰位移”。`,'ok')}});
    drawPlot('#plot-derivative',[{name:'dμ/dE',x:d.energy,y:d.dmude}], 'Energy (eV)','d(normalized μ)/dE',{vlines:[{x:e0,label:`E₀ ${e0.toFixed(1)} eV`} ]});
    drawPlot('#plot-k',[{name:'k²χ(k)',x:d.k,y:d.chi.map((v,i)=>v*d.k[i]**2)},{name:'window',x:d.k,y:d.kwin}], 'k (Å⁻¹)','weighted χ(k)',{bands:[{from:kmin,to:kmax,label:`k=${kmin}–${kmax} Å⁻¹`,color:'#a78bfa'}]});
    lastRData=d;renderRPlot();
  }catch(err){if(err.name!=='AbortError')message('#athena-message',err.message,'error')}
}

$('#process-form').onsubmit=e=>{
  e.preventDefault();runProcess(e.target);
};

const e0Number=$('#e0-number'),e0Slider=$('#e0-slider'),autoE0=$('[name="auto_e0"]');
function scheduleE0(value){
  const numeric=Number(value);if(!Number.isFinite(numeric)||numeric<=0)return;
  e0Number.value=numeric.toFixed(1);e0Slider.value=numeric;$('#e0-live-value').textContent=`${numeric.toFixed(1)} eV`;
  clearTimeout(e0Timer);e0Timer=setTimeout(()=>runProcess($('#process-form'),true),300);
}
e0Slider.addEventListener('input',e=>{if(autoE0.checked)autoE0.checked=false;scheduleE0(e.target.value)});
e0Number.addEventListener('input',e=>{if(autoE0.checked)autoE0.checked=false;scheduleE0(e.target.value)});
autoE0.addEventListener('change',()=>{e0Slider.disabled=autoE0.checked;e0Number.disabled=autoE0.checked;if(autoE0.checked)runProcess($('#process-form'),true)});

function limitSeries(x,y,max){const indices=x.map((value,index)=>value<=max?index:-1).filter(index=>index>=0);return {x:indices.map(index=>x[index]),y:indices.map(index=>y[index])}}
function renderRPlot(){
  if(!lastRData)return;const max=Number($('#r-plot-max').value||6),series=[];
  if($('#show-r-mag').checked){const s=limitSeries(lastRData.r,lastRData.chir_mag,max);series.push({name:'|χ(R)|',...s})}
  if($('#show-r-real').checked){const s=limitSeries(lastRData.r,lastRData.chir_re,max);series.push({name:'real χ(R)',...s})}
  if($('#show-r-imag').checked){const s=limitSeries(lastRData.r,lastRData.chir_im,max);series.push({name:'imaginary χ(R)',...s})}
  const onlyMagnitude=series.length===1&&$('#show-r-mag').checked,kw=Number(new FormData($('#process-form')).get('kweight'));
  drawPlot('#plot-r',series,'Radial distance R (Å)',`χ(R) (Å⁻${kw+1})`,onlyMagnitude?{ymin:0}:{});
}
['#show-r-mag','#show-r-real','#show-r-imag','#r-plot-max'].forEach(id=>$(id).addEventListener('change',renderRPlot));

$('#run-athena-multi').onclick=async()=>{
  const selected=[...$('#athena-multi-datasets').selectedOptions].map(option=>option.value),files=[...$('#athena-multi-files').files];
  if(!selected.length&&!files.length){message('#multi-message','请选择或上传至少一条数据。','error');return}
  const fd=new FormData($('#process-form'));fd.delete('data_file');fd.set('datasets',JSON.stringify(selected));files.forEach(file=>fd.append('data_files',file));
  message('#multi-message',`正在处理 ${selected.length+files.length} 条数据…`);
  try{
    const d=await jsonFetch('/api/athena/multi',{method:'POST',body:fd});lastMulti=d;
    $('#multi-results').hidden=false;message('#multi-message',`已完成 ${d.series.length} 条数据，处理参数与当前 Athena 设置一致。`,'ok');
    $('#multi-table').innerHTML=table(d.series.map(s=>({sample:s.source_name,E0_eV:s.e0,edge_step:s.edge_step,shift_eV:s.energy_shift,kmax_A_1:s.kmax_used})),['sample','E0_eV','edge_step','shift_eV','kmax_A_1']);
    drawPlot('#plot-multi-energy',d.series.map((s,i)=>({name:s.source_name,x:s.energy,y:s.normalized,color:colors[i%colors.length]})),'Energy (eV)',d.normalization_mode);
    drawPlot('#plot-multi-k',d.series.map((s,i)=>({name:s.source_name,x:s.k,y:s.chi_weighted,color:colors[i%colors.length]})),'k (Å⁻¹)',`k${d.kweight}χ(k)`);
    const rmax=Number($('#r-plot-max').value||6),rSeries=d.series.map((s,i)=>({name:s.source_name,...limitSeries(s.r,s.chir_mag,rmax),color:colors[i%colors.length]}));
    drawPlot('#plot-multi-r',rSeries,'Radial distance R (Å)',`|χ(R)| (Å⁻${Number(d.kweight)+1})`,{ymin:0});
  }catch(err){message('#multi-message',err.message,'error')}
};
$('#clear-athena-multi').onclick=()=>{lastMulti=null;$('#multi-results').hidden=true;$('#multi-table').innerHTML='';message('#multi-message','已清除叠加结果。','ok')};

$('#pick-sample-peak').onclick=()=>{pickingSamplePeak=true;$('#pick-sample-peak').classList.add('pick-active');message('#alignment-message','请在右侧 μ(E) 图中单击需要迁移的样品峰。')};

$('#calculate-alignment').onclick=async()=>{
  message('#alignment-message','正在寻找标准峰和样品峰…');
  try{
    const fd=new FormData($('#process-form'));
    fd.set('reference_dataset',$('#reference-dataset').value);fd.set('peak_mode',$('#peak-mode').value);
    fd.set('reference_peak',$('#reference-peak').value);fd.set('sample_peak',$('#sample-peak').value);
    const d=await jsonFetch('/api/align',{method:'POST',body:fd});
    $('#reference-peak').value=d.reference_peak_eV.toFixed(2);$('#sample-peak').value=d.sample_peak_eV.toFixed(2);
    const shiftInput=$('[name="energy_shift"]');shiftInput.value=d.energy_shift_eV.toFixed(3);
    autoE0.checked=false;e0Number.disabled=false;e0Slider.disabled=false;e0Number.value=d.aligned_e0_eV.toFixed(2);e0Slider.value=d.aligned_e0_eV;
    rememberedShift=d.energy_shift_eV;localStorage.setItem('xafs.energyShift',String(rememberedShift));
    $('#remembered-shift').value=rememberedShift.toFixed(3);$('#batch-energy-shift').value=rememberedShift.toFixed(3);
    const peakLabel=d.peak_mode==='e0'?'E₀ / 导数峰':'白线峰';
    message('#alignment-message',`${d.sample_name} 的 ${peakLabel} ${d.sample_peak_eV.toFixed(2)} eV → ${d.reference_peak_eV.toFixed(2)} eV；已应用并记住 ΔE=${d.energy_shift_eV.toFixed(3)} eV。`,'ok');
    $('#alignment-summary').innerHTML=`<span class="range-chip">标准：${escapeHtml(d.reference_name)} · ${d.reference_peak_eV.toFixed(2)} eV · 峰强 ${d.reference_peak_height.toFixed(4)}</span><span class="range-chip">样品原峰：${d.sample_peak_eV.toFixed(2)} eV · 峰强 ${d.sample_peak_height.toFixed(4)}</span><span class="range-chip">ΔE：${d.energy_shift_eV.toFixed(3)} eV</span>`;
    drawPlot('#plot-alignment',[{name:`标准 ${d.reference_name}`,x:d.reference.energy,y:d.reference.norm},{name:`对齐后 ${d.sample_name}`,x:d.aligned.energy,y:d.aligned.norm}], 'Energy (eV)','normalized μ(E)',{vlines:[{x:d.reference_peak_eV,label:`目标峰 ${d.reference_peak_eV.toFixed(2)} eV`} ]});
    await runProcess($('#process-form'),true);
  }catch(err){message('#alignment-message',err.message,'error')}
};

$('#remember-shift').onclick=()=>{
  rememberedShift=Number($('[name="energy_shift"]').value||0);localStorage.setItem('xafs.energyShift',String(rememberedShift));
  $('#remembered-shift').value=rememberedShift.toFixed(3);$('#batch-energy-shift').value=rememberedShift.toFixed(3);message('#alignment-message',`已记住 ΔE=${rememberedShift.toFixed(3)} eV，可用于后续样品和批处理。`,'ok');
};

$('#reuse-shift').onclick=()=>{
  $('[name="energy_shift"]').value=rememberedShift.toFixed(3);$('#batch-energy-shift').value=rememberedShift.toFixed(3);
  message('#alignment-message',`已将记忆位移 ΔE=${rememberedShift.toFixed(3)} eV 应用于当前样品。`,'ok');runProcess($('#process-form'),true);
};

$('#send-to-fit').onclick=()=>{
  if(!lastAthena)return;
  const fitTab=$('.tab[data-tab="artemis"]');fitTab.click();
  $('#fit-source').innerHTML=`<strong>已接收：</strong>${escapeHtml(lastAthena.source_name)} · E₀ ${lastAthena.e0.toFixed(2)} eV · ΔE ${Number(lastAthena.energy_shift).toFixed(3)} eV · kmax ${lastAthena.kmax_used.toFixed(2)} Å⁻¹`;
  message('#fit-message','标准化数据及 Athena 参数已传递；选择 FEFF 路径后即可拟合。','ok');
};

$('#fit-form').onsubmit=async e=>{
  e.preventDefault();clearFitErrors();if(!validateFitForm())return;message('#fit-message','正在执行 FEFFIT…');
  try{
    if($('#fit-mode').value==='unknown'&&Number.isFinite(calibratedS02)){setFitValue('s02',calibratedS02);setFitValue('s02_vary',false);setFitValue('s02_source','standard_calibration')}
    if(generatedFeff)syncGeneratedPathSelection(false);
    syncPathSettings();
    const fd=new FormData($('#process-form'));
    const fitfd=new FormData(e.target);
    for(const [k,v] of fitfd.entries()){if(k==='path_files')continue;fd.set(k,v)}
    for(const file of $('#path-files').files)fd.append('path_files',file);
    const d=await fitFetchWithRecovery(fd);lastFit=d;
    message('#fit-message',`拟合完成 · ${d.quality_status}；请结合残差和物理模型复核。`,d.warnings.length?'':'ok');
    $('#fit-warnings').innerHTML=d.warnings.length?`<div class="warning-list"><strong>质量提示</strong><ul>${d.warnings.map(w=>`<li class="${fitWarningClass(w)}">${escapeHtml(w)}</li>`).join('')}</ul></div>`:'<div class="message ok">未发现自动质量警告。</div>';
    metrics('#fit-metrics',[['采用阶段',d.accepted_stage||'未通过'],['R-factor',Number(d.r_factor).toPrecision(4)],['reduced χ²',Number(d.reduced_chi_square).toPrecision(4)],['ΔE₀',`${d.delta_e0_eV.toFixed(3)} ± ${d.delta_e0_stderr===null?'—':d.delta_e0_stderr.toFixed(3)} eV`],['S₀²',`${d.s02.toFixed(4)}${d.s02_stderr===null?' (固定)':` ± ${d.s02_stderr.toFixed(4)}`}`],['Nind',Number(d.n_independent).toFixed(2)],['变量数',d.n_variables],['Nfree',d.n_free],['k-weights',d.kweights.join(', ')],['AIC',Number(d.aic).toPrecision(5)],['BIC',Number(d.bic).toPrecision(5)] ]);
    const kw=d.display_kweight,kpow=d.data_k.map(k=>k**kw);
    const processing=$('#process-form').elements,e0=Number(d.energy_e0_eV),pre1=Number(processing.pre1.value),pre2=Number(processing.pre2.value),norm1=Number(processing.norm1.value),norm2=Number(processing.norm2.value);
    drawPlot('#plot-fit-energy',[{name:'raw μ(E)',x:d.energy_spectrum_eV,y:d.energy_raw_mu},{name:'normalized · flattened',x:d.energy_spectrum_eV,y:d.energy_normalized_mu},{name:'pre-edge',x:d.energy_spectrum_eV,y:d.energy_pre_edge},{name:'post-edge',x:d.energy_spectrum_eV,y:d.energy_post_edge},{name:'FEFF fit projection',x:d.energy_spectrum_eV,y:d.energy_normalized_fit,color:'#dc2626'}], 'Energy (eV)','absorption',{bands:[{from:e0+pre1,to:e0+pre2,label:'Pre-edge',color:'#38bdf8'},{from:e0+norm1,to:e0+norm2,label:'Normalization',color:'#f59e0b'}],vlines:[{x:e0,label:`E₀ ${e0.toFixed(1)} eV`}]});
    drawPlot('#plot-fit',[{name:'实验谱',x:d.data_k,y:d.data_chi.map((v,i)=>v*kpow[i])},{name:'拟合谱',x:d.model_k,y:d.model_chi.map((v,i)=>v*kpow[i])}], 'k (Å⁻¹)',`k${kw}χ(k)`);
    drawFitR(d);
    $('#global-fit-table').innerHTML='<h4>全部 GDS 参数</h4>'+table(d.parameter_rows,['name','state','initial_value','value','stderr','relative_error_percent','min','max','expr']);
    const assessmentMap=new Map(d.parameter_assessment.filter(item=>item.scope==='path').map(item=>[`${item.index}:${item.field}`,item.severity]));
    const fieldMap={CN:'cn',CN_stderr:'cn',deltar_A:'deltar',deltar_stderr:'deltar',R_A:'deltar',sigma2_A2:'sigma2',sigma2_stderr:'sigma2'};
    $('#fit-table').innerHTML='<h4>路径结果</h4>'+table(d.paths,['shell','label','Reff_A','CN','CN_stderr','R_A','deltar_A','deltar_stderr','sigma2_A2','sigma2_stderr'],(row,key,index)=>assessmentMap.get(`${index}:${fieldMap[key]}`)||'');
    $('#correlation-table').innerHTML=d.correlations.length?table(d.correlations.slice(0,12),['parameter_1','parameter_2','correlation']):'<p class="hint">没有绝对值大于 0.5 的参数相关性。</p>';
    $('#fit-manager-decisions').innerHTML=`<div class="manager-decisions">${d.manager_decisions.map(item=>`<p>✓ ${escapeHtml(item)}</p>`).join('')}</div>`;
    $('#fit-stage-table').innerHTML=table(d.stage_history,['stage','shells','path_count','r_factor','reduced_chi_square','n_independent','n_variables','max_abs_correlation','s02','delta_e0_eV','accepted','reason'],row=>row.accepted?'assessment-ok':'assessment-danger');
    renderFitAssessment(d);refillFitInputs(d,false);applyFitReviewColors(d);renderArtemisReport(d);$('#refill-fit-values').disabled=false;
    $('#fit-report').textContent=d.report;$('#download-fit').hidden=false;$('#download-fit-curves').hidden=false;$('#download-fit-json').hidden=false;$('#download-fit-package').hidden=false;$('#fit-download-addresses').hidden=false;$('#fit-data-url').dataset.url=d.data_download_url;$('#fit-wavelet-url').dataset.url=d.wavelet_download_url;$('#fit-package-url').dataset.url=d.download_url;$('#save-fitted-s02').disabled=!d.calibration_eligible;drawWaveletSet(d.wavelet);
  }catch(err){showFitServerError(err.message)}
};

$('#run-feff').onclick=async()=>{
  const form=$('#fit-form'),file=$('#cif-file').files[0];
  if(!file){message('#feff-message','请先选择 CIF 文件。','error');return}
  const fd=new FormData();fd.append('cif_file',file);fd.append('absorber',form.elements.absorber.value);fd.append('edge',form.elements.edge.value);fd.append('cluster_radius',form.elements.cluster_radius.value);fd.append('response_mode','json');
  message('#feff-message','正在运行 FEFF 并生成路径表，请稍候…');
  try{
    generatedFeff=await jsonFetch('/api/feff',{method:'POST',body:fd});
    $('#feff-result-id').value=generatedFeff.feff_result_id;$('#download-feff').hidden=false;$('#path-files').value='';$('#path-editor').innerHTML='';$('#path-settings').value='[]';renderGeneratedFeffPaths();
    message('#feff-message',`FEFF 已生成 ${generatedFeff.count} 条路径；第一壳单散射路径已自动勾选并传入下方参数管理器。`,'ok');
  }catch(err){message('#feff-message',err.message,'error')}
};

function renderGeneratedFeffPaths(){
  const root=$('#generated-feff-paths');if(!generatedFeff?.paths?.length){root.hidden=true;root.innerHTML='';return}
  const rows=generatedFeff.paths.map((path,index)=>{const checked=path.shell===1&&path.type==='single scattering';return `<tr class="${checked?'selected':''}"><td><input class="path-check feff-path-select" type="checkbox" data-index="${index}" ${checked?'checked':''}></td><td>${path.index}</td><td>${path.degen.toFixed(2)}</td><td>${path.reff.toFixed(4)}</td><td>${escapeHtml(path.scattering_path)}</td><td>${path.rank===null?'—':Number(path.rank).toFixed(2)}</td><td>${escapeHtml(path.type)}</td><td>${path.shell}</td></tr>`}).join('');
  root.innerHTML=`<div class="feff-path-toolbar"><strong>FEFF Scattering Paths</strong><button type="button" data-select="first">仅第一壳</button><button type="button" data-select="single">全部单散射</button><button type="button" data-select="none">清空</button></div><table><thead><tr><th>选择</th><th>#</th><th>Degen</th><th>Reff (Å)</th><th>Scattering path</th><th>Rank</th><th>Type</th><th>Shell</th></tr></thead><tbody>${rows}</tbody></table>`;root.hidden=false;
  root.querySelectorAll('.feff-path-select').forEach(input=>input.addEventListener('change',()=>{input.closest('tr').classList.toggle('selected',input.checked);syncGeneratedPathSelection(true)}));
  root.querySelectorAll('[data-select]').forEach(button=>button.addEventListener('click',()=>{const mode=button.dataset.select;root.querySelectorAll('.feff-path-select').forEach(input=>{const path=generatedFeff.paths[Number(input.dataset.index)];input.checked=mode==='first'?(path.shell===1&&path.type==='single scattering'):mode==='single'?path.type==='single scattering':false;input.closest('tr').classList.toggle('selected',input.checked)});syncGeneratedPathSelection(true)}));
  syncGeneratedPathSelection(true);
}

function syncGeneratedPathSelection(applyPreset){
  if(!generatedFeff)return [];
  const selected=$$('.feff-path-select:checked').map(input=>generatedFeff.paths[Number(input.dataset.index)]);
  $('#feff-path-names').value=JSON.stringify(selected.map(path=>path.name));
  if(applyPreset){const previous=new Map(syncPathSettings().map(item=>[item.label,item]));const configured=selected.map(path=>({...path,...(previous.get(path.label)||{})}));renderPathEditor(configured);$('#path-settings').value=JSON.stringify(configured,null,2);if(selected.length&&!previous.size)applyFitPreset('auto',false)}
  return selected;
}

$('#download-feff').onclick=()=>{if(generatedFeff?.download_url)downloadFromApi(generatedFeff.download_url,'feff-paths.zip').catch(err=>message('#feff-message',err.message,'error'))};

function pathNumber(value,digits=4){return Number(value??0).toFixed(digits)}
function renderPathEditor(settings){
  $('#path-editor').innerHTML=settings.map((item,index)=>`<section class="path-card" data-index="${index}"><div class="path-card-title"><strong>${escapeHtml(item.label||`path ${index+1}`)}</strong><span>Reff ${pathNumber(item.reff,3)} Å · FEFF degeneracy ${pathNumber(item.feff_degeneracy??item.cn,2)}</span></div><div class="grid two"><label>显示名称<input data-key="label" value="${escapeHtml(item.label||'')}"></label><label>配位壳层 shell<input data-key="shell" type="number" min="1" step="1" value="${Number(item.shell||1)}"></label></div>${pathParameter('CN','cn',item.cn,item.cn_min,item.cn_max,item.vary_cn)}${pathParameter('σ² (Å²)','sigma2',item.sigma2,item.sigma2_min??0,item.sigma2_max??0.02,item.vary_sigma2,4)}${pathParameter('ΔR (Å)','deltar',item.deltar,item.deltar_min??-0.12,item.deltar_max??0.12,item.vary_deltar,4)}<div class="grid three expr-row"><label>CN 表达式<input data-key="cn_expr" value="${escapeHtml(item.cn_expr||'')}" placeholder="可留空"></label><label>σ² 表达式<input data-key="sigma2_expr" value="${escapeHtml(item.sigma2_expr||'')}" placeholder="如 sig2_1"></label><label>ΔR 表达式<input data-key="deltar_expr" value="${escapeHtml(item.deltar_expr||'')}" placeholder="如 delr_1"></label></div></section>`).join('');
}
function pathParameter(title,key,value,min,max,vary,digits=3){return `<div class="path-parameter"><strong>${title}</strong><div class="grid three"><label>初值<input data-key="${key}" type="number" step="any" value="${pathNumber(value,digits)}"></label><label>下限<input data-key="${key}_min" type="number" step="any" value="${pathNumber(min,digits)}"></label><label>上限<input data-key="${key}_max" type="number" step="any" value="${pathNumber(max,digits)}"></label></div><label class="check"><input data-key="vary_${key==='deltar'?'deltar':key}" type="checkbox" ${vary!==false?'checked':''}>允许变化（取消勾选即固定初值）</label></div>`}
function syncPathSettings(){
  const settings=$$('.path-card').map(card=>{const item={};card.querySelectorAll('[data-key]').forEach(input=>{const key=input.dataset.key;item[key]=input.type==='checkbox'?input.checked:(input.type==='number'?Number(input.value):input.value)});return item});
  if(settings.length)$('#path-settings').value=JSON.stringify(settings,null,2);return settings;
}
function setFitValue(name,value){const input=$(`#fit-form [name="${name}"]`);if(!input)return;if(input.type==='checkbox')input.checked=Boolean(value);else input.value=value}
function setPathValue(card,key,value){const input=card?.querySelector(`[data-key="${key}"]`);if(!input)return;if(input.type==='checkbox')input.checked=Boolean(value);else input.value=value}
function clearFitErrors(){$$('#fit-form .field-error').forEach(el=>el.classList.remove('field-error'));const summary=$('#fit-field-errors');summary.hidden=true;summary.innerHTML=''}
function markFitField(input){if(!input)return;input.closest('label')?.classList.add('field-error');input.closest('.path-card')?.classList.add('field-error')}
function updateFitRangeMode(){const form=$('#fit-form');if(!form)return;const isR=form.elements.fitspace.value==='r',kmin=form.elements.fit_kmin,kmax=form.elements.fit_kmax,rmin=form.elements.rmin,rmax=form.elements.rmax;kmin.disabled=isR;kmax.disabled=isR;rmin.disabled=!isR;rmax.disabled=!isR;$('#fit-kmin-field').classList.toggle('range-auto',isR);$('#fit-kmax-field').classList.toggle('range-auto',isR);$('#fit-rmin-field').classList.toggle('range-auto',!isR);$('#fit-rmax-field').classList.toggle('range-auto',!isR);if(isR){kmin.value=Number($('#process-form').elements.kmin.value||3).toFixed(1);kmax.value=Number(lastAthena?.kmax_used||$('#process-form').elements.kmax.value||12).toFixed(1);$('#fit-range-mode-hint').textContent=`R-space：只需设置 Rmin/Rmax；K 范围自动继承 Athena（${kmin.value}–${kmax.value} Å⁻¹）。`}else{$('#fit-range-mode-hint').textContent='K-space：只需设置 kmin/kmax；R 范围不参与 K 空间拟合。'}}
function updateWaveletBackendMode(){const form=$('#fit-form'),isHama=form.elements.wavelet_backend.value==='hama';form.elements.wavelet_kappa.disabled=!isHama;form.elements.wavelet_sigma.disabled=!isHama;$('#hama-kappa-field').classList.toggle('range-auto',!isHama);$('#hama-sigma-field').classList.toggle('range-auto',!isHama)}
function validateFitForm(){
  const form=$('#fit-form'),errors=[];
  const bounded=(prefix,label,root=form,isPath=false)=>{const find=s=>isPath?root.querySelector(`[data-key="${s}"]`):root.elements[s],value=find(prefix),minimum=find(`${prefix}_min`),maximum=find(`${prefix}_max`),vary=find(`vary_${prefix==='deltar'?'deltar':prefix}`);if(!value||!Number.isFinite(Number(value.value))){errors.push(`${label} 初值不是有效数字`);markFitField(value);return}if(vary?.checked){const lo=Number(minimum?.value),hi=Number(maximum?.value),v=Number(value.value);if(!Number.isFinite(lo)||!Number.isFinite(hi)||lo>=hi){errors.push(`${label} 允许变化时必须满足下限 < 上限；固定参数请取消“允许变化”`);markFitField(minimum);markFitField(maximum)}else if(v<lo||v>hi){errors.push(`${label} 初值必须位于上下限之间`);markFitField(value)}}};
  bounded('s02','S₀²');bounded('de0','ΔE₀');
  $$('.path-card').forEach((card,index)=>{bounded('cn',`路径 ${index+1} 的 CN`,card,true);bounded('sigma2',`路径 ${index+1} 的 σ²`,card,true);bounded('deltar',`路径 ${index+1} 的 ΔR`,card,true)});
  const kmin=Number(form.elements.fit_kmin.value),kmax=Number(form.elements.fit_kmax.value),rmin=Number(form.elements.rmin.value),rmax=Number(form.elements.rmax.value);
  const isR=form.elements.fitspace.value==='r';
  if(!isR&&!(kmin>=0&&kmin<kmax)){errors.push('K 空间必须满足 0 ≤ kmin < kmax');markFitField(form.elements.fit_kmin);markFitField(form.elements.fit_kmax)}
  if(!isR&&lastAthena&&kmax>Number(lastAthena.kmax_used)+0.05){errors.push(`拟合 kmax 不能超过当前数据上限 ${Number(lastAthena.kmax_used).toFixed(2)} Å⁻¹`);markFitField(form.elements.fit_kmax)}
  if(isR&&!(rmin>=0&&rmin<rmax)){errors.push('R 空间必须满足 0 ≤ Rmin < Rmax');markFitField(form.elements.rmin);markFitField(form.elements.rmax)}
  if(!$$('.path-card').length){errors.push('请至少生成或上传并选择一条 FEFF 路径');markFitField($('#path-files'))}
  if(errors.length){const summary=$('#fit-field-errors');summary.innerHTML=`<strong>请修正以下参数：</strong><ul>${errors.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul>`;summary.hidden=false;message('#fit-message','拟合参数检查未通过，左侧标红区域需要修改。','error');$('#fit-form .field-error')?.scrollIntoView({behavior:'smooth',block:'center'});return false}return true;
}
function showFitServerError(text){clearFitErrors();const messageText=String(text||'拟合失败');const mappings=[['CN','[data-key="cn"]'],['σ²','[data-key="sigma2"]'],['ΔR','[data-key="deltar"]'],['S₀²','[name="s02"]'],['ΔE₀','[name="de0"]'],['k 空间','[name="fit_kmin"]'],['kmax','[name="fit_kmax"]'],['R 空间','[name="rmin"]']];for(const [token,selector] of mappings)if(messageText.includes(token))markFitField($(`#fit-form ${selector}`));const summary=$('#fit-field-errors');summary.innerHTML=`<strong>FEFF 拟合未运行：</strong> ${escapeHtml(messageText)}`;summary.hidden=false;message('#fit-message',messageText,'error')}
function fitWarningClass(text){return /超出|不大于|过度参数|近拟合边界|未能可靠|相对误差/.test(text)?'assessment-danger':'assessment-warning'}
function renderFitAssessment(result){
  const names={s02:'S₀²',de0:'ΔE₀',cn:'CN',sigma2:'σ²',deltar:'ΔR'},rows=result.parameter_assessment.map(item=>({parameter:item.scope==='global'?names[item.field]:`路径 ${item.index+1} · ${names[item.field]}`,value:item.value,recommended:item.recommended,status:item.severity==='danger'?'明显异常':item.severity==='warning'?'建议复核':item.severity==='info'?'可接受但非优选':'范围内',action:item.action,severity:item.severity}));
  $('#fit-assessment').innerHTML=table(rows,['parameter','value','recommended','status','action'],row=>`assessment-${row.severity}`);
}
function applyFitReviewColors(result){
  $$('#fit-form .fit-review-ok,#fit-form .fit-review-info,#fit-form .fit-review-warning,#fit-form .fit-review-danger').forEach(el=>el.classList.remove('fit-review-ok','fit-review-info','fit-review-warning','fit-review-danger'));
  result.parameter_assessment.forEach(item=>{let input;if(item.scope==='global')input=$(`#fit-form [name="${item.field}"]`);else input=$$('.path-card')[item.index]?.querySelector(`[data-key="${item.field}"]`);input?.classList.add(`fit-review-${item.severity}`)});
}
function drawFitR(result){if(!result)return;drawPlot('#plot-fit-r',[{name:'实验谱 |χ(R)|',x:result.r,y:result.data_chir_mag},{name:'拟合谱 |χ(R)|',x:result.r,y:result.model_chir_mag}],'R (Å)','|χ(R)|')}
function refillFitInputs(result,announce=true){if(!result)return;setFitValue('s02',Number(result.s02).toFixed(4));setFitValue('de0',Number(result.delta_e0_eV).toFixed(2));result.paths.forEach((path,index)=>{const card=$$('.path-card')[index];if(!card)return;setPathValue(card,'cn',Number(path.CN).toFixed(4));setPathValue(card,'sigma2',Number(path.sigma2_A2).toFixed(6));setPathValue(card,'deltar',Number(path.deltar_A).toFixed(5))});syncPathSettings();if(announce){message('#fit-message',`已把最终采用阶段 ${result.accepted_stage||'—'} 的参数回填为左侧初值，可调整后再次拟合。`,'ok');$('#fit-form').scrollIntoView({behavior:'smooth',block:'start'})}}
function renderArtemisReport(result){const cfg=result.fit_config,summary=[{item:'Fit space',value:String(cfg.fitspace).toUpperCase()},{item:'k range',value:`${cfg.kmin}–${cfg.kmax} Å⁻¹`},{item:'R range',value:`${cfg.rmin}–${cfg.rmax} Å`},{item:'k-weights',value:cfg.kweights.join(', ')},{item:'Window',value:`${cfg.window}, dk=${cfg.dk}`},{item:'Independent points',value:Number(result.n_independent).toFixed(3)},{item:'Variables',value:result.n_variables},{item:'R-factor',value:Number(result.r_factor).toPrecision(6)},{item:'χ² / reduced χ²',value:`${Number(result.chi_square).toPrecision(6)} / ${Number(result.reduced_chi_square).toPrecision(6)}`},{item:'Accepted stage',value:result.accepted_stage||'none'}];$('#artemis-fit-summary').innerHTML=table(summary,['item','value']);$('#artemis-variable-table').innerHTML=table(result.parameter_rows,['name','state','initial_value','value','stderr','relative_error_percent','min','max','expr']);$('#artemis-path-table').innerHTML=table(result.paths,['shell','label','Reff_A','CN','CN_stderr','R_A','deltar_A','deltar_stderr','sigma2_A2','sigma2_stderr']);$('#paper-fit-table').innerHTML=table(result.paper_table,['Path','d_FEFF_A','N','R_A','sigma2_A2','N_state','sigma2_state']);$('#paper-fit-notes').innerHTML=result.paper_notes.map((note,index)=>`<p><sup>${String.fromCharCode(97+index)}</sup> ${escapeHtml(note)}</p>`).join('')}
function selectGeneratedShells(maxShell){if(!generatedFeff)return;$$('.feff-path-select').forEach(input=>{const path=generatedFeff.paths[Number(input.dataset.index)];input.checked=path.shell<=maxShell&&path.type==='single scattering';input.closest('tr').classList.toggle('selected',input.checked)});syncGeneratedPathSelection(true)}
function runShellFit(maxShell,fitspace){if(generatedFeff)selectGeneratedShells(maxShell);$('#fit-max-shell').value=maxShell||'';setFitValue('fitspace',fitspace);updateFitRangeMode();$('#shell-fit-status').textContent=maxShell===1?'正在拟合第一壳；完成后参数会自动回填。':maxShell===2?`正在 ${fitspace.toUpperCase()} 空间加入第二壳拟合；沿用第一壳回填值。`:'正在拟合全部已选壳层。';$('#fit-form').requestSubmit()}
function applyFitPreset(requested=$('#fit-preset').value,announce=true){
  let preset=requested;if(preset==='auto')preset=lastAthena?.source_name?.toLowerCase().includes('foil')?'ir_foil':'unknown';
  if(preset==='ir_foil')$('#fit-mode').value='standard';else if(preset==='unknown'||preset==='iro2')$('#fit-mode').value='unknown';
  setFitValue('de0',0);setFitValue('de0_min',-10);setFitValue('de0_max',10);setFitValue('de0_vary',true);setFitValue('fit_kweights','2');setFitValue('fit_kmin',3);setFitValue('fit_kmax',Math.min(12,Number(lastAthena?.kmax_used||12)));setFitValue('fit_dk',1);setFitValue('fit_window','kaiser');setFitValue('fit_rwindow','hanning');setFitValue('wavelet_kweight',2);setFitValue('wavelet_rmax',6);setFitValue('wavelet_backend','hama');setFitValue('wavelet_kappa',10);setFitValue('wavelet_sigma',1);
  const cards=$$('.path-card');
  if(preset==='ir_foil'){
    setFitValue('s02',0.85);setFitValue('s02_source','manual');setFitValue('s02_min',0.5);setFitValue('s02_max',1.2);setFitValue('s02_vary',true);setFitValue('rmin',1.5);setFitValue('rmax',3.2);
    if(cards[0]){setPathValue(cards[0],'cn',12);setPathValue(cards[0],'cn_min',12);setPathValue(cards[0],'cn_max',12);setPathValue(cards[0],'vary_cn',false);setPathValue(cards[0],'sigma2',0.005);setPathValue(cards[0],'deltar',0)}
  }else if(preset==='iro2'){
    setFitValue('s02',0.85);setFitValue('s02_vary',false);setFitValue('rmin',1.0);setFitValue('rmax',2.4);
    if(cards[0]){setPathValue(cards[0],'cn',6);setPathValue(cards[0],'cn_min',2);setPathValue(cards[0],'cn_max',8);setPathValue(cards[0],'vary_cn',true);setPathValue(cards[0],'sigma2',0.004);setPathValue(cards[0],'deltar',0)}
  }else{
    setFitValue('s02',0.85);setFitValue('s02_vary',false);cards.forEach(card=>setPathValue(card,'vary_cn',true));
  }
  syncPathSettings();if(announce)message('#suggest-message',`已应用${preset==='ir_foil'?' Ir foil 标定':preset==='iro2'?' IrO₂ 第一壳':'未知样品'}建议参数；它们仅作为起点。`,'ok');
}
async function suggestFitParameters(){
  const files=[...$('#path-files').files];
  if(!files.length&&generatedFeff){const selected=syncGeneratedPathSelection(true);message('#suggest-message',selected.length?`已从 CIF 生成结果读取 ${selected.length} 条已勾选路径的建议参数。`:'请先在 FEFF 路径表中勾选至少一条路径。',selected.length?'ok':'error');return}
  if(!files.length){message('#suggest-message','请先由 CIF 生成路径，或手工选择一个或多个 feffNNNN.dat。','error');return}
  const fd=new FormData();files.forEach(file=>fd.append('path_files',file));message('#suggest-message','正在读取 FEFF 路径的 Reff 和简并度…');
  try{const d=await jsonFetch('/api/artemis/suggest',{method:'POST',body:fd});renderPathEditor(d.paths);$('#path-settings').value=JSON.stringify(d.paths,null,2);for(const [key,value] of Object.entries(d.global))setFitValue(key,value);applyFitPreset('auto',false);const chosen=lastAthena?.source_name?.toLowerCase().includes('foil')?'已自动切换到标准样模式：固定 CN=12，分阶段拟合 S₀²。':'已自动切换到未知样品模式：固定已标定 S₀²，分阶段拟合 CN。';message('#suggest-message',`${d.note} ${chosen}`,'ok')}catch(err){message('#suggest-message',err.message,'error')}
}
$('#suggest-fit').onclick=suggestFitParameters;
$('#path-files').addEventListener('change',()=>{if($('#path-files').files.length){generatedFeff=null;$('#feff-result-id').value='';$('#feff-path-names').value='[]';$('#generated-feff-paths').hidden=true;$('#download-feff').hidden=true}suggestFitParameters()});
$('#apply-fit-preset').onclick=()=>applyFitPreset();
$('#fit-mode').addEventListener('change',()=>{const mode=$('#fit-mode').value;if(mode==='standard'){applyFitPreset('ir_foil');$('#fit-preset').value='ir_foil'}else if(mode==='unknown'){applyFitPreset('unknown');$('#fit-preset').value='unknown';if(Number.isFinite(calibratedS02)){setFitValue('s02',calibratedS02);setFitValue('s02_vary',false);message('#suggest-message',`未知样品将固定使用已标定 S₀²=${calibratedS02.toFixed(4)}。`,'ok')}}else message('#suggest-message','高级模式不会自动改变用户的自由参数和约束表达式。','ok')});
$('#apply-saved-s02').onclick=()=>{if(!Number.isFinite(calibratedS02)){message('#fit-message','尚未保存标准样 S₀²，请先用 Ir foil 完成标定。','error');return}setFitValue('s02',calibratedS02);setFitValue('s02_vary',false);setFitValue('s02_source','standard_calibration');$('#fit-mode').value='unknown';message('#fit-message',`已应用并固定 S₀²=${calibratedS02.toFixed(4)}。`,'ok')};
$('#save-fitted-s02').onclick=()=>{if(!lastFit?.calibration_eligible){message('#fit-message','本次标准样最终振幅阶段未通过自动审查，不能保存为标定值。','error');return}calibratedS02=Number(lastFit.s02);localStorage.setItem('xafs.calibratedS02',String(calibratedS02));$('#saved-s02').textContent=calibratedS02.toFixed(4);message('#fit-message',`已保存标准样标定 S₀²=${calibratedS02.toFixed(4)}，未知样品模式会自动固定此值。`,'ok')};
$('#refill-fit-values').onclick=()=>refillFitInputs(lastFit,true);
$('#fit-form').elements.fitspace.addEventListener('change',updateFitRangeMode);
$('#fit-form').elements.wavelet_backend.addEventListener('change',updateWaveletBackendMode);
$('#fit-first-shell').onclick=()=>runShellFit(1,'r');
$('#fit-second-shell').onclick=()=>{if(!lastFit)message('#fit-message','请先完成第一壳拟合，再加入第二壳。','error');else runShellFit(2,$('#second-shell-fitspace').value)};
$('#fit-all-shells').onclick=()=>runShellFit(null,$('#fit-form').elements.fitspace.value);
$$('.plot-svg-download').forEach(button=>button.onclick=()=>{const svg=$(`#${button.dataset.plot} svg`);if(!svg){message('#fit-message','当前没有可下载的图。','error');return}const copy=svg.cloneNode(true);copy.setAttribute('xmlns','http://www.w3.org/2000/svg');downloadBlob(new XMLSerializer().serializeToString(copy),'image/svg+xml;charset=utf-8',button.dataset.name)});

function waveColor(t){t=Math.max(0,Math.min(1,t));const stops=[[7,18,48],[10,103,151],[13,202,170],[250,204,21],[239,68,68]],x=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(x)),f=x-i;return stops[i].map((v,j)=>Math.round(v+(stops[i+1][j]-v)*f))}
function drawWavelet(canvasId,matrix,k,r,maxValue){
  const canvas=$(canvasId),W=520,H=300,p={l:48,r:12,t:12,b:34};canvas.width=W;canvas.height=H;const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,W,H);const rows=matrix.length,cols=matrix[0]?.length||0;if(!rows||!cols)return;
  const image=ctx.createImageData(cols,rows);for(let iy=0;iy<rows;iy++)for(let ix=0;ix<cols;ix++){const rgb=waveColor(matrix[iy][ix]/maxValue),offset=((rows-1-iy)*cols+ix)*4;image.data[offset]=rgb[0];image.data[offset+1]=rgb[1];image.data[offset+2]=rgb[2];image.data[offset+3]=255}const off=document.createElement('canvas');off.width=cols;off.height=rows;off.getContext('2d').putImageData(image,0,0);ctx.imageSmoothingEnabled=true;ctx.drawImage(off,p.l,p.t,W-p.l-p.r,H-p.t-p.b);ctx.strokeStyle='#64748b';ctx.strokeRect(p.l,p.t,W-p.l-p.r,H-p.t-p.b);ctx.fillStyle='#475569';ctx.font='11px Segoe UI';ctx.fillText(`${k[0].toFixed(1)}`,p.l,H-15);ctx.fillText(`${k.at(-1).toFixed(1)} Å⁻¹`,W-64,H-15);ctx.fillText(`${r[0].toFixed(1)}`,8,H-p.b);ctx.fillText(`${r.at(-1).toFixed(1)} Å`,8,p.t+8);ctx.fillText('k',W/2,H-5);ctx.save();ctx.translate(12,H/2);ctx.rotate(-Math.PI/2);ctx.fillText('R',0,0);ctx.restore();
}
function drawWaveletSet(w){const all=[w.data_mag,w.model_mag].flat(2),max=Math.max(...all,1e-15);drawWavelet('#wavelet-data',w.data_mag,w.k,w.r,max);drawWavelet('#wavelet-model',w.model_mag,w.k,w.r,max);const isHama=w.backend==='hama_morlet_integrated';$('#wavelet-title').textContent=isHama?'HAMA Morlet 小波变换':'Larch Cauchy 小波变换';$('#wavelet-description').textContent=isHama?`HAMA Morlet · κ=${w.kappa} · σ=${w.sigma} · k-weight=${w.kweight} · 等间隔 Δk=${Number(w.input_k_step).toFixed(3)} Å⁻¹`:`Larch Cauchy · k-weight=${w.kweight} · Δk=${Number(w.input_k_step).toFixed(3)} Å⁻¹`}

$('#analysis-form').onsubmit=async e=>{
  e.preventDefault();message('#analysis-message','正在执行 XANES 与 LCF 分析…');
  try{
    const fd=new FormData($('#process-form')),own=new FormData(e.target);
    fd.set('reference_names',JSON.stringify([own.get('ref1'),own.get('ref2')]));
    fd.set('lcf_emin',own.get('lcf_emin'));fd.set('lcf_emax',own.get('lcf_emax'));
    if(own.get('sum_to_one'))fd.set('sum_to_one','on');else fd.delete('sum_to_one');
    const d=await jsonFetch('/api/analyze',{method:'POST',body:fd});
    message('#analysis-message',`${d.source_name} 分析完成`,'ok');
    metrics('#analysis-metrics',[['E₀',`${d.e0.toFixed(2)} eV`],['白线位置',`${d.white_line_energy.toFixed(2)} eV`],['白线高度',d.white_line_height.toFixed(4)],['LCF R-factor',d.lcf.r_factor.toPrecision(4)]]);
    drawPlot('#plot-analysis-xanes',[{name:'normalized μ(E)',x:d.energy,y:d.norm},{name:'dμ/dE',x:d.energy,y:d.dmude}], 'Energy (eV)','normalized / derivative',{vlines:[{x:d.e0,label:`E₀ ${d.e0.toFixed(1)} eV`} ]});
    $('#lcf-table').innerHTML=table(d.lcf.fractions,['reference','fraction']);
    drawPlot('#plot-lcf',[{name:'sample',x:d.lcf.energy,y:d.lcf.sample},{name:'LCF fit',x:d.lcf.energy,y:d.lcf.fit},{name:'residual',x:d.lcf.energy,y:d.lcf.residual}], 'Energy (eV)','normalized μ(E)');
  }catch(err){message('#analysis-message',err.message,'error')}
};

$('#run-batch').onclick=async()=>{
  const selected=[...$('#batch-datasets').selectedOptions].map(o=>o.value);
  if(!selected.length){message('#analysis-message','请先选择至少一个批量样品。','error');return}
  message('#analysis-message',`正在处理 ${selected.length} 个谱…`);
  try{
    const fd=new FormData($('#process-form'));fd.set('datasets',JSON.stringify(selected));fd.set('energy_shift',$('#batch-energy-shift').value);
    const d=await jsonFetch('/api/batch',{method:'POST',body:fd});lastBatch=d.rows;
    $('#batch-table').innerHTML=table(d.rows,Object.keys(d.rows[0]));$('#download-batch').hidden=false;
    message('#analysis-message',`已完成 ${d.rows.length} 个谱的质量汇总。`,'ok');
  }catch(err){message('#analysis-message',err.message,'error')}
};

$('#batch-use-remembered').onclick=()=>{$('#batch-energy-shift').value=rememberedShift.toFixed(3);message('#analysis-message',`批处理将统一使用 ΔE=${rememberedShift.toFixed(3)} eV。`,'ok')};

$('#download-standardized-batch').onclick=async()=>{
  const selected=[...$('#batch-datasets').selectedOptions].map(o=>o.value);
  if(!selected.length){message('#analysis-message','请先选择至少一个批量样品。','error');return}
  const fd=new FormData($('#process-form'));fd.set('datasets',JSON.stringify(selected));fd.set('energy_shift',$('#batch-energy-shift').value);
  message('#analysis-message',`正在标准化并打包 ${selected.length} 个谱…`);
  try{
    const response=await fetch(apiUrl('/api/batch/export'),{method:'POST',body:fd});
    if(!response.ok){const problem=await response.json();throw new Error(problem.error||`HTTP ${response.status}`)}
    const blob=await response.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='xafs_standardized_batch.zip';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
    message('#analysis-message',`已导出 ${selected.length} 个标准化谱、处理参数和汇总表。`,'ok');
  }catch(err){message('#analysis-message',err.message,'error')}
};

function table(rows,keys,classFor=null){return `<table><thead><tr>${keys.map(k=>`<th>${escapeHtml(k)}</th>`).join('')}</tr></thead><tbody>${rows.map((r,index)=>{const rowClass=classFor&&classFor.length<3?classFor(r,index):'';return `<tr class="${escapeHtml(rowClass||'')}">${keys.map(k=>{const cellClass=classFor&&classFor.length>=3?classFor(r,k,index):'';return `<td class="${escapeHtml(cellClass||'')}">${r[k]===null?'—':escapeHtml(typeof r[k]==='number'?Number(r[k]).toPrecision(6):r[k]??'')}</td>`}).join('')}</tr>`}).join('')}</tbody></table>`}

$('#download-fit').onclick=()=>{if(!lastFit)return;const keys=['name','value','stderr','vary','min','max','expr'],rows=[keys.join(','),...lastFit.parameter_rows.map(r=>keys.map(k=>r[k]??'').join(',')),'','path,'+Object.keys(lastFit.paths[0]).join(','),...lastFit.paths.map(r=>'path,'+Object.keys(r).map(k=>r[k]??'').join(','))];downloadBlob('\ufeff'+rows.join('\n'),'text/csv;charset=utf-8','feffit_parameters.csv')};
$('#download-fit-curves').onclick=()=>{if(lastFit?.data_download_url)downloadFromApi(lastFit.data_download_url,'fit-data.csv').catch(err=>message('#fit-message',err.message,'error'))};
$('#download-fit-json').onclick=()=>{if(lastFit)downloadBlob(JSON.stringify(lastFit,null,2),'application/json','feffit_complete_result.json')};
$('#download-fit-package').onclick=()=>{if(lastFit?.download_url)downloadFromApi(lastFit.download_url,'fit-result.zip').catch(err=>message('#fit-message',err.message,'error'))};

$('#download-batch').onclick=()=>{if(!lastBatch?.length)return;const keys=Object.keys(lastBatch[0]),quote=v=>`"${String(v??'').replaceAll('"','""')}"`,rows=[keys.map(quote).join(','),...lastBatch.map(r=>keys.map(k=>quote(r[k])).join(','))];const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+rows.join('\n')],{type:'text/csv;charset=utf-8'}));a.download='xafs_batch_quality.csv';a.click();URL.revokeObjectURL(a.href)};

function downloadBlob(content,type,name){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([content],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
$('#download-energy').onclick=()=>{if(!lastAthena)return;const keys=['energy','mu','norm','flat','display_norm','pre_edge','post_edge','dmude'],rows=[keys.join(',')];for(let i=0;i<lastAthena.energy.length;i++)rows.push(keys.map(k=>lastAthena[k][i]??'').join(','));downloadBlob('\ufeff'+rows.join('\n'),'text/csv;charset=utf-8',`${lastAthena.source_name}_athena.csv`)};
$('#download-project').onclick=()=>{if(!lastAthena)return;const config=Object.fromEntries(new FormData($('#process-form')).entries());downloadBlob(JSON.stringify({version:1,created_at:new Date().toISOString(),config,result:lastAthena},null,2),'application/json',`${lastAthena.source_name}_xafs_project.json`)};

$('#edge-form').onsubmit=async e=>{e.preventDefault();try{const d=await jsonFetch('/api/edges/'+encodeURIComponent(new FormData(e.target).get('symbol')));message('#edge-message',`${d.element} · ${d.backend}`,'ok');$('#edge-table').innerHTML=table(d.edges,Object.keys(d.edges[0]))}catch(err){message('#edge-message',err.message,'error')}};

updateFitRangeMode();
updateWaveletBackendMode();
$('#refresh-fit-history').onclick=loadRecentFits;
boot().catch(handleBootFailure);
