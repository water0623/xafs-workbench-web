"""XAS input parser for common synchrotron text formats."""
import numpy as np


def load_ascii_xas(text):
    lines = text.decode(errors='ignore').splitlines() if isinstance(text, bytes) else text.splitlines()
    rows=[]
    for line in lines:
        if not line.strip() or line.lstrip().startswith(('#','%')):
            continue
        try:
            vals=[float(x) for x in line.replace(',',' ').split()]
            if len(vals)>=2:
                rows.append(vals)
        except ValueError:
            continue
    if len(rows)<5:
        raise ValueError('No valid XAS numerical data found')
    arr=np.asarray(rows,float)
    return {
        'energy':arr[:,0],
        'mu':arr[:,1],
        'columns':arr.tolist(),
        'n_columns':arr.shape[1]
    }
