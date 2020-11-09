# -*- coding: utf-8 -*-
"""Demo script to construct a bus timetable for use by scheduling algorithm.
Illustrates how to build trips using the hierarchical data structures TripNode,
LegNode, SegmentNode and the TimeInfo time format.
"""
import eflips
import string
import os
import copy

# -----------------------------------------------------------------------------
# File paths
# -----------------------------------------------------------------------------

# Output will be placed in working directory; if desired, specify a different
# directory here:
output_path = os.getcwd()
timetable_filename = 'timetable.pickle'
timetable_text_file_name = 'timetable.txt'
plot_filename = 'timetable'

# -----------------------------------------------------------------------------
# Create a grid
# -----------------------------------------------------------------------------

# We will create a simple grid consisting of points named A through Z, and
# a depot. In reality, the grid would be generated from imported
# operators' data.

num_stops = 26
segment_distance = 0.6  # km
depot_trip_distance = 5  # km
average_velocity = 18  # km/h
segment_duration = 120  # s

grid = eflips.Grid()
stop_names = string.ascii_uppercase[0:num_stops]
point_id = 0
for i in range(num_stops):
    grid.add_point(eflips.GridPoint(point_id, stop_names[i], 'stop'))
    point_id += 1

# Add depot grid point
grid.add_point(eflips.GridPoint(point_id, 'Depot', 'depot'))
depot_id = point_id
point_id += 1

# Create segments A-B, B-C, ..., and reverse
segment_id = 0
segments_outbound = []
segments_return = []

for i in range(num_stops-1):
    origin_id = i
    destination_id = i + 1
    grid.create_segment(segment_id, origin_id, destination_id,
                        distance=segment_distance)
    segments_outbound.append(segment_id)
    segment_id += 1
    grid.create_segment(segment_id, destination_id, origin_id,
                        distance=segment_distance)
    segments_return.append(segment_id)
    segment_id += 1

# Create depot segments
for point_name in [stop_names[0], stop_names[-1]]:
    point_id = grid.find_points('name', point_name)[0].ID
    grid.create_segment(segment_id, depot_id, point_id,
                        distance=depot_trip_distance)
    segment_id += 1
    grid.create_segment(segment_id, point_id, depot_id,
                        distance=depot_trip_distance)
    segment_id += 1


# -----------------------------------------------------------------------------
# Create timetable
# -----------------------------------------------------------------------------

# We will create a simple timetable with a 20-minute headway and constant
# travel times throughout the day. In the morning and afternoon peak, the
# headway is shortened to 10 minutes.

first_departure = eflips.TimeInfo('Monday', 5*3600)
last_departure = eflips.TimeInfo('Monday', 23*3600)
peak_begin_morning = eflips.TimeInfo('Monday', 7*3600)
peak_end_morning = eflips.TimeInfo('Monday', 9*3600)
peak_begin_afternoon = eflips.TimeInfo('Monday', 16*3600)
peak_end_afternoon = eflips.TimeInfo('Monday', 18*3600)
headway_regular = 20 * 60
headway_peak = 10 * 60
vehicle_type = 'SB'
line = '100'
outbound_direction = 1
return_direction = 2

trip_list = []
trip_id = 0

# It is important to copy() TimeInfo objects if they are to be modified later!
# "current_time = first_departure" would create an object reference and
# modifying any of the two variables would modify the other one, too.
current_time = copy.copy(first_departure)
while current_time <= last_departure:
    # TripNode is instantiated without a parent.
    # Attributes 'vehicle_type' and 'direction' are optional, but vehicle_type
    # is later required for scheduling and direction is required for
    # plotting a graphical timetable.
    trip_outbound = eflips.TripNode(None, trip_id, 'passengerTrip',
                                     line=line,
                                     vehicle_type=vehicle_type,
                                     direction=outbound_direction)
    leg_id = 0
    leg_departure = copy.copy(current_time)
    for segment_id in segments_outbound:
        # LegNode is instantiated with trip_outbound as its parent;
        # it is automatically added to trip_outbound.children.
        # Same with SegmentNode.
        leg = eflips.LegNode(trip_outbound, leg_id, copy.copy(leg_departure), 0)
        eflips.SegmentNode(leg, grid.get_segment(segment_id),
                            segment_duration)
        leg_departure.addSeconds(segment_duration)
        leg_id += 1
    trip_list.append(trip_outbound)
    trip_id += 1

    trip_return = eflips.TripNode(None, trip_id, 'passengerTrip',
                                   line=line,
                                   vehicle_type=vehicle_type,
                                   direction=return_direction)
    leg_id = 0
    leg_departure = copy.copy(current_time)
    for segment_id in reversed(segments_return):
        leg = eflips.LegNode(trip_return, leg_id, copy.copy(leg_departure), 0)
        eflips.SegmentNode(leg, grid.get_segment(segment_id),
                            segment_duration)
        leg_departure.addSeconds(segment_duration)
        leg_id += 1
    trip_list.append(trip_return)
    trip_id += 1

    if (current_time >= peak_begin_morning and current_time < peak_end_morning) \
            or (current_time >= peak_begin_afternoon and
                current_time < peak_end_afternoon):
        current_time.addSeconds(headway_peak)
    else:
        current_time.addSeconds(headway_regular)

# Create TimeTable object and save as pickle
timetable = eflips.TimeTable(trip_list)
eflips.io.export_pickle(os.path.join(output_path, timetable_filename),
                         (grid, timetable))

# Export timetable as text file
timetable.export_text_file(os.path.join(output_path, timetable_text_file_name))

# Plot the trips as a graphical timetable
eflips.evaluation.plot_trips(trip_list, xlabel='Time (hours)',
                              ylabel='Stop', save=True, show=False,
                              filename=os.path.join(output_path,
                                                    plot_filename))
