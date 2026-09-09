'use strict';
const C_K = 3.80998212;
const state = { raw:null, processed:null, fit:null, feff:[null,null] };
const $ = id => document.getElementById(id);
const num = (id, d=0) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : d; };

document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===btn));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===btn.dataset.tab));
  if(btn.dataset.tab==='analysis') refreshAnalysis();
}));

function parseNumericText(text){
  const rows=[];
  for(const line0 of text.split(/\r?\n/)){
    const line=line0.trim();
    if(!line || /^[#;!*]/.test(line)) continue;
    const parts=line.replace(/,/g,' ').split(/\s+/).map(Number);
    if(parts.length>=2 && parts.every(Number.isFinite)) rows.push(parts);
  }
  if(rows.length<8) throw new Error('可识别的数值行不足 8 行。');
  const ncol=Math.min(...rows.map(r=>r.length));
  return rows.map(r=>r.slice(0,ncol));
}

$('data-file').addEventListener('change',async e=>{
  const f=e.target.files[0]; if(!f) return;
  try{ const rows=parseNumericText(await f.text()); state.raw={name:f.name,rows}; $('file-info').textContent=`${f.name} · ${rows.length} 行 · ${rows[0].length} 列`; }
  catch(err){ $('file-info').textContent=err.message; }
});

function linfit(x,y){
  const n=x.length, sx=x.reduce((a,b)=>a+b,0), sy=y.reduce((a,b)=>a+b,0), sxx=x.reduce((a,b)=>a+b*b,0), sxy=x.reduce((a,b,i)=>a+b*y[i],0);
  const den=n*sxx-sx*sx || 1e-12; const b=(n*sxy-sx*sy)/den; const a=(sy-b*sx)/n; return [a,b];
}
function polyfit2(x,y){
  let s0=x.length,s1=0,s2=0,s3=0,s4=0,t0=0,t1=0,t2=0;
  for(let i=0;i<x.length;i++){const X=x[i],Y=y[i],X2=X*X;s1+=X;s2+=X2;s3+=X2*X;s4+=X2*X2;t0+=Y;t1+=X*Y;t2+=X2*Y;}
  const A=[[s0,s1,s2],[s1,s2,s3],[s2,s3,s4]], b=[t0,t1,t2];
  for(let i=0;i<3;i++){let p=i;for(let j=i+1;j<3;j++)if(Math.abs(A[j][i])>Math.abs(A[p][i]))p=j;[A[i],A[p]]=[A[p],A[i]];[b[i],b[p]]=[b[p],b[i]];let d=A[i][i]||1e-12;for(let k=i;k<3;k++)A[i][k]/=d;b[i]/=d;for(let j=0;j<3;j++){if(j===i)continue;let f=A[j][i];for(let k=i;k<3;k++)A[j][k]-=f*A[i][k];b[j]-=f*b[i];}}
  return b;
}
function movingAverage(y,window){
  const w=Math.max(3,Math.round(window)|1), out=new Array(y.length); let sum=0;
  for(let i=0;i<y.length;i++){sum+=y[i]; if(i-w>=0)sum-=y[i-w]; const n=Math.min(i+1,w); out[i]=sum/n;}
  const rev=[...out].reverse(), rev2=[];sum=0;for(let i=0;i<rev.length;i++){sum+=rev[i];if(i-w>=0)sum-=rev[i-w];rev2[i]=sum/Math.min(i+1,w);}return rev2.reverse();
}
function interp1(x,y,xq){
  if(xq<=x[0])return y[0]; if(xq>=x[x.length-1])return y[y.length-1];
  let lo=0,hi=x.length-1;while(hi-lo>1){const m=(lo+hi)>>1;if(x[m]<=xq)lo=m;else hi=m;}const t=(xq-x[lo])/(x[hi]-x[lo]);return y[lo]*(1-t)+y[hi]*t;
}
function derivative(x,y){
  return y.map((_,i)=>{if(i===0)return (y[1]-y[0])/(x[1]-x[0]);if(i===y.length-1)return (y[i]-y[i-1])/(x[i]-x[i-1]);return (y[i+1]-y[i-1])/(x[i+1]-x[i-1]);});
}
function chooseSignal(rows){
  const ec=Math.round(num('energy-column',0)), sc=Math.round(num('signal-column',1)), i0c=Math.round(num('i0-column',1)), ic=Math.round(num('it-if-column',2));
  const mode=$('signal-mode').value, E=[], mu=[];
  for(const r of rows){ if(ec>=r.length)continue; const e=r[ec]+num('energy-shift',0); let m;
    const actual=mode==='auto' ? (r.length>=3?'transmission':'direct') : mode;
    if(actual==='direct'){if(sc>=r.length)continue;m=r[sc];}
    else if(actual==='transmission'){if(i0c>=r.length||ic>=r.length||r[i0c]<=0||r[ic]<=0)continue;m=Math.log(r[i0c]/r[ic]);}
    else {if(i0c>=r.length||ic>=r.length||r[i0c]===0)continue;m=r[ic]/r[i0c];}
    if(Number.isFinite(e)&&Number.isFinite(m)){E.push(e);mu.push(m);}
  }
  const zipped=E.map((e,i)=>[e,mu[i]]).sort((a,b)=>a[0]-b[0]); return {E:zipped.map(z=>z[0]),mu:zipped.map(z=>z[1])};
}
function processData(){
  if(!state.raw) throw new Error('请先上传 XAS 数据。');
  const {E,mu}=chooseSignal(state.raw.rows); if(E.length<20)throw new Error('有效数据点不足。请检查列号与信号模式。');
  const smoothRaw=movingAverage(mu, Math.max(5,Math.round(E.length/180)));
  const dRaw=derivative(E,smoothRaw);
  let e0=num('e0',0);
  if($('auto-e0').checked || !e0){let best=-Infinity,idx=0;for(let i=2;i<dRaw.length-2;i++){if(dRaw[i]>best){best=dRaw[i];idx=i;}}e0=E[idx];$('e0').value=e0.toFixed(2);}
  const pre1=num('pre1',-150), pre2=num('pre2',-30), norm1=num('norm1',150), norm2=num('norm2',700);
  const preIdx=E.map((e,i)=>[e,i]).filter(z=>z[0]>=e0+pre1&&z[0]<=e0+pre2).map(z=>z[1]);
  const postIdx=E.map((e,i)=>[e,i]).filter(z=>z[0]>=e0+norm1&&z[0]<=e0+norm2).map(z=>z[1]);
  if(preIdx.length<4||postIdx.length<4)throw new Error('Pre/Norm 区间有效点不足，请调整 E₀ 或区间。');
  const [pa,pb]=linfit(preIdx.map(i=>E[i]),preIdx.map(i=>mu[i]));
  const pc=polyfit2(postIdx.map(i=>E[i]-e0),postIdx.map(i=>mu[i]));
  const preAt=e=>pa+pb*e, postAt=e=>pc[0]+pc[1]*(e-e0)+pc[2]*(e-e0)*(e-e0);
  const edgeStep=postAt(e0)-preAt(e0); if(Math.abs(edgeStep)<1e-12)throw new Error('计算得到的 edge step 接近 0。');
  const norm=E.map((e,i)=>(mu[i]-preAt(e))/edgeStep);
  const dnorm=derivative(E,norm);
  const k=[],chiRaw=[]; for(let i=0;i<E.length;i++){if(E[i]>e0){k.push(Math.sqrt((E[i]-e0)/C_K));chiRaw.push(norm[i]);}}
  const kmin=num('kmin',3),kmax=num('kmax',12),kw=parseInt($('kweight').value,10);
  const selected=k.map((v,i)=>[v,i]).filter(z=>z[0]>=0.5&&z[0]<=kmax+1).map(z=>z[1]);
  const xbg=selected.map(i=>k[i]), ybg=selected.map(i=>chiRaw[i]);
  const coeff=polyfit2(xbg,ybg); const residual=chiRaw.map((v,i)=>v-(coeff[0]+coeff[1]*k[i]+coeff[2]*k[i]*k[i]));
  const rbkg=Math.max(.2,num('rbkg',1)); const smw=Math.max(5,Math.round((12/rbkg))); const slow=movingAverage(residual,smw);
  const chi=residual.map((v,i)=>v-slow[i]);
  const kWeighted=chi.map((v,i)=>v*Math.pow(k[i],kw));
  const ft=fourierTransform(k,kWeighted,kmin,kmax,num('rmax',6));
  state.processed={name:state.raw.name,E,mu,norm,dnorm,e0,edgeStep,k,chi,kWeighted,kw,kmin,kmax,ft,params:{pre1,pre2,norm1,norm2,rbkg}};
  renderProcessed();
}
$('process-form').addEventListener('submit',e=>{e.preventDefault();try{processData();setMsg('athena-message','处理完成。所有计算在当前浏览器内完成。','ok');}catch(err){setMsg('athena-message',err.message,'error');}});

function fourierTransform(k,y,kmin,kmax,rmax){
  const pairs=k.map((v,i)=>[v,y[i]]).filter(z=>z[0]>=kmin&&z[0]<=kmax); if(pairs.length<4)return {R:[],mag:[],real:[],imag:[]};
  const kk=pairs.map(z=>z[0]), yy=pairs.map(z=>z[1]); const n=kk.length;
  const win=yy.map((v,i)=>v*0.5*(1-Math.cos(2*Math.PI*i/(n-1))));
  const R=[],real=[],imag=[],mag=[]; const nr=300;
  for(let ir=0;ir<nr;ir++){const r=rmax*ir/(nr-1);let re=0,im=0;for(let i=0;i<n-1;i++){const dk=kk[i+1]-kk[i];const ph=2*kk[i]*r;re+=win[i]*Math.cos(ph)*dk;im+=win[i]*Math.sin(ph)*dk;}R.push(r);real.push(re);imag.push(im);mag.push(Math.hypot(re,im));}
  return {R,real,imag,mag};
}
function renderProcessed(){const p=state.processed;
  $('athena-metrics').innerHTML=metric('E₀',`${p.e0.toFixed(2)} eV`)+metric('Edge step',p.edgeStep.toPrecision(5))+metric('k range',`${p.kmin.toFixed(1)}–${p.kmax.toFixed(1)} Å⁻¹`)+metric('Points',p.E.length);
  plot('plot-energy',[{x:p.E,y:p.mu,label:'μ(E)',cls:'s1'},{x:p.E,y:p.norm,label:'normalized',cls:'s2'}],'Energy (eV)','Intensity');
  plot('plot-derivative',[{x:p.E,y:p.dnorm,label:'d(norm)/dE',cls:'s1'}],'Energy (eV)','Derivative');
  plot('plot-k',[{x:p.k,y:p.kWeighted,label:`k^${p.kw}χ(k)`,cls:'s1'}],'k (Å⁻¹)',`k^${p.kw}χ(k)`);
  plot('plot-r',[{x:p.ft.R,y:p.ft.mag,label:'|χ(R)|',cls:'s1'}],'R (Å)','|χ(R)|');
  $('fit-source').textContent=`当前实验数据：${p.name}；E₀=${p.e0.toFixed(2)} eV；k=${p.kmin}–${p.kmax} Å⁻¹`;
  refreshAnalysis();
}

async function readFeff(file,slot){
  if(!file){state.feff[slot]=null;return;}
  const text=await file.text(); let reff=null,deg=null;
  const rm=text.match(/reff\s*=\s*([0-9.+\-Ee]+)/i); if(rm)reff=parseFloat(rm[1]);
  const dm=text.match(/deg\s*=\s*([0-9.+\-Ee]+)/i); if(dm)deg=parseFloat(dm[1]);
  const rows=[];for(const line of text.split(/\r?\n/)){const p=line.trim().split(/\s+/).map(Number);if(p.length>=7&&p.slice(0,7).every(Number.isFinite))rows.push(p.slice(0,7));}
  if(rows.length<8)throw new Error('FEFF 文件中未识别到足够的 7 列路径数据。');
  if(!reff){reff=2.0;} state.feff[slot]={name:file.name,reff,deg:deg||1,rows,k:rows.map(r=>r[0]),phc:rows.map(r=>r[1]),amp:rows.map(r=>r[2]),phase:rows.map(r=>r[3]),red:rows.map(r=>r[4]),lambda:rows.map(r=>r[5]),p:rows.map(r=>r[6])};
  $(`feff${slot+1}-info`).textContent=`${file.name} · Reff=${reff.toFixed(4)} Å · deg=${(deg||1).toFixed(2)} · ${rows.length} 点`;
}
$('feff1').addEventListener('change',async e=>{try{await readFeff(e.target.files[0],0);}catch(err){setMsg('fit-message',err.message,'error');}});
$('feff2').addEventListener('change',async e=>{try{await readFeff(e.target.files[0],1);}catch(err){setMsg('fit-message',err.message,'error');}});

function pathChi(path,k,N,dR,sig2,de0,s02){
  const R=Math.max(.5,path.reff+dR), k2=Math.max(0,k*k-de0/C_K), ke=Math.sqrt(k2); if(ke<.05)return 0;
  const amp=interp1(path.k,path.amp,ke), phc=interp1(path.k,path.phc,ke), phase=interp1(path.k,path.phase,ke), red=interp1(path.k,path.red,ke), lam=Math.max(.1,interp1(path.k,path.lambda,ke));
  const A=s02*N*amp*red*Math.exp(-2*R/lam)*Math.exp(-2*sig2*ke*ke)/(ke*R*R);
  return A*Math.sin(2*ke*R+phase+phc);
}
function fitObjective(par){const p=state.processed, [N1,dR1,s1,N2,dR2,s2,de0]=par, s02=num('s02',.9);let ss=0,sy=0,n=0;
  for(let i=0;i<p.k.length;i++){const k=p.k[i];if(k<p.kmin||k>p.kmax)continue;let m=pathChi(state.feff[0],k,N1,dR1,s1,de0,s02);if(state.feff[1])m+=pathChi(state.feff[1],k,N2,dR2,s2,de0,s02);const d=p.chi[i]-m;ss+=d*d;sy+=p.chi[i]*p.chi[i];n++;}
  return {score:ss/(sy||1e-15),n};
}
function coordinateFit(){
  let par=[num('n1',4),num('dr1',0),num('sig1',.005),num('n2',4),num('dr2',0),num('sig2',.006),num('de0',0)];
  const lo=[0,-.5,.0001,0,-.5,.0001,-20], hi=[30,.5,.03,30,.5,.03,20]; let step=[2,.03,.0015,2,.03,.0015,2];
  if(!state.feff[1]){par[3]=0;step[3]=step[4]=step[5]=0;}
  let best=fitObjective(par).score; const rounds=Math.round(num('fit-iterations',9));
  for(let r=0;r<rounds;r++){
    for(let j=0;j<par.length;j++){if(step[j]===0)continue;let local=best,bp=par[j];for(const dir of [-1,1]){const cand=[...par];cand[j]=Math.min(hi[j],Math.max(lo[j],par[j]+dir*step[j]));const s=fitObjective(cand).score;if(s<local){local=s;bp=cand[j];}}par[j]=bp;best=local;}
    step=step.map(s=>s*.58);
  }
  return {par,rfactor:best};
}
$('fit-form').addEventListener('submit',e=>{e.preventDefault();try{
  if(!state.processed)throw new Error('请先在 Athena 页处理实验数据。'); if(!state.feff[0])throw new Error('请至少上传第一条 FEFF 路径文件。');
  setMsg('fit-message','正在浏览器中拟合…'); const res=coordinateFit(); const [N1,dR1,s1,N2,dR2,s2,de0]=res.par; const p=state.processed,s02=num('s02',.9),model=p.k.map(k=>pathChi(state.feff[0],k,N1,dR1,s1,de0,s02)+(state.feff[1]?pathChi(state.feff[1],k,N2,dR2,s2,de0,s02):0)); const kwModel=model.map((v,i)=>v*Math.pow(p.k[i],p.kw)); const ftModel=fourierTransform(p.k,kwModel,p.kmin,p.kmax,num('rmax',6));
  state.fit={params:{N1,dR1,sig1:s1,R1:state.feff[0].reff+dR1,N2,dR2,sig2:s2,R2:state.feff[1]?state.feff[1].reff+dR2:null,de0,s02,Rfactor:res.rfactor},model,kwModel,ftModel}; renderFit();setMsg('fit-message',`拟合完成，R-factor=${res.rfactor.toExponential(3)}`,'ok');
}catch(err){setMsg('fit-message',err.message,'error');}});
function renderFit(){const f=state.fit,p=state.processed, q=f.params;
  $('fit-metrics').innerHTML=metric('R-factor',q.Rfactor.toExponential(3))+metric('ΔE₀',`${q.de0.toFixed(2)} eV`)+metric('Path 1 R',`${q.R1.toFixed(4)} Å`)+(q.R2?metric('Path 2 R',`${q.R2.toFixed(4)} Å`):'');
  plot('plot-fit-k',[{x:p.k,y:p.kWeighted,label:'data',cls:'s1'},{x:p.k,y:f.kwModel,label:'fit',cls:'s2'}],'k (Å⁻¹)',`k^${p.kw}χ(k)`);
  plot('plot-fit-r',[{x:p.ft.R,y:p.ft.mag,label:'data',cls:'s1'},{x:f.ftModel.R,y:f.ftModel.mag,label:'fit',cls:'s2'}],'R (Å)','|χ(R)|');
  let rows=[['Path 1',q.N1,q.R1,q.sig1]];if(state.feff[1])rows.push(['Path 2',q.N2,q.R2,q.sig2]);$('fit-table').innerHTML=`<table class="fit-table"><thead><tr><th>Path</th><th>CN</th><th>R (Å)</th><th>σ² (Å²)</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r[0]}</td><td>${r[1].toFixed(3)}</td><td>${r[2].toFixed(5)}</td><td>${r[3].toFixed(6)}</td></tr>`).join('')}</tbody></table>`;refreshAnalysis();
}

function plot(id,series,xlabel,ylabel){const el=$(id);if(!series.length||!series[0].x.length){el.innerHTML='<p class="hint">无数据</p>';return;}const W=900,H=280,m={l:58,r:20,t:25,b:44};let xs=[],ys=[];series.forEach(s=>{xs=xs.concat(s.x.filter(Number.isFinite));ys=ys.concat(s.y.filter(Number.isFinite));});let xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);if(xmax===xmin)xmax=xmin+1;if(ymax===ymin)ymax=ymin+1;const px=x=>m.l+(x-xmin)/(xmax-xmin)*(W-m.l-m.r),py=y=>H-m.b-(y-ymin)/(ymax-ymin)*(H-m.t-m.b);let svg=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
  for(let i=0;i<=5;i++){const x=xmin+(xmax-xmin)*i/5,y=ymin+(ymax-ymin)*i/5;svg+=`<line class="gridline" x1="${px(x)}" y1="${m.t}" x2="${px(x)}" y2="${H-m.b}"/><text x="${px(x)}" y="${H-18}" text-anchor="middle">${fmt(x)}</text><line class="gridline" x1="${m.l}" y1="${py(y)}" x2="${W-m.r}" y2="${py(y)}"/><text x="${m.l-8}" y="${py(y)+4}" text-anchor="end">${fmt(y)}</text>`;}
  svg+=`<line class="axis" x1="${m.l}" y1="${H-m.b}" x2="${W-m.r}" y2="${H-m.b}"/><line class="axis" x1="${m.l}" y1="${m.t}" x2="${m.l}" y2="${H-m.b}"/><text x="${(m.l+W-m.r)/2}" y="${H-3}" text-anchor="middle">${xlabel}</text><text x="14" y="${H/2}" transform="rotate(-90 14 ${H/2})" text-anchor="middle">${ylabel}</text>`;
  series.forEach((s,si)=>{let d='';for(let i=0;i<s.x.length;i++){const x=s.x[i],y=s.y[i];if(!Number.isFinite(x)||!Number.isFinite(y))continue;d+=`${d?'L':'M'}${px(x).toFixed(2)},${py(y).toFixed(2)}`;}svg+=`<path class="series ${s.cls||('s'+(si+1))}" d="${d}"/>`;svg+=`<text x="${W-150}" y="${18+si*16}">${s.label||''}</text>`;});svg+='</svg>';el.innerHTML=svg;}
function fmt(v){const a=Math.abs(v);return (a>=1000||a<.001&&a>0)?v.toExponential(2):v.toFixed(a<10?2:1);}
function metric(k,v){return `<div class="metric"><div class="k">${k}</div><div class="v">${v}</div></div>`;}
function setMsg(id,text,type=''){const el=$(id);el.textContent=text;el.className='message'+(type?' '+type:'');}

function download(name,text,type='text/plain'){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);}
$('download-processed').addEventListener('click',()=>{if(!state.processed)return alert('尚无处理结果');const p=state.processed;let s='Energy_eV,mu,norm,dnorm\n';for(let i=0;i<p.E.length;i++)s+=`${p.E[i]},${p.mu[i]},${p.norm[i]},${p.dnorm[i]}\n`;s+='\nk_A^-1,chi,kweighted\n';for(let i=0;i<p.k.length;i++)s+=`${p.k[i]},${p.chi[i]},${p.kWeighted[i]}\n`;download('xafs_processed.csv',s,'text/csv');});
$('download-fit').addEventListener('click',()=>{if(!state.fit)return alert('尚无拟合结果');const p=state.processed,f=state.fit;let s='k_A^-1,chi_data,chi_fit,kweighted_data,kweighted_fit\n';for(let i=0;i<p.k.length;i++)s+=`${p.k[i]},${p.chi[i]},${f.model[i]},${p.kWeighted[i]},${f.kwModel[i]}\n`;download('xafs_fit.csv',s,'text/csv');});
$('download-report').addEventListener('click',()=>{download('xafs_project.json',JSON.stringify({processed:state.processed?{name:state.processed.name,e0:state.processed.e0,edgeStep:state.processed.edgeStep,kmin:state.processed.kmin,kmax:state.processed.kmax,kw:state.processed.kw,params:state.processed.params}:null,fit:state.fit?state.fit.params:null,feff:state.feff.map(x=>x?{name:x.name,reff:x.reff,deg:x.deg}:null),generated:new Date().toISOString()},null,2),'application/json');});
function refreshAnalysis(){let s='Open XAFS Workbench project summary\n';if(state.processed){const p=state.processed;s+=`\nDataset: ${p.name}\nE0: ${p.e0.toFixed(3)} eV\nEdge step: ${p.edgeStep}\nk range: ${p.kmin}–${p.kmax} Å^-1\nk-weight: ${p.kw}\n`;}else s+='\nNo processed dataset.\n';if(state.fit){const q=state.fit.params;s+=`\nFit R-factor: ${q.Rfactor}\nDelta E0: ${q.de0} eV\nPath1: CN=${q.N1}, R=${q.R1} Å, sigma2=${q.sig1} Å^2\n`;if(q.R2)s+=`Path2: CN=${q.N2}, R=${q.R2} Å, sigma2=${q.sig2} Å^2\n`;}else s+='\nNo FEFF fit yet.\n';$('analysis-summary').textContent=s;}

const edges={Cr:{K:5989,L3:574},Mn:{K:6539,L3:638.7},Fe:{K:7112,L3:706.8},Co:{K:7709,L3:778.1},Ni:{K:8333,L3:852.7},Cu:{K:8979,L3:932.7},Mo:{K:20000,L3:2520},Ru:{K:22117,L3:2838},Ir:{K:76111,L3:11215},Pt:{K:78395,L3:11564}};
function updateEdge(){const e=$('element-select').value,edge=$('edge-select').value;$('edge-energy').value=edges[e]?.[edge]??'N/A';}
$('element-select').addEventListener('change',updateEdge);$('edge-select').addEventListener('change',updateEdge);updateEdge();refreshAnalysis();
