# -*- coding: utf-8 -*-
import logging
import copy
from eflips import osm
from eflips.io import import_json


class GridPoint:
    """A class describing a grid point, e.g. a bus stop, a train station, or
    a depot.

    Application-specific implementations may subclass from this class and add,
    for example, geographic data or operator-specific information. Information
    on charging infrastructure should NOT be put into this class as we want to
    keep the geographic grid separate from the charging infrastructure.
    """

    def __init__(self, ID, name, point_type, elevation=0, **kwargs):
        """Create new a GridPoint object. Arguments:

        ID: Any unique identifier, preferably an integer.
        name: String containing a (preferably) human-readable name.
        type_: A string defining a type, e.g. 'stop', 'depot'  etc.
        elevation: Elevation in m
        """
        self.ID = ID
        self.name = name
        self.type_ = point_type
        self.elevation = elevation

        for key, value in kwargs.items():
            setattr(self, key, value)

    # This causes an error in scheduling ('Unhashable type GridPoint')
    # def __eq__(self, other):
    #     return self.ID == other.ID

    def to_string(self):
        string = "id: %d\nname: %s" % (self.ID, self.name)
        if hasattr(self, "short_name"):
            string += "\nshort_name: %s" % self.short_name
        if hasattr(self, "group"):
            string += "\ngroup: %s" % self.group
        return string


class GridSegment:
    """A grid segment is a connection between two grid points with a specified
    distance. Different ways to travel between the same two points are
    represented by two different segments.
    """

    def __init__(self, ID, origin, destination, distance,
                 type_='route_segment', name=None, **kwargs):
        """Create a new RouteSegment object. Arguments:

        ID: Any unique identifier, preferably an integer.

        origin, destination: GridPoint objects defining start and end
                             of the segment.

        distance: Distance in km.

        type: A string defining a type, e.g. 'route_segment'
        """
        self.ID = ID
        self.origin = origin
        self.destination = destination
        if name is None:
            self.name = '%s_%s' % (self.origin.ID, self.destination.ID)
        else:
            self.name = name
        self.type_ = type_
        self.distance = distance

        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def gradient(self):
        if self.distance != 0:
            return self.elevation_diff/(self.distance*1000)
        else:
            return 0

    @property
    def elevation_diff(self):
        if hasattr(self.origin, 'elevation') and \
                hasattr(self.destination, 'elevation'):
            return self.destination.elevation - self.origin.elevation
        else:
            return 0


class Grid:
    """A grid consisting of unique points and segments."""
    def __init__(self):
        """Creates a new, empty Grid object."""
        self._points = dict()
        self._segments = dict()

    def __copy__(self):
        """This tells the copy.copy() function to include shallow copies of
        the points and segments list. The original GridPoint and GridSegment
        objects in these lists will be retained."""
        new_obj = Grid()
        new_obj._points = copy.copy(self._points)
        new_obj._segments = copy.copy(self._segments)
        return new_obj

    def _update_point(self, grid_point):
        """Internal method to add a grid point."""
        if grid_point.ID in self._points:
            # That ID exists already, issue a warning:
            logger = logging.getLogger('grid_logger')
            logger.warning('Grid point with ID %s (%s) already exists. '
                           'Overwriting' % (grid_point.ID, grid_point.name))
        self._points.update({grid_point.ID: grid_point})

    def add_point(self, grid_points):
        """Add a GridPoint object or a list of GridPoint objects to the grid.

        The type-checking method is probably not pythonic, need to find an
        alternative.
        """
        if type(grid_points) is list:
            for point in grid_points:
                self._update_point(point)
        else:
            self._update_point(grid_points)

    def get_point(self, ID):
        """Retrieve a grid point by its ID."""
        return self._points[ID]

    def get_all_points_by_ID(self):
        return self._points

    def get_all_segments_by_ID(self):
        return self._segments

    def contains_point_id(self, ID):
        return ID in self._points.keys()

    def contains_point(self, point):
        return point in self._points.values()

    def contains_segment(self, segment):
        return segment in self._segments.values()

    def contains_segment_id(self, ID):
        return ID in self._segments.keys()

    def create_segment(self, ID, origin, destination, distance=None,
                       type_='route_segment', name=None, **kwargs):
        """Create a new route segment linking two grid points. Note that
        origin and destination are specified by their ID and not their
        GridPoint objects."""
        if ID in self._segments:
            logger = logging.getLogger('grid_logger')
            logger.warning('segment with ID %s already exists. Overwriting.'
                           % ID)
            # overwrite?!
        if origin in self._points and destination in self._points:
            if distance is None:
                distance = osm.get_open_route_distance(origin.name, destination.name)
            new_segment = GridSegment(ID, self._points[origin],
                                      self._points[destination],
                                      distance, type_, name, **kwargs)
            self._segments.update({ID: new_segment})
            return new_segment
        else:
            logger = logging.getLogger('grid_logger')
            logger.error('Error locating grid points for route segment '
                         '%s with origin_id %s and dest_id %s'
                         % (ID, origin, destination))
            raise ValueError('Error locating grid points for route segment'
                             ' %s with origin_id %s and dest_id %s'
                             % (ID, origin, destination))

    def create_segment_osm(self, ID, origin, destination, cachedata, distance=None,
                       type_='route_segment', name=None, **kwargs):
        """Create a new route segment linking two grid points. Note that
        origin and destination are specified by their ID and not their
        GridPoint objects."""
        if ID in self._segments:
            logger = logging.getLogger('grid_logger')
            logger.warning('segment with ID %s already exists. Overwriting.'
                           % ID)
        if origin.ID in self._points and destination.ID in self._points:
            if distance is None:
                distance = osm.get_distance_between_gridpoints(origin, destination, cachedata)
            new_segment = GridSegment(ID, self._points[origin.ID],
                                      self._points[destination.ID],
                                      distance, type_, name, **kwargs)
            self._segments.update({ID: new_segment})
            return new_segment
        else:
            logger = logging.getLogger('grid_logger')
            logger.error('Error locating grid points for route segment '
                         '%s with origin_id %s and dest_id %s'
                         % (ID, origin, destination))
            raise ValueError('Error locating grid points for route segment'
                             ' %s with origin_id %s and dest_id %s'
                             % (ID, origin, destination))

    def add_segment(self, segment):
        """Add a segment created elsewhere"""
        if segment.ID in self._segments:
            raise ValueError('Segment ID %s already exists in grid' %
                             segment.ID)
        self._segments.update({segment.ID: segment})

    def get_segment(self, ID):
        """Retrieve a route segment by its ID."""
        return self._segments[ID]

    def find_points(self, attribute, value):
        return self.find(self._points, attribute, value)

    def find_segments(self, attribute, value):
        return self.find(self._segments, attribute, value)

    def get_shortest_segment(self, point_a, point_b, compare_name=False):
        """
        :param point_a: GridPoint object
        :param point_b: GridPoint object
        :param compare_name: Identify grid points by their 'name' and 'group'
               attributes instead of the actual GridPoint objects. This enables
               finding segments between points with different IDs, but (more or
               less) identical geographical lócus. Grid points are assumed to
               belong together only if they share the same 'group' attribute,
               i.e. multiple grid points with the same name, but different
               locations may exist.
        :return: segment between point_a and point_b with shortest distance
        new segment if no segment existed
        """
        res_segment = None
        current_distance = float('inf')
        if compare_name:
            for segment in self._segments.values():
                if segment.origin.name == point_a.name and segment.destination.name == point_b.name \
                        and segment.origin.group == point_a.group and segment.destination.group == point_b.group \
                        and segment.distance < current_distance:
                    current_distance = segment.distance
                    res_segment = segment
        else:
            for segment in self._segments.values():
                if segment.origin == point_a and segment.destination == point_b \
                        and segment.distance < current_distance:
                    current_distance = segment.distance
                    res_segment = segment

        # note: i would not do this.
        # it could result in bugs if a method called get_segment manipulates the grid
        # if res_segment is None:
        #     grid_segment_id = int(str(point_a.ID) + str(point_b.ID))
        #     distance = 0 # TODO @issue 108
        #     res_segment = GridSegment(grid_segment_id, point_a, point_b, distance, type_='route_segment')
        #     self.add_segment(res_segment)

        return res_segment

    def add_coordinates(self, json_file, overwrite=False):
        """Add geographical information to gridpoints as supplied in JSON file.
        If overwrite=True, existing coords attribute in GridPoints will
        be overwritten; if not, they will be kept."""
        coord_data = import_json(json_file)
        edited_points = []

        for point in self._points.values():
            if not hasattr(point, 'coords') or overwrite:
                try:
                    if point.name in coord_data['by_name']:
                        point_data = coord_data['by_name'][point.name]
                    elif point.group in coord_data['by_group']:
                        point_data = coord_data['by_group'][point.group]
                    elif str(point.ID) in coord_data['by_id']:
                        point_data = coord_data['by_id'][point.ID]
                    else:
                        continue
                except AttributeError:
                    continue
                edited_point = False
                if 'coords' in point_data:
                    point.coords = point_data['coords']
                    edited_point = True
                if 'osm_req_str' in point_data:
                    point.osm_req_str = point_data['osm_req_str']
                    edited_point = True
                if edited_point:
                    edited_points.append(point)

        return edited_points

    @staticmethod
    def find(obj_dict, attribute, value):
        res = []
        for id, obj in obj_dict.items():
            if getattr(obj, attribute) == value:
                res.append(obj)
        return res
