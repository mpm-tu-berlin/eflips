# -*- coding: utf-8 -*-
"""Demo script for bus system TCO analysis.

Before running this script, you must execute the following scripts:
* Generate_Schedules_and_Grid.py (to generate schedules)
* ScheduleSimulation_DC.py (to determine vehicle, staff and infrastructure
  demand for critical consumption case)
* BatchScheduleSimulation_DC.py (to determine annual energy demand of the
  fleet and annual driver hours)
"""

import eflips
import os


# -----------------------------------------------------------------------------
# Define file paths
# -----------------------------------------------------------------------------

# Modify paths and filenames as required

# Path to schedules (for total passenger trip distance)
schedules_path = os.getcwd()
schedules_file = 'test_schedules.pickle'

# Path to schedule simulation (for critical consumption vehicle/staff demand)
critical_simulation_path = os.path.join(os.getcwd(), 'ScheduleSimulation_DC')
critical_sim_data_file = 'ScheduleSimulation_DC.pickle'

# Path to batch simulation (for annual energy consumption)
batch_simulation_path = os.path.join(os.getcwd(), 'BatchScheduleSimulation_DC')
batch_sim_data_file = 'BatchScheduleSimulation_DC.pickle'

# Output path
output_path_base = os.getcwd()
output_path = os.path.join(output_path_base, 'TCO_Analysis_DC')
tco_file = "TCO_DC.pickle"

if not os.path.exists(output_path):
    os.mkdir(output_path)


# -----------------------------------------------------------------------------
# Setup logger, load data
# -----------------------------------------------------------------------------

# Setup logger. Set level='debug' for more detailed logging
log_file = eflips.misc.generate_log_file_name(timestamp=True)
eflips.misc.setup_logger(os.path.join(output_path, log_file),
                          level='warning')

# Load schedules and grid
grid, schedules = \
    eflips.io.import_pickle(os.path.join(schedules_path, schedules_file))

# Load critical schedule simulation results
critical_schedule_sim_data = \
    eflips.io.import_pickle(os.path.join(critical_simulation_path,
                                          critical_sim_data_file))

# Load batch simulation results
batch_simulation = eflips.io.import_pickle(
    os.path.join(batch_simulation_path, batch_sim_data_file))


# -----------------------------------------------------------------------------
# Define cost parameters
# -----------------------------------------------------------------------------

# TCO parameters
battery_renewal = True
start_year = 2020
project_duration = 12
end_year = start_year + project_duration
i_discount = 0.014
i_battery = -0.08
i_electricity = 0.038
repeat_procurements = True
i_capital = 0.04
use_salvage_value = False
annualise = True

cost_data = {
    'CAPEX': {
        'vehicle_SB': {
            'escalation':
                dict([(year, i_discount) for year in
                      range(start_year, end_year+1)]),
            'escalation_type': 'compound',
            'unit_cost': 450000,  # €
            'base_year': start_year,
            'quantity': 0,  # fill later
            'depreciation_period': 12
        },
        'battery': {
            'escalation':
                dict([(year, i_battery) for year in
                      range(start_year, end_year + 1)]),
            'escalation_type': 'compound',
            'unit_cost': 500,  # €/kWh
            'base_year': start_year,
            'quantity': 0,  # kWh  # fill later
            'depreciation_period': 6 if battery_renewal == True else 12
        },
        'depot_charging_point_150kW': {
            'escalation':
                dict([(year, 0) for year in
                      range(start_year, end_year + 1)]),
            'escalation_type': 'compound',
            'unit_cost': 100000,  # €
            'base_year': start_year,
            'quantity': 0,  # fill later
            'depreciation_period': 20
        },
    },
    'OPEX': {
        'electricity': {
            'escalation':
                dict([(year, i_electricity) for year in
                      range(start_year, end_year+1)]),
            'unit_cost': 0.15,  # €/kWh
            'base_year': start_year,
            'quantity': 0  # kWh/a  # fill later
        },
        'driver': {
            'escalation':
                dict([(year, i_discount) for year in
                      range(start_year, end_year + 1)]),
            'unit_cost': 20,  # €/h
            'base_year': start_year,
            'quantity': 0  # h/a  # fill later
        },
        'vehicle_maintenance': {
            'escalation':
                dict([(year, i_discount) for year in
                      range(start_year, end_year + 1)]),
            'unit_cost': 0.3,  # €/km
            'base_year': start_year,
            'quantity': 0  # km/a  # fill later
        }
    }
}


# -----------------------------------------------------------------------------
# Extract quantities from schedules and simulation data
# -----------------------------------------------------------------------------

# Get productive fleet mileage (i.e. the total distance driven on passenger
# trips, the quantity for which the specific TCO in €/km will be determined).
# We currently need to extract this data from the schedules as the batch
# simulation does not keep track of different trip types.
production_data = {
    'fleet_mileage_productive': schedules.distance(trip_type='passengerTrip') * 365
}

# Vehicle demand from critical schedule simulation
cost_data['CAPEX']['vehicle_SB']['quantity'] = \
    critical_schedule_sim_data['object_eval_data']['num_vehicles']['SB']

# Battery capacity from critical schedule simulation
cost_data['CAPEX']['battery']['quantity'] = \
    critical_schedule_sim_data['object_eval_data']['num_vehicles']['SB'] * \
    critical_schedule_sim_data['params']['vehicle_params']['SB']['battery'] \
        ['capacity_max']

# Depot charging points as maximum occupation from critical schedule
# simulation
cost_data['CAPEX']['depot_charging_point_150kW']['quantity'] = \
    critical_schedule_sim_data['object_eval_data']['charging_points'] \
        [1]['max_occupation']

# Annual electricity demand from batch simulation
cost_data['OPEX']['electricity']['quantity'] = \
    batch_simulation.evaluation['fleet_consumption']['Electricity'].energy_ref

# Annual driver hours from batch simulation
cost_data['OPEX']['driver']['quantity'] = \
    batch_simulation.evaluation['driver_total_time']/3600

# Annual fleet mileage (for maintenance cost) from batch simulation
cost_data['OPEX']['vehicle_maintenance']['quantity'] = \
    batch_simulation.evaluation['fleet_mileage_by_vehicle_type']['SB']


# -----------------------------------------------------------------------------
# Execute TCO calculation
# -----------------------------------------------------------------------------

# Construct TCO object; it is executed automatically
tco = eflips.tco.TCO(cost_data, start_year, project_duration,
                      i_discount, repeat_procurements,
                      use_salvage_value=use_salvage_value,
                      annualise=annualise,
                      production_data=production_data)

# Save TCO results for later
eflips.io.export_pickle(os.path.join(output_path, tco_file), tco)
