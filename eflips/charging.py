# -*- coding: utf-8 -*-

# To Do:
# ChargingFacility --> ChargingPoint, ChargingSegment
# ChargingNetwork

from eflips.energy import Port, MultiPort
from eflips.grid import GridPoint, GridSegment
from eflips.misc import IndexedContainer
from eflips.settings import global_constants
from eflips.evaluation import DataLogger
from abc import ABCMeta
import logging
import simpy
import eflips.events
from functools import total_ordering
# import folium
import pandas as pd
import base64
import io


@total_ordering
class Slot:
    """A slot to charge a vehicle.

    Tobias Altmann"""

    def __init__(self, ID):
        self.ID = ID

    def __eq__(self, other):
        return self.ID == other.ID

    def __nq__(self, other):
        return not self == other

    def __lt__(self, other):
        return self.ID < other.ID


class SlotPool(simpy.PriorityStore):
    """Tobias Altmann"""
    def __init__(self, env, numSlots):
        super().__init__(env, capacity=numSlots)
        self.request = super().get
        # self.release = super().put
        for ID in range(1, numSlots+1):
            self.put(Slot(ID))

    def release(self, request):
        if request in self.queue:
            request.cancel()
        elif request.value not in self.items:
            super().put(request.value)
        else:
            logger = logging.getLogger(('charging_logger'))
            logger.warning('t = %d: Trying to release charging slot '
                           'that is already free' % self._env.now)

    @property
    def count(self):
        return self.capacity - len(self.items)

    @property
    def queue(self):
        return self.get_queue

    @property
    def free(self):
        return [slot.ID for slot in self.items]

    @property
    def occupied(self):
        free = self.free
        return [ID for ID in range(1, self.capacity+1) if ID not in free]


class ChargingFacility(metaclass=ABCMeta):
    def __init__(self, env, interface_type, location, capacity,
                 manoeuvre_duration_before, manoeuvre_duration_after, ID=None):
        self.env = env
        self.ID = ID
        self.interface_type = interface_type
        self.location = location
        self.capacity = capacity
        self.manoeuvre_duration_before = manoeuvre_duration_before
        self.manoeuvre_duration_after = manoeuvre_duration_after
        # self.slots = simpy.Resource(env, capacity)
        self.slots = SlotPool(env, capacity)
        self.loads = MultiPort(interface_type.medium)
        self.in_port = Port(interface_type.medium)
        self.max_occupation = 0

        self.state_change_event = eflips.events.EventHandler(self)
        self.log_attributes = {
            'num_vehicles': {'attribute': 'slots.count',
                             'name': 'Number of vehicles',
                             'unit': '1',
                             'discrete': True},
        }
        self.log_params = {
            'location': self.location,
            'interface_type': self.interface_type.name,
            'capacity': self.capacity,
            'manoeuvre_duration_before': manoeuvre_duration_before,
            'manoeuvre_duration_after': manoeuvre_duration_after
        }

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    # @abstractmethod
    def request(self):
        logger = logging.getLogger('charging_logger')
        logger.debug('Requesting charging slot')
        req = self.slots.request()
        self.env.process(self._schedule_update(req))
        return req

    # @abstractmethod
    def release(self, req):
        logger = logging.getLogger('charging_logger')
        # if self.slots.count != 0:
        logger.debug('Releasing charging slot')
        self.slots.release(req)
        self.state_change_event()
        # else:
        #     logger.debug('Tried to release charging slot but all slots are free!')

    @property
    def is_vacant(self):
        return self.slots.count < self.capacity

    def _schedule_update(self, req):
        yield req
        if self.slots.count > self.max_occupation:
            self.max_occupation = self.slots.count
        self.state_change_event()


class ChargingPoint(ChargingFacility):
    def __init__(self, env, interface_type, location, capacity, ID=None,
                 manoeuvre_duration_before=0, manoeuvre_duration_after=0):
        super().__init__(env, interface_type, location, capacity,
                         manoeuvre_duration_before, manoeuvre_duration_after,
                         ID=ID)
    # def request(self):
    #     # if not (global_constants['SKIP_CHARGING_WHEN_OCCUPIED'] and self.slots.count == self.capacity):
    #     # if global_constants['DEBUG_MSGS']:
    #     #     print('t = %d: Requesting charging slot' % self.env.now)
    #     req = self.slots.request()
    #     self.env.process(self._schedule_update(req))
    #     # else:
    #     #     req = None
    #     return req
    #
    # def release(self, req):
    #     # if req is not None:
    #     # if global_constants['DEBUG_MSGS']:
    #     #     print('t = %d: Releasing charging slot' % self.env.now)
    #     # self.slots.release(req.value)
    #     self.slots.release(req)
    #     self.state_change_event()


class ChargingSegment(ChargingFacility):
    def __init__(self, env, interface_type, location, capacity, ID=None):
        super().__init__(env, interface_type, location, capacity, 0, 0, ID=ID)
    # def request(self):
    #     logger = logging.getLogger('charging_logger')
    #     logger.debug('Requesting charging segment')
    #     req = self.slots.request()
    #     return req
    #
    # def release(self, req):
    #     logger = logging.getLogger('charging_logger')
    #     logger.debug('Releasing charging segment')
    #     self.slots.release(req)


class ChargingFacilityContainer(IndexedContainer):
    """Container class for ChargingFacilities for use in ChargingNetwork."""
    def __init__(self):
        super().__init__()
        self._location_map = dict()
    
    def add(self, obj):
        self._add(obj)
        
        if obj.location in self._location_map:
            # There is already a facility at this location.
            if obj.interface_type in \
                    self._location_map[obj.location]:
                # facility with same interface already exists here, ignore:
                logger = logging.getLogger('charging_logger')
                logger.warning('Trying to add facility obj at %s '
                               'with interface %s, but facility with same '
                               'interface already exists! Ignoring '
                               'new facility.' %
                               (obj.location.name,
                                obj.interface_type.name))
            else:
                # Update interface dict at this location:
                self._location_map[obj.location].update(
                    {obj.interface_type: obj}
                )
        else:
            # No obj at this location:
            self._location_map.update(
                {obj.location: {obj.interface_type: obj}})

    def get_by_location(self, location):
        return self._location_map[location]


class ChargingNetwork:
    def __init__(self, env):
        self.env = env
        self._point_stack = ChargingFacilityContainer()
        self._segment_stack = ChargingFacilityContainer()

    def get(self, point_or_segment):
        """
        Return a dict of the form {ChargingInterfaceType: ChargingFacility}
        with the keys being all interface types available at the specified
        location and the values being the corresponding ChargingPoint or
        ChargingSegment objects.
        """
        if isinstance(point_or_segment, GridPoint):
            return self.get_point(point_or_segment)
        elif isinstance(point_or_segment, GridSegment):
            return self.get_segment(point_or_segment)

    def get_point(self, location):
        try:
            return self._point_stack.get_by_location(location)
        except KeyError:
            return None

    def get_segment(self, location):
        try:
            return self._segment_stack.get_by_location(location)
        except KeyError:
            return None

    def create_point(self, interface_type, location, capacity):
        new_point = ChargingPoint(self.env, interface_type, location, capacity)
        self._point_stack.add(new_point)

    def create_segment(self, interface_type, location, capacity):
        new_segment = ChargingSegment(self.env, interface_type, location, capacity)
        self._segment_stack.add(new_segment)

    def get_all_points_by_ID(self):
        return self._point_stack.get_all_by_ID()

    def get_all_segments_by_ID(self):
        return self._segment_stack.get_all_by_ID()