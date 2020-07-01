# deafrica_phenology.py
"""
This script contains functions for calculating land-surface 
phenology metrics on a time series of a vegetations index
stored within an xarray.DataArray.
----------  
TO DO:
- implement xr.polyfit once xarray releases version 0.16
- Handle dask arrays once xarray releases version 0.16
- Implement intergal-of-season statistic
"""


import sys
import dask
import numpy as np
import xarray as xr
import hdstats
sys.path.append('../Scripts')
from deafrica_datahandling import first, last

def allNaN_arg(da, dim, stat):
    """
    Calculate da.argmax() or da.argmin() while handling
    all-NaN slices. Fills all-NaN locations with an
    float and then masks the offending cells.

    Params
    ------
    xarr : xarray.DataArray
    dim : str, 
            Dimension over which to calculate argmax, argmin e.g. 'time'
    stat : str,
        The statistic to calculte, either 'min' for argmin()
        or 'max' for .argmax()
    Returns
    ------
    xarray.DataArray
    """
    # generate a mask where entire axis along dimension is NaN
    mask = da.isnull().all(dim)

    if stat == 'max':
        y = da.fillna(float(da.min() - 1))
        y = y.argmax(dim=dim, skipna=True).where(~mask)
        return y

    if stat == 'min':
        y = da.fillna(float(da.max() + 1))
        y = y.argmin(dim=dim, skipna=True).where(~mask)
        return y

def _vpos(da):
    """
    vPOS = Value at peak of season
    """
    return da.max('time')


def _pos(da):
    """
    POS = DOY of peak of season
    """ 
    return da.isel(time=da.argmax('time')).time.dt.dayofyear


def _trough(da):
    """
    Trough = Minimum value
    """
    return da.min('time')


def _aos(vpos, trough):
    """
    AOS = Amplitude of season
    """
    return vpos - trough


def _vsos(da, pos, method_sos='first'):
    """
    vSOS = Value at the start of season
    Params
    -----
    da : xarray.DataArray
    method_sos : str, 
        If 'first' then vSOS is estimated
        as the first positive slope on the
        greening side of the curve. If 'median',
        then vSOS is estimated as the median value
        of the postive slopes on the greening side
        of the curve.
    """
    # select timesteps before peak of season (AKA greening)
    greenup = da.where(da.time < pos.time)
    # find the first order slopes
    green_deriv = greenup.differentiate('time')
    # find where the first order slope is postive
    pos_green_deriv = green_deriv.where(green_deriv > 0)
    # positive slopes on greening side
    pos_greenup = greenup.where(pos_green_deriv)
    # find the median
    median = pos_greenup.median('time')
    # distance of values from median
    distance = pos_greenup - median
    
    if method_sos == 'first':
        # find index (argmin) where distance is most negative
        idx = allNaN_arg(distance, 'time', 'min').astype('int16')

    if method_sos == 'median':
        # find index (argmin) where distance is smallest absolute value
        idx = allNaN_arg(xr.ufuncs.fabs(distance), 'time', 'min').astype('int16')
    
    return pos_greenup.isel(time=idx)


def _sos(vsos):
    """
    SOS = DOY for start of season
    """
    return vsos.time.dt.dayofyear


def _veos(da, pos, method_eos='last'):
    """
    vEOS = Value at the start of season
    Params
    -----
    method_eos : str
        If 'first' then vEOS is estimated
        as the last negative slope on the
        senescing side of the curve. If 'median',
        then vEOS is estimated as the 'median' value
        of the negative slopes on the senescing 
        side of the curve.
    """
    # select timesteps before peak of season (AKA greening)
    senesce = da.where(da.time > pos.time)
    # find the first order slopes
    senesce_deriv = senesce.differentiate('time')
    # find where the fst order slope is postive
    neg_senesce_deriv = senesce_deriv.where(senesce_deriv < 0)
    # negative slopes on senescing side
    neg_senesce = senesce.where(neg_senesce_deriv)
    # find medians
    median = neg_senesce.median('time')
    # distance to the median
    distance = neg_senesce - median

    if method_eos == 'last':
        # index where last negative slope occurs
        idx = allNaN_arg(distance, 'time', 'min').astype('int16')
    
    if method_eos == 'median':
        # index where median occurs
        idx = allNaN_arg(xr.ufuncs.fabs(distance), 'time', 'min').astype('int16')
    
    return neg_senesce.isel(time=idx)


def _eos(veos):
    """
    EOS = DOY for end of seasonn
    """
    return veos.time.dt.dayofyear


def _los(da, eos, sos):
    """
    LOS = Length of season (in DOY)
    """
    los = eos - sos
    # handle negative values
    los = xr.where(
        los >= 0,
        los, 
        da.time.dt.dayofyear.values[-1] +
        (eos.where(los < 0) - sos.where(los < 0)))

    return los


def _rog(vpos, vsos, pos, sos):
    """
    ROG = Rate of Greening (Days)
    """
    return (vpos - vsos) / (pos - sos)


def _ros(veos, vpos, eos, pos):
    """
    ROG = Rate of Senescing (Days)
    """
    return (veos - vpos) / (eos - pos)


def xr_phenology(da,
                 stats=[
                     'SOS', 'POS', 'EOS', 'Trough', 'vSOS', 
                     'vPOS', 'vEOS', 'LOS', 'AOS', 'ROG', 'ROS'
                 ],
                 method_sos='median',
                 method_eos='median',
                 complete_smooth=True,
                 ):
    
    """
    Obtain land surface phenology metrics from an
    xarray.DataArray containing a timeseries of a 
    vegetation index like NDVI.
    last modified June 2020
    
    Parameters
    ----------
    da :  xarray.DataArray
        DataArray should contain a 2 or 3D time series of a
        vegetation index like NDVI
    stats : list
        list of phenological statistics to return. Regardless of
        the metrics returned, all statistics are calculated
        due to inter-dependencies between metrics.
        Options include:
            SOS = DOY of start of season
            POS = DOY of peak of season
            EOS = DOY of end of season
            vSOS = Value at start of season
            vPOS = Value at peak of season
            vEOS = Value at end of season
            Trough = Minimum value of season
            LOS = Length of season (DOY)
            AOS = Amplitude of season (in value units)
            ROG = Rate of greening
            ROS = Rate of senescence
    method_sos : str 
        If 'first' then vSOS is estimated
        as the first positive slope on the
        greening side of the curve. If 'median',
        then vSOS is estimated as the median value
        of the postive slopes on the greening side
        of the curve.
    method_eos : str
        If 'first' then vEOS is estimated
        as the last negative slope on the
        senescing side of the curve. If 'median',
        then vEOS is estimated as the 'median' value
        of the negative slopes on the senescing 
        side of the curve.
    complete_smooth : bool
        If True, the timeseries will be completed (gap filled) using
        hdstats.fast_completion, and smoothed using
        hdstats.smooth.
    
    Outputs
    -------
        xarray.Dataset containing variables for the selected 
        phenology statistics 
    
    """
    # Check inputs before running calculations
    if dask.is_dask_collection(da):
        raise TypeError(
            "Dask arrays are not currently supported by this function, "+
            "run da.compute() before passing dataArray."
        ) 

    if method_sos not in ('median', 'first'):
        raise ValueError("method_sos should be either 'median' or 'first'")

    if method_eos not in ('median', 'last'):
        raise ValueError("method_eos should be either 'median' or 'last'")
    
    # If stats supplied is not a list, convert to list.
    stats = stats if isinstance(stats, list) else [stats]
    
    # complete and smooth the timeseries
    if complete_smooth:
        #grab coords etc
        x,y,time,attrs=da.x, da.y, da.time,da.attrs
        #reshape to satisfy function
        da = da.transpose('y', 'x', 'time').values
        #complete timeseries
        print('Completing...')
        da = hdstats.fast_completion(da)
        #smooth using weiner filter
        print('   Smoothing...')
        da = hdstats.smooth(da)
        #place back into xarray
        da = xr.DataArray(da,
                          attrs=attrs,
                          coords={'x':x, 'y':y, 'time':time},
                          dims=['y', 'x', 'time'])
    
    #remove any remaining all-NaN pixels 
    mask = da.isnull().all('time')
    da = da.where(~mask, other=0)
    
    #calculate the statistics
    print('      Phenology...')
    vpos = _vpos(da)
    pos = _pos(da)
    trough = _trough(da)
    aos = _aos(vpos, trough)
    vsos = _vsos(da, pos, method_sos=method_sos)
    sos = _sos(vsos)
    veos = _veos(da, pos, method_eos=method_eos)
    eos = _eos(veos)
    los = _los(da, eos, sos)
    rog = _rog(vpos, vsos, pos, sos)
    ros = _ros(veos, vpos, eos, pos)

    # Dictionary containing the statistics
    stats_dict = {
        'SOS': sos.astype(np.int16),
        'EOS': eos.astype(np.int16),
        'vSOS': vsos.astype(np.float32),
        'vPOS': vpos.astype(np.float32),
        'Trough': trough.astype(np.float32),
        'POS': pos.astype(np.int16),
        'vEOS': veos.astype(np.float32),
        'LOS': los.astype(np.int16),
        'AOS': aos.astype(np.float32),
        'ROG': rog.astype(np.float32),
        'ROS': ros.astype(np.float32),
    }

    # intialise dataset with first statistic
    ds = stats_dict[stats[0]].to_dataset(name=stats[0])

    # add the other stats to the dataset
    for stat in stats[1:]:
        stats_keep = stats_dict.get(stat)
        ds[stat] = stats_dict[stat]

    return ds


def temporal_statistics(da, stats):
    
    """
    Obtain temporal statistics using the hdstats temporal
    library:
    https://github.com/daleroberts/hdstats/blob/master/hdstats/ts.pyx
    
    last modified June 2020
    
    Parameters
    ----------
    da :  xarray.DataArray
        DataArray should contain a 3D time series of a
        vegetation index like NDVI
    stats : list
        list of temporal statistics to calculate.
        Options include:
            discordance
            f_std
            f_mean
            f_median
            mean_change
            median_change
            abs_change 
            complexity
            central_diff
            num_peaks
    
    Outputs
    -------
        xarray.Dataset containing variables for the selected 
        temporal statistics 
        
    """

    #grab all the attributes of the xarray
    x,y,time,attrs=da.x, da.y, da.time,da.attrs

    #reshape to satisfy functions
    da = da.transpose('y', 'x', 'time').values

    #complete timeseries
    print('Completing...')
    da = hdstats.fast_completion(da)

    stats_dict = {
        'discordance' : lambda da : hdstats.discordance(da, n=10),
        'f_std_n1' : lambda da: hdstats.fourier_std(da, n=3, step=5)[:,:,0],
        'f_std_n2' : lambda da: hdstats.fourier_std(da, n=3, step=5)[:,:,1],
        'f_std_n3' : lambda da: hdstats.fourier_std(da, n=3, step=5)[:,:,2],
        'f_mean_n1' : lambda da: hdstats.fourier_mean(da, n=3, step=5)[:,:,0],
        'f_mean_n2' : lambda da: hdstats.fourier_mean(da, n=3, step=5)[:,:,1],
        'f_mean_n3' : lambda da: hdstats.fourier_mean(da, n=3, step=5)[:,:,2],
        'f_median_n1' : lambda da: hdstats.fourier_median(da, n=3, step=5)[:,:,0],
        'f_median_n2' : lambda da: hdstats.fourier_median(da, n=3, step=5)[:,:,1],
        'f_median_n3' : lambda da: hdstats.fourier_median(da, n=3, step=5)[:,:,2],
        'mean_change' : lambda da: hdstats.mean_change(da),
        'median_change' : lambda da: hdstats.median_change(da),
        'abs_change' : lambda da: hdstats.mean_abs_change(da),
        'complexity' : lambda da: hdstats.complexity(da),
        'central_diff' : lambda da: hdstats.mean_central_diff(da),
        'num_peaks' : lambda da: hdstats.number_peaks(da, 10)
    }

    # If stats supplied is not a list, convert to list.
    stats = stats if isinstance(stats, list) else [stats]

    #intialise dataset with first statistic and
    print('   Statistics:')
    first_func = stats_dict.get(str(stats[0]))
    print("      "+stats[0])
    ds = first_func(da)

    #convert back to xarray dataset
    ds = xr.DataArray(ds,
                      attrs=attrs,
                      coords={'x':x, 'y':y},
                      dims=['y', 'x']).to_dataset(name=stats[0])

    for stat in stats[1:]:
        print("      "+stat)

        # Select an index function from the dictionary
        stat_func = stats_dict.get(str(stat))
        ds[stat] = xr.DataArray(stat_func(da),
                      attrs=attrs,
                      coords={'x':x, 'y':y},
                      dims=['y', 'x'])

    return ds
    
