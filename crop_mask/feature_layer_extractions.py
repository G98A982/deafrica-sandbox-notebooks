
import richdem as rd
import pyproj
from odc.algo import xr_reproject
import datacube
import numpy as np
import sys
import xarray as xr

sys.path.append('../Scripts')
from deafrica_bandindices import calculate_indices
from deafrica_temporal_statistics import xr_phenology, temporal_statistics
from datacube.utils.geometry import assign_crs

def xr_terrain(da, attribute=None):
    """
    Using the richdem package, calculates terrain attributes
    on a DEM stored in memory as an xarray.DataArray 
    
    Params
    -------
    da : xr.DataArray
    attribute : str
        One of the terrain attributes that richdem.TerrainAttribute()
        has implemented. e.g. 'slope_riserun', 'slope_percentage', 'aspect'.
        See all option here:  
        https://richdem.readthedocs.io/en/latest/python_api.html#richdem.TerrainAttribute
        
    """
    #remove time if its there
    da = da.squeeze()
    #convert to richdem array
    rda = rd.rdarray(da.data, no_data=da.attrs['nodata'])
    #add projection and geotransform
    rda.projection=pyproj.crs.CRS(da.attrs['crs']).to_wkt()
    rda.geotransform = da.geobox.affine.to_gdal()
    #calulate attribute
    attrs = rd.TerrainAttribute(rda, attrib=attribute)

    #return as xarray DataArray
    return xr.DataArray(attrs,
                        attrs=da.attrs,
                        coords={'x':da.x, 'y':da.y},
                        dims=['y', 'x'])


def crop_features(ds):
    dc = datacube.Datacube(app='training')
    data = calculate_indices(ds,
                             index=['NDVI'],
                             drop=True,
                             collection='s2')
    
    #temporal stats
#     ts = temporal_statistics(data.NDVI,
#                        stats=['f_mean', 'abs_change',
#                               'complexity','central_diff'])
    ts = xr_phenology(data.NDVI, 
                      stats=['Trough','vSOS', 'vPOS','AOS','ROG','ROS'],
                      complete='fast_completion')

    #rainfall climatology
    chirps = assign_crs(xr.open_rasterio('data/CHIRPS/CHPclim_sum.nc'),  crs='epsg:4326')
    chirps = xr_reproject(chirps,ds.geobox,"mode")
    chirps = chirps.to_dataset(name='chirps')
    
    #slope
    slope = dc.load(product='srtm', like=ds.geobox).squeeze()
    slope = slope.elevation
    slope = xr_terrain(slope, 'slope_riserun')
    slope = slope.to_dataset(name='slope')
    
    #Surface reflectance results
    sr = ds.median('time')
    result = xr.merge([ts, sr, chirps,slope], compat='override')
    result = assign_crs(result, crs=ds.geobox.crs)

    return result.squeeze()