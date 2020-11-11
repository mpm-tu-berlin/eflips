# -*- coding: utf-8 -*-
import eflips
import string
import os

# -----------------------------------------------------------------------------
# File paths
# -----------------------------------------------------------------------------

# Output will be placed in working directory; if desired, specify a different
# directory here:
output_path = os.path.join(os.getcwd(), 'output')
output_filename = 'very_simple_schedules.pickle'


# -----------------------------------------------------------------------------
# Create a grid
# -----------------------------------------------------------------------------

# We will create a simple geographic grid consisting of points named A through
# J, and a depot. In reality, the grid would be generated from imported
# operators' data.

num_stops = 10

grid = eflips.Grid()
stop_names = string.ascii_uppercase[0:num_stops]
id = 0
for i in range(0, num_stops):
    base_name = stop_names[i]
    for k in ['1', '2']:
        name = base_name + k
        point = eflips.GridPoint(id, name, 'stop', group=base_name)
        grid.add_point(point)
        id += 1

# Add depot grid point
grid.add_point(eflips.GridPoint(id, 'Depot', 'depot'))

# Create segments A1-B1-C1-..., H2-G2-F2-... with random distance
segment_list = ['A2']
for i in range(0, num_stops):
    segment_list.append(stop_names[i] + '1')
for i in range(num_stops-1, -1, -1):
    segment_list.append(stop_names[i] + '2')

small_distance = 0.1
large_distance = 0.8

id = 0
for i in range(0, len(segment_list)-1):
    origin_name = segment_list[i]
    origin_id = grid.find_points('name', origin_name)[0].ID
    destination_name = segment_list[i+1]
    destination_id = grid.find_points('name', destination_name)[0].ID
    if origin_name[0:1] == destination_name[0:1]:
        distance = small_distance
    else:
        distance = large_distance
    grid.create_segment(id, origin_id, destination_id,
                        distance=distance)
    id += 1

# Create segments for depot trip
depot_distance = 6  # km
depot_segments = [('Depot', 'A1'),
                  ('A2', 'Depot')]
for seg in depot_segments:
    origin_id = grid.find_points('name', seg[0])[0].ID
    destination_id = grid.find_points('name', seg[1])[0].ID
    grid.create_segment(id, origin_id, destination_id, distance=depot_distance)
    id += 1


# -----------------------------------------------------------------------------
# Create a list of vehicle schedules
# -----------------------------------------------------------------------------

# Generate a set of simple vehicle schedules. This would usually be imported
# from operators' data.

# Departure times of all trips are calculated based upon the first trip:
first_departure = eflips.TimeInfo('Monday', 4*3600)

# For now, we have only one vehicle type ('SB' - standard bus):
vehicle_type = 'SB'

num_schedules = 6  # i.e. x vehicles will be dispatched
interval = 600  # seconds between dispatches
num_round_trips_per_schedule = 3
pause_duration = 15*60  # pause at terminus
velocity = 18  # km/h

schedule_list = []

# Create list of trip relations for schedule:
trip_relations = []
trip_directions = []
trip_relations.append([('Depot', 'A1')])
trip_directions.append(0)
for i in range(0, num_round_trips_per_schedule):
    # outbound
    legs_in_trip = []
    if i > 0:
        legs_in_trip.append((stop_names[0] + '2', stop_names[0] + '1'))
    for j in range(0, len(stop_names)-1):
        origin_name = stop_names[j] + '1'
        destination_name = stop_names[j+1] + '1'
        legs_in_trip.append((origin_name, destination_name))
    trip_relations.append(legs_in_trip)
    trip_directions.append(1)

    # return
    legs_in_trip = []
    legs_in_trip.append((stop_names[-1] + '1', stop_names[-1] + '2'))
    for j in range(len(stop_names)-1, 0, -1):
        origin_name = stop_names[j] + '2'
        destination_name = stop_names[j-1] + '2'
        legs_in_trip.append((origin_name, destination_name))
    trip_relations.append(legs_in_trip)
    trip_directions.append(2)
trip_relations.append([('A2', 'Depot')])
trip_directions.append(0)
num_trips_in_schedule = len(trip_relations)

# Create tree structure for each schedule (consisting of ScheduleNode,
# TripNode, LegNode and SegmentNode objects):
schedule_id = 0
trip_id = 0
leg_id = 0
for i in range(num_schedules):
    departure_time = first_departure + i * interval
    schedule_node = eflips.ScheduleNode(i, vehicle_type)  # root node

    for j, trip in enumerate(trip_relations):
        if j == 0 or j == num_trips_in_schedule - 1:
            trip_type = 'empty'
        else:
            trip_type = 'passenger'

        if j == 0 or j == num_trips_in_schedule - 1 or j == num_trips_in_schedule - 2:
            pause = 0
        else:
            pause = pause_duration

        trip_node = eflips.TripNode(schedule_node, trip_id, trip_type,
                                     vehicle_type=vehicle_type,
                                     direction=trip_directions[j])
        trip_id += 1

        num_legs = len(trip)
        for k, (origin_name, destination_name) in enumerate(trip):
            if k == num_legs - 1:
                leg_pause = pause
            else:
                leg_pause = 0
            leg_node = eflips.LegNode(trip_node, leg_id, departure_time,
                                       leg_pause)
            leg_id += 1
            segment = grid.get_shortest_segment(
                grid.find_points('name', origin_name)[0],
                grid.find_points('name', destination_name)[0])
            duration = segment.distance / velocity * 3600  # seconds
            eflips.SegmentNode(leg_node, segment, duration)
            departure_time += duration + leg_pause

    schedule = eflips.Schedule(schedule_node)
    schedule_list.append(schedule)


# add random delays
min_delay_per_segment = -10
max_delay_per_segment = 30
schedule_list = eflips.schedule.add_random_delays(schedule_list,
                                                   min_delay_per_segment,
                                                   max_delay_per_segment)

# Create schedule container and save
schedules = eflips.ScheduleContainer(schedule_list)
eflips.io.export_pickle(os.path.join(output_path, output_filename),
                         (grid, schedules))
