# -*- coding: utf-8 -*-
"""Demo script for longitudinal dynamics simulation using the
LongitudinalDynamicsTraction_ConstantEfficiency traction model.
"""

import eflips
import simpy
import os
import pandas as pd
import numpy as np

# -----------------------------------------------------------------------------
# Define file paths
# -----------------------------------------------------------------------------

# Modify paths and filenames as required:
driving_profile_file = 'sort2.csv'
output_path_base = os.path.join(os.getcwd(), 'output')

output_path = os.path.join(output_path_base, 'LDM_Simulation')
simdata_file = "simdata_LDM.pickle"

if not os.path.exists(output_path):
    os.mkdir(output_path)


# -----------------------------------------------------------------------------
# Setup logger, load driving profile
# -----------------------------------------------------------------------------

# Set level='debug' for more detailed logging
log_file = eflips.misc.generate_log_file_name(timestamp=True)
eflips.misc.setup_logger(os.path.join(output_path, log_file),
                          level='warning')

# Load driving profile, create equidistant time grid and convert velocity
# from km/h to m/s
data = pd.read_csv(driving_profile_file, sep=';')
data.set_index('t [s]', inplace=True)
new_index = np.arange(data.index[0], data.index[-1], 0.1)
data_new_index = data.reindex(index=data.index.union(new_index))
data_interpolated = data_new_index.interpolate(method='index')

driving_profile = eflips.DrivingProfile('SORT 2',
                                         data_interpolated.index,
                                         data_interpolated['v [km/h]'] / 3.6)


# -----------------------------------------------------------------------------
# Define parameters
# -----------------------------------------------------------------------------

vehicle_architecture = 'bus_electric_constantaux'
vehicle_params = {
    'num_passengers': 1,
    'aux_power': 0,  # kW
    'traction_model': 'LongitudinalDynamicsTraction_ConstantEfficiency',
    'kerb_weight': 14500,  # kg
    'charging_interfaces': ['plug'],
    'battery': {
        'capacity_max': 300,  # kWh
        'soc_reserve': 0.08,
        'soc_min': 0.10,
        'soc_max': 0.90,
        # Very important: Don't start with a full battery, otherwise
        # recuperation won't work and SORT energy consumption will be
        # calculated incorrectly
        'soc_init': 0.80,
        'soh': 0.8,
        'discharge_rate': 1,
        'charge_rate': 1
    },
    'traction': {
        # Values from König 2018 (except eta_total):
        'f_r': 0.008,  # rolling resistance coefficient
        'c_w': 0.6,
        'A': 8.28,  # m²
        'lambda': 1.1,  # rotational mass factor
        'eta_total': 0.75  # total efficiency
    }
}

# Vehicle type map maps the vehicle type string encountered in schedules
# to a VehicleType object; required for Fleet initialisation
vehicle_type_map = {'SB': eflips.VehicleType('SB', vehicle_architecture,
                                               vehicle_params)}


# -----------------------------------------------------------------------------
# Build simulation environment, execute simulation, save results
# -----------------------------------------------------------------------------

# Generate simpy environment
env = simpy.Environment()

# Create vehicle fleet
fleet = eflips.Fleet(env, vehicle_type_map)

# Create a single vehicle
vehicle = fleet.create_vehicle('SB', ID=0)

# Switch on ignition, drive profile
vehicle.ignition_on = True
env.process(vehicle.drive_profile(driving_profile))

# Start simulation
env.run()

# Collect data from DataLogger object
retriever = eflips.LogRetriever(
    vehicles=fleet.get_all_by_ID())
sim_data = retriever.data

# Save simulation data
eflips.io.export_pickle(os.path.join(output_path, simdata_file),
                         sim_data)


# -----------------------------------------------------------------------------
# Plot simulation results
# -----------------------------------------------------------------------------

# Vehicles
for vehicle_id, vehicle_data in sim_data['vehicles'].items():
    # SoC
    eflips.evaluation.plot_soc(
        vehicle_data,
        title='Vehicle %d (%s); total %d km; %.2f kWh/km' %
            (vehicle_id,
             vehicle_data['params']['vehicle_type'].name,
             list(vehicle_data['log_data']['odo']['values'].values())[-1],
             list(vehicle_data['log_data']['specific_consumption_primary']\
                      ['values'].values())[-1]),
        xlabel='Time (s)', ylabel='SoC',
        hour_xlabels=False, show=False, save=True,
        filename=os.path.join(output_path, 'soc_%03d' % vehicle_id))

    # Delay
    eflips.evaluation.plot_retriever_data(
        vehicle_data, 'delay',
        title='Vehicle %d (%s): Delay' % (vehicle_id,
                                       vehicle_data['params'][
                                             'vehicle_type'].name),
        xlabel='Time (s)', hour_xlabels=False,
        ylabel='Delay (s)', show=False, save=True,
        filename=os.path.join(output_path, 'delay_%03d' % vehicle_id))

    # AC request and ignition
    eflips.evaluation.plot_retriever_data(
        vehicle_data, 'ignition_on', 'ac_request',
        title='Vehicle %d (%s): Ignition and air-conditioning' % (vehicle_id,
        vehicle_data['params']['vehicle_type'].name),
        xlabel='Time (s)',
        hour_xlabels=False,
        legend_loc='upper right',
        show=False, save=True,
        filename=os.path.join(output_path, 'ignition_ac_%03d' % vehicle_id))

    # Traction and total power
    eflips.evaluation.plot_retriever_data(
        vehicle_data, 'traction_power', 'aux_power_primary',
        'total_power_primary',
        title='Vehicle %d (%s): Power' % (vehicle_id,
        vehicle_data['params']['vehicle_type'].name),
        xlabel='Time (s)',
        ylabel='Power (kW)',
        hour_xlabels=False,
        legend_loc='upper right',
        show=False, save=True,
        filename=os.path.join(output_path, 'power_%03d' % vehicle_id))

    # Velocity
    eflips.evaluation.plot_retriever_data(
        vehicle_data, 'velocity',
        title='Vehicle %d (%s): Velocity' % (vehicle_id,
        vehicle_data['params']['vehicle_type'].name),
        xlabel='Time (s)',
        ylabel='Velocity (m/s)',
        hour_xlabels=False,
        legend_loc='upper right',
        show=False, save=True,
        filename=os.path.join(output_path, 'velocity_%03d' % vehicle_id))
