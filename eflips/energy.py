# -*- coding: utf-8 -*-
import eflips.events
import numbers
import logging
from abc import ABCMeta, abstractmethod
from eflips.settings import global_constants
from eflips.misc import set_default_kwargs, hms_str
import math


class Unit:
    def __init__(self, name, factor):
        self.name = name
        self.factor = factor


class Units:
    """Unit system to be used. The default (=reference) units are:

        energy: kWh
        mass: kg
        mass flow: kg/s
        volume: L
        volume flow: L/s
        distance: km

    If a unit is changed, the correction factor has to be set to satisfy the
    following:

        newUnit = defaultUnit * factor

    For example: energy = Unit('MWh', 1000).

    wall_time specifies the wall clock time equivalent of one simulation time
    increment in seconds. The default is 1 second. If the simulation clock
    shall count minutes, set wall_time = Unit('min', 60). If it shall count
    hours, wall_time = Unit('h', 3600) and so forth.

    """
    energy = Unit('kWh', 1)
    power = Unit('kW', 1)
    mass = Unit('kg', 1)
    massflow = Unit('kg/s', 1)
    volume = Unit('L', 1)
    volumeflow = Unit('L/s', 1)
    distance = Unit('km', 1)
    wall_time = Unit('s', 1)


class EnergyMedium:
    """Any energy medium."""
    def __init__(self, name):
        self.name = name


class Fuel(EnergyMedium):
    """Liquid or gaseous fuel. Heating value MUST be specified in kJ/kg,
    and density MUST be specified in kg/L. In case of gaseous fuels, specify
    the density at atmospheric or normal conditions to get the normalised
    volume."""
    def __init__(self, name, heatingValue, density):
        super().__init__(name)
        self.heatingValue = heatingValue
        self.density = density


class Fuels:
    diesel = Fuel('Diesel', 42700, 0.84)
    hydrogen = Fuel('Hydrogen', 120000, 0.0899e-3)
    electricity = EnergyMedium('Electricity')
    heat = EnergyMedium('Heat')
    mechanical = EnergyMedium('Mechanical')


class EnergyAbstract(metaclass=ABCMeta):
    """Base class for energy and energy flow objects. Allows for easy conversion
    between energy, mass and volume representations.

    _ref denotes attributes specified in the reference units given in class
    Units. Energy calculations must ALWAYS use reference units internally as
    these cannot be overridden by the user."""
    def __init__(self, medium):
        super().__init__()
        self.medium = medium

    @classmethod
    def from_energy(cls, medium, quantity):
        obj = cls(medium)
        obj.energy = quantity
        return obj

    @classmethod
    def from_energy_ref(cls, medium, quantity):
        obj = cls(medium)
        obj.energy_ref = quantity
        return obj

    @classmethod
    def from_mass(cls, medium, quantity):
        if type(medium) is not Fuel:
            logger = logging.getLogger('energy_logger')
            logger.error('TypeError: Can only be applied to medium of type Fuel')
            raise TypeError('Can only be applied to medium of type Fuel')
        obj = cls(medium)
        obj.mass = quantity
        return obj

    @classmethod
    def from_mass_ref(cls, medium, quantity):
        if type(medium) is not Fuel:
            logger = logging.getLogger('energy_logger')
            logger.error('TypeError: Can only be applied to medium of type Fuel')
            raise TypeError('Can only be applied to medium of type Fuel')
        obj = cls(medium)
        obj.mass_ref = quantity
        return obj

    @classmethod
    def from_volume(cls, medium, quantity):
        if type(medium) is not Fuel:
            logger = logging.getLogger('energy_logger')
            logger.error('TypeError: Can only be applied to medium of type Fuel')
            raise TypeError('Can only be applied to medium of type Fuel')
        obj = cls(medium)
        obj.volume = quantity
        return obj

    @classmethod
    def from_volume_ref(cls, medium, quantity):
        if type(medium) is not Fuel:
            logger = logging.getLogger('energy_logger')
            logger.error('TypeError: Can only be applied to medium of type Fuel')
            raise TypeError('Can only be applied to medium of type Fuel')
        obj = cls(medium)
        obj.volume_ref = quantity
        return obj

    @property
    def energy_ref(self):
        return self._energy_ref

    @property
    @abstractmethod
    def energy(self):
        pass

    @property
    @abstractmethod
    def mass_ref(self):
        pass

    @property
    @abstractmethod
    def mass(self):
        pass

    @property
    @abstractmethod
    def volume_ref(self):
        pass

    @property
    @abstractmethod
    def volume(self):
        pass

    @energy_ref.setter
    def energy_ref(self, value):
        self._energy_ref = value

    @energy.setter
    @abstractmethod
    def energy(self, value):
        pass

    @mass_ref.setter
    @abstractmethod
    def mass_ref(self, value):
        pass

    @mass.setter
    @abstractmethod
    def mass(self, value):
        pass

    @volume_ref.setter
    @abstractmethod
    def volume_ref(self, value):
        pass

    @volume.setter
    @abstractmethod
    def volume(self, value):
        pass

    def __eq__(self, other):
        """=="""
        if other == 0:
            # We need this little hack to be able to use sum() on energy objects
            other = self.__class__.from_energy_ref(self.medium, 0)
        return self.energy_ref == other.energy_ref

    def __ne__(self, other):
        """!="""
        if other == 0:
            # We need this little hack to be able to use sum() on energy objects
            other = self.__class__.from_energy_ref(self.medium, 0)
        return not self.energy_ref == other.energy_ref

    def __abs__(self):
        """abs()"""
        res = self.__class__.from_energy_ref(self.medium,
                                             abs(self._energy_ref))
        return res

    def __pos__(self):
        """unary +"""
        return self

    def __neg__(self):
        """unary -"""
        res = self.__class__.from_energy_ref(self.medium,
                                             -self._energy_ref)
        return res

    def __add__(self, other):
        """binary +"""
        if other == 0:
            # We need this little hack to be able to use sum() on energy objects
            other = self.__class__.from_energy_ref(self.medium, 0)
        elif type(self) != type(other):
            logger = logging.getLogger('energy_logger')
            logger.error('TypeError: Can only add energy objects of identical type.')
            raise TypeError('Can only add energy objects of identical type.')
        if self.medium.name != other.medium.name:
            logger = logging.getLogger('energy_logger')
            logger.error('ValueError: When adding energy objects, each object '
                             'must have identical medium attributes.')
            raise ValueError('When adding energy objects, each object '
                             'must have identical medium attributes.')
        res = self.__class__.from_energy_ref(self.medium,
                                             self._energy_ref
                                             + other._energy_ref)
        return res

    def __round__(self, n=None):
        """round"""
        res = self.__class__.from_energy_ref(self.medium,
                                             round(self._energy_ref, n))
        return res

    def __radd__(self, other):
        """swapped binary +"""
        return self.__add__(other)

    def __sub__(self, other):
        """binary -"""
        if type(self) != type(other):
            logger = logging.getLogger('energy_logger')
            logger.error('TypeError: Can only subtract energy objects of identical type.')
            raise TypeError('Can only subtract energy objects of identical type.')
        if self.medium != other.medium:
            logger = logging.getLogger('energy_logger')
            logger.error('ValueError: When subtracting energy objects, each object '
                             'must have identical medium attributes.')
            raise ValueError('When subtracting energy objects, each object '
                             'must have identical medium attributes.')
        res = self.__class__.from_energy_ref(self.medium,
                                             self._energy_ref
                                             - other._energy_ref)
        return res

    def __mul__(self, other):
        """Enable multiplication by scalar"""
        if isinstance(other, numbers.Real):
            return self.__class__.from_energy_ref(self.medium,
                                                  self._energy_ref*other)
        else:
            return NotImplemented

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, other):
        """Enable division by same class or by scalar"""
        if isinstance(other, EnergyAbstract):
            # return scalar
            return self.energy_ref/other.energy_ref
        else:
            # pass to __mul__
            return self.__mul__(1/other)

    def __lt__(self, other):
        if type(self) == type(other):
            return self._energy_ref < other._energy_ref
        else:
            return NotImplemented

    def __le__(self, other):
        if type(self) == type(other):
            return self._energy_ref <= other._energy_ref
        else:
            return NotImplemented

    def __gt__(self, other):
        if type(self) == type(other):
            return self._energy_ref > other._energy_ref
        else:
            return NotImplemented

    def __ge__(self, other):
        if type(self) == type(other):
            return self._energy_ref >= other._energy_ref
        else:
            return NotImplemented


class Energy(EnergyAbstract):
    @property
    def energy(self):
        return self._energy_ref / Units.energy.factor

    @property
    def mass_ref(self):
        return self._energy_ref * 3600 / self.medium.heatingValue \
            if hasattr(self.medium, 'heatingValue') else None

    @property
    def mass(self):
        return self._energy_ref * 3600 / self.medium.heatingValue \
               / Units.mass.factor \
            if hasattr(self.medium, 'heatingValue') else None

    @property
    def volume_ref(self):
        return self._energy_ref * 3600 / self.medium.heatingValue \
                / self.medium.density \
            if hasattr(self.medium, 'heatingValue') else None

    @property
    def volume(self):
        return self._energy_ref * 3600 / self.medium.heatingValue \
                / self.medium.density / Units.volume.factor \
            if hasattr(self.medium, 'heatingValue') else None

    @energy.setter
    def energy(self, value):
        self._energy_ref = value * Units.energy.factor

    @mass_ref.setter
    def mass_ref(self, value):
        self._energy_ref = value * self.medium.heatingValue / 3600

    @mass.setter
    def mass(self, value):
        self._energy_ref = value * Units.mass.factor \
                           * self.medium.heatingValue / 3600

    @volume_ref.setter
    def volume_ref(self, value):
        self._energy_ref = value * self.medium.density \
                           * self.medium.heatingValue / 3600

    @volume.setter
    def volume(self, value):
        self._energy_ref = value * Units.volume.factor \
                           * self.medium.density * self.medium.heatingValue \
                           / 3600

    def derivative(self, sim_duration):
        duration = sim_duration * Units.wall_time.factor  # s
        flow = 0 if duration == 0 else self.energy_ref / duration * 3600  # kW
        return EnergyFlow.from_energy_ref(self.medium, flow)


class EnergyFlow(EnergyAbstract):
    @property
    def energy(self):
        return self._energy_ref / Units.power.factor

    @property
    def mass_ref(self):
        return self._energy_ref / self.medium.heatingValue \
            if hasattr(self.medium, 'heatingValue') else None

    @property
    def mass(self):
        return self._energy_ref / self.medium.heatingValue \
               / Units.massflow.factor \
            if hasattr(self.medium, 'heatingValue') else None

    @property
    def volume_ref(self):
        return self._energy_ref / self.medium.heatingValue \
                / self.medium.density \
            if hasattr(self.medium, 'heatingValue') else None

    @property
    def volume(self):
        return self._energy_ref / self.medium.heatingValue \
                / self.medium.density / Units.volumeflow.factor \
            if hasattr(self.medium, 'heatingValue') else None

    @energy.setter
    def energy(self, value):
        self._energy_ref = value * Units.power.factor

    @mass_ref.setter
    def mass_ref(self, value):
        self._energy_ref = value * self.medium.heatingValue

    @mass.setter
    def mass(self, value):
        self._energy_ref = value * Units.massflow.factor \
                           * self.medium.heatingValue

    @volume_ref.setter
    def volume_ref(self, value):
        self._energy_ref = value * self.medium.density \
                           * self.medium.heatingValue

    @volume.setter
    def volume(self, value):
        self._energy_ref = value * Units.volumeflow.factor \
                           * self.medium.density * self.medium.heatingValue

    def integrate(self, sim_duration):
        duration = sim_duration * Units.wall_time.factor  # s
        energy = self.energy_ref * duration / 3600  # kWh
        return Energy.from_energy_ref(self.medium, energy)


class Port:
    def __init__(self, medium):
        self.medium = medium
        self._flow = EnergyFlow.from_energy_ref(medium, 0)
        # flow: > 0 consumption, < 0 production
        self.state_change_event = eflips.events.EventHandler(self)

    @property
    def flow(self):
        return self._flow

    @flow.setter
    def flow(self, value):
        if not self._flow == value:
            self._flow = value
            # print('t = %d: %s power %d kW' % (
            #     self.env.now, self.name, self.flow.energy_ref))
            self.state_change_event()


class MultiPort:
    """Multiplexer connecting several ports to determine the sum of all
    incoming and outgoing flows. Use this to connect multiple devices
    to an EnergyStorage or ChargeController."""
    def __init__(self, medium, list_of_in_ports=None):
        self.medium = medium
        self.out_port = Port(medium)
        if list_of_in_ports is None:
            list_of_in_ports = []
        self.in_ports = list_of_in_ports
        for port in list_of_in_ports:
            # Caution: no sanity check whether medium matches in all ports
            port.state_change_event.add(self._update)
        # self.state_change_event = eflips.events.EventHandler(self)
        self._update(self)

    def add_port(self, port):
        self.in_ports.append(port)
        port.state_change_event.add(self._update)

    def remove_port(self, port):
        self.in_ports.remove(port)
        port.state_change_event.remove(self._update)

    def _update(self, sender):
        """Recalculate energy flow as sum of all ports. Objects listening
        to out_port will be notified automatically."""
        # sum_flows = sum([port.flow for port in self.in_ports])

        # sum_flows becomes an integer zero if the list is empty, so check
        # for this:
        self.out_port.flow = sum([port.flow for port in self.in_ports])
        # self.out_port.flow = EnergyFlow.from_energy_ref(self.medium, 0) \
        #         if sum_flows == 0 else sum_flows


class ChargeController:
    def __init__(self, vehicle, env, medium, load_port, list_of_interfaces,
                 storage):
        self.vehicle = vehicle
        self.env = env
        self.medium = medium
        self.driving = vehicle.driving
        self._max_supply = EnergyFlow.from_energy_ref(self.medium, 0)
        self._bidirectional = False
        self._last_update = self.env.now

        # Port to monitor (=port connected to storage):
        self.load_port = load_port

        # Listen to changes on this port:
        self.load_port.state_change_event.add(self._update)

        # Interface port (to be used by ChargingFacilities):
        self.interface_port = Port(medium)

        self.interfaces = list_of_interfaces

        # Last flows (required for energy integration):
        self._last_interface_flow = EnergyFlow.from_energy_ref(self.medium, 0)
        self._last_load_flow = EnergyFlow.from_energy_ref(self.medium, 0)
        self._last_interface_to_storage_flow = \
            EnergyFlow.from_energy_ref(self.medium, 0)

        # Listen for changes in connectivity on any interface
        # (we will have to figure out how to make sure only one interface is
        # connected later):
        for interface in self.interfaces:
            interface.connect_event.add(self._connect_interface)
            interface.disconnect_event.add(self._disconnect_interface)

        # Listen for vehicle driving state changes (driving/stationary)
        vehicle.driving_state_change_event.add(self._driving_state_change)

        # Currently connected interface:
        self._interface_connected = None

        self.storage = storage  # EnergyStorage

        # Listen for 'force update' event (to refresh SoC while charging):
        self.storage.force_update_event.add(self._update)

        # Listen for 'fully charged' event (force update upon event):
        # self.storage.fully_charged_event.callbacks.append(self._update)
        self.storage.fully_charged_event.add(self._update)

        # Hook up energy storage port:
        self.charge_port = storage.port

        # Event for anyone listening to state changes in ChargeController.
        self.state_change_event = eflips.events.EventHandler(self)

        # Implement these two later if we need to analyse bidirectional
        # charging:
        # Total energy drawn from interface (> 0):
        # self.energy_from_interface = Energy.from_energy_ref(self.medium, 0)
        # Total energy fed back to interface (< 0):
        # self.energy_to_interface = Energy.from_energy_ref(self.medium, 0)

        # Net energy drawn from interface (> 0: from grid, < 0: to grid):
        self.energy_from_interface_net = Energy.from_energy_ref(self.medium, 0)

        # Net energy from interface to storage(> 0: from grid, < 0: to grid):
        self.energy_from_interface_to_storage = \
            Energy.from_energy_ref(self.medium, 0)

        # Net energy transferred to loads (=vehicle consumption):
        self.energy_to_loads_net = Energy.from_energy_ref(self.medium, 0)

        # Initialise variables required for energy flow integration:
        self.flow_interface_to_load = \
            EnergyFlow.from_energy_ref(self.medium, 0)
        self.flow_interface_to_storage = \
            EnergyFlow.from_energy_ref(self.medium, 0)
        self.flow_load_to_interface = \
            EnergyFlow.from_energy_ref(self.medium, 0)
        self.flow_load_to_storage = EnergyFlow.from_energy_ref(self.medium, 0)
        self.flow_storage_to_load = EnergyFlow.from_energy_ref(self.medium, 0)

    def _driving_state_change(self, sender):
        self.driving = self.vehicle.driving
        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): ChargeController noticed new '
                     'driving state: %s' % (self.env.now,
                                            hms_str(self.env.now),
                                            self.driving))
        self._update(self)

    def _select_charging_power(self):
        if self._interface_connected:
            if self.driving:
                supply = self._interface_connected.interface_type.\
                    max_flow_in_motion
            else:
                supply = self._interface_connected.interface_type.\
                    max_flow_stationary
        else:
            supply = EnergyFlow.from_energy_ref(self.medium, 0)
        self._max_supply = supply

    def _connect_interface(self, sender):
        if self._interface_connected is not None:
            logger = logging.getLogger('energy_logger')
            logger.error('RuntimeError: '
                         'Cannot connect two interfaces at the same time.')
            RuntimeError('Cannot connect two interfaces at the same time.')

        # sender is the interface object that fired the event
        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): Interface %s connected' %
                     (self.env.now, hms_str(self.env.now),
                      sender.interface_type.name))
        self._interface_connected = sender

        self._bidirectional = sender.interface_type.bidirectional
        self._select_charging_power()
        self._update(self)

    def _disconnect_interface(self, sender):
        # sender is the interface object that fired the event
        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): Interface %s disconnected' %
                  (self.env.now, hms_str(self.env.now),
                   sender.interface_type.name))
        self._interface_connected = None
        self._bidirectional = False
        self._select_charging_power()
        self._update(self)

    def _update(self, sender):
        # Integrate energy flow over period since last update:
        duration = self.env.now - self._last_update
        self.energy_from_interface_net += \
            self._last_interface_flow.integrate(duration)
        self.energy_to_loads_net += \
            self._last_load_flow.integrate(duration)
        self.energy_from_interface_to_storage += \
            self._last_interface_to_storage_flow.integrate(duration)

        # self.energy_from_interface_net += \
        #     self.interface_port.flow.integrate(duration)
        # self.energy_to_loads_net += \
        #     self.load_port.flow.integrate(duration)


        # Set energy flow variables for next period:

        # Update supply:
        self._select_charging_power()

        # Consumption or recuperation?
        if self.load_port.flow.energy_ref >= 0:
            # consumption
            self.direction = 1
        else:
            # recuperation:
            self.direction = -1

        if self.direction == 1:
            # consumption
            source_power = self._max_supply \
                           + abs(self.storage.flow_limit_lower)
            if self.load_port.flow > source_power:
                logger = logging.getLogger('energy_logger')
                logger.warning('Warning: Consumption %.2f exceeds available '
                               'source power %.2f' %
                               (self.load_port.flow.energy_ref,
                                source_power.energy_ref))
                # raise ValueError(
                # 'Consumption exceeds available source power')

            if self._max_supply > self.load_port.flow:
                # Interface can supply energy demand completely
                self.flow_interface_to_load = self.load_port.flow
            else:
                self.flow_interface_to_load = self._max_supply

            # Flow from load to interface is zero (no recuperation); same for
            # load to storage:
            self.flow_load_to_interface = EnergyFlow.from_energy_ref(
                self.storage.medium, 0)
            self.flow_load_to_storage = EnergyFlow.from_energy_ref(
                self.storage.medium, 0)

            # Storage must supply remaining power:
            self.flow_storage_to_load = self.load_port.flow \
                                        - self.flow_interface_to_load

            # Maximum power available for charging storage:
            self.flow_interface_to_storage_max = self._max_supply \
                                                 - self.flow_interface_to_load

            if self.flow_interface_to_storage_max <= \
                    self.storage.flow_limit_upper:
                self.flow_interface_to_storage \
                    = self.flow_interface_to_storage_max
            else:
                self.flow_interface_to_storage = self.storage.flow_limit_upper

        elif self.direction == -1:
            # recuperation
            if self._bidirectional:
                sink_power = self._max_supply + self.storage.flow_limit_upper
            else:
                sink_power = self.storage.flow_limit_upper
            # if ((self._bidirectional and
            #             abs(self.load_port.flow) > self._max_supply
            #                 + self.storage.flow_limit_upper)
            #         or ((not self._bidirectional) and
            #             abs(self.load_port.flow)
            #                 > self.storage.flow_limit_upper)):
            if abs(self.load_port.flow) > sink_power:
                logger = logging.getLogger('energy_logger')
                logger.warning('Warning: Recuperation power %.2f exceeds available '
                               'sink power %.2f' %
                               (abs(self.load_port.flow.energy_ref),
                                sink_power.energy_ref))
                # raise ValueError('Recuperation power exceeds available '
                #                  'sink power')

            if abs(self.load_port.flow) <= self.storage.flow_limit_upper:
                # Recuperation power can be handled by storage
                self.flow_load_to_storage = abs(self.load_port.flow)
            else:
                # Recuperation power is higher than storage flow limit -
                # remaining power either has to go back to interface or
                # through braking resistance
                self.flow_load_to_storage = self.storage.flow_limit_upper

            self.flow_storage_to_load = EnergyFlow.from_energy_ref(
                self.storage.medium, 0)

            self.flow_load_to_interface = abs(self.load_port.flow) \
                                          - self.flow_load_to_storage

            self.flow_interface_to_load = EnergyFlow.from_energy_ref(
                self.storage.medium, 0)

            # Maximum power available for charging storage:
            self.flow_interface_to_storage_max = self.storage.flow_limit_upper \
                                                 - self.flow_load_to_storage

            if self.flow_interface_to_storage_max <= self._max_supply:
                self.flow_interface_to_storage \
                    = self.flow_interface_to_storage_max
            else:
                self.flow_interface_to_storage = self._max_supply

        # Update interface port (ChargingFacilities will use this port):
        self.interface_port.flow = \
            self.flow_interface_to_load + self.flow_interface_to_storage \
            - self.flow_load_to_interface

        # Net flow to/from storage (>0: consumption; <0: charging)
        self.charge_port.flow = self.flow_storage_to_load \
                                - (self.flow_load_to_storage
                                + self.flow_interface_to_storage)

        # print('t = %d: Charge flow = %.1f kW' % (self.env.now, self.charge_port.flow.energy_ref))
        self.state_change_event()  # notify other objects

        # Save information required for next integration step
        self._last_update = self.env.now
        self._last_load_flow = self.load_port.flow
        self._last_interface_flow = self.interface_port.flow
        self._last_interface_to_storage_flow = self.flow_interface_to_storage

    # def _stop_charging(self, sender):
    #     print('t = %d: fully_charged_event() issued' % self.env.now)
    #     self._update(self)
        # if self.storage.is_full():
        #     # self.charger.flow =
        #     self.charger.flow =
    #     EnergyFlow.from_energy_ref(self.storage.medium,0)
        #     print('t = %d: Charge flow = %.1f kW' % (self.env.now,
        #                                              self.charger.flow.energy_ref))
        #     self.state_change_event()  # notify other objects
        # If negative, flows have changed before the fully_charged_event was
        # fired. Do nothing!


class EnergyStorage:
    def __init__(self, env, medium, energy_nominal, energy_init,
                 flow_limit_lower, flow_limit_upper, discharge_efficiency=1,
                 charge_efficiency=1, ID=None):
        self.env = env
        self.medium = medium  # EnergyMedium
        self.energy_nominal = energy_nominal  # Energy
        # EnergyFlow; must be negative (discharge limit)
        self._flow_limit_lower_abs = flow_limit_lower
        # EnergyFlow; must be positive (charge limit)
        self._flow_limit_upper_abs = flow_limit_upper
        self.energy = energy_init  # Energy
        self.discharge_efficiency = discharge_efficiency  # 0...1 (1: 100%)
        self.charge_efficiency = charge_efficiency  # 0...1 (1: 100%)
        self.port = Port(self.medium)
        self.port.state_change_event.add(self._update)
        self.fully_charged_event = eflips.events.EventHandler(self)
        self.force_update_event = eflips.events.EventHandler(self)
        self.force_update_event.add(self._update)
        self.action = None
        self.soc_was_valid = self.soc_valid
        self.soc_was_critical = self.soc_critical
        self._calc_flow()
        self._ID = ID

    @property
    def energy_max(self):
        return self.energy_nominal

    @property
    def energy_remaining(self):
        """Effective amount of energy usable by vehicle at the current state
        of charge."""
        return self.energy

    def is_full(self):
        return 0.99999 * self.energy_max < self.energy < 1.00001 * self.energy_max
        # return (self.energy > 0.99 * self.energy_max
        #         and self.energy < 1.01 * self.energy_max)

    @property
    def flow_limit_lower(self):
        return self._flow_limit_lower_abs

    @property
    def flow_limit_upper(self):
        if self.is_full():
            return EnergyFlow.from_energy_ref(self.medium, 0)
        else:
            return self._flow_limit_upper_abs

    @property
    def soc(self):
        return self.energy / self.energy_max

    @property
    def soc_valid(self):
        # This only checks for negative SoC because overcharging is prevented
        # by the model.
        # Expected to be overridden by subclasses that define different
        # SoC validity ranges!
        if self.energy.energy_ref < 0:
            return False
        else:
            return True

    @property
    def soc_critical(self):
        # This method is expected to be overridden by subclasses that actually
        # define a critical charging state
        return not self.soc_valid

    @property
    def id(self):
        return self._ID

    def _calc_flow(self):
        """refresh energy flow (< 0: consumption, > 0: charging) and adjust
        charging/discharging limit"""
        self._flow = (-1) * self.port.flow
        self.last_update = self.env.now
        #
        # # Trigger event to prevent overcharging.
        # # Beware: State changes may occur BEFORE time_until_full has passed!
        # # It is therefore important that listeners to fully_charged_event()
        # # check if EnergyStorage really is full before shutting off charging.
        # # See ChargeController.
        # if self._flow.energy_ref > 0:
        #     time_until_full = (self.energy_max.energy_ref
        #                        - self.energy.energy_ref) * 3600 \
        #                       / self._flow.energy_ref  # s
        #     if time_until_full >= 0:
        #         self.action = self.env.process(
        #             self._check_fully_charged(time_until_full))

    def _schedule_update(self, duration):
        yield self.env.timeout(duration)
        self.force_update_event()
        # self._update(self)
        # if self.is_full():
        #     if global_constants['DEBUG_MSGS']:
        #         print('t = %d: Energy storage fully charged' % self.env.now)
        #         self.fully_charged_event()

    def _charge(self, duration):
        """Charge (or discharge) the specified amount. Over- and undercharging
        protection must be implemented in superordinate methods!"""
        energy_charged = self._flow.integrate(duration)
        if energy_charged.energy_ref >= 0:
            energy_charged = energy_charged * self.charge_efficiency
        else:
            energy_charged = energy_charged / self.discharge_efficiency
        self.energy += energy_charged
        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): %s charged %.2f kWh in %d s, '
                     'new capacity: %.2f kWh' %
                     (self.env.now, hms_str(self.env.now),
                      self.__class__.__name__,
                      energy_charged.energy_ref,
                      duration,
                      self.energy.energy_ref))
        return energy_charged

    def _update(self, sender):
        """integrate flow over time interval passed; recalculate flow"""

        duration = self.env.now - self.last_update
        energy_charged = self._charge(duration)
        self._calc_flow()
        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): %s updating flow' % (
                self.env.now, hms_str(self.env.now),
                self.__class__.__name__))
        if not self.soc_valid:
            self.soc_was_valid = False
            if not global_constants['ALLOW_INVALID_SOC']:
                raise RuntimeError('Invalid charging state')
        if self.soc_critical:
            self.soc_was_critical = True

        # Trigger event to prevent overcharging.
        # Beware: State changes may occur BEFORE time_until_full has passed!
        # It is therefore important that listeners to fully_charged_event()
        # check if EnergyStorage really is full before shutting off charging.
        # See ChargeController.
        if self._flow.energy_ref > 0:
            time_until_full = (self.energy_max.energy_ref  # s
                               - self.energy.energy_ref) * 3600 \
                              / self._flow.energy_ref / self.charge_efficiency
            # Force an update every minute to be able to review the SoC during
            # charging. If the storage is full before then, update accordingly.
            if time_until_full > 0:
                # If 'FORCE_UPDATES_WHILE_CHARGING' global option is enabled,
                # force an update at regular intervals to be able to monitor
                # the SoC while charging.
                if global_constants['FORCE_UPDATES_WHILE_CHARGING']:
                    if time_until_full < \
                            global_constants['CHARGING_UPDATE_INTERVAL']:
                        schedule_fully_charged_event = True
                    else:
                        schedule_fully_charged_event = False
                        self.action = self.env.process(
                            self._schedule_update(
                                global_constants['CHARGING_UPDATE_INTERVAL']))
                else:
                    schedule_fully_charged_event = True

                if schedule_fully_charged_event:
                    logger = logging.getLogger('energy_logger')
                    logger.debug(
                        ' t = %d (%s): Storage %s will be fully '
                        'charged in %.2f s; '
                        'scheduling update event at t = %d'
                        % (self.env.now, hms_str(self.env.now),
                           self.__class__.__name__,
                           time_until_full, self.env.now + time_until_full))
                    self.action = self.env.process(
                        self._schedule_update(time_until_full))

        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): Net flow to storage %s = %.1f kW' %
                     (self.env.now, hms_str(self.env.now),
                      self.__class__.__name__, self._flow.energy_ref))

        if energy_charged.energy_ref > 0 and self.is_full():
            logger = logging.getLogger('energy_logger')
            logger.debug(' t = %d (%s): Energy storage %s fully charged' %
                         (self.env.now, hms_str(self.env.now),
                          self.__class__.__name__))
            # self.fully_charged_event.succeed()
            self.fully_charged_event()


    # def _update(self, sender):
    #     """integrate flow over time interval passed; recalculate flow"""
    #     duration = self.env.now - self.last_update
    #     energy_charged = self._charge(duration)
    #     self._calc_flow()
    #
    #     if not self.soc_valid:
    #         self.soc_was_valid = False
    #         if not global_constants['ALLOW_INVALID_SOC']:
    #             raise RuntimeError('Invalid charging state')
    #     if self.soc_critical:
    #         self.soc_was_critical = True
    #
    #     # Trigger event to prevent overcharging.
    #     # Beware: State changes may occur BEFORE time_until_full has passed!
    #     # It is therefore important that listeners to fully_charged_event()
    #     # check if EnergyStorage really is full before shutting off charging.
    #     # See ChargeController.
    #     if self._flow.energy_ref > 0:
    #         # Rounding was introduced to prevent triggering fully_charged_event
    #         # multiple times within the same timestep:
    #         # time_until_full = math.floor((self.energy_max.energy_ref
    #         #                    - self.energy.energy_ref) * 3600 \
    #         #                   / self._flow.energy_ref)  # s
    #         time_until_full = (self.energy_max.energy_ref
    #                            - self.energy.energy_ref) * 3600 \
    #                           / self._flow.energy_ref  # s
    #         if time_until_full > 0:
    #             # if time_until_full > 0:
    #             logger = logging.getLogger('energy_logger')
    #             logger.debug(' t = %d: Storage %s will be fully charged in %.2f s; '
    #                          'scheduling update event at t = %d'
    #                          % (self.env.now, self.__class__.__name__,
    #                             time_until_full, self.env.now + time_until_full))
    #             self.action = self.env.process(
    #                 self._schedule_update(time_until_full))
    #
    #     logger = logging.getLogger('energy_logger')
    #     logger.debug(' t = %d: Net flow to storage %s = %.1f kW' %
    #               (self.env.now, self.__class__.__name__, self._flow.energy_ref))
    #
    #     if energy_charged.energy_ref > 0 and self.is_full():
    #         logger = logging.getLogger('energy_logger')
    #         logger.debug(' t = %d: Energy storage %s fully charged' % (self.env.now, self.__class__.__name__))
    #         # self.fully_charged_event.succeed()
    #         self.fully_charged_event()

    @property
    def discharge_reserve(self):
        """Return discharge reserve (< 0)"""
        if self._flow > self.flow_limit_lower:
            return self.flow_limit_lower - self._flow
        else:
            return EnergyFlow.from_energy_ref(self.medium, 0)

    @property
    def charge_reserve(self):
        """Return charge reserve (> 0)"""
        if self._flow < self.flow_limit_upper:
            return self.flow_limit_upper - self._flow
        else:
            return EnergyFlow.from_energy_ref(self.medium, 0)


class Battery(EnergyStorage):
    def __init__(self, env, energy_nominal, soc_reserve, soc_min,
                 soc_max, soc_init, soh, discharge_rate, charge_rate,
                 discharge_efficiency=1, charge_efficiency=1, ID=None):
        medium = Fuels.electricity
        self.soc_reserve = soc_reserve  # 0...1, expected to be > soc_min
        self.soc_min = soc_min  # 0...1
        self.soc_max = soc_max  # 0...1
        self.soh = soh  # 0...1
        self.discharge_rate = discharge_rate  # C rate (>0)
        self.charge_rate = charge_rate  # C rate (>0)
        flow_limit_lower = EnergyFlow.from_energy_ref(
            medium,
            energy_nominal.energy_ref * (-1) * self.discharge_rate)
        flow_limit_upper = EnergyFlow.from_energy_ref(
            medium,
            energy_nominal.energy_ref * self.charge_rate)
        energy_init = soc_init * energy_nominal * soh
        super().__init__(env, medium, energy_nominal, energy_init,
                         flow_limit_lower, flow_limit_upper,
                         discharge_efficiency, charge_efficiency, ID)

    @property
    def soc(self):
        return self.energy / self.energy_real

    @property
    def energy_real(self):
        return self.energy_nominal * self.soh

    @property
    def energy_max(self):
        return self.energy_real * self.soc_max

    @property
    def energy_min(self):
        return self.energy_real * self.soc_min

    @property
    def energy_remaining(self):
        """Effective amount of energy usable by vehicle at the current state
        of charge."""
        return self.energy - self.energy_min

    @property
    def energy_reserve(self):
        return self.energy_real * self.soc_reserve

    @property
    def soc_valid(self):
        if self.soc < self.soc_min:
            return False
        else:
            return True

    @property
    def soc_critical(self):
        if self.soc < self.soc_reserve:
            return True
        else:
            return False


class DieselTank(EnergyStorage):
    def __init__(self, env, energy_nominal, energy_init):
        medium = Fuels.diesel

        # Set flow limits to 1 L/s (very high, shouldn't cause problems):
        flow_limit_lower = EnergyFlow.from_volume_ref(medium, -1)
        flow_limit_upper = EnergyFlow.from_volume_ref(medium, 1)

        super().__init__(env, medium, energy_nominal, energy_init,
                         flow_limit_lower, flow_limit_upper)


class EnergySubSystem:
    """An energy subsystem consisting of a storage and one or more loads (ports)
    connected to it."""
    def __init__(self, vehicle, env, storage, dict_of_load_ports,
                 list_of_charging_interfaces):
        self.env = env
        self.storage = storage
        self.medium = storage.medium
        self.loads = MultiPort(self.medium,
                               list_of_in_ports=list(
                                   dict_of_load_ports.values()))
        self.interfaces = list_of_charging_interfaces

        # ugly: no checking if storage actually has attribute 'port'
        self.controller = ChargeController(vehicle, env, self.medium,
                                           self.loads.out_port,
                                           list_of_charging_interfaces,
                                           self.storage)

        # Charging handler process will be stored here so that it can be
        # interrupted:
        self.charging_handler_proc = None


class ChargingInterfaceType:
    def __init__(self, name, medium, dynamic, max_flow,
                 dead_time_dock, dead_time_undock, **kwargs):
        """
        Create new charging interface type.
        :param name: String describing the interface (e.g. 'Pantograph')
        :param medium: EnergyMedium object
        :param dynamic: Whether the interface can charge in-motion or not
            (boolean)
        :param max_flow: Maximum energy flow (EnergyFlow object)
        :param dead_time_dock: Dead time docking (float)
        :param dead_time_undock: Dead time undocking (float)
        :param kwargs:
            max_flow_stationary: EnergyFlow object. If the interface is dynamic,
                restrict energy flow to this value when vehicle is stationary.
                Defaults to max_flow.
            dynamic_dock: Interface can dock while in motion (boolean).
                Default: False.
            dynamic_undock: Interface can undock while in motion (boolean).
                Default: False.
            bidirectional: Interface can feed power back to grid (boolean).
                Default: False.

        max_flow_stationary, dynamic_dock and dynamic_undock are without
        effect if interface is not dynamic.
        """
        self.name = name
        self.medium = medium  # EnergyMedium
        self.dynamic = dynamic

        # dead times are specified in the default wall_time unit
        self.dead_time_dock = dead_time_dock * Units.wall_time.factor
        self.dead_time_undock = dead_time_undock * Units.wall_time.factor

        set_default_kwargs(self, kwargs, {'bidirectional': False})

        if dynamic:
            # assign parameters for dynamic interface
            self.max_flow_in_motion = max_flow
            arg_defaults = {'max_flow_stationary': max_flow,
                            'dynamic_dock': False,
                            'dynamic_undock': False}
            set_default_kwargs(self, kwargs, arg_defaults)
        else:
            # assign parameters for stationary interface
            if 'max_flow_stationary' in kwargs:
                logger = logging.getLogger('energy_logger')
                logger.warning('Warning: Ignoring keyword argument max_flow_stationary '
                      'for stationary charging interface')
            self.max_flow_in_motion = EnergyFlow.from_energy_ref(medium, 0)
            self.max_flow_stationary = max_flow

            if 'dynamic_dock' in kwargs:
                logger = logging.getLogger('energy_logger')
                logger.warning('Warning: Ignoring keyword argument dynamic_dock '
                      'for stationary charging interface')
            self.dynamic_dock = False

            if 'dynamic_undock' in kwargs:
                logger = logging.getLogger('energy_logger')
                logger.warning('Warning: Ignoring keyword argument dynamic_undock '
                      'for stationary charging interface')
            self.dynamic_undock = False


class ChargingInterfaceTypes:
    pantograph = ChargingInterfaceType(
        'Stationary pantograph 450 kW',
        Fuels.electricity,
        False,
        EnergyFlow.from_energy_ref(Fuels.electricity, 450*0.95),
        15,
        15,
        bidirectional=True
    )

    pantograph_300 = ChargingInterfaceType(
        'Stationary pantograph 300 kW',
        Fuels.electricity,
        False,
        EnergyFlow.from_energy_ref(Fuels.electricity, 300*0.95),
        15,
        15,
        bidirectional=True
    )

    pantograph_450 = ChargingInterfaceType(
        'Stationary pantograph 450 kW',
        Fuels.electricity,
        False,
        EnergyFlow.from_energy_ref(Fuels.electricity, 450*0.95),
        15,
        15,
        bidirectional=True
    )

    plug = ChargingInterfaceType(
        'Manual plug',
        Fuels.electricity,
        False,
        EnergyFlow.from_energy_ref(Fuels.electricity, 150*0.95),
        60,
        60,
        bidirectional=True
    )

    plug_60 = ChargingInterfaceType(
        'Manual plug',
        Fuels.electricity,
        False,
        EnergyFlow.from_energy_ref(Fuels.electricity, 60*0.95),
        60,
        60,
        bidirectional=True
    )

    trolley = ChargingInterfaceType(
        'Trolley current collector',
        Fuels.electricity,
        True,
        EnergyFlow.from_energy_ref(Fuels.electricity, 600),
        10,
        10,
        max_flow_stationary=EnergyFlow.from_energy_ref(Fuels.electricity, 50),
        dynamic_dock=False,
        dynamic_undock=False,
        bidirectional=True
    )

    train_pantograph = ChargingInterfaceType(
        'train current collector',
        Fuels.electricity,
        True,
        EnergyFlow.from_energy_ref(Fuels.electricity, 2000),
        10,
        10,
        max_flow_stationary=EnergyFlow.from_energy_ref(Fuels.electricity, 1200),
        dynamic_dock=True,
        dynamic_undock=True,
        bidirectional=True
    )


class ChargingInterface:
    def __init__(self, env, interface_type):
        self.env = env
        self.interface_type = interface_type
        self._connected_to = None
        self._is_docked = False
        self.port = Port(interface_type.medium)
        self.connect_event = eflips.events.EventHandler(self)
        self.disconnect_event = eflips.events.EventHandler(self)

    def dock(self):
        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): Docking interface %s' %
                     (self.env.now, hms_str(self.env.now),
                      self.interface_type.name))
        yield self.env.timeout(self.interface_type.dead_time_dock)
        self._is_docked = True

    def undock(self):
        logger = logging.getLogger('energy_logger')
        logger.debug(' t = %d (%s): Undocking interface %s' %
                     (self.env.now, hms_str(self.env.now),
                      self.interface_type.name))
        self._is_docked = False
        yield self.env.timeout(self.interface_type.dead_time_undock)

    def connect(self, charging_facility):
        if self._connected_to is not None:
            logger = logging.getLogger('energy_logger')
            logger.debug('RuntimeError: Tried to connect to charging facility'
                         'without prior disconnect from other facility.')
            raise RuntimeError('Tried to connect to charging facility '
                               'without prior disconnect from other facility.')
        self._connected_to = charging_facility
        self.connect_event()

    def disconnect(self):
        self._connected_to = None
        self.disconnect_event()

    @property
    def connected_to(self):
        return self._connected_to

    # @connected_to.setter
    # def connected_to(self, value):
    #     self._connected_to = value
    #     if value is None:
    #         self.disconnect_event()
    #     else:
    #         self.connect_event()

    @property
    def is_connected(self):
        return True if self.connected_to is not None else False

    @property
    def is_docked(self):
        return self._is_docked
