# -*- coding: utf-8 -*-
"""Demo script illustrating use of scheduling algorithm for opportunity
charging.
"""
import eflips
import os

# -----------------------------------------------------------------------------
# File paths
# -----------------------------------------------------------------------------

timetable_path = os.path.join(os.getcwd(), 'output')
timetable_filename = 'timetable.pickle'

# Output will be placed in working directory; if desired, specify a different
# directory here:
output_path = os.path.join(os.getcwd(), 'output')
schedule_filename = 'schedules_OC.pickle'
schedule_text_tile_name = 'schedules_OC.txt'
plot_filename = 'schedules_OC'

# -----------------------------------------------------------------------------
# Setup logger, load data
# -----------------------------------------------------------------------------

# Setup logger. Set level='debug' for more detailed logging
log_file = eflips.misc.generate_log_file_name(timestamp=True)
eflips.misc.setup_logger(os.path.join(output_path, log_file),
                          level='warning')

# Load timetable and grid
grid, timetable = eflips.io.import_pickle(os.path.join(timetable_path,
                                                        timetable_filename))


# -----------------------------------------------------------------------------
# Define parameters
# -----------------------------------------------------------------------------

# Refer to eflips.scheduling.generate_schedules_singledepot()
# documentation for details on the parameter dict.
scheduler_params = {
    'charging_point_names': {
        '100': ['A', 'Z']
    },
    'scheduling_params': {
        'depot_gridpoint_id': grid.find_points('name','Depot')[0].ID,
        'min_pause_duration': 0,  # s
        'max_pause_duration': 45 * 60,  # s
        'max_deadheading_duration': 45 * 60,  # s
        'use_static_range': False,
        'default_depot_trip_distance': 5,  # km
        'default_depot_trip_velocity': 25,  # km/h
        'default_deadhead_trip_distance': 5,  # km
        'default_deadhead_trip_velocity': 25,  # km/h
        'get_missing_coords_from_osm': False,
        'fill_missing_distances_with_default': False,
        'deadheading': False,
        'mix_lines_at_stop': False,
        'mix_lines_deadheading': True,
        'add_delays': False,
        'delay_mode': 'all',
        'delayed_trip_ids': None,
        'delay_threshold': 0  # s
    },
    'vehicle_params': {
        'SB': {
            'capacity': 90 * 0.8 * 0.8 - 5,  # kWh
            'static_range': 0,  # km (irrelevant, deactivated above)
            'traction_consumption': 0.88,  # kWh/km
            'aux_power_driving': 2 + 8,  # kW
            'aux_power_pausing': 2,  # kW
            'charge_power': 300,  # kW
            'reduce_charge_time': 0,
            'dead_time': 30  # s
        }
    }
}

# Generate an empty OpenStreetMap cache. We don't need it for this
# simple example, so we will not save it for later use.
osm_cache = eflips.scheduling.generate_osm_cache()

# Invoke scheduler
schedules, grid = eflips.scheduling.generate_schedules_singledepot(
    timetable, grid, scheduler_params, osm_cache)

# Export text file of schedules
schedules.export_text_file(os.path.join(output_path, schedule_text_tile_name))

# Export schedules as pickle
eflips.io.export_pickle(os.path.join(output_path, schedule_filename),
                         (grid, schedules))

# Plot schedules
eflips.evaluation.plot_schedule_time(
    schedules, separate_trips=True, save=True,
    filename=os.path.join(output_path, plot_filename))
