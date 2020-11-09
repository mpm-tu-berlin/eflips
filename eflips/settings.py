# -*- coding: utf-8 -*-
from eflips.misc import cm2in
from eflips.io import import_json
from matplotlib import rcParams
import os.path

current_path = os.path.dirname(__file__)
default_settings_file = os.path.join(current_path, 'settings_default.json')
global_constants = import_json(default_settings_file)

# global_constants = {
#     'DEBUG_MSGS': True,  # to be removed
#     'TRY_CHARGING': True,
#     'QUEUE_FOR_CHARGING': False,
#     'CHARGE_FULL': False,
#     'RELEASE_WHEN_FULL': False,
#     'MIN_CHARGE_DURATION': 0,
#     'ALLOW_INVALID_SOC': True,
#     'FORCE_UPDATES_WHILE_CHARGING': True,
#     'CHARGING_UPDATE_INTERVAL': 60,
#     'DATA_LOGGING': True,
#
#     'SKIP_CHARGING_WHEN_OCCUPIED': False,  # to be removed
#     'WAIT_FOR_CHARGING': False,  # to be removed
#
#     # Default size for plots:
#     'DEFAULT_PLOT_SIZE': cm2in(15, 9)
# }

if global_constants['LENGTH_UNIT'] == 'cm':
    global_constants['DEFAULT_PLOT_SIZE'] = cm2in(
        *global_constants['DEFAULT_PLOT_SIZE'])
elif global_constants['LENGTH_UNIT'] == 'in':
    global_constants['DEFAULT_PLOT_SIZE'] = \
        tuple(global_constants['DEFAULT_PLOT_SIZE'])
else:
    raise ValueError('Unknown LENGTH_UNIT')

rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = 'Liberation Sans, Arial, Helvetica, DejaVu Sans'
rcParams['font.size'] = 10
rcParams['axes.labelsize'] = 10
rcParams['axes.titleweight'] = 'bold'
rcParams['axes.titlesize'] = 10
rcParams['legend.fontsize'] = 10
rcParams['legend.frameon'] = True
rcParams['figure.autolayout'] = True
rcParams['figure.dpi'] = 150
# rcParams['backend'] = 'agg'