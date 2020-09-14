#!/usr/bin/env python3
"""
Package for processing with autoRIFT ICSE
"""

import argparse
import glob
import logging
import os
import shutil
from pathlib import Path

from hyp3lib.execute import execute
from hyp3lib.get_orb import downloadSentinelOrbitFile

from hyp3_autorift import geometry
from hyp3_autorift import io

log = logging.getLogger(__name__)

_PRODUCT_LIST = [
    'offset.tif',
    'velocity.tif',
    'window_location.tif',
    'window_offset.tif',
    'window_rdr_off2vel_x_vec.tif',
    'window_rdr_off2vel_y_vec.tif',
]


def process(master, slave, download=False, polarization='hh', orbits=None, aux=None, process_dir=None, product=False):
    """Process a Sentinel-1 image pair

    Args:
        master: Path to master Sentinel-1 SAFE zip archive
        slave: Path to slave Sentinel-1 SAFE zip archive
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
    master = Path(master).resolve()
    slave = Path(slave).resolve()

    product_dir = os.path.join(os.getcwd(), 'PRODUCT')

    if not master.is_file() or not slave.is_file() and download:
        log.info('Downloading Sentinel-1 image pair')
        dl_file_list = 'download_list.csv'
        with open('download_list.csv', 'w') as f:
            f.write(f'{master.name}\n'
                    f'{slave.name}\n')

        execute(f'get_asf.py {dl_file_list}')
        os.rmdir('download')  # Really, get_asf.py should do this...

    if orbits is None:
        orbits = Path('Orbits').resolve()
        orbits.mkdir(parents=True)
        master_state_vec, master_provider = downloadSentinelOrbitFile(master.stem, directory=orbits)
        log.info(f'Downloaded orbit file {master_state_vec} from {master_provider}')
        slave_state_vec, slave_provider = downloadSentinelOrbitFile(slave.stem, directory=orbits)
        log.info(f'Downloaded orbit file {slave_state_vec} from {slave_provider}')

    if aux is None:
        aux = orbits

    lat_limits, lon_limits = geometry.bounding_box(
        str(master), orbits=orbits, aux=aux, polarization=polarization
    )

    dem = geometry.find_jpl_dem(lat_limits, lon_limits, download=download)

    if download:
        io.fetch_jpl_tifs(match=os.path.basename(dem)[:3])

    if process_dir:
        Path(process_dir).mkdir(parents=True)
        os.chdir(process_dir)

    isce_dem = geometry.prep_isce_dem(dem, lat_limits, lon_limits)

    io.format_tops_xml(master, slave, polarization, isce_dem, orbits, aux)

    with open('topsApp.txt', 'w') as f:
        cmd = '${ISCE_HOME}/applications/topsApp.py topsApp.xml --end=mergebursts'
        execute(cmd, logfile=f, uselogging=True)

    m_slc = os.path.join(os.getcwd(), 'merged', 'master.slc.full')
    s_slc = os.path.join(os.getcwd(), 'merged', 'slave.slc.full')

    with open('createImages.txt', 'w') as f:
        for slc in [m_slc, s_slc]:
            cmd = f'gdal_translate -of ENVI {slc}.vrt {slc}'
            execute(cmd, logfile=f, uselogging=True)

    in_file_base = dem.replace('_h.tif', '')
    with open('testGeogrid.txt', 'w') as f:
        cmd = f'testGeogrid_ISCE.py -m master -s slave' \
              f' -d {dem} -ssm {in_file_base}_StableSurface.tif' \
              f' -sx {in_file_base}_dhdx.tif -sy {in_file_base}_dhdy.tif' \
              f' -vx {in_file_base}_vx0.tif -vy {in_file_base}_vy0.tif' \
              f' -srx {in_file_base}_vxSearchRange.tif -sry {in_file_base}_vySearchRange.tif' \
              f' -csminx {in_file_base}_xMinChipSize.tif -csminy {in_file_base}_yMinChipSize.tif' \
              f' -csmaxx {in_file_base}_xMaxChipSize.tif -csmaxy {in_file_base}_yMaxChipSize.tif'
        execute(cmd, logfile=f, uselogging=True)

    with open('testautoRIFT.txt', 'w') as f:
        cmd = f'testautoRIFT_ISCE.py' \
              f' -m {m_slc} -s {s_slc} -g window_location.tif -o window_offset.tif' \
              f' -vx window_rdr_off2vel_x_vec.tif -vy window_rdr_off2vel_y_vec.tif' \
              f' -sr window_search_range.tif -csmin window_chip_size_min.tif' \
              f' -csmax window_chip_size_max.tif -nc S'
        execute(cmd, logfile=f, uselogging=True)

    if product:
        Path(product_dir).mkdir(parents=True)
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
    parser.add_argument('master', type=os.path.abspath,
                        help='Master Sentinel-1 SAFE zip archive')
    parser.add_argument('slave', type=os.path.abspath,
                        help='Slave Sentinel-1 SAFE zip archive')
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
