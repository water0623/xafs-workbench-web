// Athena display helpers: keep raw and normalized spectra in separate panels.
(function(){
  'use strict';
  window.AthenaDisplay = {
    plotSeries: function(plot, raw, normalized){
      if(typeof plot !== 'function') return;
      plot('plot-raw-energy', [{x:raw.x,y:raw.y,label:'Raw μ(E)',cls:'s1'}], 'Energy (eV)', 'μ(E)');
      plot('plot-normalized-energy', [{x:normalized.x,y:normalized.y,label:'Normalized μ(E)',cls:'s2'}], 'Energy (eV)', 'Normalized μ(E)');
    }
  };
})();
