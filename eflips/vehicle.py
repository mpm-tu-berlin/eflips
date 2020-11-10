# -*- coding: utf-8 -*-
import simpy
import random
import logging
import eflips.events
import numpy as np
from abc import ABCMeta, abstractmethod
from eflips.schedule import LegNode, DrivingProfile, \
    ChargingScheduleParameterSet, ChargingParametersNotPresent, Interval
from eflips.energy import Units, EnergySubSystem, Port, Energy, EnergyFlow, \
    Fuels, ChargingInterface, ChargingInterfaceTypes, Battery, DieselTank, \
    MultiPort
from eflips.evaluation import DataLogger
from eflips.misc import IndexedContainer, interrupt_process, \
    Ambient, hms_str, CalcDict
from eflips.settings import global_constants
from collections import Counter
from eflips import io

# from bemu import SimpleTrainTractionWithPotentialEnergy


class VehicleType:
    def __init__(self, name, vehicle_architecture, params_dict):
        self.name = name
        self.architecture = vehicle_architecture
        self.params = params_dict


class VehicleAbstract(metaclass=ABCMeta):
    """Base class for all vehicles that make use of eFLIPS interval-based
    operation and charging logic."""
    def __init__(self, env, vehicle_type, charging_network, num_passengers=0,
                 kerb_weight=0, ID=None, charging_schedule=None, location=None):
        self.env = env
        self.vehicle_type = vehicle_type
        self._charging_network = charging_network
        self._num_passengers = num_passengers
        self._kerb_weight = kerb_weight
        self.ID = ID
        self._charging_schedule = charging_schedule
        self._location = location

        self.odo = 0  # odometer (total distance in km); replace with proper unit later?
        self.operation_time = 0  # total time in operation
        self._ignition_on = False
        self._ac_request = False
        self.delay = 0
        self._driving = False  # stationary or driving

        # Attributes to be added/modified by subclasses:
        self._subsystems = dict()
        self.traction = None
        self.subsystem_primary = None  # primary energy subsystem
        self.energy_storage_primary = None  # primary energy storage

        # To be modified after instantiation:
        self.driver = None
        self.mission_list = []

        # Attribute for processes that may need to be interrupted from outside:
        self.action = None

        # Events:
        self.state_change_event = eflips.events.EventHandler(self)
        self.driving_state_change_event = eflips.events.EventHandler(self)

    def _update(self, sender):
        self.state_change_event()
        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s), Vehicle %d: Total power %.2f kW' %
                     (self.env.now, hms_str(self.env.now), self.ID,
                      self.total_power_primary.energy_ref))

    def check_charging_state(self):
        for subsystem in self._subsystems.values():
            if not subsystem.storage.soc_valid:
                self._soc_valid = False

    def add_subsystem(self, energy_subsystem):
        self._subsystems.update({energy_subsystem.medium: energy_subsystem})

    def range_estimate(self):
        """Return an estimate of vehicle range based on the current storage
        capacity"""
        return self.energy_storage_primary.energy_remaining.energy_ref / \
            self.vehicle_type.params['range_estimation_consumption']

    @property
    def soc_valid(self):
        """Return True if ALL energy storage components have a valid SoC,
        otherwise False."""
        res = True
        for subsystem in self._subsystems.values():
            # Find first subsystem with invalid SoC and exit loop
            if not subsystem.storage.soc_valid:
                res = False
                break
        return res

    @property
    def soc_critical(self):
        """Return True if ANY energy storage component has a critical SoC,
        otherwise False."""
        res = False
        for subsystem in self._subsystems.values():
            # Find first subsystem with critical SoC and exit loop
            if subsystem.storage.soc_critical:
                res = True
                break
        return res

    @property
    def soc_was_valid(self):
        """Return True if ALL energy storage components have a history of
        valid SoC, otherwise False."""
        res = True
        for subsystem in self._subsystems.values():
            # Find first subsystem with invalid SoC and exit loop
            if not subsystem.storage.soc_was_valid:
                res = False
                break
        return res

    @property
    def soc_was_critical(self):
        """Return True if ANY energy storage component has a history of
        critical SoC, otherwise False."""
        res = False
        for subsystem in self._subsystems.values():
            # Find first subsystem with critical SoC and exit loop
            if subsystem.storage.soc_was_critical:
                res = True
                break
        return res

    @abstractmethod
    def _create_primary_subsystem(self, *args, **kwargs):
        # Inheriting classes MUST create at least one (i.e., the primary)
        # subsystem by calling this method from their __init__ method after
        # calling super().__init__.
        # In this method, (1) the subsystem must be added to the vehicle using
        # self.add_subsystem(), (2) self._update() must be added as a callback
        # for state changes of the subsystem.
        # This would usually look like this:
        # subsystem.controller.state_change_event.add(self._update)
        pass

    @property
    def ignition_on(self):
        return self._ignition_on

    @ignition_on.setter
    def ignition_on(self, value):
        # What we really want to do here is make the setter an abstract method.
        # However, Python does not allow an abstract setter without an abstract
        # getter. Solution: Redirect to abstract method _set_ignition().
        self._set_ignition(value)

    @abstractmethod
    def _set_ignition(self, value):
        pass

    @property
    def ac_request(self):
        return self._ac_request

    @ac_request.setter
    def ac_request(self, value):
        self._set_ac_request(value)

    @abstractmethod
    def _set_ac_request(self, value):
        pass

    @property
    def kerb_weight(self):
        return self._kerb_weight

    @property
    def payload(self):
        return self.num_passengers * \
               global_constants['AVERAGE_PASSENGER_WEIGHT_KG']

    @property
    def total_mass(self):
        return self._kerb_weight + self.payload

    @property
    def num_passengers(self):
        return self._num_passengers

    @num_passengers.setter
    def num_passengers(self, value):
        self._set_num_passengers(value)

    @abstractmethod
    def _set_num_passengers(self, value):
        # Inheriting classes can play around with status updates upon
        # passenger load change
        pass

    @abstractmethod
    def total_power_primary(self):
        pass

    @property
    def velocity(self):
        if hasattr(self.traction, 'velocity'):
            return self.traction.velocity
        else:
            return 0


    @property
    @abstractmethod
    def energy_charged_primary(self):
        pass

    @property
    @abstractmethod
    def energy_consumed_primary(self):
        pass

    @property
    def specific_consumption_primary(self):
        if self.odo == 0:
            return Energy.from_energy_ref(self.energy_storage_primary.medium,
                                          0)
        else:
            return self.energy_consumed_primary/self.odo

    @property
    def driving(self):
        return self._driving

    @driving.setter
    def driving(self, value):
        if not value == self._driving:
            self._driving = value
            self.driving_state_change_event()

    @property
    def location(self):
        return self._location

    def drive_leg(self, leg_node):
        """New driving method; includes the pause following a leg."""
        if not isinstance(leg_node, LegNode):
            logger = logging.getLogger('vehicle_logger')
            logger.error('leg_node must be of type LegNode')
            raise TypeError('leg_node must be of type LegNode')

        self.delay = self.env.now - abs(leg_node.departure)
        # +++ DEBUG +++
        # if self.delay < 0:
        #     print('gotcha')
        time_leg_begin = self.env.now

        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s), Vehicle %s: driving from %s to %s; departure '
                  'delay: %d' % (self.env.now, hms_str(self.env.now), self.ID, leg_node.origin.name,
                                 leg_node.destination.name, self.delay))

        # Switch on AC if it is off:
        if not self.ac_request:
            self.ac_request = True

        # Pass leg node to traction consumption model. Traction model is
        # responsible for unpacking the leg into segments:
        self.env.process(self.traction.drive(leg_node))

        # Iterate over segments and call interface controller
        num_segments = len(leg_node.children)
        for i, segment in enumerate(leg_node.children):
            # time_segment_begin = self.env.now
            loc = segment.grid_segment
            logger.debug('t = %d, (%s), Vehicle %s: driving over segment %s; '
                         'distance %.1f; duration %d; departure delay: %d' %
                         (self.env.now, hms_str(self.env.now), self.ID,
                          segment.grid_segment.name,
                          segment.grid_segment.distance,
                          segment.duration,
                          self.delay))
            try:
                if global_constants['DELAYS']:
                    dur = segment.duration + segment.delay
                else:
                    dur = segment.duration
            except (KeyError, AttributeError):
                dur = segment.duration
            if i == num_segments-1:
                # last segment; next location is gridpoint
                nextloc = loc.destination
            else:
                # next location is another segment
                if segment.get_right() is not None:
                    nextloc = segment.get_right().grid_segment
                else:
                    nextloc = None
            logger.debug('t = %d, (%s), Vehicle %s: next location is %s "%s"' %
                         (self.env.now, hms_str(self.env.now),
                          self.ID, nextloc.type_, nextloc.name))
            self._location = loc
            self.driving = True
            self.state_change_event()
            # Call interface controller and yield
            yield self.env.process(
                self._interface_controller(
                    leg_node,
                    Interval(loc, dur, nextloc)))  # Interval class is
            # superflous

            # Segment finished. Update delay, odo and operation time
            self.delay = self.env.now - abs(segment.arrival)
            # +++ DEBUG +++
            # if self.delay < 0:
            #     print('gotcha')
            self.odo += loc.distance
            # self.operation_time += (self.env.now - time_segment_begin)
            self.state_change_event()

        # We are at the end of the leg.
        driving_time = self.env.now - time_leg_begin
        loc = nextloc
        self._location = loc  # this is a GridPoint
        self.driving = False
        if 'switch_off_ac_in_pause' in self.vehicle_type.params:
            if self.vehicle_type.params['switch_off_ac_in_pause']:
                self.ac_request = False

        logger.debug('t = %d (%s), Vehicle %d: arrived at %s; arrival delay %d'
                     % (self.env.now, hms_str(self.env.now),
                        self.ID, self._location.name, self.delay))

        # Shorten pause duration by delay in order
        # to enable punctual departure.
        # It may become negative, but interface controller can handle this:
        dur = leg_node.pause - self.delay
        if segment.get_right() is not None:
            nextloc = segment.get_right().grid_segment
        else:
            nextloc = None

        logger.debug('t = %d (%s), Vehicle %d: pausing at %s for %d' %
                  (self.env.now, hms_str(self.env.now), self.ID, self._location.name, dur))

        break_begin = self.env.now

        # Call interface controller for pause, and yield:
        yield self.env.process(
            self._interface_controller(
                leg_node,
                Interval(loc, dur, nextloc)))  # Interval class is superflous

        break_time = self.env.now - break_begin

        self.operation_time += (driving_time + break_time)
        self.state_change_event()

        return driving_time, break_time

    def drive_profile(self, driving_profile):
        if not isinstance(driving_profile, DrivingProfile):
            logger = logging.getLogger('vehicle_logger')
            logger.error('driving_profile must be of type DrivingProfile')
            raise TypeError('driving_profile must be of type DrivingProfile')

        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s), Vehicle %s: Starting driving profile %s'
                     % (self.env.now, hms_str(self.env.now), self.ID,
                        driving_profile.name))

        self.driving = True
        self.state_change_event()

        # Pass driving profile to traction consumption model
        yield self.env.process(self.traction.drive(driving_profile))
        self.odo += driving_profile.total_distance/1000
        self.operation_time += driving_profile.total_time
        self.driving = False

        self.state_change_event()
        logger.debug('t = %d (%s), Vehicle %s: Finished driving profile %s'
                     % (self.env.now, hms_str(self.env.now), self.ID,
                        driving_profile.name))

    def charge_full(self):
        """Force full charge at current location. This requires a suitable
        charging facility to exist in the charging network at this location!"""

        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s): Vehicle %d attempting full charge at %s' %
                     (self.env.now, hms_str(self.env.now), self.ID, self.location.name))

        # Construct a dummy interval (required for _charging_process()). The
        # duration of 0 is overridden by the ChargingScheduleParameterSet
        # generated later, where charge_full=True. We use 0 rather than
        # float('inf') here because we want the charging interface
        # to disconnect and undock once the vehicle is fully charged.
        # ToDo: Write method to release all charging slots (?)
        interval = Interval(self.location, 0, None)

        for subsystem in self._subsystems.values():
            # Determine whether a matching charging facility is available at
            # this location:
            interface, facility = \
                self._select_interface(subsystem, self.location)
            if interface is not None:
                # Construct a hard set of charging parameters. We set
                # release_when_full to True so that the Dispatcher does not
                # have to fiddle around with resource requests once the vehicle
                # leaves the depot for a new schedule.
                try_charging = True
                queue_for_charging = True
                charge_full = True
                release_when_full = True
                min_charge_duration = 0
                charging_params = ChargingScheduleParameterSet(
                    try_charging, queue_for_charging, charge_full,
                    release_when_full, min_charge_duration)

                # Invoke charging process:
                charging_proc = self.env.process(
                    self._charging_process(charging_params, interval,
                                           subsystem, interface, facility))
                yield charging_proc

    def stop_charging(self):
        """"Quit all charging processes in all subsystems."""
        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s): Vehicle %d interrupting charging at %s' %
                     (self.env.now, hms_str(self.env.now), self.ID, self.location.name))
        wait_for_processes = []
        for subsystem in self._subsystems.values():
            if subsystem.charging_handler_proc is not None:
                if subsystem.charging_handler_proc.is_alive:
                    subsystem.charging_handler_proc.interrupt()
                    wait_for_processes.append(subsystem.charging_handler_proc)

        # Wait for charging processes to finish (undocking etc.):
        if len(wait_for_processes) > 0:
            yield simpy.events.AllOf(self.env, wait_for_processes)

    @staticmethod
    def _charging_params_from_global():
        """Generate default charging parameter set from global_constants"""
        return ChargingScheduleParameterSet(
            global_constants['TRY_CHARGING'],
            queue_for_charging=global_constants['QUEUE_FOR_CHARGING'],
            charge_full=global_constants['CHARGE_FULL'],
            release_when_full=global_constants['RELEASE_WHEN_FULL'],
            min_charge_duration=global_constants['MIN_CHARGE_DURATION'])

    def _get_charging_params(self, location, leg_node):
        """Determine whether we can charge at the current location"""
        # if interface is not None:
        # Determine which schedule we are operating in order to look up
        # parameters from charging schedule. If no charging schedule exists
        # or the charging schedule does not provide parameters for our
        # schedule, use default values from global_constants:
        schedule_node = leg_node.parent.parent
        try:
            charging_params = self._charging_schedule.get(schedule_node,
                                                          location)
        except (AttributeError, ChargingParametersNotPresent):
            charging_params = self._charging_params_from_global()
        return charging_params
        # else:
        #     return None

    def _interface_controller(self, leg_node, interval):
        """This process determines whether a vehicle could charge at a specific
        location (i.e., whether the location provides a charging facility with
        an interface matching the vehicle), regardless of the time available.
        If charging is technically possible, _charging_process is called which
        takes care of all further factors (charging schedule, timing, queuing,
        ...).
        """
        charging_procs = []
        for subsystem in self._subsystems.values():
            # Determine whether a matching charging facility is available at
            # this location:
            interface, facility = \
                self._select_interface(subsystem, interval.location)
            if interface is not None:
                # We can charge! Get charging parameters.
                charging_params = self._get_charging_params(interval.location,
                                                            leg_node)
                charging_procs.append(self.env.process(
                    self._charging_process(charging_params, interval,
                                           subsystem, interface, facility)))
                # charging_proc = self.env.process(
                #     self._charging_process(charging_params, interval,
                #                            subsystem, interface, facility))
                # yield charging_proc
            else:
                # If duration is negative, yield a zero timeout:
                charging_procs.append(self.env.timeout(max(interval.duration,
                                                           0)))
                # yield self.env.timeout(max(interval.duration, 0))
        yield simpy.events.AllOf(self.env, charging_procs)

    def _charging_process(self, charging_params, interval, subsystem,
                          interface, facility):
        """This process consults the charging schedule to find out whether
        charging is desired at this time and location and whether the vehicle
        must queue for a charging slot. If there is enough time available,
        charging is started.
        """
        time_start = self.env.now
        if charging_params.try_charging:
            # Charging attempt is scheduled here
            if facility.is_vacant:
                # No need for queuing!
                queueing = False
                skip = False
            else:
                # Only attempt to charge if queuing is permitted
                if charging_params.queue_for_charging:
                    queueing = True
                    skip = False
                else:
                    skip = True
        else:
            # No scheduled charging attempt
            skip = True

        # ++++ CONTINUE HERE: Prevent docking at segments if interface is not
        # capable of dynamic docking ++++++

        if not skip:
            # Determine whether we have to dock and/or undock:
            dock, undock = self._get_dock_actions(subsystem, interval,
                                                  interface)

            # If we are queueing, we have to consider the time for manoeuvring
            # to the charging point:
            manoeuvre_before = queueing

            # Determine max. duration allowed for request:
            if charging_params.charge_full:
                # We have unlimited time because we MUST fully charge.
                # Invoke request handler without timekeeper:
                request = True
                req_handler = self.env.process(self._request_handler(facility))
                yield req_handler
            else:
                # We must stick to the interval time limit.
                time_passed = self.env.now - time_start
                max_request_time = self._get_time_remaining(
                    charging_params, interface.interface_type, facility,
                    interval.duration, time_passed, charge=True,
                    manoeuvre_before=manoeuvre_before, manoeuvre_after=False,
                    dock=dock, undock=undock)
                if max_request_time >= 0:
                    # Enough time available!
                    # Invoke request handler and timekeeper. If request handler
                    # has not switched to triggered=True after
                    # max_request_time,
                    # it will be interrupted by timekeeper (through callback
                    # function):
                    request = True
                    req_handler = self.env.process(
                        self._request_handler(facility))
                    req_timekeeper = self.env.process(
                        self._timekeeper(max_request_time))
                    interrupt_req_handler = lambda sender: \
                        interrupt_process(req_handler, sender)
                    req_timekeeper.callbacks.append(interrupt_req_handler)
                    yield req_handler
                else:
                    # Not enough time available; do not attempt request
                    request = False

            if request and req_handler.value:  # This is the return value
                # of the process
                # Request was successful, we can try to charge
                if queueing:
                    # Advance the vehicle to the charging facility
                    yield self.env.timeout(facility.
                                           manoeuvre_duration_before)
                if not interface.is_docked:
                    # Dock interface
                    yield self.env.process(interface.dock())
                interface.connect(facility)

                time_passed = self.env.now - time_start
                time_remaining = interval.duration - time_passed

                if charging_params.charge_full:
                    # Invoke charging handler without timekeeper
                    subsystem.charging_handler_proc = self.env.process(
                        self._finish_charging(req_handler.value, subsystem,
                                              interface, facility,
                                              time_remaining, charging_params,
                                              undock))
                    yield subsystem.charging_handler_proc
                else:
                    # Invoke charging handler and timekeeper
                    # time_passed = self.env.now - time_start
                    max_charge_time = self._get_time_remaining(
                        charging_params, interface.interface_type, facility,
                        interval.duration, time_passed, charge=False,
                        manoeuvre_before=False,
                        manoeuvre_after=False,
                        dock=False, undock=undock)
                    # time_remaining = interval.duration - time_passed
                    if max_charge_time < 0:
                        logger = logging.getLogger('vehicle_logger')
                        logger.error('Something went seriously wrong here.')
                        raise RuntimeError(
                            'Something went seriously wrong here.')
                    subsystem.charging_handler_proc = self.env.process(
                        self._finish_charging(req_handler.value, subsystem,
                                              interface, facility,
                                              time_remaining, charging_params,
                                              undock))

                    # +++++++++++ CONTINUE HERE +++++++++++

                    charging_timekeeper = self.env.process(
                        self._timekeeper(max_charge_time))
                    interrupt_charging_handler = lambda sender: \
                        interrupt_process(subsystem.charging_handler_proc,
                                          sender)
                    charging_timekeeper.callbacks.append(
                        interrupt_charging_handler)
                    yield subsystem.charging_handler_proc
            else:
                # Request didn't happen or it was interrupted (return value
                # False). Wait until end of interval:
                # (CAUTION: We should check again whether we have to undock)
                time_passed = self.env.now - time_start
                time_remaining = self._get_time_remaining(
                    charging_params, interface.interface_type, facility,
                    interval.duration, time_passed, charge=False,
                    manoeuvre_before=False, manoeuvre_after=False,
                    dock=False, undock=False)
                if time_remaining > 0:
                    yield self.env.timeout(time_remaining)
        else:
            # Do not attempt to request or charge; just wait for interval to
            # finish
            if interval.duration > 0:
                yield self.env.timeout(interval.duration)

    def _generate_fully_charged_event(self, subsystem):
        """Generate a simpy event that will trigger when a fully_charged_event
        is received from the energy storage. This allows yielding to the event.
        """
        fully_charged_event = self.env.event()
        subsystem.storage.fully_charged_event.add(fully_charged_event.succeed)
        return fully_charged_event

    def _finish_charging(self, request, subsystem, interface, facility,
                         max_duration, charging_params, undock):
        time_start = self.env.now

        try:
            # Wait for fully charged event:
            fully_charged_event = self._generate_fully_charged_event(subsystem)
            yield fully_charged_event

            time_passed = self.env.now - time_start
            time_remaining = self._get_time_remaining(
                charging_params, interface.interface_type, facility,
                max_duration, time_passed, charge=False,
                manoeuvre_before=False, manoeuvre_after=False,
                dock=False, undock=undock)
            logger = logging.getLogger('vehicle_logger')
            logger.debug('t = %d (%s), Vehicle %s: _charging_handler received '
                      'fully_charged_event after %d s. Time remaining: %d' %
                      (self.env.now, hms_str(self.env.now), self.ID,
                       time_passed, time_remaining))
            if charging_params.release_when_full:
                # Free up charging slot only if there is sufficient time for
                # the manoeuvre;
                # otherwise stay there until time is up (to avoid
                # delayed departure)
                manoeuvre = time_remaining >= facility.manoeuvre_duration_after
            else:
                # Stay at the charging slot until end of interval
                manoeuvre = False

            if manoeuvre:
                # Release facility
                yield self.env.process(
                    self._release_facility(interface, facility, request,
                                           undock))

                # Free up charging slot (manoeuvre):
                logger = logging.getLogger('vehicle_logger')
                logger.debug('t = %d (%s), Vehicle %d: advancing from '
                             'charging slot' %
                             (self.env.now, hms_str(self.env.now), self.ID))
                yield self.env.timeout(facility.manoeuvre_duration_after)

                # Determine time remaining and wait:
                time_passed = self.env.now - time_start
                time_remaining = self._get_time_remaining(
                    charging_params, interface.interface_type, facility,
                    max_duration, time_passed, charge=False,
                    manoeuvre_before=False, manoeuvre_after=False, dock=False,
                    undock=False)
                yield self.env.timeout(max(time_remaining, 0))
            else:
                # Stay put until end of interval
                # Determine time remaining and wait:
                time_passed = self.env.now - time_start
                time_remaining = self._get_time_remaining(
                    charging_params, interface.interface_type, facility,
                    max_duration, time_passed, charge=False,
                    manoeuvre_before=False, manoeuvre_after=False, dock=False,
                    undock=undock)
                yield self.env.timeout(max(time_remaining, 0))
                # Release facility
                yield self.env.process(
                    self._release_facility(interface, facility, request,
                                           undock))
        except simpy.Interrupt:
            # Release facility
            logger = logging.getLogger('vehicle_logger')
            logger.debug('t = %d (%s), Vehicle %d: '
                         'Interrupted charging handler'
                         % (self.env.now, hms_str(self.env.now), self.ID))
            yield self.env.process(
                self._release_facility(interface, facility, request,
                                       undock))

        # Remove the simpy event from the list of callbacks in the subsystem:
        try:
            last_event = subsystem.storage.fully_charged_event.callbacks[-1]
            if isinstance(last_event.__self__, simpy.events.Event):
                subsystem.storage.fully_charged_event.callbacks. \
                    remove(last_event)
        except IndexError:
            # Do nothing
            pass

    def _release_facility(self, interface, facility, request, undock):
        interface.disconnect()
        if undock:
            yield self.env.process(interface.undock())
        facility.release(request)

    def _request_handler(self, facility):
        """Process to request a charging facility. If not interrupted, a
        charging slot will be requested and further execution will be delayed
        until the slot is granted."""
        # Request charging slot
        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s), Vehicle %d: requesting charging slot at %s'
                     % (self.env.now, hms_str(self.env.now),
                        self.ID, facility.location.name))
        req = facility.request()
        try:
            yield req
            logger.debug('t = %d (%s), Vehicle %d: charging request at %s '
                         'granted' % (self.env.now, hms_str(self.env.now),
                                      self.ID, facility.location.name))
            return req
        except simpy.Interrupt:
            logger.debug('t = %d (%s), Vehicle %d: request at %s cancelled' %
                      (self.env.now, hms_str(self.env.now), self.ID, facility.location.name))
            facility.release(req)
            return None

    def _timekeeper(self, duration):
        """Simple timekeeping process. Create a process instance of this and
        add an appropriate callback function to interrupt other processes after
        passage of duration."""
        yield self.env.timeout(duration)

    @staticmethod
    def _get_time_remaining(charging_params, interface_type, facility,
                            max_duration, time_passed, charge=False,
                            manoeuvre_before=False, manoeuvre_after=False,
                            dock=False, undock=False):
        """Get time remaining until next action in order to finish interval
        on time. If the result is negative (i.e., we have already spent too
        much time, for example, waiting for a charging request), return zero.
        """
        min_charge_duration = charging_params.min_charge_duration
        dock_time = interface_type.dead_time_dock
        undock_time = interface_type.dead_time_undock
        manoeuvre_time_before = facility.manoeuvre_duration_before
        manoeuvre_time_after = facility.manoeuvre_duration_after

        time_remaining = max_duration - time_passed \
                         - charge * min_charge_duration \
                         - dock * dock_time \
                         - undock * undock_time \
                         - manoeuvre_before * manoeuvre_time_before \
                         - manoeuvre_after * manoeuvre_time_after

        return time_remaining

    def _get_dock_actions(self, subsystem, interval, interface):
        """Determine whether we have to dock at the beginning and undock at the
        end of the interval."""
        # Already docked?
        if interface.is_docked:
            dock = False
        else:
            dock = True

        # Get interface at next location:
        interface_next, facility_next = \
            self._select_interface(subsystem, interval.next_location)
        if interface_next is not None:
            if interface_next.interface_type == interface.interface_type:
                # We can continue using the interface
                undock = False
            else:
                # We cannot reuse the interface, but if dynamic undocking
                # is possible, we needn't undock until the next interval:
                if interface.interface_type.dynamic_undock:
                    undock = False
                else:
                    undock = True
        else:
            undock = True

        return dock, undock

    def _select_interface(self, subsystem, location):
        """Check if the current location provides a charging facility with an
        interface matching the vehicle. If it does, return the interface
        and the facility; if not, return None for both. If multiple facilities
        exist with different interfaces, the interface most preferred by the
        vehicle is chosen. (The list of vehicle-side interfaces,
        subsystem.interfaces, is expected to be sorted by priority in
        descending order.)

        """
        match_interface = None
        match_facility = None
        # Check for charging infra. We get a dict with available
        # ChargingInterfaceTypes as keys and the corresponding
        # ChargingFacility objects as values.

        if self._charging_network is not None:
            current_charging_facilities = \
                self._charging_network.get(location)
        else:
            current_charging_facilities = None

        # Select the correct interface per subsystem
        if current_charging_facilities is not None:
            # Vehicle-side interfaces are sorted by priority, so we
            # will automatically use them in their order of
            # preference:
            for interface in subsystem.interfaces:
                if interface.interface_type in \
                        current_charging_facilities.keys():
                    # Habemus interface! Return first match
                    match_interface = interface
                    match_facility = current_charging_facilities[
                        interface.interface_type]
                    break

        return match_interface, match_facility

    def _disconnect_all(self):
        """Disconnect all interfaces"""
        for subsystem in self._subsystems.values():
            for interface in subsystem.interfaces:
                if interface.is_connected:
                    interface.disconnect()

    def _undock_all(self):
        """Undock all interfaces"""
        for subsystem in self._subsystems.values():
            for interface in subsystem.interfaces:
                if interface.is_docked:
                    self.env.process(interface.undock())


class SimpleVehicle(VehicleAbstract):
    """Simple vehicle with one energy subsystem and a single, constant power
    auxiliary device."""
    def __init__(self, env, vehicle_type, charging_network,
                 traction, aux, storage, list_of_charging_interfaces,
                 kerb_weight,
                 num_passengers=0, ID=None,
                 charging_schedule=None, location=None):
        super().__init__(env, vehicle_type, charging_network,
                         kerb_weight=kerb_weight,
                         num_passengers=num_passengers, ID=ID,
                         charging_schedule=charging_schedule,
                         location=location)

        self._create_primary_subsystem(env, storage, traction, aux,
                                       list_of_charging_interfaces)

        # Invoke DataLogger
        self.log_attributes = {
            'ignition_on': {'attribute': 'ignition_on',
                            'name': 'Ignition',
                            'unit': 'boolean',
                            'discrete': True},

            'ac_request': {'attribute': 'ac_request',
                           'name': 'Air-Conditioning Request',
                           'unit': 'boolean',
                           'discrete': True},

            'driving': {'attribute': 'driving',
                        'name': 'Driving',
                        'unit': 'boolean',
                        'discrete': True},

            'velocity': {'attribute': 'velocity',
                         'name': 'Velocity',
                         'unit': 'm/s',
                         'discrete': False},

            'odo': {'attribute': 'odo',
                    'name': 'Odometer',
                    'unit': Units.distance.name,
                    'discrete': False},

            'operation_time': {'attribute': 'operation_time',
                               'name': 'Operation time',
                               'unit': Units.wall_time.name,
                               'discrete': False},

            'driver_time': {'attribute': 'driver.total_time',
                            'name': 'Driver total time',
                            'unit': Units.wall_time.name,
                            'discrete': False},

            'traction_power': {'attribute': 'traction_power.energy',
                               'name': 'Traction power',
                               'unit': Units.power.name,
                               'discrete': False},

            'aux_power_primary': {'attribute': 'aux_power_primary.energy',
                                  'name': 'Aux power',
                                  'unit': Units.power.name,
                                  'discrete': False},

            'total_power_primary': {'attribute': 'total_power_primary.energy',
                                    'name': 'Total power',
                                    'unit': Units.power.name,
                                    'discrete': False},

            'interface_power_primary':
                {'attribute': 'charging_interface_power_primary.energy',
                 'name': 'Interface power',
                 'unit': Units.power.name,
                 'discrete': False},

            'storage_power_primary':
                {'attribute': 'storage_power_primary.energy',
                 'name': 'Storage power',
                 'unit': Units.power.name,
                 'discrete': False},

            'soc_primary': {'attribute': 'energy_storage_primary.soc',
                            'name': 'State of charge',
                            'unit': '1',
                            'discrete': False},

            'soc_valid': {'attribute': 'soc_valid',
                          'name': 'State of charge valid',
                          'unit': 'boolean',
                          'discrete': True},

            'soc_critical': {'attribute': 'soc_critical',
                             'name': 'State of charge critical',
                             'unit': 'boolean',
                             'discrete': True},

            'location': {'attribute': 'location',
                         'name': 'Location',
                         'unit': None,
                         'discrete': False},

            'delay': {'attribute': 'delay',
                      'name': 'Delay',
                      'unit': Units.wall_time.name,
                      'discrete': False}
        }

        if self.energy_storage_primary.medium == Fuels.diesel:
            # Display energy in litres
            self.log_attributes.update({
                'capacity_primary': {
                    'attribute': 'energy_storage_primary.energy.volume',
                    'name': 'Capacity',
                    'unit': Units.volume.name,
                    'discrete': False},

                'energy_consumed_primary': {
                    'attribute': 'energy_consumed_primary.volume',
                    'name': 'Energy consumed',
                    'unit': Units.volume.name,
                    'discrete': False},

                'specific_consumption_primary': {
                    'attribute': 'specific_consumption_primary.volume',
                    'name': 'Specific consumption',
                    'unit': Units.volume.name + '/km',
                    'discrete': False},

                'energy_charged_primary': {
                    'attribute': 'energy_charged_primary.volume',
                    'name': 'Energy charged',
                    'unit': Units.volume.name,
                    'discrete': False}})
        else:
            # Display energy in kWh
            self.log_attributes.update({
                'capacity_primary': {
                    'attribute': 'energy_storage_primary.energy.energy',
                    'name': 'Capacity',
                    'unit': Units.energy.name,
                    'discrete': False},

                'energy_consumed_primary': {
                    'attribute': 'energy_consumed_primary.energy',
                    'name': 'Energy consumed',
                    'unit': Units.energy.name,
                    'discrete': False},

                'specific_consumption_primary': {
                    'attribute': 'specific_consumption_primary.energy',
                    'name': 'Specific consumption',
                    'unit': Units.energy.name + '/km',
                    'discrete': False},

                'energy_interface_primary': {
                    'attribute': 'energy_interface_primary.energy',
                    'name': 'Energy interface',
                    'unit': Units.energy.name,
                    'discrete': False},

                'energy_charged_primary': {
                    'attribute': 'energy_charged_primary.energy',
                    'name': 'Energy charged',
                    'unit': Units.energy.name,
                    'discrete': False}})

        self.log_params = {'vehicle_type': self.vehicle_type,
                           'medium': storage.medium.name}
        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    def _create_primary_subsystem(self, env, storage, traction, aux,
                                  list_of_charging_interfaces):
        # Assign components as attributes:
        self.energy_storage_primary = storage
        self.traction = traction
        self.traction.vehicle = self
        self.aux = aux

        # Create primary energy subsystem and add to vehicle:
        self.subsystem_primary = EnergySubSystem(
                self,
                env,
                storage,
                {'traction': traction.port,
                 'aux': aux.port},
                list_of_charging_interfaces
            )
        self.add_subsystem(self.subsystem_primary)

        # Add event listener to log changes in subsystem
        self.subsystem_primary.controller.state_change_event.add(self._update)

    def _set_ignition(self, value):
        self.traction.on = value
        self.aux.on = value
        self._ignition_on = value

    def _set_ac_request(self, value):
        self._ac_request = value

    def _set_num_passengers(self, value):
        self._num_passengers = value
        self.state_change_event()
        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s), Vehicle %d: Number of passengers set to %d' %
                     (self.env.now, hms_str(self.env.now),
                      self.ID, value))

    @property
    def traction_power(self):
        return self.traction.port.flow

    @property
    def aux_power_primary(self):
        return self.aux.port.flow

    @property
    def total_power_primary(self):
        return self.traction_power + self.aux_power_primary

    @property
    def charging_interface_power_primary(self):
        return self.subsystem_primary.controller.interface_port.flow

    @property
    def charging_interface_power_secondary(self):
        if hasattr(self, 'subsystem_secondary'):
            return self.subsystem_secondary.controller.interface_port.flow
        else:
            return None

    @property
    def storage_power_primary(self):
        return self.subsystem_primary.controller.charge_port.flow

    @property
    def energy_interface_primary(self):
        return self.subsystem_primary.controller.energy_from_interface_net

    @property
    def energy_charged_primary(self):
        return self.subsystem_primary.controller.energy_from_interface_net

    @property
    def energy_charged_secondary(self):
        if hasattr(self, 'subsystem_secondary'):
            return self.subsystem_secondary.controller.energy_from_interface_net
        else:
            return None

    @property
    def energy_consumed_primary(self):
        return self.subsystem_primary.controller.energy_to_loads_net

    @property
    def energy_consumed_secondary(self):
        if hasattr(self, 'subsystem_secondary'):
            return self.subsystem_secondary.controller.energy_to_loads_net
        else:
            return None


class SimpleVehicleNoLogging(SimpleVehicle):
    # Required for charging station optimisation (Benno)
    def __init__(self, env, vehicle_type, charging_network,
                 traction, aux, storage, list_of_charging_interfaces, ID=None,
                 charging_schedule=None, location=None):
        super().__init__(env, vehicle_type, charging_network,
                         traction, aux, storage, list_of_charging_interfaces,
                         ID=ID, charging_schedule=charging_schedule,
                         location=location)
        self.aux = None
        self._create_primary_subsystem(env, storage, traction, aux,
                                       list_of_charging_interfaces)

        # Invoke DataLogger
        self.log_attributes = {
            'soc_valid': {'attribute': 'soc_valid',
                          'name': 'State of charge valid',
                          'unit': 'boolean',
                          'discrete': True}
        }
        self.log_params = {'vehicle_type': self.vehicle_type,
                           'medium': storage.medium.name}
        self.logger = DataLogger(self.env, self)


class VehicleWithHVAC(VehicleAbstract):
    """Vehicle with a primary energy subsystem, a secondary subsystem for
    a heating medium (e.g., diesel heating in an electric bus), and
    heating/cooling load calculation."""
    def __init__(self, env, vehicle_type, charging_network,
                 traction, aux, hvac, storage_primary,
                 list_of_charging_interfaces_primary,
                 ambient,
                 kerb_weight,
                 num_passengers=0,
                 storage_secondary=None,
                 list_of_charging_interfaces_secondary=None,
                 ID=None, charging_schedule=None, location=None,
                 cabin_temperature=20):
        super().__init__(env, vehicle_type, charging_network,
                         kerb_weight=kerb_weight,
                         num_passengers=num_passengers, ID=ID,
                         charging_schedule=charging_schedule, location=location)
        if not isinstance(ambient, Ambient):
            raise TypeError('When using VehicleWithHVAC, ambient must be of '
                            'type eflips.misc.Ambient.')

        if list_of_charging_interfaces_secondary is None:
            list_of_charging_interfaces_secondary = []
        self.aux = None
        self.hvac = None
        self.ambient = ambient
        self.cabin_temperature = cabin_temperature  # °C

        self._create_primary_subsystem(env, storage_primary, traction, hvac,
                                       aux, list_of_charging_interfaces_primary)

        if storage_secondary is not None:
            self._create_secondary_subsystem(
                env, storage_secondary, hvac,
                list_of_charging_interfaces_secondary)

        # Invoke DataLogger
        self.log_attributes = {
            'ignition_on': {'attribute': 'ignition_on',
                            'name': 'Ignition',
                            'unit': 'boolean',
                            'discrete': True},

            'ac_request': {'attribute': 'ac_request',
                           'name': 'Air-Conditioning Request',
                           'unit': 'boolean',
                           'discrete': True},

            'driving': {'attribute': 'driving',
                        'name': 'Driving',
                        'unit': 'boolean',
                        'discrete': True},

            'odo': {'attribute': 'odo',
                    'name': 'Odometer',
                    'unit': Units.distance.name,
                    'discrete': False},

            'operation_time': {'attribute': 'operation_time',
                               'name': 'Operation time',
                               'unit': Units.wall_time.name,
                               'discrete': False},

            'driver_time': {'attribute': 'driver.total_time',
                            'name': 'Driver total time',
                            'unit': Units.wall_time.name,
                            'discrete': False},

            'traction_power': {'attribute': 'traction_power.energy',
                               'name': 'Traction power',
                               'unit': Units.power.name,
                               'discrete': False},

            'hvac_power_primary': {'attribute': 'hvac_power_primary.energy',
                                   'name': 'HVAC power (primary)',
                                   'unit': Units.power.name,
                                   'discrete': False},

            'hvac_power_secondary': {'attribute': 'hvac_power_secondary.energy',
                                     'name': 'HVAC power (secondary)',
                                     'unit': Units.power.name,
                                     'discrete': False},

            'other_aux_power_primary': {'attribute': 'other_aux_power_primary.energy',
                                        'name': 'Other aux power (primary)',
                                        'unit': Units.power.name,
                                        'discrete': False},

            'aux_power_primary': {'attribute': 'aux_power_primary.energy',
                                  'name': 'Total aux power (primary)',
                                  'unit': Units.power.name,
                                  'discrete': False},

            'aux_power_secondary': {'attribute': 'aux_power_secondary.energy',
                                    'name': 'Total aux power (secondary)',
                                    'unit': Units.power.name,
                                    'discrete': False},

            'total_power_primary': {'attribute': 'total_power_primary.energy',
                                    'name': 'Total power (primary)',
                                    'unit': Units.power.name,
                                    'discrete': False},

            'total_power_secondary': {'attribute': 'total_power_secondary.energy',
                                      'name': 'Total power (secondary)',
                                      'unit': Units.power.name,
                                      'discrete': False},

            'charging_power_primary': {'attribute': 'charging_interface_power_primary.energy',
                                       'name': 'Charging power (primary)',
                                       'unit': Units.power.name,
                                       'discrete': False},

            'charging_power_secondary': {'attribute': 'charging_interface_power_secondary.energy',
                                         'name': 'Charging power (secondary)',
                                         'unit': Units.power.name,
                                         'discrete': False},

            'soc_primary': {'attribute': 'energy_storage_primary.soc',
                            'name': 'State of charge (primary)',
                            'unit': '1',
                            'discrete': False},

            'soc_secondary': {'attribute': 'energy_storage_secondary.soc',
                              'name': 'State of charge (secondary)',
                              'unit': '1',
                              'discrete': False},

            'soc_valid': {'attribute': 'soc_valid',
                          'name': 'State of charge valid',
                          'unit': 'boolean',
                          'discrete': True},

            'soc_critical': {'attribute': 'soc_critical',
                             'name': 'State of charge critical',
                             'unit': 'boolean',
                             'discrete': True},

            'capacity_primary': {'attribute': 'energy_storage_primary.energy.energy',
                                 'name': 'Capacity (primary)',
                                 'unit': Units.energy.name,
                                 'discrete': False},

            'capacity_secondary': {'attribute': 'energy_storage_secondary.energy.energy',
                                   'name': 'Capacity (secondary)',
                                   'unit': Units.energy.name,
                                   'discrete': False},

            'energy_consumed_primary': {'attribute': 'energy_consumed_primary.energy',
                                        'name': 'Energy consumed (primary)',
                                        'unit': Units.energy.name,
                                        'discrete': False},

            'specific_consumption_primary': {'attribute': 'specific_consumption_primary.energy',
                                             'name': 'Specific consumption (primary)',
                                             'unit': Units.energy.name + '/km',
                                             'discrete': False},

            'energy_consumed_secondary': {'attribute': 'energy_consumed_secondary.energy',
                                          'name': 'Energy consumed (secondary)',
                                          'unit': Units.energy.name,
                                          'discrete': False},

            'energy_charged_primary': {'attribute': 'energy_charged_primary.energy',
                                       'name': 'Energy charged (primary)',
                                       'unit': Units.energy.name,
                                       'discrete': False},

            'energy_charged_secondary': {'attribute': 'energy_charged_secondary.energy',
                                         'name': 'Energy charged (secondary)',
                                         'unit': Units.energy.name,
                                         'discrete': False},

            'location': {'attribute': 'location',
                         'name': 'Location',
                         'unit': None,
                         'discrete': False},

            'delay': {'attribute': 'delay',
                      'name': 'Delay',
                      'unit': Units.wall_time.name,
                      'discrete': False},

            'cabin_temperature': {'attribute': 'cabin_temperature',
                                  'name': 'Cabin Temperature',
                                  'unit': '°C',
                                  'discrete': False},

            'ambient_temperature': {'attribute': 'ambient.temperature',
                                    'name': 'Ambient Temperature',
                                    'unit': '°C',
                                    'discrete': False},

            'heating_load_convection': {'attribute':
                                            'heating_load_convection.energy',
                                        'name':
                                            'Convective heating/cooling load',
                                        'unit': Units.power.name,
                                        'discrete': False},

            'heating_load_insolation': {'attribute':
                                            'heating_load_insolation.energy',
                                        'name': 'Solar heating/cooling load',
                                        'unit': Units.power.name,
                                        'discrete': False},

            'heating_load': {'attribute': 'heating_load.energy',
                                          'name': 'Total heating/cooling load',
                                          'unit': Units.power.name,
                                          'discrete': False}
        }
        self.log_params = {'vehicle_type': self.vehicle_type,
                           'medium_primary':
                               self.subsystem_primary.medium.name,
                           'medium_secondary':
                               None if storage_secondary is None
                               else self.subsystem_secondary.medium.name}

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(self.env, self)

    def _create_primary_subsystem(self, env, storage, traction, hvac, aux,
                                  list_of_charging_interfaces):
        # Assign components as attributes:
        self.energy_storage_primary = storage
        self.traction = traction
        self.traction.vehicle = self
        self.hvac = hvac
        self.hvac.vehicle = self
        self.aux = aux

        # Create primary energy subsystem and add to vehicle:
        self.subsystem_primary = EnergySubSystem(
            self,
            env,
            storage,
            {'traction': traction.port,
             'aux': aux.port,
             'hvac': hvac.port_primary},
            list_of_charging_interfaces
        )
        self.add_subsystem(self.subsystem_primary)

        # Add event listener to log changes in subsystem
        self.subsystem_primary.controller.state_change_event.add(self._update)

    def _create_secondary_subsystem(self, env, storage, hvac,
                                    list_of_charging_interfaces):
        # Assign components as attributes:
        self.energy_storage_secondary = storage

        # Create primary energy subsystem and add to vehicle:
        self.subsystem_secondary = EnergySubSystem(
            self,
            env,
            storage,
            {'hvac': hvac.port_secondary},
            list_of_charging_interfaces
        )
        self.add_subsystem(self.subsystem_secondary)

        # Add event listener to log changes in subsystem
        self.subsystem_secondary.controller.state_change_event.add(self._update)

    def _set_ignition(self, value):
        self.traction.on = value
        self.aux.on = value
        self._ignition_on = value

    def _set_ac_request(self, value):
        self._ac_request = value
        self.hvac.on = value

    def _set_num_passengers(self, value):
        self._num_passengers = value
        self.state_change_event()

    @property
    def heating_load_convection(self):
        """Return convective heating load (<0) or cooling load (>0) depending on
        vehicle type and cabin/ambient temperature."""
        return EnergyFlow.from_energy_ref(
            Fuels.heat,
            self.vehicle_type.params['UA_value'] * (self.ambient.temperature
                                                    - self.cabin_temperature)
        )

    @property
    def heat_production_passengers_sensible(self):
        if global_constants['DISABLE_PASSENGER_HEAT_PRODUCTION'] is True:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)
        else:
            # Correlation from VDI 2078, referenced in Jefferies (2015)
            # (diploma thesis). Activity level II
            if self.cabin_temperature <= 16:
                temperature = 16
            elif self.cabin_temperature >= 28:
                temperature = 28
            else:
                temperature = self.cabin_temperature
            heat_production_per_passenger_W = 166 - 3.8*temperature
            return EnergyFlow.from_energy_ref(Fuels.heat, self.num_passengers *
                                              heat_production_per_passenger_W/1000)

    @property
    def heat_production_passengers_latent(self):
        if global_constants['DISABLE_PASSENGER_HEAT_PRODUCTION'] is True:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)
        else:
            # Correlation from VDI 2078, referenced in Jefferies (2015)
            # (diploma thesis). Activity level II
            if self.cabin_temperature <= 16:
                temperature = 16
            elif self.cabin_temperature >= 28:
                temperature = 28
            else:
                temperature = self.cabin_temperature
            heat_production_per_passenger_W = -41 + 3.8*temperature
            return EnergyFlow.from_energy_ref(Fuels.heat, self.num_passengers *
                                              heat_production_per_passenger_W/1000)

    @property
    def heating_load_insolation(self):
        """Return absorbed solar power."""
        return EnergyFlow.from_energy_ref(
            Fuels.heat,
            self.vehicle_type.params['insolation_area']
            * self.ambient.insolation/1000
        )

    @property
    def heating_load(self):
        """Return heating load (<0) or cooling load (>0) depending on
        vehicle type and cabin/ambient temperature."""
        return self.heating_load_convection + self.heating_load_insolation +\
            self.heat_production_passengers_latent + \
            self.heat_production_passengers_sensible

    @property
    def traction_power(self):
        return self.traction.port.flow

    @property
    def hvac_power_primary(self):
        return self.hvac.port_primary.flow

    @property
    def hvac_power_secondary(self):
        if hasattr(self.hvac, 'port_secondary'):
            return self.hvac.port_secondary.flow
        else:
            return None

    @property
    def other_aux_power_primary(self):
        return self.aux.port.flow

    @property
    def aux_power_primary(self):
        return self.hvac_power_primary + self.other_aux_power_primary

    @property
    def aux_power_secondary(self):
        return self.hvac_power_secondary

    @property
    def total_power_primary(self):
        return self.traction_power + self.aux_power_primary

    @property
    def total_power_secondary(self):
        return self.aux_power_secondary

    @property
    def charging_interface_power(self):
        return self.charging_interface_power_primary

    @property
    def charging_interface_power_primary(self):
        return self.subsystem_primary.controller.interface_port.flow

    @property
    def charging_interface_power_secondary(self):
        if hasattr(self, 'subsystem_secondary'):
            return self.subsystem_secondary.controller.interface_port.flow
        else:
            return None

    @property
    def energy_charged_primary(self):
        return self.subsystem_primary.controller.energy_from_interface_net

    @property
    def energy_charged_secondary(self):
        return self.subsystem_secondary.controller.energy_from_interface_net

    @property
    def energy_consumed_primary(self):
        return self.subsystem_primary.controller.energy_to_loads_net

    @property
    def energy_consumed_secondary(self):
        if hasattr(self, 'subsystem_secondary'):
            return self.subsystem_secondary.controller.energy_to_loads_net
        else:
            return None


class Device(metaclass=ABCMeta):
    """ABC for a general device that can be switched on and off. Devices are
    free to define any number of ports as public attributes."""
    def __init__(self, env):
        self.env = env
        self._on = False
        self.action = None

    @property
    def on(self):
        return self._on

    @on.setter
    def on(self, value):
        self._set_on(value)

    @abstractmethod
    def _set_on(self, value):
        pass


class HVACWithBackup(Device):
    # ToDo:
    # [x] multiple media
    # [ ] COP, capacity = f(ambient temperature, cabin temperature)
    def __init__(self, env, medium,
                 capacity_ac_unit, cop_ac, num_ac_units,
                 capacity_hp_unit, cop_hp, num_hp_units,
                 capacity_backup_unit, cop_backup, num_backup_units,
                 vehicle=None):
        super().__init__(env)
        # logger = logging.getLogger('vehicle_logger')
        self.vehicle = vehicle  # vehicle will most likely be added after init
        # if not hasattr(vehicle, 'ambient'):
        #     logger.error('Vehicle requires an attribute ambient')
        #     raise AttributeError('Vehicle requires an attribute ambient')
        self.medium = medium
        self.capacity_ac_unit = capacity_ac_unit
        self.cop_ac = cop_ac
        self.num_ac_units = num_ac_units
        self._capacity_hp_unit = capacity_hp_unit
        self.cop_hp = cop_hp
        self.num_hp_units = num_hp_units
        self.capacity_backup_unit = capacity_backup_unit
        self.cop_backup = cop_backup
        self.num_backup_units = num_backup_units

        self.port_primary = Port(medium)
        self.port_primary.flow = self.power_total

        self.state_change_event = eflips.events.EventHandler(self)

        # self.log_attributes = {
        #     'mode': {'attribute': 'mode',
        #              'name': 'Operation Mode',
        #              'unit': None,
        #              'discrete': True},
        #     'on': {'attribute': 'on',
        #            'name': 'On/Off',
        #            'unit': 'boolean',
        #            'discrete': True},
        #     'cooling_power_ac': {'attribute': 'cooling_power_ac',
        #                          'name': 'Cooling power',
        #                          'unit': Units.power,
        #                          'discrete': False},
        #     'heating_power_hp': {'attribute': 'heating_power_hp',
        #                          'name': 'Heat pump heating power',
        #                          'unit': Units.power,
        #                          'discrete': False},
        #     'heating_power_backup': {'attribute': 'heating_power_backup',
        #                              'name': 'Backup heating power',
        #                              'unit': Units.power,
        #                              'discrete': False},
        #     'power_total': {'attribute': 'port.flow',
        #                                  'name': 'Total electric power',
        #                                  'unit': Units.power,
        #                                  'discrete': False},
        # }
        #
        # self.logger = DataLogger(self.env, self)
        # self.vehicle.state_change_event.add(self._update)
        # This will cause infinite recursion. Trigger HVAC state change event
        # directly from cabin and ambient temperature setters!

    def _update(self):
        self.port_primary.flow = self.power_total
        self.state_change_event()

    def _set_on(self, value):
        self._on = value
        self._update()

    @property
    def capacity_hp_unit(self):
        # Enables us to implement temperature-dependent heat pump capacity
        # in subclasses
        return self._capacity_hp_unit

    @property
    def mode(self):
        try:
            if self.vehicle.heating_load.energy_ref < 0:
                return 'heating'
            elif self.vehicle.heating_load.energy_ref > 0:
                return 'cooling'
            elif self.vehicle.heating_load.energy_ref == 0:
                return 'venting'
        except AttributeError:
            return None

    @property
    def capacity_ac_total(self):
        return self.num_ac_units * self.capacity_ac_unit

    @property
    def capacity_hp_total(self):
        return self.num_hp_units * self.capacity_hp_unit

    @property
    def capacity_backup_total(self):
        return self.num_backup_units * self.capacity_backup_unit

    @property
    def capacity_heating_total(self):
        return self.capacity_hp_total + self.capacity_backup_total

    @property
    def cooling_power_ac(self):
        logger = logging.getLogger('vehicle_logger')
        if self.on and self.mode == 'cooling':
            if self.vehicle.heating_load <= self.capacity_ac_total:
                return self.vehicle.heating_load
            else:
                logger.warning('t = %d (%s), vehicle %d: Cooling load (%.1f) '
                               'exceeds available cooling power (%.1f). '
                               'Selected cabin temperature cannot be achieved.' %
                               (self.env.now, hms_str(self.env.now),
                                self.vehicle.ID,
                                self.vehicle.heating_load.energy,
                                self.capacity_ac_total.energy))
                return self.capacity_ac_total
        else:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)

    @property
    def heating_power_hp(self):
        if self.on and self.mode == 'heating':
            if abs(self.vehicle.heating_load) <= self.capacity_hp_total:
                return abs(self.vehicle.heating_load)
            else:
                return self.capacity_hp_total
        else:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)

    @property
    def heating_power_backup(self):
        logger = logging.getLogger('vehicle_logger')
        if self.on and self.mode == 'heating':
            if abs(self.vehicle.heating_load) < self.capacity_hp_total:
                return EnergyFlow.from_energy_ref(Fuels.heat, 0)
            elif (abs(self.vehicle.heating_load) >= self.capacity_hp_total) \
                and (abs(self.vehicle.heating_load) <=
                     self.capacity_heating_total):
                return abs(self.vehicle.heating_load) \
                    - self.capacity_hp_total
            else:
                logger.warning('t = %d (%s), vehicle %d: Heating load (%.1f) '
                               'exceeds available heating power (%.1f). '
                               'Selected cabin temperature cannot be achieved.' %
                               (self.env.now, hms_str(self.env.now),
                                self.vehicle.ID,
                                abs(self.vehicle.heating_load.energy),
                                self.capacity_heating_total.energy))
                return self.capacity_backup_total
        else:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)

    @property
    def power_ac(self):
        return EnergyFlow.from_energy_ref(Fuels.electricity,
                                          self.cooling_power_ac.energy_ref/
                                          self.cop_ac)

    @property
    def power_hp(self):
        return EnergyFlow.from_energy_ref(Fuels.electricity,
                                          self.heating_power_hp.energy_ref/
                                          self.cop_hp)

    @property
    def power_backup(self):
        return EnergyFlow.from_energy_ref(Fuels.electricity,
                                          self.heating_power_backup.energy_ref/
                                          self.cop_backup)

    @property
    def power_total(self):
        return self.power_ac + self.power_hp + self.power_backup


class HVACWithBackupDualMedia(Device):
    # ToDo:
    # [x] multiple media
    # [x] implement multiple media within Vehicle
    # (logging attributes!) and Fleet
    # [ ] COP, capacity = f(ambient temperature, cabin temperature)
    def __init__(self, env, medium_primary, medium_secondary,
                 capacity_ac_unit, cop_ac, num_ac_units,
                 capacity_hp_unit, cop_hp, num_hp_units,
                 capacity_backup_unit, cop_backup, num_backup_units,
                 medium_ac='primary', medium_hp='primary',
                 medium_backup='primary', vehicle=None):
        super().__init__(env)
        # logger = logging.getLogger('vehicle_logger')
        self.vehicle = vehicle  # vehicle will most likely be added after init
        # if not hasattr(vehicle, 'ambient'):
        #     logger.error('Vehicle requires an attribute ambient')
        #     raise AttributeError('Vehicle requires an attribute ambient')
        self.medium_primary = medium_primary

        if medium_secondary is None:
            self.medium_secondary = medium_primary
        else:
            self.medium_secondary = medium_secondary

        self.capacity_ac_unit = capacity_ac_unit
        self.cop_ac = cop_ac
        self.num_ac_units = num_ac_units
        self._capacity_hp_unit = capacity_hp_unit
        self.cop_hp = cop_hp
        self.num_hp_units = num_hp_units
        self.capacity_backup_unit = capacity_backup_unit
        self.cop_backup = cop_backup
        self.num_backup_units = num_backup_units

        self.loads_primary = MultiPort(medium_primary)
        self.loads_secondary = MultiPort(medium_secondary)

        self.port_primary = self.loads_primary.out_port
        self.port_secondary = self.loads_secondary.out_port

        self._media_map = {'primary': self.medium_primary,
                           'secondary': self.medium_secondary}

        # Generate port attribute for AC, HP and backup, and add to respective
        # MultiPort:
        self._media_string_map = {'ac': medium_ac,
                                  'hp': medium_hp,
                                  'backup': medium_backup}
        for att, mediastr in self._media_string_map.items():
            portname = '_port_' + att
            port = Port(self._media_map[mediastr])
            setattr(self, portname, port)
            multiport = getattr(self, 'loads_' + mediastr)
            multiport.add_port(port)

        self.state_change_event = eflips.events.EventHandler(self)

    @property
    def capacity_hp_unit(self):
        # Enables us to implement temperature-dependent heat pump capacity
        # in subclasses
        return self._capacity_hp_unit

    def _update(self):
        self._port_ac.flow = self.power_ac
        self._port_hp.flow = self.power_hp
        self._port_backup.flow = self.power_backup
        self.state_change_event()

    def _set_on(self, value):
        self._on = value
        self._update()

    @property
    def mode(self):
        try:
            if self.vehicle.heating_load.energy_ref < 0:
                return 'heating'
            elif self.vehicle.heating_load.energy_ref > 0:
                return 'cooling'
            elif self.vehicle.heating_load.energy_ref == 0:
                return 'venting'
        except AttributeError:
            return None

    @property
    def capacity_ac_total(self):
        return self.num_ac_units * self.capacity_ac_unit

    @property
    def capacity_hp_total(self):
        return self.num_hp_units * self.capacity_hp_unit

    @property
    def capacity_backup_total(self):
        return self.num_backup_units * self.capacity_backup_unit

    @property
    def capacity_heating_total(self):
        return self.capacity_hp_total + self.capacity_backup_total

    @property
    def cooling_power_ac(self):
        logger = logging.getLogger('vehicle_logger')
        if self.on and self.mode == 'cooling':
            if self.vehicle.heating_load <= self.capacity_ac_total:
                return self.vehicle.heating_load
            else:
                logger.warning('t = %d (%s), vehicle %d: Cooling load (%.1f) '
                               'exceeds available cooling power (%.1f). '
                               'Selected cabin temperature cannot be achieved.' %
                               (self.env.now, hms_str(self.env.now),
                                self.vehicle.ID,
                                self.vehicle.heating_load.energy,
                                self.capacity_ac_total.energy))
                return self.capacity_ac_total
        else:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)

    @property
    def heating_power_hp(self):
        if self.on and self.mode == 'heating':
            if abs(self.vehicle.heating_load) <= self.capacity_hp_total:
                return abs(self.vehicle.heating_load)
            else:
                return self.capacity_hp_total
        else:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)

    @property
    def heating_power_backup(self):
        logger = logging.getLogger('vehicle_logger')
        if self.on and self.mode == 'heating':
            if abs(self.vehicle.heating_load) < self.capacity_hp_total:
                return EnergyFlow.from_energy_ref(Fuels.heat, 0)
            elif (abs(self.vehicle.heating_load) >= self.capacity_hp_total) \
                and (abs(self.vehicle.heating_load) <=
                     self.capacity_heating_total):
                return abs(self.vehicle.heating_load) \
                    - self.capacity_hp_total
            else:
                logger.warning('t = %d (%s), vehicle %d: Heating load (%.1f) '
                               'exceeds available heating power (%.1f). '
                               'Selected cabin temperature cannot be achieved.' %
                               (self.env.now, hms_str(self.env.now),
                                self.vehicle.ID,
                                abs(self.vehicle.heating_load.energy),
                                self.capacity_heating_total.energy))
                return self.capacity_backup_total
        else:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)

    @property
    def power_ac(self):
        return EnergyFlow.from_energy_ref(self._port_ac.medium,
                                          self.cooling_power_ac.energy_ref/
                                          self.cop_ac)

    @property
    def power_hp(self):
        return EnergyFlow.from_energy_ref(self._port_hp.medium,
                                          self.heating_power_hp.energy_ref/
                                          self.cop_hp)

    @property
    def power_backup(self):
        return EnergyFlow.from_energy_ref(self._port_backup.medium,
                                          self.heating_power_backup.energy_ref/
                                          self.cop_backup)

    @property
    def power_total_primary(self):
        return self.port_primary.flow

    @property
    def power_total_secondary(self):
        return self.port_secondary.flow


class ValeoR134aHeatPump_ElectricBackup(HVACWithBackup):
    def __init__(self, env, num_ac_units, num_hp_units, num_backup_units,
                 hp_cutoff=-5, vehicle=None):
        medium = Fuels.electricity
        capacity_ac_unit = EnergyFlow.from_energy_ref(Fuels.heat, 24)
        capacity_hp_unit = None  # overriden by property method
        capacity_backup_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)

        # Assumption
        cop_ac = 2

        # Heat pump COP from presentation by Valeo:
        # Färber, F.: Heizen im Elektrobus. VDV-Akademie-Konferenz
        # Elektrobusse, Berlin, 2019
        cop_hp = 2

        # Assumption
        cop_backup = 0.91

        super().__init__(env, medium,
                 capacity_ac_unit, cop_ac, num_ac_units,
                 capacity_hp_unit, cop_hp, num_hp_units,
                 capacity_backup_unit, cop_backup, num_backup_units,
                 vehicle=vehicle)

        self.hp_cutoff_temperature = max(-5, hp_cutoff)

    @property
    def capacity_hp_unit(self):
        try:
            # cabin_temperature = self.vehicle.cabin_temperature
            ambient_temperature = self.vehicle.ambient.temperature
        except AttributeError:
            # This will occur if self.vehicle is not set yet
            # cabin_temperature = 20
            ambient_temperature = 20

        # Heating capacity function from presentation by Valeo:
        # Färber, F.: Heizen im Elektrobus. VDV-Akademie-Konferenz
        # Elektrobusse, Berlin, 2019
        # See also: \\mpm-space.mpm.tu-berlin.de\ETS_Team\eFLIPS\Sonstiges\
        # Auswertung Heizleistung Valeo-WP
        if ambient_temperature < self.hp_cutoff_temperature:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)
        elif ambient_temperature > 20:
            return EnergyFlow.from_energy_ref(Fuels.heat, 24)
        else:
            power = (24-10.9)/(20+5)*(ambient_temperature+5) + 10.9
            return EnergyFlow.from_energy_ref(Fuels.heat, power)


class ValeoR134aHeatPump_DieselBackup(HVACWithBackupDualMedia):
    def __init__(self, env, num_ac_units, num_hp_units, num_backup_units,
                 hp_cutoff=-5, vehicle=None):
        medium_primary = Fuels.electricity
        medium_secondary = Fuels.diesel
        capacity_ac_unit = EnergyFlow.from_energy_ref(Fuels.heat, 24)
        capacity_hp_unit = None  # overriden by property method
        capacity_backup_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)

        # Assumption
        cop_ac = 2

        # Heat pump COP from presentation by Valeo:
        # Färber, F.: Heizen im Elektrobus. VDV-Akademie-Konferenz
        # Elektrobusse, Berlin, 2019
        cop_hp = 2

        # Diesel heater efficiency determined for Valeo Thermo S 300;
        # see \\mpm-space.mpm.tu-berlin.de\ETS_Team\Literatur\Datenblätter\
        # Valeo (2017) Thermo S Datenblatt.pdf
        cop_backup = 0.84

        super().__init__(env, medium_primary, medium_secondary,
                 capacity_ac_unit, cop_ac, num_ac_units,
                 capacity_hp_unit, cop_hp, num_hp_units,
                 capacity_backup_unit, cop_backup, num_backup_units,
                 medium_ac='primary', medium_hp='primary',
                 medium_backup='secondary', vehicle=vehicle)

        self.hp_cutoff_temperature = max(-5, hp_cutoff)

    @property
    def capacity_hp_unit(self):
        try:
            # cabin_temperature = self.vehicle.cabin_temperature
            ambient_temperature = self.vehicle.ambient.temperature
        except AttributeError:
            # This will occur if self.vehicle is not set yet
            # cabin_temperature = 20
            ambient_temperature = 20

        # Heating capacity function from presentation by Valeo:
        # Färber, F.: Heizen im Elektrobus. VDV-Akademie-Konferenz
        # Elektrobusse, Berlin, 2019
        if ambient_temperature < self.hp_cutoff_temperature:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)
        elif ambient_temperature > 20:
            return EnergyFlow.from_energy_ref(Fuels.heat, 24)
        else:
            power = (24-10.9)/(20+5)*(ambient_temperature+5) + 10.9
            return EnergyFlow.from_energy_ref(Fuels.heat, power)


class KonvektaR744HeatPump_ElectricBackup(HVACWithBackup):
    def __init__(self, env, num_ac_units, num_hp_units, num_backup_units,
                 hp_cutoff=-15, vehicle=None):
        medium = Fuels.electricity
        capacity_ac_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)
        capacity_hp_unit = None  # overriden by property method
        capacity_backup_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)

        # Assumptions
        cop_ac = 2
        cop_hp = 2
        cop_backup = 0.9

        super().__init__(env, medium,
                         capacity_ac_unit, cop_ac, num_ac_units,
                         capacity_hp_unit, cop_hp, num_hp_units,
                         capacity_backup_unit, cop_backup, num_backup_units,
                         vehicle=vehicle)
        self.hp_cutoff_temperature = max(-15, hp_cutoff)

    @property
    def capacity_hp_unit(self):
        try:
            # cabin_temperature = self.vehicle.cabin_temperature
            ambient_temperature = self.vehicle.ambient.temperature
        except AttributeError:
            # This will occur if self.vehicle is not set yet
            # cabin_temperature = 20
            ambient_temperature = 20

        # Heating capacity function from Konvekta catalogue data (see data for
        # EVS31 paper):
        if ambient_temperature < self.hp_cutoff_temperature:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)
        elif ambient_temperature > 0:
            return EnergyFlow.from_energy_ref(Fuels.heat, 18.2)
        else:
            power = 0.27*ambient_temperature + 18.2
            return EnergyFlow.from_energy_ref(Fuels.heat, power)


class KonvektaR744HeatPump_DieselBackup(HVACWithBackupDualMedia):
    def __init__(self, env, num_ac_units, num_hp_units, num_backup_units,
                 hp_cutoff=-15, vehicle=None):
        medium_primary = Fuels.electricity
        medium_secondary = Fuels.diesel
        capacity_ac_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)
        capacity_hp_unit = None  # overriden by property method
        capacity_backup_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)

        # Assumptions
        cop_ac = 2
        cop_hp = 2

        # Diesel heater efficiency determined for Valeo Thermo S 300;
        # see \\mpm-space.mpm.tu-berlin.de\ETS_Team\Literatur\Datenblätter\
        # Valeo (2017) Thermo S Datenblatt.pdf
        cop_backup = 0.84

        super().__init__(env, medium_primary, medium_secondary,
                 capacity_ac_unit, cop_ac, num_ac_units,
                 capacity_hp_unit, cop_hp, num_hp_units,
                 capacity_backup_unit, cop_backup, num_backup_units,
                 medium_ac='primary', medium_hp='primary',
                 medium_backup='secondary', vehicle=vehicle)

        self.hp_cutoff_temperature = max(-15, hp_cutoff)

    @property
    def capacity_hp_unit(self):
        try:
            # cabin_temperature = self.vehicle.cabin_temperature
            ambient_temperature = self.vehicle.ambient.temperature
        except AttributeError:
            # This will occur if self.vehicle is not set yet
            # cabin_temperature = 20
            ambient_temperature = 20

        # Heating capacity function from Konvekta catalogue data (see data for
        # EVS31 paper):
        if ambient_temperature < self.hp_cutoff_temperature:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)
        elif ambient_temperature > 0:
            return EnergyFlow.from_energy_ref(Fuels.heat, 18.2)
        else:
            power = 0.27*ambient_temperature + 18.2
            return EnergyFlow.from_energy_ref(Fuels.heat, power)


class KonvektaR134aAC_ElectricHeating_DieselBackup(HVACWithBackupDualMedia):
    """Conventional AC with electric resistance heater and diesel backup
    heater.

    We use the combined AC/heat pump model with the heat pump COP adjusted
    to a resistance heater."""
    def __init__(self, env, num_ac_units, num_hp_units, num_backup_units,
                 electric_heating_cutoff=5, vehicle=None):
        medium_primary = Fuels.electricity
        medium_secondary = Fuels.diesel
        capacity_ac_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)
        capacity_hp_unit = None  # overriden by property method
        capacity_backup_unit = EnergyFlow.from_energy_ref(Fuels.heat, 20)

        # Assumptions
        cop_ac = 2
        cop_hp = 0.9

        # Diesel heater efficiency determined for Valeo Thermo S 300;
        # see \\mpm-space.mpm.tu-berlin.de\ETS_Team\Literatur\Datenblätter\
        # Valeo (2017) Thermo S Datenblatt.pdf
        cop_backup = 0.84

        super().__init__(env, medium_primary, medium_secondary,
                         capacity_ac_unit, cop_ac, num_ac_units,
                         capacity_hp_unit, cop_hp, num_hp_units,
                         capacity_backup_unit, cop_backup, num_backup_units,
                         medium_ac='primary', medium_hp='primary',
                         medium_backup='secondary', vehicle=vehicle)

        self.hp_cutoff_temperature = max(0, electric_heating_cutoff)

    @property
    def capacity_hp_unit(self):
        try:
            # cabin_temperature = self.vehicle.cabin_temperature
            ambient_temperature = self.vehicle.ambient.temperature
        except AttributeError:
            # This will occur if self.vehicle is not set yet
            # cabin_temperature = 20
            ambient_temperature = 20

        # Heating capacity function:
        if ambient_temperature < self.hp_cutoff_temperature:
            return EnergyFlow.from_energy_ref(Fuels.heat, 0)
        else:
            power = 20
            return EnergyFlow.from_energy_ref(Fuels.heat, power)


class ConstantPowerDevice(Device):
    def __init__(self, env, medium, energy_flow):
        super().__init__(env)
        self.port = Port(medium)
        self.port.flow = EnergyFlow.from_energy_ref(medium, 0)
        self._energy_flow = energy_flow

    def _set_on(self, value):
        if value:
            self._on = True
            self.port.flow = self._energy_flow
            logger = logging.getLogger('vehicle_logger')
            logger.debug('t = %d (%s): ConstantPowerDevice power %d kW' %
                         (self.env.now,
                          hms_str(self.env.now),
                          self.port.flow.energy_ref))
        elif not value:
            self._on = False
            self.port.flow = EnergyFlow.from_energy_ref(self.port.medium, 0)
            logger = logging.getLogger('vehicle_logger')
            logger.debug('t = %d (%s): ConstantPowerDevice power %d kW' %
                      (self.env.now, hms_str(self.env.now),
                       self.port.flow.energy_ref))

#
# class VariablePowerDevice(Device):
#     def __init__(self, env, medium, energy_flow):
#         super().__init__(env)
#         self.port = Port(medium)
#         self.port.flow = EnergyFlow.from_energy_ref(medium, 0)
#         self._energy_flow = energy_flow
#
#     def _set_on(self, value):
#         if value:
#             self._on = True
#             self.port.flow = self._energy_flow
#             logger = logging.getLogger('vehicle_logger')
#             logger.debug('ConstantPowerDevice power %d kW' % self.port.flow.energy_ref)
#         elif not value:
#             self._on = False
#             self.port.flow = EnergyFlow.from_energy_ref(self.port.medium, 0)
#             logger = logging.getLogger('vehicle_logger')
#             logger.debug('ConstantPowerDevice power %d kW' %
#                       (self.port.flow.energy_ref))
#
#     def set_flow(self, value):
#         self


class RandomPowerDevice(Device):
    """For testing purposes"""
    def __init__(self, env, medium):
        super().__init__(env)
        self.port = Port(medium)

    def _set_on(self, value):
        if value == True:
            if self._on == False:
                self._on = True
                self.action = self.env.process(self._run())
        elif value == False:
            if self.action is not None:
                self._on = False
                self.action.interrupt()
                logger = logging.getLogger('vehicle_logger')
                logger.debug('RandomDevice interrupted')

    def _run(self):
        random.seed()
        try:
            while True:
                # change flow to a random number
                self.port.flow = EnergyFlow.from_energy_ref(
                    self.port.medium, random.randrange(0, 120))
                logger = logging.getLogger('vehicle_logger')
                logger.debug('RandomDevice power %d kW' %
                             self.port.flow.energy_ref)
                yield self.env.timeout(random.randrange(1, 3) * 60)
        except simpy.Interrupt:
            # Do nothing
            pass


class TractionAbstract(Device, metaclass=ABCMeta):
    def __init__(self, env, medium):
        super().__init__(env)
        self.port = Port(medium)
        self.vehicle = None
        self.velocity = 0  # m/s
        self.odo = 0  # km (!)
        self.consumption = Energy.from_energy_ref(medium, 0)  # kWh/km or similar

    @abstractmethod
    def drive(self, element):
        pass

    @property
    def specific_consumption(self):
        if self.odo == 0:
            return Energy.from_energy_ref(self.port.medium, 0)
        else:
            return self.consumption/self.odo

    def _set_on(self, value):
        self._on = value


class LongitudinalDynamicsTraction_ConstantEfficiency(TractionAbstract):
    """Longitudinal dynamics model with constant overall drivetrain
    efficiency.
    """
    def __init__(self, env, medium, f_r, c_w, A, lam, eta_total,
                 rho_air=1.2):
        super().__init__(env, medium)
        self.f_r = f_r
        self.c_w = c_w
        self.A = A
        self.lam = lam  # 'lambda' is a reserved keyword in python
        self.eta_total = eta_total
        self.rho_air = rho_air

        # self.velocity = 0  # already initialised in parent
        self.acceleration = 0
        self.alpha = 0
        self.F_r = 0
        self.F_climb = 0
        self.F_air = 0
        self.F_acc = 0
        self.F_total = 0
        self.P_wheel = 0
    
    def drive(self, driving_profile):
        if not isinstance(driving_profile, DrivingProfile):
            raise TypeError('driving_profile must be of DrivingProfile type')
        for i in range(len(driving_profile)):
            self.velocity = driving_profile.velocity[i]
            self.acceleration = driving_profile.acceleration[i]
            self.alpha = driving_profile.slope[i]

            # Resistances in N:
            # Rolling resistance
            self.F_r = self.f_r * self.vehicle.total_mass * 9.81 * np.cos(self.alpha)

            # Climbing resistance
            self.F_climb = self.vehicle.total_mass * 9.81 * np.sin(self.alpha)

            # Air resistance
            self.F_air = self.rho_air / 2 * self.c_w * self.A * (self.velocity) ** 2

            # Acceleration resistance
            # self.F_acc = self.lam * self.vehicle.total_mass * self.acceleration
            self.F_acc = (self.lam * self.vehicle.kerb_weight + self.vehicle.payload) * self.acceleration

            # Total resistance
            self.F_total = self.F_r + self.F_climb + self.F_air + self.F_acc

            # Power at the wheel (W)
            self.P_wheel = self.F_total * self.velocity
            self.power_wheel = EnergyFlow.from_energy_ref(Fuels.mechanical,
                                                          self.P_wheel/1000)

            # Electric power
            if self.P_wheel >= 0:
                self.power_traction = EnergyFlow.from_energy_ref(
                    Fuels.electricity,
                    self.power_wheel.energy_ref/self.eta_total)
            else:
                self.power_traction = EnergyFlow.from_energy_ref(
                    Fuels.electricity,
                    self.power_wheel.energy_ref*self.eta_total)
            self.port.flow = self.power_traction

            logger = logging.getLogger('vehicle_logger')
            logger.debug('t = %d (%s), step %d: Traction power %.2f kW' %
                         (self.env.now, hms_str(self.env.now), i,
                          self.port.flow.energy_ref))
            dt = driving_profile.time_delta[i]
            yield self.env.timeout(dt)
            self.consumption += self.power_traction.integrate(dt)
            self.odo += driving_profile.distance[i]/1000


class Traction_Leg(TractionAbstract, metaclass=ABCMeta):
    """Abstract base class for traction models that operate based on
    schedule legs"""
    def drive(self, leg_node):
        if not isinstance(leg_node, LegNode):
            raise TypeError('Wrong type supplied for leg_node')
        for segment_node in leg_node.children:
            if 'DELAYS' in global_constants and \
                    global_constants['DELAYS'] == True:
                # avoid negative durations:
                duration = max(segment_node.duration + segment_node.delay,
                               0)
            else:
                duration = segment_node.duration
            distance_km = segment_node.grid_segment.distance
            self.odo += distance_km
            self.action = self.env.process(self._drive(distance_km,
                                                       duration))
            yield self.action

    @abstractmethod
    def _drive(self, distance, duration):
        pass


# class Traction(Device):
#     def __init__(self, env, medium):
#         super().__init__(env)
#         self.port = Port(medium)
#         self.vehicle = None
#
#     def _set_on(self, value):
#         pass
#
#     def drive(self, profile_element):
#         if isinstance(profile_element, LegNode):
#             for segment_node in profile_element.children:
#                 if 'DELAYS' in global_constants and \
#                         global_constants['DELAYS'] == True:
#                     # avoid negative durations:
#                     duration = max(segment_node.duration + segment_node.delay,
#                                    0)
#                 else:
#                     duration = segment_node.duration
#                 distance_km = segment_node.grid_segment.distance
#                 self.action = self.env.process(self._drive(distance_km,
#                                                            duration))
#                 yield self.action
#
#     def _drive(self, distance, duration):
#         pass
#
#     def consumption_per_km(self):
#         pass


class ConstantConsumptionTraction(Traction_Leg):
    def __init__(self, env, medium, specific_consumption):
        super().__init__(env, medium)
        self.specific_consumption_input = specific_consumption

    def _drive(self, distance, duration):
        consumption = self.specific_consumption_input * distance
        duration = max(duration, 0)

        self.port.flow = consumption.derivative(duration)
        logger = logging.getLogger('vehicle_logger')
        logger.debug('t = %d (%s): Traction power %.2f kW' %
                     (self.env.now, hms_str(self.env.now),
                      self.port.flow.energy_ref))
        yield self.env.timeout(duration)
        self.consumption += consumption
        self.port.flow = EnergyFlow.from_energy_ref(self.port.medium, 0)
        logger.debug('t = %d (%s): Traction power %.2f kW' %
                     (self.env.now, hms_str(self.env.now),
                      self.port.flow.energy_ref))


class EfficiencyMapTraction_12m_bus(Traction_Leg):
    def __init__(self, env, medium):
        super().__init__(env, medium)
        self.correlation_map = io.import_pickle(
            '/Users/jonassm/tubCloud/Shared/Datenaustausch_eflips/Jonas/'
            '05_MA_Tilman König, Traktionsmodell E-Bus/Simulationsmodell/Kennlinien/correlation_map_mass.dat')

    def _drive(self, distance_km, duration_s):
        if duration_s > 0:
            v_avg_kmh = distance_km / duration_s * 3600
            consumption = self.consumption_per_km(v_avg_kmh) * distance_km

            self.port.flow = consumption.derivative(duration_s)
            logger = logging.getLogger('vehicle_logger')
            logger.debug('t = %d (%s): Traction power %.2f kW' %
                         (self.env.now, hms_str(self.env.now),
                          self.port.flow.energy_ref))
            yield self.env.timeout(duration_s)
            self.port.flow = EnergyFlow.from_energy_ref(self.port.medium, 0)
            logger.debug('t = %d (%s): Traction power %.2f kW' %
                         (self.env.now, hms_str(self.env.now),
                          self.port.flow.energy_ref))

    def consumption_per_km(self, v_avg_kmh):
        mass_min = 12650
        mass_max = mass_min + 65 * global_constants['AVERAGE_PASSENGER_WEIGHT_KG']
        logger = logging.getLogger('vehicle_logger')
        if mass_min <= self.vehicle.total_mass <= mass_max:
            prev_params = self.correlation_map[mass_min]
            for mass, params in self.correlation_map.items():
                if mass == self.vehicle.total_mass:
                    a, b, c = params
                    energy_consumption_kwh_km = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)
                elif mass > self.vehicle.total_mass:
                    a, b, c = params
                    energy_consumption_kwh_km_ceil = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)
                    a, b, c = prev_params
                    energy_consumption_kwh_km_floor = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)
                    energy_consumption_kwh_km = (energy_consumption_kwh_km_ceil - energy_consumption_kwh_km_floor) / 2
                prev_params = params
        elif self.vehicle.total_mass > mass_max:
            logger.debug('%d > %d. considering mass of %d to calculate traction consumption'
                         % (self.vehicle.total_mass, mass_max, mass_max))
            a, b, c = self.correlation_map[mass_max]
            energy_consumption_kwh_km = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)
        else:
            logger.debug('%d < %d. considering mass of %d to calculate traction consumption'
                         % (self.vehicle.total_mass, mass_min, mass_min))
            a, b, c = self.correlation_map[mass_min]
            energy_consumption_kwh_km = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)

        return Energy.from_energy(Fuels.electricity, energy_consumption_kwh_km)


class EfficiencyMapTraction_18m_bus(Traction_Leg):
    def __init__(self, env, medium):
        super().__init__(env, medium)
        self.correlation_map = io.import_pickle(
            '/Users/jonassm/tubCloud/Shared/Datenaustausch_eflips/Jonas/'
            '05_MA_Tilman König, Traktionsmodell E-Bus/Simulationsmodell/Kennlinien/correlation_map_mass.dat')

    def _drive(self, distance_km, duration_s):
        if duration_s > 0:
            v_avg_kmh = distance_km / duration_s * 3600
            consumption = self.consumption_per_km(v_avg_kmh) * distance_km

            self.port.flow = consumption.derivative(duration_s)
            logger = logging.getLogger('vehicle_logger')
            logger.debug('t = %d (%s): Traction power %.2f kW' %
                         (self.env.now, hms_str(self.env.now),
                          self.port.flow.energy_ref))
            yield self.env.timeout(duration_s)
            self.port.flow = EnergyFlow.from_energy_ref(self.port.medium, 0)
            logger.debug('t = %d (%s): Traction power %.2f kW' %
                         (self.env.now, hms_str(self.env.now),
                          self.port.flow.energy_ref))

    def consumption_per_km(self, v_avg_kmh):
        mass_ref = self.vehicle.total_mass / 1.5
        mass_min = 12650
        mass_max = mass_min + 65*global_constants['AVERAGE_PASSENGER_WEIGHT_KG']
        logger = logging.getLogger('vehicle_logger')
        if mass_min <= mass_ref <= mass_max:
            prev_params = self.correlation_map[mass_min]
            for mass, params in self.correlation_map.items():
                if mass > mass_ref:
                    a, b, c = params
                    energy_consumption_kwh_km_ceil = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)
                    a, b, c = prev_params
                    energy_consumption_kwh_km_floor = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)
                    energy_consumption_kwh_km = (energy_consumption_kwh_km_ceil + energy_consumption_kwh_km_floor)/2
                    break
                prev_params = params
        elif mass_ref > mass_max:
            logger.debug('%d > %d. considering mass of %d to calculate traction consumption'
                         % (self.vehicle.total_mass, mass_max * 1.5, mass_max * 1.5))
            a, b, c = self.correlation_map[mass_max]
            energy_consumption_kwh_km = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)
        else:
            logger.debug('%d < %d. considering mass of %d to calculate traction consumption'
                         % (self.vehicle.total_mass, mass_min * 1.5, mass_min * 1.5))
            a, b, c = self.correlation_map[mass_min]
            energy_consumption_kwh_km = (a * np.log(v_avg_kmh) + b) * (1 + c / v_avg_kmh)

        return Energy.from_energy(Fuels.electricity, energy_consumption_kwh_km*1.5)


class Fleet:
    def __init__(self, env, vehicle_type_map, charging_network=None,
                 charging_schedule=None, ambient=None):
        self.env = env
        self.vehicle_type_map = vehicle_type_map
        self.charging_network = charging_network
        self.charging_schedule = charging_schedule
        self.ambient = ambient
        self.vehicle_types = []
        self._vehicle_stack = IndexedContainer()
        self.state_change_event = eflips.events.EventHandler(self)

        # Invoke DataLogger
        self.log_attributes = {
            'num_vehicles': {
                'attribute': 'num_vehicles',
                'name': 'Number of vehicles generated',
                'unit': None,
                'discrete': True
            }
        }
        self.params = None

        if global_constants['DATA_LOGGING']:
            self.logger = DataLogger(env, self)

    @property
    def num_vehicles(self):
        return Counter([v.vehicle_type.name for v
                        in self._vehicle_stack.get_all()])

    @property
    def mileage(self):
        mileage = CalcDict()
        for vehicle in self._vehicle_stack.get_all():
            vtype = vehicle.vehicle_type.name
            if vtype not in mileage:
                mileage.update({vtype: vehicle.odo})
            else:
                mileage[vtype] += vehicle.odo
        return mileage


    def create_vehicle(self, vehicle_type_string, ID=None):
        """Wrapper function to create new Vehicle objects using flat parameter
        sets. Variants of the same vehicle_type with different parameters
        are defined as subtypes. The calling class must handle correct passing
        of the respective parameter set for each subtype.

        Still evolving as Vehicle and auxiliary classes (AirConditioning, ...)
        are not yet complete."""
        vehicle_type = self.vehicle_type_map[vehicle_type_string]
        if not isinstance(vehicle_type, VehicleType):
            logger = logging.getLogger('vehicle_logger')
            logger.error('vehicle_type must be an instance of VehicleType')
            raise TypeError('vehicle_type must be an instance of VehicleType')

        if vehicle_type not in self.vehicle_types:
            # Keep track of all vehicle types currently in operation:
            self.vehicle_types.append(vehicle_type)

        arch = vehicle_type.architecture
        params = vehicle_type.params

        arch_electric_bus = ['bus_electric_constantaux',
                             'bus_electric_hvac',
                             'bus_electric_hvac_dualmedia',
                             'bus_electric_valeo_hvac_electric',
                             'bus_electric_valeo_hvac_diesel',
                             'bus_electric_konvekta_hvac_electric',
                             'bus_electric_konvekta_hvac_diesel',
                             'bus_electric_no_logging']

        if arch in arch_electric_bus:
            # Common operations for electric buses:
            # 1. Create traction model
            # 2. Create aux
            # 3. Create battery
            # 4. Create charging interfaces

            # Create traction model
            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            elif params['traction_model'].lower() == 'efficiencymaptraction_18m_bus':
                traction = EfficiencyMapTraction_18m_bus(self.env,
                                                         Fuels.electricity)
            elif params['traction_model'].lower() == 'efficiencymaptraction_12m_bus':
                traction = EfficiencyMapTraction_12m_bus(self.env,
                                                         Fuels.electricity)
            elif params['traction_model'].lower() == 'longitudinaldynamicstraction_constantefficiency':
                traction = LongitudinalDynamicsTraction_ConstantEfficiency(
                    self.env,
                    Fuels.electricity,
                    params['traction']['f_r'],
                    params['traction']['c_w'],
                    params['traction']['A'],
                    params['traction']['lambda'],
                    params['traction']['eta_total']
                )
            else:
                raise ValueError('Traction model ' + params['traction_model'] + ' not supported')

            # Create auxiliaries
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )

            # Create battery
            battery = Battery(self.env,
                              Energy.from_energy(Fuels.electricity,
                                                 params['battery']
                                                 ['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            # Create charging interfaces
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]


            # Create diesel heating tank if required
            if arch in ['bus_electric_hvac_dualmedia',
                        'bus_electric_valeo_hvac_diesel',
                        'bus_electric_konvekta_hvac_diesel',
                        'bus_electric_konvekta_hvac_electric_diesel']:
                diesel_tank = DieselTank(self.env,
                                         Energy.from_volume(
                                             Fuels.diesel,
                                             params['diesel_tank']['volume']),
                                         Energy.from_volume(
                                             Fuels.diesel,
                                             params['diesel_tank']['volume_init']))
                charging_interface_list_secondary = []

            # Create HVAC system if required
            if arch == 'bus_electric_hvac':
                # General-purpose electric HVAC model (AC + heat pump +
                # electric backup heater)
                hvac = HVACWithBackup(
                    self.env,
                    Fuels.electricity,
                    EnergyFlow.from_energy(Fuels.heat,
                                           params['hvac']['capacity_ac_unit']),
                    params['hvac']['cop_ac'],
                    params['hvac']['num_ac_units'],
                    EnergyFlow.from_energy(Fuels.heat,
                                           params['hvac']['capacity_hp_unit']),
                    params['hvac']['cop_hp'],
                    params['hvac']['num_hp_units'],
                    EnergyFlow.from_energy(Fuels.heat,
                                           params['hvac'][
                                               'capacity_backup_unit']),
                    params['hvac']['cop_backup'],
                    params['hvac']['num_backup_units'])

            elif arch == 'bus_electric_hvac_dualmedia':
                # General-purpose electric/diesel HVAC model (AC + heat pump +
                # diesel backup heater). Can also be used to simulate
                # AC + electric resistance heater + diesel backup heater.
                hvac = HVACWithBackupDualMedia(
                    self.env,
                    Fuels.electricity,
                    Fuels.diesel,
                    EnergyFlow.from_energy(Fuels.heat,
                                           params['hvac']['capacity_ac_unit']),
                    params['hvac']['cop_ac'],
                    params['hvac']['num_ac_units'],
                    EnergyFlow.from_energy(Fuels.heat,
                                           params['hvac']['capacity_hp_unit']),
                    params['hvac']['cop_hp'],
                    params['hvac']['num_hp_units'],
                    EnergyFlow.from_energy(Fuels.heat,
                                           params['hvac'][
                                               'capacity_backup_unit']),
                    params['hvac']['cop_backup'],
                    params['hvac']['num_backup_units'],
                    medium_ac=params['hvac']['medium_ac'],
                    medium_hp=params['hvac']['medium_hp'],
                    medium_backup=params['hvac']['medium_backup'])

            elif arch == 'bus_electric_valeo_hvac_electric':
                # Valeo R134a AC/heat pump + electric backup heater
                if 'hp_cutoff_temperature' in params['hvac']:
                    hvac = ValeoR134aHeatPump_ElectricBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'],
                        hp_cutoff=params['hvac']['hp_cutoff_temperature'])
                else:
                    hvac = ValeoR134aHeatPump_ElectricBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'])

            elif arch == 'bus_electric_valeo_hvac_diesel':
                # Valeo R134a AC/heat pump + diesel backup heater
                if 'hp_cutoff_temperature' in params['hvac']:
                    hvac = ValeoR134aHeatPump_DieselBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'],
                        hp_cutoff=params['hvac']['hp_cutoff_temperature'])
                else:
                    hvac = ValeoR134aHeatPump_DieselBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'])

            elif arch == 'bus_electric_konvekta_hvac_electric':
                # Konvekta R744 AC/heat pump + electric backup heater
                if 'hp_cutoff_temperature' in params['hvac']:
                    hvac = KonvektaR744HeatPump_ElectricBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'],
                        hp_cutoff=params['hvac']['hp_cutoff_temperature'])
                else:
                    hvac = KonvektaR744HeatPump_ElectricBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'])

            elif arch == 'bus_electric_konvekta_hvac_diesel':
                # Konvekta R744 AC/heat pump + diesel backup heater
                if 'hp_cutoff_temperature' in params['hvac']:
                    hvac = KonvektaR744HeatPump_DieselBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'],
                        hp_cutoff=params['hvac']['hp_cutoff_temperature'])
                else:
                    hvac = KonvektaR744HeatPump_DieselBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_hp_units'],
                        params['hvac']['num_backup_units'])

            elif arch == 'bus_electric_konvekta_hvac_electric_diesel':
                # Konvekta R134a AC + electric heater + diesel backup heater
                if 'electric_heating_cutoff_temperature' in params['hvac']:
                    hvac = KonvektaR134aAC_ElectricHeating_DieselBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_heating_units'],
                        params['hvac']['num_backup_units'],
                        electric_heating_cutoff=params['hvac'] \
                            ['electric_heating_cutoff_temperature'])
                else:
                    hvac = KonvektaR134aAC_ElectricHeating_DieselBackup(
                        self.env,
                        params['hvac']['num_ac_units'],
                        params['hvac']['num_heating_units'],
                        params['hvac']['num_backup_units'])

            # Create vehicle
            if arch == 'bus_electric_constantaux':
                vehicle = SimpleVehicle(
                    self.env, vehicle_type, self.charging_network, traction,
                    aux, battery, charging_interface_list_primary,
                    params['kerb_weight'],
                    num_passengers=params['num_passengers'],
                    charging_schedule=self.charging_schedule)
            elif arch == 'bus_electric_no_logging':
                vehicle = SimpleVehicleNoLogging(
                    self.env, vehicle_type, self.charging_network, traction,
                    aux, battery, charging_interface_list_primary,
                    charging_schedule=self.charging_schedule)
            elif arch in ['bus_electric_hvac',
                          'bus_electric_valeo_hvac_electric',
                          'bus_electric_konvekta_hvac_electric']:
                vehicle = VehicleWithHVAC(
                    self.env, vehicle_type, self.charging_network, traction,
                    aux, hvac, battery, charging_interface_list_primary,
                    self.ambient, params['kerb_weight'],
                    num_passengers=params['num_passengers'],
                    cabin_temperature=params['cabin_temperature'],
                    charging_schedule=self.charging_schedule)
            elif arch in ['bus_electric_hvac_dualmedia',
                          'bus_electric_valeo_hvac_diesel',
                          'bus_electric_konvekta_hvac_diesel',
                          'bus_electric_konvekta_hvac_electric_diesel']:
                vehicle = VehicleWithHVAC(
                    self.env, vehicle_type, self.charging_network, traction,
                    aux, hvac, battery, charging_interface_list_primary,
                    self.ambient, params['kerb_weight'],
                    num_passengers=params['num_passengers'],
                    cabin_temperature=params['cabin_temperature'],
                    storage_secondary=diesel_tank,
                    list_of_charging_interfaces_secondary=
                        charging_interface_list_secondary,
                    charging_schedule=self.charging_schedule)

        elif arch == 'bus_hydrogen':
            pass

        elif arch == 'bus_diesel':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.diesel,
                EnergyFlow.from_volume(Fuels.diesel,
                                       params['aux_consumption'])
            )
            if params[
                'traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.diesel,
                    Energy.from_volume(Fuels.diesel,
                                       params['traction_consumption']))
            else:
                ValueError('Only Simple Traction is supported')
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type))
                for interface_type in params['charging_interfaces']
            ]
            diesel_tank = DieselTank(self.env,
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume']),
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank'][
                                             'volume_init']))

            vehicle = SimpleVehicle(self.env, vehicle_type,
                                    self.charging_network, traction,
                                    aux, diesel_tank,
                                    charging_interface_list_primary,
                                    params['kerb_weight'],
                                    num_passengers=params[
                                        'num_passengers'],
                                    charging_schedule=self.charging_schedule)

        self._vehicle_stack.add(vehicle)
        self.state_change_event()
        return vehicle


    def create_vehicle_old(self, vehicle_type_string, ID=None):
        """Wrapper function to create new Vehicle objects using flat parameter
        sets. Variants of the same vehicle_type with different parameters
        are defined as subtypes. The calling class must handle correct passing
        of the respective parameter set for each subtype.

        Still evolving as Vehicle and auxiliary classes (AirConditioning, ...)
        are not yet complete."""
        vehicle_type = self.vehicle_type_map[vehicle_type_string]
        if not isinstance(vehicle_type, VehicleType):
            logger = logging.getLogger('vehicle_logger')
            logger.error('vehicle_type must be an instance of VehicleType')
            raise TypeError('vehicle_type must be an instance of VehicleType')

        if vehicle_type not in self.vehicle_types:
            # Keep track of all vehicle types currently in operation:
            self.vehicle_types.append(vehicle_type)

        arch = vehicle_type.architecture
        params = vehicle_type.params

        if arch == 'bus_electric_constantaux':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )
            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            elif params['traction_model'].lower() == 'efficiencymaptraction_18m_bus':
                traction = EfficiencyMapTraction_18m_bus(self.env,
                                                         Fuels.electricity)
            elif params['traction_model'].lower() == 'efficiencymaptraction_12m_bus':
                traction = EfficiencyMapTraction_12m_bus(self.env,
                                                         Fuels.electricity)
            else:
                ValueError('Traction model ' + params['traction_model'] + ' not supported')
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(Fuels.electricity,
                                                 params['battery']
                                                 ['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            vehicle = SimpleVehicle(self.env, vehicle_type,
                                    self.charging_network, traction,
                                    aux, battery,
                                    charging_interface_list_primary,
                                    num_passengers=params['num_passengers'],
                                    charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_hvac':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )
            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            elif params['traction_model'].lower() == 'efficiencymaptraction_18m_bus':
                traction = EfficiencyMapTraction_18m_bus(self.env,
                                                         Fuels.electricity)
            elif params['traction_model'].lower() == 'efficiencymaptraction_12m_bus':
                traction = EfficiencyMapTraction_12m_bus(self.env,
                                                         Fuels.electricity)
            else:
                ValueError('Traction model ' + params['traction_model'] + ' not supported')
            hvac = HVACWithBackup(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.heat,
                                       params['hvac']['capacity_ac_unit']),
                params['hvac']['cop_ac'],
                params['hvac']['num_ac_units'],
                EnergyFlow.from_energy(Fuels.heat,
                                       params['hvac']['capacity_hp_unit']),
                params['hvac']['cop_hp'],
                params['hvac']['num_hp_units'],
                EnergyFlow.from_energy(Fuels.heat,
                                       params['hvac']['capacity_backup_unit']),
                params['hvac']['cop_backup'],
                params['hvac']['num_backup_units'])
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(Fuels.electricity,
                                                 params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            vehicle = VehicleWithHVAC(self.env, vehicle_type,
                self.charging_network, traction,
                aux, hvac, battery, charging_interface_list_primary,
                self.ambient,
                num_passengers=params['num_passengers'],
                cabin_temperature=params['cabin_temperature'],
                charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_hvac_dualmedia':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )
            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            # elif params['traction_model'].lower() == 'complextraction':
            #     traction = ComplexTraction(self.env, Fuels.electricity, num_passengers)
            # env, medium_primary, medium_secondary,
            # capacity_ac_unit, cop_ac, num_ac_units,
            # capacity_hp_unit, cop_hp, num_hp_units,
            # capacity_backup_unit, cop_backup, num_backup_units,
            # medium_ac = 'primary', medium_hp = 'primary',
            # medium_backup = 'primary', vehicle = None

            hvac = HVACWithBackupDualMedia(
                self.env,
                Fuels.electricity,
                Fuels.diesel,
                EnergyFlow.from_energy(Fuels.heat,
                                       params['hvac']['capacity_ac_unit']),
                params['hvac']['cop_ac'],
                params['hvac']['num_ac_units'],
                EnergyFlow.from_energy(Fuels.heat,
                                       params['hvac']['capacity_hp_unit']),
                params['hvac']['cop_hp'],
                params['hvac']['num_hp_units'],
                EnergyFlow.from_energy(Fuels.heat,
                                       params['hvac']['capacity_backup_unit']),
                params['hvac']['cop_backup'],
                params['hvac']['num_backup_units'],
                medium_ac=params['hvac']['medium_ac'],
                medium_hp=params['hvac']['medium_hp'],
                medium_backup=params['hvac']['medium_backup'])
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(
                                  Fuels.electricity,
                                  params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            diesel_tank = DieselTank(self.env,
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume']),
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume_init']))

            charging_interface_list_secondary = []

            vehicle = VehicleWithHVAC(
                self.env,
                vehicle_type,
                self.charging_network,
                traction,
                aux,
                hvac,
                battery,
                charging_interface_list_primary,
                self.ambient,
                num_passengers=params['num_passengers'],
                cabin_temperature=params['cabin_temperature'],
                storage_secondary=diesel_tank,
                charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_valeo_hvac_electric':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )

            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            elif params['traction_model'].lower() == 'efficiencymaptraction_18m_bus':
                traction = EfficiencyMapTraction_18m_bus(self.env,
                                                         Fuels.electricity)
            elif params['traction_model'].lower() == 'efficiencymaptraction_12m_bus':
                traction = EfficiencyMapTraction_12m_bus(self.env,
                                                         Fuels.electricity)
            else:
                ValueError('Traction model ' + params['traction_model'] + ' not supported')

            if 'hp_cutoff_temperature' in params['hvac']:
                hvac = ValeoR134aHeatPump_ElectricBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'],
                    hp_cutoff=params['hvac']['hp_cutoff_temperature'])
            else:
                hvac = ValeoR134aHeatPump_ElectricBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'])
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(Fuels.electricity,
                                                 params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            vehicle = VehicleWithHVAC(self.env, vehicle_type,
                self.charging_network, traction,
                aux, hvac, battery, charging_interface_list_primary,
                self.ambient,
                num_passengers=params['num_passengers'],
                cabin_temperature=params['cabin_temperature'],
                charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_valeo_hvac_diesel':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )

            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            else:
                ValueError('Only Simple Traction is supported')

            if 'hp_cutoff_temperature' in params['hvac']:
                hvac = ValeoR134aHeatPump_DieselBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'],
                    hp_cutoff=params['hvac']['hp_cutoff_temperature'])
            else:
                hvac = ValeoR134aHeatPump_DieselBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'])
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(
                                  Fuels.electricity,
                                  params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            diesel_tank = DieselTank(self.env,
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume']),
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume_init']))

            charging_interface_list_secondary = []

            vehicle = VehicleWithHVAC(
                self.env,
                vehicle_type,
                self.charging_network,
                traction,
                aux,
                hvac,
                battery,
                charging_interface_list_primary,
                self.ambient,
                num_passengers=params['num_passengers'],
                cabin_temperature=params['cabin_temperature'],
                storage_secondary=diesel_tank,
                charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_konvekta_hvac_electric':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )
            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            elif params['traction_model'].lower() == 'efficiencymaptraction_18m_bus':
                traction = EfficiencyMapTraction_18m_bus(self.env,
                                                         Fuels.electricity)
            elif params['traction_model'].lower() == 'efficiencymaptraction_12m_bus':
                traction = EfficiencyMapTraction_12m_bus(self.env,
                                                         Fuels.electricity)
            else:
                ValueError('Traction model ' + params['traction_model'] + ' not supported')
            if 'hp_cutoff_temperature' in params['hvac']:
                hvac = KonvektaR744HeatPump_ElectricBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'],
                    hp_cutoff=params['hvac']['hp_cutoff_temperature'])
            else:
                hvac = KonvektaR744HeatPump_ElectricBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'])
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(Fuels.electricity,
                                                 params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              # soc_min,
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            vehicle = VehicleWithHVAC(self.env, vehicle_type,
                                      self.charging_network, traction,
                                      aux, hvac, battery, charging_interface_list_primary,
                                      self.ambient,
                                      num_passengers=params['num_passengers'],
                                      kerb_weight=params['kerb_weight'],
                                      cabin_temperature=params['cabin_temperature'],
                                      charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_konvekta_hvac_diesel':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )

            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            else:
                ValueError('Only Simple Traction is supported')

            if 'hp_cutoff_temperature' in params['hvac']:
                hvac = KonvektaR744HeatPump_DieselBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'],
                    hp_cutoff=params['hvac']['hp_cutoff_temperature'])
            else:
                hvac = KonvektaR744HeatPump_DieselBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_hp_units'],
                    params['hvac']['num_backup_units'])
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(
                                  Fuels.electricity,
                                  params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            diesel_tank = DieselTank(self.env,
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume']),
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume_init']))

            charging_interface_list_secondary = []

            vehicle = VehicleWithHVAC(
                self.env,
                vehicle_type,
                self.charging_network,
                traction,
                aux,
                hvac,
                battery,
                charging_interface_list_primary,
                self.ambient,
                num_passengers=params['num_passengers'],
                cabin_temperature=params['cabin_temperature'],
                storage_secondary=diesel_tank,
                charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_konvekta_hvac_electric_diesel':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )

            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            else:
                ValueError('Only Simple Traction is supported')

            if 'electric_heating_cutoff_temperature' in params['hvac']:
                hvac = KonvektaR134aAC_ElectricHeating_DieselBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_heating_units'],
                    params['hvac']['num_backup_units'],
                    electric_heating_cutoff=params['hvac']\
                        ['electric_heating_cutoff_temperature'])
            else:
                hvac = KonvektaR134aAC_ElectricHeating_DieselBackup(
                    self.env,
                    params['hvac']['num_ac_units'],
                    params['hvac']['num_heating_units'],
                    params['hvac']['num_backup_units'])
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                        for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(
                                  Fuels.electricity,
                                  params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            diesel_tank = DieselTank(self.env,
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume']),
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume_init']))

            charging_interface_list_secondary = []

            vehicle = VehicleWithHVAC(
                self.env,
                vehicle_type,
                self.charging_network,
                traction,
                aux,
                hvac,
                battery,
                charging_interface_list_primary,
                self.ambient,
                num_passengers=params['num_passengers'],
                cabin_temperature=params['cabin_temperature'],
                storage_secondary=diesel_tank,
                charging_schedule=self.charging_schedule)

        elif arch == 'bus_electric_no_logging':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.electricity,
                EnergyFlow.from_energy(Fuels.electricity, params['aux_power'])
            )
            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.electricity,
                    Energy.from_energy(Fuels.electricity,
                                       params['traction_consumption']))
            else:
                ValueError('Only Simple Traction are supported')
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type)) \
                for interface_type in params['charging_interfaces']
            ]
            battery = Battery(self.env,
                              Energy.from_energy(Fuels.electricity,
                                                 params['battery']['capacity_max']),
                              params['battery']['soc_reserve'],
                              params['battery']['soc_min'],
                              params['battery']['soc_max'],
                              params['battery']['soc_init'],
                              params['battery']['soh'],
                              params['battery']['discharge_rate'],
                              params['battery']['charge_rate'])

            vehicle = SimpleVehicleNoLogging(self.env, vehicle_type,
                                             self.charging_network, traction,
                                             aux, battery, charging_interface_list_primary,
                                             num_passengers=params['num_passengers'],
                                             charging_schedule=self.charging_schedule)

        elif arch == 'bus_hydrogen':
            pass

        elif arch == 'bus_diesel':
            aux = ConstantPowerDevice(
                self.env,
                Fuels.diesel,
                EnergyFlow.from_volume(Fuels.diesel, params['aux_consumption'])
            )
            if params['traction_model'].lower() == 'constantconsumptiontraction':
                traction = ConstantConsumptionTraction(
                    self.env,
                    Fuels.diesel,
                    Energy.from_volume(Fuels.diesel,
                                       params['traction_consumption']))
            else:
                ValueError('Only Simple Traction is supported')
            charging_interface_list_primary = [
                ChargingInterface(
                    self.env,
                    getattr(ChargingInterfaceTypes, interface_type))
                for interface_type in params['charging_interfaces']
            ]
            diesel_tank = DieselTank(self.env,
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume']),
                                     Energy.from_volume(
                                         Fuels.diesel,
                                         params['diesel_tank']['volume_init']))

            vehicle = SimpleVehicle(self.env, vehicle_type,
                                    self.charging_network, traction,
                                    aux, diesel_tank,
                                    charging_interface_list_primary,
                                    num_passengers=params['num_passengers'],
                                    charging_schedule=self.charging_schedule)

        self._vehicle_stack.add(vehicle)
        self.state_change_event()
        return vehicle

    def get_all(self):
        return self._vehicle_stack.get_all()

    def get_all_by_ID(self):
        return self._vehicle_stack.get_all_by_ID()

def cabin_temperature_vdv(ambient_temperature):
    """Determine desired cabin temperature in °C according to VDV 236 (2015).
    Returns a dict with the maximum and minimum temperature permitted as well
    as the temperature required by the 'comfort' and 'economy' profiles."""
    if ambient_temperature <= -13:
        T_max = 17
        T_min = 12
        T_comf = 16
        T_eco = 14
    elif ambient_temperature > -13 and ambient_temperature <= -10:
        T_max = 5/3 * (ambient_temperature + 13) + 17
        T_min = 5/3 * (ambient_temperature + 13) + 12
        T_comf = 4/3 * (ambient_temperature + 13) + 16
        T_eco = 4/3 * (ambient_temperature + 13) + 14
    elif ambient_temperature > -10 and ambient_temperature <= 22:
        T_max = 22
        T_min = 17
        T_comf = 1/32 * (ambient_temperature + 10) + 20
        T_eco = 1/32 * (ambient_temperature + 10) + 18
    elif ambient_temperature > 22 and ambient_temperature <= 35:
        T_max = 10/13 * (ambient_temperature - 22) + 22
        T_min = 10/13 * (ambient_temperature - 22) + 17
        T_comf = 9/13 * (ambient_temperature - 22) + 21
        T_eco = 12/13 * (ambient_temperature - 22) + 19
    else:  # > 35°C
        T_max = 32
        T_min = 27
        T_comf = 30
        T_eco = 31
    return {'max': T_max, 'min': T_min, 'comfort': T_comf,
            'economy': T_eco}
