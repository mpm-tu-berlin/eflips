# -*- coding: utf-8 -*-
from itertools import tee
from collections import deque
from collections import Counter
from collections.abc import Mapping
from abc import ABCMeta
from collections.abc import Iterable
import os
import sys
import re
import logging
import time
import eflips.events
from functools import total_ordering
import itertools as it
import math
import copy

def weekday(weekday):
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    res = 1
    for day in days:
        if day == weekday:
            return res
        res += 1
    return -1

def getNextDay(weekday):
    days = it.cycle(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
    while not next(days) == weekday:
        pass
    return next(days)

@total_ordering
class TimeInfo:
    weekday = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2,
               'Thursday': 3, 'Friday': 4, 'Saturday': 5,
               'Sunday': 6}

    @classmethod
    def weekdayInv(cls):
        return dict(reversed(item) for item in cls.weekday.items())

    @classmethod
    def adjust(cls, newFirstDay):
        shift = 7 - cls.weekday[newFirstDay]
        for day in cls.weekday:
            index = (cls.weekday[day] + shift) % 7
            cls.weekday.update({day: index})

    @classmethod
    def reset(cls):
        cls.weekday = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2,
                       'Thursday': 3, 'Friday': 4, 'Saturday': 5,
                       'Sunday': 6}

    @classmethod
    def firstDay(cls):
        return cls.weekdayInv()[0]

    def __init__(self, day, time):
        # add sanity checking here: day has to be a string conforming to weekday -> done
        if day not in self.weekday:
            raise ValueError("day '%s' is not a valid key in " % day +
                             "TimeInfo.weekday")
        self.day = day
        self.time = time

    def __eq__(self, other):
        return (self.day, self.time) == (other.day, other.time)

    def __nq__(self, other):
        return not self == other

    def __lt__(self, other):
        if self.day == other.day:
            return self.time < other.time
        else:
            return TimeInfo.weekday[self.day] < TimeInfo.weekday[other.day]

    def getSeconds(self):
        secOfDay = 86400
        return (self.weekday[self.day])*secOfDay + self.time

    def __add__(self, other):
        if type(other) == int or type(other) == float:
            res = copy.deepcopy(self)
            res.addSeconds(other)
            return res
        else:
            return NotImplemented

    def __sub__(self, other):
        secOfWeek= 86400*7
        if self < other:
            return ((secOfWeek + self.getSeconds()) - other.getSeconds())
        else:
            return (self.getSeconds() - other.getSeconds())

    def addSeconds(self, seconds):
        # if self.time + seconds < 86400:
        #     self.time = self.time + seconds
        # else:
        offsetDays, newTime = divmod(self.time + seconds, 86400)
        self.time = newTime
        newDay = (TimeInfo.weekday[self.day] + offsetDays) % 7
        self.day = TimeInfo.weekdayInv()[newDay]

    def subSeconds(self, seconds):
        secOfWeek = 86400
        seconds = self.getSeconds() - seconds
        while seconds < 0:
            seconds += secOfWeek
        day, time = divmod(seconds, 86400)
        self.day = TimeInfo.weekdayInv()[day]
        self.time = time


    def delay(self, other):
        if other < self:
            return -1
        else:
            if self.day == other.day:
                return other.time - self.time
            else:
                diff = (TimeInfo.weekday[other.day] - TimeInfo.weekday[
                    self.day] - 1) * 86400  # 86400=24*3600
                diff = diff + (86400 - self.time) + other.time
                return diff

    @property
    def totalSeconds(self):
        """Return total seconds since the beginning of the first day."""
        return self.time + TimeInfo.weekday[self.day]*86400

    def __abs__(self):
        return self.totalSeconds

    def hms(self):
        """Return hours, minutes and seconds"""
        return hms(self.time)

    def toString_hms(self):
        """Return hours, minutes and seconds as string"""
        return hms_str(self.time)

    def toString(self):
        """Return a string of the form 'Tuesday 16:03:41'"""
        (hour, minute, second) = self.hms()
        day = self.day
        return day + ' ' + '{:02.0f}'.format(hour) + ':'\
               + '{:02.0f}'.format(minute) + ':' \
               + '{:02.0f}'.format(second)

    def toString_short(self):
        """Return a string of the form 'Tue 16:03'"""
        (hour, minute, second) = self.hms()
        day_short = {'Monday': 'Mon',
                     'Tuesday': 'Tue',
                     'Wednesday': 'Wed',
                     'Thursday': 'Thu',
                     'Friday': 'Fri',
                     'Saturday': 'Sat',
                     'Sunday': 'Sun'}
        day = day_short[self.day]
        return day + ' ' + '{:02.0f}'.format(hour) + ':'\
               + '{:02.0f}'.format(minute)

def hms(sec):
    """Return hours, minutes and seconds"""
    hour = math.floor(sec / 3600)
    minute = math.floor((sec - hour * 3600) / 60)
    second = sec - hour * 3600 - minute * 60
    return hour, minute, second

def hms_str(sec):
    """Return hours, minutes and seconds as string"""
    hour, minute, second = hms(sec)
    return '{:02.0f}'.format(hour) + ':'\
           + '{:02.0f}'.format(minute) + ':' \
           + '{:02.0f}'.format(second)

class Stopwatch:
    def __init__(self):
        self._lastTime = time.time()
        self.times = []

    def add(self, description):
        newTime = time.time()
        dt = newTime - self._lastTime
        self._lastTime = newTime
        self.times.append((description, dt))


class Ambient:
    """Object with ambient conditions, i.e. weather."""
    def __init__(self, temperature, rel_humidity, insolation):
        self.temperature = temperature  # °C
        self.rel_humidity = rel_humidity  # 0...1
        self.insolation = insolation  # W/m²


# class Counter(CounterOriginal):
#     @property
#     def total(self):
#         return sum(self.values())

    # This does not work:
    # def __add__(self, other):
    #     if other == 0:
    #         # hack to be able to use sum() on Counter objects
    #         return self
    #     else:
    #         return super().__add__(other)

class CalcDict(dict):
    """Dict with add and subtract methods to enable fast adding/subtracting
    of categorised data. It follows the general idea of collections.Counter,
    but enables non-integer values."""
    def __init__(self, *args):
        if len(args) == 1 and isinstance(args[0], dict):
            # The supplied argument is an initial dict
            super().__init__(args[0])
        elif len(args) == 1 and isinstance(args[0], Iterable):
            # The supplied argument is probably a list of tuples with initial
            # counts/values
            super().__init__()
            for elem in args[0]:
                key = elem[0]
                val = elem[1]
                if key in self:
                    self[key] += val
                else:
                    self.update({key: val})
        else:
            # The supplied arguments (if any) are key names; initialise their
            # values to zero:
            super().__init__()
            for arg in args:
                self.update({arg: 0})

    def __missing__(self, key):
        return 0

    def __add__(self, other):
        if not isinstance(other, CalcDict):
            return NotImplemented
        res = CalcDict()
        for key, value in self.items():
            newval = value + other[key]
            res.update({key: newval})
        for key, value in other.items():
            if key not in self:
                newval = value
                res.update({key: newval})
        return res

    def __sub__(self, other):
        if not isinstance(other, CalcDict):
            return NotImplemented
        res = CalcDict()
        for key, value in self.items():
            newval = value - other[key]
            res.update({key: newval})
        for key, value in other.items():
            if key not in self:
                newval = 0 - value
                res.update({key: newval})
        return res


class AddSubDict(metaclass=ABCMeta):
    """ABC to check for dictionary add/subtract functionality"""
    pass


AddSubDict.register(Counter)
AddSubDict.register(CalcDict)


def setup_logger(logging_filename, level='debug'):
    # setup and config logger
    # once this logger is setup one can log from different areas in your application
    # e.g. logging.info() , logging.debug() etc.

    # set up logging to file for debug messages or higher
    log_level_map = {'debug': logging.DEBUG,
                     'warning': logging.WARNING,
                     'error': logging.ERROR}

    logging.basicConfig(level=log_level_map[level],
                        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                        datefmt='%m-%d %H:%M',
                        filename=logging_filename,
                        filemode='w')
    # define a Handler which writes INFO messages or higher to the console
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    # set a format which is simpler for console use
    formatter = logging.Formatter('%(asctime)s %(name)-12s: %(levelname)-8s %(message)s')
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)


def interrupt_process(process, sender):
    """Helpfer function to interrupt simpy processes."""
    if not process.triggered:
        process.interrupt(sender)


def clear_queue(env):
    """helper function to clear env queue"""
    env._queue.clear()


def pairwise(iterable):
    """s -> (s0,s1), (s1,s2), (s2, s3), ..."""
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def set_default_kwargs(obj, kwargs, defaults):
    """Helper function to quickly skim keyword arguments, set default
    values for missing arguments and add these arguments to obj as attributes.
    defaults must be a dict of the same form as kwargs:
    {'arg1': default_val1, 'arg2': default_val2} and so forth. Note that
    defaults MUST provide values for all possible kwargs encountered.
    """
    for arg, val in defaults.items():
        try:
            setattr(obj, arg, kwargs[arg])
        except KeyError:
            setattr(obj, arg, val)


# class IDContainer:
#     """Container class for indexed stacks. Requires the calling class
#     to assign unique IDs to the stacked objects in an attribute obj.ID."""
#     def __init__(self):
#         self._stack = deque()
#         self._ID_map = dict()
#
#     def _add(self, obj):
#         self._stack.append(obj)
#         self._ID_map.update({obj.ID: obj})
#
#     def get_by_ID(self, ID):
#         return self._ID_map[ID]
#
#     def get_all(self):
#         return self._stack


class IndexedContainer:
    def __init__(self):
        self._stack = deque()
        self._ID_map = dict()
        self._next_ID = 1

    def _add(self, obj):
        self._stack.append(obj)
        self._ID_map.update({self._next_ID: obj})
        obj.ID = self._next_ID
        self._next_ID += 1

    def add(self, obj):
        self._add(obj)

    def get_by_ID(self, ID):
        return self._ID_map[ID]

    def get_all(self):
        return self._stack

    def get_all_by_ID(self):
        return self._ID_map


class LocationMapContainer(IndexedContainer):
    def __init__(self):
        super().__init__()
        self._location_map = dict()

    def add(self, obj):
        self._add(obj)
        self._location_map.update({obj.location: obj})

    def get_by_location(self, location):
        return self._location_map[location]

    def get_all_by_location(self):
        return self._location_map


def union(set_a, set_b):
    union_set = []
    for element in set_a:
        if element not in set_b:
            union_set.append(element)

    union_set = union_set + set_b

    return union_set


def intersect(set_a, set_b):
    intersection = []
    for element in set_a:
        if element in set_b:
            intersection.append(element)

    return intersection

# def count_vehicles_by_type(list_of_types, list_of_vehicles):
#     """Helper function to generate a dict of the form
#     {vehicle_type_string_1: num_vehicles_1,
#     vehicle_type_string_2: num_vehicles_2,
#     ...}.
#     Used by SimpleDepot and Fleet."""
#     out = dict([(t.name, 0) for t in list_of_types])
#     out.update({'total': 0})
#     for v in list_of_vehicles:
#         out[v.vehicle_type.name] += 1
#         out['total'] += 1
#     return out

def cm2in(*cm):
    """Convert cm to inch (required for matplotlib). If multiple arguments
    are supplied, return a tuple; useful for
    fig = plt.figure(figsize=cm2in(15,9))."""
    oneinch = 2.54
    if len(cm) > 1:
        # return tuple
        return tuple(i/oneinch for i in cm)
    elif len(cm) == 1:
        return cm[0]/oneinch
    else:
        # return zero
        return 0

def in2cm(*inches):
    """Convert inch to cm (required for matplotlib). If multiple arguments
    are supplied, return a tuple"""
    inch_in_cm = 2.54
    if len(inches) > 1:
        return tuple(inch*inch_in_cm for inch in inches)
    elif len(inches) == 1:
        return inches[0]*inch_in_cm
    else:
        return 0


def miles_to_km(miles):
    return miles/0.62137119223733

def seconds_to_hm_string(sec):
    hours, rest = divmod(sec, 3600)
    minutes, _ = divmod(rest, 60)
    return '{:0d}'.format(hours) + ':' + '{:02d}'.format(minutes)

def list_to_string(iterable, separator, apply_function=None):
    """Helper function to write an iterable to a string with entries separated
    by separator."""
    n = len(iterable)
    out = ''
    for index, entry in enumerate(iterable):
        if apply_function is None:
            out += str(entry)
        else:
            out += apply_function(entry)
        if index < n - 1:
            out += separator
    return out

def hline_thin():
    return '-------------------------------------------------------------------------------'

def hline_thick():
    return '==============================================================================='

def generate_log_file_name(timestamp=True):
    filename = os.path.split(sys.argv[0])[1]
    pattern = re.compile('(.*)\.(.*)')
    res = pattern.match(filename)
    if res is not None:
        filename_base = res.groups()[0]
    else:
        filename_base = filename
    current_time = time.localtime()
    time_str = '%04d%02d%02d_%02d%02d%02d' % (
        current_time[0], current_time[1], current_time[2],
        current_time[3], current_time[4], current_time[5]
    )
    if timestamp:
        filename_base += '_' + time_str
    filename = filename_base + '.log'
    return filename

def translate(word, dictionary):
    try:
        return dictionary[word]
    except (KeyError, TypeError):
        return word

def deep_merge(d, u):
    """Do a deep merge of one dict into another.

    This will update d with values in u, but will not delete keys in d
    not found in u at some arbitrary depth of d. That is, u is deeply
    merged into d.

    Args -
     d, u: dicts

    Note: this is destructive to d, but not u.

    Returns: None

    From: https://stackoverflow.com/a/52099238
    Notable differences to dict.update():
    - Subdicts at arbitrary levels existing in both dicts are merged instead of
        replaced.
    - An object reference to an existing subdict in d is kept as long as it
        exists in both dicts (consequence of above).
    """
    stack = [(d, u)]
    while stack:
        d, u = stack.pop(0)
        for k, v in u.items():
            if not isinstance(v, Mapping):
                # u[k] is not a dict, nothing to merge, so just set it,
                # regardless if d[k] *was* a dict
                d[k] = v
            else:
                # note: u[k] is a dict

                # get d[k], defaulting to a dict, if it doesn't previously
                # exist
                dv = d.setdefault(k, {})

                if not isinstance(dv, Mapping):
                    # d[k] is not a dict, so just set it to u[k],
                    # overriding whatever it was
                    d[k] = v
                else:
                    # both d[k] and u[k] are dicts, push them on the stack
                    # to merge
                    stack.append((dv, v))


# def lookup_from_x(x0, x, y, interpolate=False):
#     if x0 in x:
