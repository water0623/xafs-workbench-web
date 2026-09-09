// Athena advanced controls: energy calibration, peak alignment, background/normalization helpers
(function(){
'use strict';
window.AthenaAdvanced={
 calibrate:function(e0Measured,e0Reference){return Number(e0Reference)-Number(e0Measured);},
 applyShift:function(E,shift){return E.map(v=>v+shift);},
 polynomial:function(x,y,order){
  const n=x.length,m=order+1,A=Array.from({length:m},()=>Array(m).fill(0)),b=Array(m).fill(0);
  for(let i=0;i<n;i++)for(let j=0;j<m;j++){b[j]+=y[i]*Math.pow(x[i],j);for(let k=0;k<m;k++)A[j][k]+=Math.pow(x[i],j+k);}
  for(let i=0;i<m;i++){let p=i;for(let j=i+1;j<m;j++)if(Math.abs(A[j][i])>Math.abs(A[p][i]))p=j;[A[i],A[p]]=[A[p],A[i]];[b[i],b[p]]=[b[p],b[i]];let d=A[i][i]||1e-12;for(let j=i;j<m;j++)A[i][j]/=d;b[i]/=d;for(let j=0;j<m;j++){if(j===i)continue;let f=A[j][i];for(let k=i;k<m;k++)A[j][k]-=f*A[i][k];b[j]-=f*b[i];}}
  return b;
 },
 subtractBackground:function(E,mu,start,end){
   const ids=E.map((v,i)=>v>=start&&v<=end?i:-1).filter(i=>i>=0);
   const c=this.polynomial(ids.map(i=>E[i]),ids.map(i=>mu[i]),2);
   return mu.map((v,i)=>v-(c[0]+c[1]*E[i]+c[2]*E[i]*E[i]));
 }
};
})();
