# -*- coding: utf-8 -*-
"""
This file contains the Qudi logic <####>.

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""


from core.module import Connector, StatusVar, ConfigOption
from logic.generic_logic import GenericLogic
from core.util import units
from core.util.mutex import Mutex
import threading
import numpy as np
import os
import time
import datetime
import matplotlib.pyplot as plt
import math

from deprecation import deprecated

from qtpy import QtCore

class WorkerThread(QtCore.QRunnable):
    """ Create a simple Worker Thread class, with a similar usage to a python
    Thread object. This Runnable Thread object is indented to be run from a
    QThreadpool.

    @param obj_reference target: A reference to a method, which will be executed
                                 with the given arguments and keyword arguments.
                                 Note, if no target function or method is passed
                                 then nothing will be executed in the run
                                 routine. This will serve as a dummy thread.
    @param tuple args: Arguments to make available to the run code, should be
                       passed in the form of a tuple
    @param dict kwargs: Keywords arguments to make available to the run code
                        should be passed in the form of a dict
    @param str name: optional, give the thread a name to identify it.
    """

    def __init__(self, target=None, args=(), kwargs={}, name=''):
        super(WorkerThread, self).__init__()
        # Store constructor arguments (re-used for processing)
        self.target = target
        self.args = args
        self.kwargs = kwargs

        if name == '':
            name = str(self.get_thread_obj_id())

        self.name = name
        self._is_running = False

    def get_thread_obj_id(self):
        """ Get the ID from the current thread object. """

        return id(self)

    @QtCore.Slot()
    def run(self):
        """ Initialise the runner function with passed self.args, self.kwargs."""

        if self.target is None:
            return

        self._is_running = True
        self.target(*self.args, **self.kwargs)
        self._is_running = False

    def is_running(self):
        return self._is_running

class AFMConfocalLogic(GenericLogic):
    """ Main AFM logic class providing advanced measurement control. """


    _modclass = 'AFMConfocalLogic'
    _modtype = 'logic'

    __version__ = '0.1.4' # version number 

    _meas_path = ConfigOption('meas_path', default='', missing='warn')

    # declare connectors. It is either a connector to be connected to another
    # logic or another hardware. Hence the interface variable will take either 
    # the name of the logic class (for logic connection) or the interface class
    # which is implemented in a hardware instrument (for a hardware connection)
    spm_device = Connector(interface='CustomScanner') # hardware example
    savelogic = Connector(interface='SaveLogic')  # logic example
    counter_device = Connector(interface='SlowCounterInterface')
    counter_logic = Connector(interface='CounterLogic')
    fitlogic = Connector(interface='FitLogic')



    # configuration parameters/options for the logic. In the config file you
    # have to specify the parameter, here: 'conf_1'
    # _conf_1 = ConfigOption('conf_1', missing='error')

    # status variables, save status of certain parameters if object is 
    # deactivated.
    # _count_length = StatusVar('count_length', 300)

    _stop_request = False
    _stop_request_all = False

    # AFM signal 
    _meas_line_scan = []
    _spm_line_num = 0   # store here the current line number
    # total matrix containing all measurements of all parameters
    _meas_array_scan = []
    _meas_array_scan_fw = []    # forward
    _meas_array_scan_bw = []    # backward
    _afm_meas_duration = 0  # store here how long the measurement has taken
    _afm_meas_optimize_interval = 0 # in seconds

    # APD signal
    _apd_line_scan = []
    _apd_line_num = 0   # store here the current line number
    _apd_array_scan = []
    _apd_array_scan_fw = [] # forward
    _apd_array_scan_bw = [] # backward
    _scan_counter = 0
    _end_reached = False
    _obj_meas_duration = 0
    _opti_meas_duration = 0

    _curr_scan_params = []

    # prepare measurement lines for the general measurement modes
    _obj_scan_line = np.zeros(10)   # scan line array for objective scanner
    _afm_scan_line = np.zeros(10)   # scan line array for objective scanner
    _qafm_scan_line = np.zeros(10)   # scan line array for combined afm + objective scanner
    _opti_scan_line = np.zeros(10)  # for optimizer

    #prepare the required arrays:
    # all of the following dicts should have the same unified structure
    _obj_scan_array = {} # all objective scan data are stored here
    _afm_scan_array = {}  # all pure afm data are stored here
    _qafm_scan_array = {} # all qafm data are stored here
    _opti_scan_array = {} # all optimizer data are stored here
    _esr_scan_array = {} # all the esr data from a scan are stored here

    #FIXME: Implement for this the methods:
    _esr_line_array = {} # the current esr scan and its matrix is stored here
    _saturation_array = {} # all saturation related data here

    # Signals:
    # ========

    # Objective scanner
    # for the pure objective scanner, emitted will be the name of the scan, so 
    # either obj_xy, obj_xz or obj_yz
    sigObjScanInitialized = QtCore.Signal(str)
    sigObjLineScanFinished = QtCore.Signal(str)    
    sigObjScanFinished = QtCore.Signal()  

    # Qualitative Scan (Quenching Mode)
    sigQAFMScanInitialized = QtCore.Signal()
    sigQAFMLineScanFinished = QtCore.Signal()
    sigQAFMScanFinished = QtCore.Signal()
    
    #FIXME: Check whether this is really required.
    # Pure AFM Scan
    sigAFMLineScanFinished = QtCore.Signal()

    # position of Objective in SI in x,y,z
    sigNewObjPos = QtCore.Signal(dict)
    sigObjTargetReached = QtCore.Signal()

    # position of AFM in SI in x,y,z
    sigNewAFMPos = QtCore.Signal(dict)
    sigAFMTargetReached = QtCore.Signal()

    # Optimizer related signals
    sigOptimizeScanInitialized = QtCore.Signal(str)
    sigOptimizeLineScanFinished = QtCore.Signal(str) 
    sigOptimizeScanFinished = QtCore.Signal()

    # saved signals
    sigQAFMDataSaved = QtCore.Signal()
    sigObjDataSaved = QtCore.Signal()
    sigOptiDataSaved = QtCore.Signal()
    sigQuantiDataSaved = QtCore.Signal()

    # Quantitative Scan (Full B Scan)
    sigQuantiScanFinished = QtCore.Signal()

    _obj_pos = {'x': 0.0, 'y': 0.0, 'z': 0.0}
    _afm_pos = {'x': 0.0, 'y': 0.0}

    __data_to_be_saved = 0  # emit a signal if the data to be saved reaches 0

    #optimizer: x_max, y_max, c_max, z_max, c_max_z
    _opt_val = [0, 0, 0, 0, 0]

    # make a dummy worker thread:
    _worker_thread = WorkerThread(print)

    _optimizer_thread = WorkerThread(print)


    # NV parameters:
    ZFS = 2.87e9    # Zero-field-splitting
    E_FIELD = 0.0   # strain field

    # Move Settings
    _sg_idle_move_target_sample = StatusVar(default=0.5)
    _sg_idle_move_target_obj = StatusVar(default=0.5)

    # Scan Settings
    _sg_idle_move_scan_sample = StatusVar(default=0.1)
    _sg_idle_move_scan_obj = StatusVar(default=0.1)
    _sg_int_time_sample_scan = StatusVar(default=0.01)
    _sg_int_time_obj_scan = StatusVar(default=0.01)

    # Save Settings
    _sg_root_folder_name = StatusVar(default='')
    _sg_create_summary_pic = StatusVar(default=True)

    # Optimizer Settings
    _sg_optimizer_x_range = StatusVar(default=1.0e-6)
    _sg_optimizer_x_res = StatusVar(default=15)
    _sg_optimizer_y_range = StatusVar(default=1.0e-6)
    _sg_optimizer_y_res = StatusVar(default=15)
    _sg_optimizer_z_range = StatusVar(default=2.0e-6)
    _sg_optimizer_z_res = StatusVar(default=50)    
    _sg_optimizer_int_time = StatusVar(default=0.01)
    _sg_periodic_optimizer = False  # do not safe this a status var
    _sg_optimizer_period = StatusVar(default=60)
    _optimize_request = False

    # target positions of the optimizer
    _optimizer_x_target_pos = 15e-6
    _optimizer_y_target_pos = 15e-6
    _optimizer_z_target_pos = 5e-6

    sigSettingsUpdated = QtCore.Signal()

    def __init__(self, config, **kwargs):
        """ Create CounterLogic object with connectors.

        @param dict config: module configuration
        @param dict kwargs: optional parameters
        """
        super().__init__(config=config, **kwargs)

        # locking mechanism for thread safety. Use it like
        #   self.threadlock.lock() # to lock the current thread
        #   self.threadlock.unlock() # to unlock the current thread
        #   self.threadlock.acquire() # to acquire a lock
        #   self.threadlock.trylock()   # to try to lock it.
        self.threadlock = Mutex()

        # checking for the right configuration
        for key in config.keys():
            self.log.debug('{0}: {1}'.format(key, config[key]))

        # make at first a certain shape


    def on_activate(self):
        """ Initialization performed during activation of the module. """

        # Connect to hardware and save logic
        self._spm = self.spm_device()
        self._save_logic = self.savelogic()
        self._counter = self.counter_device()
        self._counterlogic = self.counter_logic()
        self._fitlogic = self.fitlogic()

        self._qafm_scan_array = self.initialize_qafm_scan_array(0, 100e-6, 10, 
                                                                0, 100e-6, 10)

        self._obj_scan_array = self.initialize_obj_scan_array('obj_xy', 
                                                               0, 30e-6, 30,
                                                               0, 30e-6, 30)
        self._obj_scan_array = self.initialize_obj_scan_array('obj_xz', 
                                                               0, 30e-6, 30,
                                                               0, 10e-6, 30)
        self._obj_scan_array = self.initialize_obj_scan_array('obj_yz', 
                                                               0, 30e-6, 30,
                                                               0, 10e-6, 30)

        self._opti_scan_array = self.initialize_opti_xy_scan_array(0, 2e-6, 30,
                                                                   0, 2e-6, 30)

        self._opti_scan_array = self.initialize_opti_z_scan_array(0, 10e-6, 30)

        self.sigNewObjPos.emit(self.get_obj_pos())
        self.sigNewAFMPos.emit(self.get_afm_pos())

        self._save_logic.sigSaveFinished.connect(self.decrease_save_counter)

        self._meas_path = os.path.abspath(self._meas_path)

        #FIXME: Introduce a state variable to prevent redundant configuration calls of the hardware.
        self._counter.prepare_pixelclock()

        if not os.path.exists(self._meas_path):
            self._meas_path = self._save_logic.get_path_for_module(module_name='ProteusQ')

        # in this threadpool our worker thread will be run
        self.threadpool = QtCore.QThreadPool()


        self.sigOptimizeScanFinished.connect(self._optimize_finished)

    def on_deactivate(self):
        """ Deinitializations performed during deactivation of the module. """

        pass

    def initialize_qafm_scan_array(self, x_start, x_stop, num_columns, 
                                         y_start, y_stop, num_rows):
        """ Initialize the qafm scan array. 

        @param int num_columns: number of columns, essentially the x resolution
        @param int num_rows: number of columns, essentially the y resolution
        """


        coord0_arr = np.linspace(x_start, x_stop, num_columns, endpoint=True)
        coord1_arr = np.linspace(y_start, y_stop, num_rows, endpoint=True)

        #FIXME: use Tesla not Gauss, right not, this is just for display purpose
        # add counts to the parameter list
        meas_params_units = {'counts' : {'measured_units' : 'c/s',
                                         'scale_fac': 1,    # multiplication factor to obtain SI units    
                                         'si_units': 'c/s', 
                                         'nice_name': 'Fluorescence'},
                             'b_field': {'measured_units' : 'G',
                                         'scale_fac': 1,    # multiplication factor to obtain SI units
                                         'si_units': 'G',
                                         'nice_name': 'Magnetic field '},
                                         }
        meas_params_units.update(self._spm.get_meas_params())

        meas_params = list(meas_params_units)

        meas_dir = ['fw', 'bw']
        meas_dict = {}

        for direction in meas_dir:
            for param in meas_params:

                name = f'{param}_{direction}' # this is the naming convention!

                meas_dict[name] = {'data': np.zeros((num_rows, num_columns))}
                meas_dict[name]['coord0_arr'] = coord0_arr
                meas_dict[name]['coord1_arr'] = coord1_arr
                #meas_dict[name] = {'data': np.random.rand(num_rows, num_columns)}
                meas_dict[name].update(meas_params_units[param])
                meas_dict[name]['params'] = {}
                meas_dict[name]['display_range'] = None

        self.sigQAFMScanInitialized.emit()

        return meas_dict

    def initialize_esr_scan_array(self, esr_start, esr_stop, esr_num,
                                  coord0_start, coord0_stop, num_columns,
                                  coord1_start, coord1_stop, num_rows):
        """ Initialize the ESR scan array data.
        The dimensions are not the same for the ESR data, it is a 3 dimensional
        tensor rather then a 2 dimentional matrix. """


        meas_dir = ['fw', 'bw']
        meas_dict = {}

        for entry in meas_dir:
            name = f'esr_{entry}'

            meas_dict[name] = {'data': np.zeros((num_rows, num_columns, esr_num)),
                               'data_std': np.zeros((num_rows, num_columns, esr_num)),
                               'coord0_arr': np.linspace(coord0_start, coord0_stop, num_columns, endpoint=True),
                               'coord1_arr': np.linspace(coord1_start, coord1_stop, num_rows, endpoint=True),
                               'coord2_arr': np.linspace(esr_start, esr_stop, esr_num, endpoint=True),
                               'measured_units': 'c/s',
                               'scale_fac': 1,  # multiplication factor to obtain SI units
                               'si_units': 'c/s',
                               'nice_name': 'Fluorescence',
                               'params': {},  # !!! here are all the measurement parameter saved
                               'display_range': None,
                               }

        return meas_dict


    def initialize_obj_scan_array(self, plane_name, coord0_start, coord0_stop, num_columns, 
                                     coord1_start, coord1_stop, num_rows):

        meas_dict = {'data': np.zeros((num_rows, num_columns)),
                     'coord0_arr': np.linspace(coord0_start, coord0_stop, num_columns, endpoint=True),
                     'coord1_arr': np.linspace(coord1_start, coord1_stop, num_rows, endpoint=True),
                     'measured_units' : 'c/s', 
                     'scale_fac': 1,    # multiplication factor to obtain SI units   
                     'si_units': 'c/s', 
                     'nice_name': 'Fluorescence',
                     'params': {}, # !!! here are all the measurement parameter saved
                     'display_range': None,
                     }
            
        self._obj_scan_array[plane_name] = meas_dict

        self.sigObjScanInitialized.emit(plane_name)

        return self._obj_scan_array
        

    def initialize_opti_xy_scan_array(self, coord0_start, coord0_stop, num_columns, 
                                      coord1_start, coord1_stop, num_rows):
        """ Initialize the optimizer scan array. 

        @param int num_columns: number of columns, essentially the x resolution
        @param int num_rows: number of columns, essentially the y resolution
        """
        name = 'opti_xy'

        meas_dict = {'data': np.zeros((num_rows, num_columns)),
                     'data_fit': np.zeros((num_rows, num_columns)),
                     'coord0_arr': np.linspace(coord0_start, coord0_stop, num_columns, endpoint=True),
                     'coord1_arr': np.linspace(coord1_start, coord1_stop, num_rows, endpoint=True),
                     'measured_units' : 'c/s', 
                     'scale_fac': 1,    # multiplication factor to obtain SI units 
                     'si_units': 'c/s', 
                     'nice_name': 'Fluorescence',
                     'params': {}, # !!! here are all the measurement parameter saved, including the fit parameter
                     'display_range': None,
                    }

        self._opti_scan_array[name] = meas_dict

        self.sigOptimizeScanInitialized.emit(name)

        return self._opti_scan_array

    def initialize_opti_z_scan_array(self, coord0_start, coord0_stop, num_points):
        """ Initialize the z scan line. 

        @param int num_points: number of points for the line
        """
        name = 'opti_z'

        meas_dict = {'data': np.zeros(num_points),
                     'coord0_arr': np.linspace(coord0_start, coord0_stop, num_points, endpoint=True),
                     'measured_units' : 'c/s', 
                     'scale_fac': 1,    # multiplication factor to obtain SI units 
                     'si_units': 'c/s', 
                     'nice_name': 'Fluorescence',
                     'params': {}, # !!! here are all the measurement parameter saved
                     'fit_result': None,
                     'display_range':None,
                     }

        self._opti_scan_array[name] = meas_dict

        self.sigOptimizeScanInitialized.emit(name)
        return self._opti_scan_array

    def get_afm_meas_params(self):
        return self._spm.get_meas_params()


    def get_curr_scan_params(self):
        """ Return the actual list of scanning parameter, forward and backward. """

        scan_param = []

        for entry in self._curr_scan_params:
            scan_param.append(f'{entry}_fw')
            scan_param.append(f'{entry}_bw')

        return scan_param


    def get_qafm_settings(self, setting_list=None):
        """ Obtain all the settings for the qafm in a dict container. 

        @param list setting_list: optional, if specific settings are required, 
                                  and not all of them, then you can specify 
                                  those in this list.  

        @return dict: with all requested or available settings for qafm.
        """


        # settings dictionary
        sd = {}
        # Move Settings
        sd['idle_move_target_sample'] = self._sg_idle_move_target_sample
        sd['idle_move_target_obj'] = self._sg_idle_move_target_obj
        # Scan Settings
        sd['idle_move_scan_sample'] = self._sg_idle_move_scan_sample
        sd['idle_move_scan_obj'] = self._sg_idle_move_scan_obj
        sd['int_time_sample_scan'] = self._sg_int_time_sample_scan
        sd['int_time_obj_scan'] = self._sg_int_time_obj_scan
        # Save Settings
        sd['root_folder_name'] = self._sg_root_folder_name
        sd['create_summary_pic'] = self._sg_create_summary_pic
        # Optimizer Settings
        sd['optimizer_x_range'] = self._sg_optimizer_x_range
        sd['optimizer_x_res'] = self._sg_optimizer_x_res
        sd['optimizer_y_range'] = self._sg_optimizer_y_range
        sd['optimizer_y_res'] = self._sg_optimizer_y_res
        sd['optimizer_z_range'] = self._sg_optimizer_z_range
        sd['optimizer_z_res'] = self._sg_optimizer_z_res

        sd['optimizer_int_time'] = self._sg_optimizer_int_time
        sd['optimizer_period'] = self._sg_optimizer_period

        if setting_list is None:
            return sd
        else:
            ret_sd = {}
            for entry in setting_list:
                item = sd.get(entry, default=None)
                if item is not None:
                    ret_sd[entry] = item
            return ret_sd

    def set_qafm_settings(self, set_dict):
        """ Set the current qafm settings. 

        @params dict set_dict: a dictionary containing all the settings which 
                               needs to be set. For an empty dict, nothing will
                               happen. 
                               Hint: use the get_qafm_settings method to obtain
                                     a full list of available items.
        """
        
        for entry in set_dict:
            attr_name = f'_sg_{entry}'
            if hasattr(self, attr_name):
                setattr(self, attr_name, set_dict[entry])

        self.sigSettingsUpdated.emit()

    #FIXME: There is an error occurring if no SPM measurement parameters are specified. Fix this!
    def scan_area_qafm_bw_fw_by_line(self, coord0_start, coord0_stop, coord0_num,
                                     coord1_start, coord1_stop, coord1_num,
                                     integration_time, plane='XY',
                                     meas_params=['counts', 'Height(Dac)'],
                                     continue_meas=False):

        """ QAFM measurement (optical + afm) forward and backward for a scan by line.

        @param float coord0_start: start coordinate in m
        @param float coord0_stop: start coordinate in m
        @param int coord0_num: number of points in coord0 direction
        @param float coord1_start: start coordinate in m
        @param float coord1_stop: start coordinate in m
        @param int coord1_num: number of points in coord1 direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement
                                 parameter. Have a look at MEAS_PARAMS to see
                                 the available parameters. Include the parameter
                                 'Counts', if you want to measure them.

        @return 2D_array: measurement results in a two dimensional list.
        """

        if integration_time is None:
            integration_time = self._sg_int_time_sample_scan

        self.module_state.lock()

        # set up the spm device:
        reverse_meas = False
        self._stop_request = False


        # time in which the stage is just moving without measuring
        time_idle_move = self._sg_idle_move_scan_sample

        scan_speed_per_line = integration_time * coord0_num
        scan_arr = self._spm.create_scan_leftright2(coord0_start, coord0_stop,
                                                    coord1_start, coord1_stop,
                                                    coord1_num)

        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=meas_params,
                                                           scan_mode=0)  # line scan
        spm_start_idx = 0

        if 'counts' in meas_params:
            self._spm.enable_point_trigger()
            curr_scan_params.insert(0, 'counts')  # insert the fluorescence parameter
            
            if self._counter.get_device_mode() != 'pixel':
                self._counter.prepare_pixelclock()
            
            spm_start_idx = 1 # start index of the temporary scan for the spm parameters

        # this case is for starting a new measurement:
        if (self._spm_line_num == 0) or (not continue_meas):
            self._spm_line_num = 0
            self._afm_meas_duration = 0

            # AFM signal
            self._qafm_scan_array = self.initialize_qafm_scan_array(coord0_start,
                                                                    coord0_stop,
                                                                    coord0_num,
                                                                    coord1_start,
                                                                    coord1_stop,
                                                                    coord1_num)
            self._scan_counter = 0

        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane,
                                                            coord0_start,
                                                            coord0_stop,
                                                            coord1_start,
                                                            coord1_stop)
        if ret_val < 1:
            self.module_state.unlock()
            return self._qafm_scan_array

        start_time_afm_scan = datetime.datetime.now()
        self._curr_scan_params = curr_scan_params

        num_params = len(curr_scan_params)

        # save the measurement parameter
        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Parameters for'] = 'QAFM measurement'
            self._qafm_scan_array[entry]['params']['axis name for coord0'] = 'X'
            self._qafm_scan_array[entry]['params']['axis name for coord1'] = 'Y'
            self._qafm_scan_array[entry]['params']['measurement plane'] = 'XY'
            self._qafm_scan_array[entry]['params']['coord0_start (m)'] = coord0_start
            self._qafm_scan_array[entry]['params']['coord0_stop (m)'] = coord0_stop
            self._qafm_scan_array[entry]['params']['coord0_num (#)'] = coord0_num
            self._qafm_scan_array[entry]['params']['coord1_start (m)'] = coord1_start
            self._qafm_scan_array[entry]['params']['coord1_stop (m)'] = coord1_stop
            self._qafm_scan_array[entry]['params']['coord1_num (#)'] = coord1_num
            self._qafm_scan_array[entry]['params']['Scan speed per line (s)'] = scan_speed_per_line
            self._qafm_scan_array[entry]['params']['Idle movement speed (s)'] = time_idle_move

            self._qafm_scan_array[entry]['params']['integration time per pixel (s)'] = integration_time
            self._qafm_scan_array[entry]['params']['Measurement parameter list'] = str(curr_scan_params)
            self._qafm_scan_array[entry]['params']['Measurement start'] = start_time_afm_scan.isoformat()

        for line_num, scan_coords in enumerate(scan_arr):

            # for a continue measurement event, skip the first measurements
            # until one has reached the desired line, then continue from there.
            if line_num < self._spm_line_num:
                continue

            # optical + AFM signal
            self._qafm_scan_line = np.zeros((num_params, coord0_num))

            if 'counts' in meas_params:
                self._counter.arm_device(coord0_num)

            self._spm.setup_scan_line(corr0_start=scan_coords[0],
                                      corr0_stop=scan_coords[1],
                                      corr1_start=scan_coords[2],
                                      corr1_stop=scan_coords[3],
                                      time_forward=scan_speed_per_line,
                                      time_back=time_idle_move)

            self._spm.scan_line()  # start the scan line

            if num_params > 1:
                # i.e. afm parameters are set
                self._qafm_scan_line[spm_start_idx:] = self._spm.get_scanned_line(reshape=True)
            else:
                # perform just the scan without using the data.
                self._spm.get_scanned_line(reshape=True)

            if 'counts' in meas_params:
                # first entry is always assumed to be counts
                self._qafm_scan_line[0] = self._counter.get_line()/integration_time

            if reverse_meas:

                for index, param_name in enumerate(curr_scan_params):
                    name = f'{param_name}_bw'  # use the unterlying naming convention

                    # save to the corresponding matrix line and renormalize the results to SI units:
                    self._qafm_scan_array[name]['data'][line_num // 2] = np.flip(self._qafm_scan_line[index]) * self._qafm_scan_array[name]['scale_fac']
                reverse_meas = False

                # emit only a signal if the reversed is finished.
                self.sigQAFMLineScanFinished.emit()
            else:
                for index, param_name in enumerate(curr_scan_params):
                    name = f'{param_name}_fw'  # use the unterlying naming convention
                    # save to the corresponding matrix line and renormalize the results to SI units:
                    self._qafm_scan_array[name]['data'][line_num // 2] = self._qafm_scan_line[index] * self._qafm_scan_array[name]['scale_fac']
                reverse_meas = True

            # self.log.info(f'Line number {line_num} completed.')
            #print(f'Line number {line_num} completed.')

            # enable the break only if next scan goes into forward movement
            if self._stop_request and not reverse_meas:
                break

            # store the current line number
            self._spm_line_num = line_num

            # if next measurement is not in the reverse way, make a quick stop
            # and perform here an optimization first
            if self.get_optimize_request():

                self._spm.finish_scan()
                time.sleep(2)

                self.default_optimize()
                _, _, _ = self._spm.setup_spm(plane=plane,
                                              line_points=coord0_num,
                                              meas_params=meas_params,
                                              scan_mode=0)  # line scan
                if 'counts' in meas_params:
                    self._spm.enable_point_trigger()

                self.log.info('optimizer finished.')

        stop_time_afm_scan = datetime.datetime.now()
        self._afm_meas_duration = self._afm_meas_duration + (stop_time_afm_scan - start_time_afm_scan).total_seconds()

        if line_num == self._spm_line_num:
            self.log.info(f'Scan finished at {int(self._afm_meas_duration)}s. Yeehaa!')
        else:
            self.log.info(f'Scan stopped at {int(self._afm_meas_duration)}s.')

        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Measurement stop'] = stop_time_afm_scan.isoformat()
            self._qafm_scan_array[entry]['params']['Total measurement time (s)'] = self._afm_meas_duration

        # clean up the counter
        if 'counts' in meas_params:
            self._counter.stop_measurement()

        # clean up the spm
        self._spm.finish_scan()
        self.module_state.unlock()
        self.sigQAFMScanFinished.emit()

        return self._qafm_scan_array

    def start_scan_area_qafm_bw_fw_by_line(self, coord0_start=48*1e-6, coord0_stop=53*1e-6, coord0_num=40,
                            coord1_start=47*1e-6, coord1_stop=52*1e-6, coord1_num=40, integration_time=None,
                            plane='XY', meas_params=['counts', 'Phase', 'Height(Dac)', 'Height(Sen)'],
                            continue_meas=False):

        if self.check_thread_active():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self._worker_thread = WorkerThread(target=self.scan_area_qafm_bw_fw_by_line,
                                            args=(coord0_start, coord0_stop, coord0_num,
                                                  coord1_start, coord1_stop, coord1_num,
                                                  integration_time, plane,
                                                  meas_params, continue_meas),
                                            name='qafm_fw_bw_line')

        self.threadpool.start(self._worker_thread)





# ==============================================================================
#             forward and backward most general scan
# ==============================================================================

    # TODO: implement a hardcore stop mechanism!!!!
    @deprecated(details='Use the method "scan_area_qafm_bw_fw_by_line" instead.')
    def scan_area_by_point(self, coord0_start, coord0_stop,
                           coord1_start, coord1_stop, res_x, res_y,
                           integration_time, plane='XY', meas_params=['Height(Dac)'],
                           continue_meas=False):

        """ QAFM measurement (optical + afm) forward and backward for a scan by point.
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int res_x: number of points in x direction
        @param int res_y: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """

        self.module_state.lock()


        # set up the spm device:
        reverse_meas = False      
        self._stop_request = False

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        
        if self._counterlogic.module_state.current == 'idle':
            self._counterlogic.startCount()

        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_arr = self._spm.create_scan_leftright2(coord0_start, coord0_stop, 
                                                    coord1_start, coord1_stop, res_y)

        #FIXME: check whether the number of parameters are required and whether they are set correctly.
        # self._spm._params_per_point = len(names_buffers)
        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=res_x, 
                                                           meas_params=meas_params)

        #FIXME: Implement an better initialization procedure
        #FIXME: Create a better naming for the matrices

        if (self._spm_line_num==0) or (not continue_meas):
            self._spm_line_num = 0
            self._afm_meas_duration = 0

             # AFM signal
            self._meas_array_scan_fw = np.zeros((res_y, len(curr_scan_params)*res_x))
            self._meas_array_scan_bw = np.zeros((res_y, len(curr_scan_params)*res_x))
            # APD signal
            self._apd_array_scan_fw = np.zeros((res_y, res_x))
            self._apd_array_scan_bw = np.zeros((res_y, res_x))

            self._scan_counter = 0   

        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop, coord1_start, coord1_stop)   


        if ret_val < 1:
            return (self._apd_array_scan_fw, self._apd_array_scan_bw, 
                    self._meas_array_scan_fw, self._meas_array_scan_bw)

        # if everything is fine, start and prepare the measurement
        self._curr_scan_params = curr_scan_params
        start_time_afm_scan = time.time()

        for line_num, scan_coords in enumerate(scan_arr):
            
            # for a continue measurement event, skip the first measurements 
            # until one has reached the desired line, then continue from there.
            if line_num < self._spm_line_num:
                continue

            # AFM signal
            self._meas_line_scan = np.zeros(len(curr_scan_params)*res_x)
            # APD signal
            self._apd_line_scan = np.zeros(res_x)
            
            self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                      corr0_stop=scan_coords[1], 
                                      corr1_start=scan_coords[2], 
                                      corr1_stop=scan_coords[3], 
                                      time_forward=scan_speed_per_line, 
                                      time_back=scan_speed_per_line)
            
            vals = self._spm.scan_point()  # these are points to throw away

            #if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")

            for index in range(res_x):

                #Important: Get first counts, then the SPM signal!
                self._apd_line_scan[index] = self._counter.get_counter(1)[0][0]
                self._meas_line_scan[index*len(curr_scan_params):(index+1)*len(curr_scan_params)] = self._spm.scan_point()
                
                self._scan_counter += 1
                
                # remove possibility to stop during line scan.
                #if self._stop_request:
                #    break

            if reverse_meas:
                self._meas_array_scan_bw[line_num//2] = self._meas_line_scan[::-1]
                self._apd_array_scan_bw[line_num//2] = self._apd_line_scan[::-1]
                # bring directly in correct shape: a.reshape((4, len(a)//4) )[::-1].ravel()
                # where 4 are the number of parameters 
                reverse_meas = False
            else:
                self._meas_array_scan_fw[line_num//2] = self._meas_line_scan
                self._apd_array_scan_fw[line_num//2] = self._apd_line_scan
                reverse_meas = True

            #self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')

            # enable the break only if next scan goes into forward movement
            if self._stop_request and not reverse_meas:
                break

            # store the current line number
            self._spm_line_num = line_num



        self._afm_meas_duration = self._afm_meas_duration + (datetime.datetime.now() - start_time_afm_scan).total_seconds()

        if line_num == self._spm_line_num:
            self.log.info(f'Scan finished after {int(self._afm_meas_duration)}s. Yeehaa!')
        else:
            self.log.info(f'Scan stopped after {int(self._afm_meas_duration)}s.')
        
        # clean up the spm
        self._spm.finish_scan()
        self.module_state.unlock()
        
        return (self._apd_array_scan_fw, self._apd_array_scan_bw, 
                self._meas_array_scan_fw, self._meas_array_scan_bw)

    @deprecated(details='Use the method "start_scan_area_qafm_bw_fw_by_line" instead.')
    def start_measure_point(self, coord0_start=48*1e-6, coord0_stop=53*1e-6, 
                            coord1_start=47*1e-6, coord1_stop=52*1e-6, 
                            res_x=40, res_y=40, integration_time=0.02, plane='XY',
                            meas_params=['Phase', 'Height(Dac)', 'Height(Sen)'],
                            continue_meas=False):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.scan_area_by_point, 
                                            args=(coord0_start, coord0_stop, 
                                                  coord1_start, coord1_stop, 
                                                  res_x, res_y, 
                                                  integration_time,
                                                  plane,
                                                  meas_params, continue_meas), 
                                            name='meas_thread')
        self.meas_thread.start()

# ==============================================================================
#           Quantitative Mode with ESR forward and backward movement
# ==============================================================================


    def calc_mag_field_single_res(self, res_freq, zero_field=2.87e9, e_field=0.0):
        """ Calculate the magnetic field experience by the NV, assuming low 
            mag. field.

        according to:
        https://iopscience.iop.org/article/10.1088/0034-4885/77/5/056503

        """

        gyro_nv = 28e9  # gyromagnetic ratio of the NV in Hz/T (would be 28 GHz/T)

        return np.sqrt(abs(res_freq - zero_field)**2 - e_field**2) / gyro_nv


    def calc_mag_field_double_res(self, res_freq_low, res_freq_high, 
                                  zero_field=2.87e9, e_field=0.0):
        """ Calculate the magnetic field experience by the NV, assuming low 
            mag. field by measuring two frequencies.

        @param float res_freq_low: lower resonance frequency in Hz
        @param float res_freq_high: high resonance frequency in Hz
        @param float zero_field: Zerofield splitting of NV in Hz
        @param float e_field: Estimated electrical field on the NV center

        @return float: the experiences mag. field of the NV in Tesla

        according to:
        https://www.osapublishing.org/josab/fulltext.cfm?uri=josab-33-3-B19&id=335418

        """

        gyro_nv = 28e9  # gyromagnetic ratio of the NV in Hz/T (would be 28 GHz/T)

        return np.sqrt((res_freq_low+res_freq_high - res_freq_low*res_freq_high - zero_field**2)/3 - e_field**2) / gyro_nv


    def scan_area_quanti_qafm_fw_bw_by_point(self, coord0_start, coord0_stop,
                                          coord0_num, coord1_start, coord1_stop,
                                          coord1_num, int_time_afm=0.1,
                                          idle_move_time=0.1, freq_start=2.77e9,
                                          freq_stop=2.97e9, freq_points=100,
                                          esr_count_freq=200,
                                          mw_power=0.4, num_esr_runs=30,
                                          optimize_period = 100,
                                          meas_params=['Height(Dac)'],
                                          single_res=True,
                                          continue_meas=False):

        """ QAFM measurement (optical + afm) forward and backward for a scan by point.

        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param int coord0_num: number of points in coord0 direction
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int coord1_num: start coordinate in um
        @param int coord0_num: number of points in coord1 direction
        @param float int_time_afm: integration time for afm operations
        @param float idle_move_time: time for a movement where nothing is measured
        @param float freq_start: start frequency for ESR scan in Hz
        @param float freq_stop: stop frequency for ESR scan in Hz
        @param float freq_points: number of frequencies for ESR scan
        @param float esr_count_freq: The count frequency in ESR scan in Hz
        @param float mw_power: microwave power during scan
        @param int num_esr_runs: number of ESR runs
        @param float optimize_period: time after which an optimization request 
                                      is set

        @param list meas_params: list of possible strings of the measurement
                                 parameter. Have a look at MEAS_PARAMS to see
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list.
        """

        # self.log.info('forward backward scan started.')
        # self.log.info(f'{coord0_start, coord0_stop, coord0_num, coord1_start, coord1_stop, coord1_num, int_time_afm, idle_move_time, freq_start, freq_stop, freq_points, esr_count_freq, mw_power, num_esr_runs, optimize_period, meas_params, single_res, continue_meas}')
        # time.sleep(3)
        # self.sigQuantiScanFinished.emit()
        # return
        
        #self.module_state.lock()
        plane = 'XY'

        # set up the spm device:
        reverse_meas = False
        self._stop_request = False

        self._optimize_period = optimize_period

        # make the counter for esr ready
        freq_list = np.linspace(freq_start, freq_stop, freq_points, endpoint=True)



        self._counter.prepare_cw_esr(freq_list, esr_count_freq, mw_power)

        # scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = int_time_afm
        scan_arr = self._spm.create_scan_leftright2(coord0_start, coord0_stop,
                                                    coord1_start, coord1_stop, coord1_num)

        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=meas_params)

        curr_scan_params.insert(0, 'counts')  # insert the fluorescence parameter

        # this case is for starting a new measurement:
        if (self._spm_line_num == 0) or (not continue_meas):
            self._spm_line_num = 0
            self._afm_meas_duration = 0

            # AFM signal
            self._qafm_scan_array = self.initialize_qafm_scan_array(coord0_start, 
                                                                    coord0_stop, 
                                                                    coord0_num,
                                                                    coord1_start, 
                                                                    coord1_stop, 
                                                                    coord1_num)
            self._scan_counter = 0


            self._esr_scan_array = self.initialize_esr_scan_array(freq_start, 
                                                                  freq_stop, 
                                                                  freq_points,
                                                                  coord0_start, 
                                                                  coord0_stop, 
                                                                  coord0_num,
                                                                  coord1_start, 
                                                                  coord1_stop, 
                                                                  coord1_num)

            # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop,
                                                            coord1_start, coord1_stop)
        if ret_val < 1:
            self.sigQuantiScanFinished.emit()
            return self._qafm_scan_array

        start_time_afm_scan = datetime.datetime.now()
        opti_counter = datetime.datetime.now()
        self._curr_scan_params = curr_scan_params

        # save the measurement parameter
        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Parameters for'] = 'QAFM measurement'
            self._qafm_scan_array[entry]['params']['axis name for coord0'] = 'X'
            self._qafm_scan_array[entry]['params']['axis name for coord1'] = 'Y'
            self._qafm_scan_array[entry]['params']['measurement plane'] = 'XY'
            self._qafm_scan_array[entry]['params']['coord0_start (m)'] = coord0_start
            self._qafm_scan_array[entry]['params']['coord0_stop (m)'] = coord0_stop
            self._qafm_scan_array[entry]['params']['coord0_num (#)'] = coord0_num
            self._qafm_scan_array[entry]['params']['coord1_start (m)'] = coord1_start
            self._qafm_scan_array[entry]['params']['coord1_stop (m)'] = coord1_stop
            self._qafm_scan_array[entry]['params']['coord1_num (#)'] = coord1_num

            self._qafm_scan_array[entry]['params']['ESR Frequency start (Hz)'] = freq_start
            self._qafm_scan_array[entry]['params']['ESR Frequency stop (Hz)'] = freq_stop
            self._qafm_scan_array[entry]['params']['ESR Frequency points (#)'] = freq_points
            self._qafm_scan_array[entry]['params']['ESR Count Frequency (Hz)'] = esr_count_freq
            self._qafm_scan_array[entry]['params']['ESR MW power (gain)'] = mw_power
            self._qafm_scan_array[entry]['params']['ESR Measurement runs (#)'] = num_esr_runs
            self._qafm_scan_array[entry]['params']['Expect one resonance dip'] = single_res
            self._qafm_scan_array[entry]['params']['Optimize Period (s)'] = optimize_period

            self._qafm_scan_array[entry]['params']['AFM integration time per pixel (s)'] = int_time_afm
            self._qafm_scan_array[entry]['params']['AFM time for idle move (s)'] = idle_move_time
            self._qafm_scan_array[entry]['params']['Measurement parameter list'] = str(curr_scan_params)
            self._qafm_scan_array[entry]['params']['Measurement start'] = start_time_afm_scan.isoformat()

        for line_num, scan_coords in enumerate(scan_arr):

            # for a continue measurement event, skip the first measurements
            # until one has reached the desired line, then continue from there.
            if line_num < self._spm_line_num:
                continue

            num_params = len(curr_scan_params)

            self._spm.setup_scan_line(corr0_start=scan_coords[0],
                                      corr0_stop=scan_coords[1],
                                      corr1_start=scan_coords[2],
                                      corr1_stop=scan_coords[3],
                                      time_forward=scan_speed_per_line,
                                      time_back=idle_move_time)

            # -1 otherwise it would be more than coord0_num points, since first one is counted too.
            x_step = (scan_coords[1] - scan_coords[0]) / (coord0_num - 1)

            self._afm_pos = {'x': scan_coords[0], 'y': scan_coords[2]}

            vals = self._spm.scan_point()  # these are points to throw away
            self.sigNewAFMPos.emit(self._afm_pos)

            # if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")

            last_elem = list(range(coord0_num))[-1]
            for index in range(coord0_num):

                # first two entries are counts and b_field, remaining entries are the scan parameter
                self._scan_point = np.zeros(num_params) 

                # at first the AFM parameter
                self._scan_point[2:] = self._spm.scan_point()  
                
                # obtain ESR measurement
                self._counter.start_esr(num_esr_runs)
                esr_meas = self._counter.get_esr_meas()[:, 2:]

                esr_meas_mean = esr_meas.mean(axis=0)
                esr_meas_std = esr_meas.std(axis=0)
                
                mag_field = 0.0

                try:

                    # perform analysis and fit for the measured data:
                    if single_res:
                        res = self._fitlogic.make_lorentzian_fit(freq_list,
                                                                 esr_meas_mean,
                                                                 estimator=self._fitlogic.estimate_lorentzian_dip)
                        res_freq = res.params['center'].value
                        #FIXME: use Tesla not Gauss, right not, this is just for display purpose
                        mag_field =  self.calc_mag_field_single_res(res_freq, 
                                                                    self.ZFS, 
                                                                    self.E_FIELD) * 10000


                    else:    
                        res = self._fitlogic.make_lorentziandouble_fit(freq_list, 
                                                                       esr_meas_mean,
                                                                       estimator=self._fitlogic.estimate_lorentziandouble_dip)

                        res_freq_low = res.params['l0_center'].value
                        res_freq_high = res.params['l1_center'].value
                        #FIXME: use Tesla not Gauss, right not, this is just for display purpose
                        mag_field = self.calc_mag_field_double_res(res_freq_low,
                                                              res_freq_high, 
                                                              self.ZFS, 
                                                              self.E_FIELD)* 10000

                    fluorescence = res.params['offset']

                except:
                    self.log.warning(f'Fit was not working at line {line_num//2} and index {index}. Data needs to be post-processed.')

                # here the counts are saved:
                self._scan_point[0] = fluorescence
                # here the b_field is saved:
                self._scan_point[1] = mag_field
                
                if reverse_meas:

                    for param_index, param_name in enumerate(curr_scan_params):
                        name = f'{param_name}_bw'

                        self._qafm_scan_array[name]['data'][line_num // 2][coord0_num-index-1] = self._scan_point[param_index] * self._qafm_scan_array[name]['scale_fac']

                    # insert number from the back
                    self._esr_scan_array['esr_bw']['data'][line_num// 2][coord0_num-index-1] = esr_meas_mean
                    self._esr_scan_array['esr_bw']['data_std'][line_num//2][coord0_num-index-1] = esr_meas_std
 
                else:

                    for param_index, param_name in enumerate(curr_scan_params):
                        name = f'{param_name}_fw'

                        self._qafm_scan_array[name]['data'][line_num // 2][index] = self._scan_point[param_index] * self._qafm_scan_array[name]['scale_fac']

                    self._esr_scan_array['esr_fw']['data'][line_num//2][index] = esr_meas_mean
                    self._esr_scan_array['esr_fw']['data_std'][line_num//2][index] = esr_meas_std


                self.log.info(f'Point: {line_num * coord0_num + index + 1} out of {coord0_num*coord1_num*2}, {(line_num * coord0_num + index +1)/(coord0_num*coord1_num*2) * 100:.2f}% finished.')

                if index != last_elem:
                    self._afm_pos['x'] += x_step
                    self.sigNewAFMPos.emit({'x': self._afm_pos['x']})

                self._scan_counter += 1

                # emit a signal at every point, so that update can happen in real time.
                self.sigQAFMLineScanFinished.emit()

                # remove possibility to stop during line scan.
                if self._stop_request:
                   break

            # self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')

            # store the current line number
            self._spm_line_num = line_num

            # break irrespective of the direction of the scan
            if self._stop_request:
                break

            # perform optimization always after line finishes
            if (datetime.datetime.now() - opti_counter).total_seconds() > self._optimize_period:

                self.log.info('Enter optimization.')

                self._counter.prepare_pixelclock()
                self._spm.finish_scan()

                self.default_optimize()
                _, _, _ = self._spm.setup_spm(plane=plane,
                                              line_points=coord0_num,
                                              meas_params=meas_params)
                self._counter.prepare_cw_esr(freq_list, esr_count_freq, mw_power)
                opti_counter = datetime.datetime.now()



        stop_time_afm_scan = datetime.datetime.now()
        self._afm_meas_duration = self._afm_meas_duration + (stop_time_afm_scan - start_time_afm_scan).total_seconds()

        if line_num == self._spm_line_num:
            self.log.info(f'Scan finished at {int(self._afm_meas_duration)}s. Yeehaa!')
        else:
            self.log.info(f'Scan stopped at {int(self._afm_meas_duration)}s.')

        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Measurement stop'] = stop_time_afm_scan.isoformat()
            self._qafm_scan_array[entry]['params']['Total measurement time (s)'] = self._afm_meas_duration

        # clean up the spm
        self._spm.finish_scan()
        #self.module_state.unlock()
        self.sigQuantiScanFinished.emit()

        return self._qafm_scan_array

    def start_scan_area_quanti_qafm_fw_bw_by_point(self, coord0_start, coord0_stop,
                                              coord0_num, coord1_start, coord1_stop,
                                              coord1_num, int_time_afm=0.1,
                                              idle_move_time=0.1, freq_start=2.77e9,
                                              freq_stop=2.97e9, freq_points=100,
                                              esr_count_freq=200,
                                              mw_power=0.4, num_esr_runs=30,
                                              optimize_period=100,
                                              meas_params=['Height(Dac)'],
                                              single_res=True,
                                              continue_meas=False):

        if self.check_thread_active():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self._worker_thread = WorkerThread(target=self.scan_area_quanti_qafm_fw_bw_by_point,
                                            args=(coord0_start, coord0_stop,
                                              coord0_num, coord1_start, coord1_stop,
                                              coord1_num, int_time_afm,
                                              idle_move_time, freq_start,
                                              freq_stop, freq_points,
                                              esr_count_freq,
                                              mw_power, num_esr_runs,
                                              optimize_period,
                                              meas_params,
                                              single_res,
                                              continue_meas),
                                            name='quanti_thread')
        self.threadpool.start(self._worker_thread)

    # ==============================================================================
    #           Quantitative Mode with ESR just forward movement
    # ==============================================================================

    def scan_area_quanti_qafm_fw_by_point(self, coord0_start, coord0_stop,
                                             coord0_num, coord1_start, coord1_stop,
                                             coord1_num, int_time_afm=0.1,
                                             idle_move_time=0.1, freq_start=2.77e9,
                                             freq_stop=2.97e9, freq_points=100,
                                             esr_count_freq=200,
                                             mw_power=0.4, num_esr_runs=30,
                                             optimize_period=100,
                                             meas_params=['Height(Dac)'],
                                             single_res=True,
                                             continue_meas=False):

        """ QAFM measurement (optical + afm) snake movement for a scan by point.

        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param int coord0_num: number of points in coord0 direction
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int coord1_num: start coordinate in um
        @param int coord0_num: number of points in coord1 direction
        @param float int_time_afm: integration time for afm operations
        @param float idle_move_time: time for a movement where nothing is measured
        @param float freq_start: start frequency for ESR scan in Hz
        @param float freq_stop: stop frequency for ESR scan in Hz
        @param float freq_points: number of frequencies for ESR scan
        @param count_freq: The count frequency in ESR scan in Hz
        @param float mw_power: microwave power during scan
        @param int num_esr_runs: number of ESR runs

        @param list meas_params: list of possible strings of the measurement
                                 parameter. Have a look at MEAS_PARAMS to see
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list.
        """

        # self.log.info('forwards scan started.')
        # self.log.info(f'{coord0_start, coord0_stop, coord0_num, coord1_start, coord1_stop, coord1_num, int_time_afm, idle_move_time, freq_start, freq_stop, freq_points, esr_count_freq, mw_power, num_esr_runs, optimize_period, meas_params, single_res, continue_meas}')
        # time.sleep(3)
        # self.sigQuantiScanFinished.emit()
        # return

        # self.module_state.lock()
        plane = 'XY'

        # set up the spm device:
        ## reverse_meas = False
        self._stop_request = False

        self._optimize_period = optimize_period

        # make the counter for esr ready
        freq_list = np.linspace(freq_start, freq_stop, freq_points, endpoint=True)
        self._counter.prepare_cw_esr(freq_list, esr_count_freq, mw_power)

        # scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = int_time_afm

        scan_arr = self._spm.create_scan_leftright(coord0_start, coord0_stop,
                                                   coord1_start, coord1_stop, coord1_num)
        # scan_arr = self._spm.create_scan_snake(coord0_start, coord0_stop,
        #                                        coord1_start, coord1_stop, coord1_num)

        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=meas_params)

        curr_scan_params.insert(0, 'b_field')  # insert the fluorescence parameter
        curr_scan_params.insert(0, 'counts')  # insert the fluorescence parameter

        # this case is for starting a new measurement:
        if (self._spm_line_num == 0) or (not continue_meas):
            self._spm_line_num = 0
            self._afm_meas_duration = 0

            # AFM signal
            self._qafm_scan_array = self.initialize_qafm_scan_array(coord0_start, coord0_stop, coord0_num,
                                                                    coord1_start, coord1_stop, coord1_num)
            self._scan_counter = 0

            self._esr_scan_array = self.initialize_esr_scan_array(freq_start, 
                                                                  freq_stop, 
                                                                  freq_points,
                                                                  coord0_start, 
                                                                  coord0_stop, 
                                                                  coord0_num,
                                                                  coord1_start, 
                                                                  coord1_stop, 
                                                                  coord1_num)


            # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop,
                                                            coord1_start, coord1_stop)
        if ret_val < 1:
            self.sigQuantiScanFinished.emit()
            return self._qafm_scan_array

        start_time_afm_scan = datetime.datetime.now()
        opti_counter = datetime.datetime.now()
        self._curr_scan_params = curr_scan_params

        # save the measurement parameter
        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Parameters for'] = 'QAFM measurement'
            self._qafm_scan_array[entry]['params']['axis name for coord0'] = 'X'
            self._qafm_scan_array[entry]['params']['axis name for coord1'] = 'Y'
            self._qafm_scan_array[entry]['params']['measurement plane'] = 'XY'
            self._qafm_scan_array[entry]['params']['coord0_start (m)'] = coord0_start
            self._qafm_scan_array[entry]['params']['coord0_stop (m)'] = coord0_stop
            self._qafm_scan_array[entry]['params']['coord0_num (#)'] = coord0_num
            self._qafm_scan_array[entry]['params']['coord1_start (m)'] = coord1_start
            self._qafm_scan_array[entry]['params']['coord1_stop (m)'] = coord1_stop
            self._qafm_scan_array[entry]['params']['coord1_num (#)'] = coord1_num

            self._qafm_scan_array[entry]['params']['ESR Frequency start (Hz)'] = freq_start
            self._qafm_scan_array[entry]['params']['ESR Frequency stop (Hz)'] = freq_stop
            self._qafm_scan_array[entry]['params']['ESR Frequency points (#)'] = freq_points
            self._qafm_scan_array[entry]['params']['ESR Count Frequency (Hz)'] = esr_count_freq
            self._qafm_scan_array[entry]['params']['ESR MW power (gain)'] = mw_power
            self._qafm_scan_array[entry]['params']['ESR Measurement runs (#)'] = num_esr_runs
            self._qafm_scan_array[entry]['params']['Expect one resonance dip'] = single_res
            self._qafm_scan_array[entry]['params']['Optimize Period (s)'] = optimize_period

            self._qafm_scan_array[entry]['params']['AFM integration time per pixel (s)'] = int_time_afm
            self._qafm_scan_array[entry]['params']['AFM time for idle move (s)'] = idle_move_time
            self._qafm_scan_array[entry]['params']['Measurement parameter list'] = str(curr_scan_params)
            self._qafm_scan_array[entry]['params']['Measurement start'] = start_time_afm_scan.isoformat()

        for line_num, scan_coords in enumerate(scan_arr):

            # for a continue measurement event, skip the first measurements
            # until one has reached the desired line, then continue from there.
            if line_num < self._spm_line_num:

                # take care of the proper order of the data
                # if line_num%2 == 0:
                #     # i.e. next measurement must be in reversed order
                #     reverse_meas = True
                # else:
                #     reverse_meas = False
                continue

            num_params = len(curr_scan_params)

            self.set_afm_pos({'x': scan_coords[0], 'y': scan_coords[2]})
            time.sleep(1)

            self._spm.setup_scan_line(corr0_start=scan_coords[0],
                                      corr0_stop=scan_coords[1],
                                      corr1_start=scan_coords[2],
                                      corr1_stop=scan_coords[3],
                                      time_forward=scan_speed_per_line,
                                      time_back=idle_move_time)

            # -1 otherwise it would be more than coord0_num points, since first one is counted too.
            x_step = (scan_coords[1] - scan_coords[0]) / (coord0_num - 1)

            self._afm_pos = {'x': scan_coords[0], 'y': scan_coords[2]}

            vals = self._spm.scan_point()  # these are points to throw away
            self.sigNewAFMPos.emit(self._afm_pos)

            # if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")

            last_elem = list(range(coord0_num))[-1]

            for index in range(coord0_num):

                # first two entries are counts and b_field, remaining entries are the scan parameter
                self._scan_point = np.zeros(num_params) 

                # at first the AFM parameter
                self._debug = self._spm.scan_point()
                self._scan_point[2:] = self._debug 
                
                # obtain ESR measurement
                self._counter.start_esr(num_esr_runs)
                esr_meas = self._counter.get_esr_meas()[:, 2:]

                esr_meas_mean = esr_meas.mean(axis=0)
                esr_meas_std = esr_meas.std(axis=0)
                
                mag_field = 0.0
                fluorescence = 0.0

                try:

                    # perform analysis and fit for the measured data:
                    if single_res:
                        res = self._fitlogic.make_lorentzian_fit(freq_list,
                                                                 esr_meas_mean,
                                                                 estimator=self._fitlogic.estimate_lorentzian_dip)
                        res_freq = res.params['center'].value
                        #FIXME: use Tesla not Gauss, right not, this is just for display purpose
                        mag_field =  self.calc_mag_field_single_res(res_freq, 
                                                                    self.ZFS, 
                                                                    self.E_FIELD) * 10000


                    else:    
                        res = self._fitlogic.make_lorentziandouble_fit(freq_list, 
                                                                       esr_meas_mean,
                                                                       estimator=self._fitlogic.estimate_lorentziandouble_dip)

                        res_freq_low = res.params['l0_center'].value
                        res_freq_high = res.params['l1_center'].value
                        #FIXME: use Tesla not Gauss, right not, this is just for display purpose
                        mag_field = self.calc_mag_field_double_res(res_freq_low,
                                                                   res_freq_high,
                                                                   self.ZFS,
                                                                   self.E_FIELD) * 10000

                    fluorescence = res.params['offset'].value

                except:
                    self.log.warning(f'Fit was not working at line {line_num} and index {index}. Data needs to be post-processed.')

                # here the counts are saved:
                self._scan_point[0] = fluorescence
                # here the b_field is saved:
                self._scan_point[1] = mag_field

                # save measured data in array:
                for param_index, param_name in enumerate(curr_scan_params):
                    name = f'{param_name}_fw'

                    self._qafm_scan_array[name]['data'][line_num][index] = self._scan_point[param_index] * self._qafm_scan_array[name]['scale_fac']

                self._esr_scan_array['esr_fw']['data'][line_num][index] = esr_meas_mean
                self._esr_scan_array['esr_fw']['data_std'][line_num][index] = esr_meas_std

                # For debugging, display status text:
                progress_text = f'Point: {line_num * coord0_num + index + 1} out of {coord0_num * coord1_num }, {(line_num * coord0_num + index + 1) / (coord0_num * coord1_num ) * 100:.2f}% finished.'
                print(progress_text)
                self.log.info(progress_text)

                # track current AFM position:
                if index != last_elem:
                    self._afm_pos['x'] += x_step
                    self.sigNewAFMPos.emit({'x': self._afm_pos['x']})

                self._scan_counter += 1

                # emit a signal at every point, so that update can happen in real time.
                self.sigQAFMLineScanFinished.emit()

                # possibility to stop during line scan.
                if self._stop_request:
                    break

            self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')

            self.sigQAFMLineScanFinished.emit()

            # store the current line number
            self._spm_line_num = line_num

            if self._stop_request:
                break

            # perform optimization always after line finishes
            if (datetime.datetime.now() - opti_counter).total_seconds() > self._optimize_period:


                self.log.info('Enter optimization.')

                self._counter.prepare_pixelclock()
                self._spm.finish_scan()

                time.sleep(1)

                self.default_optimize()
                _, _, _ = self._spm.setup_spm(plane=plane,
                                              line_points=coord0_num,
                                              meas_params=meas_params)
                self._counter.prepare_cw_esr(freq_list, esr_count_freq, mw_power)
                time.sleep(1)
                opti_counter = datetime.datetime.now()


            self.log.info('Pass optimization.')

        stop_time_afm_scan = datetime.datetime.now()
        self._afm_meas_duration = self._afm_meas_duration + (
                    stop_time_afm_scan - start_time_afm_scan).total_seconds()

        if line_num == self._spm_line_num:
            self.log.info(f'Scan finished at {int(self._afm_meas_duration)}s. Yeehaa!')
        else:
            self.log.info(f'Scan stopped at {int(self._afm_meas_duration)}s.')

        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Measurement stop'] = stop_time_afm_scan.isoformat()
            self._qafm_scan_array[entry]['params']['Total measurement time (s)'] = self._afm_meas_duration

        # clean up the spm
        self._spm.finish_scan()
        # self.module_state.unlock()
        self.sigQuantiScanFinished.emit()

        return self._qafm_scan_array

    def start_scan_area_quanti_qafm_fw_by_point(self, coord0_start, coord0_stop,
                                                   coord0_num, coord1_start, coord1_stop,
                                                   coord1_num, int_time_afm=0.1,
                                                   idle_move_time=0.1, freq_start=2.77e9,
                                                   freq_stop=2.97e9, freq_points=100,
                                                   esr_count_freq=200,
                                                   mw_power=0.4, num_esr_runs=30,
                                                   optimize_period=100,
                                                   meas_params=['Height(Dac)'],
                                                   single_res=True,
                                                   continue_meas=False):

        if self.check_thread_active():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self._worker_thread = WorkerThread(target=self.scan_area_quanti_qafm_fw_by_point,
                                            args=(coord0_start, coord0_stop,
                                                  coord0_num, coord1_start, coord1_stop,
                                                  coord1_num, int_time_afm,
                                                  idle_move_time, freq_start,
                                                  freq_stop, freq_points,
                                                  esr_count_freq,
                                                  mw_power, num_esr_runs,
                                                  optimize_period,
                                                  meas_params,
                                                  single_res,
                                                  continue_meas),
                                            name='qanti_thread')
        self.threadpool.start(self._worker_thread)

# ==============================================================================
#             forward and backward QAFM (optical + afm) scan
# ==============================================================================

    @deprecated(details='Use the method "scan_area_qafm_bw_fw_by_line" instead.')
    def scan_area_qafm_bw_fw_by_point(self, coord0_start, coord0_stop, coord0_num,
                                      coord1_start, coord1_stop, coord1_num,
                                      integration_time, meas_params=['Height(Dac)'],
                                      continue_meas=False):

        """ QAFM measurement (optical + afm) forward and backward for a scan by point.
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int coord0_num: number of points in x direction
        @param int res_y: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """

        self.module_state.lock()
        plane='XY'

        # set up the spm device:
        reverse_meas = False      
        self._stop_request = False

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        
        if self._counterlogic.module_state.current == 'idle':
            self._counterlogic.startCount()

        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_arr = self._spm.create_scan_leftright2(coord0_start, coord0_stop, 
                                                    coord1_start, coord1_stop, coord1_num)

        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=meas_params)

        curr_scan_params.insert(0, 'b_field')  # insert the fluorescence parameter
        curr_scan_params.insert(0, 'counts')   # insert the fluorescence parameter

        # this case is for starting a new measurement:
        if (self._spm_line_num==0) or (not continue_meas):
            self._spm_line_num = 0
            self._afm_meas_duration = 0

            # AFM signal
            self._qafm_scan_array = self.initialize_qafm_scan_array(coord0_start, coord0_stop, coord0_num,
                                                                    coord1_start, coord1_stop, coord1_num)
            self._scan_counter = 0   

        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop,
                                                            coord1_start, coord1_stop)
        if ret_val < 1:
            return self._qafm_scan_array

        start_time_afm_scan = datetime.datetime.now()
        self._curr_scan_params = curr_scan_params

        # save the measurement parameter
        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Parameters for'] = 'QAFM measurement'
            self._qafm_scan_array[entry]['params']['axis name for coord0'] = 'X'
            self._qafm_scan_array[entry]['params']['axis name for coord1'] = 'Y'
            self._qafm_scan_array[entry]['params']['measurement plane'] = 'XY'
            self._qafm_scan_array[entry]['params']['coord0_start (m)'] = coord0_start
            self._qafm_scan_array[entry]['params']['coord0_stop (m)'] = coord0_stop
            self._qafm_scan_array[entry]['params']['coord0_num (#)'] = coord0_num
            self._qafm_scan_array[entry]['params']['coord1_start (m)'] = coord1_start
            self._qafm_scan_array[entry]['params']['coord1_stop (m)'] = coord1_stop
            self._qafm_scan_array[entry]['params']['coord1_num (#)'] = coord1_num

            self._qafm_scan_array[entry]['params']['integration time per pixel (s)'] = integration_time
            self._qafm_scan_array[entry]['params']['Measurement parameter list'] = str(curr_scan_params)
            self._qafm_scan_array[entry]['params']['Measurement start'] = start_time_afm_scan.isoformat()


        for line_num, scan_coords in enumerate(scan_arr):
            
            # for a continue measurement event, skip the first measurements 
            # until one has reached the desired line, then continue from there.
            if line_num < self._spm_line_num:
                continue

            num_params = len(curr_scan_params)
            # optical + AFM signal
            self._qafm_scan_line = np.zeros(num_params*coord0_num)
            
            self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                      corr0_stop=scan_coords[1], 
                                      corr1_start=scan_coords[2], 
                                      corr1_stop=scan_coords[3], 
                                      time_forward=scan_speed_per_line, 
                                      time_back=scan_speed_per_line)

            # -1 otherwise it would be more than coord0_num points, since first one is counted too.
            x_step = (scan_coords[1]-scan_coords[0])/(coord0_num-1)

            self._afm_pos = {'x': scan_coords[0], 'y': scan_coords[2]}


            vals = self._spm.scan_point()  # these are points to throw away
            self.sigNewAFMPos.emit(self._afm_pos)

            #if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")

            last_elem = list(range(coord0_num))[-1]
            for index in range(coord0_num):

                #Important: Get first counts, then the SPM signal!
                # self._qafm_scan_line[index*num_params] = self._counter.get_counter(1)[0][0]
                self._qafm_scan_line[index*num_params] = self._counterlogic.get_last_counts(1)[0][0]

                self._qafm_scan_line[index*num_params+1:(index+1)*num_params] = self._spm.scan_point()

                if index != last_elem:                
                    self._afm_pos['x'] += x_step
                    self.sigNewAFMPos.emit({'x': self._afm_pos['x']})

                self._scan_counter += 1
                
                # remove possibility to stop during line scan.
                #if self._stop_request:
                #    break

            """ 
            Algorithm:
            - make the _qafm_scan_array an dictionary
            - initialize the dictionary
            - for loop around the curr_scan_params
            - select those entries from for loop which are required and save to the correct dict entry

            """

            if reverse_meas:

                # mirror array due to backscan and take care that numbers are 
                # inserted in reversed order:
                self._qafm_scan_line = self._qafm_scan_line.reshape((len(self._qafm_scan_line)//num_params, num_params) )[::-1].ravel()

                for index, param_name in enumerate(curr_scan_params):
                    name = f'{param_name}_bw'   # use the unterlying naming convention
                    # save to the corresponding matrix line and renormalize the results to SI units:
                    self._qafm_scan_array[name]['data'][line_num//2] = self._qafm_scan_line[index::num_params] * self._qafm_scan_array[name]['scale_fac']
                reverse_meas = False

                # emit only a signal if the reversed is finished.
                self.sigQAFMLineScanFinished.emit() 
            else:
                for index, param_name in enumerate(curr_scan_params):
                    name = f'{param_name}_fw'   # use the unterlying naming convention
                    # save to the corresponding matrix line and renormalize the results to SI units:
                    self._qafm_scan_array[name]['data'][line_num//2] = self._qafm_scan_line[index::num_params] * self._qafm_scan_array[name]['scale_fac']
                reverse_meas = True

            #self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')

            # enable the break only if next scan goes into forward movement
            if self._stop_request and not reverse_meas:
                break

            # store the current line number
            self._spm_line_num = line_num

        stop_time_afm_scan = datetime.datetime.now()
        self._afm_meas_duration = self._afm_meas_duration + (stop_time_afm_scan - start_time_afm_scan).total_seconds()

        if line_num == self._spm_line_num:
            self.log.info(f'Scan finished at {int(self._afm_meas_duration)}s. Yeehaa!')
        else:
            self.log.info(f'Scan stopped at {int(self._afm_meas_duration)}s.')

        for entry in self._qafm_scan_array:
            self._qafm_scan_array[entry]['params']['Measurement stop'] = stop_time_afm_scan.isoformat()
            self._qafm_scan_array[entry]['params']['Total measurement time (s)'] = self._afm_meas_duration

        # clean up the spm
        self._spm.finish_scan()
        self.module_state.unlock()
        self.sigQAFMScanFinished.emit()
        
        return self._qafm_scan_array

    @deprecated(details='Use the method "start_scan_area_qafm_bw_fw_by_line" instead.')
    def start_scan_area_qafm_bw_fw_by_point(self, coord0_start=48*1e-6, coord0_stop=53*1e-6, coord0_num=40,
                            coord1_start=47*1e-6, coord1_stop=52*1e-6, coord1_num=40, integration_time=0.02,
                            meas_params=['Phase', 'Height(Dac)', 'Height(Sen)'],
                            continue_meas=False):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.scan_area_qafm_bw_fw_by_point, 
                                            args=(coord0_start, coord0_stop, coord0_num,
                                                  coord1_start, coord1_stop, coord1_num,
                                                  integration_time,
                                                  meas_params, continue_meas), 
                                            name='meas_thread')
        self.meas_thread.start()


# ==============================================================================
# pure optical measurement, by point
# ==============================================================================
    @deprecated(details='Use the method "scan_area_obj_by_line" instead.')
    def scan_area_obj_by_point(self, coord0_start, coord0_stop, coord0_num,
                               coord1_start, coord1_stop, coord1_num,
                               integration_time, plane='X2Y2',
                               continue_meas=False, wait_first_point=True):

        """ QAFM measurement (optical + afm) forward and backward for a scan by point.
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int coord0_num: number of points in x direction
        @param int coord1_num: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """

        #TODO&FIXME: check the following parameters:
        # self._spm_line_num
        # self._scan_counter

        self.module_state.lock()

        # check input values
        ret_val = self._spm.check_spm_scan_params_by_plane(plane,
                                                           coord0_start,
                                                           coord0_stop,
                                                           coord1_start,
                                                           coord1_stop)
        if ret_val < 1:
            self.module_state.unlock()
            return self._obj_scan_array

        # create mapping to refer to the the correct position of the coordinate
        mapping = {'coord0': plane[0].lower(), 'coord1': plane[2].lower()}

        # set up the spm device:
        reverse_meas = False      
        self._stop_request = False

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        
        if self._counterlogic.module_state.current == 'idle':
            self._counterlogic.startCount()

        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_arr = self._spm.create_scan_leftright(coord0_start, coord0_stop, 
                                                   coord1_start, coord1_stop,
                                                   coord1_num)

        #FIXME: check whether the number of parameters are required and whether they are set correctly.
        # self._spm._params_per_point = len(names_buffers)
        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=[],
                                                           scan_mode=1) # point mode
        if ret_val < 1:
            self.module_state.unlock()
            return self._obj_scan_array


        curr_scan_params.insert(0, 'counts')   # insert the fluorescence parameter

        #FIXME: Implement an better initialization procedure
        #FIXME: Create a better naming for the matrices

        if (self._spm_line_num==0) or (not continue_meas):
            self._spm_line_num = 0
            self._obj_meas_duration = 0

            self._obj_scan_array = self.initialize_obj_scan_array(arr_name,
                                                                  coord0_start, 
                                                                  coord0_stop,
                                                                  coord0_num,
                                                                  coord1_start, 
                                                                  coord1_stop,
                                                                  coord1_num)
            self._scan_counter = 0   


        start_time_obj_scan = datetime.datetime.now()
        num_params = len(curr_scan_params)

        # save the measurement parameter
        self._obj_scan_array[arr_name]['params']['Parameters for'] = 'Objective measurement'
        self._obj_scan_array[arr_name]['params']['axis name for coord0'] = arr_name[-2].upper()
        self._obj_scan_array[arr_name]['params']['axis name for coord1'] = arr_name[-1].upper()
        self._obj_scan_array[arr_name]['params']['measurement plane'] = arr_name[-2:].upper()
        self._obj_scan_array[arr_name]['params']['coord0_start (m)'] = coord0_start
        self._obj_scan_array[arr_name]['params']['coord0_stop (m)'] = coord0_stop
        self._obj_scan_array[arr_name]['params']['coord0_num (#)'] = coord0_num
        self._obj_scan_array[arr_name]['params']['coord1_start (m)'] = coord1_start
        self._obj_scan_array[arr_name]['params']['coord1_stop (m)'] = coord1_stop
        self._obj_scan_array[arr_name]['params']['coord1_num (#)'] = coord1_num

        self._obj_scan_array[arr_name]['params']['integration time per pixel (s)'] = integration_time
        self._obj_scan_array[arr_name]['params']['Measurement start'] = start_time_obj_scan.isoformat()

        time.sleep(3)


        for line_num, scan_coords in enumerate(scan_arr):
            
            # for a continue measurement event, skip the first measurements 
            # until one has reached the desired line, then continue from there.
            if line_num < self._spm_line_num:
                continue

            
            # optical signal only
            self._obj_scan_line = np.zeros(num_params*coord0_num)
            
            self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                      corr0_stop=scan_coords[1], 
                                      corr1_start=scan_coords[2], 
                                      corr1_stop=scan_coords[3], 
                                      time_forward=scan_speed_per_line, 
                                      time_back=scan_speed_per_line)

            # -1 otherwise it would be more than coord0_num points, since first one is counted too.
            coord0_step = (scan_coords[1] - scan_coords[0])/ (coord0_num-1)

            vals = self._spm.scan_point()  # these are points to throw away

            # this is the first point to approach:
            new_coords = {mapping['coord0']: scan_coords[0], mapping['coord1']: scan_coords[2]}
            self._obj_pos.update(new_coords)
            self.sigNewObjPos.emit(new_coords)

            # wait a bit before starting to count the first value.
            if wait_first_point:
                time.sleep(2)
                wait_first_point = False

            last_elem = list(range(coord0_num))[-1]
            for index in range(coord0_num):

                #Important: Get first counts, then the SPM signal!
                self._obj_scan_line[index*num_params] = self._counter.get_counter(1)[0][0]
                # self._obj_scan_line[index*num_params] = self._counterlogic.get_last_counts(1)[0][0]

                #start_time = datetime.datetime.now()

                self._spm.scan_point()

                #self._time_call[line_num][index] = (datetime.datetime.now() - start_time).total_seconds()

                if index != last_elem:
                    self._obj_pos[mapping['coord0']] += coord0_step
                    self.sigNewObjPos.emit({mapping['coord0']: self._obj_pos[mapping['coord0']]})
                
                self._scan_counter += 1
                
                # remove possibility to stop during line scan.
                #if self._stop_request:
                #    break

            self._obj_scan_array[arr_name]['data'][line_num] = self._obj_scan_line
            self.sigObjLineScanFinished.emit(arr_name)


            # enable the break only if next scan goes into forward movement
            if self._stop_request:
                break

            # store the current line number
            self._spm_line_num = line_num
            print(f'Line number {line_num} completed.')

        stop_time_obj_scan = datetime.datetime.now()
        self._obj_meas_duration = self._obj_meas_duration + (stop_time_obj_scan - start_time_obj_scan).total_seconds()

        if line_num == self._spm_line_num:
            self.log.info(f'Objective scan finished after {int(self._obj_meas_duration)}s. Yeehaa!')
        else:
            self.log.info(f'Objective scan stopped after {int(self._obj_meas_duration)}s.')

        self._obj_scan_array[arr_name]['params']['Measurement stop'] = stop_time_obj_scan.isoformat()
        self._obj_scan_array[arr_name]['params']['Total measurement time (s)'] = self._obj_meas_duration
        
        # clean up the spm
        self._spm.finish_scan()
        self.module_state.unlock()
        self.sigObjScanFinished.emit()
        
        return self._obj_scan_array

    @deprecated(details='Use the method "start_scan_area_obj_by_line" instead.')
    def start_scan_area_obj_by_point(self, coord0_start=48*1e-6, coord0_stop=53*1e-6, coord0_num=40,
                                     coord1_start=47*1e-6, coord1_stop=52*1e-6, coord1_num=40,
                                     integration_time=0.02, plane='X2Y2',
                                     continue_meas=False):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.scan_area_obj_by_point, 
                                            args=(coord0_start, coord0_stop, coord0_num,
                                                  coord1_start, coord1_stop, coord1_num,
                                                  integration_time,
                                                  plane, continue_meas), 
                                            name='meas_thread')
        self.meas_thread.start()

# ==============================================================================
# pure optical measurement, by line
# ==============================================================================

    def scan_area_obj_by_line(self, coord0_start, coord0_stop, coord0_num,
                               coord1_start, coord1_stop, coord1_num,
                               integration_time, plane='X2Y2',
                               continue_meas=False):

        """ QAFM measurement (optical + afm) forward and backward for a scan by line.

        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int coord0_num: number of points in x direction
        @param int coord1_num: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement
                                 parameter. Have a look at MEAS_PARAMS to see
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list.
        """
        if integration_time is None:
            integration_time = self._sg_int_time_obj_scan

        self.module_state.lock()

        coord0, coord1 = (0.0, 0.0)

        mapping = {'coord0': 0}

        if plane == 'X2Y2':
            arr_name = 'obj_xy'
            mapping = {'coord0': 0, 'coord1': 1, 'fixed': 2}
        elif plane == 'X2Z2':
            arr_name = 'obj_xz'
            mapping = {'coord0': 0, 'fixed': 1, 'coord1': 2, }
        elif plane == 'Y2Z2':
            arr_name = 'obj_yz'
            mapping = {'fixed': 0, 'coord0': 1, 'coord1': 2}

        # set up the spm device:
        reverse_meas = False
        self._stop_request = False

        # time in which the stage is just moving without measuring
        time_idle_move = self._sg_idle_move_scan_obj

        if self._counter.get_device_mode() != 'pixel':
            self._counter.prepare_pixelclock()

        # scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time * coord0_num

        # FIXME: Uncomment for snake like scan, however, not recommended!!!
        #       As it will distort the picture.
        # scan_arr = self._spm.create_scan_snake(coord0_start, coord0_stop,
        #                                        coord1_start, coord1_stop,
        #                                        coord1_num)

        scan_arr = self._spm.create_scan_leftright(coord0_start, coord0_stop,
                                                   coord1_start, coord1_stop,
                                                   coord1_num)


        # FIXME: check whether the number of parameters are required and whether they are set correctly.
        # self._spm._params_per_point = len(names_buffers)
        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=[],
                                                           scan_mode=0) # line scan

        curr_scan_params.insert(0, 'counts')  # insert the fluorescence parameter

        self._spm.enable_point_trigger()


        # FIXME: Implement an better initialization procedure
        # FIXME: Create a better naming for the matrices

        if (self._spm_line_num == 0) or (not continue_meas):
            self._spm_line_num = 0
            self._obj_meas_duration = 0

            self._obj_scan_array = self.initialize_obj_scan_array(arr_name,
                                                                  coord0_start,
                                                                  coord0_stop,
                                                                  coord0_num,
                                                                  coord1_start,
                                                                  coord1_stop,
                                                                  coord1_num)

            self._scan_counter = 0

            # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane,
                                                            coord0_start,
                                                            coord0_stop,
                                                            coord1_start,
                                                            coord1_stop)

        if ret_val < 1:
            return self._obj_scan_array

        start_time_obj_scan = datetime.datetime.now()
        num_params = len(curr_scan_params)

        # save the measurement parameter
        self._obj_scan_array[arr_name]['params']['Parameters for'] = 'Objective measurement'
        self._obj_scan_array[arr_name]['params']['axis name for coord0'] = arr_name[-2].upper()
        self._obj_scan_array[arr_name]['params']['axis name for coord1'] = arr_name[-1].upper()
        self._obj_scan_array[arr_name]['params']['measurement plane'] = arr_name[-2:].upper()
        self._obj_scan_array[arr_name]['params']['coord0_start (m)'] = coord0_start
        self._obj_scan_array[arr_name]['params']['coord0_stop (m)'] = coord0_stop
        self._obj_scan_array[arr_name]['params']['coord0_num (#)'] = coord0_num
        self._obj_scan_array[arr_name]['params']['coord1_start (m)'] = coord1_start
        self._obj_scan_array[arr_name]['params']['coord1_stop (m)'] = coord1_stop
        self._obj_scan_array[arr_name]['params']['coord1_num (#)'] = coord1_num
        self._obj_scan_array[arr_name]['params']['Scan speed per line (s)'] = scan_speed_per_line
        self._obj_scan_array[arr_name]['params']['Idle movement speed (s)'] = time_idle_move

        self._obj_scan_array[arr_name]['params']['integration time per pixel (s)'] = integration_time
        self._obj_scan_array[arr_name]['params']['Measurement start'] = start_time_obj_scan.isoformat()


        for line_num, scan_coords in enumerate(scan_arr):

            # for a continue measurement event, skip the first measurements
            # until one has reached the desired line, then continue from there.
            if line_num < self._spm_line_num:
                continue

            # optical signal only
            self._obj_scan_line = np.zeros(num_params * coord0_num)

            self._spm.setup_scan_line(corr0_start=scan_coords[0],
                                      corr0_stop=scan_coords[1],
                                      corr1_start=scan_coords[2],
                                      corr1_stop=scan_coords[3],
                                      time_forward=scan_speed_per_line,
                                      time_back=time_idle_move)

            self._counter.arm_device(coord0_num)
            self._spm.scan_line()

            #FIXME: Uncomment for snake like scan, however, not recommended!!!
            #       As it will distort the picture.
            # if line_num % 2 == 0:
            #     self._obj_scan_array[arr_name]['data'][line_num] = self._counter.get_line() / integration_time
            # else:
            #     self._obj_scan_array[arr_name]['data'][line_num] = self._counter.get_line()[::-1] / integration_time

            self._obj_scan_array[arr_name]['data'][line_num] = self._counter.get_line()/integration_time
            self.sigObjLineScanFinished.emit(arr_name)

            # enable the break only if next scan goes into forward movement
            if self._stop_request:
                break

            # store the current line number
            self._spm_line_num = line_num
            #print(f'Line number {line_num} completed.')

        stop_time_obj_scan = datetime.datetime.now()
        self._obj_meas_duration = self._obj_meas_duration + (
                    stop_time_obj_scan - start_time_obj_scan).total_seconds()

        if line_num == self._spm_line_num:
            self.log.info(f'Objective scan finished after {int(self._obj_meas_duration)}s. Yeehaa!')
        else:
            self.log.info(f'Objective scan stopped after {int(self._obj_meas_duration)}s.')

        self._obj_scan_array[arr_name]['params']['Measurement stop'] = stop_time_obj_scan.isoformat()
        self._obj_scan_array[arr_name]['params']['Total measurement time (s)'] = self._obj_meas_duration

        # clean up the spm
        self._spm.finish_scan()
        # clean up the counter
        self._counter.stop_measurement()

        self.module_state.unlock()
        self.sigObjScanFinished.emit()

        return self._obj_scan_array


    def start_scan_area_obj_by_line(self, coord0_start=48*1e-6, coord0_stop=53*1e-6, coord0_num=40,
                                     coord1_start=47*1e-6, coord1_stop=52*1e-6, coord1_num=40,
                                     integration_time=None, plane='X2Y2',
                                     continue_meas=False):

        if self.check_thread_active():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self._worker_thread = WorkerThread(target=self.scan_area_obj_by_line,
                                           args=(coord0_start, coord0_stop, coord0_num,
                                                 coord1_start, coord1_stop, coord1_num,
                                                 integration_time,
                                                 plane, continue_meas),
                                           name='obj_scan')
        self.threadpool.start(self._worker_thread)

# ==============================================================================
# Optimizer scan an area by point
# ==============================================================================

    @deprecated(details='Use the method "scan_area_obj_by_line_opti" instead.')
    def scan_area_obj_by_point_opti(self, coord0_start, coord0_stop, coord0_num,
                                    coord1_start, coord1_stop, coord1_num,
                                    integration_time,
                                    wait_first_point=True):

        """ Measurement method for a scan by point, with just one linescan
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int coord0_num: number of points in x direction
        @param int coord1_num: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """
        meas_params = []
        #FIXME: implement general optimizer for all the planes
        plane='X2Y2'

        opti_name = 'opti_xy'

        start_time_opti = datetime.datetime.now()
        self._opti_meas_duration = 0

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        self._counterlogic.startCount()

        # set up the spm device:
        self._stop_request = False
        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_arr = self._spm.create_scan_leftright(coord0_start, coord0_stop, 
                                                   coord1_start, coord1_stop, coord1_num)

        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=meas_params)
        

        self._opti_scan_array = self.initialize_opti_xy_scan_array(coord0_start, coord0_stop, coord0_num,
                                                                   coord1_start, coord1_stop, coord1_num)
        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop, coord1_start, coord1_stop)   

        if ret_val < 1:
            return self._opti_scan_array

        self._opti_scan_array[opti_name]['params']['Parameters for'] = 'Optimize XY measurement'
        self._opti_scan_array[opti_name]['params']['axis name for coord0'] = opti_name[-2].upper()
        self._opti_scan_array[opti_name]['params']['axis name for coord1'] = opti_name[-1].upper()
        self._opti_scan_array[opti_name]['params']['measurement plane'] = opti_name[-2:].upper()
        self._opti_scan_array[opti_name]['params']['coord0_start (m)'] = coord0_start
        self._opti_scan_array[opti_name]['params']['coord0_stop (m)'] = coord0_stop
        self._opti_scan_array[opti_name]['params']['coord0_num (#)'] = coord0_num
        self._opti_scan_array[opti_name]['params']['coord1_start (m)'] = coord1_start
        self._opti_scan_array[opti_name]['params']['coord1_stop (m)'] = coord1_stop
        self._opti_scan_array[opti_name]['params']['coord1_num (#)'] = coord1_num

        self._opti_scan_array[opti_name]['params']['integration time per pixel (s)'] = integration_time
        self._opti_scan_array[opti_name]['params']['Measurement start'] = start_time_opti.isoformat()

        self._scan_counter = 0

        for line_num, scan_coords in enumerate(scan_arr):
            
            # APD signal
            self._opti_scan_line = np.zeros(coord0_num)
            
            self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                      corr0_stop=scan_coords[1], 
                                      corr1_start=scan_coords[2], 
                                      corr1_stop=scan_coords[3], 
                                      time_forward=scan_speed_per_line, 
                                      time_back=scan_speed_per_line)

            # -1 otherwise it would be more than coord0_num points, since first one is counted too.
            coord0_step = (scan_coords[1] - scan_coords[0])/ (coord0_num-1)


            vals = self._spm.scan_point()  # these are points to throw away

            new_coords = {'x': scan_coords[0], 'y': scan_coords[2]}
            self._obj_pos.update(new_coords)
            self.sigNewObjPos.emit(new_coords)

            # wait a bit before starting to count the first value.
            if wait_first_point and (self._scan_counter == 0):
                time.sleep(2)

            #if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")
            last_elem = list(range(coord0_num))[-1]
            for index in range(coord0_num):

                #Important: Get first counts, then the SPM signal!
                self._opti_scan_line[index] = self._counter.get_counter(1)[0][0]
                # self._opti_scan_line[index] = self._counterlogic.get_last_counts(1)[0][0]

                self._spm.scan_point()
                
                if index != last_elem:
                    self._obj_pos['x'] += coord0_step
                    self.sigNewObjPos.emit({'x': self._obj_pos['x']})

                self._scan_counter += 1
                if self._stop_request:
                    break

            self._opti_scan_array[opti_name]['data'][line_num] = self._opti_scan_line
            self.sigOptimizeLineScanFinished.emit(opti_name)

            if self._stop_request:
                break

            #self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')

        stop_time_opti = datetime.datetime.now()
        self._opti_meas_duration = (stop_time_opti - start_time_opti).total_seconds()
        self.log.info(f'Optimizer finished after {int(self._opti_meas_duration)}s. Yeehaa!')

        self._opti_scan_array[opti_name]['params']['Measurement stop'] = stop_time_opti.isoformat()
        self._opti_scan_array[opti_name]['params']['Total measurement time (s)'] = self._opti_meas_duration

        # clean up the counter
        self._counter.stop_measurement()
        time.sleep(1)
        
        # clean up the spm
        self._spm.finish_scan()

        
        return self._opti_scan_array

# ==============================================================================
# Optimizer scan an area by line
# ==============================================================================

    def scan_area_obj_by_line_opti(self, coord0_start, coord0_stop, coord0_num,
                                    coord1_start, coord1_stop, coord1_num,
                                    integration_time):

        """ Measurement method for a scan by line, with just one linescan

        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int coord0_num: number of points in x direction
        @param int coord1_num: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement
                                 parameter. Have a look at MEAS_PARAMS to see
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list.
        """



        meas_params = []
        # FIXME: implement general optimizer for all the planes
        plane = 'X2Y2'

        opti_name = 'opti_xy'

        start_time_opti = datetime.datetime.now()
        self._opti_meas_duration = 0

        # set up the spm device:
        self._stop_request = False
        # scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time * coord0_num

        #FIXME: Make this a setting value
        time_idle_move = 0.1 # in seconds, time in which the stage is just
                             # moving without measuring

        if self._counter.get_device_mode() != 'pixel':
            self._counter.prepare_pixelclock()

        scan_arr = self._spm.create_scan_leftright(coord0_start, coord0_stop,
                                                   coord1_start, coord1_stop,
                                                   coord1_num)

        #TODO: implement the scan line mode
        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=coord0_num,
                                                           meas_params=meas_params,
                                                           scan_mode=0) # line scan
        self._spm.enable_point_trigger()

        self._opti_scan_array = self.initialize_opti_xy_scan_array(coord0_start,
                                                                   coord0_stop,
                                                                   coord0_num,
                                                                   coord1_start,
                                                                   coord1_stop,
                                                                   coord1_num)
        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane,
                                                            coord0_start,
                                                            coord0_stop,
                                                            coord1_start,
                                                            coord1_stop)

        if ret_val < 1:
            return self._opti_scan_array

        self._opti_scan_array[opti_name]['params']['Parameters for'] = 'Optimize XY measurement'
        self._opti_scan_array[opti_name]['params']['axis name for coord0'] = opti_name[-2].upper()
        self._opti_scan_array[opti_name]['params']['axis name for coord1'] = opti_name[-1].upper()
        self._opti_scan_array[opti_name]['params']['measurement plane'] = opti_name[-2:].upper()
        self._opti_scan_array[opti_name]['params']['coord0_start (m)'] = coord0_start
        self._opti_scan_array[opti_name]['params']['coord0_stop (m)'] = coord0_stop
        self._opti_scan_array[opti_name]['params']['coord0_num (#)'] = coord0_num
        self._opti_scan_array[opti_name]['params']['coord1_start (m)'] = coord1_start
        self._opti_scan_array[opti_name]['params']['coord1_stop (m)'] = coord1_stop
        self._opti_scan_array[opti_name]['params']['coord1_num (#)'] = coord1_num
        self._opti_scan_array[opti_name]['params']['Scan speed per line (s)'] = scan_speed_per_line
        self._opti_scan_array[opti_name]['params']['Idle movement speed (s)'] = time_idle_move

        self._opti_scan_array[opti_name]['params']['integration time per pixel (s)'] = integration_time
        self._opti_scan_array[opti_name]['params']['Measurement start'] = start_time_opti.isoformat()

        self._scan_counter = 0

        for line_num, scan_coords in enumerate(scan_arr):

            # APD signal
            self._opti_scan_line = np.zeros(coord0_num)

            self._spm.setup_scan_line(corr0_start=scan_coords[0],
                                      corr0_stop=scan_coords[1],
                                      corr1_start=scan_coords[2],
                                      corr1_stop=scan_coords[3],
                                      time_forward=scan_speed_per_line,
                                      time_back=time_idle_move)

            self._counter.arm_device(coord0_num)
            self._spm.scan_line()

            self._opti_scan_array[opti_name]['data'][line_num] = self._counter.get_line()/integration_time
            self.sigOptimizeLineScanFinished.emit(opti_name)

            if self._stop_request:
                break

            # self.log.info(f'Line number {line_num} completed.')
            # print(f'Line number {line_num} completed.')

        stop_time_opti = datetime.datetime.now()
        self._opti_meas_duration = (stop_time_opti - start_time_opti).total_seconds()
        self.log.info(f'Optimizer XY finished after {int(self._opti_meas_duration)}s. Yeehaa!')

        self._opti_scan_array[opti_name]['params']['Measurement stop'] = stop_time_opti.isoformat()
        self._opti_scan_array[opti_name]['params']['Total measurement time (s)'] = self._opti_meas_duration


        # clean up the counter
        self._counter.stop_measurement()

        # clean up the spm
        self._spm.finish_scan()


        return self._opti_scan_array

# ==============================================================================
#           Scan of just one line for optimizer by point
# ==============================================================================

    @deprecated(details='Use the method "scan_line_obj_by_line_opti" instead.')
    def scan_line_obj_by_point_opti(self, coord0_start, coord0_stop, coord1_start,
                                    coord1_stop, res, integration_time, 
                                    wait_first_point=False, continue_meas=False):

        """ Measurement method for a scan by point.
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int res_x: number of points in x direction
        @param int res_y: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """

        meas_params = []
        plane='X2Z2'

        opti_name = 'opti_z'

        self._start = time.time()

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        self._counterlogic.startCount()

        # set up the spm device:
        reverse_meas = False
        self._stop_request = False
        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_coords = [coord0_start, coord0_stop, coord1_start, coord1_stop]

        #FIXME: check whether the number of parameters are required and whether they are set correctly.
        # self._spm._params_per_point = len(names_buffers)
        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=res, 
                                                           meas_params=meas_params)


        self._opti_scan_array = self.initialize_opti_z_scan_array(coord1_start, coord1_stop, res)


        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop, coord1_start, coord1_stop)   

        if ret_val < 1:
            return self._opti_scan_array

        self._scan_counter = 0

        start_time_opti = datetime.datetime.now()

        self._opti_scan_array[opti_name]['params']['Parameters for'] = 'Optimize Z measurement'
        self._opti_scan_array[opti_name]['params']['axis name for coord0'] = 'Z'
        self._opti_scan_array[opti_name]['params']['measurement direction '] = 'Z'
        self._opti_scan_array[opti_name]['params']['coord0_start (m)'] = coord1_start
        self._opti_scan_array[opti_name]['params']['coord0_stop (m)'] = coord1_stop
        self._opti_scan_array[opti_name]['params']['coord0_num (#)'] = res

        self._opti_scan_array[opti_name]['params']['integration time per pixel (s)'] = integration_time
        self._opti_scan_array[opti_name]['params']['Measurement start'] = start_time_opti.isoformat()


        # Optimizer Z signal
        self._opti_scan_array[opti_name]['data'] = np.zeros(res)
        
        self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                  corr0_stop=scan_coords[1], 
                                  corr1_start=scan_coords[2], 
                                  corr1_stop=scan_coords[3], 
                                  time_forward=scan_speed_per_line, 
                                  time_back=scan_speed_per_line)

        # -1 otherwise it would be more than res_x points, since first one is counted too.
        coord1_step = (scan_coords[3] - scan_coords[2])/ (res-1)

        vals = self._spm.scan_point()  # these are points to throw away

        new_coords = {'x': scan_coords[0], 'z': scan_coords[2]}
        self._obj_pos.update(new_coords)
        self.sigNewObjPos.emit(new_coords)

        if wait_first_point and (self._scan_counter == 0):
            time.sleep(2)

        #if len(vals) > 0:
        #    self.log.error("The scanner range was not correctly set up!")

        last_elem = list(range(res))[-1]
        for index in range(res):

            #Important: Get first counts, then the SPM signal!
            #self._apd_line_scan[index] = self._counter.get_counter(1)[0][0]
            self._opti_scan_array[opti_name]['data'][index] = self._counter.get_counter(1)[0][0]
            # self._opti_scan_array[opti_name]['data'][index] = self._counterlogic.get_last_counts(1)[0][0]

            self._spm.scan_point()

            if index != last_elem:
                self._obj_pos['z'] += coord1_step
                self.sigNewObjPos.emit({'z': self._obj_pos['z']})
            
            self._scan_counter += 1
            if self._stop_request:
                break

         #self.log.info(f'Line number {line_num} completed.')
        print(f'Optimizer Z scan complete.')
        self.sigOptimizeLineScanFinished.emit(opti_name)

        stop_time_opti = datetime.datetime.now()
        self._opti_meas_duration = (stop_time_opti - start_time_opti).total_seconds()
        self.log.info(f'Scan finished after {int(self._opti_meas_duration)}s. Yeehaa!')

        self._opti_scan_array[opti_name]['params']['Measurement stop'] = stop_time_opti.isoformat()
        self._opti_scan_array[opti_name]['params']['Total measurement time (s)'] = self._opti_meas_duration

        # clean up the spm
        self._spm.finish_scan()
        
        return self._opti_scan_array

# ==============================================================================
#           Scan of just one line for optimizer by line
# ==============================================================================

    def scan_line_obj_by_line_opti(self, coord0_start, coord0_stop, coord1_start,
                                    coord1_stop, res, integration_time,
                                    continue_meas=False):

        """ Measurement method for a scan by line.

        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int res_x: number of points in x direction
        @param int res_y: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement
                                 parameter. Have a look at MEAS_PARAMS to see
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list.
        """

        meas_params = []
        plane = 'X2Z2'

        opti_name = 'opti_z'

        self._start = time.time()


        # set up the spm device:
        reverse_meas = False
        self._stop_request = False

        # FIXME: Make this a setting value
        time_idle_move = 0.1 # in seconds, time in which the stage is just
                             # moving without measuring

        if self._counter.get_device_mode() != 'pixel':
            self._counter.prepare_pixelclock()
            
        # scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time * res

        scan_coords = [coord0_start, coord0_stop, coord1_start, coord1_stop]

        # FIXME: check whether the number of parameters are required and whether they are set correctly.
        # self._spm._params_per_point = len(names_buffers)
        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=res,
                                                           meas_params=meas_params,
                                                           scan_mode=0) # line scan

        self._spm.enable_point_trigger()

        self._opti_scan_array = self.initialize_opti_z_scan_array(coord1_start,
                                                                  coord1_stop,
                                                                  res)
        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane,
                                                            coord0_start,
                                                            coord0_stop,
                                                            coord1_start,
                                                            coord1_stop)
        if ret_val < 1:
            return self._opti_scan_array

        self._scan_counter = 0

        start_time_opti = datetime.datetime.now()

        self._opti_scan_array[opti_name]['params']['Parameters for'] = 'Optimize Z measurement'
        self._opti_scan_array[opti_name]['params']['axis name for coord0'] = 'Z'
        self._opti_scan_array[opti_name]['params']['measurement direction '] = 'Z'
        self._opti_scan_array[opti_name]['params']['coord0_start (m)'] = coord1_start
        self._opti_scan_array[opti_name]['params']['coord0_stop (m)'] = coord1_stop
        self._opti_scan_array[opti_name]['params']['coord0_num (#)'] = res

        self._opti_scan_array[opti_name]['params']['Scan speed per line (s)'] = scan_speed_per_line
        self._opti_scan_array[opti_name]['params']['Idle movement speed (s)'] = time_idle_move

        self._opti_scan_array[opti_name]['params']['integration time per pixel (s)'] = integration_time
        self._opti_scan_array[opti_name]['params']['Measurement start'] = start_time_opti.isoformat()

        # Optimizer Z signal
        self._opti_scan_array[opti_name]['data'] = np.zeros(res)

        self._spm.setup_scan_line(corr0_start=scan_coords[0],
                                  corr0_stop=scan_coords[1],
                                  corr1_start=scan_coords[2],
                                  corr1_stop=scan_coords[3],
                                  time_forward=scan_speed_per_line,
                                  time_back=time_idle_move)

        self._counter.arm_device(res)
        self._spm.scan_line()

        self._opti_scan_array[opti_name]['data'] = self._counter.get_line()/integration_time

        #print(f'Optimizer Z scan complete.')
        self.sigOptimizeLineScanFinished.emit(opti_name)

        stop_time_opti = datetime.datetime.now()
        self._opti_meas_duration = (stop_time_opti - start_time_opti).total_seconds()
        self.log.info(f'Scan finished after {int(self._opti_meas_duration)}s. Yeehaa!')

        self._opti_scan_array[opti_name]['params']['Measurement stop'] = stop_time_opti.isoformat()
        self._opti_scan_array[opti_name]['params']['Total measurement time (s)'] = self._opti_meas_duration

        # clean up the spm
        self._spm.finish_scan()
        # clean up the counter
        self._counter.stop_measurement()

        return self._opti_scan_array

# ==============================================================================
#   Optimize position routine
# ==============================================================================

    def get_optimizer_target(self):
        """ Obtain the current target position for the optimizer. 

        @return tuple: with (x, y, z) as the target position in m.
        """

        return (self._optimizer_x_target_pos, 
                self._optimizer_y_target_pos,
                self._optimizer_z_target_pos)

    def set_optimizer_target(self, x_target=None, y_target=None, z_target=None):
        """ Set the target position for the optimizer around which optimization happens. """

        if x_target is not None:
            self._optimizer_x_target_pos = x_target 
        if y_target is not None:
            self._optimizer_y_target_pos = y_target 
        if z_target is not None:
            self._optimizer_z_target_pos = z_target 

        #FIXME: Think about a general method and a generic return for this method
        #       to obtain the currently set target positions.



    #FIXME: Check, whether optimizer can get out of scan range, and if yes, 
    #       react to this!
    def default_optimize(self, run_in_thread=False):
        """ Note, this is a blocking method for optimization! """
        pos = self.get_obj_pos()

        _optimize_period = 60

        # make step symmetric
        x_step = self._sg_optimizer_x_range/2
        y_step = self._sg_optimizer_y_range / 2
        z_step = self._sg_optimizer_z_range / 2

        x_start = self._optimizer_x_target_pos - x_step
        x_stop = self._optimizer_x_target_pos + x_step
        res_x = self._sg_optimizer_x_res
        y_start = self._optimizer_y_target_pos - y_step
        y_stop = self._optimizer_y_target_pos + y_step
        res_y = self._sg_optimizer_y_res
        z_start = self._optimizer_z_target_pos - z_step
        z_stop = self._optimizer_z_target_pos + z_step
        res_z = self._sg_optimizer_z_res
        int_time_xy = self._sg_optimizer_int_time
        int_time_z = self._sg_optimizer_int_time

        if run_in_thread:
            self.start_optimize_pos(x_start, x_stop, res_x, y_start, y_stop,
                                    res_y,  z_start, z_stop, res_z, int_time_xy,
                                    int_time_z)
        else:
            self.optimize_obj_pos(x_start, x_stop, res_x, y_start, y_stop,
                                  res_y, z_start, z_stop, res_z, int_time_xy, 
                                  int_time_z)

    def optimize_obj_pos(self, x_start, x_stop, res_x, y_start, y_stop, res_y,
                         z_start, z_stop, res_z, int_time_xy, int_time_z):
        """ Optimize position for x, y and z by going to maximal value"""

        # FIXME: Remove after tests!
        # opti_scan_arr = self.scan_area_obj_by_point_opti(x_start, x_stop, res_x,
        #                                                  y_start, y_stop, res_y,
        #                                                  int_time_xy,
        #                                                  wait_first_point=True)

        #FIXME: Module state
        # self.module_state.lock()

        opti_scan_arr = self.scan_area_obj_by_line_opti(x_start, x_stop, res_x,
                                                        y_start, y_stop, res_y,
                                                        int_time_xy)

        if self._stop_request:
            # self.module_state.unlock()
            self.sigOptimizeScanFinished.emit()
            return

        x_max, y_max, c_max = self._calc_max_val_xy(arr=opti_scan_arr['opti_xy']['data'], 
                                                    x_start=x_start, x_stop=x_stop, 
                                                    y_start=y_start, y_stop=y_stop)

        self._opti_scan_array['opti_xy']['params']['coord0 optimal pos (nm)'] = x_max
        self._opti_scan_array['opti_xy']['params']['coord1 optimal pos (nm)'] = y_max
        self._opti_scan_array['opti_xy']['params']['signal at optimal pos (c/s)'] = c_max

        if self._stop_request:
            # self.module_state.unlock()
            self.sigOptimizeScanFinished.emit()
            return


        pos = self.set_obj_pos( {'x': x_max, 'y': y_max})

        # curr_pos = self.get_obj_pos()
        # self._spm._set_pos_xy([x_max, y_max])
        # time.sleep(1)
        # self._spm._set_pos_xy([x_max, y_max])
        # time.sleep(1)
        # self._obj_pos[0] = x_max
        # self._obj_pos[1] = y_max
        self.sigNewObjPos.emit(self._obj_pos)


        # opti_scan_arr = self.scan_line_obj_by_point_opti(coord0_start=x_max, coord0_stop=x_max,
        #                                                coord1_start=z_start, coord1_stop=z_stop,
        #                                                res=res_z,
        #                                                integration_time=int_time_z,
        #                                                wait_first_point=True)
        opti_scan_arr = self.scan_line_obj_by_line_opti(coord0_start=x_max,
                                                        coord0_stop=x_max,
                                                        coord1_start=z_start,
                                                        coord1_stop=z_stop,
                                                        res=res_z,
                                                        integration_time=int_time_z)

        if self._stop_request:
            # self.module_state.unlock()
            self.sigOptimizeScanFinished.emit()
            return

        z_max, c_max_z = self._calc_max_val_z(opti_scan_arr['opti_z']['data'], z_start, z_stop)

        self._opti_scan_array['opti_z']['params']['coord0 optimal pos (nm)'] = z_max
        self._opti_scan_array['opti_z']['params']['signal at optimal pos (c/s)'] = c_max_z

        self.log.debug(f'Found maximum at: [{x_max*1e6:.2f}, {y_max*1e6:.2f}, {z_max*1e6:.2f}]')

        self.set_obj_pos({'x': x_max, 'y': y_max, 'z': z_max})

        # self.set_obj_pos(x_max, y_max, z_max)
        # time.sleep(2)
        # self.set_obj_pos(x_max, y_max, z_max)

        self._optimizer_x_target_pos = x_max
        self._optimizer_y_target_pos = y_max
        self._optimizer_z_target_pos = z_max

        self._opt_val = [x_max, y_max, c_max, z_max, c_max_z]
        # self.module_state.unlock()
        self.sigOptimizeScanFinished.emit()

        return x_max, y_max, c_max, z_max, c_max_z


    def start_optimize_pos(self, x_start, x_stop, res_x, y_start, y_stop, res_y, z_start, z_stop, res_z,
                           int_time_xy, int_time_z):

        if self.check_thread_active():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self._worker_thread = WorkerThread(target=self.optimize_obj_pos,
                                           args=(x_start, x_stop, res_x,
                                                 y_start, y_stop, res_y,
                                                 z_start, z_stop, res_z,
                                                 int_time_xy, int_time_z),
                                           name='optimizer')
        self.threadpool.start(self._worker_thread)


# ==============================================================================
# QAFM measurement with optimization possibility:
# ==============================================================================

    #FIXME: This methods needs to be checked!!
    def measure_point_optimized(self, x_start_afm=48*1e-6, x_stop_afm=53*1e-6, 
                                y_start_afm=47*1e-6, y_stop_afm=52*1e-6, 
                                res_x_afm=40, res_y_afm=40, integration_time_afm=0.02, 
                                plane_afm='XY',
                                meas_params=['Phase', 'Height(Dac)', 'Height(Sen)'],
                                continue_meas=False, optimize_int=60,
                                res_x_obj=25, res_y_obj=25, res_z_obj=25, 
                                int_time_xy_obj=0.01, int_time_z_obj=0.02):

        self._stop_request_all = False
        self._afm_meas_optimize_interval = optimize_int

        self.start_measure_point(x_start_afm, x_stop_afm, y_start_afm, y_stop_afm, 
                                 res_x_afm, res_y_afm, 
                                 integration_time_afm, plane_afm, meas_params, 
                                 continue_meas)

        # just safety wait
        time.sleep(0.1)

        time_start =  time.time()

        while not self._stop_request_all:
            time.sleep(1)

            if (time.time() - time_start) > self._afm_meas_optimize_interval:
                self.stop_measure()



                timeout = 60
                counter = 0
                # make a timeout for waiting
                while self.module_state.current != 'idle':
                    time.sleep(1)
                    counter += 1

                    if counter > timeout:
                        self.log.warning('Timeout reached! Abort optimize and quit.')
                        return

                x_start = self._opt_val[0] - 0.5*1e-6
                x_stop = self._opt_val[0] + 0.5*1e-6
                y_start = self._opt_val[1] - 0.5*1e-6
                y_stop = self._opt_val[1] + 0.5*1e-6
                z_start = 0*1e-6
                z_stop = 8*1e-6
                self.optimize_pos(x_start=x_start, x_stop=x_stop, 
                                  y_start=y_start, y_stop=y_stop, 
                                  z_start=z_start, z_stop=z_stop, 
                                  res_x=res_x_obj, res_y=res_y_obj, res_z=res_z_obj, 
                                  int_time_xy=int_time_xy_obj, 
                                  int_time_z=int_time_z_obj)


                time_start = time.time()

                self.start_measure_point(x_start_afm, x_stop_afm, y_start_afm, 
                                         y_stop_afm, res_x_afm, res_y_afm, 
                                         integration_time_afm, plane_afm, 
                                         meas_params, True)
                time.sleep(0.1)


            if self.module_state.current == 'idle':
                break


        self.log.info("Measurement completely finished, yeehaa!")


    def start_measure_point_optimized(self, x_start_afm=48*1e-6, x_stop_afm=53*1e-6, 
                                      y_start_afm=47*1e-6, y_stop_afm=52*1e-6, 
                                      res_x_afm=40, res_y_afm=40, 
                                      integration_time_afm=0.02, plane_afm='XY',
                                      meas_params=['Phase', 'Height(Dac)', 'Height(Sen)'],
                                      continue_meas=False, optimize_int=60,
                                      res_x_obj=25, res_y_obj=25, res_z_obj=25, 
                                      int_time_xy_obj=0.01, int_time_z_obj=0.02):

        if self.check_meas_opt_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread_opt = threading.Thread(target=self.measure_point_optimized, 
                                            args=(x_start_afm, x_stop_afm, 
                                                  y_start_afm, y_stop_afm, 
                                                  res_x_afm, res_y_afm, 
                                                  integration_time_afm, plane_afm,
                                                  meas_params, continue_meas,
                                                  optimize_int, res_x_obj, 
                                                  res_y_obj, res_z_obj, 
                                                  int_time_xy_obj, int_time_z_obj), 
                                            name='meas_thread_opt')
        self.meas_thread_opt.start()


# ==============================================================================
#           Method to measure just one line instead of whole area point
# ==============================================================================
    def scan_line_by_point(self, coord0_start, coord0_stop, coord1_start, coord1_stop, res, 
                           integration_time, plane='XY', meas_params=['Height(Dac)'],
                           wait_first_point=False, continue_meas=False):

        """ Measurement method for a scan by point.
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int res_x: number of points in x direction
        @param int res_y: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """


        self._start = time.time()

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        self._counterlogic.startCount()

        # set up the spm device:
        reverse_meas = False
        self._stop_request = False
        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_arr = [[coord0_start, coord0_stop, coord1_start, coord1_stop]]

        #FIXME: check whether the number of parameters are required and whether they are set correctly.
        # self._spm._params_per_point = len(names_buffers)
        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=res, 
                                                           meas_params=meas_params)
        # AFM signal
        self._meas_array_scan = np.zeros(len(meas_params)*res)
        # APD signal
        self._apd_array_scan = np.zeros(res)

        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop, coord1_start, coord1_stop)   

        if ret_val < 1:
            return self._apd_array_scan, self._meas_array_scan



        self._scan_counter = 0

        for line_num, scan_coords in enumerate(scan_arr):
            
            # AFM signal
            self._meas_line_scan = np.zeros(len(curr_scan_params)*res)
            # APD signal
            self._apd_line_scan = np.zeros(res)
            
            self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                      corr0_stop=scan_coords[1], 
                                      corr1_start=scan_coords[2], 
                                      corr1_stop=scan_coords[3], 
                                      time_forward=scan_speed_per_line, 
                                      time_back=scan_speed_per_line)
            
            vals = self._spm.scan_point()  # these are points to throw away

            if wait_first_point and (self._scan_counter == 0):
                time.sleep(2)

            #if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")

            for index in range(res):

                #Important: Get first counts, then the SPM signal!
                #self._apd_line_scan[index] = self._counter.get_counter(1)[0][0]
                self._apd_line_scan[index] = self._counterlogic.get_last_counts(1)[0][0]

                self._meas_line_scan[index*len(curr_scan_params):(index+1)*len(curr_scan_params)] = self._spm.scan_point()
                
                self._scan_counter += 1
                if self._stop_request:
                    break

                self._meas_array_scan = self._meas_line_scan
                self._apd_array_scan = self._apd_line_scan

            if self._stop_request:
                break

            #self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')
                
        self._stop = time.time() - self._start
        self.log.info(f'Scan finished after {int(self._stop)}s. Yeehaa!')

        # clean up the counter:
        #self._counter.close_counter()
        #self._counter.close_clock()
        
        # clean up the spm
        self._spm.finish_scan()
        
        return self._apd_array_scan, self._meas_array_scan

    def start_measure_line_point(self, coord0_start=0*1e-6, coord0_stop=0*1e-6, 
                                 coord1_start=0*1e-6, coord1_stop=10*1e-6, 
                                 res=100, integration_time=0.02, plane='XY',
                                 meas_params=['Phase', 'Height(Dac)', 'Height(Sen)'],
                                 wait_first_point=False):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.scan_line_by_point, 
                                            args=(coord0_start, coord0_stop, 
                                                  coord1_start, coord1_stop, 
                                                  res, 
                                                  integration_time,
                                                  plane,
                                                  meas_params, wait_first_point), 
                                            name='meas_thread')

        self.meas_thread.start()

# ==============================================================================
#        General stop routine, to stop the current running measurement
# ==============================================================================

    def stop_measure(self):
        #self._counter.stop_measurement()
        self._stop_request = True

        #FIXME: this is mostly for debugging reasons, but it should be removed later.
        # unlock the state in case an error has happend.
        if not self._worker_thread.is_running():
            self._counter.cond.wakeAll()
            if self.module_state() != 'idle':
                self.module_state.unlock()
            return -1
        return 0

        #self._spm.finish_scan()


# ==============================================================================
#        Higher level optimization routines for objective scanner
# ==============================================================================

    def optimize_pos(self, x_start, x_stop, y_start, y_stop, z_start,z_stop, 
                     res_x, res_y, res_z, int_time_xy, int_time_z):
        """ Optimize position for x, y and z by going to maximal value"""


        apd_arr_xy, afm_arr_xy = self.scan_by_point_single_line(x_start, x_stop, 
                                       y_start, y_stop, res_x, res_y, 
                                       int_time_xy, plane='X2Y2', meas_params=[], 
                                       wait_first_point=True)

        if self._stop_request:
            return

        x_max, y_max, c_max = self._calc_max_val_xy(arr=apd_arr_xy, x_start=x_start,
                                                    x_stop=x_stop, y_start=y_start,
                                                    y_stop=y_stop)
        if self._stop_request:
            return

        self.set_obj_pos({'x': x_max, 'y':y_max})

        # self._spm._set_pos_xy([x_max, y_max])
        # time.sleep(1)
        # self._spm._set_pos_xy([x_max, y_max])
        # time.sleep(1)

        apd_arr_z, afm_arr_z = self.scan_line_by_point(coord0_start=x_max, coord0_stop=x_max, 
                                                       coord1_start=z_start, coord1_stop=z_stop, 
                                                       res=res_z, 
                                                       integration_time=int_time_z, 
                                                       plane='X2Z2', meas_params=[],
                                                       wait_first_point=True)

        if self._stop_request:
            return

        z_max, c_max_z = self._calc_max_val_z(apd_arr_z, z_start, z_stop)

        self.set_obj_pos({'x': x_max, 'y': y_max, 'z':z_max})

        # self._spm.set_pos_obj([x_max, y_max, z_max])
        # time.sleep(2)
        # self._spm.set_pos_obj([x_max, y_max, z_max])

        self._opt_val = [x_max, y_max, c_max, z_max, c_max_z]

        return x_max, y_max, c_max, z_max, c_max_z


    def _calc_max_val_xy(self, arr, x_start, x_stop, y_start, y_stop):
        """ Calculate the maximal value in an 2d array. """
        np.amax(arr)
        column_max = np.amax(arr, axis=1).argmax()
        row_max = np.amax(arr, axis=0).argmax()
        column_num, row_num = np.shape(arr)

        x_max = (row_max + 1)/row_num * (x_stop - x_start) + x_start
        y_max = (column_max + 1)/column_num * (y_stop - y_start) + y_start
        c_max = arr[column_max, row_max]

        #FIXME: make sure c_max is the fitted value coming from x_max and y_max

        x_axis = np.linspace(x_start,x_stop,row_num)
        y_axis = np.linspace(y_start,y_stop,column_num)

        optimizer_x, optimizer_y = np.meshgrid(x_axis, y_axis)

        xy_axes = np.empty((len(x_axis) * len(y_axis), 2))
        xy_axes = (optimizer_x.flatten(), optimizer_y.flatten())

        for i in range(3):
            try:
                res = self._fitlogic.make_twoDgaussian_fit(xy_axes,arr.ravel(),
                    estimator=self._fitlogic.estimate_twoDgaussian_MLE)

                x_max = res.params['center_x'].value
                y_max = res.params['center_y'].value

                break

            except:
                pass

        return (x_max, y_max, c_max)


    def _calc_max_val_z(self, arr_z, z_start, z_stop):
        """ Calculate maximum value from z scan. """
        c_max = arr_z.max()
        z_max = arr_z.argmax()/len(arr_z) * (z_stop-z_start) + z_start
        z_axis = np.linspace(z_start,z_stop,len(arr_z))

        res = self._fitlogic.make_gaussianlinearoffset_fit(z_axis,arr_z,
            estimator=self._fitlogic.estimate_gaussianlinearoffset_peak)

        #FIXME: make sure c_max is the fitted value coming from z_max

        z_max = res.params['center'].value

        return z_max, c_max


    def start_measure_opt_pos(self, x_start, x_stop, y_start, y_stop, z_start, z_stop, 
                              res_x, res_y, res_z, int_time_xy, int_time_z):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.optimize_pos, 
                                            args=(x_start, x_stop, 
                                                  y_start, y_stop,
                                                  z_start, z_stop, 
                                                  res_x, res_y, res_z,
                                                  int_time_xy, int_time_z), 
                                            name='meas_thread')
        self.meas_thread.start()

# ==============================================================================
#        Perform a scan just in one direction
# ==============================================================================

    def scan_by_point_single_line(self, coord0_start, coord0_stop, 
                                  coord1_start, coord1_stop, 
                                  res_x, res_y, integration_time, plane='XY', 
                                  meas_params=['Height(Dac)'], 
                                  wait_first_point=False):

        """ Measurement method for a scan by point, with just one linescan
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int res_x: number of points in x direction
        @param int res_y: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """

        self._start = time.time()

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        self._counterlogic.startCount()

        # set up the spm device:
        self._stop_request = False
        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_arr = self._spm.create_scan_leftright(coord0_start, coord0_stop, 
                                                    coord1_start, coord1_stop, res_y)

        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=res_x, 
                                                           meas_params=meas_params)
        # AFM signal
        self._meas_array_scan = np.zeros((res_y, len(curr_scan_params)*res_x))
        # APD signal
        self._apd_array_scan = np.zeros((res_y, res_x))

        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop, coord1_start, coord1_stop)   

        if ret_val < 1:
            return (self._apd_array_scan, self._meas_array_scan)



        self._scan_counter = 0

        for line_num, scan_coords in enumerate(scan_arr):
            
            # AFM signal
            self._meas_line_scan = np.zeros(len(curr_scan_params)*res_x)
            # APD signal
            self._apd_line_scan = np.zeros(res_x)
            
            self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                      corr0_stop=scan_coords[1], 
                                      corr1_start=scan_coords[2], 
                                      corr1_stop=scan_coords[3], 
                                      time_forward=scan_speed_per_line, 
                                      time_back=scan_speed_per_line)
            
            vals = self._spm.scan_point()  # these are points to throw away

            # wait a bit before starting to count the first value.
            if wait_first_point and (self._scan_counter == 0):
                time.sleep(2)

            #if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")

            for index in range(res_x):

                #Important: Get first counts, then the SPM signal!
                self._apd_line_scan[index] = self._counter.get_counter(1)[0][0]
                self._meas_line_scan[index*len(curr_scan_params):(index+1)*len(curr_scan_params)] = self._spm.scan_point()
                
                self._scan_counter += 1
                if self._stop_request:
                    break

            self._meas_array_scan[line_num] = self._meas_line_scan
            self._apd_array_scan[line_num] = self._apd_line_scan


            if self._stop_request:
                break

            #self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')
                
        self._stop = time.time() - self._start
        self.log.info(f'Scan finished after {int(self._stop)}s. Yeehaa!')

        # clean up the counter:
        # self._counter.close_counter()
        # self._counter.close_clock()
        
        # clean up the spm
        self._spm.finish_scan()
        
        return (self._apd_array_scan, self._meas_array_scan)


    def start_measure_scan_by_point_single_line(self, coord0_start=0*1e-6, coord0_stop=0*1e-6, 
                                                coord1_start=0*1e-6, coord1_stop=10*1e-6, 
                                                res_x=100, res_y=100, integration_time=0.02, 
                                                plane='XY',
                                                meas_params=['Phase', 'Height(Dac)', 'Height(Sen)']):
        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.scan_by_point_single_line, 
                                            args=(coord0_start, coord0_stop, 
                                                  coord1_start, coord1_stop, 
                                                  res_x, res_y,
                                                  integration_time,
                                                  plane,
                                                  meas_params), 
                                            name='meas_thread')
        self.meas_thread.start()

# ==============================================================================
#        Perform a scan in a snake line way
# ==============================================================================

    def scan_area_by_point_snakeline(self, coord0_start, coord0_stop, 
                                     coord1_start, coord1_stop, res_x, res_y, 
                                     integration_time, plane='XY', 
                                     meas_params=['Height(Dac)']):

        """ Measurement method for a scan by point.
        
        @param float coord0_start: start coordinate in um
        @param float coord0_stop: start coordinate in um
        @param float coord1_start: start coordinate in um
        @param float coord1_stop: start coordinate in um
        @param int res_x: number of points in x direction
        @param int res_y: number of points in y direction
        @param float integration_time: time for the optical integration in s
        @param str plane: Name of the plane to be scanned. Possible options are
                            'XY', 'YZ', 'XZ', 'X2Y2', 'Y2Z2', 'X2Z2'
        @param list meas_params: list of possible strings of the measurement 
                                 parameter. Have a look at MEAS_PARAMS to see 
                                 the available parameters.

        @return 2D_array: measurement results in a two dimensional list. 
        """

        self._start = time.time()

        if not np.isclose(self._counterlogic.get_count_frequency(), 1/integration_time):
            self._counterlogic.set_count_frequency(frequency=1/integration_time)
        self._counterlogic.startCount()

        # set up the spm device:
        reverse_meas = False
        self._stop_request = False
        #scan_speed_per_line = 0.01  # in seconds
        scan_speed_per_line = integration_time
        scan_arr = self._spm.create_scan_snake(coord0_start, coord0_stop, 
                                               coord1_start, coord1_stop, res_y)

        ret_val, _, curr_scan_params = self._spm.setup_spm(plane=plane,
                                                           line_points=res_x, 
                                                           meas_params=meas_params)
        # AFM signal
        self._meas_array_scan = np.zeros((res_y, len(curr_scan_params)*res_x))
        # APD signal
        self._apd_array_scan = np.zeros((res_y, res_x))

        # check input values
        ret_val |= self._spm.check_spm_scan_params_by_plane(plane, coord0_start, coord0_stop, 
                                                            coord1_start, coord1_stop)   

        if ret_val < 1:
            return (self._apd_array_scan, self._meas_array_scan)

        self._scan_counter = 0

        for line_num, scan_coords in enumerate(scan_arr):
            
            # AFM signal
            self._meas_line_scan = np.zeros(len(curr_scan_params)*res_x)
            # APD signal
            self._apd_line_scan = np.zeros(res_x)
            
            self._spm.setup_scan_line(corr0_start=scan_coords[0], 
                                      corr0_stop=scan_coords[1], 
                                      corr1_start=scan_coords[2], 
                                      corr1_stop=scan_coords[3], 
                                      time_forward=scan_speed_per_line, 
                                      time_back=scan_speed_per_line)
            
            vals = self._spm.scan_point()  # these are points to throw away

            #if len(vals) > 0:
            #    self.log.error("The scanner range was not correctly set up!")

            for index in range(res_x):

                #Important: Get first counts, then the SPM signal!
                self._apd_line_scan[index] = self._counter.get_counter(1)[0][0]
                self._meas_line_scan[index*len(curr_scan_params):(index+1)*len(curr_scan_params)] = self._spm.scan_point()
                
                self._scan_counter += 1
                if self._stop_request:
                    break

            if reverse_meas:
                self._meas_array_scan[line_num] = self._meas_line_scan[::-1]
                self._apd_array_scan[line_num] = self._apd_line_scan[::-1]
                reverse_meas = False
            else:
                self._meas_array_scan[line_num] = self._meas_line_scan
                self._apd_array_scan[line_num] = self._apd_line_scan
                reverse_meas = True

            if self._stop_request:
                break

            #self.log.info(f'Line number {line_num} completed.')
            print(f'Line number {line_num} completed.')
                
        self._stop = time.time() - self._start
        self.log.info(f'Scan finished after {int(self._stop)}s. Yeehaa!')

        # clean up the counter:
        # self._counter.close_counter()
        # self._counter.close_clock()
        
        # clean up the spm
        self._spm.finish_scan()
        
        return (self._apd_array_scan, self._meas_array_scan)


    def start_measure_scan_area_by_point_snakeline(self, coord0_start=0*1e-6, coord0_stop=0*1e-6, 
                                                   coord1_start=0*1e-6, coord1_stop=10*1e-6, 
                                                   res_x=100, res_y=100, integration_time=0.02, 
                                                   plane='XY',
                                                   meas_params=['Phase', 'Height(Dac)', 'Height(Sen)']):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.scan_area_by_point_snakeline, 
                                            args=(coord0_start, coord0_stop, 
                                                  coord1_start, coord1_stop, 
                                                  res_x, res_y, 
                                                  integration_time,
                                                  plane,
                                                  meas_params), 
                                            name='meas_thread')
        self.meas_thread.start()

# ==============================================================================
#        Optimize objective scanner and track the maximal fluorescence level
# ==============================================================================

    @QtCore.Slot()
    def _optimize_finished(self):
        self.set_optimize_request(False)

    def set_optimize_request(self, state):
        """ Set the optimizer request flag.
        Optimization is performed at the next possible moment.

        Procedure:
            The gui should set all the optimizer settings parameter in the 
            logic, then check if meas thread is running and existing, 
                if no, run optimization routine
                if yes, set just the optimize request flag and the running 
                method will call the optimization at an appropriated point in 
                time.
            
            The optimization request will be not accepted during an optical 
            scan.
        """

        if state:

            if self.check_thread_active():
                if not self._worker_thread.name == 'obj_scan':
                    # set optimize request only if the state is appropriate for 
                    # this.
                    self._optimize_request = state

                    return True

            else:
                self.default_optimize(run_in_thread=True)

                return True



        else:
            self._optimize_request = state

        return False

    def get_optimize_request(self):
        return self._optimize_request


    def track_optimal_pos(self, x_start, x_stop, y_start, y_stop, z_start,z_stop, 
                          res_x, res_y, res_z, int_time_xy, int_time_z, wait_inbetween=60):

        self._stop_request = False
        self._opt_pos = {}

        counter = 0
        sleep_counter = 0



        while not self._stop_request:

            x_max, y_max, c_max, z_max, c_max_z = self.optimize_pos(x_start, x_stop, 
                                                                    y_start, y_stop, 
                                                                    z_start,z_stop, 
                                                                    res_x, res_y, res_z, 
                                                                    int_time_xy, int_time_z)

            # sleep for 1 minute
            while sleep_counter < wait_inbetween and not self._stop_request:
                time.sleep(1)
                sleep_counter += 1

            counts = self._counter.get_counter(100)[0].mean()
            self._opt_pos[counter] = [time.time(), x_max, y_max, c_max, z_max, c_max_z, counts]

            counter += 1
            sleep_counter = 0

            x_start = x_max - 0.5 *1e-6
            x_stop = x_max + 0.5 *1e-6
            y_start = y_max - 0.5 *1e-6
            y_stop = y_max + 0.5 *1e-6

        return self._opt_pos

    def start_track_optimal_pos(self, x_start=14*1e-6, x_stop=15*1e-6, y_start=14*1e-6, y_stop=15*1e-6, 
                                z_start=0*1e-6, z_stop=10*1e-6, res_x=25, res_y=25, res_z=500, 
                                int_time_xy=0.05, int_time_z=0.05, wait_inbetween=60):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.track_optimal_pos, 
                                            args=(x_start, x_stop, 
                                                  y_start, y_stop, 
                                                  z_start,z_stop, 
                                                  res_x, res_y, res_z, 
                                                  int_time_xy, int_time_z,
                                                  wait_inbetween), 
                                            name='meas_thread')
        self.meas_thread.start()

# ==============================================================================
#        Record fluorescence as a function of time at fixed objective position
# ==============================================================================

    def record_fluorescence(self, timeinterval=10, average_time=1, count_freq=50):
        """ Record the fluorescence signal over a certain time interval.

        @param float timeinterval: wait time between measurements
        @param float average_time: time over which to average counts
        @param float count_freq: count frequency of the fluorescence counter
        """

        # the fluorescence track arrays
        self._f_track_time = []
        self._f_track_counts = []

        if not np.isclose(self._counterlogic.get_count_frequency(), count_freq):
            self._counterlogic.set_count_frequency(frequency=count_freq)
        self._counterlogic.startCount()

        while not self._stop_request:
            time.sleep(timeinterval)
            samples = int(average_time*count_freq)
            self._f_track_counts.append(self._counter.get_counter(samples)[0].mean())
            self._f_track_time.append(time.time())

        return (self._f_track_time, self._f_track_counts)

    def start_record_fluorescence(self, timeinterval=10, average_time=1, count_freq=50):

        if self.check_meas_run():
            self.log.error("A measurement is currently running, stop it first!")
            return

        self.meas_thread = threading.Thread(target=self.record_fluorescence, 
                                        args=(timeinterval, average_time,
                                              count_freq), 
                                        name='meas_thread')
        self.meas_thread.start()


    @deprecated('Deprecated thread checking routine, use check_thread_active instead.')
    def check_meas_run(self):
        """ Check routine, whether main measurement thread is running. """
        if hasattr(self, 'meas_thread'):
            if self.meas_thread.isAlive():
                return True
        return False

    def check_thread_active(self):
        """ Check whether current worker thread is running. """

        if hasattr(self, '_worker_thread'):
            if self._worker_thread.is_running():
                return True
        return False




    def check_meas_opt_run(self):
        """ Check routine, whether main optimization measurement thread is running. """
        if hasattr(self, 'meas_thread_opt'):
            if self.meas_thread_opt.isAlive():
                return True
        
        return False

    def get_qafm_data(self):
        return self._qafm_scan_array

    def get_obj_data(self):
        return self._obj_scan_array

    def get_opti_data(self):
        return self._opti_scan_array

    def get_obj_pos(self, pos_list=['x', 'y', 'z']):
        """ Get objective position.

        @param list pos_list: optional, specify, which axis you want to have.
                              Possibilities are 'X' or 'x', 'Y' or 'y', 'Z' or
                              'z'.

        @return dict: the full position dict, containing the updated values.
        """

        # adapt to the standard convention of the hardware, do not manipulate
        # the passed list.
        target_pos_list = [0.0] * len(pos_list)
        for index, entry in enumerate(pos_list):
            target_pos_list[index] = entry.upper() + '2'

        pos = self._spm.get_objective_scanner_pos(target_pos_list)

        for entry in pos:
            self._obj_pos[entry[0].lower()] = pos[entry]

        return self._obj_pos

    def get_afm_pos(self, pos_list=['x', 'y']):
        """ Get AFM position.

        @param list pos_list: optional, specify, which axis you want to have.
                              Possibilities are 'X' or 'x', 'Y' or 'y'.

        @return dict: the full position dict, containing the updated values.
        """

        # adapt to the standard convention of the hardware, do not manipulate
        # the passed list.
        target_pos_list = [0.0] * len(pos_list)
        for index, entry in enumerate(pos_list):
            target_pos_list[index] = entry.upper() + '1'

        pos = self._spm.get_sample_scanner_pos(target_pos_list)

        for entry in pos:
            self._afm_pos[entry[0].lower()] = pos[entry] # for now I drop the z position

        return self._afm_pos

    def set_obj_pos(self, pos_dict, move_time=None):
        """ Set the objective position.

        @param dict pos_dict: a position dictionary containing keys as 'x', 'y'
                              and 'z' and the values are the positions in m.
                              E.g.:
                                    {'x': 10e-6, 'z': 1e-6}

        @return dict: the actual set position within the position dict. The full
                      position dict is returned.
        """

        if move_time is None:
            move_time = self._sg_idle_move_target_obj

        target_pos_dict = {}
        for entry in pos_dict:
            target_pos_dict[entry.upper() + '2'] = pos_dict[entry]

        pos = self._spm.set_objective_scanner_pos(target_pos_dict, 
                                                  move_time=move_time)

        for entry in pos:
            self._obj_pos[entry[0].lower()] = pos[entry]

        self.sigNewObjPos.emit(pos)
        if self.module_state() != 'locked':
            self.sigObjTargetReached.emit()

        return self._obj_pos

    def set_afm_pos(self, pos_dict, move_time=None):
        """ Set the AFM position.

        @param dict pos_dict: a position dictionary containing keys as 'x' and
                             'y', and the values are the positions in m.
                              E.g.:
                                    {'x': 10e-6, 'y': 1e-6}

        @return dict: the actual set position within the position dict. The full
                      position dict is returned.
        """

        if move_time is None:
            move_time = self._sg_idle_move_target_sample

        target_pos_dict = {}
        for entry in pos_dict:
            target_pos_dict[entry.upper()] = pos_dict[entry]

        pos = self._spm.set_sample_scanner_pos(target_pos_dict, move_time=move_time)

        for entry in pos:
            self._afm_pos[entry[0].lower()] = pos[entry]

        self.sigNewAFMPos.emit(pos)
        self.sigAFMTargetReached.emit()
        return self._afm_pos       



    def record_sample_distance(self, start_z, stop_z, num_z, int_time):
        pass

    def start_record_sample_distance(self, start_z, stop_z, num_z, int_time):
        pass



    def get_qafm_save_directory(self, use_qudi_savescheme=True, root_path=None,
                           daily_folder=True, probe_name=None, sample_name=None):

        return_path = self._get_root_dir(use_qudi_savescheme, root_path)

        if not use_qudi_savescheme:

            # if probe name is provided, make the folder for it
            if probe_name is not None or probe_name != '':
                probe_name = self.check_for_illegal_char(probe_name)
                return_path = os.path.join(return_path, probe_name)

            # if sample name is provided, make the folder for it
            if sample_name is not None or sample_name != '':
                sample_name = self.check_for_illegal_char(sample_name)
                return_path = os.path.join(return_path, sample_name)

            # if daily folder is required, create it:
            if daily_folder:
                daily_folder_name = time.strftime("%Y%m%d")
                return_path = os.path.join(return_path, daily_folder_name)

            if not os.path.exists(return_path):
                os.makedirs(return_path, exist_ok=True)

        return os.path.abspath(return_path)

    def get_probe_path(self, use_qudi_savescheme=False, root_path=None, probe_name=None):

        return_path = self._get_root_dir(root_path, use_qudi_savescheme)

        # if probe name is provided, make the folder for it
        if probe_name is not None or probe_name != '':
            probe_name = self.check_for_illegal_char(probe_name)
            return_path = os.path.join(return_path, probe_name)

        if not os.path.exists(return_path):
            os.makedirs(return_path, exist_ok=True)

        return os.path.abspath(return_path)


    def get_confocal_path(self, use_qudi_savescheme=False, root_path=None,
                          daily_folder=True, probe_name=None):

        return_path = self.get_probe_path(use_qudi_savescheme, root_path,
                                          probe_name)

        return_path = os.path.join(return_path, 'Confocal')

        # if daily folder is required, create it:
        if daily_folder:
            daily_folder_name = time.strftime("%Y%m%d")
            return_path = os.path.join(return_path, daily_folder_name)

        if not os.path.exists(return_path):
            os.makedirs(return_path, exist_ok=True)

        return return_path


    def _get_root_dir(self, use_qudi_savescheme=False, root_path=None):
        """ Check the passed root path and return the correct path.

        By providing a root path you force the method to take it, if the path
        is valid.

        If qudi scheme is selected, then the rootpath is ignored.
        """

        if use_qudi_savescheme:
            return_path = self._save_logic.get_path_for_module(module_name='ProteusQ')
        else:

            if root_path is None or root_path == '' or not os.path.exists(root_path):

                return_path = self._meas_path

                self.log.debug(f'The provided rootpath "{root_path}" for '
                                 f'save operation does not exist! Take '
                                 f'default one: "{return_path}"')
            else:
                if os.path.exists(root_path):
                    return_path = self._meas_path
                    self.log.debug(f'The provided rootpath "{root_path}" for '
                                   f'save operation does not exist! Take '
                                   f'default one: "{return_path}"')
                else:
                    return_path = root_path


        return return_path

    def check_for_illegal_char(self, input_str):
        replace_char = '_'
        illegal = ['\\', '/', ':', '?', '*', '<', '>', '|']

        for entry in illegal:
            if entry in input_str:
                self.log.warning(f'The name {input_str} has an invalid input '
                                 f'character:  {entry} . It is replaced by _ ')
                input_str = input_str.replace(entry, replace_char)

        return input_str

    def save_qafm_data(self, tag=None, probe_name=None, sample_name=None,
                       use_qudi_savescheme=False, root_path=None, 
                       daily_folder=True, timestamp=None):

        scan_params = self.get_curr_scan_params()
        
        if scan_params == []:
            self.log.warning('Nothing measured to be saved for the QAFM measurement. Save routine skipped.')
            self.sigQAFMDataSaved.emit()
            return

        #scan_params = ['counts_fw','counts_bw','Height(Sen)_fw','Height(Sen)_bw','Mag_fw','Mag_bw','Phase_fw','Phase_bw',
        #                'Freq_fw','Freq_bw'] #Tests for data obtained from .dat file

        save_path =  self.get_qafm_save_directory(use_qudi_savescheme=use_qudi_savescheme,
                                             root_path=root_path,
                                             daily_folder=daily_folder,
                                             probe_name=probe_name,
                                             sample_name=sample_name)

        data = self.get_qafm_data()

        if timestamp is None:
            timestamp = datetime.datetime.now()

        for entry in scan_params:
            parameters = {}
            parameters.update(data[entry]['params'])
            nice_name = data[entry]['nice_name']
            unit = data[entry]['si_units']

            parameters['Name of measured signal'] = nice_name
            parameters['Units of measured signal'] = unit

            figure_data = data[entry]['data']

            # check whether figure has only zeros as data, skip this then
            if not np.any(figure_data):
                self.log.debug(f'The data array "{entry}" contains only zeros and will be not saved.')
                continue

            image_extent = [data[entry]['coord0_arr'][0],
                            data[entry]['coord0_arr'][-1],
                            data[entry]['coord1_arr'][0],
                            data[entry]['coord1_arr'][-1]]

            axes = ['X', 'Y']

            cbar_range = data[entry]['display_range']

            parameters['display_range'] = cbar_range

            #self.log.info(f'Save: {entry}')
            fig = self.draw_figure(figure_data, image_extent, axes, cbar_range,
                                        signal_name=nice_name, signal_unit=unit)

            image_data = {}
            image_data[f'QAFM XY scan image of a {nice_name} measurement without axis.\n'
                       'The upper left entry represents the signal at the upper left pixel position.\n'
                       'A pixel-line in the image corresponds to a row '
                       f'of entries where the Signal is in {unit}:'] = figure_data

            filelabel = f'QAFM_{entry}'

            if tag is not None:
                filelabel = f'{tag}_{filelabel}'

            fig = self._save_logic.save_data(image_data,
                                       filepath=save_path,
                                       timestamp=timestamp,
                                       parameters=parameters,
                                       filelabel=filelabel,
                                       fmt='%.6e',
                                       delimiter='\t',
                                       plotfig=fig)

            self.increase_save_counter()
            # prepare the full raw data in an OrderedDict:

            signal_name = data[entry]['nice_name']
            units_signal = data[entry]['si_units']

            raw_data = {}
            raw_data['X position (m)'] = np.tile(data[entry]['coord0_arr'], len(data[entry]['coord0_arr']))
            raw_data['Y position (m)'] = np.repeat(data[entry]['coord1_arr'], len(data[entry]['coord1_arr']))
            raw_data[f'{signal_name} ({units_signal})'] = data[entry]['data'].flatten()

            filelabel = filelabel + '_raw'

            self._save_logic.save_data(raw_data,
                                       filepath=save_path,
                                       timestamp=timestamp,
                                       parameters=parameters,
                                       filelabel=filelabel,
                                       fmt='%.6e',
                                       delimiter='\t')
            self.increase_save_counter()

    def draw_figure(self, image_data, image_extent, scan_axis=None, cbar_range=None,
                    percentile_range=None, signal_name='', signal_unit=''):


        if scan_axis is None:
            scan_axis = ['X', 'Y']

        # If no colorbar range was given, take full range of data
        if cbar_range is None:
            cbar_range = [np.min(image_data), np.max(image_data)]

            # discard zeros if they are exactly the lowest value
            if np.isclose(cbar_range[0], 0.0):
                cbar_range[0] = image_data[np.nonzero(image_data)].min()

        # Scale color values using SI prefix
        prefix = ['p', 'n', r'$\mathrm{\mu}$', 'm', '', 'k', 'M', 'G']
        scale_fac = 1000**4 # since it starts from p
        prefix_count = 0

        draw_cb_range = np.array(cbar_range)*scale_fac
        image_dimension = image_extent.copy()

        if abs(draw_cb_range[0]) > abs(draw_cb_range[1]):
            while abs(draw_cb_range[0]) > 1000:
                scale_fac = scale_fac / 1000
                draw_cb_range = draw_cb_range / 1000
                prefix_count = prefix_count + 1
        else:
            while abs(draw_cb_range[1]) > 1000:
                scale_fac = scale_fac/1000
                draw_cb_range = draw_cb_range/1000
                prefix_count = prefix_count + 1

        scaled_data = image_data*scale_fac
        c_prefix = prefix[prefix_count]

        # Scale axes values using SI prefix
        axes_prefix = ['', 'm', 'u', 'n']  # mu = r'$\mathrm{\mu}$'
        x_prefix_count = 0
        y_prefix_count = 0

        while np.abs(image_dimension[1] - image_dimension[0]) < 1:
            image_dimension[0] = image_dimension[0] * 1000.
            image_dimension[1] = image_dimension[1] * 1000.
            x_prefix_count = x_prefix_count + 1

        while np.abs(image_dimension[3] - image_dimension[2]) < 1:
            image_dimension[2] = image_dimension[2] * 1000.
            image_dimension[3] = image_dimension[3] * 1000.
            y_prefix_count = y_prefix_count + 1

        x_prefix = axes_prefix[x_prefix_count]
        y_prefix = axes_prefix[y_prefix_count]

        self.log.debug(('image_dimension: ', image_dimension))

        # Use qudi style
        plt.style.use(self._save_logic.mpl_qd_style)

        # Create figure
        fig, ax = plt.subplots()

        # Create image plot
        cfimage = ax.imshow(scaled_data,
                            cmap=plt.get_cmap('inferno'), # reference the right place in qd
                            origin="lower",
                            vmin=draw_cb_range[0],
                            vmax=draw_cb_range[1],
                            interpolation='none',
                            extent=image_dimension
                            )

        ax.set_aspect(1)
        ax.set_xlabel(scan_axis[0] + ' position (' + x_prefix + 'm)')
        ax.set_ylabel(scan_axis[1] + ' position (' + y_prefix + 'm)')
        ax.spines['bottom'].set_position(('outward', 10))
        ax.spines['left'].set_position(('outward', 10))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.get_xaxis().tick_bottom()
        ax.get_yaxis().tick_left()

        # Draw the colorbar
        cbar = plt.colorbar(cfimage, shrink=0.8)#, fraction=0.046, pad=0.08, shrink=0.75)
        cbar.set_label(f'{signal_name} ({c_prefix}{signal_unit})')

        # remove ticks from colorbar for cleaner image
        cbar.ax.tick_params(which=u'both', length=0)

        return fig


    def save_quantitative_data(self):
        pass



    def increase_save_counter(self, ret_val=0):
        """ Update the save counter.

        @param int ret_val: save status from the save logic, if -1, then error
                            occured during save, if 0 then everything is fine,
                            not used at the moment
        """
        self.__data_to_be_saved += 1

    def decrease_save_counter(self, ret_val=0):
        """ Update the save counter.

        @param int ret_val: save status from the save logic, if -1, then error
                            occurred during save, if 0 then everything is fine.
                            
        """

        if ret_val == 0:

            with self.threadlock:
                self.__data_to_be_saved -= 1

            if self.__data_to_be_saved == 0:
                self.sigQAFMDataSaved.emit()
                self.sigObjDataSaved.emit()
                self.sigOptiDataSaved.emit()

    def get_save_counter(self):
        return self.__data_to_be_saved

    def save_all_qafm_figures(self, tag=None, probe_name=None, sample_name=None,
                       use_qudi_savescheme=False, root_path=None, 
                       daily_folder=True):

        scan_params = self.get_curr_scan_params()
        
        #scan_params = ['counts_fw','counts_bw','Height(Sen)_fw','Height(Sen)_bw'] #Tests for data obtained from .dat file

        if scan_params == []:
            self.log.warning('Nothing measured to be saved for the QAFM measurement. Save routine skipped.')
            self.sigQAFMDataSaved.emit()
            return

        save_path =  self.get_qafm_save_directory(use_qudi_savescheme=use_qudi_savescheme,
                                             root_path=root_path,
                                             daily_folder=daily_folder,
                                             probe_name=probe_name,
                                             sample_name=sample_name)

        data = self.get_qafm_data()

        timestamp = datetime.datetime.now()

        fig = self.draw_all_qafm_figures(data)

        for entry in scan_params:
            parameters = {}
            parameters.update(data[entry]['params'])
            nice_name = data[entry]['nice_name']
            unit = data[entry]['si_units']

            parameters['Name of measured signal'] = nice_name
            parameters['Units of measured signal'] = unit

            figure_data = data[entry]['data']
            image_extent = [data[entry]['coord0_arr'][0],
                            data[entry]['coord0_arr'][-1],
                            data[entry]['coord1_arr'][0],
                            data[entry]['coord1_arr'][-1]]

            axes = ['X', 'Y']

            cbar_range = data[entry]['display_range']

            parameters['display_range'] = cbar_range

            image_data = {}
            image_data[f'QAFM XY scan image of a {nice_name} measurement without axis.\n'
                       'The upper left entry represents the signal at the upper left pixel position.\n'
                       'A pixel-line in the image corresponds to a row '
                       f'of entries where the Signal is in {unit}:'] = figure_data

            filelabel = f'QAFM_{entry}'

            if tag is not None:
                filelabel = f'{tag}_{filelabel}'

            fig = self._save_logic.save_data(image_data,
                                       filepath=save_path,
                                       timestamp=timestamp,
                                       parameters=parameters,
                                       filelabel=filelabel,
                                       fmt='%.6e',
                                       delimiter='\t',
                                       plotfig=fig)

            # prepare the full raw data in an OrderedDict:

            signal_name = data[entry]['nice_name']
            units_signal = data[entry]['si_units']

            raw_data = {}
            raw_data['X position (m)'] = np.tile(data[entry]['coord0_arr'], len(data[entry]['coord0_arr']))
            raw_data['Y position (m)'] = np.repeat(data[entry]['coord1_arr'], len(data[entry]['coord1_arr']))
            raw_data[f'{signal_name} ({units_signal})'] = data[entry]['data'].flatten()

            filelabel = filelabel + '_raw'

            self._save_logic.save_data(raw_data,
                                       filepath=save_path,
                                       timestamp=timestamp,
                                       parameters=parameters,
                                       filelabel=filelabel,
                                       fmt='%.6e',
                                       delimiter='\t')
            self.increase_save_counter()


    def draw_all_qafm_figures(self, qafm_data, scan_axis=None, cbar_range=None,
                    percentile_range=None, signal_name='', signal_unit=''):
        
        data = qafm_data #typically just get_qafm_data()

        #Starting the count to see how many images will be plotted and in which arrangement.
        nrows = 0
        ncols = 0
        counter = 0

        for entry in data:
            if np.mean(data[entry]['data']) != 0:
                counter = counter + 1

        if counter == 1:
            print('Try using draw_fig')
            pass

        #Simple arrangement, <3 images is 1 row, <7 images is 2, <13 images is 3 rows else 4 rows
        #Can be changed for any arrangement here.  
        if counter <= 2:
            nrows = 1
            ncols = counter
        else:
            if counter > 2 and counter <= 6:
                nrows = 2
                ncols = math.ceil(counter/nrows)
            else:
                if counter <= 12:
                    nrows = 3
                    ncols = math.ceil(counter/nrows)
                else:
                    nrows = 4
                    ncols = math.ceil(counter/nrows)

        fig, axs = plt.subplots(nrows = nrows, ncols = ncols, dpi=300, squeeze = True)

        plt.style.use(self._save_logic.mpl_qd_style)

        #Variable used to eliminate the empty subplots created in the figure. 
        axis_position_comparison = []
        for i in range(nrows):
            for j in range(ncols):
                axis_position_comparison.append([i,j])

        counter_rows = 0
        counter_cols = 0
        axis_position = []
        axis_position_container = []

        for entry in data:
            if '_fw' in entry or '_bw' in entry:
                data_entry = data[entry]
                image_data = data_entry['data']
                
                if np.mean(image_data) != 0:
                    
                    image_extent = [data_entry['coord0_arr'][0],
                                    data_entry['coord0_arr'][-1],
                                    data_entry['coord1_arr'][0],
                                    data_entry['coord1_arr'][-1]]
                    scan_axis = ['X','Y']
                    cbar_range = data_entry['display_range']
                    signal_name = data_entry['nice_name']
                    signal_unit = data_entry['si_units']
                    
                    # Scale color values using SI prefix
                    prefix = ['p', 'n', r'$\mathrm{\mu}$', 'm', '', 'k', 'M', 'G']
                    scale_fac = 1000**4 # since it starts from p
                    prefix_count = 0

                    draw_cb_range = np.array(cbar_range)*scale_fac
                    image_dimension = image_extent.copy()

                    if abs(draw_cb_range[0]) > abs(draw_cb_range[1]):
                        while abs(draw_cb_range[0]) > 1000:
                            scale_fac = scale_fac / 1000
                            draw_cb_range = draw_cb_range / 1000
                            prefix_count = prefix_count + 1
                    else:
                        while abs(draw_cb_range[1]) > 1000:
                            scale_fac = scale_fac/1000
                            draw_cb_range = draw_cb_range/1000
                            prefix_count = prefix_count + 1

                    scaled_data = image_data*scale_fac
                    c_prefix = prefix[prefix_count]

                    # Scale axes values using SI prefix
                    axes_prefix = ['', 'm',r'$\mathrm{\mu}$', 'n']  # mu = r'$\mathrm{\mu}$'
                    x_prefix_count = 0
                    y_prefix_count = 0

                    while np.abs(image_dimension[1] - image_dimension[0]) < 1:
                        image_dimension[0] = image_dimension[0] * 1000.
                        image_dimension[1] = image_dimension[1] * 1000.
                        x_prefix_count = x_prefix_count + 1

                    while np.abs(image_dimension[3] - image_dimension[2]) < 1:
                        image_dimension[2] = image_dimension[2] * 1000.
                        image_dimension[3] = image_dimension[3] * 1000.
                        y_prefix_count = y_prefix_count + 1

                    x_prefix = axes_prefix[x_prefix_count]
                    y_prefix = axes_prefix[y_prefix_count]
                    
                    #If there are only 2 images to plot, there is only 1 row, which makes the imaging 
                    #have only 1 axes making the creation of the image different than if there were more. 
                    if counter == 2:
                        
                        cfimage = axs[counter_cols].imshow(scaled_data,cmap=plt.get_cmap('inferno'),
                                                            origin='lower', vmin= draw_cb_range[0],
                                                            vmax=draw_cb_range[1],interpolation='none',
                                                            extent=image_dimension)
                        
                        axs[counter_cols].set_aspect(1)
                        axs[counter_cols].set_xlabel(scan_axis[0] + ' position (' + x_prefix + 'm)')
                        axs[counter_cols].set_ylabel(scan_axis[1] + ' position (' + y_prefix + 'm)')
                        axs[counter_cols].spines['bottom'].set_position(('outward', 10))
                        axs[counter_cols].spines['left'].set_position(('outward', 10))
                        axs[counter_cols].spines['top'].set_visible(False)
                        axs[counter_cols].spines['right'].set_visible(False)
                        axs[counter_cols].get_xaxis().tick_bottom()
                        axs[counter_cols].get_yaxis().tick_left()

                        cbar = plt.colorbar(cfimage, ax=axs[counter_cols], shrink=0.8)
                        cbar.set_label(f'{signal_name} ({c_prefix}{signal_unit})')
                    
                    else:
            
                        cfimage = axs[counter_rows][counter_cols].imshow(scaled_data,cmap=plt.get_cmap('inferno'),
                                                                        origin='lower', vmin= draw_cb_range[0],
                                                                        vmax=draw_cb_range[1],interpolation='none',
                                                                        extent=image_dimension)
                        
                        #Required since the qudi default font is too big for all of the subplots.
                        plt.rcParams.update({'font.size': 8})
                        axs[counter_rows][counter_cols].set_aspect(1)
                        axs[counter_rows][counter_cols].set_xlabel(scan_axis[0] + ' position (' + x_prefix + 'm)')
                        axs[counter_rows][counter_cols].set_ylabel(scan_axis[1] + ' position (' + y_prefix + 'm)')
                        axs[counter_rows][counter_cols].spines['bottom'].set_position(('outward', 10))
                        axs[counter_rows][counter_cols].spines['left'].set_position(('outward', 10))
                        axs[counter_rows][counter_cols].spines['top'].set_visible(False)
                        axs[counter_rows][counter_cols].spines['right'].set_visible(False)
                        axs[counter_rows][counter_cols].get_xaxis().tick_bottom()
                        axs[counter_rows][counter_cols].get_yaxis().tick_left()

                        cbar = plt.colorbar(cfimage, ax=axs[counter_rows][counter_cols], shrink=0.8)
                        cbar.set_label(f'{signal_name} ({c_prefix}{signal_unit})')
                    
                    axis_position = [counter_rows,counter_cols]
                    axis_position_container.append(axis_position)
                    
                    counter_cols = counter_cols + 1
                    
                    #Used to make sure the counters for columns and rows work correctly.
                    if counter_cols == ncols:
                        counter_rows = counter_rows + 1
                        counter_cols = 0
        
        #Removing the empty axis figures created at the end of all plotting.
        if counter > 2:
            for position in axis_position_comparison:
                if position not in axis_position_container:
                    axs[position[0]][position[1]].remove()

        plt.tight_layout()

        return fig

    def save_obj_data(self, obj_name_list, tag=None, probe_name=None, sample_name=None,
                      use_qudi_savescheme=False, root_path=None, 
                      daily_folder=None):

        if len(obj_name_list) == 0:
            self.sigObjDataSaved.emit()
            self.log.warning(f'Save aborted, no data to save selected!')

        # get the objective data
        data = self.get_obj_data()

        for entry in obj_name_list:
            if len(data[entry]['params']) == 0:
                self.sigObjDataSaved.emit()
                self.log.warning(f'Save aborted, no proper data in the image {entry}.')
                return

        save_path = self.get_confocal_path(use_qudi_savescheme=use_qudi_savescheme,
                                           root_path=root_path,
                                           daily_folder=daily_folder,
                                           probe_name=probe_name)

        timestamp = datetime.datetime.now()

        for entry in obj_name_list:
            parameters = {}
            parameters.update(data[entry]['params'])
            nice_name = data[entry]['nice_name']
            unit = data[entry]['si_units']

            parameters['Name of measured signal'] = nice_name
            parameters['Units of measured signal'] = unit

            figure_data = data[entry]['data']
            image_extent = [data[entry]['coord0_arr'][0],
                            data[entry]['coord0_arr'][-1],
                            data[entry]['coord1_arr'][0],
                            data[entry]['coord1_arr'][-1]]

            axes = [data[entry]['params']['axis name for coord0'], data[entry]['params']['axis name for coord1']]

            cbar_range = data[entry]['display_range']

            parameters['display_range'] = cbar_range

            fig = self.draw_figure(figure_data, image_extent, axes, cbar_range,
                                        signal_name=nice_name, signal_unit=unit)

            image_data = {}
            image_data[f'Objective scan image with a {nice_name} measurement without axis.\n'
                       'The upper left entry represents the signal at the upper left pixel position.\n'
                       'A pixel-line in the image corresponds to a row '
                       f'of entries where the Signal is in {unit}:'] = figure_data

            filelabel = entry

            if tag is not None:
                filelabel = f'{tag}_{filelabel}'

            fig = self._save_logic.save_data(image_data,
                                       filepath=save_path,
                                       timestamp=timestamp,
                                       parameters=parameters,
                                       filelabel=filelabel,
                                       fmt='%.6e',
                                       delimiter='\t',
                                       plotfig=fig)
            self.increase_save_counter()
            # prepare the full raw data in an OrderedDict:

            signal_name = data[entry]['nice_name']
            units_signal = data[entry]['si_units']

            raw_data = {}
            raw_data[f'{axes[0]} position (m)'] = np.tile(data[entry]['coord0_arr'], len(data[entry]['coord0_arr']))
            raw_data[f'{axes[1]} position (m)'] = np.repeat(data[entry]['coord1_arr'], len(data[entry]['coord1_arr']))
            raw_data[f'{signal_name} ({units_signal})'] = data[entry]['data'].flatten()

            filelabel = filelabel + '_raw'

            self._save_logic.save_data(raw_data,
                                       filepath=save_path,
                                       timestamp=timestamp,
                                       parameters=parameters,
                                       filelabel=filelabel,
                                       fmt='%.6e',
                                       delimiter='\t')
            self.increase_save_counter()

    def draw_obj_figure(self):
        pass

    def save_optimizer_data(self, tag=None, probe_name=None, sample_name=None, 
                            use_qudi_savescheme=False, root_path=None, 
                            daily_folder=None):

        # get the optimizer data
        data = self.get_opti_data()
        data_xy = data['opti_xy']
        data_z = data['opti_z']

        for entry in data:
            if len(data[entry]['params']) == 0:
                self.sigObjDataSaved.emit()
                self.log.warning(f'Save aborted, no proper data in the image {entry}.')
                return

        save_path = self.get_confocal_path(use_qudi_savescheme=use_qudi_savescheme,
                                           root_path=root_path,
                                           daily_folder=daily_folder,
                                           probe_name=probe_name)

        timestamp = datetime.datetime.now()

        parameters = {}
        parameters.update(data_xy['params'])
        nice_name = data_xy['nice_name']
        unit = data_xy['si_units']

        parameters['Name of measured signal'] = nice_name
        parameters['Units of measured signal'] = unit

        image_extent = [data_xy['coord0_arr'][0],
                        data_xy['coord0_arr'][-1],
                        data_xy['coord1_arr'][0],
                        data_xy['coord1_arr'][-1]]

        axes = [data_xy['params']['axis name for coord0'], data_xy['params']['axis name for coord1']]

        cbar_range = data_xy['display_range']

        parameters['display_range'] = cbar_range

        fig = self.draw_optimizer_figure(data_xy, data_z, image_extent, axes, cbar_range,
                                    signal_name=nice_name, signal_unit=unit)

        image_data = {}
        image_data[f'Objective scan image with a {nice_name} measurement without axis.\n'
                   'The upper left entry represents the signal at the upper left pixel position.\n'
                   'A pixel-line in the image corresponds to a row '
                   f'of entries where the Signal is in {unit}:'] = data_xy['data']

        filelabel = list(data)[0]

        if tag is not None:
            filelabel = f'{tag}_{filelabel}'

        fig = self._save_logic.save_data(image_data,
                                   filepath=save_path,
                                   timestamp=timestamp,
                                   parameters=parameters,
                                   filelabel=filelabel,
                                   fmt='%.6e',
                                   delimiter='\t',
                                   plotfig=fig)
        self.increase_save_counter()

        # prepare the full raw data in an OrderedDict:

        signal_name = data_xy['nice_name']
        units_signal = data_xy['si_units']

        raw_data = {}
        raw_data[f'{axes[0]} position (m)'] = np.tile(data_xy['coord0_arr'], len(data_xy['coord0_arr']))
        raw_data[f'{axes[1]} position (m)'] = np.repeat(data_xy['coord1_arr'], len(data_xy['coord1_arr']))
        raw_data[f'{signal_name} ({units_signal})'] = data_xy['data'].flatten()

        filelabel = filelabel + '_raw'

        self._save_logic.save_data(raw_data,
                                   filepath=save_path,
                                   timestamp=timestamp,
                                   parameters=parameters,
                                   filelabel=filelabel,
                                   fmt='%.6e',
                                   delimiter='\t')
        self.increase_save_counter()
        image_data = {}
        image_data[f'Objective scan image with a {nice_name} measurement in 1 axis.\n'
                   f'Where the Signal is in {unit}:'] = data_z['data']

        axes = [data_z['params']['axis name for coord0']]

        filelabel = list(data)[1]

        if tag is not None:
            filelabel = f'{tag}_{filelabel}'

        fig = self._save_logic.save_data(image_data,
                                   filepath=save_path,
                                   timestamp=timestamp,
                                   parameters=parameters,
                                   filelabel=filelabel,
                                   fmt='%.6e',
                                   delimiter='\t')
        self.increase_save_counter()
        # prepare the full raw data in an OrderedDict:

        signal_name = data_z['nice_name']
        units_signal = data_z['si_units']

        raw_data = {}
        raw_data[f'{axes[0]} position (m)'] = np.tile(data_z['coord0_arr'],1)      
        raw_data[f'{signal_name} ({units_signal})'] = data_z['data'].flatten()

        filelabel = filelabel + '_raw'

        self._save_logic.save_data(raw_data,
                                   filepath=save_path,
                                   timestamp=timestamp,
                                   parameters=parameters,
                                   filelabel=filelabel,
                                   fmt='%.6e',
                                   delimiter='\t')
        self.increase_save_counter()

    def draw_optimizer_figure(self, image_data_xy, image_data_z, image_extent, scan_axis=None, 
                              cbar_range=None, percentile_range=None, signal_name='', signal_unit=''):

        if scan_axis is None:
            scan_axis = ['X', 'Y']

        figure_data_xy = image_data_xy
        figure_data_z = image_data_z

        image_data_xy = image_data_xy['data']
        image_data_z = image_data_z['data']

        # If no colorbar range was given, take full range of data
        if cbar_range is None:
            cbar_range = [np.min(image_data_xy), np.max(image_data_xy)]

            # discard zeros if they are exactly the lowest value
            if np.isclose(cbar_range[0], 0.0):
                cbar_range[0] = image_data_xy[np.nonzero(image_data_xy)].min()

        # Scale color values using SI prefix
        prefix = ['p', 'n', r'$\mathrm{\mu}$', 'm', '', 'k', 'M', 'G']
        scale_fac = 1000**4 # since it starts from p
        prefix_count = 0

        draw_cb_range = np.array(cbar_range)*scale_fac
        image_dimension = image_extent.copy()

        if abs(draw_cb_range[0]) > abs(draw_cb_range[1]):
            while abs(draw_cb_range[0]) > 1000:
                scale_fac = scale_fac / 1000
                draw_cb_range = draw_cb_range / 1000
                prefix_count = prefix_count + 1
        else:
            while abs(draw_cb_range[1]) > 1000:
                scale_fac = scale_fac/1000
                draw_cb_range = draw_cb_range/1000
                prefix_count = prefix_count + 1

        scaled_data = image_data_xy*scale_fac
        c_prefix = prefix[prefix_count]

        # Scale axes values using SI prefix
        axes_prefix = ['', 'm', r'$\mathrm{\mu}$', 'n']  # mu = r'$\mathrm{\mu}$'
        x_prefix_count = 0
        y_prefix_count = 0

        #Rounding image dimension up to nm scale, to make sure value does not end at 0.9999
        while np.abs(round(image_dimension[1],9) - round(image_dimension[0],9)) < 1:
            image_dimension[0] = image_dimension[0] * 1000.
            image_dimension[1] = image_dimension[1] * 1000.
            x_prefix_count = x_prefix_count + 1

        while np.abs(round(image_dimension[3],9) - round(image_dimension[2],9)) < 1:
            image_dimension[2] = image_dimension[2] * 1000.
            image_dimension[3] = image_dimension[3] * 1000.
            y_prefix_count = y_prefix_count + 1

        x_prefix = axes_prefix[x_prefix_count]
        y_prefix = axes_prefix[y_prefix_count]

        #afm_scanner_logic.log.debug(('image_dimension: ', image_dimension))

        # Use qudi style
        plt.style.use(self._save_logic.mpl_qd_style)

        # Create figure
        fig, axs = plt.subplots(ncols=2, squeeze=True)
        fig.subplots_adjust(wspace=0.1, left=0.02, right=0.98)
        ax = axs[0]
        axz = axs[1]

        # Create image plot for xy
        cfimage = ax.imshow(scaled_data,
                            cmap=plt.get_cmap('inferno'), # reference the right place in qd
                            origin="lower",
                            vmin=draw_cb_range[0],
                            vmax=draw_cb_range[1],
                            interpolation='none',
                            extent=image_dimension,
                            )

        #Define aspects and ticks of xy image
        ax.set_aspect(1)
        ax.set_xlabel(scan_axis[0] + ' position (' + x_prefix + 'm)')
        ax.set_ylabel(scan_axis[1] + ' position (' + y_prefix + 'm)')
        ax.spines['bottom'].set_position(('outward', 10))
        ax.spines['left'].set_position(('outward', 10))
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.get_xaxis().tick_bottom()
        ax.get_yaxis().tick_left()

        # Draw the colorbar
        cbar = plt.colorbar(cfimage, shrink=0.8, ax=ax)#, fraction=0.046, pad=0.08, shrink=0.75)
        cbar.set_label(f'{signal_name} ({c_prefix}{signal_unit})')

        # remove ticks from colorbar for cleaner image
        cbar.ax.tick_params(which=u'both', length=0)

        #Create z plot using appropriate scale factors and units
        scale_factor_x = units.ScaledFloat(figure_data_z['coord0_arr'][0])
        scale_factor_x = scale_factor_x.scale_val

        scaled_data_x = figure_data_z['coord0_arr']/scale_factor_x

        scale_factor_y = units.ScaledFloat(figure_data_z['data'][0])
        scale_factor_y = scale_factor_y.scale_val

        scaled_data_y = figure_data_z['data']/scale_factor_y

        #Defining the same color map of the xy image for the points in the z plot
        cmap = plt.get_cmap('inferno')

        #Creating the initial z plot so that the multicolor dots are connected
        cfimage2 = axz.plot(scaled_data_x,scaled_data_y,'k', markersize=2, alpha=0.2)

        #Plotting each data point with a different color using the cmap
        for i in range(len(scaled_data_y)):
            if scaled_data_y[i] > scaled_data.max():
                point_color = cmap(int(np.rint(255)))
                axz.plot(scaled_data_x[i],scaled_data_y[i],'o',mfc= point_color, mec= point_color)
            else:
                point_color = cmap(int(np.rint(scaled_data_y[i]/scaled_data.max()*255)))
                axz.plot(scaled_data_x[i],scaled_data_y[i],'o',mfc= point_color, mec= point_color)

        axz.set_xlabel(figure_data_z['params']['axis name for coord0'] + ' position (' + r'$\mathrm{\mu}$' + 'm)')

        return fig


