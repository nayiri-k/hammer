from pathlib import Path
from typing import List

from hammer.vlsi.units import TimeValue, PowerValue
import numpy as np
import pandas as pd


class PowerParser():

    def profiledata_to_df(joules_fpath: Path):

        # parse file
        with open(joules_fpath,'r') as f:
            lines = f.readlines()
        header = None
        if len(lines) == 0: return None
        while lines[0].startswith('# '):
            header = lines.pop(0)
            if len(lines) == 0: return None
        if header is None: 
            # joules.logger.warning(f"# Incomplete file at {joules_fpath}\n")
            return None
        header_fields = header.split(' -')

        # get column indexes
        cols = [col for field in header_fields if field.startswith('ykeylabel ') for col in field.split()[1:]]
        col_labels = [col.split(':') for col in cols]
        col_hiers = [col[0] for col in col_labels]
        col_powtype = [col[-1] for col in col_labels]
        col_powcat = [col[1].replace('__cat_','') if len(col) == 3 else 'total' for col in col_labels]
        col_names = ['hier','power_category','power_type']
        columns = pd.MultiIndex.from_arrays([col_hiers,col_powcat,col_powtype],names=col_names)

        # extract time/power units        
        l = [f for f in header_fields if f.startswith('xlabel')][0]
        time_unit = l[l.index('(')+1:l.index(')')]
        l = [f for f in header_fields if f.startswith('ylabel')][0]
        power_unit = l[l.index('(')+1:l.index(')')]

        # scale time/power values to ns/mW
        time_power = [l.split() for l in lines if len(l.split()) == len(cols) + 1]
        timescaling = TimeValue("1ns").value_in_units(time_unit,round_zeroes=False)
        time_ns = np.round(np.array([float(l[0]) for l in time_power]) / timescaling).astype(int)
        powerscaling = PowerValue("1mW").value_in_units(power_unit,round_zeroes=False)
        power = np.array([[float(p) for p in l[1:]] for l in time_power]) / powerscaling

        # generate index
        fp_start = Path(str(joules_fpath).split('.profile.')[0]+'.frames.start_times.txt')
        fp_end = Path(str(joules_fpath).split('.profile.')[0]+'.frames.end_times.txt')
        #   NOTE: Joules manual says times are written out in ns, but they are actually written in s
        with fp_start.open('r') as f: start_ns = np.round(np.array([float(t) for t in f.read().split()]) * 1e9).astype(int)
        with fp_end.open('r')   as f: end_ns   = np.round(np.array([float(t) for t in f.read().split()]) * 1e9).astype(int)
        index = pd.MultiIndex.from_arrays([time_ns,start_ns,end_ns],names=['time_ns','start_ns','end_ns'])

        # create dataframe
        df = pd.DataFrame(power,index=index,columns=columns)
        return df
