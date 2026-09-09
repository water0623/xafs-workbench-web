// UI enhancement layer for Athena-style workflow
(function(){
'use strict';
const panel=document.querySelector('.controls');
if(!panel)return;
const box=document.createElement('div');
box.className='advanced-controls';
box.innerHTML=`
<h3>Pre-edge / Normalization</h3>
<label>E0 (eV)<input id="e0" value="" placeholder="auto"></label>
<label><input id="auto-e0" type="checkbox" checked> 自动识别 E0</label>
<label>Pre-edge range <input id="pre1" value="-150"> ~ <input id="pre2" value="-30"></label>
<label>Normalization range <input id="norm1" value="150"> ~ <input id="norm2" value="700"></label>
<h3>EXAFS</h3>
<label>k weighting<select id="kweight"><option value="1">k¹</option><option value="2" selected>k²</option><option value="3">k³</option></select></label>
<label>k max<input id="kmax" value="12"></label>
<label>R max<input id="rmax" value="6"></label>
<button id="run-athena" type="button">开始 Athena 处理</button>
`;
panel.appendChild(box);
const btn=document.getElementById('run-athena');
if(btn){btn.onclick=()=>document.getElementById('process-form').dispatchEvent(new Event('submit',{cancelable:true}));}
})();
