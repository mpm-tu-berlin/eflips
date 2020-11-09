# -*- coding: utf-8 -*-
"""Demo script for bus schedule simulation with depot charging (DC), but
no depot (not kidding!) using a manually created simulation environment. A
new, fully charged vehicle object is generated by the Dispatcher for every
schedule. Simulation without a depot is discouraged; it is a better idea
to at least define a SimpleDepot as this allows keeping track of the number
of vehicles in and out of service.

test_schedules.pickle must be created prior to execution by running
Generate_Schedules_and_Grid.py.
"""

import eflips
import simpy
import os


# -----------------------------------------------------------------------------
# Define file paths
# -----------------------------------------------------------------------------

# Modify paths and filenames as required:
schedules_path = os.getcwd()
schedules_file = 'test_schedules.pickle'
output_path_base = os.getcwd()

output_path = os.path.join(output_path_base, 'Custom_Simulation_DC_noDepot')
simdata_file = "simdata_DC_noDepot.pickle"

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
ambient_humidity = 0.4  # ignored
insolation = 0  # W/m²

vehicle_architecture = 'bus_electric_konvekta_hvac_electric'
vehicle_params = {
    # Vehicle architecture (see class vehicle.Fleet for details):
    'architecture': vehicle_architecture,

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
        eflips.vehicle.cabin_temperature_vdv(ambient_temperature) \
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
}

# Vehicle type map maps the vehicle type string encountered in schedules
# to a VehicleType object; required for Fleet initialisation
vehicle_type_map = {'SB': eflips.VehicleType('SB', vehicle_architecture,
                                               vehicle_params)}

# Create ambient
ambient = eflips.Ambient(ambient_temperature,
                          ambient_humidity,
                          insolation)


# -----------------------------------------------------------------------------
# Build simulation environment, execute simulation, save results
# -----------------------------------------------------------------------------

# Generate simpy environment
env = simpy.Environment()

# Create vehicle fleet
fleet = eflips.Fleet(env, vehicle_type_map, ambient=ambient)

# Create dispatcher
dispatcher = eflips.Dispatcher(env, schedules, fleet)

# Start simulation
env.run()

# Collect data from DataLogger objects
retriever = eflips.LogRetriever(
    fleet=fleet,
    vehicles=fleet.get_all_by_ID())

# Evaluate DataLogger objects
sim_data = retriever.data
eval_data = eflips.evaluation.evaluate_simulation_log(sim_data)

# Save simulation and evaluation data
eflips.io.export_pickle(os.path.join(output_path, simdata_file),
                         (sim_data, eval_data))


# -----------------------------------------------------------------------------
# Plot simulation results
# -----------------------------------------------------------------------------

# Energy balance pie
eflips.evaluation.plot_energy_balance_pie(
    sim_data['vehicles'], value_labels='abs', show=False, save=True,
    filename=os.path.join(output_path, 'energy_balance'))

# Fleet size
eflips.evaluation.plot_retriever_data_counter(
    sim_data['fleet'], 'num_vehicles',
    title='Total number of vehicles',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'fleet_size'))

# Vehicles
for vehicle_id, vehicle_data in sim_data['vehicles'].items():
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
