# -*- coding: utf-8 -*-
"""
Created on Sat Mar 16 13:38:11 2024

@author: cortespea
"""
from matplotlib import pyplot as plt
from numpy.testing import assert_allclose
import biosteam as bst
import numpy as np
import pandas as pd
from biosteam.utils import colors as c
from colorpalette import Color
from scipy import interpolate
from scipy.ndimage import gaussian_filter
from math import sqrt
from warnings import catch_warnings, filterwarnings
from typing import NamedTuple
from . import systems
import os
import pickle
import thermosteam as tmo
from scipy.integrate import romb
from scipy.optimize import minimize
from warnings import warn
from biosteam import report
import openpyxl
import json

__all__ = (
    'BenchmarkModel',
    'run_monte_carlo',
    'plot_monte_carlo',
    'plot_benchmark',
    'plot_profile',
    'register',
    'all_systems',
    'test_convergence',
    'save_stream_tables_and_specifications',
    'save_simulation_errors',
    'Tracker',
    'test_convergence_rigorous',
)

# %% Make simulation rigorous to achieve lower tolerances

bst.MultiStageEquilibrium.default_maxiter = 20
bst.MultiStageEquilibrium.default_max_attempts = 10
bst.MultiStageEquilibrium.default_molar_tolerance = 1e-9
bst.MultiStageEquilibrium.default_relative_molar_tolerance = 1e-12
bst.MultiStageMixerSettlers.default_maxiter = 50
tmo.BubblePoint.maxiter = 100 # -> 50 [-]
tmo.DewPoint.maxiter = 100 # -> 50 [-]
tmo.BubblePoint.T_tol = 1e-16 # -> 1e-9 [K]
tmo.DewPoint.T_tol = 1e-16 # -> 1e-9 [K]
tmo.BubblePoint.P_tol = 1e-9 # -> 1e-3 [Pa]
tmo.DewPoint.P_tol = 1e-9 # -> 1e-3 [Pa]
tmo.VLE.T_tol = 1e-12 # -> 5e-8 [K]
tmo.VLE.P_tol = 1e-12 # -> 1. [Pa]
tmo.VLE.maxiter = 50 # -> 20 [-]
tmo.VLE.T_tol = 1e-12 # -> 5e-8 [K]
tmo.VLE.P_tol = 1e-9 # -> 1. [Pa]
tmo.VLE.H_hat_tol = 1e-12 # -> 1e-6 [J/g]
tmo.VLE.S_hat_tol = 1e-12 # -> 1e-6 [J/g/K]
tmo.VLE.V_tol = 1e-12 # -> 1e-6 [mol %]
tmo.VLE.x_tol = 1e-12 # -> 1e-9 [mol %]
tmo.VLE.y_tol = 1e-12 # -> 1e-9 [mol %]
tmo.LLE.shgo_options = dict(f_tol=1e-9, minimizer_kwargs=dict(f_tol=1e-9))
tmo.LLE.differential_evolution_options = {'seed': 0, 'popsize': 12, 'tol': 1e-9}
tmo.LLE.pseudo_equilibrium_outer_loop_options = dict(
    xtol=1e-16, maxiter=200, checkiter=False, 
    checkconvergence=False, convergenceiter=20,
)
tmo.LLE.pseudo_equilibrium_inner_loop_options = dict(
    xtol=1e-12, maxiter=200, checkiter=False,
    checkconvergence=False, convergenceiter=20,
)
tmo.LLE.default_composition_cache_tolerance = 1e-16
tmo.LLE.default_temperature_cache_tolerance = 1e-16
bst.ShortcutColumn.iter_solver_kwargs = dict(
    xtol=1e-16,
    checkiter=False,
    checkconvergence=False, 
    convergenceiter=20,
)
# bst.units.stage.PhasePartition.S_relaxation_factor = 0
# bst.units.stage.PhasePartition.B_relaxation_factor = 0
# bst.units.stage.PhasePartition.K_relaxation_factor = 0
# bst.units.stage.PhasePartition.T_relaxation_factor = 0

# %% Uncertainty analysis

class BenchmarkModel:
    
    def __init__(self):
        model = bst.Model(None, specification=lambda: None)
        parameter = model.parameter
        self.model = model
        
        def load_trackers():
            system = 'acetic_acid_complex'
            self.sm_tracker = Tracker(
                system, 'sequential modular',
                extraction_stages=self.extraction_stages, 
                raffinate_distillation_stages=self.raffinate_distillation_stages,
                extract_distillation_stages=self.raffinate_distillation_stages,
                atol=1e-10
            )
            self.sm_system = self.sm_tracker.system
            self.sm_recycles = self.sm_system.get_all_recycles()
            self.po_tracker = Tracker(
                system, 'phenomena oriented', 
                extraction_stages=self.extraction_stages, 
                raffinate_distillation_stages=self.raffinate_distillation_stages,
                extract_distillation_stages=self.raffinate_distillation_stages,
                atol=1e-10
            )
            self.po_system = self.po_tracker.system
            self.po_recycles = self.po_system.get_all_recycles()
        
        @parameter(units='-', bounds=[1, 12], hook=lambda x: int(round(x)))
        def set_extraction_stages(extraction_stages):
            self.extraction_stages = extraction_stages
        
        @parameter(units='-', bounds=[1, 12], hook=lambda x: int(round(x)))
        def set_raffinate_distillation_stages(raffinate_distillation_stages):
            self.raffinate_distillation_stages = raffinate_distillation_stages
            
        @parameter(units='-', bounds=[1, 12], hook=lambda x: int(round(x)))
        def set_extract_distillation_stages(extract_distillation_stages):
            self.extract_distillation_stages = extract_distillation_stages
        
        # benchmark = tracker.benchmark()
        # chemicals = [i.ID for i in bst.settings.chemicals]
        # for i, (flows, T) in enumerate(zip(self.material_flows, self.Ts)):
        #     @parameter(units='K', name=f"Recycle {i}", element='temperature', bounds=[T - 15, T + 15])
        #     def set_temperature(T, index=i):
        #         return
        #         self.sm_recycles[index].T = T
        #         self.po_recycles[index].T = T
                
        #     for chemical, flow in zip(chemicals, flows):
        #         @parameter(units='-', name=chemical, element=f"Recycle {i}", bounds=[-3, 3])
        #         def set_chemical_flow(flow, index=i, chemical=chemical, flow_max=flow):
        #             flow = flow_max * 10 ** flow
        #             self.sm_recycles[index].imol[chemical] = flow
        #             self.po_recycles[index].imol[chemical] = flow
        
        @model.metric(units='%', element='Sequential modular')
        def distance_from_steady_state():
            sm_b = self.sm_tracker.benchmark()
            po_b = self.po_tracker.benchmark()
            sm_e = sm_b['Error history']
            po_e = po_b['Error history']
            t_lb = max(po_e[0].time, sm_e[0].time)
            t_ub = min(po_e[0].time, sm_e[0].time)
            x, y = zip(*sm_e)
            t = np.linspace(t_lb, t_ub, 2**10 + 1)
            sm_y = interpolate.interp1d(x, y, bounds_error=False)(t)
            x, y = zip(*sm_e)
            po_y = interpolate.interp1d(x, y, bounds_error=False)(t)
            return romb(po_y / sm_y, t[1] - t[0]) / (t_ub - t_lb)
          
        @model.metric(units='%', element='Phenomena-oriented')
        def distance_from_steady_state():
            sm_b = self.sm_tracker.benchmark()
            po_b = self.po_tracker.benchmark()
            sm_e = sm_b['Error history']
            po_e = po_b['Error history']
            t_lb = max(po_e[0].time, sm_e[0].time)
            t_ub = min(po_e[0].time, sm_e[0].time)
            x, y = zip(*sm_e)
            t = np.linspace(t_lb, t_ub, 2**10 + 1)
            sm_y = interpolate.interp1d(x, y, bounds_error=False)(t)
            x, y = zip(*sm_e)
            po_y = interpolate.interp1d(x, y, bounds_error=False)(t)
            return romb(po_y / sm_y, t[1] - t[0]) / (t_ub - t_lb)
        
        @model.metric(units='%')
        def average_relative_distance_from_steady_state():
            sm_b = self.sm_tracker.benchmark()
            po_b = self.po_tracker.benchmark()
            sm_e = sm_b['Error history']
            po_e = po_b['Error history']
            t_lb = max(po_e[0].time, sm_e[0].time)
            t_ub = min(po_e[0].time, sm_e[0].time)
            x, y = zip(*sm_e)
            t = np.linspace(t_lb, t_ub, 2**10 + 1)
            sm_y = interpolate.interp1d(x, y, bounds_error=False)(t)
            x, y = zip(*sm_e)
            po_y = interpolate.interp1d(x, y, bounds_error=False)(t)
            return romb(po_y / sm_y, t[1] - t[0]) / (t_ub - t_lb)
        
        @model.metric(units='s')
        def sequential_modular_simulation_time():
            return self._time_sm
        
        @model.metric(units='s')
        def phenomena_oriented_simulation_time():
            return self._time_po
        
        @model.metric(units='-')
        def distance():
            return self._distance

def run_monte_carlo(N=50, system='alcohol_wide_flash', autosave=True, autoload=True):
    bm = BenchmarkModel(system)
    samples = bm.model.sample(N, rule='L', seed=0)
    bm.model.load_samples(samples)
    bm.model.evaluate(
        notify=10,
        autosave=autosave, autoload=autoload,
        file=os.path.join(simulations_folder, f'{system}_MC{N}')
    )
    bm.model.table.to_excel(os.path.join(simulations_folder, f'{system}_MC{N}.xlsx'))
    bm.model.table.to_excel(os.path.join(simulations_folder, f'{system}_MC.xlsx'))

def plot_monte_carlo(system='alcohol_wide_flash'):
    file = os.path.join(simulations_folder, f'{system}_MC.xlsx')
    df = pd.read_excel(file, header=[0, 1], index_col=[0])
    plt.scatter(df.iloc[:, 0], df.iloc[:, -4])
    plt.show()

# %% System creation

try:
    images_folder = os.path.join(os.path.dirname(__file__), 'images')
    simulations_folder = os.path.join(os.path.dirname(__file__), 'simulations')
except:
    images_folder = os.path.join(os.getcwd(), 'images')
    simulations_folder = os.path.join(os.getcwd(), 'simulations')

all_systems = {}
system_titles = {}
system_convergence_times = {}
system_tickmarks = {}
system_labels = {}
system_yticks = {}
try:
    with open('system_stages.json') as f: system_stages = json.load(f)
except:
    system_stages = {}

def register(name, title, time, tickmarks, label, yticks=None):
    f = getattr(systems, 'create_system_' + name, None) or getattr(systems, 'create_' + name + '_system')
    if yticks is None: yticks = [(-10, -5, 0, 5), (-10, -5, 0, 5)]
    if name not in system_stages: 
        sys = f(None)
        system_stages[name] = len(sys.stages)
    all_systems[name] = f
    system_titles[name] = title
    system_convergence_times[name] = time
    system_tickmarks[name] = tickmarks
    system_labels[name] = label
    system_yticks[name] = yticks

# register(
#     'acetic_acid_reactive_purification', 'Acetic acid reactive purification',
#     10, [2, 4, 6, 8, 10], 'AA\nr. sep.'
# )
register(
    'acetic_acid_complex', 'Rigorous system',
    240, [0, 60, 120, 180, 240], 'AcOH\nindustrial\ndewatering', 
    [(-15, -10, -5, 0, 5), (-15, -10, -5, 0, 5)],
    # [(-5, -2.5, 0, 2.5, 5), (-8, -5, -2, 1, 4)],
)
register(
    'acetic_acid_simple', 'Subsystem',
    40, [0, 8, 16, 24, 32], 'AcOH\npartial\ndewatering',
    [(-15, -10, -5, 0, 5), (-15, -10, -5, 0, 5)],
    # [(-15, -10, -5, 0, 5, 10), (-15, -10, -5, 0, 5, 10)],
)
register(
    'acetic_acid_complex_decoupled', 'Shortcut system',
    25, [5, 10, 15, 20, 25], 'AcOH\nshortcut\ndewatering',
    [(-15, -10, -5, 0, 5), (-15, -10, -5, 0, 5)],
)
# register(
#     'alcohol_narrow_flash', 'Alcohol flash narrow',
#     0.05, [0.01, 0.02, 0.03, 0.04, 0.05], 'Alcohol\nflash\nnarrow'
# )
# register(
#     'alcohol_wide_flash', 'Alcohol flash wide',
#     0.05, [0.01, 0.02, 0.03, 0.04, 0.05], 'Alcohol\nflash\nwide'
# )
register(
    'butanol_purification', 'Butanol purification',
    1, [0, 0.1, 0.2, 0.3, 0.4, 0.5], 'BtOH\nseparation',
    [(-15, -10, -5, 0, 5), (-15, -10, -5, 0, 5)],
)
register(
    'ethanol_purification', 'Ethanol purification',
    0.2, [0, 0.03, 0.06, 0.09, 0.12], 'EtOH\nseparation',
    [(-15, -10, -5, 0, 5), (-15, -10, -5, 0, 5)],
)
# register(
#     'hydrocarbon_narrow_flash', 'Hydrocarbon flash narrow',
#     0.05, [0.01, 0.02, 0.03, 0.04, 0.05], 'Alkane\nflash\nnarrow'
# )
# register(
#     'hydrocarbon_wide_flash', 'Hydrocarbon flash wide',
#     0.1, [0.02, 0.04, 0.06, 0.08, 0.10], 'Alkane\nflash\nwide'
# )
# register(
#     'lactic_acid_purification', 'Lactic acid purification',
#     10, [2, 4, 6, 8, 10], 'LA\nsep.'
# )
register(
    'haber_bosch_process', 'Haber-Bosch',
    0.03, [0, 0.004, 0.010, 0.015, 0.020], 'Haber-Bosch\nammonia\nproduction',
    [[-10, -7.5, -5, -2.5, 0], [-10, -7.5, -5, -2.5, 0]],
)

with open('system_stages.json', 'w') as file: json.dump(system_stages, file)

# %% Testing

def test_convergence(systems=None, alg=None, maxiter=None):
    if maxiter is None: maxiter = 200
    if systems is None: systems = list(all_systems)
    elif isinstance(systems, str): systems = [systems]
    outs = []
    with catch_warnings():
        filterwarnings('ignore')
        time = bst.TicToc()
        for sys in systems:
            f_sys = all_systems[sys]
            new = []
            print(sys)
            if alg is None or alg == 'po': 
                bst.F.set_flowsheet('PO')
                po = f_sys('phenomena oriented')
                po.set_tolerance(rmol=1e-5, mol=1e-5, subsystems=True, method='fixed-point', maxiter=maxiter)
                time.tic()
                po.simulate()
                print('- Phenomena oriented', time.toc())
                new.append(po)
            if alg is None or alg == 'sm': 
                bst.F.set_flowsheet('SM')
                sm = f_sys('sequential modular')
                sm.set_tolerance(rmol=1e-5, mol=1e-5, subsystems=True, method='fixed-point', maxiter=maxiter)
                time.tic()
                sm.simulate()
                print('- Sequential modular', time.toc())
                new.append(sm)
            outs.append(new)
            if alg is None:
                for s_sm, s_dp in zip(sm.streams, po.streams):
                    actual = s_sm.mol
                    value = s_dp.mol
                    try:
                        assert_allclose(actual, value, rtol=0.01, atol=0.01)
                    except:
                        if s_sm.source:
                            print(f'- Multiple steady stages for {s_sm}, {s_sm.source}-{s_sm.source.outs.index(s_sm)}: sm-{actual} po-{value}')
                        else:
                            print(f'- Multiple steady stages for {s_sm}, {s_sm.sink.ins.index(s_sm)}-{s_sm.sink}: sm-{actual} po-{value}')
    return outs

# %% Stream tables and specifications

def save_stream_tables_and_specifications(systems=None):
    if systems is None: systems = list(all_systems)
    for sys in systems:
        po = Tracker(sys, 'phenomena oriented')
        for i in range(50): po.run()
        with po.system.stage_configuration() as conf:
            for i in conf.streams:
                if i.ID == '': i.ID = ''
        name = system_labels[sys].replace('\n', ' ')
        file_name = f'{name}.xlsx'
        file = os.path.join(simulations_folder, file_name)
        po.system.save_report(
            file=file,
            sheets={
                'Flowsheet',
                'Stream table',
                'Specifications',
                'Reactions',
            },
            stage=True,
        )

# %% Simulation errors

def save_simulation_errors(systems=None):
    if systems is None: systems = list(all_systems)
    values = []
    for sys in systems:
        file_name = f"{sys}_steady_state"
        file = os.path.join(simulations_folder, file_name)
        values.append([
            Convergence(
                all_systems[sys](i), file
            ).benchmark
            for i in ('phenomena-oriented', 'sequential-modular')
        ])
    df = pd.DataFrame(
        values, 
        [system_labels[i].replace('\n', ' ') for i in systems], 
        ('Phenomena-based', 'Sequential modular')
    )
    file_name = 'Simulation times.xlsx'
    file = os.path.join(simulations_folder, file_name)
    df.to_excel(file)
    return df


# %% Convergence time

def convergence_time(sm, po):
    ysm = np.array(sm)
    ypo = np.array(po)
    cutoff = ysm.min() + 1
    sm_index = sum(ysm > cutoff)
    po_index = sum(ypo > cutoff)
    return sm['Time'][sm_index], po['Time'][po_index]


# %% Profiling and benchmarking utilities

class ErrorPoint(NamedTuple):
    time: float; error: float

default_steady_state_cutoff = 1
    
def get_flows(streams, phases):
    flows = []
    for i, stream_phases in zip(streams, phases):
        if len(stream_phases) == 1:
            flows.append(i.mol)
            continue
        for j in stream_phases:
            flows.append(i.imol[j])
    return np.array(flows)

def steady_state_error(profile, steady_state_cutoff=None):
    if steady_state_cutoff is None: steady_state_cutoff = default_steady_state_cutoff
    minimum_error = np.log10(10 ** profile['Component flow rate error'][-1] + 10 ** profile['Temperature error'][-1]) 
    return minimum_error + steady_state_cutoff
    
def benchmark(profile, steady_state_error=None):
    if steady_state_error is None: steady_state_error = steady_state_error(profile)
    time = profile['Time']
    error = np.log10(10 ** profile['Component flow rate error'] + 10 ** profile['Temperature error'])
    if np.isnan(error).any(): breakpoint()
    time = interpolate.interp1d(error, time, bounds_error=False)(steady_state_error)
    if np.isnan(error).any(): breakpoint()
    return time 
    
def test_convergence_rigorous(system=None):
    if system is None: system = 'acetic_acid_simple'
    algorithm = 'Phenomena oriented'
    file_name = f"{system}_{algorithm}_steady_state"
    file = os.path.join(simulations_folder, file_name)
    L, R = [
        Convergence(
            all_systems[system](algorithm), file
        ).results[0]
        for algorithm in ('Sequential modular', 'Phenomena oriented')
    ]
    print(np.abs(L - R))
    breakpoint()

class Convergence:
    
    def __init__(self, system, file):
        system.flowsheet.clear()
        try:
            with open(file, 'rb') as f: 
                *results, benchmark = pickle.load(f)
        except: 
            try: system.simulate()
            except: pass
            if system.algorithm == 'Phenomena oriented':
                N = 500
            else:
                N = 50
            for i in range(N): system.run()
            streams, adiabatic_stages, all_stages = streams_and_stages(system)
            cfe, te = zip(*[i._simulation_error() for i in all_stages])
            phases = [i.phases for i in streams]
            flows = get_flows(streams, phases)
            system.run()
            cfe, te = zip(*[i._simulation_error() for i in all_stages])
            flows_new = get_flows(streams, phases)
            benchmark = sum(cfe) + sum(te) + np.abs(flows_new - flows).sum()
            Ts = np.array([i.T for i in streams])
            results = flows_new, Ts, [i.node_tag for i in streams], phases
            with open(file, 'wb') as f: pickle.dump((*results, benchmark), f)
        self.results = results
        self.benchmark = benchmark
        

class Tracker:
    __slots__ = (
        'system', 'run', 'streams', 
        'adiabatic_stages', 'stages',
        'profile_time', 'rtol', 'atol',
        'kwargs', 'name', 'algorithm'
    )
    
    def __init__(self, name, algorithm, rtol=1e-16, atol=1e-9, **kwargs):
        sys = all_systems[name](algorithm, **kwargs)
        sys._setup_units()
        sys.flowsheet.clear()
        self.system = sys
        self.name = name
        self.kwargs = kwargs
        if sys.algorithm == 'Sequential modular':
            self.run = sys.run_sequential_modular
        elif sys.algorithm == 'Phenomena oriented':
            self.run = sys.run_phenomena
        else:
            raise ValueError('invalid algorithm')
        self.algorithm = algorithm
        self.rtol = rtol
        self.atol = atol
        self.profile_time = system_convergence_times[name]
        self.streams, self.adiabatic_stages, self.stages, = streams_and_stages(sys)
        
    def estimate_steady_state(self, load=True): # Uses optimization to estimate steady state
        options = '_'.join(['{i}_{j}' for i, j in self.kwargs.items()])
        algorithm = self.algorithm
        if options:
            file_name = f"{self.name}_{options}_{algorithm}_steady_state"
        else:
            file_name = f"{self.name}_{algorithm}_steady_state"
        file = os.path.join(simulations_folder, file_name)
        c = Convergence(
            all_systems[self.name](algorithm, **self.kwargs), file
        )
        # L, R = [
        #     Convergence(all_systems[self.name](algorithm, **self.kwargs), file).results[0]
        #     for algorithm in ('Sequential modular', 'Phenomena oriented')
        # ]
        # print(np.abs(L - R))
        # breakpoint()
        print('Error', algorithm, c.benchmark)
        print('-----------------')
        return c.results
        
    # def estimate_steady_state(self, load=True): # Uses optimization to estimate steady state
    #     options = '_'.join(['{i}_{j}' for i, j in self.kwargs.items()])
    #     if options:
    #         file_name = f"{self.name}_{options}_steady_state"
    #     else:
    #         file_name = f"{self.name}_steady_state"
    #     file = os.path.join(simulations_folder, file_name)
    #     if load:
    #         try:
    #             with open(file, 'rb') as f: return pickle.load(f)
    #         except: pass
    #     sys = all_systems[self.name]('phenomena-oriented', **self.kwargs)
    #     try: sys.simulate()
    #     except: pass
    #     for i in range(100): sys.run()
    #     sys.flowsheet.clear()
    #     p = bst.units.stage.PhasePartition
    #     settings = (
    #         p.S_relaxation_factor, p.B_relaxation_factor, 
    #         p.K_relaxation_factor, p.T_relaxation_factor
    #     )
    #     p.S_relaxation_factor = 0
    #     p.B_relaxation_factor = 0
    #     p.K_relaxation_factor = 0
    #     p.T_relaxation_factor = 0
    #     try:
    #         results = self._estimate_steady_state(sys)
    #         with open(file, 'wb') as f: pickle.dump(results, f)
    #     finally:
    #         (p.S_relaxation_factor, p.B_relaxation_factor, 
    #          p.K_relaxation_factor, p.T_relaxation_factor) = settings
    #     return results
    
    # def _estimate_steady_state(self, system):
    #     po = system
    #     streams, adiabatic_stages, all_stages = streams_and_stages(po)
    #     flows = np.array(sum([i._imol._parent.data.rows for i in streams], []))
    #     Ts = np.array([i.T for i in streams])
    #     stages = []
    #     shortcuts = []
    #     for i in po.units:
    #         if hasattr(i, 'stages'):
    #             stages.extend(i.stages)
    #         elif isinstance(i, bst.StageEquilibrium):
    #             stages.append(i)
    #         elif isinstance(i, bst.Distillation):
    #             shortcuts.append(i)
    #             i._update_equilibrium_variables()
    #         elif not isinstance(i, (bst.Mixer, bst.Separator, bst.SinglePhaseStage)):
    #             pass
            
    #     def get_S(u): # Shortcut column
    #         if hasattr(u, '_distillate_recoveries'):
    #             d = u._distillate_recoveries
    #             b = (1 - d)
    #             # mask = b == 0
    #             # b[mask] = 1
    #             S = d / b
    #         else:
    #             S = u.K * u.B
    #         # S[mask] = np.inf
    #         return S
        
    #     def set_S(u, S):
    #         u._distillate_recoveries = S / (1 + S)
        
    #     all_stages = stages + shortcuts
    #     N_chemicals = po.units[0].chemicals.size
    #     S = np.array([get_S(i) for i in all_stages])
    #     S_full = S
    #     S_index = S_index = [
    #         i for i, j in enumerate(all_stages)
    #         if not (getattr(j, 'B_specification', None) == 0 or getattr(j, 'B_specification', None) == np.inf)
    #     ]
    #     lle_stages = []
    #     vle_stages = []
    #     for i in S_index:
    #         s = all_stages[i]
    #         if not isinstance(s, bst.StageEquilibrium): continue
    #         phases = getattr(s, 'phases', None)
    #         if phases == ('g', 'l'):
    #             vle_stages.append(s)
    #         elif phases == ('L', 'l'):
    #             lle_stages.append(s)
    #     S = S[S_index]
    #     N_S_index = len(S_index)
    #     lnS = np.log(S).flatten()
    #     count = [0]
        
    #     energy_error = lambda stage: abs(
    #         (sum([i.H for i in stage.outs]) - sum([i.H for i in stage.ins])) / sum([i.C for i in stage.outs])
    #     )
        
    #     def B_error(stage):
    #         B = getattr(stage, 'B_specification', None)
    #         if B is not None:
    #             top, bottom = stage.partition.outs
    #             return 100 * (top.F_mol / bottom.F_mol - B)
    #         else:
    #             return 0
        
    #     def T_equilibrium_error(stage):
    #         if len(stage.outs) == 2:
    #             top, bottom = stage.outs
    #         else:
    #             top, bottom = stage.partition.outs
    #         return (top.dew_point_at_P().T - bottom.T)
        
    #     def lnS_objective(lnS):
    #         S_original = np.exp(lnS)
    #         S = S_full
    #         S[S_index] = S_original.reshape([N_S_index, N_chemicals])
    #         for i in S_index:
    #             s = all_stages[i]
    #             if hasattr(s, '_distillate_recoveries'):
    #                 set_S(s, S[i])
    #             elif getattr(s, 'B_specification', None) is not None:
    #                 s.K = S[i] / s.B_specification
    #             else:
    #                 s.B = 1 # Work around S = K * B
    #                 s.K = S[i]
    #         with po.stage_configuration(aggregated=False) as conf:
    #             conf._solve_material_flows(composition_sensitive=False)
    #         # breakpoint()
    #         for i in vle_stages:
    #             partition = i.partition
    #             # print('----')
    #             # print(i.K * i.B)
    #             partition._run_decoupled_KTvle()
    #             if i.B_specification is None: partition._run_decoupled_B()
    #             # print(i.K * i.B)
    #             T = partition.T
    #             for i in (partition.outs + i.outs): i.T = T
    #         for i in shortcuts:
    #             for s in i.outs:
    #                 if s.phase == 'l': 
    #                     bp = s.bubble_point_at_P()
    #                     s.T = bp.T
    #                 elif s.phase == 'g': 
    #                     dp = s.dew_point_at_P()
    #                     s.T = dp.T
    #         # Ts = np.array([i.T for i in lle_stages])
    #         # for i in range(10):
    #         #     Ts_new = np.array([i.T for i in lle_stages])
    #         #     with po.stage_configuration(aggregated=False) as conf:
    #         #         conf.solve_energy_departures(temperature_only=True)
    #         #     for i in lle_stages:
    #         #         for j in i.outs: j.T = i.T
    #         #     print(np.abs(Ts_new - Ts).sum())   
    #         #     if np.abs(Ts_new - Ts).sum() < 1e-9: break
    #         #     Ts = Ts_new
    #         for i in lle_stages:
    #             i.partition._run_lle(update=False)
    #         total_energy_error = sum([energy_error(stage) for stage in stages if stage.B_specification is None and stage.T_specification is None])
    #         specification_errors = np.array([B_error(all_stages[i]) for i in S_index])
    #         # temperature_errors = np.array([T_equilibrium_error(i) for i in vle_stages])
    #         for i in shortcuts: i._run()
    #         S_new = np.array([get_S(all_stages[i]) for i in S_index]).flatten()
    #         splits_new = S_new / (S_new + 1)
    #         splits = S_original / (S_original + 1)
    #         diff = (splits_new - splits)
    #         total_split_error = (diff * diff).sum()
    #         total_specification_error = (specification_errors * specification_errors).sum()
    #         # total_temperature_error = (temperature_errors * temperature_errors).sum()
    #         total_error = total_split_error + total_energy_error + total_specification_error #+ total_temperature_error
    #         err = np.sqrt(total_error)
    #         # if not count[0] % 100:
    #         #     print(err)
    #         #     print(total_split_error, total_energy_error, total_specification_error)
    #         #     po.show()
    #         count[0] += 1
    #         return err
    #     benchmark = lnS_objective(lnS)
    #     result = minimize(
    #         lnS_objective, 
    #         lnS,
    #         tol=0.5, 
    #         method='CG',
    #         options=dict(maxiter=80),
    #     )
    #     optimization = lnS_objective(result.x)
    #     if benchmark > optimization:
    #         streams, adiabatic_stages, all_stages = streams_and_stages(po)
    #         flows = np.array(sum([i._imol._parent.data.rows for i in streams], []))
    #         Ts = np.array([i.T for i in streams])
    #         return flows, Ts, optimization
    #     else:
    #         return flows, Ts, benchmark
        
    def profile(self):
        f = self.run
        streams = self.streams
        adiabatic_stages = self.adiabatic_stages
        stages = self.stages
        total_time = self.profile_time
        time = bst.TicToc()
        flow_error = []
        energy_error = []
        material_error = []
        temperature_error = []
        net_time = 0
        temperatures = np.array([i.T for i in streams])
        diverged_scenarios = []
        temperature_history = []
        flow_history = []
        record = []
        steady_state_flows, steady_state_temperatures, node_tags, phases = self.estimate_steady_state()
        assert node_tags == [i.node_tag for i in streams]
        flows = get_flows(streams, phases)
        while net_time < total_time:
            time.tic()
            diverged_scenarios.append(f())
            net_time += time.toc()
            new_temperatures = np.array([i.T for i in streams])
            new_flows = get_flows(streams, phases)
            record.append(net_time)
            flow_history.append(new_flows)
            temperature_history.append(new_temperatures)
            dF = np.abs(flows - new_flows).sum()
            dT = np.abs(temperatures - new_temperatures).sum()
            flow_error.append(
                np.log10(dF + 1e-25)
            )
            temperature_error.append(
                np.log10(dT + 1e-25)
            )
            energy_error.append(
                np.log10(sum([abs(dT_error(i)) for i in adiabatic_stages]) + 1e-25)
            )
            material_error.append(
                np.log10(sum([abs(i.mass_balance_error()) for i in stages]) + 1e-25)
            )
            flows = new_flows
            temperatures = new_temperatures
        cfe = np.log10([np.abs(steady_state_flows - i).sum() + 1e-25 for i in flow_history])
        te = np.log10([np.abs(steady_state_temperatures - i).sum() + 1e-25 for i in temperature_history])
        return {
            'Time': record, 
            'Component flow rate error': cfe,
            'Temperature error': te,
            'Stream temperature': temperature_error,
            'Component flow rate': flow_error, 
            'Energy balance': energy_error, 
            'Material balance': material_error,
            'Diverged scenarios': diverged_scenarios,
        }

def streams_and_stages(sys):
    all_stages = []
    adiabatic_stages = []
    streams = []
    past_streams = set()
    # print(f'----{sys.algorithm}----')
    for i in sorted(sys.unit_path, key=lambda x: x.node_tag):
        # print(i)
        if hasattr(i, 'stages'):
            all_stages.extend(i.stages)
            for j in i.stages:
                new_streams = [i for i in (j.outs + j.ins) if i.imol not in past_streams]
                streams.extend(new_streams)
                past_streams.update([i.imol for i in new_streams])
                if j.B_specification is None and j.T_specification is None:
                    adiabatic_stages.append(j)
        else:
            try:
                if i.B_specification is None and i.T_specification is None:
                    adiabatic_stages.append(j)
            except:
                pass
            all_stages.append(i)
            new_streams = [j for j in (i.outs + i.ins) if j.imol not in past_streams]
            streams.extend(new_streams)
            past_streams.update([i.imol for i in new_streams])
    streams = sorted(streams, key=lambda x: x.node_tag) 
    return (streams, adiabatic_stages, all_stages)

def dT_error(stage):
    if all([i.isempty() for i in stage.outs]): 
        return 0
    else:
        return (
            sum([i.H for i in stage.outs]) - sum([i.H for i in stage.ins])
        ) / sum([i.C for i in stage.outs])

def division_mean_std(xdx, ydy):
    x, dx = xdx
    y, dy = ydy
    if x == 0 and y == 0:
        return [1, 0]
    else:
        z = x / y
        if x == 0:
            dxx = 0
        else:
            dxx = dx / x
        if y == 0:
            dyy = 0
        else:
            dyy = dy / y
        return [z, z * sqrt(dxx*dxx + dyy*dyy)]

# %% Benchmark plot

def plot_benchmark(systems=None, exclude=None, N=5, load=True, save=True, sort_by_stage=True, label_stages=True):
    if systems is None: systems = list(all_systems)
    if exclude is not None: systems = [i for i in systems if i not in exclude]
    if sort_by_stage: systems = sorted(systems, key=lambda x: system_stages[x])
    n_systems = len(systems)
    results = np.zeros([n_systems, 3])
    Ns = N * np.ones(n_systems, int)
    index = []
    values = []
    for m, sys in enumerate(systems):
        N = Ns[m]
        time = system_convergence_times[sys]
        sms = []
        pos = []
        if load:
            # try:
            for i in range(N):
                sm_name = f'sm_{time}_{sys}_profile_{i}.npy'
                file = os.path.join(simulations_folder, sm_name)
                if load:
                    try:
                        with open(file, 'rb') as f: sm = pickle.load(f)
                    except:
                        sm = Tracker(sys, 'sequential modular').profile()
                else:
                    sm = Tracker(sys, 'sequential modular').profile()
                if save:
                    sm_name = f'sm_{time}_{sys}_profile_{i}.npy'
                    file = os.path.join(simulations_folder, sm_name)
                    with open(file, 'wb') as f: pickle.dump(sm, f)
                sms.append(sm)
            for i in range(N):
                po_name = f'po_{time}_{sys}_profile_{i}.npy'
                file = os.path.join(simulations_folder, po_name)
                if load:
                    try:
                        with open(file, 'rb') as f: po = pickle.load(f)
                    except:
                        po = Tracker(sys, 'phenomena oriented').profile()
                else:
                    po = Tracker(sys, 'phenomena oriented').profile()
                if save:
                    po_name = f'po_{time}_{sys}_profile_{i}.npy'
                    file = os.path.join(simulations_folder, po_name)
                    with open(file, 'wb') as f: pickle.dump(po, f)
                pos.append(po)
            # except:
            #     for i in range(N):
            #         sm = Tracker(sys, 'sequential modular').profile()
            #         sms.append(sm)
            #     for i in range(N):
            #         po = Tracker(sys, 'phenomena oriented').profile()
            #         pos.append(po)
            #     if save:
            #         sm_name = f'sm_{time}_{sys}_benchmark_{N}.npy'
            #         file = os.path.join(simulations_folder, sm_name)
            #         with open(file, 'wb') as f: pickle.dump(sms, f)
            #         po_name = f'po_{time}_{sys}_benchmark_{N}.npy'
            #         file = os.path.join(simulations_folder, po_name)
            #         with open(file, 'wb') as f: pickle.dump(pos, f)
        else:
            for i in range(N):
                sm = Tracker(sys, 'sequential modular').profile()
                sms.append(sm)
            for i in range(N):
                po = Tracker(sys, 'phenomena oriented').profile()
                pos.append(po)
            if save:
                sm_name = f'sm_{time}_{sys}_profile.npy'
                file = os.path.join(simulations_folder, sm_name)
                with open(file, 'wb') as f: pickle.dump(sms, f)
                po_name = f'po_{time}_{sys}_profile.npy'
                file = os.path.join(simulations_folder, po_name)
                with open(file, 'wb') as f: pickle.dump(pos, f)
        cutoff = max([steady_state_error(i) for i in sms + pos])
        sms = np.array([benchmark(i, cutoff) for i in sms])
        pos = np.array([benchmark(i, cutoff) for i in pos])
        values.append(pos)
        name = system_labels[sys].replace('\n', ' ')
        index.append(
            (name, 'Phen.')
        )
        values.append(sms)
        index.append(
            (name, 'Seq. mod.')
        )
        pos_mean_std = [np.mean(pos), np.std(pos)]
        sms_mean_std = [np.mean(sms), np.std(sms)]
        mean, std = division_mean_std(pos_mean_std, sms_mean_std)
        # sm_better = False
        sm_better = mean > 1
        if sm_better: mean = 1 / mean
        results[m] = [100 * mean, 100 * std, sm_better]
        # print(sms)
        # print(pos)
        # print([100 * mean, 100 * std, sm_better])
        # breakpoint()
        # sm = dct_mean_std(sms, keys)
        # po = dct_mean_std(pos, keys)
        # system_results.append((sm, po))
    # Assume only time matters from here on
    # for i, (sm, po) in enumerate(system_results):
    #     results[i] = uncertainty_percent(po['Time'], sm['Time'])
    df = pd.DataFrame(
        values, 
        index=pd.MultiIndex.from_tuples(index),
        columns=[str(i) for i in range(N)], 
    )
    file_name = 'Simulation times.xlsx'
    file = os.path.join(simulations_folder, file_name)
    df.to_excel(file)
    
    n_rows = 1
    n_cols = 1
    fs = 8
    bst.set_font(fs)
    bst.set_figure_size()
    fig, ax = plt.subplots(n_rows, n_cols)
    # red = Color(fg='#f1777f').RGBn
    # blue = Color(fg='#5fc1cf').RGBn
    black = Color(fg='#7b8580').RGBn
    csm = Color(fg='#33BBEE').RGBn
    cpo = Color(fg='#EE7733').RGBn
    # csm = Color(fg='#33BBEE').RGBn
    # cpo = Color(fg='#EE7733').RGBn
    yticks = (0, 25, 50, 75, 100, 125)
    yticklabels = [f'{i}%' for i in yticks]
    xticks = list(range(n_systems))
    if label_stages:
        xticklabels = [system_labels[sys] + f'\n[{system_stages[sys]} stages]' for sys in systems]
    else:
        xticklabels = [system_labels[sys] for sys in systems]
    sm_index, = np.where(results[:, -1])
    po_index, = np.where(~results[:, -1].astype(bool))
    plt.errorbar([xticks[i] for i in sm_index], results[sm_index, 0], 
                 yerr=results[sm_index, 1], color=csm, marker='x', linestyle='', ms=10,
                 capsize=5, capthick=1.5, ecolor=black)
    plt.errorbar([xticks[i] for i in po_index], results[po_index, 0], yerr=results[po_index, 1], color=cpo,
                 marker='s', linestyle='', capsize=5, capthick=1.5, ecolor=black)
    plt.axhline(y=100, color='grey', ls='--', zorder=-1)
    plt.ylabel('Relative simulation time [%]')
    bst.utils.style_axis(
        ax, xticks=xticks, yticks=yticks,
        xticklabels=xticklabels,
        yticklabels=yticklabels,
    )
    plt.subplots_adjust(right=0.96, left=0.2, bottom=0.2, top=0.95, hspace=0, wspace=0)
    for i in ('svg', 'png'):
        name = f'PO_SM_{time}_benchmark_{N}.{i}'
        file = os.path.join(images_folder, name)
        plt.savefig(file, dpi=900, transparent=True)
    return fig, ax, results


# %%  Profile plot

def dct_mean_profile(dcts: list[dict], keys: list[str], ub: float):
    tmin = np.mean([np.min(i['Time']) for i in dcts])
    size = np.min([len(i['Time']) for i in dcts])
    t = np.array([i['Time'][:size] for i in dcts]).mean(axis=0)
    mean = {i: np.zeros(size) for i in keys}
    mean['Time'] = t
    mean['Diverged scenarios'] = np.array(dcts[-1]['Diverged scenarios'])[:size]
    goods = [np.zeros(size) for i in range(len(keys))]
    for dct in dcts:
        for i, good in zip(keys, goods): 
            x = dct['Time']
            y = dct[i]
            values = interpolate.interp1d(x, y, bounds_error=False)(t)
            mask = ~np.isnan(values)
            mean[i][mask] += values[mask]
            mean[i][t < tmin] = np.nan
            good[t > tmin] += 1
    for i, j in zip(keys, goods): mean[i][j > 0] /= j[j > 0]
    return mean

def dct_mean_std(dcts: list[dict], keys: list[str]):
    n = len(dcts)
    values = {i: np.zeros(n) for i in keys}
    for i, dct in enumerate(dcts):
        for key in keys: values[key][i] = dct[key]
    return {i: (values[i].mean(), values[i].std()) for i in keys}

def plot_profile(
        systems=None, N=1, load=True, save=True,
        T=False,
    ):
    if systems is None: systems = list(all_systems)
    fs = 9
    bst.set_font(fs)
    labels = {
        'Component flow rate error': 'Flow rate error',
        'Temperature error': 'Temperature error',
        'Stripping factor': 'Stripping factor\nconvergence error',
        'Component flow rate': 'Flow rate\nconvergence error',
        'Stream temperature': 'Temperature\nconvergence error',
        'Material balance': 'Stage material\nbalance error',
        'Energy balance': 'Stage energy\nbalance error',
    }
    keys = (
        'Temperature error' if T else 'Component flow rate error' ,
    )
    # 'Temperature error',
    # 'Component flow rate',
    # 'Stream temperature',
    # 'Stripping factor',
    # 'Material balance',
    # 'Energy balance',
    units = (
        r'$[\mathrm{K}]$' if T else r'$[\mathrm{mol} \cdot \mathrm{hr}^{\mathrm{-1}}]$',
    )
    # r'$[\mathrm{K}]$',
    # r'$[\mathrm{mol} \cdot \mathrm{hr}^{\mathrm{-1}}]$',
    # r'$[\mathrm{K}]$',
    # r'$[-]$',
    # r'$[\mathrm{mol} \cdot \mathrm{hr}^{\mathrm{-1}}]$',
    # r'$[\mathrm{K}]$',
    n_rows = len(units)
    n_cols = len(systems)
    if n_cols >= 2: 
        width = 'full'
    else:
        width = 'half'
    if n_rows == 4:
        bst.set_figure_size(aspect_ratio=1.1 / n_cols, width=width)
    elif n_rows == 2:
        if n_cols >= 2:
            aspect_ratio = 0.75
        else:
            aspect_ratio = 1.4
        bst.set_figure_size(aspect_ratio=aspect_ratio, width=width)
    else:
        if n_cols >= 2:
            aspect_ratio = 0.75 / 2
        elif n_rows == 1:
            aspect_ratio = 1.4 / 2
        else:
            aspect_ratio = 1.5 / 2
        bst.set_figure_size(aspect_ratio=aspect_ratio, width=width)
    fig, all_axes = plt.subplots(n_rows, n_cols)
    if n_rows == 1:
        if n_cols == 1:
            all_axes = np.array([[all_axes]])
        else:
            all_axes = all_axes.reshape([n_rows, n_cols])
    if n_cols == 1:
        all_axes = np.reshape(all_axes, [n_rows, n_cols]) 
    for m, sys in enumerate(systems):
        time = system_convergence_times[sys]
        axes = all_axes[:, m]
        sms = []
        pos = []
        for i in range(N):
            sm_name = f'sm_{time}_{sys}_profile_{i}.npy'
            file = os.path.join(simulations_folder, sm_name)
            if load:
                try:
                    with open(file, 'rb') as f: sm = pickle.load(f)
                except:
                    sm = Tracker(sys, 'sequential modular').profile()
            else:
                sm = Tracker(sys, 'sequential modular').profile()
            if save:
                sm_name = f'sm_{time}_{sys}_profile_{i}.npy'
                file = os.path.join(simulations_folder, sm_name)
                with open(file, 'wb') as f: pickle.dump(sm, f)
            sms.append(sm)
        for i in range(N):
            po_name = f'po_{time}_{sys}_profile_{i}.npy'
            file = os.path.join(simulations_folder, po_name)
            if load:
                try:
                    with open(file, 'rb') as f: po = pickle.load(f)
                except:
                    po = Tracker(sys, 'phenomena oriented').profile()
            else:
                po = Tracker(sys, 'phenomena oriented').profile()
            if save:
                po_name = f'po_{time}_{sys}_profile_{i}.npy'
                file = os.path.join(simulations_folder, po_name)
                with open(file, 'wb') as f: pickle.dump(po, f)
            pos.append(po)
        tub = system_tickmarks[sys][-1]
        if N > 1:
            pos = pos[1:]
            sms = sms[1:]
            tub = min(tub, min([dct['Time'][-1] for dct in sms]), min([dct['Time'][-1] for dct in pos]))
        sm = dct_mean_profile(sms, keys, tub)
        po = dct_mean_profile(pos, keys, tub)
        csm = Color(fg='#33BBEE').RGBn
        cpo = Color(fg='#EE7733').RGBn
        yticks_list = system_yticks[sys]
        for n, (i, ax, u) in enumerate(zip(keys, axes, units)):
            plt.sca(ax)
            xticks = system_tickmarks[sys]
            ms = False # (np.array(xticks) < 1e-1).all()
            if n == n_rows-1: 
                if ms:
                    plt.xlabel('Time [ms]')
                else:
                    plt.xlabel('Time [s]')
            label = labels[i]
            if m == 0: plt.ylabel(f'{label} {u}')
            ysm = np.array(sm[i])
            ypo = np.array(po[i])
            ysm = gaussian_filter(ysm, 0.2)
            ypo = gaussian_filter(ypo, 0.2)
            cutoff = ysm.min() + 1
            sm_index = sum(ysm > cutoff)
            po_index = sum(ypo > cutoff)
            tsm = np.array(sm['Time'])
            tpo = np.array(po['Time'])
            if ms: 
                xticks = [int(i * 1e3) for i in xticks]
                tsm *= 1e3
                tpo *= 1e3
            size = len(tpo)
            diverged = po['Diverged scenarios'][:size]
            plt.plot(tsm, ysm, '--', color=csm, lw=1.5, alpha=0.5)
            plt.plot(tsm, ysm, lw=0, marker='.', color=csm, markersize=2.5)
            plt.plot(tpo[~diverged], ypo[~diverged], lw=0, marker='.', color=cpo, markersize=2.5)
            plt.plot(tpo[diverged], ypo[diverged], lw=0, marker='x', color=cpo, markersize=2.5)
            plt.plot(tpo, ypo, '-', color=cpo, lw=1.5, alpha=0.5)
            try:
                plt.plot(tsm[sm_index], ysm[sm_index], lw=0, marker='*', color=csm, markersize=5)
                plt.plot(tpo[po_index], ypo[po_index], lw=0, marker='*', color=cpo, markersize=5)
            except:
                pass
            print(sm_index, po_index)
            # plt.annotate(str(sm_index), (tsm[sm_index], ysm[sm_index]), (tsm[sm_index], ysm[sm_index] - 1.5), color=csm)
            # plt.annotate(str(po_index), (tpo[po_index], ypo[po_index]), (tpo[po_index], ypo[po_index] + 0.5), color=cpo)
            yticklabels = m == 0
            yticks = yticks_list[n]
            if yticklabels:
                yticklabels = [r'$\mathrm{10}^{' f'{i}' '}$' for i in yticks]
            # if m == 0 and n == 0:
            #     index = int(len(tsm) * 0.5)
            #     xy = x, y = (tsm[index], ysm[index])
            #     ax.annotate('Sequential\nmodular',
            #         xy=xy, 
            #         xytext=(x-0.01*tub, y+1),
            #         # arrowprops=dict(arrowstyle="->", color=csm),
            #         color=csm,
            #         fontsize=fs,
            #         fontweight='bold',
            #     )
            #     index = int(len(tpo) * 0.5)
            #     xy = x, y = (tpo[index], ypo[index])
            #     ax.annotate('Phenomena\noriented',
            #         xy=xy, 
            #         xytext=(x+0.05*tub, y+5),
            #         # arrowprops=dict(arrowstyle="->", color=cpo),
            #         ha='right',
            #         color=cpo,
            #         fontsize=fs,
            #         fontweight='bold',
            #     )
            xticklabels = xtick0 = n == n_rows-1
            xtickf = m == n_cols-1
            ytick0 = n == n_rows-1
            ytickf = n == 0
            plt.xlim(0, xticks[-1])
            plt.ylim(yticks[0], yticks[-1])
            bst.utils.style_axis(
                ax, xticks=xticks, yticks=yticks, 
                xtick0=xtick0, xtickf=xtickf, ytick0=ytick0, ytickf=ytickf,
                xticklabels=xticklabels,
                yticklabels=yticklabels,
            )
    letter_color = c.neutral.shade(25).RGBn
    titles = [system_titles[i] for i in systems]
    # for ax, letter in zip(all_axes[0], titles):
    #     plt.sca(ax)
    #     ylb, yub = plt.ylim()
    #     xlb, xub = plt.xlim()
    #     plt.text((xlb + xub) * 0.5, ylb + (yub - ylb) * 1.1, letter, color=letter_color,
    #               horizontalalignment='center',verticalalignment='center',
    #               fontsize=fs, fontweight='bold')
    left = 0.1
    top = 0.85
    if n_rows == 2:
        left = 0.25
        bottom = 0.1
    elif n_rows == 1:
        bottom = 0.15
        if n_cols == 1:
            left = 0.25
            top = 0.90
            bottom = 0.2
    else:
        bottom = 0.08
    plt.subplots_adjust(right=0.96, left=left, bottom=bottom, top=top, hspace=0, wspace=0)
    for i in ('svg', 'png'):
        name = f'PO_SM_profile.{i}'
        file = os.path.join(images_folder, name)
        plt.savefig(file, dpi=900, transparent=True)
    for i in ('svg', 'png'):
        system_names = '_'.join(systems)
        name = f'PO_SM_{system_names}_profile.{i}'
        file = os.path.join(images_folder, name)
        plt.savefig(file, dpi=900, transparent=True)
    # return fig, all_axes, sms, pos
