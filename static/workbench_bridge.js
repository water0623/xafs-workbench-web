"use strict";

window.XAFSWorkbench = {
  tabs(){
    document.querySelectorAll('.tab').forEach(btn=>{
      btn.onclick=()=>{
        document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b===btn));
        document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active',p.id===btn.dataset.tab));
      };
    });
  },
  metrics(data){
    const box=document.getElementById('athena-metrics');
    if(!box||!data)return;
    box.innerHTML=`<div>E0: ${Number(data.e0||0).toFixed(2)} eV</div><div>Points: ${data.E?.length||0}</div>`;
  },
  init(){this.tabs();}
};
window.addEventListener('DOMContentLoaded',()=>window.XAFSWorkbench.init());
