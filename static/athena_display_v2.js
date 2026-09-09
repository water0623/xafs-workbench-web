// Athena display v2: raw spectrum first, normalized spectrum second.
(function(){
  'use strict';
  window.renderProcessed = function(){
    const p = state.processed;
    $('athena-metrics').innerHTML =
      metric('E₀', `${p.e0.toFixed(2)} eV`) +
      metric('Edge step', p.edgeStep.toPrecision(5)) +
      metric('k range', `${p.kmin.toFixed(1)}–${p.kmax.toFixed(1)} Å⁻¹`) +
      metric('Points', p.E.length);

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

    plot('plot-r', [
      {x:p.ft.R, y:p.ft.mag, label:'|χ(R)|', cls:'s1'}
    ], 'R (Å)', '|χ(R)|');

    $('fit-source').textContent = `当前实验数据：${p.name}；E₀=${p.e0.toFixed(2)} eV；k=${p.kmin}–${p.kmax} Å⁻¹`;
    refreshAnalysis();
  };
})();
