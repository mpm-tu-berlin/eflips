# -*- coding: utf-8 -*-
import eflips
import simpy
import logging
import copy
import pandas
from multiprocessing import Pool
from eflips.charging import ChargingNetwork
from eflips.misc import TimeInfo, Ambient, setup_logger
from eflips.energy import ChargingInterfaceTypes
from eflips.evaluation import LogRetriever, evaluate_simulation_log,\
    evaluate_simulation_objects, SimulationReport
from eflips.io import export_pickle
from eflips.simpleDepot import DepotWithChargingContainer, \
    SimpleDepotContainer, Dispatcher
from eflips.settings import global_constants
from eflips.vehicle import VehicleType, Fleet


class ScheduleSimulation:
    """High-level class for schedule simulation.

    :param dict params: Dictionary of schedule simulation parameters. See below for a template.
    :param eflips.schedule.ScheduleContainer schedules: The schedules to be simulated.
    :param eflips.grid.Grid grid: The grid pertaining to the schedules.
    :param eflips.schedule.ChargingSchedule charging_schedule: Optional charging schedule.


    Template for ``params``: ::

        params = {'test1': 'test',
                  'test2': 'test'}

    """
    def __init__(self, params, schedules, grid, charging_schedule=None):
        logger = logging.getLogger('simulation_logger')
        logger.debug('Initialising ScheduleSimulation')

        self._params = params
        self._global_constants = copy.copy(global_constants)
        self._schedules = schedules
        self._grid = grid
        self._charging_schedule = charging_schedule

        # Set base day
        TimeInfo.adjust(params['simulation_params']['base_day'])

        # Generate simpy environment
        self._env = simpy.Environment()

        # Create charging network
        self._charging_network = ChargingNetwork(self._env)

        # Add charging facilities
        if 'charging_point_params' in params:
            for ID, cp_params in params['charging_point_params'].items():
                location = self._grid.get_point(ID)
                interface = getattr(ChargingInterfaceTypes,
                                    cp_params['interface'])
                self._charging_network.create_point(interface, location,
                                                    cp_params['capacity'])

        # Charging segment support will be added later

        # Create ambient
        self._ambient = Ambient(params['ambient_params']['temperature'],
                                params['ambient_params']['humidity'],
                                params['ambient_params']['insolation'])

        # Create vehicle type map
        self._vehicle_type_map = {}
        for vtype, vparams in params['vehicle_params'].items():
            self._vehicle_type_map.update({
                vtype: VehicleType(vtype, vparams['architecture'], vparams)})

        # Create vehicle fleet
        self._fleet = Fleet(self._env, self._vehicle_type_map,
                            charging_network=self._charging_network,
                            charging_schedule=self._charging_schedule,
                            ambient=self._ambient)

        # Create depots
        if params['depot_params']['charging'] == True:
            # Use DepotWithCharging
            self._depot_container = DepotWithChargingContainer(
                self._env, self._fleet,
                charging_network=self._charging_network)

            for ID in params['depot_params']['locations']:
                location = self._grid.get_point(ID)
                depot_params = params['depot_charging_params'][ID]
                self._depot_container.create_depot(
                    location,
                    dead_time_before=depot_params['dead_time_before'],
                    dead_time_after=depot_params['dead_time_after'],
                    interrupt_charging=depot_params['interrupt_charging'])
        else:
            # Use SimpleDepot
            self._depot_container = SimpleDepotContainer(
                self._env, self._fleet,
                charging_network=self._charging_network)

            for ID in params['depot_params']['locations']:
                location = self._grid.get_point(ID)
                self._depot_container.create_depot(location)

        # Create dispatcher
        self._dispatcher = Dispatcher(
            self._env, self._schedules, self._fleet,
            depot_container=self._depot_container,
            driver_additional_paid_time=
                params['depot_params']['driver_additional_paid_time'])

        # Run simulation
        if params['simulation_params']['run_until'] is None:
            logger.debug('Executing simulation until no events left')
            self._env.run()
        else:
            logger.debug('Executing simulation until t = %d' %
                         params['simulation_params']['run_until'])
            self._env.run(until=params['simulation_params']['run_until'])

        # Collect and evaluate data from DataLogger objects
        if global_constants['DATA_LOGGING']:
            self._retriever = LogRetriever(
                fleet=self._fleet,
                vehicles=self._fleet.get_all_by_ID(),
                depot_container=self._depot_container,
                depots=self._depot_container.get_all_by_ID(),
                charging_points=self._charging_network.get_all_points_by_ID())
            self._logger_eval_data = evaluate_simulation_log(self._retriever.data)
        else:
            self._retriever = None
            self._logger_eval_data = None
        self._object_eval_data = evaluate_simulation_objects(
            self._fleet, charging_network=self._charging_network)

        # Create a dict of charging station groups
        if self._retriever is not None:
            cp_data_grouped = {}
            for cp_id, cp_data in self._retriever.data[
                'charging_points'].items():
                cp_name = cp_data['params']['location'].name
                if not cp_name in cp_data_grouped:
                    cp_data_grouped.update({cp_name: [cp_data]})
                else:
                    cp_data_grouped[cp_name].append(cp_data)

            # Create aligned pandas Series and sum up
            cp_sums = {}
            for cp_name, cp_data_list in cp_data_grouped.items():
                res = pandas.Series(
                    list(cp_data_list[0]['log_data']['num_vehicles']
                         ['values'].values()),
                    list(cp_data_list[0]['log_data']['num_vehicles']
                         ['values'].keys())
                )
                for i in range(1, len(cp_data_list)):
                    new = pandas.Series(
                        list(cp_data_list[i]['log_data']['num_vehicles']
                             ['values'].values()),
                        list(cp_data_list[i]['log_data']['num_vehicles']
                             ['values'].keys())
                    )
                    res_aligned, new_aligned = res.align(new, method='ffill')
                    res = res_aligned + new_aligned
                cp_sums.update({cp_name: res})
        else:
            cp_sums = None

        # Prepare public dict for further evaluation or saving
        self.simulation_info = {
            'params': self._params,
            'global_constants': self._global_constants,
            'logger_data': self._retriever.data \
                if self._retriever is not None else None,
            'logger_eval_data': self._logger_eval_data,
            'object_eval_data': self._object_eval_data,
            'charging_point_occupation_grouped': cp_sums
        }

        logger.debug('ScheduleSimulation finished')

    def save(self, file_path, replace_file=True):
        export_pickle(file_path, self.simulation_info,
                      replace_file=replace_file)

    def xls_report(self, file_path):
        report = SimulationReport(
            vehicle_type_map=self._vehicle_type_map,
            vehicles=self._fleet.get_all(),
            title=self._params['simulation_params']['title'])
        report.save_xls(file_path)


class BatchScheduleSimulation:
    """Simulate multiple schedule or parameter configurations and determine
    cumulative energy consumption."""
    def __init__(self, list_of_param_dicts, multicore=True):
        """
        params_dict must be of the following form:
        params_dict = {set_id_1: param_set_1,
                       set_id_2: param_set_2,
                       ...}

        set_id_x can be any hashable identifier for an individual
        parameter set.

        param_set_x must be of the following form:
        param_set_1 = {'id': id,
                       'multiplier': multiplier,
                       'params': sim_params,
                       'schedules': schedules,
                       'grid': grid,
                       'charging_schedule': charging_schedule}

        id: Any identifier for an individual parameter set.

        multiplier: Number of times this simulation case is to be multiplied
            for cumulative energy consumption calculation.

        sim_params: Dict with parameters as used by ScheduleSimulation.

        schedules: ScheduleContainer

        grid: Grid

        charging_schedule: ChargingSchedule
        """
        self.list_of_param_dicts = list_of_param_dicts
        self.sim_results = {}

        # This is a hack to ensure proper setting of global_constants in the
        # child processes. For some reason, each child process only sees
        # the default values for global_constants and not the values set in
        # the top-level script. By copying global_constants and passing
        # it as a function argument to the child processes we can circumvent
        # this:
        for param_dict in list_of_param_dicts:
            param_dict.update({'global_constants':
                                   copy.copy(global_constants)})

        if multicore:
            with Pool(None) as pool:
                results = pool.map(self._execute_simulation,
                                   list_of_param_dicts)
                self.sim_results = dict(results)
        else:
            for set_params in list_of_param_dicts:
                id, sim = self._execute_simulation(set_params)
                self.sim_results.update({id: sim})

        self._evaluate_simulation()

    @staticmethod
    def _execute_simulation(set_params):
        """Helper function to create simulation object (required for
        multiprocessing.Pool)."""
        # Hack to set global_constants (see above):
        eflips.global_constants.update(set_params['global_constants'])

        sim =  ScheduleSimulation(set_params['params'],
                                  set_params['schedules'],
                                  set_params['grid'],
                                  set_params['charging_schedule'])

        # We cannot return ScheduleSimulation objects as they are not
        # picklable. Thus we return the simulation_info dict:
        return set_params['id'], sim.simulation_info

    def _evaluate_simulation(self):
        self.evaluation = {}

        # Sum over driver hours
        # for att in ['driver_driving_time', 'driver_pause_time',
        #             'driver_additional_paid_time', 'driver_total_time']:
        #     s = sum(res['object_eval_data'][att]
        #               for res in self.sim_results.values())
        #     self.evaluation.update({att: s})

        self.evaluation.update({
            'fleet_consumption': {},
            'fleet_consumption_by_vehicle_type': {},
            'fleet_mileage_by_vehicle_type': {},
            'driver_driving_time': 0,
            'driver_pause_time': 0,
            'driver_additional_paid_time': 0,
            'driver_total_time': 0
        })

        for sim_id, simulation_info in self.sim_results.items():
            # Find simulation parameter set in list
            found_id = False
            for params in self.list_of_param_dicts:
                if params['id'] == sim_id:
                    found_id = True
                    break
            if found_id == False:
                raise RuntimeError('Could not locate simulation parameter set for id %d' % sim_id)
            multiplier = params['multiplier'] if 'multiplier' in params else 1
            for medium_name, energy in simulation_info['object_eval_data']['fleet_consumption'].items():
                if medium_name in self.evaluation['fleet_consumption']:
                    self.evaluation['fleet_consumption'][medium_name] += multiplier*energy
                else:
                    self.evaluation['fleet_consumption'].update({medium_name: multiplier*energy})

            for vtype, consumption in simulation_info['object_eval_data']['fleet_consumption_by_vehicle_type'].items():
                if vtype not in \
                        self.evaluation['fleet_consumption_by_vehicle_type']:
                    self.evaluation['fleet_consumption_by_vehicle_type']\
                        .update({vtype: {}})
                for medium_name, energy in consumption.items():
                    if medium_name in \
                            self.evaluation['fleet_consumption_by_vehicle_type'][vtype]:
                        self.evaluation['fleet_consumption_by_vehicle_type']\
                            [vtype][medium_name] += multiplier*energy
                    else:
                        self.evaluation['fleet_consumption_by_vehicle_type']\
                            [vtype].update({medium_name: multiplier*energy})

            # Determine fleet mileage by vehicle type
            for vtype, mileage in simulation_info['object_eval_data']['fleet_mileage'].items():
                if vtype not in \
                        self.evaluation['fleet_mileage_by_vehicle_type']:
                    self.evaluation['fleet_mileage_by_vehicle_type'].update({vtype: 0})
                self.evaluation['fleet_mileage_by_vehicle_type'][vtype] \
                    += multiplier*mileage

            # Determine driver hours
            for att in ['driver_driving_time', 'driver_pause_time',
                        'driver_additional_paid_time', 'driver_total_time']:
                val = simulation_info['object_eval_data'][att]
                self.evaluation[att] += multiplier * val

        # Determine specific consumption by vehicle type
        fleet_specific_consumption_by_vehicle_type = {}
        for vtype, consumption in self.evaluation['fleet_consumption_by_vehicle_type'].items():
            if vtype not in fleet_specific_consumption_by_vehicle_type:
                fleet_specific_consumption_by_vehicle_type.update({vtype: {}})
            for medium_name, energy in consumption.items():
                fleet_specific_consumption_by_vehicle_type[vtype].update(
                    {medium_name: energy/self.evaluation['fleet_mileage_by_vehicle_type'][vtype]}
                )

        self.evaluation.update({'fleet_specific_consumption_by_vehicle_type': fleet_specific_consumption_by_vehicle_type})





# class YearScheduleSimulation:
#     """Simulate a whole year with given temperature histogram"""
#     def __init__(self, params_base, schedules, grid, temperature_histogram,
#                  insolation_histogram, cabin_temperature_function,
#                  charging_schedule=None):
#         self._params_base = params_base
#         self._schedules = schedules
#         self._grid = grid
#         self._charging_schedule = charging_schedule
#         self._temperature_histogram = temperature_histogram
#         self._insolation_histogram = insolation_histogram
#         self._cabin_temperature_function = cabin_temperature_function
#         self._sim_params_per_day = {}
#         self._simdata_per_day = {}
#
#         for ambient_temperature in self._temperature_histogram.keys():
#             # Create a set of simulation parameters for each ambient
#             # temperature
#             self._sim_params_per_day.update(
#                 {ambient_temperature: copy.deepcopy(self._params_base)})
#
#             self._sim_params_per_day[ambient_temperature]['ambient_params']\
#                 ['temperature'] = ambient_temperature
#
#             # Oops. Insolation and temperature don't correspond....



def schedule_simulation(schedules, grid, depot_ids,
                        depot_charging_interface_type,
                        charging_point_ids,
                        charging_point_interface_type,
                        vehicle_type_map,
                        base_day='Monday',
                        charging_schedule=None,
                        num_charging_points_depot=200,
                        num_charging_points_per_station=20,
                        depot_dead_time_before=600,
                        depot_dead_time_after=600,
                        additional_driver_time=600,
                        ambient_temperature=-10,
                        ambient_humidity=0.4,
                        insolation=0):
    """Makeshift schedule simulation function for Benno. Obsolete"""

    # Generate simpy environment
    env = simpy.Environment()

    TimeInfo.adjust(base_day)

    # Create charging network
    charging_network = eflips.ChargingNetwork(env)

    for id in depot_ids:
        # Add depot charging facilities
        charging_network.create_point(depot_charging_interface_type,
                                      grid.get_point(id),
                                      num_charging_points_depot)

    # Add other charging points.
    for id in charging_point_ids:
        charging_network.create_point(
            charging_point_interface_type,
            grid.get_point(id), num_charging_points_per_station)

    # Create ambient
    ambient = eflips.Ambient(ambient_temperature, ambient_humidity,
                              insolation)

    # Create vehicle fleet
    fleet = eflips.Fleet(env, vehicle_type_map,
                          charging_network=charging_network,
                          charging_schedule=charging_schedule,
                          ambient=ambient)

    # Create depots
    depot_container = eflips.DepotWithChargingContainer(
        env, fleet, charging_network=charging_network)

    for id in depot_ids:
        depot_container.create_depot(
            grid.get_point(id), dead_time_before=depot_dead_time_before,
            dead_time_after=depot_dead_time_after)

    # Create dispatcher
    dispatcher = eflips.Dispatcher(
        env, schedules, fleet, depot_container=depot_container,
        driver_additional_paid_time=additional_driver_time)

    # Start simulation
    env.run()

    return fleet, depot_container, charging_network


def evaluate_vehicle_energy_state(fleet):
    num_vehicles = fleet.num_vehicles
    soc_critical = False
    soc_valid = True
    for vehicle in fleet.get_all():
        if not vehicle.soc_was_valid:
            soc_valid = False
        if vehicle.soc_was_critical:
            soc_critical = True
        if not soc_valid and soc_critical:
            break
    return num_vehicles, soc_critical, soc_valid


def evaluate_schedule_simulation(fleet, depot_container, charging_network):
    # Collect and save data from DataLogger objects
    retriever = eflips.LogRetriever(
        fleet=fleet,
        vehicles=fleet.get_all_by_ID(),
        depot_container=depot_container,
        depots=depot_container.get_all_by_ID(),
        charging_points=charging_network.get_all_points_by_ID())
    eval_data = eflips.evaluation.evaluate_simulation_log(retriever.data)
    return (retriever.data, eval_data)


def calculate_vehicle_demand_singledepot(
        timetable, grid, scheduling_params,
        depot_charging_interface_type, charging_point_interface_type,
        vehicle_type_map,
        osm_cache_file,
        base_day='Monday',
        charging_schedule=None,
        num_charging_points_depot=200,
        num_charging_points_per_station=20,
        depot_dead_time_before=600,
        depot_dead_time_after=600,
        additional_driver_time=600,
        ambient_temperature=-10,
        ambient_humidity=0.4,
        insolation=0):
    """Wrapper function for quick vehicle demand calculation for a given set
    of timetables, vehicle and infrastructure parameters.
    Used by opportunity charging infrastructure placement algorithm."""

    # Identify depot grid point. This should yield only one result:
    depot_grid_point = \
        grid.find_points('name', scheduling_params['depot_name'])[0]

    # Invoke scheduler
    scheduler = eflips.schedule.SingleDepotScheduler(
        timetable, grid, scheduling_params['charging_point_names'],
        scheduling_params['vehicle'], depot_grid_point, osm_cache_file)

    grid, schedules = \
        scheduler.generate_schedules(
            scheduling_params['scheduler']['min_pause_duration'],
            scheduling_params['scheduler']['max_pause_duration'],
            default_depot_trip_distance=
                scheduling_params['scheduler']['depot_trip_distance'],
            default_depot_trip_velocity=
                scheduling_params['scheduler']['depot_trip_velocity'],
            mix_lines_at_stop=scheduling_params['scheduler']['mix_lines'],
            reduce_aux_power=scheduling_params['scheduler']['reduce_aux_power'],
            add_delays=scheduling_params['scheduler']['add_delays'])

    depot_ids = [depot_grid_point.ID]
    charging_point_ids = []
    for name in scheduling_params['charging_point_names']:
        for point in grid.find_points('name', name):
            charging_point_ids.append(point.ID)

    fleet, depot_container, charging_network = schedule_simulation(
        schedules, grid, depot_ids,
        depot_charging_interface_type,
        charging_point_ids,
        charging_point_interface_type,
        vehicle_type_map,
        base_day=base_day,
        charging_schedule=charging_schedule,
        num_charging_points_depot=num_charging_points_depot,
        num_charging_points_per_station=num_charging_points_per_station,
        depot_dead_time_before=depot_dead_time_before,
        depot_dead_time_after=depot_dead_time_after,
        additional_driver_time=additional_driver_time,
        ambient_temperature=ambient_temperature,
        ambient_humidity=ambient_humidity,
        insolation=insolation)

    num_vehicles, soc_critical, soc_valid = \
        evaluate_vehicle_energy_state(fleet)

    driver_time = 0
    consumed_energy = 0
    total_distance = 0
    for vehicle_id in fleet._vehicle_stack._ID_map:
        driver_time += fleet._vehicle_stack._ID_map[vehicle_id].operation_time + 600
        consumed_energy += fleet._vehicle_stack._ID_map[vehicle_id].energy_consumed_primary.energy
        for mission in fleet._vehicle_stack._ID_map[vehicle_id].mission_list:
            total_distance += mission.root_node.distance


    return num_vehicles, driver_time, consumed_energy, total_distance, soc_critical, soc_valid
