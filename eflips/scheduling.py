# -*- coding: utf-8 -*-
import copy
import logging
from eflips.schedule import ScheduleContainer, Schedule, ScheduleNode,\
    TripNode, LegNode, SegmentNode, trip_info_str_header, trip_info_str,\
    schedule_info_str_header, schedule_info_str
from eflips.grid import GridSegment
from eflips import osm
from math import ceil
from collections import deque

def generate_osm_cache():
    """Generate an empty OSM cache dict to be used to store OSM requests
    offline.
    """
    osmcache = {'osm_places': {},
                'openroute_distance': {}}
    return osmcache

def generate_schedules_singledepot(timetable, grid, params,
                                   osm_cache_data):
    """

    :param timetable: A TimeTable object
    :param grid: a Grid object
    :param params: A dict of the following form:

        params = {
            'charging_point_names': {
                # Charging point names can either be specified as one large
                # list - then, all charging stations will be used by all
                # lines - or as a dict of lists with the respective line
                # numbers as keys. This way, each line may charge only at the
                # specified stations.
                '171': ['U Hermannplatz', 'U Hermannplatz/Urbanstr.'],
                'M11': ['S Schöneweide/Sterndamm', 'U Dahlem-Dorf'],
                'X07': ['U Rudow'],
                'X11': ['S Schöneweide/Sterndamm', 'U Krumme Lanke', 'Busseallee'],
                'X69': ['Köthener Str.', 'Neuer Weg'],
                '165': ['Müggelschlößchenweg', 'U Märkisches Museum'],
                '166': ['S Schöneweide/Sterndamm', 'Weisestr.'],
                '169': ['Odernheimer Str.', 'U Elsterwerdaer Platz'],
                '260': ['U Rudow'],
                '269': ['Alte Försterei', 'U Kaulsdorf-Nord'],
                'N65': ['Müggelschlößchenweg', 'S Hackescher Markt']
            },
            'scheduling_params': {
                'depot_gridpoint_id': 103129450,
                'min_pause_duration': 4*60,  # s
                'max_pause_duration': 45*60,  # s
                'max_deadheading_duration': 45*60,  # s
                'use_static_range': True,
                'default_depot_trip_distance': 5,  # km
                'default_depot_trip_velocity': 25,  # km/h
                'default_deadhead_trip_distance': 5,  # km
                'default_deadhead_trip_velocity': 25,  # km/h
                'deadheading': True,
                'mix_lines_at_stop': False,
                'mix_lines_deadheading': True,
                'add_delays': True,
                'delay_mode': 'all' | 'charging_only' | 'selected_only',
                'delayed_trip_ids': None | list of trip IDs
                'delay_threshold': 3*60   # s
            },
            'vehicle_params': {
                'EN': {
                    'capacity': 300 * 0.8 * 0.8 - 5,  # kWh
                    'static_range': 130,  # km
                    'traction_consumption': 0.88,  # kWh/km
                    'aux_power_driving': 2 + 7.59,  # kW (Solaris EN, -10/17°C)
                    'aux_power_pausing': 2,  # kW
                    'charge_power': 150 * 0.95,  # kW
                    'reduce_charge_time': 0,  # irrelevant
                    'dead_time': 120  # s
                },
                'GN': {
                    'capacity': 174*0.9*0.85 - 5,  # kWh
                    'static_range': float('inf'),  # km
                    'traction_consumption': 1.22,  # kWh/km
                    'aux_power_driving': 3+11.38,  # kW
                    'aux_power_pausing': 3,  # kW
                    'charge_power': 450*0.95,  # kW
                    'reduce_charge_time': 0,
                    'dead_time': 30  # s
                }
            }
        }

        The dict in 'charging_point_names' may be replaced by a list of
        charging point names if charging at any station is desired for all
        lines.

        If 'add_delays' is True, delays will be added to the minimum dwell
        time at each terminus according to the following modes:
            'all': Add delays after every trip.
            'charging_only': Add delays only after trips ending at a charging
                             station.
            'selected_only': Only add delays to trips whose IDs are supplied
                             in 'delayed_trip_ids'
        Note: If 'charging_only' is selected, 'delayed_trip_ids' is
        evaluated nevertheless!

        'delay_threshold' can be used to consider delays only above a certain
        threshold. This works as follows:
        minimum dwell time after trip = max(0, delay - threshold)
        Required charging time is then added to dwell time if applicable.

    :param osm_cache_data: Dict with OSM cache data. It will be updated during
        scheduling. Allows a DictProxy to be passed to enable multicore
        scheduling.
    :return:
    """
    logger = logging.getLogger('scheduling_logger')
    timetable.sort_by_departure()
    unprocessed_trips = timetable.get_all(copy_objects=True)

    # add charging attribute to trips
    for trip_node in unprocessed_trips:
        trip_node.charge = False

    # Make a copy of grid so that we don't modify the original one
    grid = copy.copy(grid)

    depot_grid_point = grid.get_point(params['scheduling_params']
                                      ['depot_gridpoint_id'])
    next_deadhead_trip_id = 0
    depot_trip_segments = {}
    schedule_list = []
    schedule_id = 0
    while len(unprocessed_trips) > 0:
        # Gather vehicle and line information for new schedule:
        first_passenger_trip = unprocessed_trips[0]

        # Set pause to zero (temporary - should be handled by timetable
        # generation):
        first_passenger_trip.children[-1].pause = 0

        vehicle_type = first_passenger_trip.vehicle_type
        line = first_passenger_trip.line

        # Start new schedule with a depot trip
        schedule_node = ScheduleNode(schedule_id, vehicle_type)

        logger.debug('Number of trips currently remaining in timetable: %d'
                     % len(unprocessed_trips))
        logger.debug('Starting new schedule %d' % schedule_id)

        schedule_node.add_node(first_passenger_trip)
        unprocessed_trips.remove(first_passenger_trip)

        schedule_node, depot_trip_segments, next_deadhead_trip_id = \
            _add_deadhead_trip(schedule_node, line, depot_grid_point,
                               'start', grid, depot_trip_segments,
                               next_deadhead_trip_id, params,
                               osm_cache_data)
        logger.debug('Schedule %d: Pull-out trip and first passenger '
                     'trip added:' % schedule_id
                     + '\n' + trip_info_str_header() + '\n' +
                     trip_info_str(schedule_node.children[0]) + '\n' +
                     trip_info_str(schedule_node.children[1]))

        while True:
            capacity, capacity_min, cons_total_driving, cons_total, \
                    spec_cons_driving, spec_cons_total = \
                _capacity(schedule_node, params)
            schedule_distance = schedule_node.distance
            logger.debug('Schedule %d: Distance %.1f km; '
                         'Capacity: %.1f; min. capacity: %.1f; '
                         'Consumption driving/total: %.1f/%.1f; '
                         'Specific cons. driving/total: %.2f/%.2f' %
                         (schedule_id, schedule_distance, capacity,
                          capacity_min, cons_total_driving, cons_total,
                          spec_cons_driving, spec_cons_total))

            if params['scheduling_params']['use_static_range'] is True \
                    and schedule_distance > params['vehicle_params']\
                    [vehicle_type]['static_range']:
                # Max. schedule distance exceeded, finish schedule
                logger.debug('Schedule %d: Static range constraint '
                             'exceeded. Finishing schedule' % schedule_id)
                break
            if capacity_min < 0:
                # Critical SoC exceeded, finish schedule
                logger.debug('Schedule %d: SoC critical. Finishing '
                             'schedule' % schedule_id)
                break

            # Get current trip:
            current_trip = schedule_node.children[-1]
            current_location = current_trip.destination
            current_line = current_trip.line

            # This is ugly. For pull-in trips, the same calculation
            # has already been performed in create_deadhead_trip()!
            # Check if we can charge at destination; set minimum dwell
            # time (pause duration):
            if len(schedule_node.children) == 1:
                # Pause duration is already correctly determined by
                # create_deadhead_trip()
                min_departure_time = copy.copy(current_trip.arrival)
                min_departure_time.addSeconds(current_trip.pause)
            else:
                # Set pause duration to zero (otherwise charging time
                # calculation will fail):
                # current_trip.children[-1].pause = 0

                # Pause has yet to be determined (currently set to zero)
                min_pause_duration_trip = \
                    params['scheduling_params']['min_pause_duration']

                if _charging_possible(current_location, current_line,
                                      params):
                    current_trip.charge = True
                    charge_duration = _charge_duration(schedule_node, params)
                else:
                    charge_duration = 0

                # Determine earlierst possible departure time:
                min_departure_time = copy.copy(current_trip.arrival)
                add_delay_here = False
                if params['scheduling_params']['add_delays'] == True:
                    # In any case, consider delays contained in
                    # 'delayed_trip_ids':
                    if params['scheduling_params']['delayed_trip_ids']\
                            is not None and current_trip.ID in\
                            params['scheduling_params']['delayed_trip_ids']:
                        add_delay_here = True
                    # All delays:
                    if params['scheduling_params']['delay_mode'] == 'all':
                        add_delay_here = True
                    # Only when charging:
                    if params['scheduling_params']['delay_mode'] ==\
                            'charging_only' and current_trip.charge == True:
                        add_delay_here = True
                    # Only selected trips (this is already taken care of
                    # through the first if clause; only for readability):
                    if params['scheduling_params']['delay_mode'] ==\
                            'selected_only':
                        pass

                if add_delay_here == True:
                    # Only add actual delays, ignore overpunctual arrivals
                    min_departure_time.addSeconds(
                        max(current_trip.delay - params['scheduling_params']\
                            ['delay_threshold'], 0))

                min_departure_time.addSeconds(max(min_pause_duration_trip,
                                                  charge_duration))

                logger.debug('Schedule %d: Min. charge duration: %.1f min; min. pause '
                      'duration: %.1f min (at %s)' %
                      (schedule_id, charge_duration/60,
                       min_pause_duration_trip/60, current_location.name))

            logger.debug('Schedule %d: Next possible departure from %s: %s' %
                  (schedule_id, current_location.name,
                   min_departure_time.toString()))

            # Find next matching trip from destination:
            if params['scheduling_params']['mix_lines_at_stop']:
                next_line = 'all'
            else:
                next_line = line

            next_trip = _find_next_trip(unprocessed_trips,
                                        current_location,
                                        min_departure_time,
                                        vehicle_type,
                                        next_line)
            if next_trip is None:
                # No more trips available; finish schedule
                logger.debug('Schedule %d: No more trips available '
                      'from location %s. Finishing schedule' %
                      (schedule_id, current_location.name))
                break

            # Check if trip exceeds maximum permitted dwell time:
            pause_duration = next_trip.departure - current_trip.arrival
            if pause_duration > \
                    params['scheduling_params']['max_pause_duration']:
                # Trip is too far in the future, and so will be all
                # other matching trips. Finish schedule
                break

            # If we have made it to here, the next trip is valid!
            # Set pause duration of current trip, and add next trip to
            # schedule:
            current_trip.children[-1].pause = pause_duration

            # Set pause to zero:
            next_trip.children[-1].pause = 0
            schedule_node.add_node(next_trip)

            logger.debug('Schedule %d: Passenger trip added:'
                         % schedule_id + '\n' +
                         trip_info_str_header() + '\n' +
                         trip_info_str(next_trip))

            # Remove trip from stack
            unprocessed_trips.remove(next_trip)

        # Finish schedule
        while True:
            if _count_passenger_trips(schedule_node) == 0:
                # Schedule contains no passenger trips; this means
                # the depot trip OR a combination of depot and passenger
                # trip is unserviceable. Raise error
                logger.error('Unserviceable trips in timetable, cannot '
                             'complete scheduling')
                raise ValueError('Unserviceable trips in timetable, cannot '
                                 'complete scheduling')

            # Get current trip (this should be the last passenger trip):
            current_trip = schedule_node.children[-1]
            line = current_trip.line

            # Set pause duration to zero (we currently don't want any
            # pause before returning to depot):
            current_trip.children[-1].pause = 0

            # Determine departure time for depot trip.
            # Later, we could perhaps check for charging possibility and
            # enable charging before returning to the depot
            departure = copy.copy(current_trip.arrival)
            departure.addSeconds(current_trip.children[-1].pause)

            # Create depot trip and add to schedule
            schedule_node, depot_trip_segments, next_deadhead_trip_id =\
                _add_deadhead_trip(schedule_node, line, depot_grid_point,
                                   'end', grid, depot_trip_segments,
                                   next_deadhead_trip_id, params,
                                   osm_cache_data)

            logger.debug('Schedule %d: Pull-in trip added:' % schedule_id
                         + '\n' + trip_info_str_header() + '\n' +
                         trip_info_str(schedule_node.children[-1]))

            capacity, capacity_min, cons_total_driving, cons_total, \
                    spec_cons_driving, spec_cons_total = \
                _capacity(schedule_node, params)
            schedule_distance = schedule_node.distance

            logger.debug('Schedule %d: Distance %.1f km; '
                         'Capacity: %.1f; min. capacity: %.1f; '
                         'Consumption driving/total: %.1f/%.1f; '
                         'Specific cons. driving/total: %.1f/%.1f' %
                         (schedule_id, schedule_distance, capacity, capacity_min,
                          cons_total_driving, cons_total,
                          spec_cons_driving, spec_cons_total))

            remove_last_trip = False

            if params['scheduling_params']['use_static_range'] is True \
                    and schedule_distance > params['vehicle_params']\
                    [vehicle_type]['static_range']:
                logger.debug(
                    'Schedule %d: Static range contraint exceeded. '
                    'Removing pull-in trip '
                    'and last passenger trip' % schedule_id)
                remove_last_trip = True

            if capacity_min < 0:
                logger.debug('Schedule %d: SoC critical. Removing pull-in trip '
                      'and last passenger trip' % schedule_id)
                remove_last_trip = True

            if remove_last_trip:
                # Remove depot trip...
                schedule_node.pop_last_node()

                #  ...and last passenger trip, adding it back to the stack:
                passenger_trip = schedule_node.pop_last_node()
                unprocessed_trips.append(passenger_trip)

                logger.debug('Schedule %d: Trip removed and re-added to '
                             'timetable:' % schedule_id + '\n' +
                             trip_info_str_header() + '\n' +
                             trip_info_str(passenger_trip))

                # Make sure stack is sorted by departure:
                unprocessed_trips = \
                    _sort_by_departure(unprocessed_trips)
            else:
                # Schedule is complete!
                logger.debug('Schedule %d complete! Distance = %d' %
                      (schedule_id, schedule_node.distance))
                break

        schedule_list.append(Schedule(schedule_node))

        # increase counter for next schedule
        schedule_id += 1

    # Set of schedules without deadheading between passenger trips is now
    # complete. We will now try to connect schedules through deadhead trips
    # to avoid unnecessary trips to the depot.
    if params['scheduling_params']['deadheading']:
        # List of schedules left in their original state, i.e. not
        # joined with other schedules:
        original_schedules = copy.copy(schedule_list)

        # List of newly created schedules:
        new_schedules = []

        # Create a stack of all schedules and sort by arrival time of
        # last passenger trip, asscending
        unprocessed_schedules = deque(sorted(
            copy.copy(original_schedules),
            key=lambda schedule: _last_arrival_time(schedule)))

        while len(unprocessed_schedules) > 0:
            # Take first schedule from unprocessed_schedules
            schedule1 = unprocessed_schedules.popleft()
            vehicle_type = schedule1.root_node.vehicle_type

            # Create new stack from original schedules, sorted by
            # departure time of first passenger trip, ascending
            connecting_schedules = deque(sorted(
                copy.copy(original_schedules),
                key=lambda schedule: _first_departure_time(schedule)))

            save = False
            while len(connecting_schedules) > 0:
                concat = False
                schedule2 = connecting_schedules.popleft()
                new_schedule, depot_trip_segments, next_deadhead_trip_id = \
                    _concatenate_schedules(schedule1, schedule2, grid,
                                           depot_trip_segments,
                                           next_deadhead_trip_id, params,
                                           osm_cache_data)
                if new_schedule is not None:
                    logger.debug('Trying to concatenate schedules:\n'
                                 + schedule_info_str_header() + '\n'
                                 + schedule_info_str(schedule1) + '\n'
                                 + schedule_info_str(schedule2) + '\n')
                    capacity, capacity_min, cons_total_driving, cons_total, \
                            spec_cons_driving, spec_cons_total = \
                        _capacity(new_schedule.root_node, params)
                    schedule_distance = new_schedule.root_node.distance

                    logger.debug(
                        'Schedule %d: Distance %.1f km; Capacity: %.1f; '
                        'min. capacity: %.1f; '
                        'Consumption driving/total: %.1f/%.1f; '
                        'Specific cons. driving/total: %.1f/%.1f' %
                        (new_schedule.root_node.ID,
                         new_schedule.root_node.distance,
                         capacity, capacity_min,
                         cons_total_driving, cons_total,
                         spec_cons_driving, spec_cons_total))

                    if capacity_min >= 0:
                        concat = True

                    if params['scheduling_params']['use_static_range'] \
                            is True and \
                            schedule_distance > params['vehicle_params']\
                            [vehicle_type]['static_range']:
                        concat = False

                    if concat:
                        save = True
                        if schedule1 in original_schedules:
                            original_schedules.remove(schedule1)
                        if schedule2 in original_schedules:
                            original_schedules.remove(schedule2)
                        if schedule2 in unprocessed_schedules:
                            unprocessed_schedules.remove(schedule2)
                        schedule1 = new_schedule
                        logger.debug('Concatenation successful! New schedule:'
                                     + '\n' + schedule_info_str_header()
                                     + '\n' + schedule_info_str(schedule1)
                                     + '\n')
                    else:
                        logger.debug('Concatenation not possible, '
                                     'SoC critical')
            if save:
                logger.debug('No more connecting schedules left. Saving new schedule:\n'
                             + schedule_info_str_header() + '\n'
                             + schedule_info_str(schedule1) + '\n')
                new_schedules.append(schedule1)

        save_schedules = sorted(original_schedules + new_schedules,
                                key=lambda schedule:
                                schedule.root_node.departure)

    else:
        save_schedules = sorted(schedule_list,
                                key=lambda schedule:
                                schedule.root_node.departure)

    # ---------------------------------------------------------------------

    # Update grid to include new depot trip segments
    for segment in depot_trip_segments.values():
        grid.add_segment(segment)

    # Re-number schedules:
    schedule_id = 0
    for schedule in save_schedules:
        schedule.root_node.ID = schedule_id
        schedule_id += 1

    # Put all schedules into a ScheduleContainer and return
    return grid, ScheduleContainer(save_schedules)

def _capacity(schedule_node, params):
    """Return the minimum capacity encountered during schedule."""
    logger = logging.getLogger('scheduling_logger')
    vehicle_type = schedule_node.vehicle_type
    capacity_nom = params['vehicle_params'][vehicle_type]['capacity']  # e.g. kWh
    charge_power = params['vehicle_params'][vehicle_type]['charge_power']  # e.g. kW
    dead_time = params['vehicle_params'][vehicle_type]['dead_time']
    traction_consumption = \
        params['vehicle_params'][vehicle_type]['traction_consumption']  # e.g. kWh/km
    aux_power_driving = \
        params['vehicle_params'][vehicle_type]['aux_power_driving']  # e.g. kW
    aux_power_pausing = \
        params['vehicle_params'][vehicle_type]['aux_power_pausing']  # e.g. kW

    capacity_max = capacity_nom
    capacity = capacity_nom
    capacity_min = capacity
    cons_total_driving = 0
    cons_total_pausing = 0
    distance_total = 0
    # logger.debug('Determining capacity for schedule %s (before/after pause):'
    #              % schedule_node.ID)
    for i, trip_node in enumerate(schedule_node.children):
        add_delay_here = False
        if params['scheduling_params']['add_delays'] == True:
            # In any case, consider delays contained in
            # 'delayed_trip_ids':
            if params['scheduling_params']['delayed_trip_ids'] \
                    is not None and trip_node.ID in \
                    params['scheduling_params']['delayed_trip_ids']:
                add_delay_here = True
            # All delays:
            if params['scheduling_params']['delay_mode'] == 'all':
                add_delay_here = True
            # Only when charging:
            if params['scheduling_params']['delay_mode'] == \
                    'charging_only' and trip_node.charge == True:
                add_delay_here = True
            # Only selected trips (this is already taken care of
            # through the first if clause; only for readability):
            if params['scheduling_params']['delay_mode'] == \
                    'selected_only':
                pass

        if add_delay_here == True:
            # Only positive delays:
            delay = max(trip_node.delay - params['scheduling_params']\
                        ['delay_threshold'], 0)
        else:
            delay = 0
        time_driving = trip_node.duration + delay \
                       - trip_node.pause
        # The last trip in the schedule hs not been assigned a pause
        # duration at this point, it is zero. Avoid negative pause
        # durations:
        time_pausing = max(trip_node.pause - delay, 0)

        # Determine capacity before pause
        cons_driving = trip_node.distance * traction_consumption \
                       + time_driving / 3600 * aux_power_driving

        cons_total_driving += cons_driving
        distance_total += trip_node.distance

        capacity -= cons_driving

        # Update minimum capacity
        if capacity < capacity_min:
            capacity_min = capacity

        capacity_before_pause = capacity

        # Determine capacity after pause
        # Consumption:
        cons_pausing = time_pausing / 3600 * aux_power_pausing

        # Energy charged:
        if trip_node.charge and time_pausing > dead_time:
            max_energy_charged = (time_pausing - dead_time) / 3600 \
                                 * charge_power
        else:
            max_energy_charged = 0

        cons_total_pausing += cons_pausing

        # Determine capacity after pause:
        capacity = min(capacity_max,
                       capacity - cons_pausing + max_energy_charged)

        # logger.debug('Trip %d (ID %d): %.1f / %.1f' %
        #              (i, trip_node.ID, capacity_before_pause, capacity))

        # Update minimum capacity
        if capacity < capacity_min:
            capacity_min = capacity

    cons_total = cons_total_driving + cons_total_pausing
    if distance_total == 0:
        spec_cons_driving = 0
        spec_cons_total = 0
    else:
        spec_cons_driving = cons_total_driving/distance_total
        spec_cons_total = cons_total / distance_total

    # logger.debug('Total consumption driving: %.1f\n' % cons_total_driving
    #              + 'Specific consumption driving: %.1f\n' % spec_cons_driving
    #              + 'Total consumption: %.1f' % cons_total)


    return (capacity, capacity_min, cons_total_driving, cons_total,
            spec_cons_driving, spec_cons_total)

def capacity_timeseries(schedule_node, params):
    """Return a time series of storage capacity. Useful for debugging."""
    time = []
    capacity = []
    time_before_pause = []
    capacity_before_pause = []
    time_after_pause = []
    capacity_after_pause = []

    # Initialise
    time.append(schedule_node.children[0].departure)
    capacity.append(params['vehicle_params'][schedule_node.vehicle_type]['capacity'])

    for i, trip_node in enumerate(schedule_node.children):
        sched = copy.deepcopy(schedule_node)
        sched.children = deque(list(schedule_node.children)[0:i+1])

        # Get capacity before pause
        pause = sched.children[-1].children[-1].pause
        sched.children[-1].children[-1].pause = 0
        arrival = copy.copy(trip_node.arrival)
        add_delay_here = False
        if params['scheduling_params']['add_delays'] == True:
            # In any case, consider delays contained in
            # 'delayed_trip_ids':
            if params['scheduling_params']['delayed_trip_ids'] \
                    is not None and trip_node.ID in \
                    params['scheduling_params']['delayed_trip_ids']:
                add_delay_here = True
            # All delays:
            if params['scheduling_params']['delay_mode'] == 'all':
                add_delay_here = True
            # Only when charging:
            if params['scheduling_params']['delay_mode'] == \
                    'charging_only' and trip_node.charge == True:
                add_delay_here = True
            # Only selected trips (this is already taken care of
            # through the first if clause; only for readability):
            if params['scheduling_params']['delay_mode'] == \
                    'selected_only':
                pass
        if add_delay_here == True:
            arrival.addSeconds(max(0, trip_node.delay
                                   - params['scheduling_params']\
                                   ['delay_threshold']))
        time.append(arrival)
        cap = _capacity(sched, params)[0]
        capacity.append(cap)
        time_before_pause.append(arrival)
        capacity_before_pause.append(cap)

        # Get capacity after pause
        if pause > 0:
            sched.children[-1].children[-1].pause = pause
            departure = copy.copy(trip_node.arrival)
            # Departure time does not change regardless of delay (?)
            departure.addSeconds(pause)
            time.append(departure)
            cap = _capacity(sched, params)[0]
            capacity.append(cap)
            time_after_pause.append(departure)
            capacity_after_pause.append(cap)

    return time, capacity, time_before_pause, capacity_before_pause, \
           time_after_pause, capacity_after_pause

def _charge_duration(schedule_node, params):
    """Return the duration required for a full charge at the current
    SoC."""
    capacity, capacity_min, cons_total_driving, cons_total, \
            spec_cons_driving, spec_cons_total = \
        _capacity(schedule_node, params)
    vehicle_type = schedule_node.vehicle_type
    aux_power_pausing = \
        params['vehicle_params'][vehicle_type]['aux_power_pausing']  # e.g. kW
    capacity_nom = params['vehicle_params'][vehicle_type]['capacity']  # e.g. kWh
    reduce_charge_time = params['vehicle_params'][vehicle_type]\
        ['reduce_charge_time']
    capacity_max = capacity_nom

    charge_power = params['vehicle_params'][vehicle_type]['charge_power']  # e.g. kW
    charge_duration = ((capacity_max-capacity) / (charge_power-aux_power_pausing)
                      *3600
                      + params['vehicle_params'][vehicle_type]['dead_time']) \
                      * (1-reduce_charge_time)
    return ceil(charge_duration)

def _add_deadhead_trip(schedule_node, line, connecting_grid_point,
                       where, grid, depot_trip_segments, next_deadhead_trip_id,
                       params, osm_cache_data):
    vehicle_type = schedule_node.vehicle_type

    if where == 'start':
        origin = connecting_grid_point
        destination = schedule_node.origin
        departure_time = copy.copy(schedule_node.departure)
    elif where == 'end':
        origin = schedule_node.destination
        destination = connecting_grid_point
        departure_time = copy.copy(schedule_node.arrival)
    else:
        raise ValueError('Unknown argument: where = %s' % where)

    grid_segment, depot_trip_segments = \
        _get_deadhead_segment(origin, destination, grid,
                              depot_trip_segments, params,
                              osm_cache_data)

    distance = grid_segment.distance

    # Round duration to full minutes. If we don't do this, we get weird
    # results when finding the next trip because comparison of "equal"
    # timestamps fails.
    duration = ceil(distance / params['scheduling_params']
                    ['default_deadhead_trip_velocity'] * 60) * 60

    trip_node = TripNode(None, next_deadhead_trip_id, 'empty',
                         vehicle_type=vehicle_type, line=line,
                         charge=False)
    next_deadhead_trip_id += 1
    leg_node = LegNode(trip_node, 0, departure_time, 0)
    SegmentNode(leg_node, grid_segment, duration)

    if where == 'start':
        # If we can charge at destination, create temporary schedule
        # to calculate charging time
        if _charging_possible(destination, line, params):
            # Create a temporary ScheduleNode to allow for charging time
            # calculation:
            schedule_node_temp = ScheduleNode(0, vehicle_type)
            schedule_node_temp.add_node(trip_node)

            # Determine required charging time, rounded to full minutes
            trip_node.charge = True
            pause = ceil(_charge_duration(schedule_node_temp, params)/60) * 60
        else:
            pause = 0
        departure_time.subSeconds(duration+pause)
        trip_node.children[-1].pause = pause
    elif where == 'end':
        preceding_trip = schedule_node.children[-1]
        # If we can charge, calculate charging time for given schedule
        if _charging_possible(origin, line, params):
            # Set pause duration of last trip to zero, otherwise
            # charging time calculation will fail:
            preceding_trip.children[-1].pause = 0

            # Determine required charging time
            pause = ceil(_charge_duration(schedule_node, params)/60) * 60
            preceding_trip.charge = True
        else:
            pause = 0

        add_delay_here = False
        if params['scheduling_params']['add_delays'] == True:
            # In any case, consider delays contained in
            # 'delayed_trip_ids':
            if params['scheduling_params']['delayed_trip_ids'] \
                    is not None and preceding_trip.ID in \
                    params['scheduling_params']['delayed_trip_ids']:
                add_delay_here = True
            # All delays:
            if params['scheduling_params']['delay_mode'] == 'all':
                add_delay_here = True
            # Only when charging:
            if params['scheduling_params']['delay_mode'] == \
                    'charging_only' and preceding_trip.charge == True:
                add_delay_here = True
            # Only selected trips (this is already taken care of
            # through the first if clause; only for readability):
            if params['scheduling_params']['delay_mode'] == \
                    'selected_only':
                pass

        if add_delay_here == True:
            # Only add actual delays, ignore overpunctual arrivals
            pause += max(preceding_trip.delay - params['scheduling_params']\
                         ['delay_threshold'], 0)

        departure_time.addSeconds(pause)

        # Add pause to last schedule leg:
        preceding_trip.children[-1].pause = pause

    if where == 'start':
        schedule_node.add_node(trip_node, where='left')
    elif where == 'end':
        schedule_node.add_node(trip_node, where='right')

    return schedule_node, depot_trip_segments, next_deadhead_trip_id

def _get_deadhead_segment(origin, destination, grid, depot_trip_segments,
                          params, osm_cache_data):
    grid_segment = grid.get_shortest_segment(origin, destination,
                                             compare_name=False)
    if grid_segment is None:
        # Segment not available in grid; check in list of newly constructed
        # segments. If we don't find it there, create a new segment.
        if (origin, destination) in depot_trip_segments:
            grid_segment = depot_trip_segments[(origin, destination)]
        else:
            distance = osm.get_distance_between_gridpoints(
                origin, destination, osm_cache_data,
                get_missing_coords_from_osm=
                params['scheduling_params']['get_missing_coords_from_osm'])
            logger = logging.getLogger("schedule_logger")
            if distance is None:
                if params['scheduling_params']\
                        ['fill_missing_distances_with_default']:
                    logger.warning('Could not determine distance between '
                                   '%s and %s. Setting default distance'
                                   % (origin.name, destination.name))
                    distance = params['scheduling_params']\
                        ['default_deadhead_trip_distance']
                else:
                    logger.error('Could not determine distance between '
                                 '%s and %s'
                                 % (origin.name, destination.name))
                    raise ValueError('Could not determine distance between '
                                     '%s and %s.'
                                     % (origin.name, destination.name))
            segment_id = int(str(origin.ID) + str(destination.ID))
            segment_name = str(origin.ID) + '_' + str(destination.ID)
            grid_segment = GridSegment(segment_id,
                                       origin, destination, distance,
                                       name=segment_name)
            logger.debug("%s > %s: %4.2f", origin.name, destination.name,
                         distance)
            depot_trip_segments.update(
                {(origin, destination): grid_segment})
    return grid_segment, depot_trip_segments

def _find_next_trip(trip_node_list, location, departure_time,
                   vehicle_type, line):
    # trip_node_list is expected to be sorted by departure!
    # ToDo: Find out why comparing location against trip_node.origin
    # does not work
    next_trip = None
    for trip_node in trip_node_list:
        if (trip_node.departure >= departure_time and
                trip_node.origin.name == location.name and
                trip_node.vehicle_type == vehicle_type):
            if line == 'all':
                next_trip = trip_node
                break
            else:
                if trip_node.line == line:
                    next_trip = trip_node
                    break
    return next_trip

def _concatenate_schedules(schedule1, schedule2, grid, depot_trip_segments,
                           next_deadhead_trip_id, params, osm_cache_data):
    vehicle_type = schedule1.root_node.vehicle_type
    if not vehicle_type == schedule2.root_node.vehicle_type:
        return None, depot_trip_segments, next_deadhead_trip_id

    # Determine origin and destination of last/first passenger trip.
    # If, for whatever reason, multiple deadhead trips occur, this will
    # be handled correctly.
    origin = None
    destination = None
    for trip_node in reversed(schedule1.root_node.children):
        if trip_node.trip_type == 'passenger':
            origin = trip_node.destination
            arrival = trip_node.arrival
            line1 = trip_node.line
            if trip_node.charge:
                charge_time = trip_node.pause
            else:
                charge_time = 0
            break

    for trip_node in schedule2.root_node.children:
        if trip_node.trip_type == 'passenger':
            destination = trip_node.origin
            departure = trip_node.departure
            line2 = trip_node.line
            break

    if not params['scheduling_params']['mix_lines_deadheading']:
        # Lines must match. If they don't, we can stop here:
        if line1 != line2:
            return None, depot_trip_segments, next_deadhead_trip_id

    if origin is None or destination is None:
        # This should, in theory, be checked after generating the schedules,
        # not here!
        raise ValueError('One of the schedules to be concatenated does not '
                         'contain any passenger trips!')

    if origin.name != destination.name:
        create_deadhead = True
    else:
        create_deadhead = False

    if not params['scheduling_params']['deadheading'] and create_deadhead:
        # Schedules do not share the same location, but deadheading is
        # disabled: No concatenation possible
        return None, depot_trip_segments, next_deadhead_trip_id

    # Determine time available
    time_available = departure.getSeconds() - arrival.getSeconds()\
                     - charge_time

    if time_available < 0 or time_available > params['scheduling_params']\
            ['max_deadheading_duration']:
        return None, depot_trip_segments, next_deadhead_trip_id

    # If we have got this far, there is a chance the two schedules
    # can be connected. We will now check if we can deadhead between
    # the two schedules within the available time window.
    # Create a copy of each schedule:
    schedule1_copy = copy.copy(schedule1)
    schedule2_copy = copy.copy(schedule2)

    # Start by removing the existing deadhead trips from the end of
    # schedule 1 and from the beginning of schedule 2:
    for trip_node in reversed(
            schedule1_copy.root_node.children.copy()):
        if trip_node.trip_type == 'empty':
            schedule1_copy.root_node.children.remove(trip_node)
        elif trip_node.trip_type == 'passenger':
            # Stop here to avoid deleting all but the last deadhead trips
            break
    for trip_node in schedule2_copy.root_node.children.copy():
        if trip_node.trip_type == 'empty':
            schedule2_copy.root_node.children.remove(trip_node)
        elif trip_node.trip_type == 'passenger':
            # Stop here to avoid deleting all but the first deadhead trips
            break

    if create_deadhead:
        # Assign line of the succeeding schedule
        line = schedule2_copy.root_node.children[0].line
        schedule_node, depot_trip_segments, next_deadhead_trip_id =\
            _add_deadhead_trip(schedule1_copy.root_node, line, destination,
                               'end', grid, depot_trip_segments,
                               next_deadhead_trip_id, params,
                               osm_cache_data)
        schedule1_copy.root_node = schedule_node
        # Earliest departure is the end of the pause after the deadhead
        # trip:
        min_departure = copy.copy(schedule1_copy.root_node.arrival)
        min_departure.addSeconds(
            schedule1_copy.root_node.children[-1].pause)
        if min_departure > schedule2_copy.root_node.departure:
            # Deadhead trip takes too long; no concatenation possible
            return None, depot_trip_segments, next_deadhead_trip_id

        # If schedule2 begins after the pause, set correct pause duration
        # for schedule 1:
        pause = schedule2_copy.root_node.departure \
                - schedule1_copy.root_node.children[-1].departure \
                - schedule1_copy.root_node.children[-1].duration
        schedule1_copy.root_node.children[-1].children[-1].pause = pause
    else:
        # No deadhead trip; wait until schedule2 begins:
        schedule1_copy.root_node.children[-1].children[-1].pause = \
            departure.getSeconds() - arrival.getSeconds()

    # Join schedules:
    schedule1_copy.root_node.join(schedule2_copy.root_node)
    return schedule1_copy, depot_trip_segments, next_deadhead_trip_id

def _count_passenger_trips(schedule_node):
    res = 0
    for trip_node in schedule_node.children:
        if trip_node.trip_type == 'passenger':
            res += 1
    return res

def _sort_by_departure(trip_node_list):
    return sorted(trip_node_list, key=lambda trip_node: trip_node.departure)

def _last_arrival_time(schedule):
    """Return arrival time of last passenger trip."""
    ok = False
    for trip_node in reversed(schedule.root_node.children):
        if trip_node.trip_type == 'passenger':
            ok = True
            break
    if not ok:
        raise ValueError('No passenger trip found in schedule')
    else:
        return trip_node.arrival

def _first_departure_time(schedule):
    """Return departure time of first passenger trip."""
    ok = False
    for trip_node in schedule.root_node.children:
        if trip_node.trip_type == 'passenger':
            ok = True
            break
    if not ok:
        raise ValueError('No passenger trip found in schedule')
    else:
        return trip_node.departure

def _charging_possible(location, line, params):
    res = False
    if isinstance(params['charging_point_names'], list):
        if location.name in params['charging_point_names']:
            res = True
    elif isinstance(params['charging_point_names'], dict):
        if line in params['charging_point_names'] and \
                location.name in params['charging_point_names'][line]:
            res = True
    else:
        raise TypeError('charging_point_names must be of type list or dict')
    return res