"""
Package for processing with autoRIFT ICSE
"""

import argparse
import glob
import logging
import os
import shutil
from pathlib import Path

import numpy as np
from hyp3lib.execute import execute
from hyp3lib.file_subroutines import mkdir_p
from hyp3lib.get_orb import downloadSentinelOrbitFile
from hyp3lib.makeAsfBrowse import makeAsfBrowse
from osgeo import gdal

from hyp3_autorift import geometry
from hyp3_autorift import io

log = logging.getLogger(__name__)

_PRODUCT_LIST = [
    'offset.tif',
    'velocity.tif',
    'velocity_browse.tif',
    'velocity_browse.kmz',
    'velocity_browse.png',
    'velocity_browse.png.aux.xml',
    'window_chip_size_max.tif',
    'window_chip_size_min.tif',
    'window_location.tif',
    'window_offset.tif',
    'window_rdr_off2vel_x_vec.tif',
    'window_rdr_off2vel_y_vec.tif',
    'window_search_range.tif',
    'window_stable_surface_mask.tif',
]


def process(reference, secondary, download=False, polarization='hh', orbits=None, aux=None, process_dir=None,
            product=False):
    """Process a Sentinel-1 image pair

    Args:
        reference: Path to reference Sentinel-1 SAFE zip archive
        secondary: Path to secondary Sentinel-1 SAFE zip archive
        download: If True, try and download the granules from ASF to the
            current working directory (default: False)
        polarization: Polarization of Sentinel-1 scene (default: 'hh')
        orbits: Path to the orbital files, otherwise, fetch them from ASF
            (default: None)
        aux: Path to the auxiliary orbital files, otherwise, assume same as orbits
            (default: None)
        process_dir: Path to a directory for processing inside
            (default: None; use current working directory)
        product: Create a product directory in the current working directory with
            copies of the product-level files (no intermediate files; default: False)
    """

    # Ensure we have absolute paths
    reference = Path(reference).resolve()
    secondary = Path(secondary).resolve()

    product_dir = os.path.join(os.getcwd(), 'PRODUCT')

    if not reference.is_file() or not secondary.is_file() and download:
        log.info('Downloading Sentinel-1 image pair')
        dl_file_list = 'download_list.csv'
        with open('download_list.csv', 'w') as f:
            f.write(f'{reference.name}\n'
                    f'{secondary.name}\n')

        execute(f'get_asf.py {dl_file_list}')
        os.rmdir('download')  # Really, get_asf.py should do this...

    if orbits is None:
        orbits = Path('Orbits').resolve()
        mkdir_p(orbits)
        reference_state_vec, reference_provider = downloadSentinelOrbitFile(reference.stem, directory=orbits)
        log.info(f'Downloaded orbit file {reference_state_vec} from {reference_provider}')
        secondary_state_vec, secondary_provider = downloadSentinelOrbitFile(secondary.stem, directory=orbits)
        log.info(f'Downloaded orbit file {secondary_state_vec} from {secondary_provider}')

    if aux is None:
        aux = orbits

    lat_limits, lon_limits = geometry.bounding_box(
        str(reference), orbits=orbits, aux=aux, polarization=polarization
    )

    dem = geometry.find_jpl_dem(lat_limits, lon_limits, download=download)

    if download:
        io.fetch_jpl_tifs(ice_sheet=os.path.basename(dem)[:3])

    if process_dir:
        mkdir_p(process_dir)
        os.chdir(process_dir)

    isce_dem = geometry.prep_isce_dem(dem, lat_limits, lon_limits)

    io.format_tops_xml(reference, secondary, polarization, isce_dem, orbits, aux)

    with open('topsApp.txt', 'w') as f:
        cmd = '${ISCE_HOME}/applications/topsApp.py topsApp.xml --end=mergebursts'
        execute(cmd, logfile=f, uselogging=True)

    m_slc = os.path.join(os.getcwd(), 'merged', 'reference.slc.full')
    s_slc = os.path.join(os.getcwd(), 'merged', 'secondary.slc.full')

    with open('createImages.txt', 'w') as f:
        for slc in [m_slc, s_slc]:
            cmd = f'gdal_translate -of ENVI {slc}.vrt {slc}'
            execute(cmd, logfile=f, uselogging=True)

    in_file_base = dem.replace('_h.tif', '')
    with open('testGeogrid.txt', 'w') as f:
        cmd = f'testGeogrid_ISCE.py -r reference -s secondary' \
              f' -d {dem} -ssm {in_file_base}_StableSurface.tif' \
              f' -sx {in_file_base}_dhdx.tif -sy {in_file_base}_dhdy.tif' \
              f' -vx {in_file_base}_vx0.tif -vy {in_file_base}_vy0.tif' \
              f' -srx {in_file_base}_vxSearchRange.tif -sry {in_file_base}_vySearchRange.tif' \
              f' -csminx {in_file_base}_xMinChipSize.tif -csminy {in_file_base}_yMinChipSize.tif' \
              f' -csmaxx {in_file_base}_xMaxChipSize.tif -csmaxy {in_file_base}_yMaxChipSize.tif'
        execute(cmd, logfile=f, uselogging=True)

    with open('testautoRIFT.txt', 'w') as f:
        cmd = f'testautoRIFT_ISCE.py' \
              f' -r {m_slc} -s {s_slc} -g window_location.tif -o window_offset.tif' \
              f' -sr window_search_range.tif -csmin window_chip_size_min.tif -csmax window_chip_size_max.tif' \
              f' -vx window_rdr_off2vel_x_vec.tif -vy window_rdr_off2vel_y_vec.tif' \
              f'-ssm window_stable_surface_mask.tif -nc S'
        execute(cmd, logfile=f, uselogging=True)

    velocity_tif = gdal.Open('velocity.tif')
    x_velocity = np.ma.masked_invalid(velocity_tif.GetRasterBand(1).ReadAsArray())
    y_velocity = np.ma.masked_invalid(velocity_tif.GetRasterBand(2).ReadAsArray())
    velocity = np.sqrt(x_velocity**2 + y_velocity**2)

    browse_file = Path('velocity_browse.tif')
    driver = gdal.GetDriverByName('GTiff')
    browse_tif = driver.Create(
        str(browse_file), velocity.shape[1], velocity.shape[0], 1, gdal.GDT_Byte, ['COMPRESS=LZW']
    )
    browse_tif.SetProjection(velocity_tif.GetProjection())
    browse_tif.SetGeoTransform(velocity_tif.GetGeoTransform())
    velocity_band = browse_tif.GetRasterBand(1)
    velocity_band.WriteArray(velocity)

    del velocity_band, browse_tif, velocity_tif

    makeAsfBrowse(browse_file, browse_file.stem)

    if product:
        mkdir_p(product_dir)
        for f in _PRODUCT_LIST:
            shutil.copyfile(f, os.path.join(product_dir, f))

        for f in glob.iglob('*.nc'):
            shutil.copyfile(f, os.path.join(product_dir, f))


def main():
    """Main entrypoint"""
    parser = argparse.ArgumentParser(
        prog=os.path.basename(__file__),
        description=__doc__,
    )
    parser.add_argument('reference', type=os.path.abspath,
                        help='Reference Sentinel-1 SAFE zip archive')
    parser.add_argument('secondary', type=os.path.abspath,
                        help='Secondary Sentinel-1 SAFE zip archive')
    parser.add_argument('-d', '--download', action='store_true',
                        help='Download the granules from ASF to the current'
                             'working directory')
    parser.add_argument('-p', '--polarization', default='hh',
                        help='Polarization of the Sentinel-1 scenes')
    parser.add_argument('--orbits', type=os.path.abspath,
                        help='Path to the Sentinel-1 orbital files. If this argument'
                             'is not give, process will try and download them from ASF')
    parser.add_argument('--aux', type=os.path.abspath,
                        help='Path to the Sentinel-1 auxiliary orbital files. If this argument'
                             'is not give, process will try and download them from ASF')
    parser.add_argument('--process-dir', type=os.path.abspath,
                        help='If given, do processing inside this directory, otherwise, '
                             'use the current working directory')
    parser.add_argument('--product', action='store_true',
                        help='Create a product directory in the current working directory '
                             'with copies of the product-level files (no intermediate files)')
    args = parser.parse_args()

    process(**args.__dict__)


if __name__ == "__main__":
    main()
