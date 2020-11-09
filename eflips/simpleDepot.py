# -*- coding: utf-8 -*-
from abc import ABCMeta, abstractmethod
from eflips.schedule import Driver
from eflips.evaluation import DataLogger
from eflips.misc import LocationMapContainer, CalcDict, hms_str
from eflips.settings import global_constants
from collections import deque, Counter
import logging
import eflips.events


class DepotNotFoundError(Exception):
    pass


class DepotAbstract(metaclass=ABCMeta):
    def __init__(self, env, location, fleet, ID=None):
        self._vehicles_in_service = deque()
        self._vehicles_out_of_service = deque()
        self.env = env
        self.ID = ID
        self.location = location
        self.fleet = fleet
        self.state_change_event = eflips.events.EventHandler(self)

    @property
    def num_vehicles_in_service(self):
        return Counter([v.vehicle_type.name for v
                        in self._vehicles_in_service])
        # return count_vehicles_by_type(self.fleet.vehicle_types,
        #                               self._vehicles_in_service)

    @property
    def num_vehicles_out_of_service(self):
        return Counter([v.vehicle_type.name for v
                        in self._vehicles_out_of_service])
        # return count_vehicles_by_type(self.fleet.vehicle_types,
        #                               self._vehicles_out_of_service)

    @abstractmethod
    def request_vehicle(self, vehicle_type_string, required_range):
        pass

    @abstractmethod
    def return_vehicle(self, vehicle):
        pass


class SimpleDepot(DepotAbstract):
    """Very simple depot model without pooling and charging simulation.
    A a new vehicle is created for each schedule. Use this if only route
    simulation is of interest."""
    def __init__(self, env, location, fleet, ID=None, charging_network=None):
        super().__init__(env, location, fleet, ID=ID)
        self.charging_network = charging_network
        self.state_change_event = eflips.events.EventHandler(self)

        # Invoke DataLogger
        self.log_attributes = {
            'num_vehicles_in_service': {
                'attribute': 'num_vehicles_in_service',
                'name': 'Number of vehicles in service',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_out_of_service': {
                'attribute': 'num_vehicles_out_of_service',
                'name': 'Number of vehicles out of service',
                'unit': None,
                'discrete': True
            }
        }
        self.params = {'ID': self.ID,
                       'name': self.location.name}

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    def request_vehicle(self, vehicle_type_string, _):
        vehicle = self.fleet.create_vehicle(vehicle_type_string)
        self._vehicles_in_service.append(vehicle)
        self.state_change_event()
        logger = logging.getLogger('depot_logger')
        logger.debug('  t = %d (%s): Requesting vehicle of type %s '
                     'from depot no. %d' %
                    (self.env.now, hms_str(self.env.now),
                     vehicle_type_string, self.ID))

        # Pseudo timeout to ensure we always reach a yield statement
        # (otherwise, this function would not work as a simpy process):
        yield self.env.timeout(0)
        return vehicle

    def return_vehicle(self, vehicle):
        logger = logging.getLogger('depot_logger')
        if vehicle in self._vehicles_in_service:
            self._vehicles_in_service.remove(vehicle)
        else:
            logger.warning('  t = %d (%s): Trying to return unknown '
                           'vehicle to depot '
                           'no. %d' % (self.env.now, hms_str(self.env.now),
                                       self.ID))
        self._vehicles_out_of_service.append(vehicle)
        self.state_change_event()
        logger.debug('  t = %d (%s): Returning vehicle of type %s '
                     'to depot no. %d' %
            (self.env.now, hms_str(self.env.now),
             vehicle.vehicle_type.name, self.ID))


class DepotWithCharging(DepotAbstract):
    """Depot with vehicle pooling and charging functionality.

    Upon request, the depot searches for available vehicles in its own pool;
    if no matching vehicle is present, a new one is created and added to the
    pool.

    To charge vehicles, a ChargingPoint with the appropriate number of slots
    at the depot's location must be present in the ChargingNetwork.

    For now, the charging behaviour is tailored towards electric vehicles:
    Charging is carried out while the vehicles are parked, with dead times
    before and after. Be aware that the charging slot is automatically released
    by the vehicle when charging is finished. (May be changed later.) This means
    that peak charging slot demand must NOT be evaluated from the number of
    slots occupied, but from the num_vehicles_charging property."""
    def __init__(self, env, location, fleet, ID=None, charging_network=None,
                 dead_time_before=0, dead_time_after=0,
                 interrupt_charging=False):
        super().__init__(env, location, fleet, ID=ID)
        self._vehicles_charging = deque()  # including dead times
        self._vehicles_ready = deque()
        self.charging_network = charging_network
        self.dead_time_before = dead_time_before
        self.dead_time_after = dead_time_after
        self.interrupt_charging = interrupt_charging
        self.state_change_event = eflips.events.EventHandler(self)

        # Invoke DataLogger
        self.log_attributes = {
            'num_vehicles_in_service': {
                'attribute': 'num_vehicles_in_service',
                'name': 'Number of vehicles in service',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_out_of_service': {
                'attribute': 'num_vehicles_out_of_service',
                'name': 'Number of vehicles out of service',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_charging': {
                'attribute': 'num_vehicles_charging',
                'name': 'Number of vehicles charging/being serviced',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_ready': {
                'attribute': 'num_vehicles_ready',
                'name': 'Number of vehicles ready for service',
                'unit': None,
                'discrete': True
            }
        }
        self.params = {'ID': self.ID,
                       'name': self.location.name}

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    @property
    def num_vehicles_ready(self):
        return Counter([v.vehicle_type.name for v
                        in self._vehicles_ready])
        # return count_vehicles_by_type(self.fleet.vehicle_types,
        #                               self._vehicles_ready)

    @property
    def num_vehicles_charging(self):
        return Counter([v.vehicle_type.name for v
                        in self._vehicles_charging])
        # return count_vehicles_by_type(self.fleet.vehicle_types,
        #                               self._vehicles_charging)

    def _remove(self, vehicle):
        # if vehicle in self._vehicles_charging:
        #     raise ValueError('  t = %d: Tried to remove vehicle from depot
        #     while charging' % self.env.now)
        if vehicle in self._vehicles_in_service:
            raise ValueError('  t = %d (%s): Tried to remove vehicle from depot while '
                             'in service' % (self.env.now,
                                             hms_str(self.env.now)))
            raise ValueError('  t = %d: Tried to remove vehicle from depot '
                             'while in service' % self.env.now)
        if vehicle in self._vehicles_ready:
            self._vehicles_ready.remove(vehicle)
        if vehicle in self._vehicles_out_of_service:
            self._vehicles_out_of_service.remove(vehicle)
        if vehicle in self._vehicles_charging:
            self._vehicles_charging.remove(vehicle)

    def request_vehicle(self, vehicle_type_string, required_range):
        logger = logging.getLogger('depot_logger')
        match = False
        stop_charging = False
        for vehicle in self._vehicles_ready:
            if vehicle.vehicle_type.name == vehicle_type_string:
                match = True
                break

        if not match and self.interrupt_charging:
            # Try to find a charging vehicle with sufficient SoC
            for vehicle in self._vehicles_charging:
                if vehicle.vehicle_type.name == vehicle_type_string and \
                        vehicle.range_estimate() >= required_range:
                    match = True
                    stop_charging = True
                    break

        if match:
            # Remove vehicle from stack BEFORE yielding to stop_charging;
            # otherwise, we would get into trouble if a new schedule begins
            # while waiting for stop_charging:
            self._remove(vehicle)

        if stop_charging:
            # Stop charging
            yield self.env.process(vehicle.stop_charging())

        if match:
            logger.debug('  t = %d (%s): Vehicle %d now entering service at '
                        'depot %d' % (self.env.now, hms_str(self.env.now),
                                      vehicle.ID, self.ID))

        if not match:
            # Create a new vehicle
            vehicle = self.fleet.create_vehicle(vehicle_type_string)
            logger.debug('  t = %d (%s): Created new vehicle %d at depot %d' %
                        (self.env.now, hms_str(self.env.now),
                         vehicle.ID, self.ID))

        self._vehicles_in_service.append(vehicle)
        self.state_change_event()

        # Pseudo timeout to ensure we always reach a yield statement
        # (otherwise, this function would not work as a simpy process):
        yield self.env.timeout(0)
        return vehicle

    def return_vehicle(self, vehicle):
        logger = logging.getLogger('depot_logger')
        if vehicle in self._vehicles_in_service:
            self._vehicles_in_service.remove(vehicle)
            logger.debug('  t = %d (%s): Vehicle %d returned to '
                        'depot no. %d' % (self.env.now, hms_str(self.env.now),
                                          vehicle.ID, self.ID))
        else:
            logger.warning('  t = %d (%s): Trying to return unknown vehicle %d to '
                           'depot no. %d' % (self.env.now, hms_str(self.env.now),
                                             vehicle.ID, self.ID))
            logger.warning('  t = %d: Trying to return unknown vehicle %d to '
                           'depot no. %d'
                           % (self.env.now, vehicle.ID, self.ID))
        self._vehicles_out_of_service.append(vehicle)
        self._vehicles_charging.append(vehicle)
        self.state_change_event()
        self.env.process(self._charge(vehicle))

    def _charge(self, vehicle):
        logger = logging.getLogger('depot_logger')
        yield self.env.timeout(self.dead_time_before)
        yield self.env.process(vehicle.charge_full())
        yield self.env.timeout(self.dead_time_after)
        if vehicle in self._vehicles_charging:
            self._vehicles_charging.remove(vehicle)
            self._vehicles_ready.append(vehicle)
        # If charging was interrupted, the vehicle will have been removed from
        # _vehicles_charging already; no need to add to _vehicles_ready
        # as the vehicle will go into service directly
        logger.debug('  t = %d (%s): Vehicle %d now ready for service at depot %d' %
                    (self.env.now, hms_str(self.env.now),
                     vehicle.ID, self.ID))
        self.state_change_event()


# class SimpleDepot:
#     """Very simple depot model without pooling and charging simulation.
#     A a new vehicle is created for each schedule. Use this if only route
#     simulation is of interest."""
#     def __init__(self, env, location, fleet, ID=None, charging_network=None):
#         self._vehicles_in_service = deque()
#         self._vehicles_out_of_service = deque()
#         self.env = env
#         self.ID = ID
#         self.location = location
#         self.fleet = fleet
#         self.charging_network = charging_network
#         self.state_change_event = eflips.events.EventHandler(self)
#
#         # Invoke DataLogger
#         self.log_attributes = {
#             'num_vehicles_in_service': {
#                 'attribute': 'num_vehicles_in_service',
#                 'name': 'Number of vehicles in service',
#                 'unit': None,
#                 'discrete': True
#             },
#             'num_vehicles_out_of_service': {
#                 'attribute': 'num_vehicles_out_of_service',
#                 'name': 'Number of vehicles out of service',
#                 'unit': None,
#                 'discrete': True
#             }
#         }
#         self.params = {'ID': self.ID,
#                        'name': self.location.name}
#         self.logger = DataLogger(self.env, self)
#
#     @property
#     def num_vehicles_in_service(self):
#         return count_vehicles_by_type(self.fleet.vehicle_types,
#                                       self._vehicles_in_service)
#
#     @property
#     def num_vehicles_out_of_service(self):
#         return count_vehicles_by_type(self.fleet.vehicle_types,
#                                       self._vehicles_out_of_service)
#
#     def request_vehicle(self, vehicle_type):
#         vehicle = self.fleet.create_vehicle(vehicle_type)
#         self._vehicles_in_service.append(vehicle)
#         self.state_change_event()
#         logger = logging.getLogger('depot_logger')
#         logger.debug('t = %d: Requesting vehicle of type %s from depot no. %d' %
#                     (self.env.now, vehicle_type.name, self.ID))
#         logger.info('t = %d: Requesting vehicle of type %s from depot no.
#         %d' % (self.env.now, vehicle_type.name, self.ID))
#         return vehicle
#
#     def return_vehicle(self, vehicle):
#         logger = logging.getLogger('depot_logger')
#         if vehicle in self._vehicles_in_service:
#             self._vehicles_in_service.remove(vehicle)
#             self._vehicles_out_of_service.append(vehicle)
#             self.state_change_event()
#             logger.debug('t = %d: Returning vehicle of type %s to depot no. %d' %
#                 (self.env.now, vehicle.vehicle_type.name, self.ID))
#             logger.info('t = %d: Returning vehicle of type %s to depot
#             no. %d' % (self.env.now, vehicle.vehicle_type.name, self.ID))
#         else:
#             logger.warning('t = %d: Trying to return unknown
#             vehicle to depot no. %d' % (self.env.now, self.ID))


class DepotContainerAbstract(metaclass=ABCMeta):
    def __init__(self, env, fleet):
        self.env = env
        self.fleet = fleet
        self._depot_stack = LocationMapContainer()

    def _count_vehicles_by_type(self, attribute_name):
        # This is a slight hack required because sum() does not work on Counter
        # objects
        return sum([getattr(depot, attribute_name) for depot in
                    self._depot_stack.get_all()], Counter())
        # depots = self._depot_stack.get_all()
        # res = Counter()
        # for depot in depots:
        #     res += getattr(depot, attribute_name)
        # return res

    # def _count_vehicles_by_type(self, attribute_name):
    #     """Output a dict with vehicle count over all depots, with the vehicle
    #     type name as keys and a 'total' key with the sum.
    #
    #     attribute_name can be any attribute/property name of the Depot class
    #     used that returns a dict of the same form, e.g.
    #     'num_vehicles_in_service'.
    #     """
    #     out = dict([(t.name, 0) for t in self.fleet.vehicle_types])
    #     out.update({'total': 0})
    #     for depot in self._depot_stack.get_all():
    #         num_vehicles = getattr(depot, attribute_name)
    #         for vtype_name, count in num_vehicles.items():
    #             out[vtype_name] += count
    #     return out

    @property
    def num_vehicles_in_service(self):
        return self._count_vehicles_by_type('num_vehicles_in_service')

    @property
    def num_vehicles_out_of_service(self):
        return self._count_vehicles_by_type('num_vehicles_out_of_service')

    def get_by_location(self, location):
        try:
            return self._depot_stack.get_by_location(location)
        except KeyError:
            raise DepotNotFoundError('No depot at location %s'
                                     % location.name)

    def get_all(self):
        return self._depot_stack.get_all()

    def get_all_by_ID(self):
        return self._depot_stack.get_all_by_ID()

    @abstractmethod
    def create_depot(self, location):
        pass


class SimpleDepotContainer(DepotContainerAbstract):
    def __init__(self, env, fleet, charging_network=None):
        super().__init__(env, fleet)
        self.charging_network = charging_network
        self.state_change_event = eflips.events.EventHandler(self)

        # Invoke DataLogger
        self.log_attributes = {
            'num_vehicles_in_service': {
                'attribute': 'num_vehicles_in_service',
                'name': 'Number of vehicles in service',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_out_of_service': {
                'attribute': 'num_vehicles_out_of_service',
                'name': 'Number of vehicles out of service',
                'unit': None,
                'discrete': True
            }
        }

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    def create_depot(self, location):
        new_depot = SimpleDepot(self.env, location, self.fleet,
                                charging_network=self.charging_network)
        new_depot.state_change_event.add(self._update)
        self._depot_stack.add(new_depot)

    def _update(self, sender):
        self.state_change_event()


class DepotWithChargingContainer(DepotContainerAbstract):
    def __init__(self, env, fleet, charging_network=None):
        super().__init__(env, fleet)
        self.charging_network = charging_network
        self.state_change_event = eflips.events.EventHandler(self)

        # Invoke DataLogger
        self.log_attributes = {
            'num_vehicles_in_service': {
                'attribute': 'num_vehicles_in_service',
                'name': 'Number of vehicles in service',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_out_of_service': {
                'attribute': 'num_vehicles_out_of_service',
                'name': 'Number of vehicles out of service',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_charging': {
                'attribute': 'num_vehicles_charging',
                'name': 'Number of vehicles charging/being serviced',
                'unit': None,
                'discrete': True
            },
            'num_vehicles_ready': {
                'attribute': 'num_vehicles_ready',
                'name': 'Number of vehicles ready for service',
                'unit': None,
                'discrete': True
            }
        }

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    @property
    def num_vehicles_charging(self):
        return self._count_vehicles_by_type('num_vehicles_charging')

    @property
    def num_vehicles_ready(self):
        return self._count_vehicles_by_type('num_vehicles_ready')

    def create_depot(self, location, dead_time_before=0, dead_time_after=0,
                     interrupt_charging=False):
        new_depot = DepotWithCharging(self.env, location, self.fleet,
                                      charging_network=self.charging_network,
                                      dead_time_before=dead_time_before,
                                      dead_time_after=dead_time_after,
                                      interrupt_charging=interrupt_charging)
        new_depot.state_change_event.add(self._update)
        self._depot_stack.add(new_depot)

    def _update(self, sender):
        self.state_change_event()


# class SimpleDepotContainer:
#     def __init__(self, env, fleet, charging_network=None):
#         self.env = env
#         self.fleet = fleet
#         self.charging_network = charging_network
#         self._depot_stack = LocationMapContainer()
#         self.state_change_event = eflips.events.EventHandler(self)
#
#         # Invoke DataLogger
#         self.log_attributes = {
#             'num_vehicles_in_service': {
#                 'attribute': 'num_vehicles_in_service',
#                 'name': 'Number of vehicles in service',
#                 'unit': None,
#                 'discrete': True
#             },
#             'num_vehicles_out_of_service': {
#                 'attribute': 'num_vehicles_out_of_service',
#                 'name': 'Number of vehicles out of service',
#                 'unit': None,
#                 'discrete': True
#             }
#         }
#
#         self.logger = DataLogger(self.env, self)
#
#     def _count_vehicles_by_type(self, attribute_name):
#         out = dict([(t.name, 0) for t in self.fleet.vehicle_types])
#         out.update({'total': 0})
#         for depot in self._depot_stack.get_all():
#             num_vehicles = getattr(depot, attribute_name)
#             for vtype_name, count in num_vehicles.items():
#                 out[vtype_name] += count
#         return out
#
#     @property
#     def num_vehicles_in_service(self):
#         return self._count_vehicles_by_type('num_vehicles_in_service')
#
#     @property
#     def num_vehicles_out_of_service(self):
#         return self._count_vehicles_by_type('num_vehicles_out_of_service')
#
#     def create_depot(self, location):
#         new_depot = SimpleDepot(self.env, location, self.fleet,
#                                 charging_network=self.charging_network)
#         new_depot.state_change_event.add(self._update)
#         self._depot_stack.add(new_depot)
#
#     def get_by_location(self, location):
#         try:
#             return self._depot_stack.get_by_location(location)
#         except KeyError:
#             raise DepotNotFoundError('No depot at location %s'
#                                      % location.name)
#
#     def get_all(self):
#         return self._depot_stack.get_all()
#
#     def get_all_by_ID(self):
#         return self._depot_stack.get_all_by_ID()
#
#     def _update(self, sender):
#         self.state_change_event()


class Dispatcher:
    def __init__(self, env, schedules, fleet, depot_container=None,
                 driver_additional_paid_time=0,
                 line_monitor=None):
        self.env = env
        self.schedules = schedules
        self.schedules.sort_by_departure()
        self.fleet = fleet
        self.depot_container = depot_container
        self.driver_additional_paid_time = driver_additional_paid_time
        self.line_monitor = line_monitor
        self.run()

    def run(self):
        for schedule_node in self.schedules.get_all():
            self.env.process(self.run_schedule(schedule_node))

    def run_schedule(self, schedule):
        logger = logging.getLogger('depot_logger')
        # Wait until schedule begins:
        timeout = abs(schedule.root_node.departure) - self.env.now
        yield self.env.timeout(timeout)

        # Request vehicle:
        vehicle_type_string = schedule.root_node.vehicle_type
        # origin = first_leg.children[0].origin
        origin = schedule.root_node.origin

        try:
            # Request vehicle from depot:
            request_proc = self.env.process(
                self.depot_container.get_by_location(origin).request_vehicle(
                    vehicle_type_string, schedule.root_node.distance))
            yield request_proc
            vehicle = request_proc.value
        except (DepotNotFoundError, AttributeError):
            # Schedule does not start at a depot or no depots present
            logger.warning('  t = %d (%s): Schedule %d does not start at depot or no '
                            'depots present!' % (self.env.now,
                                                 hms_str(self.env.now),
                                                 schedule.root_node.ID))
            vehicle = self.fleet.create_vehicle(vehicle_type_string)

        # Assign driver or use existing one
        if vehicle.driver is None:
            driver = Driver(self.env, vehicle)
            if self.line_monitor is not None:
                driver.start_trip_event.add(self.line_monitor.start_trip)
                driver.end_trip_event.add(self.line_monitor.end_trip)

        # Wait for driver to finish:
        yield self.env.process(
            vehicle.driver.drive_schedule(
                schedule, additional_paid_time=
                self.driver_additional_paid_time))

        # Try to return vehicle to depot:
        destination = vehicle.location
        try:
            self.depot_container.get_by_location(destination)\
                .return_vehicle(vehicle)
        except (DepotNotFoundError, AttributeError):
            # Do nothing, leave vehicle as it is:
            pass


class LineMonitor:
    def __init__(self, env):
        self.env = env
        self.trips_per_line = CalcDict()
        self.state_change_event = eflips.events.EventHandler(self)

        # Invoke DataLogger
        self.log_attributes = {
            'trips_per_line': {
                'attribute': 'trips_per_line',
                'name': 'Number of parallel trips per line',
                'unit': None,
                'discrete': True
            }
        }

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    def start_trip(self, _, trip_node):
        if trip_node.trip_type == 'passengerTrip':
            if hasattr(trip_node, 'line'):
                if not trip_node.line in self.trips_per_line:
                    self.trips_per_line.update({trip_node.line: 0})
                self.trips_per_line[trip_node.line] += 1
        elif trip_node.trip_type == 'emptyTrip':
            if not 'empty' in self.trips_per_line:
                self.trips_per_line.update({'empty': 0})
            self.trips_per_line['empty'] += 1
        self.state_change_event()

    def end_trip(self, _, trip_node):
        if trip_node.trip_type == 'passengerTrip':
            if hasattr(trip_node, 'line'):
                if not trip_node.line in self.trips_per_line:
                    self.trips_per_line.update({trip_node.line: 0})
                else:
                    self.trips_per_line[trip_node.line] -= 1
        elif trip_node.trip_type == 'emptyTrip':
            if not 'empty' in self.trips_per_line:
                self.trips_per_line.update({'empty': 0})
            else:
                self.trips_per_line['empty'] -= 1
        self.state_change_event()
