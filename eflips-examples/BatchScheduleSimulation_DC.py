# -*- coding: utf-8 -*-
"""Demo script for bus BatchScheduleSimulation with depot charging (DC).

This script illustrates how to perform a batch simulation to obtain annual
energy consumption for a bus fleet considering different ambient and cabin
temperatures for each month.

test_schedules.pickle must be created prior to execution by running
Generate_Schedules_and_Grid.py.
"""

import eflips
import os
import copy
import pandas as pd


# -----------------------------------------------------------------------------
# Define file paths
# -----------------------------------------------------------------------------

# Modify paths and filenames as required:
schedules_path = os.path.join(os.getcwd(), 'output')
schedules_file = 'schedules_DC.pickle'

# Sample weather data file containing monthly average values for temperature
# and insolation:
weather_data_file = 'weather_data.csv'

output_path_base = os.path.join(os.getcwd(), 'output')

output_path = os.path.join(output_path_base, 'BatchScheduleSimulation_DC')
simdata_file = "BatchScheduleSimulation_DC.pickle"

if not os.path.exists(output_path):
    os.mkdir(output_path)


# -----------------------------------------------------------------------------
# Setup logger, load data
# -----------------------------------------------------------------------------

# Set level='debug' for more detailed logging
log_file = eflips.misc.generate_log_file_name(timestamp=True)
eflips.misc.setup_logger(os.path.join(output_path, log_file),
                          level='warning')

# Load schedules and grid
grid, schedules = \
    eflips.io.import_pickle(os.path.join(schedules_path, schedules_file))

# Load weather data (monthly average values for temperature and insolation)
weather_data = pd.read_csv(weather_data_file)

# -----------------------------------------------------------------------------
# Define parameters
# -----------------------------------------------------------------------------

# Identify depot grid point
depot_grid_point_id = grid.find_points('name', 'Depot')[0].ID

# These are the same schedule simulation parameters as used in the
# ScheduleSimulation_DC.py example script, but without the 'ambient_params'
# part and without 'cabin_temperature' which depends on ambient temperature.

schedule_simulation_params = {
    'simulation_params': {
        'base_day': 'Monday',
        'run_until': None  # run until no events are left
    },
    'vehicle_params': {
        'SB': {  # standard bus
            # Vehicle architecture (see class vehicle.Fleet for details):
            'architecture': 'bus_electric_konvekta_hvac_electric',

            # Number of passengers used for payload and heating/cooling load
            # calculation. Irrelevant for traction consumption if we use
            # ConstantConsumptionTraction; set to zero to obtain the maximum
            # heating load (no heat sources):
            'num_passengers': 0,

            # Power of auxiliaries excluding HVAC system:
            'aux_power': 2,  # kW

            # Traction model used for consumption calculation. At present,
            # the only model usable for ScheduleSimulation is
            # ConstantConsumptionTraction:
            'traction_model': 'ConstantConsumptionTraction',

            # Mean traction consumption:
            'traction_consumption': 0.88,  # kWh/km

            # Kerb weight is irrelevant as long as we use
            # ConstantConsumptionTraction, but has to be specified:
            'kerb_weight': 14500,  # kg

            # Whether or not to switch off the HVAC system while the bus
            # is pausing at terminal stops:
            'switch_off_ac_in_pause': False,

            # List of charging interfaces; see energy.ChargingInterfaceTypes
            # class documentation for details:
            'charging_interfaces': ['plug'],

            # Overall UA value (heat transmittance) of bus chassis for
            # heat transfer calculation:
            'UA_value': 0.562,  # kW/K

            # Surface area used to calculate solar gain:
            'insolation_area': 11.4,  # m²

            # Number of HVAC system units; the type of HVAC system is
            # determined by the vehicle architecture specified above:
            'hvac': {
                'num_ac_units': 1,
                'num_hp_units': 1,
                'num_backup_units': 0
            },

            # Battery parameters:
            'battery': {
                'capacity_max': 300,  # kWh
                'soc_reserve': 0.08,
                'soc_min': 0.10,
                'soc_max': 0.90,
                'soc_init': 0.90,
                'soh': 0.8,
                'discharge_rate': 1,
                'charge_rate': 1
            }
        },
    },
    'charging_point_params': {
        depot_grid_point_id: {
            'interface': 'plug',
            'capacity': 10
        }
    },
    'depot_params': {
        'charging': True,
        'locations': [depot_grid_point_id],
        'driver_additional_paid_time': 1200  # seconds
    },
    'depot_charging_params': {
        depot_grid_point_id: {
            'dead_time_before': 600,
            'dead_time_after': 600,
            'interrupt_charging': False
        }
    }
}

# We will now construct a separate parameter set for each month according to
# the weather data:
batch_schedule_simulation_params = []
for id, (ind, row) in enumerate(weather_data.iterrows()):
    # Number of days the resulting energy consumption will be multiplied by:
    num_days = row['num_days']
    ambient_temperature = row['temperature_C']
    insolation = row['insolation_W_m2']

    schedule_simulation_params_case = copy.deepcopy(schedule_simulation_params)

    # Write current ambient conditions to schedule simulation parameters:
    schedule_simulation_params_case.update({
        'ambient_params': {
            'temperature': ambient_temperature,
            'humidity': 0.4,  # irrelevant, currently not used by the model
            'insolation': insolation
        }
    })

    # Write cabin temperature to vehicle parameters:
    for vparams in schedule_simulation_params_case['vehicle_params'].values():
        vparams.update({
            # Cabin temperature is obtained as a function of ambient
            # temperature from a correlation:
            'cabin_temperature':
                eflips.vehicle.cabin_temperature_vdv(ambient_temperature)\
                    ['economy'],
        })

    # Compile parameter dict for this month and append to list:
    batch_schedule_simulation_params_case = {
        'id': id,
        'multiplier': row['num_days'],
        'params': schedule_simulation_params_case,
        'schedules': schedules,
        'grid': grid,
        'charging_schedule': None
    }

    batch_schedule_simulation_params.append(
        batch_schedule_simulation_params_case)


# -----------------------------------------------------------------------------
# Execute simulation
# -----------------------------------------------------------------------------

# Construct simulation object; it is executed automatically.
# NOTE: If you set multicore=True, you MUST enclose the entire script
# in an "if __name__=='__main__'" clause, otherwise it won't work!
simulation = eflips.BatchScheduleSimulation(batch_schedule_simulation_params,
                                             multicore=False)

# Save simulation results for later. For this example, we save the entire
# BatchScheduleSimulation object, but it can become very large
# even for mdoerately-sized simulations. Instead, consider saving only the
# simulation.evaluation attribute or deleting the 'logger_data' entry from each
# of the dicts in simulation.sim_results prior to saving.
eflips.io.export_pickle(os.path.join(output_path, simdata_file),
                         simulation)
