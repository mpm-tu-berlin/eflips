# -*- coding: utf-8 -*-
from abc import ABCMeta, abstractmethod
from random import randint
import copy
import numpy as np
import time
import datetime
import os
import logging
from eflips import io
from eflips.settings import rcParams, global_constants
from eflips.simulation import ScheduleSimulation
from eflips.scheduling import generate_schedules_singledepot
from eflips.tco import simple_tco
from collections import OrderedDict
from multiprocessing import Pool, Manager
from itertools import product

class BinaryGeneticIteratorAbstract(metaclass=ABCMeta):
    def __init__(self, population_size, num_bits, best_selection_share=0.5,
                 mutation_rate=0.2, fitness_tolerance=1e-5):
        self._best_selection_share = best_selection_share
        self._mutation_rate = mutation_rate
        self._fitness_tolerance = fitness_tolerance
        self._current_population = \
            self._generate_random_population(population_size, num_bits)
        self._init_stats()
        self.peak_fitness = -np.inf
        self.peak_fitness_chromosomes = {}
        self.peak_fitness_chromosomes_decoded = {}

        # Create shared-memory dict for fitness cache and shared-memory integer
        # for fitness function call count (required for multiprocessing).
        # Caution: The fitness function call count _may_ be inaccurate
        # when using multiprocessing because of a bug in Python
        # (get_lock() method is not available in Manager.Value class; see:
        # https://bugs.python.org/issue35786)
        manager = Manager()
        self._fitness_cache_shared = manager.dict()
        self._fitness_function_calls_unique_shared = manager.Value(int, 0)
        self._fitness_function_calls_total_shared = manager.Value(int, 0)

    def _init_stats(self):
        self._current_generation = 0
        self._total_time = 0
        # Results for all generations will be saved here:
        self.history = {
            'fitness_max': OrderedDict(),
            'fitness_min': OrderedDict(),
            'fitness_mean': OrderedDict(),
            'fitness_stddev': OrderedDict(),
            'fitness_evaluation_time': OrderedDict()
        }

    @property
    def _fitness_cache(self):
        """Any method outside of the multiprocessing worker pool (i.e.
        outside of fitness evaluation) should use this property to read
        the fitness cache as it returns a plain dict instead of a DictProxy."""
        return dict(self._fitness_cache_shared)

    @_fitness_cache.setter
    def _fitness_cache(self, value):
        """Setter to update DictProxy fitness cache object."""
        self._fitness_cache_shared.update(value)

    @property
    def _fitness_function_calls_unique(self):
        """Return number of unique fitness function calls as an integer
        (instead of ValueProxy). Use this outside of the worker pool."""
        return self._fitness_function_calls_unique_shared.value

    @_fitness_function_calls_unique.setter
    def _fitness_function_calls_unique(self, value):
        """Setter to update ValueProxy object."""
        self._fitness_function_calls_unique_shared.value = value

    @property
    def _fitness_function_calls_total(self):
        """Return number of total fitness function calls as an integer
        (instead of ValueProxy). Use this outside of the worker pool."""
        return self._fitness_function_calls_total_shared.value

    @_fitness_function_calls_total.setter
    def _fitness_function_calls_total(self, value):
        """Setter to update ValueProxy object."""
        self._fitness_function_calls_total_shared.value = value

    def current_state_dict(self):
        """Return current iteration state as a dict. Useful for subclasses
        that wish to save the iteration state and additional data pertaining
        to the problem formulation."""
        state_dict = {
            'best_selection_share': self._best_selection_share,
            'mutation_rate': self._mutation_rate,
            'fitness_tolerance': self._fitness_tolerance,
            'current_population': self._current_population,
            'current_generation': self._current_generation,
            'total_time': self._total_time,
            'fitness_function_calls_total': self._fitness_function_calls_total,
            'fitness_function_calls_unique': self._fitness_function_calls_unique,
            'peak_fitness': self.peak_fitness,
            'peak_fitness_chromosomes': self.peak_fitness_chromosomes,
            'peak_fitness_chromosomes_decoded': self.peak_fitness_chromosomes_decoded,
            'fitness_cache': self._fitness_cache,
            'history': self.history
        }
        return state_dict

    def import_current_state_dict(self, state_dict):
        """Load a previous iteration state from dict generated by
        export_current_state_dict. Overrides all arguments passed during
        construction of the BinaryGeneticIterator object!"""
        self._best_selection_share = state_dict['best_selection_share']
        self._mutation_rate = state_dict['mutation_rate']
        self._fitness_tolerance = state_dict['fitness_tolerance']
        self._current_population = state_dict['current_population']
        self._current_generation = state_dict['current_generation']
        self._total_time = state_dict['total_time']
        self._fitness_function_calls_total = state_dict['fitness_function_calls_total']
        self._fitness_function_calls_unique = state_dict['fitness_function_calls_unique']
        self.peak_fitness = state_dict['peak_fitness']
        self.peak_fitness_chromosomes = state_dict['peak_fitness_chromosomes']
        self.peak_fitness_chromosomes_decoded = state_dict['peak_fitness_chromosomes_decoded']
        self.history = state_dict['history']
        self._fitness_cache = state_dict['fitness_cache']

    def save(self, output_path, base_name='binary_genetic',
             replace_file=True):
        """Save current iteration state to pickle file"""
        timestamp = self.generate_timestamp()
        filepath = os.path.join(output_path,
                                base_name + '_' + timestamp + ".dat")
        export_data = self.current_state_dict()
        io.export_pickle(filepath, export_data, replace_file=replace_file)
        return filepath

    def load(self, filepath):
        """Load a previous iteration state from pickle file. Overrides all
        arguments passed during construction of the BinaryGeneticIterator
        object!"""
        import_data = io.import_pickle(filepath)
        self.import_current_state_dict(import_data)

    @staticmethod
    def generate_timestamp():
        """Generate a timestamp for use, e.\,g., in filenames."""
        return datetime.datetime.isoformat(datetime.datetime.now()).\
            replace(":", "-").replace("-", "_").replace(".", "_")

    @staticmethod
    def _generate_random_population(population_size, num_bits):
        """Generate a random population with alleles 0 or 1."""
        res = np.empty((population_size, num_bits), dtype=np.int8)
        for i in range(0, population_size):
            for j in range(0, num_bits):
                res[i, j] = randint(0, 1)
        return res

    def _fitness(self, chromosome):
        """Evaluate fitness of a single chromosome. First check if the
        chromosome's fitness is cached; else call fitness function
        implemented by non-abstract subclass."""
        # convert to tuple because numpy arrays cannot be used as dict keys
        self._fitness_function_calls_total_shared.value += 1
        chromosome = tuple(chromosome)
        if chromosome in self._fitness_cache_shared:
            return self._fitness_cache_shared[chromosome]
        else:
            # with self._counter_lock:
            self._fitness_function_calls_unique_shared.value += 1
            fitness = self._calculate_fitness(chromosome)
            self._fitness_cache_shared.update({chromosome: fitness})
            return fitness

    @abstractmethod
    def _calculate_fitness(self, chromosome):
        """Implement your fitness function in a subclass here. Important:
        The algorithm ALWAYS maximises the function. If you wish to minimise,
        simply put a negative sign in front of the function."""
        pass

    def _fitness_population(self, population, multicore=False):
        """Evaluate fitness of an entire population; return fitness of all
        individuals as well as various statistics for the population."""
        t_start = time.time()
        pop_size = population.shape[0]
        if multicore:
            with Pool(os.cpu_count()) as pool:
                fitness_population = \
                    np.array(pool.map(self._fitness, population))
        else:
            fitness_population = np.zeros(pop_size)
            for i in range(0, pop_size):
                fitness_population[i] = self._fitness(population[i,:])
        fitness_mean = np.mean(fitness_population)
        fitness_stddev = np.std(fitness_population)
        fitness_max = np.max(fitness_population)
        fitness_min = np.min(fitness_population)
        t_end = time.time()
        dt = t_end - t_start
        stats = {'fitness_max': fitness_max,
                 'fitness_min': fitness_min,
                 'fitness_mean': fitness_mean,
                 'fitness_stddev': fitness_stddev,
                 'fitness_evaluation_time': dt}
        return fitness_population, stats

    def _update_history(self, stats):
        """Update fitness history with stats returned by
        _fitness_population()"""
        for key, val in stats.items():
            self.history[key].update({self._current_generation: val})

    @abstractmethod
    def _decode_chromosome(self, chromosome):
        """Implement method to decode chromosomes here."""
        pass

    def brute_force_evaluation(self, multicore=False):
        """Evaluate ALL possible chromosomes. Be careful with this, mainly
        for debugging purposes."""
        # Reset statistics (generation, history, ...)
        self._init_stats()

        # Generate population with all possible combinations
        _, num_bits = \
            self._get_population_size(self._current_population)
        self._current_population = \
            np.array(list(product([0,1], repeat=num_bits)))

        # Calculate fitness and terminate
        self.iterate(multicore=multicore, num_generations=0)


    def iterate(self, mutate_offspring_only=True, multicore=False,
                num_generations=np.inf, max_time=np.inf,
                num_unique_fitness_evaluations=np.inf):
        """Perform selection, mating and mutation until a termination
        criterion is reached.

        The default mode is to perform mutation only when generating
        offspring. Other implementations work by mutating the entire
        population. This can be forced by setting mutate_offspring_only=False,
        but it significantly decreases performance. If
        mutate_offspring_only=False, the entire population is mutated except
        for the single best chromosome.
        """
        while True:
            t_start = time.time()
            # evaluate fitness of current population and append to history
            self._current_population_fitness,\
                self._current_population_stats = \
                self._fitness_population(self._current_population,
                                         multicore=multicore)
            self._update_history(self._current_population_stats)

            # sort population by fitness (descending, hence the minus)
            ind = np.argsort(-self._current_population_fitness)
            self.current_population_sorted = self._current_population[ind, :]
            self.current_population_fitness_sorted = \
                self._current_population_fitness[ind]

            # check if we have a new fitness record and update peak_fitness
            # accordingly:
            population_size, num_bits = \
                self._get_population_size(self.current_population_sorted)

            if self.current_population_fitness_sorted[0] > self.peak_fitness:
                # new record
                self.peak_fitness = self.current_population_fitness_sorted[0]

                # clear all entries in peak_fitness_chromosomes with lower
                # fitness (outside of tolerance)
                for chrom, fitness in \
                        copy.copy(self.peak_fitness_chromosomes).items():
                    if fitness < self.peak_fitness - self._fitness_tolerance:
                        del self.peak_fitness_chromosomes[chrom]

            # find all new entries in current population within tolerance
            # of peak fitness
            i = 0
            while self.current_population_fitness_sorted[i] >= \
                    self.peak_fitness - self._fitness_tolerance:
                chrom = tuple(self.current_population_sorted[i])
                fitness = self.current_population_fitness_sorted[i]
                if chrom not in self.peak_fitness_chromosomes:
                    self.peak_fitness_chromosomes.update({chrom: fitness})
                if i == population_size - 1:
                    # terminate this while loop if we reach the end of
                    # population
                    break
                i += 1

            # update decoded list of best chromosomes
            self.peak_fitness_chromosomes_decoded = dict(
                [(tuple(self._decode_chromosome(chrom)), fitness) for
                 chrom, fitness in self.peak_fitness_chromosomes.items()]
            )

            # Update time; we do this in case the fitness function is
            # expensive. Its evaluation time will be counted in the current
            # generation
            t_end = time.time()
            dt = t_end - t_start
            self._total_time += dt

            # terminate if one of the termination criteria is reached
            if self._current_generation >= num_generations or \
                    self._total_time >= max_time or \
                    self._fitness_function_calls_unique >= \
                    num_unique_fitness_evaluations:
                break

            t_start = time.time()
            # keep only the best chromosomes, the share specified by
            # best_selection_share
            population_size, num_bits = \
                self._get_population_size(self._current_population)

            num_best = np.int(np.ceil(self._best_selection_share
                                      * population_size))
            if num_best < 2:
                raise ValueError('Natural selection leaves less than 2 \
                                  chromomes; mating does not work that way. \
                                  Increase best_selection_share and/or \
                                  population_size.')
            num_new = population_size - num_best
            if num_new == 0:
                raise ValueError('Cannot create any children. Decrease \
                                  best_selection_share!')
            population_best = self.current_population_sorted[0:num_best]

            # number of reproductions needed; each reproduction produces 2
            # children
            num_reproductions = np.int(np.ceil(num_new/2))

            # randomly select 'father' and 'mother' chromosomes
            mates = []
            for i in range(0, num_reproductions):
                mum = population_best[randint(0, len(population_best) - 1)]
                dad = population_best[randint(0, len(population_best) - 1)]
                # dad = mum
                # while np.array_equal(mum, dad):
                #     # make sure parents don't have the same chromosome
                #     dad = population_best[randint(0, len(population_best) - 1)]
                mates.append((mum, dad))

            population_offspring = np.empty((num_reproductions*2, num_bits),
                                            dtype=np.int8)
            for i, (mum, dad) in enumerate(mates):
                # assumes 2 offspring per reproduction
                start_idx = 2*i
                end_idx = 2*i + 2
                population_offspring[start_idx:end_idx] = \
                    self._create_offspring(mum, dad)

            # shorten offspring if required to maintain exact population size
            if len(population_offspring) > num_new:
                shorten_by = len(population_offspring) - num_new
                population_offspring = \
                    population_offspring[0:len(population_offspring)
                                           -shorten_by]

            # mutate offspring
            if mutate_offspring_only is True:
                population_offspring_mutated = \
                    self._mutate_population(population_offspring,
                                            self._mutation_rate,
                                            elitist=False)
            else:
                population_offspring_mutated = population_offspring

            # add offspring to population
            new_population = np.concatenate((population_best,
                                             population_offspring_mutated))

            # mutate complete population
            if mutate_offspring_only is True:
                new_population_mutated = new_population
            else:
                new_population_mutated = \
                    self._mutate_population(new_population,
                                            self._mutation_rate,
                                            elitist=True)

            self._current_population = new_population_mutated
            self._current_generation += 1
            # Important: At this point, self._current_population and
            # self._current_population_stats are out of sync until the
            # next fitness evaluation. However, the loop only ever terminates
            # AFTER fitness evaluation such that the values are in sync
            # when analysing and saving the data (unless a weird error occurs).

            # update time record
            t_end = time.time()
            dt = t_end - t_start
            self._total_time += dt

    @staticmethod
    def _create_offspring(mate1, mate2):
        # single-point crossing
        crossing_point = np.int(randint(1, len(mate1)-1))
        child1 = np.concatenate((mate1[0:crossing_point],
                                 mate2[crossing_point:]))
        child2 = np.concatenate((mate2[0:crossing_point],
                                 mate1[crossing_point:]))
        return np.stack((child1, child2))

    def _mutate_population(self, population, mutation_rate, elitist=True):
        """If elitist==True, the population needs to be sorted by fitness"""
        population = copy.copy(population)
        population_size, num_bits = \
            self._get_population_size(population)
        num_mutations = np.int(np.ceil((population_size-1) * num_bits *
                                       mutation_rate))
        # Change num_mutations randomly selected alleles (except on the best
        # chromosome if elitism is active):
        start_row = 1 if elitist == True else 0
        for k in range(0, num_mutations):
            i = randint(start_row, population_size-1)
            j = randint(0, num_bits-1)
            if population[i,j] == 0:
                population[i,j] = 1
            elif population[i,j] == 1:
                population[i,j] = 0
        return population

    @staticmethod
    def _get_population_size(population):
        population_shape = population.shape
        population_size = population_shape[0]
        num_bits = population_shape[1]
        return (population_size, num_bits)


class TestIterator(BinaryGeneticIteratorAbstract):
    def _calculate_fitness(self, chromosome):
        res = 0
        for i in range(0, len(chromosome)):
            res += (i+1)*chromosome[i]
        return res

    def _decode_chromosome(self, chromosome):
        return chromosome


class ChargingInfrastructureIterator(BinaryGeneticIteratorAbstract):
    def __init__(self, timetable, grid, scheduling_params, charging_stations,
                 osm_cache_data, schedule_simulation_params, cost_params,
                 charging_interface, capacity_per_station, population_size,
                 best_selection_share=0.5, mutation_rate=0.2,
                 fitness_tolerance=1e-5):
        self._timetable = timetable
        self._timetable_distance = \
            sum([trip.distance for trip in timetable.get_all()])
        self._grid = grid
        self._scheduling_params = scheduling_params
        self._charging_stations = charging_stations
        self._schedule_simulation_params = schedule_simulation_params
        self._cost_params = cost_params
        self._charging_interface = charging_interface
        self._capacity_per_station = capacity_per_station
        self._global_constants = copy.copy(global_constants)

        # Create a shared-memory dict for OSM cache data. Important: All sub-
        # dicts that will be updated by child processes must also be
        # re-instantiated as shared-memory dicts!
        manager = Manager()
        self.osm_cache_data = manager.dict()
        for key, sub_dict in osm_cache_data.items():
            self.osm_cache_data.update({
                key: manager.dict(sub_dict)
            })

        num_bits = len(charging_stations)
        self._encode_charging_station_list(charging_stations)

        super().__init__(
            population_size, num_bits,
            best_selection_share=best_selection_share,
            mutation_rate=mutation_rate,
            fitness_tolerance=fitness_tolerance
        )

    def save(self, output_path, base_name='charging_infrastructure_iterator',
             replace_file=True):
        export_data = {
            'iterator_state': self.current_state_dict(),
            'timetable': self._timetable,
            'timetable_distance': self._timetable_distance,
            'grid': self._grid,
            'scheduling_params': self._scheduling_params,
            'cost_params': self._cost_params,
            'charging_interface': self._charging_interface,
            'capacity_per_station': self._capacity_per_station,
            'global_constants': self._global_constants,
            'index_to_station': self._index_to_station,
            'station_to_index': self._station_to_index
        }
        timestamp = self.generate_timestamp()
        filepath = os.path.join(output_path,
                                base_name + '_' + timestamp + ".dat")
        io.export_pickle(filepath, export_data, replace_file=replace_file)
        return filepath

    def load(self, filepath):
        """Load a previous iteration state from pickle file. Overrides all
        arguments passed during construction of the BinaryGeneticIterator
        object!"""
        import_data = io.import_pickle(filepath)
        self.import_current_state_dict(import_data['iterator_state'])
        self._timetable = import_data['timetable']
        self._timetable_distance = import_data['timetable_distance']
        self._grid = import_data['grid']
        self._scheduling_params = import_data['scheduling_params']
        self._cost_params = import_data['cost_params']
        self._charging_interface = import_data['charging_interface']
        self._capacity_per_station = import_data['capacity_per_station']
        self._global_constants = import_data['global_constants']
        self._index_to_station = import_data['index_to_station']
        self._station_to_index = import_data['station_to_index']

    def _encode_charging_station_list(self, charging_stations):
        """Map charging stations to their respective position on the chromosome
        and vice-versa.
        Charging stations are given the index they have in
        self._charging_stations, retaining the original order passed during
        construction.
        """
        self._index_to_station = \
            dict([(i, name) for i, name in enumerate(charging_stations)])
        self._station_to_index = \
            dict([(name, i) for i, name in enumerate(charging_stations)])

    def _decode_chromosome(self, chromosome):
        station_list = []
        for i, val in enumerate(chromosome):
            if val == 1:
                station_list.append(self._index_to_station[i])
        return station_list

    def _calculate_fitness(self, chromosome):
        """Wrapper function to enable more refined fitness functions in
        subclasses, e.g. with preselection of valid chromosomes."""
        return self._calculate_fitness_eflips(chromosome)

    def _calculate_fitness_eflips(self, chromosome):
        charging_station_list = self._decode_chromosome(chromosome)
        logger = logging.getLogger('genetic_logger')

        # Set global constants (hack required for multiprocessing)
        global_constants.update(self._global_constants)

        scheduling_params = copy.copy(self._scheduling_params)
        scheduling_params['charging_point_names'] = \
            copy.copy(charging_station_list)
        grid, schedules = generate_schedules_singledepot(
            self._timetable, self._grid, scheduling_params,
            self.osm_cache_data)

        # For the simulation, we need to keep the depot charging point supplied
        # in schedule_simulation_params and replace all others with the
        # points defined in charging_point_names
        depot_gridpoint_id = \
            scheduling_params['scheduling_params']['depot_gridpoint_id']

        schedule_simulation_params = copy.copy(self._schedule_simulation_params)
        for id in copy.copy(schedule_simulation_params
                            ['charging_point_params']).keys():
            if id != depot_gridpoint_id:
                del schedule_simulation_params['charging_point_params'][id]

        for name in charging_station_list:
            points = self._grid.find_points('name', name)
            if len(points) == 0:
                logger.warning('No grid point found for charging station %s'
                               % name)
            for point in points:
                schedule_simulation_params['charging_point_params'].update(
                    {point.ID: {
                        'interface': self._charging_interface,
                        'capacity': self._capacity_per_station
                        }
                    }
                )

        simulation = ScheduleSimulation(schedule_simulation_params, schedules,
                                        grid, charging_schedule=None)

        tco = simple_tco(
            simulation.simulation_info['object_eval_data'],
            self._cost_params['ignore_charging_points'],
            self._timetable_distance,
            self._cost_params
        )
        logger.debug('Fitness evaluation:\n' +
                     'Number of vehicles: ' +
                     str(simulation.simulation_info['object_eval_data']
                         ['num_vehicles']) + '\n' +
                     'Number of charging stations: ' +
                     str(len(charging_station_list)) + '\n' +
                     'TCO: %.1f' % tco)
        return -tco


class ChargingInfrastructureIteratorWithGroups(ChargingInfrastructureIterator):
    def __init__(self, timetable, grid, scheduling_params, charging_stations,
                 charging_station_groups, penalty_fitness,
                 osm_cache_data, schedule_simulation_params, cost_params,
                 charging_interface, capacity_per_station, population_size,
                 best_selection_share, mutation_rate, fitness_tolerance=1e-5):
        """Same as ChargingInfrastructureIterator, but requires additional
        argument charging_station_groups - a list of lists where out of each
        sub-list, at least one charging station MUST appear in the solution
        (otherwise the solution's fitness is set to penalty_fitness). Use this,
        for example, to ensure that at least one charging station per line is
        set.

        Requires penalty_fitness: The fitness value assigned to
        chromosomes that do not meet the grouping criterion. Do NOT use
        infinity as this will trip up the population statistics. Use a value
        that can safely be assumed to lie outside the reasonable range for
        actual solution candidates."""
        super().__init__(timetable, grid, scheduling_params, charging_stations,
                         osm_cache_data, schedule_simulation_params, cost_params,
                         charging_interface, capacity_per_station, population_size,
                         best_selection_share, mutation_rate,
                         fitness_tolerance=fitness_tolerance)
        self._charging_station_groups = charging_station_groups
        self._penalty_fitness = penalty_fitness

    def _calculate_fitness(self, chromosome):
        charging_station_list = self._decode_chromosome(chromosome)

        # check if at least one station out of every group in
        # charging_station_groups is in charging_station_list; if not,
        # set fitness to -inf:
        succ = True
        for group in self._charging_station_groups:
            station_in_list = []
            for station in group:
                if station in charging_station_list:
                    station_in_list.append(True)
                else:
                    station_in_list.append(False)
            if not any(station_in_list):
                succ = False
                break

        if not succ:
            return self._penalty_fitness
        else:
            return self._calculate_fitness_eflips(chromosome)
