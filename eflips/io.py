# -*- coding: utf-8 -*-
import pickle
import gzip
import json
import os
import logging
import math
import pandas as pd
import numpy as np
from time import sleep


class FileExistsError(Exception):
    pass


def export_pickle(file, obj, replace_file=True):
    """Save any object using pickle and compress with gzip."""
    # if os.path.isfile(file):
    #     if replace_file:
    #         success = False
    #         while not success:
    #             try:
    #                 os.remove(file)
    #                 success = True
    #             except (PermissionError, FileNotFoundError):
    #                 sleep(1)
    #     else:
    #         logger = logging.getLogger('io_logger')
    #         logger.error('File ' + file + ' already exists. Please '
    #                                       'rename or call export_pickle with '
    #                                       'replace_file=True.')
    #         raise FileExistsError('File ' + file + ' already exists. Please '
    #                               'rename or call export_pickle with '
    #                               'replace_file=True.')

    # Pickle obj and save as gzip compressed file
    if not replace_file and os.path.isfile(file):
        logger = logging.getLogger('io_logger')
        logger.error('File ' + file + ' already exists. Please '
                                      'rename or call export_pickle with '
                                      'replace_file=True.')
        raise FileExistsError('File ' + file + ' already exists. Please '
                              'rename or call export_pickle with '
                              'replace_file=True.')
    else:
        success = False
        while not success:
            try:
                with gzip.open(file, mode='wb') as file:
                    file.write(pickle.dumps(obj))
                    success = True
            except (PermissionError, FileNotFoundError):
                sleep(1)


def import_pickle(file):
    """Load pickled and gzipped object."""
    logger = logging.getLogger('io_logger')
    if not os.path.exists(file):
        raise FileNotFoundError(file + ' not found')
    success = False
    if os.path.isfile(file):
        logger.debug("Importing %s" % file)
    while not success:
        try:
            with gzip.open(file, mode='rb') as file:
                out = pickle.loads(file.read())
                success = True
        except PermissionError:
            sleep(1)
        except:
            raise RuntimeError('Unknown error when importing pickle file')
        # except (PermissionError, FileNotFoundError):
        #     sleep(1)
        # finally:
        #     raise RuntimeError('Unknown error when importing pickle file')
    return out


def import_json(file):
    """Load json file and return dict"""
    with open(file, encoding='utf_8') as fp:
        json_data = json.load(fp)
    return json_data


def import_testreferencedata(filename):
    """
    Import text-based data from test reference years (TRY) and return as
    Pandas DataFrame. Includes a 'weekday' column and a 'week' column
    indicating the week number, both assuming Jan 1 is a Monday.

    Column names (see TRY .dat file for details - it is a text file!):

    RG TRY-Region                                                           {1..15}
    IS Standortinformation                                                  {1,2}
    MM Monat                                                                {1..12}
    DD Tag                                                                  {1..28,30,31}
    HH Stunde (MEZ)                                                         {1..24}
    N  Bedeckungsgrad                                              [Achtel] {0..8;9}
    WR Windrichtung in 10 m Höhe über Grund                        [°]      {0;10..360;999}
    WG Windgeschwindigkeit in 10 m Höhe über Grund                 [m/s]
    t  Lufttemperatur in 2m Höhe über Grund                        [°C]
    p  Luftdruck in Stationshöhe                                   [hPa]
    x  Wasserdampfgehalt, Mischungsverhältnis                      [g/kg]
    RF Relative Feuchte in 2 m Höhe über Grund                     [%]      {1..100}
    W  Wetterereignis der aktuellen Stunde                                  {0..99}
    B  Direkte Sonnenbestrahlungsstärke (horiz. Ebene)             [W/m²]   abwärts gerichtet: positiv
    D  Difuse Sonnenbetrahlungsstärke (horiz. Ebene)               [W/m²]   abwärts gerichtet: positiv
    IK Information, ob B und oder D Messwert/Rechenwert                     {1;2;3;4;9}
    A  Bestrahlungsstärke d. atm. Wärmestrahlung (horiz. Ebene)    [W/m²]   abwärts gerichtet: positiv
    E  Bestrahlungsstärke d. terr. Wärmestrahlung                  [W/m²]   aufwärts gerichtet: negativ
    IL Qualitätsbit für die langwelligen Strahlungsgrößen                   {1;2;3;4;5;6;7;8;9}
    """
    skiprows = list(range(0, 35)) + [37]
    trydata = pd.read_csv(filename, delim_whitespace=True,
                              skiprows=skiprows)
    # trydata['weekday'] = trydata['DD'].apply(
    #     lambda dayNum: TimeInfo.weekdayInv()[(dayNum - 1) % 7])

    day_of_month = np.array(trydata['DD'])
    days = np.zeros(day_of_month.shape, dtype=np.int64)
    weeks = np.zeros(day_of_month.shape, dtype=np.int64)

    day_count = 1
    last_day = day_of_month[0]
    for ind, day in enumerate(day_of_month):
        if day != last_day:
            day_count += 1
        last_day = day
        days[ind] = day_count
        weeks[ind] = math.ceil(day_count/7)


    trydata['day'] = pd.Series(days)
    trydata['week'] = pd.Series(weeks)
    return trydata