# -*- coding: utf-8 -*-
from eflips.misc import TimeInfo
import pandas as pd
import numpy as np
import math
from matplotlib import pyplot as plt

def temperature_histogram(trydata, use_day_map='default',
                          num_bins=None):
    """Import weather data from TRY (test reference years).

    use_day_map='default': A week consists of 5 identical weekdays, Saturday and
        Sunday. Return a dict with the number of days per temperature, grouped
        by the defined days (Weekday,Saturday, Sunday)

    use_day_map=None: Do not group by day, only return the number of days
        per temperature

    If num_bins=None, the bins will be 1 K wide with the left and right bounds
    of the distribution rounded to the nearest integer. If an integer is
    supplied for num_bins, the left and right bounds are the minimum/maximum
    value of the distribution and bins will have floating point edges.

    DJ"""
    if use_day_map == 'default':
        day_map = {
            'Weekday': ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                        'Friday'],
            'Saturday': ['Saturday'],
            'Sunday': ['Sunday']}
    else:
        day_map = use_day_map

    groups = trydata.groupby(['DD', 'MM', 'weekday'])
    trydata_daily_mean = groups.mean()
    trydata_daily_mean = trydata_daily_mean.reset_index(
        level=['DD', 'MM', 'weekday'])
    trydata_daily_mean.pop('HH')

    if num_bins is not None:
        T_min = trydata_daily_mean['t'].min()
        T_max = trydata_daily_mean['t'].max()
        DT = (T_max-T_min) / num_bins
        T_range = [T_min + i * DT for i in range(0, num_bins + 1)]
    else:
        T_min = math.floor(trydata_daily_mean['t'].min())
        T_max = math.ceil(trydata_daily_mean['t'].max())
        T_range = list(range(T_min, T_max + 1))

    num_days = {}

    if day_map is not None:
        # Return the number of days per weekday and temperature
        for key, days in day_map.items():
            this_day = {}
            for i in range(0, len(T_range)-1):
                count = 0
                T_lower = T_range[i]
                T_upper = T_range[i+1]\
                    if i<len(T_range)-2\
                    else T_range[i+1] + 1e-5  # hack to prevent the rightmost
                                              # distribution value from being
                                              # excluded
                T = (T_lower+T_upper)/2
                for day in days:
                    count += len(trydata_daily_mean[
                                     (trydata_daily_mean['weekday'] == day) &
                                     (trydata_daily_mean['t'] >= T_lower) &
                                     (trydata_daily_mean['t'] < T_upper)])
                this_day.update({T: count})
                # num_days.update({(key, T): count})
            num_days.update({key: this_day})
    else:
        # Return the number of days per temperature as dict
        for i in range(0, len(T_range) - 1):
            count = 0
            T_lower = T_range[i]
            T_upper = T_range[i + 1]
            T = (T_lower + T_upper) / 2
            count += len(trydata_daily_mean[
                             (trydata_daily_mean['t'] >= T_lower) &
                             (trydata_daily_mean['t'] < T_upper)])
            num_days.update({T: count})
    return num_days


def simple_tco(object_eval_data, ignore_charging_points, daily_distance,
               cost_params):
    """Simplified TCO function for genetic iteration.

    :param object_eval_data: Dict from
        eflips.evaluation.evaluate_simulation_objects()

    :param charging_point_occupation_grouped: Dict from
        eflips.evaluation.evaluate_simulation_log()

    :param ignore_charging_points: List of charging point names to ignore
        when determining cost

    :param cost_params: Dict with cost parameters of the following form:

    cost_params = {
        'vehicle_invest': {  # including first battery
            'EN': 425000,  # €
            'GN': 530000,  # €
        },
        'vehicle_lifetime': {
            'EN': 12,
            'GN': 12
        },
        'vehicle_maintenance_cost': {
            'EN': 0.29,  # €/km
            'GN': 0.29  # €/km
        },
        'battery_invest': {
            'EN': 240000,  # €
            'GN': 139200,  # €
        },
        'battery_lifetime': {
            'EN': 6,
            'GN': 6
        },
        'energy_cost': {
            'Electricity': 0.15  # €/kWh (ALL entries must be per kWh!)
        },
        'driver_cost': 33,  # €/h
        'charging_station_invest': 400000,  # €
        'charging_station_lifetime': 20
    }
    """
    # Investments are scaled to one year by dividing by lifetime
    C_vehicles_invest = 0
    for vtype, num_vehicles in object_eval_data['num_vehicles'].items():
        num_batteries = \
            math.ceil(cost_params['vehicle_lifetime'][vtype]\
            /cost_params['battery_lifetime'][vtype])
            # max(cost_params['vehicle_lifetime'][vtype]\
            # /cost_params['battery_lifetime'][vtype] - 1, 0)
        C_vehicles_invest += num_vehicles *\
            (cost_params['vehicle_invest'][vtype] + num_batteries
             * cost_params['battery_invest'][vtype]) \
            / cost_params['vehicle_lifetime'][vtype]

    # Operational costs are determined for one year
    C_vehicles_maintenance = 0
    for vtype, km in object_eval_data['fleet_mileage'].items():
        C_vehicles_maintenance +=\
            cost_params['vehicle_maintenance_cost'][vtype] * km * 365

    C_vehicles_energy = 0
    for medium, energy in object_eval_data['fleet_consumption'].items():
        consumption = energy.energy_ref
        C_vehicles_energy += \
            cost_params['energy_cost'][medium] * consumption * 365

    C_vehicles_driver = cost_params['driver_cost'] / 3600 \
        * object_eval_data['driver_total_time'] * 365

    num_charging_stations = 0
    num_charging_slots = 0

    cp_list = []
    for cp_data in object_eval_data['charging_points'].values():
        if cp_data['location'].name not in ignore_charging_points:
            # Previously, charging stations would only be counted if they
            # were actually used. This defeats the purpose of the genetic
            # algorithm that this TCO function was developed for!
            # Changed such that construction cost for charging STATIONS is
            # always considered, regardless of whether it is used or not.
            # The number of charging SLOTS is, however, evaluated based on
            # the actual occupation. This way, the algorithm can get rid of
            # unused charging locations.
            num_charging_stations += 1
            num_charging_slots += cp_data['max_occupation']
            cp_list.append(cp_data['location'].name)
            # Previous code:
            # if cp_data['max_occupation'] > 0:
            #     num_charging_stations += 1
            #     num_charging_slots += cp_data['max_occupation']
            #     cp_list.append(cp_data['location'].name)

    # for cp_name, occupation in charging_point_occupation_grouped.items():
    #     if cp_name not in ignore_charging_points:
    #         max_occupation = max(occupation)
    #         if max_occupation > 0:
    #             num_charging_stations += 1
    #             num_charging_slots += max_occupation

    C_infra_invest = \
        (cost_params['charging_station_transformer_and_construction'] *
         num_charging_stations +
         cost_params['charging_slot_invest'] * num_charging_slots) \
        / cost_params['charging_station_lifetime']

    C_total = C_vehicles_invest + C_vehicles_maintenance + C_vehicles_energy\
        + C_vehicles_driver + C_infra_invest

    distance_total = daily_distance*365

    c_total = C_total/distance_total

    # +++ DEBUG +++
    c_vehicles_invest = C_vehicles_invest/distance_total
    c_vehicles_maintenance = C_vehicles_maintenance / distance_total
    c_vehicles_energy = C_vehicles_energy / distance_total
    c_vehicles_driver = C_vehicles_driver / distance_total
    c_infra_invest = C_infra_invest / distance_total

    # print('------------------------------------------------------------------\n')
    print('    Quantities:')
    print('    Number of vehicles: %d' % sum(object_eval_data['num_vehicles'].values()))
    print('    Number of charging stations: %d' % num_charging_stations)
    print('    Number of charging points: %d' % num_charging_slots)
    print('    Charging locations: %s' % cp_list)
    print('    Fleet mileage per day: %.2f km' % sum(object_eval_data['fleet_mileage'].values()))
    print('    Energy consumption per day: %.2f kWh' % sum([energy.energy_ref for energy in object_eval_data['fleet_consumption'].values()]))
    print('    Driver hours per day: %.2f h\n' % (object_eval_data['driver_total_time']/3600))

    print('    TCO results (€/km):')
    print('    Vehicle invest (incl. battery): %.4f' % c_vehicles_invest)
    print('    Infra invest: %.4f' % c_infra_invest)
    print('    Driver: %.4f' % c_vehicles_driver)
    print('    Energy: %.4f' % c_vehicles_energy)
    print('    Vehicle maintenance: %.4f' % c_vehicles_maintenance)
    print('    Total: %.4f\n' % c_total)

    return c_total


class TCO:
    """
    TCO model with dynamic costing; Net present value (Kapitalwertmethode)

    DJ + PB
    """

    def __init__(self, cost_data, start_year, project_duration, i_discount,
                 repeat_procurements, use_salvage_value=False, i_capital=0,
                 annualise=False, base_year=None, production_data=None,
                 **kwargs):
        """Initialise TCO calculation. cost_data must be a dict of the
        following form (example):

        cost_data = {
            'CAPEX': {
                'vehicle': {
                    'escalation':
                        dict([(year, 0.02) for year in
                              range(2015, 2030)]),
                    'escalation_type': 'compound',
                    'unit_cost': 450000,  # €
                    'base_year': 2015,
                    'quantity': 35,
                    'depreciation_period': 10,
                    'salvage_value': 'linear'
                },
                'battery': {
                    'escalation':
                        dict([(year, -0.08) for year in
                              range(2015, 2021)]
                             + [(year, -0.04) for year in
                                range(2021, 2030)]),
                    'escalation_type': 'linear',
                    'unit_cost': 1200,  # €/kWh
                    'base_year': 2015,
                    'quantity': 35 * 180,  # kWh
                    'depreciation_period': 6,
                    'salvage_value': 'linear'
                }
            },
            'OPEX': {
                'electricity': {
                    'escalation':
                        dict([(year, 0.03) for year in
                              range(2015, 2030)]),
                    'unit_cost': 0.015,  # €/kWh
                    'base_year': 2015,
                    'quantity': 2.5e6  # kWh/a
                }
            }
        }

        The keys on the first level MUST be 'CAPEX' and 'OPEX' and none of them
        may be omitted. Each category can include any number of cost components
        ('vehicle' etc.).

        'escalation' must be a dict with the following syntax:
            keys:
                all years covered by the project duration as well as all years
                between base year and project start or end (required for cost
                adjustments)
            values:
                price escalation from previous to current year

        'escalation_type' must be 'compound' or 'linear': determines how the
            value escalation is performed (if escalation_type is missing,
           'compound' is the default)
            'compound': from previous to current year
            'linear': based on first year

        'unit_cost': unit cost of the specified component at the time
            specified by 'base_year'.

        'quantity':
            for CAPEX: quantity of investment object (e.g., 35 vehicles)
            for OPEX: yearly quantity (e.g., energy consumption)

        'depreciation_period': = component lifetime. Only required
            for CAPEX.

        'salvage_value':
            determination of the salvage value at the end of the period;
            if deprecation period is longer than end of project duration
            string:'linear', 'arithm-degres' or geometr-degres
            or number: (10000)
            or string: 'adjust_sum' --> to be used only with annualised method


        Other positional arguments:

        i_discount: discount rate (Kalkulationszinssatz)

        repeat_procurements: boolean specifying whether or not to model
        repeated procurements of components where
        depreciation_period < project_duration.
        If this is set to False, the project duration MUST be set
        to the SHORTEST depreciation_period, otherwise
        the results will be incorrect.


        Keyword arguments:

        use_salvage_value:
            boolean; True: subtract the salvage value at the end of the period
            according to 'salvage_value'; if False: salvageValue = 0

        i_capital: interest rate for the lended money (WACC)
            if set to 0 --> capital is not lended
            else capital is lended and annualise must be set to True

        annualise: boolean; if True: CAPEX will be divided into equal
                   yearly sums; if False, i_capital is automatically set to
                   zero (= only own capital is used)

        base_year: Year for which all currency will be adjusted. If None,
            defaults to start_year.

        production_data: Optional dict with annual production volumes by
        category, e.g.:
            production_data = {'fleetMileage_productive': 32e6,
                              'fleetMileage_total': 40e6}
            If specified, NPV values can be determined per unit production
            volume using sumCashFlows_NPV_spec() and npv_total_spec().

        kwargs:
             overview_dict: dict with summary for stacked bar plot
            (only keys are plotted)
            overview_train = {
            'Fahrzeug': ['Fahrzeug', 'Batterie', 'Fahrzeug_Instandhaltung'],
            'Infrastruktur': ['Energieinfrastruktur',
                              'Energieinfrastruktur_Instandhaltung'],
            'Energie': ['Energie']
            }
        """
        self._cost_data = cost_data
        self._production_data = production_data
        self._start_year = start_year
        self._project_duration = project_duration
        self._i_discount = i_discount
        self._repeat_procurements = repeat_procurements
        self._use_salvage_value = use_salvage_value
        self._i_capital = i_capital
        self._annualise = annualise
        self._base_year = base_year if base_year else start_year
        if 'overview_dict' in kwargs:
            self._overview_dict = kwargs['overview_dict']
            self._sum_cashflows_npv_overview = {}
        self._calculate()

    @staticmethod
    def discount_factor(interest, duration):
        return 1 / (1 + interest) ** duration

    @staticmethod
    def crf(interest, duration):
        """capital recovery factor"""
        return (interest * (1 + interest) ** duration)/ \
               ((1 + interest) ** duration - 1)

    def _calculate(self):
        self._end_year = self._start_year + self._project_duration - 1
        self._cash_flows = {}
        self._cash_flows_npv = {}
        self._sum_cash_flows_npv_not_adjusted = {}
        self._sum_cash_flows_npv = {}
        self._sum_cash_flows_npv_spec = {}
        self._npv_total_spec = {}
        self._df_nominal = pd.DataFrame()
        self._df_npv = pd.DataFrame()

        # Determine unit cost for all years for which escalation data
        # is supplied:
        self._unit_cost = {}
        for cost_type in self._cost_data.keys():
            for component, params in self._cost_data[cost_type].items():
                self._unit_cost.update({component: {}})
                escalation_type = params['escalation_type'] if \
                    'escalation_type' in params else 'compound'
                for year in params['escalation'].keys():
                    cost = params['unit_cost']
                    increment = 1 if year >= params['base_year'] else -1
                    for t in range(params['base_year'] + increment,
                                   year + increment,
                                   increment):
                        shift = 1 if increment == -1 else 0
                        if escalation_type == 'compound':
                            cost = cost * (1 + params['escalation'][
                                t + shift]) ** increment
                        elif escalation_type == 'linear':
                            factor = params['unit_cost'] * params['escalation'][
                                t + shift]
                            cost = cost + factor * increment
                        else:
                            ValueError('Please select "compound" or "linear" '
                                       'as escalation type!')
                    self._unit_cost[component].update({year: cost})

        # CAPEX
        self._capex = {}
        use_durations = {}
        self._cash_flows.update({'CAPEX': {}})
        # helper list for 'adjust_sum' salvage (all components must be true)
        adjust_sum_list = []
        for component, params in self._cost_data['CAPEX'].items():
            if not int(params['depreciation_period']) \
                   == params['depreciation_period']:
                raise ValueError('depreciation_period must be supplied in '
                                 'whole years!')
            # Make sure depreciation period is an integer:
            params['depreciation_period'] = int(params['depreciation_period'])
            self._capex.update({component: {}})
            self._cash_flows['CAPEX'].update({component: {}})

            # Determine total usage period (including all replacements)
            if self._repeat_procurements:
                # Number of procurements during project; at least 1:
                num_procurements = math.ceil(self._project_duration /
                                            params['depreciation_period'])
            else:
                # Component only procured once at beginning of project:
                num_procurements = 1

            use_durations.update({component: num_procurements
                                            * params['depreciation_period']})

            # Years of procurement
            procurement_years = \
                [self._start_year + i * params['depreciation_period']
                 for i in range(0, num_procurements)]

            # Investment per procurement
            for year in procurement_years:
                self._capex[component].update(
                    {year: self._unit_cost[component][year] \
                           * params['quantity']})

            if self._use_salvage_value:
                salvage_value = \
                    self._cost_data['CAPEX'][component]['salvage_value']
                last_replacement_value = \
                    self._capex[component][procurement_years[-1]]
                if salvage_value == 'adjust_sum':
                    # sanity check
                    if self._annualise is not True:
                        ValueError("To use 'adjust_sum', "
                                   "annulise must be True")
                    # component has 'adjust_sum' as salvage
                    adjust_sum_list.append(True)
                    salvage = 0
                elif salvage_value == 'linear':
                    one_year_value = \
                        last_replacement_value \
                        / self._cost_data['CAPEX'][component][
                            'depreciation_period']
                    years_not_used = \
                        use_durations[component] - self._project_duration
                    salvage = - one_year_value * years_not_used
                    adjust_sum_list.append(False)
                elif (isinstance(salvage_value, int) or
                      isinstance(salvage_value, float)):
                    salvage = - salvage_value
                    adjust_sum_list.append(False)
                else:  # arithmetisch-degressiv or geometrisch-degressiv
                    # not implemented
                    salvage = 0
                    adjust_sum_list.append(False)
                if salvage != 0:
                    self._capex[component].update(
                        {self._end_year: salvage})

            # cashflow CAPEX
            if self._annualise:
                if self._i_capital != 0:  # if lended capital
                    # Annualised investments if capital is lended
                    crf = \
                        self.crf(self._i_capital,
                                 params['depreciation_period'])
                    for year in procurement_years:
                        invest = self._capex[component][year]
                        for t in range(year,
                                       year + params['depreciation_period']):
                            self._cash_flows['CAPEX'][component].update(
                                {t: invest * crf})
                else:
                    # capital not lended (no interest --> i_capital = 0;
                    # linear depreciation)
                    for year in procurement_years:
                        invest = self._capex[component][year]
                        for t in range(year,
                                       year + params['depreciation_period']):
                            self._cash_flows['CAPEX'][component].update(
                                {t: invest / params['depreciation_period']})
            else:  # do not annualise (i_capital = 0)
                for t in range(self._base_year, self._end_year):
                    invest = \
                        self._capex[component][
                            t] if t in procurement_years else 0
                    self._cash_flows['CAPEX'][component].update({t: invest})
                if self._end_year in self._capex[component]:
                    self._cash_flows['CAPEX'][component].update(
                        {self._end_year: self._capex[component][self._end_year]})
        # OPEX
        self._cash_flows.update({'OPEX': {}})
        for component, params in self._cost_data['OPEX'].items():
            self._cash_flows['OPEX'].update({component: {}})
            for year in range(self._start_year, self._end_year + 1):
                self._cash_flows['OPEX'][component].update(
                    {year: self._unit_cost[component][year]
                           * params['quantity']})

        # Net present values
        for cost_type in self._cash_flows.keys():
            self._cash_flows_npv.update({cost_type: {}})
            for component, params in self._cash_flows[cost_type].items():
                self._cash_flows_npv[cost_type].update({component: {}})
                for year, cash_flow in params.items():
                    npv = \
                        cash_flow * self.discount_factor(self._i_discount,
                                                        year - self._base_year)
                    self._cash_flows_npv[cost_type][component].update(
                        {year: npv})

        # NPV sums
        # check if any, but not all salvage values are 'adjust_sum'
        if all(adjust_sum_list) is False and any(adjust_sum_list) is True:
            raise ValueError("Salvage values for the CAPEX components "
                             "are mixed! If you want to use 'adjust_sum', "
                             "all components must have salvage value "
                             "'adjust_sum'.")
        # if 'adjust_sum' is True for all CAPEX components
        elif all(adjust_sum_list):
            for cost_type in self._cash_flows_npv.keys():
                self._sum_cash_flows_npv_not_adjusted.update({cost_type: {}})
                for component, params in \
                        self._cash_flows_npv[cost_type].items():
                    self._sum_cash_flows_npv_not_adjusted[cost_type].update(
                        {component: 0})
                    for year, cash_flow in params.items():
                        self._sum_cash_flows_npv_not_adjusted[cost_type][
                            component] += cash_flow

            # Adjust NPV sums for project length (only for CAPEX)
            self._sum_cash_flows_npv.update({'CAPEX': {}})
            for component, val in \
                    self._sum_cash_flows_npv_not_adjusted['CAPEX'].items():
                npv_adjusted = self._project_duration / use_durations[
                    component] * val
                self._sum_cash_flows_npv['CAPEX'].update(
                    {component: npv_adjusted})

            self._sum_cash_flows_npv.update(
                {'OPEX': self._sum_cash_flows_npv_not_adjusted['OPEX']})

        else:  # salvageValues are not 'adjust_sum'
            for cost_type in self._cash_flows_npv.keys():
                self._sum_cash_flows_npv.update({cost_type: {}})
                for component, params in \
                        self._cash_flows_npv[cost_type].items():
                    self._sum_cash_flows_npv[cost_type].update({component: 0})
                    for year, cash_flow in params.items():
                        self._sum_cash_flows_npv[cost_type][component] \
                            += cash_flow

        if hasattr(self, '_overview_dict'):
            for costType_new, items in self._overview_dict.items():
                self._sum_cashflows_npv_overview.update({costType_new: 0})
                for item in items:  # component in _sumCashFlows_NPV
                    for cost_type in self._sum_cash_flows_npv.keys():
                        for component, cash_flow in \
                                self._sum_cash_flows_npv[cost_type].items():
                            if component == item:
                                self._sum_cashflows_npv_overview[costType_new]\
                                    += cash_flow

        # Determine total project NPV
        self._npv_total = 0
        for cost_type in self._sum_cash_flows_npv.keys():
            for component, val in self._sum_cash_flows_npv[cost_type].items():
                self._npv_total += val

        # Determine specific NPV values
        if self._production_data is not None:
            for product, prod_volume in self._production_data.items():
                self._sum_cash_flows_npv_spec.update({product: {}})
                self._npv_total_spec.update(
                    {product: self._npv_total / (prod_volume
                                                 * self._project_duration)})
                for cost_type in self._sum_cash_flows_npv.keys():
                    self._sum_cash_flows_npv_spec[product].update({cost_type: {}})
                    for component, npv_sum in \
                            self._sum_cash_flows_npv[cost_type].items():
                        self._sum_cash_flows_npv_spec[product][cost_type].update(
                            {component: npv_sum / (prod_volume *
                                                   self._project_duration)}
                        )
        else:
            self._sum_cash_flows_npv_spec = None
            self._npv_total_spec = None

        # dataframes
        for cost_type in self._cash_flows.keys():
            for component, params in self._cash_flows[cost_type].items():
                temp_df_nom = \
                    pd.DataFrame.from_dict(
                        self._cash_flows[cost_type][component],
                        orient='index', columns=[component])
                self._df_nominal = pd.concat([self._df_nominal, temp_df_nom],
                                             axis=1)
        for cost_type in self._cash_flows_npv.keys():
            for component, params in self._cash_flows_npv[cost_type].items():
                temp_df_npv = pd.DataFrame.from_dict(
                    self._cash_flows_npv[cost_type][component],
                    orient='index', columns=[component])
                self._df_npv = pd.concat([self._df_npv, temp_df_npv], axis=1)

    # Lots of silly getters and setters to ensure proper updating of data
    # when parameters are changed
    @property
    def cost_data(self):
        return self._cost_data

    @cost_data.setter
    def cost_data(self, new_val):
        self._cost_data = new_val
        self._calculate()

    @property
    def production_data(self):
        return self._production_data

    @production_data.setter
    def production_data(self, new_val):
        self._production_data = new_val
        self._calculate()

    @property
    def start_year(self):
        return self._start_year

    @start_year.setter
    def start_year(self, new_val):
        self._start_year = new_val
        self._calculate()

    @property
    def project_duration(self):
        return self._project_duration

    @project_duration.setter
    def project_duration(self, new_val):
        self._project_duration = new_val
        self._calculate()

    @property
    def i_discount(self):
        return self._i_discount

    @i_discount.setter
    def i_discount(self, new_val):
        self._i_discount = new_val
        self._calculate()

    @property
    def i_capital(self):
        return self._i_capital

    @i_capital.setter
    def i_capital(self, new_val):
        self._i_capital = new_val
        self._calculate()

    @property
    def repeat_procurements(self):
        return self._repeat_procurements

    @repeat_procurements.setter
    def repeat_procurements(self, new_val):
        self._repeat_procurements = new_val
        self._calculate()

    @property
    def base_year(self):
        return self._base_year

    @base_year.setter
    def base_year(self, new_val):
        self._base_year = new_val
        self._calculate()

    @property
    def cash_flows(self):
        return self._cash_flows

    @property
    def cash_flows_npv(self):
        return self._cash_flows_npv

    @property
    def sum_cash_flows_npv(self):
        return self._sum_cash_flows_npv

    @property
    def sum_cash_flows_npv_spec(self):
        return self._sum_cash_flows_npv_spec

    @property
    def sum_cash_flows_npv_overview(self):
        if hasattr(self, "_sum_cashflows_NPV_overview"):
            return self._sum_cashflows_npv_overview

    @property
    def npv_total(self):
        return self._npv_total

    @property
    def npv_total_spec(self):
        return self._npv_total_spec

    @property
    def df_nominal(self):
        return self._df_nominal

    @property
    def df_NPV(self):
        return self._df_npv

    # --------PLOT FUNCTIONS---------------------

    def plot_unit_cost_development(self, unit, title='unit name',
                                   unit_value='€', plot_percentage=False,
                                   saveplot=False,
                                   filename='unit_cost_development', **kwargs):
        """plots the time development of a unit cost
        kwargs:
            figsize: sets the size of the figure"""
        fig, ax1 = plt.subplots()
        plt.title(title)
        ax1.set_xlabel(xlabel='Jahr', fontsize=10)
        if plot_percentage:
            ax1.set_ylabel(ylabel='Kosten pro Einheit [%]', fontsize=10)
        else:
            ax1.set_ylabel(ylabel='Kosten pro Einheit [' + unit_value + ']',
                           fontsize=10)
        # sorted by key, return a list of tuples
        lists = sorted(self._unit_cost[unit].items())
        x, y = zip(*lists)  # unpack a list of pairs into two tuples
        if plot_percentage:
            base = y[0]
            y = [val / base * 100 for val in y]
        plt.plot(x, y)
        if 'figsize' in kwargs:
            fig.set_size_inches(kwargs['figsize'], forward=True)
        plt.tight_layout()
        if saveplot:
            plt.savefig(filename + '.png', dpi=200)

    def plot_stacked_bar_over_period_cumulated(self, saveplot=False,
                                               xlimit=None,
                                               filename='stacked_bar_over_'
                                                        'period_cumulated',
                                               **kwargs):
        fig, ax1 = plt.subplots()
        ax1.set_xlabel(xlabel='Jahr', fontsize=10)
        ax1.set_ylabel(ylabel='Mio. €', fontsize=10)
        xlim = [self._start_year, self._end_year] if xlimit is None else xlimit
        if 'colors' in kwargs.keys():
            colors = kwargs['colors']
        else:
            colormap = plt.get_cmap('tab20c')
            colors = {'Fahrzeug': colormap(5),  # orange
                      'Batterie': colormap(9),  # green
                      'PowerPack': colormap(9),  # green
                      'Energieinfrastruktur': colormap(1),  # blue
                      'Infrastruktur': colormap(1),  # blue
                      'Fahrzeug_Instandhaltung': colormap(7),  # light orange
                      # light blue
                      'Energieinfrastruktur_Instandhaltung': colormap(3),
                      'Energie': colormap(17)}  # grey
        (self._df_npv.cumsum() / 1000000).plot.bar(stacked=True, ax=ax1,
                                                   xlim=xlim,
                                                   color=
                                                   map(colors.get,
                                                       self.df_NPV.columns)
                                                   )
        plt.tight_layout()
        plt.show()
        if saveplot:
            plt.savefig(filename + '.png', dpi=200)

    def plot_stacked_bar_over_period(self, saveplot=False,
                                     xlimit=None,
                                     filename='stacked_bar_over_period',
                                     **kwargs):
        fig, ax1 = plt.subplots()
        ax1.set_xlabel(xlabel='Jahr', fontsize=10)
        ax1.set_ylabel(ylabel='Mio. €', fontsize=10)
        xlim = [self._start_year, self._end_year] if xlimit is None else xlimit
        if 'colors' in kwargs.keys():
            colors = kwargs['colors']
        else:
            colormap = plt.get_cmap('tab20c')
            colors = {'Fahrzeug': colormap(5),  # orange
                      'Batterie': colormap(9),  # green
                      'PowerPack': colormap(9),  # green
                      'Energieinfrastruktur': colormap(1),  # blue
                      'Infrastruktur': colormap(1),  # blue
                      'Fahrzeug_Instandhaltung': colormap(7),  # light orange
                      # light blue
                      'Energieinfrastruktur_Instandhaltung': colormap(3),
                      'Energie': colormap(17)}  # grey
        (self._df_npv / 1000000).plot(kind='bar', stacked=True, ax=ax1,
                                      legend=False, xlim=xlim,
                                      color=map(colors.get,
                                                self.df_NPV.columns)
                                      )
        # ax1.set(ylim=[-4, 10])
        # fig.set_size_inches((8, 4), forward=True)
        plt.tight_layout()
        plt.show()
        if saveplot:
            plt.savefig(filename + '.png', dpi=200)

    def plot_stacked_line_over_period_cumulated(self, saveplot=False,
                                                xlimit=None,
                                                filename='stacked_line_over_'
                                                         'period_cumulated',
                                                **kwargs):
        fig, ax1 = plt.subplots()
        ax1.set_xlabel(xlabel='Jahr', fontsize=10)
        ax1.set_ylabel(ylabel='Mio. €', fontsize=10)
        xlim = [self._start_year, self._end_year] if xlimit is None else xlimit
        if 'colors' in kwargs.keys():
            colors = kwargs['colors']
        else:
            colormap = plt.get_cmap('tab20c')
            colors = {'Fahrzeug': colormap(5),  # orange
                      'Batterie': colormap(9),  # green
                      'PowerPack': colormap(9),  # green
                      'Energieinfrastruktur': colormap(1),  # blue
                      'Infrastruktur': colormap(1),  # blue
                      'Fahrzeug_Instandhaltung': colormap(7),  # light orange
                      # light blue
                      'Energieinfrastruktur_Instandhaltung': colormap(3),
                      'Energie': colormap(17)}  # grey
        (self._df_npv.cumsum() / 1000000).plot.area(ax=ax1, stacked=True,
                                                    xlim=xlim,
                                                    color=
                                                    map(colors.get,
                                                        self.df_NPV.columns)
                                                    )
        plt.tight_layout()
        plt.show()
        if saveplot:
            plt.savefig(filename + '.png', dpi=200)

    def plot_sum_stacked(self, xlabel='Triebzug', plot_as_summary=False,
                         saveplot=False, filename='sum_stacked',
                         annotate=False, **kwargs):
        """plot stacked NPV sum;
            kwargs:
            colors: dict with components as keys and colors as value
        """
        fig, ax1 = plt.subplots()
        ax1.set_xlabel(xlabel=xlabel, fontsize=10)
        ax1.set_ylabel(ylabel='Mio. €', fontsize=10)
        if 'colors' in kwargs.keys():
            colors = kwargs['colors']
        else:
            colormap = plt.get_cmap('tab20c')
            colors = {'Fahrzeug': colormap(5),  # orange
                      'Batterie': colormap(9),  # green
                      'PowerPack': colormap(9),  # green
                      'Energieinfrastruktur': colormap(1),  # blue
                      'Infrastruktur': colormap(1),  # blue
                      'Fahrzeug_Instandhaltung': colormap(7),  # light orange
                      # light blue
                      'Energieinfrastruktur_Instandhaltung': colormap(3),
                      'Energie': colormap(17)}  # grey
        bottom = 0
        if plot_as_summary is False:
            for costType in self.sum_cash_flows_npv.keys():
                for component, value in \
                        self.sum_cash_flows_npv[costType].items():
                    plt.bar(0, value / 1000000, width=0.8, bottom=bottom,
                            color=colors[component],
                            label=component.replace('_', ': '))
                    bottom += value / 1000000
        else:
            if self._sum_cashflows_npv_overview:
                for costType, value in self._sum_cashflows_npv_overview.items():
                    plt.bar(0, value / 1000000, width=0.8, bottom=bottom,
                            color=colors[costType],
                            label=costType.replace('_', ': '))
                    bottom += value / 1000000
        if annotate:
            ax1.annotate("{:0.1f}".format(bottom),
                         (0, bottom),
                         xytext=(0, 5),
                         textcoords='offset pixels',
                         fontsize=8,
                         horizontalalignment='center',
                         verticalalignment='bottom'
                         )
        plt.xticks([])
        ax1.set(xlim=[-2, 2])
        handles, labels = ax1.get_legend_handles_labels()
        ax1.legend(handles[::-1], labels[::-1], loc='upper right',
                   fancybox=True, fontsize=8)
        plt.tight_layout()
        plt.show()
        if saveplot:
            plt.savefig(filename + '.png', dpi=200)

    def plot_sum_separated(self, plot_percentage=False, saveplot=False,
                           filename='sum_separated', annotate=False):
        fig, ax1 = plt.subplots()
        if plot_percentage is False:
            ax1.set_ylabel(ylabel='Mio. €', fontsize=10)
            (self._df_npv.sum() / 1000000).plot.bar(ax=ax1)
            if annotate:
                for ind, k in enumerate(self._df_npv.sum().index):
                    ax1.annotate("{:0.1f}".format(self._df_npv.sum()[k]),
                                 (ind, (self._df_npv.sum()[k]) / 1000000),
                                 xytext=(0, 5),
                                 textcoords='offset pixels',
                                 fontsize=8,
                                 horizontalalignment='center',
                                 verticalalignment='bottom'
                                 )
        else:
            ax1.set_ylabel(ylabel='Prozent von NPV [%]', fontsize=10)
            ax1.set(xlim=[0, 40])
            ans = self._df_npv.sum() / self._df_npv.sum().sum() * 100
            ans.plot.bar(ax=ax1)
            if annotate:
                for ind, k in enumerate(ans.index):
                    ax1.annotate("{:0.1f}".format(ans[k]) + "%",
                                 (ind, (ans[k])),
                                 xytext=(0, 5),
                                 textcoords='offset pixels',
                                 fontsize=8,
                                 horizontalalignment='center',
                                 verticalalignment='bottom'
                                 )
        plt.tick_params(
            axis='x',
            which='both',
            labelsize=8)
        plt.show()
        plt.tight_layout()
        if saveplot:
            plt.savefig(filename + '.png', dpi=200)


def plot_mutiple_tco(list_with_tcos, list_with_names, plot_summary=False,
                     plot_percentage=False, saveplot=False,
                     filename='sum_separated', annotate=False, grid_on=False,
                     plot_component_percentage=False,
                     fileformat=".png", **kwargs):
    """list_with_tcos is a list with TCO objects;
        the names are user for the xticks
        plot_percentage takes the sum of the first tco object and set is
        as baseline (100%)
        kwargs:
            colors: dict with components as keys and colors as value
        """
    fig, ax1 = plt.subplots()
    if grid_on:
        ax1.yaxis.grid(linewidth=.5, color="grey", linestyle="--")
    if plot_percentage:
        ax1.set_ylabel(ylabel='%', fontsize=10)
    else:
        ax1.set_ylabel(ylabel='Mio. €', fontsize=10)
    if 'colors' in kwargs.keys():
        colors = kwargs['colors']
    else:
        colormap = plt.get_cmap('tab20c')
        colors = {'Fahrzeug': colormap(5),  # orange
                  'Batterie': colormap(9),  # green
                  'PowerPack': colormap(9),  # green
                  'Energieinfrastruktur': colormap(1),  # blue
                  'Infrastruktur': colormap(1),  # blue
                  'Fahrzeug_Instandhaltung': colormap(7),  # light orange
                  # light blue
                  'Energieinfrastruktur_Instandhaltung': colormap(3),
                  'Energie': colormap(17)}  # grey
    xvalues = []
    xticks = []
    idx = 0
    if plot_percentage:
        base_value = list_with_tcos[0].npv_total
    for tco, name in zip(list_with_tcos, list_with_names):
        bottom = 0
        xvalues.append(idx)
        xticks.append(name)
        if plot_summary:
            if hasattr(tco, '_sum_cashflows_NPV_overview'):
                for costType, value in tco.sum_cash_flows_npv_overview.items():
                    if plot_percentage:
                        val = value / base_value * 100
                    else:
                        val = value / 1000000
                    plt.bar(idx, val, width=0.8, bottom=bottom,
                            color=colors[costType],
                            label=costType.replace('_', ': '))
                    if plot_component_percentage:
                        component_percentage = \
                            round(value / tco.npv_total * 100)
                        ax1.annotate(str(component_percentage) + " %",
                                     (idx, bottom + val / 2),
                                     xytext=(0, 0),
                                     textcoords='offset pixels',
                                     fontsize=6,
                                     color="white",
                                     horizontalalignment='center',
                                     verticalalignment='center')
                    bottom += val
        else:  # plot all components
            for costType in tco.sum_cash_flows_npv.keys():
                for component, value in tco.sum_cash_flows_npv[costType].items():
                    if plot_percentage:
                        val = value / base_value * 100
                    else:
                        val = value / 1000000
                    plt.bar(idx, val, width=0.8, bottom=bottom,
                            color=colors[component],
                            label=component.replace('_', ': '))
                    if plot_component_percentage:
                        component_percentage = value / tco.npv_total * 100
                        ax1.annotate("{:0.1f}".format(component_percentage) + " %",
                                     (idx, bottom + val / 2),
                                     xytext=(0, 0),
                                     textcoords='offset pixels',
                                     fontsize=6,
                                     color="white",
                                     horizontalalignment='center',
                                     verticalalignment='center')
                    bottom += val
        if annotate:
            str_attr = "%" if plot_percentage else ""
            ax1.annotate("{:0.1f}".format(bottom) + str_attr,
                         (idx, bottom),
                         xytext=(0, 5),
                         textcoords='offset pixels',
                         fontsize=8,
                         horizontalalignment='center',
                         verticalalignment='bottom'
                         )
        idx += 1

    plt.xticks(xvalues, xticks)
    plt.tick_params(
        axis='x',
        which='both',
        labelsize=8)
    ax1.set(xlim=[-1, len(list_with_tcos)])

    handles, labels = ax1.get_legend_handles_labels()
    handle_list, label_list = [], []
    for handle, label in zip(handles, labels):
        if label not in label_list:
            handle_list.append(handle)
            label_list.append(label)
    # ax1.legend(handle_list[::-1], label_list[::-1],
    #            bbox_to_anchor=(0, -0.25, 1, 0.2), mode="expand",
    #            borderaxespad=0., fancybox=True, fontsize=7, ncol=3)
    ax1.legend(handle_list, label_list, bbox_to_anchor=(0, -0.30, 1, 0.2),
               mode="expand", borderaxespad=0.,
               fancybox=True, fontsize=7, ncol=3)
    plt.show()
    if saveplot:
        plt.savefig(filename + fileformat, dpi=200, bbox_inches='tight')
