'use strict';
/* Athena-like XAFS column detector */
window.XAFSParser = {
  detect(rows, header=[]) {
    const names = header.map(x=>String(x).toLowerCase());
    const find = keys => { for (const k of keys) { const i=names.findIndex(n=>n.includes(k)); if(i>=0) return i; } return -1; };
    const energy = find(['energy','e(ev)','e ']);
    const mu = find(['mu','xmu','μ']);
    const norm = find(['norm','normalized']);
    const i0 = find(['i0','i_0']);
    const it = find(['it','i_t']);
    return {
      energy: energy>=0?energy:0,
      mu: mu>=0?mu:null,
      norm: norm>=0?norm:null,
      i0: i0>=0?i0:null,
      it: it>=0?it:null,
      columns: rows[0]?.length || 0
    };
  },
  preview(rows, mapping){
    return {
      energy: mapping.energy,
      mu: mapping.mu,
      norm: mapping.norm,
      i0: mapping.i0,
      it: mapping.it,
      columns:mapping.columns
    };
  }
};
