// Athena display v2: raw spectrum first, normalized spectrum second.
(function(){
  'use strict';
  window.renderProcessed = function(){
    const p = state.processed;
    $('athena-metrics').innerHTML =
      metric('E₀', `${p.e0.toFixed(2)} eV`) +
      metric('Edge step', p.edgeStep.toPrecision(5)) +
      metric('k range', `${p.kmin.toFixed(1)}–${p.kmax.toFixed(1)} Å⁻¹`) +
      metric('Points', p.E.length) +
      metric('清理/截取', `${p.removed || 0} 点`) +
      metric('FT 窗口', `${p.params.window}, dk=${p.params.dk}`);

    // Athena-style sequence: raw μ(E) first, normalized μ(E) second.
    plot('plot-raw-energy', [
      {x:p.E, y:p.mu, label:'Raw μ(E)', cls:'s1'}
    ], 'Energy (eV)', 'μ(E)');

    plot('plot-normalized-energy', [
      {x:p.E, y:p.norm, label:'Normalized μ(E)', cls:'s2'}
    ], 'Energy (eV)', 'Normalized μ(E)');

    plot('plot-derivative', [
      {x:p.E, y:p.dnorm, label:'d(norm)/dE', cls:'s1'}
    ], 'Energy (eV)', 'Derivative');

    plot('plot-k', [
      {x:p.k, y:p.kWeighted, label:`k^${p.kw}χ(k)`, cls:'s1'}
    ], 'k (Å⁻¹)', `k^${p.kw}χ(k)`);

    window.renderRSpace();

    $('fit-source').textContent = `当前实验数据：${p.name}；E₀=${p.e0.toFixed(2)} eV；k=${p.kmin}–${p.kmax} Å⁻¹`;
    refreshAnalysis();
  };

  window.renderRSpace = function(){
    const p=state.processed;if(!p)return;
    const series=[];
    if($('show-r-mag').checked)series.push({x:p.ft.R,y:p.ft.mag,label:'|χ(R)|',cls:'s1'});
    if($('show-r-real').checked)series.push({x:p.ft.R,y:p.ft.real,label:'Re χ(R)',cls:'s2'});
    if($('show-r-imag').checked)series.push({x:p.ft.R,y:p.ft.imag,label:'Im χ(R)',cls:'s3'});
    plot('plot-r',series.length?series:[{x:p.ft.R,y:p.ft.mag,label:'|χ(R)|',cls:'s1'}],'R (Å)','χ(R)');
  };
  ['show-r-mag','show-r-real','show-r-imag'].forEach(id=>$(id).addEventListener('change',()=>window.renderRSpace()));
})();
