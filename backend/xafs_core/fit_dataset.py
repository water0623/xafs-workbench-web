"""Prepare Artemis-style fitting input."""
import json


def export_fit_dataset(result, filename=None):
    data={
        'k':result['k'].tolist(),
        'chi':result['chi'].tolist(),
        'kweight':result.get('kweight',2),
        'range':[float(result['k'].min()),float(result['k'].max())]
    }
    if filename:
        with open(filename,'w',encoding='utf-8') as f:
            json.dump(data,f)
    return data
