import requests
import json
import logging
import time
from eflips import misc
from eflips import io
from math import ceil
from eflips.settings import global_constants


class MapRequestError(Exception):
    pass


def get_distance_between_gridpoints(origin, destination, cachedata,
                                    get_missing_coords_from_osm=True):
    """Get distance between two GridPoints using a car routing application
    (openrouteservice)."""
    logger = logging.getLogger('map_request_logger')
    logger.debug('Fetching distance for ' + origin.name + ' > '
                 + destination.name + '.\n'
                 + 'Origin GridPoint:\n' + origin.to_string() + '\n'
                 + 'Destination GridPoint:\n' + destination.to_string() + '\n')

    points_dict = {'origin': origin,
                   'destination': destination}

    coords_dict = {'origin': None,
                   'destination': None}

    # Get coordinates
    for name, point in points_dict.items():
        if hasattr(point, 'coords'):
            # Use coordinates supplied in GridPoint
            coords_dict[name] = _coords_dict_to_tuple(point.coords)
            logger.debug('Using coordinates supplied in GridPoint '
                         + point.name)
        else:
            # Get coordinates from OSM
            if get_missing_coords_from_osm:
                coords_dict[name] = get_coords(point, cachedata)
            else:
                logger.warning('Cannot get distance! No coordinates supplied '
                               'in GridPoint ' + point.name
                               + '. Add coordinates or call '
                               + 'with get_missing_coords_from_osm=True.')
                return None

    # Issue distance request
    distance = get_distance_between_coords(coords_dict['origin'],
                                           coords_dict['destination'],
                                           cachedata)
    return distance


def get_distance_between_all_gridpoints(list_of_gridpoints, cachedata,
                                        get_missing_coords_from_osm=True,
                                        max_size_per_request=50):
    """Download an entire distance matrix from openrouteservice and
    update cachedata."""
    logger = logging.getLogger('map_request_logger')

    # Compile list of coordinates
    list_of_coords = []
    for point in list_of_gridpoints:
        if hasattr(point, 'coords'):
            # Use coordinates supplied in GridPoint
            list_of_coords.append(_coords_dict_to_tuple(point.coords))
            logger.debug('Using coordinates supplied in GridPoint '
                         + point.name)
        else:
            # Get coordinates from OSM
            if get_missing_coords_from_osm:
                list_of_coords.append(get_coords(point, cachedata))
            else:
                msg = 'Cannot get distance matrix! No coordinates supplied ' \
                      + 'in GridPoint ' + point.name \
                      + '. Add coordinates or call ' \
                      + 'with get_missing_coords_from_osm=True.'
                logger.error(msg)
                raise ValueError(msg)

    # Create sub-matrices from list of gridpoints (build large OD matrix
    # from smaller tiles)
    num_points = len(list_of_gridpoints)
    num_increments = ceil(num_points/max_size_per_request)
    for i in range(0, num_increments):
        if i == num_increments - 1:
            origin_indices = list(range(i*max_size_per_request, num_points))
        else:
            origin_indices = list(range(i*max_size_per_request, (i+1)*max_size_per_request))
        for j in range(0, num_increments):
            if j == num_increments - 1:
                destination_indices = list(range(j*max_size_per_request, num_points))
            else:
                destination_indices = list(range(j*max_size_per_request, (j+1)*max_size_per_request))

            distance_matrix = get_distance_matrix_from_openrouteservice(
                list_of_coords, origin_indices=origin_indices,
                destination_indices=destination_indices
            )
            distance_dict = {}
            for k, row in enumerate(distance_matrix):
                for l, distance in enumerate(row):
                    origin_coords = list_of_coords[origin_indices[k]]
                    destination_coords = list_of_coords[destination_indices[l]]
                    distance_dict.update({(origin_coords, destination_coords): distance})
            cachedata['openroute_distance'].update(distance_dict)


def get_coords(grid_point, cachedata):
    """Get coordinates for a GridPoint from its osm_req_str or name
    attribute. First check local cache for a previous OSM request; if none is
    found, query OSM and save result to local cache.

    Warn if multiple results are found or if the results don't include
    a bus stop. If either of these occurs, return the first result so that
    the calling function is not aborted. If no result is found, raise an
    error."""
    logger = logging.getLogger('map_request_logger')

    if hasattr(grid_point, 'osm_req_str'):
        req_str = grid_point.osm_req_str
        logger.debug('Using osm request string \'' + req_str +
                     '\' supplied in GridPoint ' + grid_point.name)
    else:
        req_str = address_to_osm_request(grid_point.name)
        logger.debug('Using osm request string \'' + req_str +
                     '\' generated from GridPoint name ' + grid_point.name)

    # Load offline cache
    # cachedata = load_cache(cache_file_path)

    if req_str in cachedata['osm_places']:
        logger.debug('Found cached OSM request for \'' + req_str + '\'')
        # places contains the json output from OSM, i.e. a list of places:
        places = cachedata['osm_places'][req_str]
    else:
        logger.debug('Querying OSM for \'' + req_str + '\'')
        # places contains the json output from OSM, i.e. a list of places:
        places = find_places_in_osm(req_str)
        cachedata['osm_places'].update({req_str: places})

    if places is None:
        msg = 'No places found for request string \'' + req_str + '\'\n' \
            + 'GridPoint properties:\n' + grid_point.to_string() + '\n'
        logger.error(msg)
        raise MapRequestError(msg)

    i = 0
    bus_stop_coordinates = []
    for place in places:
        if place['type'] == 'bus_stop':
            bus_stop_coordinates.append((place['lon'], place['lat']))
            i += 1
    if i > 1:
        coords = bus_stop_coordinates[0]
        bus_stop_coordinates_string = \
            misc.list_to_string(bus_stop_coordinates, '; ',
                                lambda coord: str(coord[1]) + ', '
                                              + str(coord[0]))
        logger.warning('Found multiple bus stops for \'%s\' at these coordinates:\n%s\n'
                       'Using coordinates: %s\n'
                       'GridPoint properties:\n%s\n',
                       req_str, bus_stop_coordinates_string,
                       str(coords[1]) + ', ' + str(coords[0]),
                       grid_point.to_string())
    elif i == 1:
        coords = bus_stop_coordinates[0]
    elif i == 0:
        coords = (places[0]['lon'], places[0]['lat'])
        logger.warning('No bus stop at \'%s\' found.\n'
                       'Using coordinates: %s\n'
                       'GridPoint properties:\n%s\n',
                       req_str,
                       str(coords[1]) + ', ' + str(coords[0]),
                       grid_point.to_string())
    else:
        raise RuntimeError('Something went seriously wrong here.')

    # Update cache:
    # update_cache(cachedata, cache_file_path)
    return coords


def find_places_in_osm(req_str):
    """Return a list of places found in OpenStreetMap for an address string
    req_str, or None if there is no result."""
    logger = logging.getLogger('map_request_logger')
    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': req_str,
              'format': 'json'}
    headers = {'content-type': 'application/json'}

    request = requests.get(url=url, headers=headers, params=params)

    # max_time_limit = 5
    # first_req_time = time.time()
    while request.status_code != 200:
        logger.warning("Error retrieving " + req_str + ": "
                       + str(request.status_code) + " " + str(request.reason) + " " + request.text)
        logger.warning("Waiting 1 s for next request")
        time.sleep(1)
        request = requests.get(url=url, headers=headers, params=params)
    # while (request.status_code != 200 or request.text == "[]") and max_time_limit > time.time() - first_req_time:
    #     logger.warning("Error retrieving " + req_str + ": "
    #                    + str(request.status_code) + " " + str(request.reason) + " " + request.text)
    #     logger.warning("Waiting 1 s for next request")
    #     time.sleep(1)
    #     request = requests.get(url=url, headers=headers, params=params)

    if request.text == "[]":
        return None

    places = request.json()

    # Convert coordinates to float (OSM gives us strings):
    for place in places:
        place['lat'] = float(place['lat'])
        place['lon'] = float(place['lon'])
    return places


def address_to_osm_request(grid_point_name):
    point_address = grid_point_name

    point_address = point_address.replace("pl.", "platz")
    point_address = point_address.replace('/', ' ')
    point_address += " Berlin"

    return point_address


def get_distance_between_coords(coords_origin, coords_destination,
                                cachedata):
    """Get distance between two coordinate pairs. First check local cache
    for a previous request; if none is found, query openrouteservice and
    save result to local cache."""
    logger = logging.getLogger('map_request_logger')
    # cachedata = load_cache(cache_file_path)
    route_string = str(coords_origin[1]) + ', ' + str(coords_origin[0]) \
                   + ' > ' + str(coords_destination[1]) + ', ' \
                   + str(coords_destination[0])
    if (coords_origin, coords_destination) in cachedata['openroute_distance']:
        # Use distance found in cache
        distance = cachedata['openroute_distance']\
            [(coords_origin, coords_destination)]
        logger.debug('Found cached openroute distance for ' + route_string
                     + ': ' + str(distance))
    else:
        # Issue openrouteservice request. We get the return distance
        # for free, so we might as well write it to the cache too
        logger.debug('Querying openrouteservice for ' + route_string)
        distance, distance_return = \
            get_distance_from_openrouteservice(coords_origin,
                                               coords_destination)
        cachedata['openroute_distance'].update({
            (coords_origin, coords_destination): distance,
            (coords_destination, coords_origin): distance_return
        })
    # update_cache(cachedata, cache_file_path)
    return distance


def get_distance_from_openrouteservice(coords_origin, coords_destination):
    """Get distance between two coordinate pairs. Returns a tuple with
    outbound and return distances, i.e.
    (origin_to_destination, destination_to_origin)."""
    logger = logging.getLogger("map_request_logger")

    url = "https://api.openrouteservice.org/v2/matrix/driving-car"

    # get key your settings_file
    if global_constants["OSM_KEY"]:
        key = global_constants["OSM_KEY"]
    else:
        KeyError("OSM Key is missing. Provide key in your settings file.")

    headers = {'content-type': 'application/json',
               'Authorization': key}

    req_data = {'locations': [coords_origin, coords_destination],
                'metrics': ['distance'],
                'units': 'km'}
    req_json_data = json.dumps(req_data)

    request = requests.post(url=url, headers=headers, data=req_json_data)

    route_string = str(coords_origin[1]) + ', ' + str(coords_origin[0]) \
                   + ' > ' + str(coords_destination[1]) + ', ' \
                   + str(coords_destination[0])

    if request.status_code == 429:
        logger.warning("Error retrieving distance " + route_string
                       + "\nResponse: " + str(request.status_code) + " "
                       + str(request.reason) + "\n")
        logger.warning("Reached limit of 40 requests per minute. "
                       "Waiting 61 s for next request...")
        time.sleep(61)
        request = requests.post(url=url, headers=headers, data=req_json_data)
    elif request.status_code != 200:
        msg = "Error retrieving distance " + route_string + ": " \
              + str(request.status_code) + " " + str(request.reason) \
              + "\n"
        logger.error(msg)
        raise MapRequestError(msg)

    result = request.json()
    distance_outbound = result['distances'][0][1]
    distance_return = result['distances'][1][0]
    return (distance_outbound, distance_return)


def get_distance_matrix_from_openrouteservice(list_of_coords,
                                              origin_indices='all',
                                              destination_indices='all'):
    logger = logging.getLogger("map_request_logger")

    url = "https://api.openrouteservice.org/v2/matrix/driving-car"

    # get key your settings_file
    if global_constants["OSM_KEY"]:
        key = global_constants["OSM_KEY"]
    else:
        KeyError("OSM Key is missing. Provide key in your settings file.")

    headers = {'content-type': 'application/json',
               'Authorization': key}

    if origin_indices == 'all':
        origin_indices = list(range(0, len(list_of_coords)))
    if destination_indices == 'all':
        destination_indices = list(range(0, len(list_of_coords)))
    req_data = {'locations': list_of_coords,
                'sources': origin_indices,
                'destinations': destination_indices,
                'metrics': ['distance'],
                'units': 'km'}
    req_json_data = json.dumps(req_data)

    request = requests.post(url=url, headers=headers, data=req_json_data)

    # route_string = misc.list_to_string(list_of_coords, '; ')

    if request.status_code == 429:
        logger.warning("Error retrieving distance matrix"
                       + "\nResponse: " + str(request.status_code) + " "
                       + str(request.reason) + "\n")
        logger.warning("Reached limit of 40 requests per minute. "
                       "Waiting 61 s for next request...")
        time.sleep(61)
        request = requests.post(url=url, headers=headers, data=req_json_data)
    elif request.status_code != 200:
        msg = "Error retrieving distance matrix" + ": " \
              + str(request.status_code) + " " + str(request.reason) \
              + "\n"
        logger.error(msg)
        raise MapRequestError(msg)

    result = request.json()
    return result['distances']


def load_cache(cache_file_path):
    logger = logging.getLogger('map_request_logger')
    try:
        cachedata = io.import_pickle(cache_file_path)
    except (FileNotFoundError, EOFError):
        logger.warning('Could not find cache file at %s or file corrupted; '
                       'creating new, empty cache file.' % cache_file_path)
        cachedata = {'osm_places': {},
                     'openroute_distance': {}}
        io.export_pickle(cache_file_path, cachedata)
    return cachedata


def merge_osm_cache_files(input_file_list, output_file, replace_file=True):
    fields = ['osm_places', 'openroute_distance']
    cachedata_new = {}
    for field in fields:
        cachedata_new.update({field: {}})
    # cachedata_new = {'osm_places': {},
    #                  'openroute_distance': {}}

    for file in input_file_list:
        cachedata = io.import_pickle(file)
        for field in fields:
            for key, val in cachedata[field].items():
                if key not in cachedata_new[field]:
                    cachedata_new[field].update({key: val})

    io.export_pickle(output_file, cachedata_new, replace_file=replace_file)

def _coords_dict_to_tuple(coords_dict):
    """Convert a dict with 'lat' and 'lon' keys to (lon, lat) tuple"""
    return (coords_dict['lon'], coords_dict['lat'])