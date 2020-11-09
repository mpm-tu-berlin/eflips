# -*- coding: utf-8 -*-
"""Demo script for bus schedule simulation with opportunity charging (OC)
using a manually created simulation environment.

test_schedules.pickle must be created prior to execution by running
Generate_Schedules_and_Grid.py.
"""

import eflips
import simpy
import os

# -----------------------------------------------------------------------------
# Define file paths
# -----------------------------------------------------------------------------

# test_schedules.pickle must be created prior to execution by running
# Generate_Schedules_and_Grid.py.

# Modify paths and filenames as required:
schedules_path = os.getcwd()
schedules_file = 'test_schedules.pickle'
output_path_base = os.getcwd()

output_path = os.path.join(output_path_base, 'Custom_Simulation_OC')
simdata_file = "simdata_OC.pickle"

if not os.path.exists(output_path):
    os.mkdir(output_path)


# -----------------------------------------------------------------------------
# Setup logger, load schedules and grid
# -----------------------------------------------------------------------------

# Setup logger. Set level='debug' for more detailed logging
log_file = eflips.misc.generate_log_file_name(timestamp=True)
eflips.misc.setup_logger(os.path.join(output_path, log_file),
                          level='warning')

# Load schedules and grid
grid, schedules = eflips.io.import_pickle(os.path.join(schedules_path,
                                                        schedules_file))


# -----------------------------------------------------------------------------
# Define parameters
# -----------------------------------------------------------------------------

# Redefine pantograph interface to adjust charging power to 150 kW.
# Comment this if default parameters defined in
# eflips.energy.ChargingInterfaceTypes are desired.
eflips.energy.ChargingInterfaceTypes.pantograph = \
    eflips.energy.ChargingInterfaceType(
        'Stationary pantograph',
        eflips.Fuels.electricity,
        False,
        eflips.EnergyFlow.from_energy_ref(eflips.Fuels.electricity, 150),
        15,
        15,
        bidirectional=True
    )

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
    'charging_interfaces': ['pantograph_300', 'plug'],

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
        'capacity_max': 90,  # kWh
        'soc_reserve': 0.08,
        'soc_min': 0.10,
        'soc_max': 0.90,
        'soc_init': 0.90,
        'soh': 0.8,
        'discharge_rate': 5,
        'charge_rate': 5
    }
}

charging_station_location_names = ['A2', 'J1']
charging_station_interface = eflips.ChargingInterfaceTypes.pantograph
charging_station_capacity = 2

depot_interface = eflips.ChargingInterfaceTypes.plug
num_charging_points_depot = 10

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

# Create charging network
charging_network = eflips.ChargingNetwork(env)

# Add charging point at depot
depot_grid_point = grid.find_points('name', 'Depot')[0]
charging_network.create_point(depot_interface,
                              depot_grid_point,
                              num_charging_points_depot)

# Add OC charging stations
for name in charging_station_location_names:
    charging_network.create_point(charging_station_interface,
                                  grid.find_points('name', name)[0],
                                  charging_station_capacity)

# Create vehicle fleet
fleet = eflips.Fleet(env, vehicle_type_map,
                      charging_network=charging_network,
                      ambient=ambient)

# Create depots
depot_container = eflips.DepotWithChargingContainer(
    env, fleet, charging_network=charging_network)

depot_container.create_depot(depot_grid_point)

# Create dispatcher
dispatcher = eflips.Dispatcher(env, schedules, fleet,
                                depot_container=depot_container)

# Start simulation
env.run()

# Collect data from DataLogger objects
retriever = eflips.LogRetriever(
    fleet=fleet,
    vehicles=fleet.get_all_by_ID(),
    depot_container=depot_container,
    depots=depot_container.get_all_by_ID(),
    charging_points=charging_network.get_all_points_by_ID())

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

# Number of vehicles in service, charging etc.
eflips.evaluation.plot_retriever_data_counter(
    sim_data['depot_container'], 'num_vehicles_in_service',
    title='Vehicles in service',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_in_service'))

eflips.evaluation.plot_retriever_data_counter(
    sim_data['depot_container'], 'num_vehicles_out_of_service',
    title='Vehicles in depot',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_out_of_service'))

eflips.evaluation.plot_retriever_data_counter(
    sim_data['depot_container'], 'num_vehicles_charging',
    title='Vehicles charging in depot',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_charging'))

eflips.evaluation.plot_retriever_data_counter(
    sim_data['depot_container'], 'num_vehicles_ready',
    title='Vehicles ready for service in depot',
    legend_loc='upper left',
    filename=os.path.join(output_path, 'num_vehicles_ready'))

# Vehicles
for vehicle_id, vehicle_data in sim_data['vehicles'].items():
    # SoC
    eflips.evaluation.plot_soc(
        vehicle_data, title='Vehicle %d (%s); total %d km; %.2f kWh/km' %
            (vehicle_id,
             vehicle_data['params']['vehicle_type'].name,
             list(vehicle_data['log_data']['odo']['values'].values())[-1],
             list(vehicle_data['log_data']['specific_consumption_primary']['values'].values())[-1]),
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

# Charging points
for cp_id, cp_data in sim_data['charging_points'].items():
    eflips.evaluation.plot_retriever_data(
        cp_data, 'num_vehicles',
        title='Charging point %d (%s): Number of vehicles present' %
              (cp_id, cp_data['params']['location'].name),
        show=False, save=True,
        filename=os.path.join(output_path, 'charging_point_%03d' % cp_id))
