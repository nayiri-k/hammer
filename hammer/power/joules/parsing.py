from pathlib import Path
from typing import List

from hammer.vlsi.units import TimeValue, PowerValue
import numpy as np
import pandas as pd


class PowerParser():

    def profiledata_to_df(joules_fpath: Path,
                            **kwargs):
        # function arguments
        interval_ns = float(kwargs['interval_ns']) if 'interval_ns' in kwargs else None
        num_toggles = int(kwargs['num_toggles']) if 'num_toggles' in kwargs else None
        frame_count = int(kwargs['frame_count']) if 'frame_count' in kwargs else None

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

        # extract time and power units        
        l = [f for f in header_fields if f.startswith('xlabel')][0]
        time_unit = l[l.index('(')+1:l.index(')')]
        l = [f for f in header_fields if f.startswith('ylabel')][0]
        power_unit = l[l.index('(')+1:l.index(')')]

        # scale time/power values to ns/mW
        time_power = [l.split() for l in lines if len(l.split()) == len(cols) + 1]
        timescaling = TimeValue("1ns").value_in_units(time_unit,round_zeroes=False)
        time_ns = np.round(np.array([float(l[0]) for l in time_power]) / timescaling).astype(int)
        powerscaling = PowerValue("1mW").value_in_units(power_unit,round_zeroes=False)
        power = np.round(np.array([[float(p) for p in l[1:]] for l in time_power]) / powerscaling)

        # generate index
        if frame_count is not None:
            interval_ns = np.median(time_ns[1:101] - time_ns[:100])  # sufficient to compute for first 100 elements
        if interval_ns is not None:
            start_ns = time_ns - int(interval_ns//2)
            end_ns = time_ns + int(interval_ns//2)
        else:
            #   num_toggles estimates start/end time b/c we don't have info about toggle_signal...
            start_ns = [0] + list(((time_ns[1:] + time_ns[:-1])/2).astype(int))
            end_ns = list(((time_ns[1:] + time_ns[:-1])/2).astype(int)) + [time_ns[-1]]
        index = pd.MultiIndex.from_arrays([time_ns,start_ns,end_ns],names=['time_ns','start_ns','end_ns'])

        # create dataframe
        df = pd.DataFrame(power,index=index,columns=columns)
        return df
