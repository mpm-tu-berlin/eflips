# -*- coding: utf-8 -*-
"""Demo script for bus ScheduleSimulation with depot charging (DC).

test_schedules.pickle must be created prior to execution by running
Generate_Schedules_and_Grid.py.
"""

import eflips
import os


# -----------------------------------------------------------------------------
# Define file paths
# -----------------------------------------------------------------------------

# Modify paths and filenames as required:
schedules_path = os.getcwd()
schedules_file = 'test_schedules.pickle'
output_path_base = os.getcwd()

output_path = os.path.join(output_path_base, 'ScheduleSimulation_DC')
simdata_file = "ScheduleSimulation_DC.pickle"

if not os.path.exists(output_path):
    os.mkdir(output_path)


# -----------------------------------------------------------------------------
# Setup logger, load schedules and grid
# -----------------------------------------------------------------------------

# Set level='debug' for more detailed logging
log_file = eflips.misc.generate_log_file_name(timestamp=True)
eflips.misc.setup_logger(os.path.join(output_path, log_file),
                          level='warning')

# Load schedules and grid
grid, schedules = eflips.io.import_pickle(os.path.join(schedules_path,
                                                        schedules_file))


# -----------------------------------------------------------------------------
# Define parameters
# -----------------------------------------------------------------------------

ambient_temperature = -10  # °C

schedule_simulation_params = {
    'simulation_params': {
        'base_day': 'Monday',
        'run_until': None  # run until no events are left
    },
    'ambient_params': {
        'temperature': ambient_temperature,
        'humidity': 0.4,  # not used anywhere at the moment
        'insolation': 0  # W/m²
    },
    'vehicle_params': {
        'SB': {
            # Vehicle architecture (see class vehicle.Fleet for details):
            'architecture': 'bus_electric_konvekta_hvac_electric',

            # Number of passengers used for payload and heating/cooling load
            # calculation. Irrelevant for traction consumption if we use
            # ConstantConsumptionTraction; set to zero to obtain the maximum
            # heating load (no heat sources):
            'num_passengers': 0,

            # Power of auxiliaries excluding HVAC system:
            'aux_power': 2,  # kW

            # Cabin temperature is obtained as a function of ambient
            # temperature from a correlation:
            'cabin_temperature':
                eflips.vehicle.cabin_temperature_vdv(ambient_temperature)\
                    ['economy'],

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
        20: {  # Depot (GridPoint ID 20)
            'interface': 'plug',
            'capacity': 10
        }
    },
    'depot_params': {
        'charging': True,
        'locations': [20],
        'driver_additional_paid_time': 1200  # seconds
    },
    'depot_charging_params': {
        20: {
            'dead_time_before': 600,
            'dead_time_after': 600,
            'interrupt_charging': False
        }
    }
}


# -----------------------------------------------------------------------------
# Execute simulation
# -----------------------------------------------------------------------------

# Construct simulation object; it is executed automatically
simulation = eflips.ScheduleSimulation(
    schedule_simulation_params, schedules, grid, charging_schedule=None)

# Save simulation results for later
eflips.io.export_pickle(os.path.join(output_path, simdata_file),
                         simulation.simulation_info)


# -----------------------------------------------------------------------------
# Plot simulation results
# -----------------------------------------------------------------------------

# Energy balance pie
eflips.evaluation.plot_energy_balance_pie(
    simulation.simulation_info['logger_data']['vehicles'],
    value_labels='abs', show=False, save=True,
    filename=os.path.join(output_path, 'energy_balance'))

# Number of vehicles in service, charging etc.
eflips.evaluation.plot_retriever_data_counter(
    simulation.simulation_info['logger_data']['depot_container'],
    'num_vehicles_in_service',
    title='Vehicles in service',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_in_service'))

eflips.evaluation.plot_retriever_data_counter(
    simulation.simulation_info['logger_data']['depot_container'],
    'num_vehicles_out_of_service',
    title='Vehicles in depot',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_out_of_service'))

eflips.evaluation.plot_retriever_data_counter(
    simulation.simulation_info['logger_data']['depot_container'],
    'num_vehicles_charging',
    title='Vehicles charging in depot',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_charging'))

eflips.evaluation.plot_retriever_data_counter(
    simulation.simulation_info['logger_data']['depot_container'],
    'num_vehicles_ready',
    title='Vehicles ready for service in depot',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_ready'))

# Vehicles
for vehicle_id, vehicle_data in \
        simulation.simulation_info['logger_data']['vehicles'].items():
    # SoC
    eflips.evaluation.plot_soc(
        vehicle_data, title='Vehicle %d (%s); total %d km; %.2f kWh/km' %
            (vehicle_id,
             vehicle_data['params']['vehicle_type'].name,
             list(vehicle_data['log_data']['odo']['values'].values())[-1],
             list(vehicle_data['log_data']['specific_consumption_primary']\
                      ['values'].values())[-1]),
        show=False, save=True,
        filename=os.path.join(output_path, 'soc_%03d' % vehicle_id))

    # Delay
    eflips.evaluation.plot_retriever_data(
        vehicle_data, 'delay',
        title='Vehicle %d (%s): Delay' % (vehicle_id,
                                       vehicle_data['params'][
                                             'vehicle_type'].name),
        ylabel='Delay [s]', show=False, save=True,
        filename=os.path.join(output_path, 'delay_%03d' % vehicle_id))

    # AC request and ignition
    eflips.evaluation.plot_retriever_data(
        vehicle_data, 'ignition_on', 'ac_request',
        title='Vehicle %d (%s): Ignition and air-conditioning' % (vehicle_id,
        vehicle_data['params']['vehicle_type'].name),
        legend_loc='upper right',
        show=False, save=True,
        filename=os.path.join(output_path, 'ignition_ac_%03d' % vehicle_id))
