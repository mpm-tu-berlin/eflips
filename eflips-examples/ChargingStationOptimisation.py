# -*- coding: utf-8 -*-
"""Demo script illustrating use of geentic algorithm for cost-optimised
charging station placement.
"""
import eflips
import os

# This if clause is required for the genetic iteration to run because of the
# multiprocessing functionality - even if multiprocessing=False is specified.
if __name__=='__main__':
    # For performance reasons, be sure to turn off data logging. The genetic
    # module is designed such that detailed logging of time series data is
    # not required.
    eflips.global_constants.update({
        'DATA_LOGGING': False,
        'ALLOW_INVALID_SOC': False
    })

    # -----------------------------------------------------------------------------
    # File paths
    # -----------------------------------------------------------------------------

    timetable_path = os.path.join(os.getcwd(), 'output')
    timetable_filename = 'timetable.pickle'

    # Output will be placed in working directory; if desired, specify a different
    # directory here:
    output_path_base = os.path.join(os.getcwd(), 'output')

    output_path = os.path.join(output_path_base, 'ChargingStationOptimisation')

    if not os.path.exists(output_path):
        os.mkdir(output_path)

    # -----------------------------------------------------------------------------
    # Setup logger, load data
    # -----------------------------------------------------------------------------

    # Setup logger. Set level='debug' for more detailed logging
    log_file = eflips.misc.generate_log_file_name(timestamp=True)
    eflips.misc.setup_logger(os.path.join(output_path, log_file),
                              level='error')

    # Load timetable and grid
    grid, timetable = eflips.io.import_pickle(os.path.join(timetable_path,
                                                            timetable_filename))


    # -----------------------------------------------------------------------------
    # Define parameters
    # -----------------------------------------------------------------------------

    # Scheduling parameters
    # ---------------------

    # Refer to eflips.scheduling.generate_schedules_singledepot()
    # documentation for details on the parameter dict.
    scheduling_params = {
        'charging_point_names': [],
        'scheduling_params': {
            'depot_gridpoint_id': grid.find_points('name','Depot')[0].ID,
            'min_pause_duration': 0,  # s
            'max_pause_duration': 45 * 60,  # s
            'max_deadheading_duration': 45 * 60,  # s
            'use_static_range': False,
            'default_depot_trip_distance': 5,  # km
            'default_depot_trip_velocity': 25,  # km/h
            'default_deadhead_trip_distance': 5,  # km
            'default_deadhead_trip_velocity': 25,  # km/h
            'get_missing_coords_from_osm': False,
            'fill_missing_distances_with_default': False,
            'deadheading': False,
            'mix_lines_at_stop': False,
            'mix_lines_deadheading': True,
            'add_delays': False,
            'delay_mode': 'all',
            'delayed_trip_ids': None,
            'delay_threshold': 0  # s
        },
        'vehicle_params': {
            'SB': {
                'capacity': 90 * 0.8 * 0.8 - 5,  # kWh
                'static_range': 0,  # km (irrelevant, deactivated above)
                'traction_consumption': 0.88,  # kWh/km
                'aux_power_driving': 2 + 8,  # kW
                'aux_power_pausing': 2,  # kW
                'charge_power': 300,  # kW
                'reduce_charge_time': 0,
                'dead_time': 30  # s
            }
        }
    }

    # Schedule simulation parameters
    ambient_temperature = -10  # °C
    depot_grid_point_id = grid.find_points('name', 'Depot')[0].ID
    charging_interface = 'pantograph_300'
    capacity_per_station = 2
    schedule_simulation_params = {
        'simulation_params': {
            'base_day': 'Monday',
            'run_until': None  # run until no events are left
        },
        'ambient_params': {
            'temperature': ambient_temperature,
            'humidity': 0.4,  # not used anywhere at the moment
            'insolation': 0  # W/m²
        },
        'vehicle_params': {
            'SB': {
                # Vehicle architecture (see class vehicle.Fleet for details):
                'architecture': 'bus_electric_konvekta_hvac_electric',

                # Number of passengers used for payload and heating/cooling load
                # calculation. Irrelevant for traction consumption if we use
                # ConstantConsumptionTraction; set to zero to obtain the maximum
                # heating load (no heat sources):
                'num_passengers': 0,

                # Power of auxiliaries excluding HVAC system:
                'aux_power': 2,  # kW

                # Cabin temperature is obtained as a function of ambient
                # temperature from a correlation:
                'cabin_temperature':
                    eflips.vehicle.cabin_temperature_vdv(ambient_temperature)\
                        ['economy'],

                # Traction model used for consumption calculation. At present,
                # the only model usable for ScheduleSimulation is
                # ConstantConsumptionTraction:
                'traction_model': 'ConstantConsumptionTraction',

                # Mean traction consumption:
                'traction_consumption': 0.88,  # kWh/km

                # Kerb weight is irrelevant as long as we use
                # ConstantConsumptionTraction, but has to be specified:
                'kerb_weight': 14500,  # kg

                # Whether or not to switch off the HVAC system while the bus
                # is pausing at terminal stops:
                'switch_off_ac_in_pause': False,

                # List of charging interfaces; see energy.ChargingInterfaceTypes
                # class documentation for details:
                'charging_interfaces': ['pantograph_300', 'plug'],

                # Overall UA value (heat transmittance) of bus chassis for
                # heat transfer calculation:
                'UA_value': 0.562,  # kW/K

                # Surface area used to calculate solar gain:
                'insolation_area': 11.4,  # m²

                # Number of HVAC system units; the type of HVAC system is
                # determined by the vehicle architecture specified above:
                'hvac': {
                    'num_ac_units': 1,
                    'num_hp_units': 1,
                    'num_backup_units': 0
                },

                # Battery parameters:
                'battery': {
                    'capacity_max': 90,  # kWh
                    'soc_reserve': 0.08,
                    'soc_min': 0.10,
                    'soc_max': 0.90,
                    'soc_init': 0.90,
                    'soh': 0.8,
                    'discharge_rate': 5,
                    'charge_rate': 5
                }
            },
        },
        'charging_point_params': {
            depot_grid_point_id: {
                'interface': 'plug',
                'capacity': 10
            }
        },
        'depot_params': {
            'charging': True,
            'locations': [depot_grid_point_id],
            'driver_additional_paid_time': 1200  # seconds
        },
        'depot_charging_params': {
            depot_grid_point_id: {
                'dead_time_before': 600,
                'dead_time_after': 600,
                'interrupt_charging': False
            }
        }
    }


    # Cost parameters
    # ---------------

    # (For simplified TCO model within charging station optimiser)
    cost_params = {
        'vehicle_invest': {
            # Vehicle cost INCLUDING first battery. Battery replacements are
            # considered in 'battery_invest' below.
            'SB': 450000+90*800  # €
        },
        'vehicle_lifetime': {
            'SB': 12  # years
        },
        'vehicle_maintenance_cost': {
            'SB': 0.3  # €/km
        },
        'battery_invest': {
            # Cost for battery replacements, if applicable. The number of
            # battery replacements is calculated as
            # ceil(vehicle_lifetime/battery_lifetime). Specify the ABSOLUTE
            # cost of battery replacement or refurbishment per vehicle -
            # NOT the specific cost in €/kWh.
            # The simplified TCO calculation only allows a constant battery
            # price. If multiple replacements of the battery occur over the
            # lifetime of the vehicle, use an average value. In this case,
            # however, we only have one replacement after 6 years and can
            # compute the future battery price using a cost degression factor:
            'SB': 90*800*(1-0.08)**6
        },
        'battery_lifetime': {
            'SB': 6  # years
        },
        'energy_cost': {
            'Electricity': 0.15  # €/kWh
        },
        'driver_cost': 20,  # €/h
        'charging_slot_invest': 200000,  # €
        'charging_station_transformer_and_construction': 200000,  # €
        'charging_station_lifetime': 20,
        'ignore_charging_points': ['Depot']
    }


    # ChargingInfrastructureIterator options
    # --------------------------------------

    # List of allowed charging stations. Two of these, H and I, are useless
    # because they are not terminal stops and will be eliminated by the genetic
    # algorithm.
    possible_charging_stations = ['A', 'H', 'I', 'Z']

    # Genetic iteration options
    population_size = 10

    # Tolerance within which solutions are considered of equal cost
    fitness_tolerance = 0.001  # €/km

    # -----------------------------------------------------------------------------
    # Start ChargingInfrastructureIterator and save results
    # -----------------------------------------------------------------------------

    # Generate an empty OpenStreetMap cache. Usually, we would load it from
    # an already existing pickle file.
    osm_cache = eflips.scheduling.generate_osm_cache()

    # Initialise genetic algorithm
    optimiser = eflips.genetic.ChargingInfrastructureIterator(
        timetable, grid, scheduling_params, possible_charging_stations,
        osm_cache, schedule_simulation_params, cost_params,
        charging_interface, capacity_per_station, population_size,
        fitness_tolerance=fitness_tolerance
    )

    # Start iteration
    optimiser.iterate(num_generations=20, multicore=False)

    # Update OSM cache. We need to use update() because the
    # ChargingInfrastructureIterator object keeps a DictProxy rather than a
    # plain dict.
    osm_cache['osm_places'].update(optimiser.osm_cache_data['osm_places'])
    osm_cache['openroute_distance'].\
        update(optimiser.osm_cache_data['openroute_distance'])

    # Usually, we would now save osm_cache to a pickle file using
    # eflips.io.export_pickle() for later use.

    # Save iteration state
    optimiser.save(output_path)

    # Print the best results. It should turn out that placing a charging
    # station at A *or* Z yields identical results - which is no surprise
    # because the timetable allows equal dwell time at both stops.
    # The minus sign reverses negation of the cost function that
    # ChargingInfrastructureIterator performs internally. Negation is required
    # to minimise the cost function because BinaryGeneticIterator can only
    # maximise. (Maximising the negative of a function is the same as
    # minimising the function.)
    print('Best results:')
    for (stations, fitness) in \
            optimiser.peak_fitness_chromosomes_decoded.items():
        print('%s: %.2f €/km' % (stations, fitness*(-1)))

    # Plot progress of fitness iteration
    eflips.evaluation.plot_ga_fitness(
        optimiser.current_state_dict(), ylabel='TCO (€/km)',
        invert_fitness=True, save=True,
        # display=['mean', 'best'],
        filename=os.path.join(output_path, 'ga_fitness')
    )
