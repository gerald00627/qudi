# -*- coding: utf-8 -*-

"""
This file contains the Qudi Logic module base class.

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

from qtpy import QtCore
from collections import OrderedDict
from interface.microwave_interface import MicrowaveMode
from interface.microwave_interface import TriggerEdge
from interface.microwave_interface import MicrowaveTriggerMode

import numpy as np
import time
import datetime
import matplotlib.pyplot as plt

from logic.generic_logic import GenericLogic
from core.util.mutex import Mutex
from core.connector import Connector
from core.configoption import ConfigOption
from core.statusvariable import StatusVar



class WidefieldMeasurementLogic(GenericLogic):
    """This is the Logic class for Widefield Measurements."""

    # declare connectors
    widefieldcamera = Connector(interface='WidefieldCameraInterface')
    fitlogic = Connector(interface='FitLogic')
    microwave1 = Connector(interface='MicrowaveInterface')
    microwave2 = Connector(interface='MicrowaveInterface')
    savelogic = Connector(interface='SaveLogic')
    taskrunner = Connector(interface='TaskRunner')
    sequencegeneratorlogic = Connector(interface='SequenceGeneratorLogic')
    pulsedmeasurementlogic = Connector(interface='PulsedMeasurementLogic')

    pulser = Connector(interface='PulserInterface')

    # config option
    mw_scanmode = ConfigOption(
        'scanmode',
        'LIST',
        missing='warn',
        converter=lambda x: MicrowaveMode[x.upper()])

    frame_rate = StatusVar('frame_rate', 100)

    gain = StatusVar('gain', 0)
    trigger_mode = StatusVar('trigger_mode', False)
    exposure_mode = StatusVar('exposure_mode', 'Timed')
    exposure_modes = StatusVar('exposure_modes', ['Timed', 'TriggerWidth'])
    exposure_time = StatusVar('exposure_time', 1e-3)
    image_width = StatusVar('image_width', 1936)
    image_height = StatusVar('image_height', 1216)
    offset_x = StatusVar('offset_x', 0)
    offset_y = StatusVar('offset_y', 0)
    pixel_format = StatusVar('pixel_format', 'Mono12')
    pixel_formats = StatusVar('pixel_formats', ['Mono8','Mono12','Mono12p'])
    plot_pixel_x = StatusVar('plot_pixel_x', 10)
    plot_pixel_y = StatusVar('plot_pixel_y', 10)

    input_line = StatusVar('input_line', 4)
    input_line_inverse = StatusVar('input_line_inverse', False)
    input_line_activation = StatusVar('input_line_activation', 'RisingEdge')
    input_line_trigger_selector =  StatusVar('input_line_trigger_selector', 'FrameStart')
    input_line_trigger_delay = StatusVar('input_line_trigger_delay', 0)
    output_line = StatusVar('output_line', 3)
    output_line_inverse = StatusVar('output_line_inverse', False)
    output_line_source = StatusVar('output_line_source', 'ExposureActive')
    output_line_minpulse = StatusVar('output_line_minpulse', 0)

    measurement_type = StatusVar('measurement_type', 'rabi')

    cw_mw_frequency = StatusVar('cw_mw_frequency', 2870e6)
    cw_mw_power = StatusVar('cw_mw_power', -30)
    sweep_mw_power = StatusVar('sweep_mw_power', -30)
    fit_range = StatusVar('fit_range', 0)
    mw_starts = StatusVar('mw_starts', [2800e6])
    mw_stops = StatusVar('mw_stops', [2950e6])
    mw_steps = StatusVar('mw_steps', [2e6])
    run_time = StatusVar('run_time', 60)
    ranges = StatusVar('ranges', 1)
    fc = StatusVar('fits', None)

    curr_loaded_seq = StatusVar('curr_loaded_seq','WF_ODMR')

    # Internal signals
    sigNextLine = QtCore.Signal()
    sigPlotPxChanged = QtCore.Signal(list)

    # Update signals, e.g. for GUI module
    sigParameterUpdated = QtCore.Signal(dict)
    sigMeasurementChanged = QtCore.Signal(dict)
    sigCameraLimits = QtCore.Signal(tuple)
    sigOutputStateUpdated = QtCore.Signal(str, bool)
    sigOdmrPlotsUpdated = QtCore.Signal(np.ndarray, np.ndarray,str,str)
    sigOdmrFitUpdated = QtCore.Signal(np.ndarray, np.ndarray, dict, str)
    sigOdmrElapsedTimeUpdated = QtCore.Signal(float, int)

    # SequenceGeneratorLogic control signals
    sigSavePulseBlock = QtCore.Signal(object)
    sigSaveBlockEnsemble = QtCore.Signal(object)
    sigSaveSequence = QtCore.Signal(object)
    sigDeletePulseBlock = QtCore.Signal(str)
    sigDeleteBlockEnsemble = QtCore.Signal(str)
    sigDeleteSequence = QtCore.Signal(str)
    sigLoadBlockEnsemble = QtCore.Signal(str)
    sigLoadSequence = QtCore.Signal(str)
    sigSampleBlockEnsemble = QtCore.Signal(str)
    sigSampleSequence = QtCore.Signal(str)
    sigClearPulseGenerator = QtCore.Signal()
    sigGeneratorSettingsChanged = QtCore.Signal(dict)
    sigSamplingSettingsChanged = QtCore.Signal(dict)
    sigGeneratePredefinedSequence = QtCore.Signal(str, dict)

    # Signals coming from SequenceGeneratorLogic for GUI
    sigBlockDictUpdated = QtCore.Signal(dict)
    sigEnsembleDictUpdated = QtCore.Signal(dict)
    sigSequenceDictUpdated = QtCore.Signal(dict)
    sigAvailableWaveformsUpdated = QtCore.Signal(list)
    sigAvailableSequencesUpdated = QtCore.Signal(list)
    sigSampleEnsembleComplete = QtCore.Signal(object)
    sigSampleSequenceComplete = QtCore.Signal(object)
    sigLoadedAssetUpdated = QtCore.Signal(str, str)
    sigGeneratorSettingsUpdated = QtCore.Signal(dict)
    sigSamplingSettingsUpdated = QtCore.Signal(dict)
    sigPredefinedSequenceGenerated = QtCore.Signal(object, bool)

    # PulsedMeasurementLogic control signal
    sigTogglePulser = QtCore.Signal(bool)


    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.threadlock = Mutex()

    def on_activate(self):
        """
        Initialisation performed during activation of the module.
        """

        # Initialize status register
        self.status_dict = {'sampling_ensemble_busy': False,
                            'sampling_sequence_busy': False,
                            'sampload_busy': False,
                            'loading_busy': False,
                            'pulser_running': False,
                            'measurement_running': False,
                            'microwave_running': False,
                            'predefined_generation_busy': False,
                            'fitting_busy': False}
        
        # Get connectors
        self._mw_device = self.microwave1()
        self._mw_device2 = self.microwave2()

        self._fit_logic = self.fitlogic()
        self._widefield_camera = self.widefieldcamera()
        self._save_logic = self.savelogic()
        self._taskrunner = self.taskrunner()
        self._sequencegeneratorlogic = self.sequencegeneratorlogic()
        self._pulsedmeasurementlogic = self.pulsedmeasurementlogic()

        self._pulser = self.pulser()

        # Get hardware constraints
        limits = self.get_hw_constraints()

        # Set/recall microwave source parameters
        self.cw_mw_frequency = limits.frequency_in_range(self.cw_mw_frequency)
        self.cw_mw_power = limits.power_in_range(self.cw_mw_power)
        self.sweep_mw_power = limits.power_in_range(self.sweep_mw_power)

        self.gain = self._widefield_camera.get_gain()
        self.trigger_mode = self._widefield_camera.get_trigger_mode()
        self.exposure_mode = self._widefield_camera.get_exposure_mode()
        self.exposure_modes = self._widefield_camera.limits["exposure_modes"]
        self.exposure_time = self._widefield_camera.get_exposure()
        self.image_width, self.image_height = self._widefield_camera.get_size()
        self.offset_x, self.offset_y = self._widefield_camera.get_offset()
        self.pixel_format = self._widefield_camera.get_pixel_format()
        self.pixel_formats = self._widefield_camera.limits["pixel_formats"]
        self.plot_pixel_x, self.plot_pixel_y = self._widefield_camera.get_plot_pixel()

        input_line_parameters, output_line_parameters = self._widefield_camera.get_channel_parameters()

        self.input_line = input_line_parameters['LineSelector']
        self.input_line_inverse = input_line_parameters['LineInverter']
        self.input_line_activation = input_line_parameters['TriggerActivations']
        self.input_line_trigger_selector =  input_line_parameters['TriggerSelectors']
        self.input_line_trigger_delay = input_line_parameters['TriggerDelays']
        self.output_line = output_line_parameters['LineSelector']
        self.output_line_inverse = output_line_parameters['LineInverter']
        self.output_line_source = output_line_parameters['LineSource']
        self.output_line_minpulse = output_line_parameters['MinimumOutputPulse']

        self.predefined_generate_methods = self.generate_methods
        self.measurement_params = self.generate_method_params[self.measurement_type]

        #Place holder for currently loaded sequence string
        self.curr_loaded_seq = 'WF_ODMR'
        
        # Set the trigger polarity (RISING/FALLING) of the mw-source input trigger
        # theoretically this can be changed, but the current counting scheme will not support that
        self.mw_trigger_pol = TriggerEdge.RISING
        self.set_trigger(self.mw_trigger_pol, self.frame_rate)

        # Elapsed measurement time and number of sweeps
        self.elapsed_time = 0.0
        self.elapsed_sweeps = 0

        self.range_to_fit = 0
        self.matrix_range = 0
        self.fits_performed = {}

        self.frequency_lists = []
        self.final_freq_list = []

        self.tau_array = []
        self.num_imgs = []

        # Set flags
        # for stopping a measurement
        self._stopRequested = False
        # for clearing the ODMR data during a measurement
        self._clearOdmrData = False

        # Initalize the ODMR data arrays (mean signal)
        self._initialize_odmr_plots()
        # Raw data array
        self.odmr_raw_data = np.zeros(
            [self.odmr_plot_x.size,
             self._widefield_camera._image_size[0],
             self._widefield_camera._image_size[1]]
        )

        # Switch off microwave and set CW frequency and power
        self.mw_off()
        self.set_cw_parameters(self.cw_mw_frequency, self.cw_mw_power)

        # Connect signals
        self.sigNextLine.connect(self._scan_widefield_odmr_line, QtCore.Qt.QueuedConnection)
        self.sigPlotPxChanged.connect(self.update_plot_px, QtCore.Qt.QueuedConnection)

        # Connect signals controlling SequenceGeneratorLogic
        # self.sigSavePulseBlock.connect(
        #     self._sequencegeneratorlogic.save_block, QtCore.Qt.QueuedConnection)
        # self.sigSaveBlockEnsemble.connect(
        #     self._sequencegeneratorlogic.save_ensemble, QtCore.Qt.QueuedConnection)
        # self.sigSaveSequence.connect(
        #     self._sequencegeneratorlogic.save_sequence, QtCore.Qt.QueuedConnection)
        # self.sigDeletePulseBlock.connect(
        #     self._sequencegeneratorlogic.delete_block, QtCore.Qt.QueuedConnection)
        # self.sigDeleteBlockEnsemble.connect(
        #     self._sequencegeneratorlogic.delete_ensemble, QtCore.Qt.QueuedConnection)
        # self.sigDeleteSequence.connect(
        #     self._sequencegeneratorlogic.delete_sequence, QtCore.Qt.QueuedConnection)
        self.sigLoadBlockEnsemble.connect(
            self._sequencegeneratorlogic.load_ensemble, QtCore.Qt.QueuedConnection)
        self.sigLoadSequence.connect(
            self._sequencegeneratorlogic.load_sequence, QtCore.Qt.QueuedConnection)
        self.sigSampleBlockEnsemble.connect(
            self._sequencegeneratorlogic.sample_pulse_block_ensemble, QtCore.Qt.QueuedConnection)
        self.sigSampleSequence.connect(
            self._sequencegeneratorlogic.sample_pulse_sequence, QtCore.Qt.QueuedConnection)
        self.sigClearPulseGenerator.connect(
            self._sequencegeneratorlogic.clear_pulser, QtCore.Qt.QueuedConnection)
        # self.sigGeneratorSettingsChanged.connect(
        #     self._sequencegeneratorlogic.set_pulse_generator_settings, QtCore.Qt.QueuedConnection)
        # self.sigSamplingSettingsChanged.connect(
        #     self._sequencegeneratorlogic.set_generation_parameters, QtCore.Qt.QueuedConnection)
        self.sigGeneratePredefinedSequence.connect(
            self._sequencegeneratorlogic.generate_predefined_sequence, QtCore.Qt.QueuedConnection)

        # Connect signals coming from SequenceGeneratorLogic
        # TODO: Implement these
        # self._sequencegeneratorlogic.sigBlockDictUpdated.connect(
        #     self.sigBlockDictUpdated, QtCore.Qt.QueuedConnection)
        # self._sequencegeneratorlogic.sigEnsembleDictUpdated.connect(
        #     self.sigEnsembleDictUpdated, QtCore.Qt.QueuedConnection)
        # self._sequencegeneratorlogic.sigSequenceDictUpdated.connect(
        #     self.sigSequenceDictUpdated, QtCore.Qt.QueuedConnection)
        # self._sequencegeneratorlogic.sigAvailableWaveformsUpdated.connect(
        #     self.sigAvailableWaveformsUpdated, QtCore.Qt.QueuedConnection)
        # self._sequencegeneratorlogic.sigAvailableSequencesUpdated.connect(
        #     self.sigAvailableSequencesUpdated, QtCore.Qt.QueuedConnection)
        # self._sequencegeneratorlogic.sigGeneratorSettingsUpdated.connect(
        #     self.sigGeneratorSettingsUpdated, QtCore.Qt.QueuedConnection)
        # self._sequencegeneratorlogic.sigSamplingSettingsUpdated.connect(
        #     self.sigSamplingSettingsUpdated, QtCore.Qt.QueuedConnection)
        self._sequencegeneratorlogic.sigPredefinedSequenceGenerated.connect(
            self.predefined_sequence_generated, QtCore.Qt.QueuedConnection)
        self._sequencegeneratorlogic.sigSampleEnsembleComplete.connect(
            self.sample_ensemble_finished, QtCore.Qt.QueuedConnection)
        self._sequencegeneratorlogic.sigSampleSequenceComplete.connect(
            self.sample_sequence_finished, QtCore.Qt.QueuedConnection)
        self._sequencegeneratorlogic.sigLoadedAssetUpdated.connect(
            self.loaded_asset_updated, QtCore.Qt.QueuedConnection)
        # self._sequencegeneratorlogic.sigBenchmarkComplete.connect(
        #     self.benchmark_completed, QtCore.Qt.QueuedConnection)

        # Connect signals controlling PulsedMeasurement Logic
        self.sigTogglePulser.connect(
            self.pulsedmeasurementlogic().toggle_pulse_generator, QtCore.Qt.QueuedConnection)

        return

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        # Stop measurement if it is still running
        if self.module_state() == 'locked':
            self.stop_widefield_odmr_scan()
        timeout = 30.0
        start_time = time.time()
        while self.module_state() == 'locked':
            time.sleep(0.5)
            timeout -= (time.time() - start_time)
            if timeout <= 0.0:
                self.log.error('Failed to properly deactivate odmr logic. Odmr scan is still '
                               'running but can not be stopped after 30 sec.')
                break
        # Switch off microwave source for sure (also if CW mode is active or module is still locked)
        self._mw_device.off()

        # Disconnect signals
        self.sigNextLine.disconnect()

        # Disconnect signals controlling SequenceGeneratorLogic
        # self.sigSavePulseBlock.disconnect()
        # self.sigSaveBlockEnsemble.disconnect()
        # self.sigSaveSequence.disconnect()
        # self.sigDeletePulseBlock.disconnect()
        # self.sigDeleteBlockEnsemble.disconnect()
        # self.sigDeleteSequence.disconnect()
        # self.sigLoadBlockEnsemble.disconnect()
        self.sigLoadSequence.disconnect()
        self.sigSampleBlockEnsemble.disconnect()
        self.sigSampleSequence.disconnect()
        self.sigClearPulseGenerator.disconnect()
        # self.sigGeneratorSettingsChanged.disconnect()
        # self.sigSamplingSettingsChanged.disconnect()
        self.sigGeneratePredefinedSequence.disconnect()

        # Disconnect signals coming from SequenceGeneratorLogic
        self._sequencegeneratorlogic.sigBlockDictUpdated.disconnect()
        self._sequencegeneratorlogic.sigEnsembleDictUpdated.disconnect()
        self._sequencegeneratorlogic.sigSequenceDictUpdated.disconnect()
        self._sequencegeneratorlogic.sigAvailableWaveformsUpdated.disconnect()
        self._sequencegeneratorlogic.sigAvailableSequencesUpdated.disconnect()
        self._sequencegeneratorlogic.sigGeneratorSettingsUpdated.disconnect()
        self._sequencegeneratorlogic.sigSamplingSettingsUpdated.disconnect()
        self._sequencegeneratorlogic.sigPredefinedSequenceGenerated.disconnect()
        self._sequencegeneratorlogic.sigSampleEnsembleComplete.disconnect()
        self._sequencegeneratorlogic.sigSampleSequenceComplete.disconnect()
        self._sequencegeneratorlogic.sigLoadedAssetUpdated.disconnect()
        self._sequencegeneratorlogic.sigBenchmarkComplete.disconnect()

        # Disconnect signals controlling PulsedMeasurementLogic
        self.sigTogglePulser.disconnect()

    @fc.constructor
    def sv_set_fits(self, val):
        # Setup fit container
        fc = self.fitlogic().make_fit_container('ODMR sum', '1d')
        fc.set_units(['Hz', 'c/s'])
        if isinstance(val, dict) and len(val) > 0:
            fc.load_from_dict(val)
        else:
            d1 = OrderedDict()
            d1['Lorentzian dip'] = {
                'fit_function': 'lorentzian',
                'estimator': 'dip'
            }
            d1['Two Lorentzian dips'] = {
                'fit_function': 'lorentziandouble',
                'estimator': 'dip'
            }
            d1['N14'] = {
                'fit_function': 'lorentziantriple',
                'estimator': 'N14'
            }
            d1['N15'] = {
                'fit_function': 'lorentziandouble',
                'estimator': 'N15'
            }
            d1['Two Gaussian dips'] = {
                'fit_function': 'gaussiandouble',
                'estimator': 'dip'
            }
            default_fits = OrderedDict()
            default_fits['1d'] = d1
            fc.load_from_dict(default_fits)
        return fc

    @fc.representer
    def sv_get_fits(self, val):
        """ save configured fits """
        if len(val.fit_list) > 0:
            return val.save_to_dict()
        else:
            return None

    def _initialize_odmr_plots(self):
        """ Initializing the ODMR plots (line and matrix). """

        if 'ranges' in self.generate_method_params.get(self.curr_loaded_seq):
            # For ODMR measurements
            final_freq_list = []
            self.frequency_lists = []
            for mw_start, mw_stop, mw_step in zip(self.mw_starts, self.mw_stops, self.mw_steps):
                freqs = np.arange(mw_start, mw_stop + mw_step, mw_step)
                final_freq_list.extend(freqs)
                self.frequency_lists.append(freqs)

            # if type(self.final_freq_list) == list:
            self.final_freq_list = np.array(final_freq_list)
            
            self.odmr_plot_x = np.array(self.final_freq_list)
            self.odmr_plot_y = np.zeros(self.odmr_plot_x.size)

            range_to_fit = self.range_to_fit

            self.odmr_fit_x = np.arange(self.mw_starts[range_to_fit],
                                        self.mw_stops[range_to_fit] + self.mw_steps[range_to_fit],
                                        self.mw_steps[range_to_fit])

            self.odmr_fit_y = np.zeros(self.odmr_fit_x.size)

            self.sigOdmrPlotsUpdated.emit(self.odmr_plot_x, self.odmr_plot_y,'Frequency','Hz')
            current_fit = self.fc.current_fit
            self.sigOdmrFitUpdated.emit(self.odmr_fit_x, self.odmr_fit_y, {}, current_fit)
        else:
            # For Pulsed Measurements

            tau_start = []
            tau_step = []
            tau_end = []
            num_points = []
            tau_array = []
            reference = []

            if 'tau_start' in self.generate_method_params.get(self.curr_loaded_seq).keys():
                tau_start = self.generate_method_params.get(self.curr_loaded_seq)['tau_start']

            if 'tau_step' in self.generate_method_params.get(self.curr_loaded_seq).keys():
                tau_step = self.generate_method_params.get(self.curr_loaded_seq)['tau_step']

            if 'tau_end' in self.generate_method_params.get(self.curr_loaded_seq).keys():
                tau_end = self.generate_method_params.get(self.curr_loaded_seq)['tau_end']

            if 'num_of_points' in self.generate_method_params.get(self.curr_loaded_seq).keys():
                num_points = self.generate_method_params.get(self.curr_loaded_seq)['num_of_points']

            if 'reference' in self.generate_method_params.get(self.curr_loaded_seq).keys():
                reference = self.generate_method_params.get(self.curr_loaded_seq)['reference']

            if self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'rabiWF':
                self.tau_array = tau_start + np.arange(num_points) * tau_step
            elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'T1WFtwocurve':
                self.tau_array = np.geomspace(tau_start, tau_end, num_points)
            else:
                self.log.warning('Unable to initialize plot for this sequence.')
    
            if type(tau_array) != np.ndarray:
                self.tau_array = np.array(self.tau_array)

            # # this is where curves are added for multiple sources
            # if reference:
                
            # else:
            self.odmr_plot_x = self.tau_array
            self.odmr_plot_y = np.zeros(self.tau_array.size)

            # range_to_fit = self.range_to_fit
            # self.odmr_fit_x = np.arange(self.mw_starts[range_to_fit],
            #                             self.mw_stops[range_to_fit] + self.mw_steps[range_to_fit],
            #                             self.mw_steps[range_to_fit])

            # self.odmr_fit_y = np.zeros(self.odmr_fit_x.size)

            self.sigOdmrPlotsUpdated.emit(self.odmr_plot_x, self.odmr_plot_y,'Seconds','s')
            # current_fit = self.fc.current_fit
            # self.sigOdmrFitUpdated.emit(self.odmr_fit_x, self.odmr_fit_y, {}, current_fit)

        return

    def set_trigger(self, trigger_pol, frequency):
        """
        Set trigger polarity of external microwave trigger (for list and sweep mode).

        @param object trigger_pol: one of [TriggerEdge.RISING, TriggerEdge.FALLING]
        @param float frequency: trigger frequency during ODMR scan

        @return object: actually set trigger polarity returned from hardware
        """

        if self.module_state() != 'locked':
            self.mw_trigger_pol, triggertime = self._mw_device.set_ext_trigger(trigger_pol, 1 / frequency)
        else:
            self.log.warning('set_trigger failed. Logic is locked.')

        update_dict = {'trigger_pol': self.mw_trigger_pol}
        self.sigParameterUpdated.emit(update_dict)
        return self.mw_trigger_pol

    def set_frame_rate(self, frame_rate):
        """
        Sets the frequency of the counter clock

        @param int frame_rate: desired frequency of the clock

        @return int: actually set clock frequency
        """
        # checks if scanner is still running
        if self.module_state() != 'locked' and isinstance(frame_rate, (int, float)):
            self.frame_rate = int(frame_rate)
        else:
            self.log.warning('set_frame_rate failed. Logic is either locked or input value is '
                             'no integer or float.')

        update_dict = {'frame_rate': self.frame_rate}
        self.sigParameterUpdated.emit(update_dict)
        return self.frame_rate

    def set_gpio_settings(self, input_settings, output_settings):
        """
        Sets the Input and output channel settings

        @param dict input_settings: desired settings for input channel
        @param dict output_settings: desired settings for output channel
        """
        self._widefield_camera.set_gpio_channel(input_settings)
        self._widefield_camera.set_gpio_channel(output_settings)

        return


    def set_runtime(self, runtime):
        """
        Sets the runtime for ODMR measurement

        @param float runtime: desired runtime in seconds

        @return float: actually set runtime in seconds
        """
        if isinstance(runtime, (int, float)):
            self.run_time = runtime
        else:
            self.log.warning('set_runtime failed. Input parameter runtime is no integer or float.')

        update_dict = {'run_time': self.run_time}
        self.sigParameterUpdated.emit(update_dict)
        return self.run_time
    
    def change_measurement_type(self, measurement_type):
        """
        Change measurement type
        """
        self.measurement_type = measurement_type
        self.measurement_params = self.generate_method_params[self.measurement_type]
        #TODO: emit signal to change sequencegeneratorlogicmeasurement type
        return

    def set_camera_parameters(self, params):
        """ Set the desired new camera parameters
        
        @param dict params: dict containing parameters to change

        @return dict real_params: actually set params
        """
        if self.module_state() != 'locked':
            real_params, limits = self._widefield_camera.set_camera_parameters(params)
        else:
            self.log.warning('set_camera_parameters failed. Logic is locked.')

        self.gain = real_params["gain"]
        self.trigger_mode = real_params["trigger_mode"]
        self.exposure_mode = real_params["exposure_mode"]
        self.exposure_modes = limits["exposure_modes"]
        self.exposure_time = real_params["exposure_time"]
        self.image_width, self.image_height = real_params["image_size"]
        self.offset_x, self.offset_y = real_params["image_offset"]
        self.pixel_format = real_params["pixel_format"]
        self.pixel_formats = limits["pixel_formats"]
        self.plot_pixel_x, self.plot_pixel_y = real_params["plot_pixel"]
        
        self.sigPlotPxChanged.emit([self.plot_pixel_x,self.plot_pixel_y])
        self.sigParameterUpdated.emit(real_params)
        input_limits, output_limits = self._widefield_camera.get_channel_limits()
        self.sigCameraLimits.emit((limits, input_limits, output_limits))
        return real_params

    def set_cw_parameters(self, frequency, power):
        """ Set the desired new cw mode parameters.

        @param float frequency: frequency to set in Hz
        @param float power: power to set in dBm

        @return (float, float): actually set frequency in Hz, actually set power in dBm
        """
        if self.module_state() != 'locked' and isinstance(frequency, (int, float)) and isinstance(power, (int, float)):
            constraints = self.get_hw_constraints()
            frequency_to_set = constraints.frequency_in_range(frequency)
            power_to_set = constraints.power_in_range(power)
            self.cw_mw_frequency, self.cw_mw_power, dummy = self._mw_device.set_cw(frequency_to_set,
                                                                                   power_to_set)
        else:
            self.log.warning('set_cw_frequency failed. Logic is either locked or input value is '
                             'no integer or float.')

        param_dict = {'cw_mw_frequency': self.cw_mw_frequency, 'cw_mw_power': self.cw_mw_power}
        self.sigParameterUpdated.emit(param_dict)
        return self.cw_mw_frequency, self.cw_mw_power

    def set_sweep_parameters(self, starts, stops, steps, power):
        """ Set the desired frequency parameters for list and sweep mode

        @param list starts: list of start frequencies to set in Hz
        @param list stops: list of stop frequencies to set in Hz
        @param list steps: list of step frequencies to set in Hz
        @param list power: mw power to set in dBm

        @return list, list, list, float: current start_freq, current stop_freq,
                                            current freq_step, current power
        """
        limits = self.get_hw_constraints()
        # as everytime all the elements are read when editing of a box is finished
        # also need to reset the lists in this case
        self.mw_starts = []
        self.mw_steps = []
        self.mw_stops = []

        if self.module_state() != 'locked':
            for start, step, stop in zip(starts, steps, stops):
                if isinstance(start, (int, float)):
                    self.mw_starts.append(limits.frequency_in_range(start))
                if isinstance(stop, (int, float)) and isinstance(step, (int, float)):
                    if stop <= start:
                        stop = start + step
                    self.mw_stops.append(limits.frequency_in_range(stop))
                    if self.mw_scanmode == MicrowaveMode.LIST:
                        self.mw_steps.append(limits.list_step_in_range(step))
                    elif self.mw_scanmode == MicrowaveMode.SWEEP:
                        if self.ranges == 1:
                            self.mw_steps.append(limits.sweep_step_in_range(step))
                        else:
                            self.log.error("Sweep mode will only work with one frequency range.")

            if isinstance(power, (int, float)):
                self.sweep_mw_power = limits.power_in_range(power)
        else:
            self.log.warning('set_sweep_parameters failed. Logic is locked.')

        param_dict = {'mw_starts': self.mw_starts, 'mw_stops': self.mw_stops, 'mw_steps': self.mw_steps,
                      'sweep_mw_power': self.sweep_mw_power}
        self.sigParameterUpdated.emit(param_dict)
        return self.mw_starts, self.mw_stops, self.mw_steps, self.sweep_mw_power

    def mw_cw_on(self):
        """
        Switching on the mw source in cw mode.

        @return str, bool: active mode ['cw', 'list', 'sweep'], is_running
        """
        # if self.module_state() == 'locked':
        #     self.log.error('Can not start microwave in CW mode. ODMRLogic is already locked.')
        # else:
        self.cw_mw_frequency, \
        self.cw_mw_power, \
        mode = self._mw_device.set_cw(self.cw_mw_frequency, self.cw_mw_power)
        param_dict = {'cw_mw_frequency': self.cw_mw_frequency, 'cw_mw_power': self.cw_mw_power}
        self.sigParameterUpdated.emit(param_dict)
        if mode != 'cw':
            self.log.error('Switching to CW microwave output mode failed.')
        else:
            err_code = self._mw_device.cw_on()
            if err_code < 0:
                self.log.error('Activation of microwave output failed.')

        mode, is_running = self._mw_device.get_status()
        self.sigOutputStateUpdated.emit(mode, is_running)
        return mode, is_running

    def mw_sweep_on(self):
        """
        Switching on the mw source in list/sweep mode. Set trigger mode

        @return str, bool: active mode ['cw', 'list', 'sweep'], is_running
        """
        
        # TODO some sources do not have all these modes  

        limits = self.get_hw_constraints()
        param_dict = {}
        self.final_freq_list = []

        # if ranges is in the generate method params, we are sweeping freq.
        if 'ranges' in self.generate_method_params.get(self.curr_loaded_seq):
            if self.mw_scanmode == MicrowaveMode.LIST:
                final_freq_list = []
                used_starts = []
                used_steps = []
                used_stops = []
                for mw_start, mw_stop, mw_step in zip(self.mw_starts, self.mw_stops, self.mw_steps):
                    num_steps = int(np.rint((mw_stop - mw_start) / mw_step))
                    end_freq = mw_start + num_steps * mw_step
                    freq_list = np.linspace(mw_start, end_freq, num_steps + 1)
                    # adjust the end frequency in order to have an integer multiple of step size
                    # The master module (i.e. GUI) will be notified about the changed end frequency
                    final_freq_list.extend(freq_list)
                    used_starts.append(mw_start)
                    used_steps.append(mw_step)
                    used_stops.append(end_freq)

                final_freq_list = np.array(final_freq_list)
                if len(final_freq_list) >= limits.list_maxentries:
                    self.log.error('Number of frequency steps too large for microwave device.')
                    mode, is_running = self._mw_device.get_status()
                    self.sigOutputStateUpdated.emit(mode, is_running)
                    return mode, is_running

                # TODO Trigger mode is currently measurement dependent (eventually ESR should be changed for PS to trigger MW)
                # This needs to be changed for general triggering, as currently this will only work for WF ESR

                # Upload list of frequency/dwell time/power and set trigger mode of MW
                
                freq_list, self.sweep_mw_power, mode = self._mw_device.set_list(final_freq_list,
                                                                                self.sweep_mw_power,
                                                                                MicrowaveTriggerMode.SINGLE)

                self.final_freq_list = np.array(freq_list)
                self.mw_starts = used_starts
                self.mw_stops = used_stops
                self.mw_steps = used_steps
                param_dict = {'mw_starts': used_starts, 'mw_stops': used_stops,
                                'mw_steps': used_steps, 'sweep_mw_power': self.sweep_mw_power}

                self.sigParameterUpdated.emit(param_dict)

            elif self.mw_scanmode == MicrowaveMode.SWEEP:
                if self.ranges == 1:
                    mw_stop = self.mw_stops[0]
                    mw_step = self.mw_steps[0]
                    mw_start = self.mw_starts[0]

                    if np.abs(mw_stop - mw_start) / mw_step >= limits.sweep_maxentries:
                        self.log.warning('Number of frequency steps too large for microwave device. '
                                            'Lowering resolution to fit the maximum length.')
                        mw_step = np.abs(mw_stop - mw_start) / (limits.list_maxentries - 1)
                        self.sigParameterUpdated.emit({'mw_steps': [mw_step]})

                    sweep_return = self._mw_device.set_sweep(
                        mw_start, mw_stop, mw_step, self.sweep_mw_power)
                    mw_start, mw_stop, mw_step, self.sweep_mw_power, mode = sweep_return

                    param_dict = {'mw_starts': [mw_start], 'mw_stops': [mw_stop],
                                    'mw_steps': [mw_step], 'sweep_mw_power': self.sweep_mw_power}
                    self.final_freq_list = np.arange(mw_start, mw_stop + mw_step, mw_step)
                else:
                    self.log.error('sweep mode only works for one frequency range.')

            else:
                self.log.error('Scanmode not supported. Please select SWEEP or LIST.')

            self.sigParameterUpdated.emit(param_dict)

            if mode != 'list' and mode != 'sweep':
                self.log.error('Switching to list/sweep microwave output mode failed.')
            elif self.mw_scanmode == MicrowaveMode.SWEEP:
                err_code = self._mw_device.sweep_on()
                if err_code < 0:
                    self.log.error('Activation of microwave output failed.')
            else:
                err_code = self._mw_device.list_on()
                if err_code < 0:
                    self.log.error('Activation of microwave output failed.')

        else:
            # When ranges is not active, we have constant cw output.  
            cw_freq, cw_power ,mode = self._mw_device.set_cw(self.cw_mw_frequency,self.cw_mw_power)
            
            # TODO check that this signal does not bug with cw outputs
            param_dict = {'cw_mw_frequency': cw_freq, 'cw_mw_power': cw_power}
            self.sigParameterUpdated.emit(param_dict)

            # Turn on CW output   
            self._mw_device.cw_on() 

        mode, is_running = self._mw_device.get_status()
        self.sigOutputStateUpdated.emit(mode, is_running)
        return mode, is_running

    def reset_sweep(self):
        """
        Resets the list/sweep mode of the microwave source to the first frequency step.
        """
        if self.mw_scanmode == MicrowaveMode.SWEEP:
            self._mw_device.reset_sweeppos()
        elif self.mw_scanmode == MicrowaveMode.LIST:
            self._mw_device.reset_listpos()
        return

    def mw_off(self):
        """ Switching off the MW source.

        @return str, bool: active mode ['cw', 'list', 'sweep'], is_running
        """
        error_code = self._mw_device.off()
        if error_code < 0:
            self.log.error('Switching off microwave source failed.')

        mode, is_running = self._mw_device.get_status()
        self.sigOutputStateUpdated.emit(mode, is_running)
        return mode, is_running

    def mw_trigger(self):
        """Trigger the mw source.
        @return None
        """
        self._mw_device.trigger()
        return

    

    def _start_widefield_odmr_counter(self):
        """
        Starting the ODMR counter and set up the clock for it.
        This will setup the widefield camera

        @return int: error code (0:OK, -1:error)
        """

        # if clock_status < 0:
        #     return -1

        # counter_status = self._widefield_camera.set_up_widefield_odmr()
        # if counter_status < 0:
        #     self._widefield_camera.close_widefield_odmr_clock()
        #     return -1

        return 0

    def _stop_widefield_odmr_counter(self):
        """
        Stopping the ODMR counter.

        @return int: error code (0:OK, -1:error)
        """

        # ret_val1 = self._widefield_camera.close_odmr()
        self._widefield_camera.stop_acquisition()

        # if ret_val1 != 0:
        #     self.log.error('ODMR counter could not be stopped!')
        # ret_val2 = self._widefield_camera.close_odmr_clock()
        # if ret_val2 != 0:
        #     self.log.error('ODMR clock could not be stopped!')

        # Check with a bitwise or:
        # return ret_val1 | ret_val2
        return 

    def start_widefield_odmr_scan(self):
        """ Starting an ODMR scan.

        @return int: error code (0:OK, -1:error)
        """
        with self.threadlock:
            if self.module_state() == 'locked':
                self.log.error('Can not start ODMR scan. Logic is already locked.')
                return -1

            # self.set_trigger(self.mw_trigger_pol, self.frame_rate)

            self.module_state.lock()
            self._clearOdmrData = False
            self.stopRequested = False
            self.fc.clear_result()

            self.elapsed_sweeps = 0
            self.elapsed_time = 0.0
            self._startTime = time.time()
            self.sigOdmrElapsedTimeUpdated.emit(self.elapsed_time, self.elapsed_sweeps)


            #sets the microwave settings and turns on output
            # mode, is_running = self.mw_sweep_on()
            mode, is_running = self.mw_cw_on()

            # odmr_status = self._start_widefield_odmr_counter()
            # if odmr_status < 0:
            #     mode, is_running = self._mw_device.get_status()
            #     self.sigOutputStateUpdated.emit(mode, is_running)
            #     self.module_state.unlock()
            #     return -1

            # if not is_running:
            #     self._stop_widefield_odmr_counter()
            #     self.module_state.unlock()
            #     return -1

            # Configure camera exposuremode / trigger mode 
            # TODO it should automatically update the camera settings and reflect it on gui too

            cam_trig_mode = self._pulsedmeasurementlogic.measurement_information.get('cam_trig_mode')
            cam_exp_mode = self._pulsedmeasurementlogic.measurement_information.get('cam_exp_mode')

            self._widefield_camera.set_trigger_mode(cam_trig_mode)
            self._widefield_camera.set_exposure_mode(cam_exp_mode)

            # if self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'ODMR':
            #     self._widefield_camera.set_trigger_mode(False)
            #     self._widefield_camera.set_exposure_mode('Timed')
            # elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'rabiWF':
            #     self._widefield_camera.set_trigger_mode(True)
            #     self._widefield_camera.set_exposure_mode('Timed')
            # elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'T1WFtwocurve':
            #     self._widefield_camera.set_trigger_mode(True)
            #     self._widefield_camera.set_exposure_mode('TriggerWidth')
            # elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'T1WFexp3':
            #     self._widefield_camera.set_trigger_mode(True)
            #     self._widefield_camera.set_exposure_mode('TriggerWidth')
            # else: 
            #     pass

            self._initialize_odmr_plots()
           
            # Initialize raw data array

            num_curves = self._pulsedmeasurementlogic.measurement_information.get('number_of_curves')

            self.num_imgs = self.odmr_plot_x.size*num_curves

            # if self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'ODMR':
            #     self.num_imgs = self.odmr_plot_x.size
            # elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'rabiWF':
            #     if 'reference' in self.generate_method_params.get(self.curr_loaded_seq).keys():
            #         self.num_imgs = 2*self.odmr_plot_x.size
            #     else:
            #         self.num_imgs = self.odmr_plot_x.size
            # elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'T1WFtwocurve':
            #     self.num_imgs = 2*self.odmr_plot_x.size
            # elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'T1WFexp3':
            #     self.num_imgs = 3*self.odmr_plot_x.size
            # else: 
            #     pass

            self.odmr_raw_data = np.zeros(
            [self._widefield_camera.get_size()[0],
             self._widefield_camera.get_size()[1],self.num_imgs]
            )

            self.sigNextLine.emit()
            return 0

    def continue_widefield_odmr_scan(self):
        """ Continue ODMR scan.

        @return int: error code (0:OK, -1:error)
        """
        with self.threadlock:
            if self.module_state() == 'locked':
                self.log.error('Can not start ODMR scan. Logic is already locked.')
                return -1

            self.set_trigger(self.mw_trigger_pol, self.frame_rate)

            self.module_state.lock()
            self.stopRequested = False
            self.fc.clear_result()

            self._startTime = time.time() - self.elapsed_time
            self.sigOdmrElapsedTimeUpdated.emit(self.elapsed_time, self.elapsed_sweeps)

            odmr_status = self._start_widefield_odmr_counter()
            if odmr_status < 0:
                mode, is_running = self._mw_device.get_status()
                self.sigOutputStateUpdated.emit(mode, is_running)
                self.module_state.unlock()
                return -1

            mode, is_running = self.mw_sweep_on()
            if not is_running:
                self._stop_widefield_odmr_counter()
                self.module_state.unlock()
                return -1

            self.sigNextLine.emit()
            return 0

    def stop_widefield_odmr_scan(self):
        """ Stop the ODMR scan.

        @return int: error code (0:OK, -1:error)
        """
        with self.threadlock:
            if self.module_state() == 'locked':
                self.stopRequested = True
        return 0

    def clear_widefield_odmr_data(self):
        """¨Set the option to clear the curret ODMR data.

        The clear operation has to be performed within the method
        _scan_widefield_odmr_line. This method just sets the flag for that. """
        with self.threadlock:
            if self.module_state() == 'locked':
                self._clearOdmrData = True
        return

    def _scan_widefield_odmr_line(self):
        """ Scans one line in ODMR

        (from mw_start to mw_stop in steps of mw_step)
        """
        
        with self.threadlock:
            # If the odmr measurement is not running do nothing
            if self.module_state() != 'locked':
                return

            # Stop measurement if stop has been requested
            if self.stopRequested:
                self.stopRequested = False
                self.mw_off()
                self._stop_widefield_odmr_counter()
                self._pulser.pulser_off()
                self.save_WF_data()
                self.module_state.unlock()
                return

            # if during the scan a clearing of the ODMR data is needed:
            if self._clearOdmrData:
                self.elapsed_sweeps = 0
                self._startTime = time.time()

            # TODO this if loop can eventually be solved using predefined method 
            if self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'ODMR':
                # for CW odmr, pulse streamer is on the whole time

                # Laser and MW switch constant output, THIS SHOULD BE MOVED TO LAST to make ESR AND pulsed all work.
                self._pulser.pulser_on(n=-1,final=self._pulser._laser_off_state) 

                # Collect Count data
                for i in range(len(self.final_freq_list)):
                    self._mw_device.set_frequency(self.final_freq_list[i])
                    self._widefield_camera.begin_acquisition(1)
                    error,new_counts = self._widefield_camera.grab(1)
                    self.odmr_raw_data[:,:,i] += np.squeeze(new_counts)
            else: 
                # For pulsed measurements 
                
                self._widefield_camera.begin_acquisition(self.num_imgs)

                # Send sequence once to measure 1 line.
                self._pulser.pulser_on(False,1,False,final=self._pulser._laser_off_state) 

                # Collect Count data
                error,new_counts = self._widefield_camera.grab(self.num_imgs)
                
                for i in range(self.num_imgs):
                    self.odmr_raw_data[:,:,i] += new_counts[:,:,i]

            if error:
                self.stopRequested = True
                self.sigNextLine.emit()
                return

            # Add new count data to raw_data array and append if array is too small
            if self._clearOdmrData:
                self.odmr_raw_data[:, :, :] = 0
                self._clearOdmrData = False

            # Add new count data to mean signal
            if self._clearOdmrData:
                self.odmr_plot_y[:, :] = 0

            # Plot single pixel data
            self.plot_single_pixel()

            # Update elapsed time/sweeps
            self.elapsed_sweeps += 1
            self.elapsed_time = time.time() - self._startTime
            if self.elapsed_time >= self.run_time:
                self.stopRequested = True
            # Fire update signals
            self.sigOdmrElapsedTimeUpdated.emit(self.elapsed_time, self.elapsed_sweeps)
            self.sigOdmrPlotsUpdated.emit(self.odmr_plot_x, self.odmr_plot_y,None,None)
            
            self.sigNextLine.emit()
            return

    def plot_single_pixel(self):
        """ Prepares single curve data for plotting """

        num_curves = self._pulsedmeasurementlogic.measurement_information.get('number_of_curves')

        if num_curves == 1:
            self.odmr_plot_y = self.odmr_raw_data[self.plot_pixel_x, self.plot_pixel_y,:]
        elif num_curves == 2:
            #TODO this assumes a specific order, and only plots a single curve (subtracted bg) 
            data_l = np.zeros((self._widefield_camera.get_size()[0], self._widefield_camera.get_size()[1],int(self.num_imgs/2)))
            data_bg= np.zeros((self._widefield_camera.get_size()[0], self._widefield_camera.get_size()[1],int(self.num_imgs/2)))
            for i in range(int(self.num_imgs/2)):
                data_l[:,:,i] = self.odmr_raw_data[:,:,2*i]
                data_bg[:,:,i] = self.odmr_raw_data[:,:,2*i+1]
            self.odmr_plot_y = data_l[self.plot_pixel_x, self.plot_pixel_y,:] - data_bg[self.plot_pixel_x, self.plot_pixel_y,:]
        elif num_curves == 3:
            # TODO assumes specific order of pulsing, currently only plotting l-bg
            data_l = np.zeros((self._widefield_camera.get_size()[0], self._widefield_camera.get_size()[1],int(self.num_imgs/2)))
            data_u = np.zeros((self._widefield_camera.get_size()[0], self._widefield_camera.get_size()[1],int(self.num_imgs/2)))
            data_bg= np.zeros((self._widefield_camera.get_size()[0], self._widefield_camera.get_size()[1],int(self.num_imgs/2)))
            for i in range(int(self.num_imgs/3)):
                data_l[:,:,i] = self.odmr_raw_data[:,:,3*i]
                data_u[:,:,i] = self.odmr_raw_data[:,:,3*i+1]
                data_bg[:,:,i] = self.odmr_raw_data[:,:,3*i+2]
            self.odmr_plot_y = data_l[self.plot_pixel_x, self.plot_pixel_y,:] - data_bg[self.plot_pixel_x, self.plot_pixel_y,:]
        else: 
            self.log.warning('Number of curves exceeds 3')

        # if self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'ODMR':
        #         self.odmr_plot_y = self.odmr_raw_data[self.plot_pixel_x, self.plot_pixel_y,:]
        # elif self.generate_method_params.get(self.curr_loaded_seq)['name'] == 'rabiWF':
        #     if 'reference' in self.generate_method_params.get(self.curr_loaded_seq).keys():
        #         # split data
        #         rabi_l = np.zeros((self._widefield_camera.get_size()[0], self._widefield_camera.get_size()[1],int(self.num_imgs/2)))
        #         rabi_bg= np.zeros((self._widefield_camera.get_size()[0], self._widefield_camera.get_size()[1],int(self.num_imgs/2)))
        #         for i in range(int(self.num_imgs/2)):
        #             rabi_l[:,:,i] = self.odmr_raw_data[:,:,2*i]
        #             rabi_bg[:,:,i] = self.odmr_raw_data[:,:,2*i+1]

        #         self.odmr_plot_y = rabi_l[self.plot_pixel_x, self.plot_pixel_y,:] - rabi_bg[self.plot_pixel_x, self.plot_pixel_y,:]
        #     else:
        #         self.odmr_plot_y = self.odmr_raw_data[self.plot_pixel_x, self.plot_pixel_y,:]
        # else:   
        #     self.odmr_plot_y = self.odmr_raw_data[self.plot_pixel_x, self.plot_pixel_y,:]

        return 

    def update_plot_px(self, params):
        """ Send updated px data for GUI 
        
        @param dict params: dict containing parameters new pixels
        """
        try:
            self.plot_single_pixel()
            self.sigOdmrPlotsUpdated.emit(self.odmr_plot_x, self.odmr_plot_y,None,None)
        except:
            self.log.debug('Unable to change ODMR pixel plot')
            pass

        return

    def get_hw_constraints(self):
        """ Return the names of all ocnfigured fit functions.
        @return object: Hardware constraints object
        """
        constraints = self._mw_device.get_limits()
        return constraints

    def get_fit_functions(self):
        """ Return the hardware constraints/limits
        @return list(str): list of fit function names
        """
        return list(self.fc.fit_list)

    def do_fit(self, fit_function=None, x_data=None, y_data=None, channel_index=0, fit_range=0):
        """
        Execute the currently configured fit on the measurement data. Optionally on passed data
        """
        if (x_data is None) or (y_data is None):
            if fit_range >= 0:
                x_data = self.frequency_lists[fit_range]
                x_data_full_length = np.zeros(len(self.final_freq_list))
                # how to insert the data at the right position?
                start_pos = np.where(np.isclose(self.final_freq_list, self.mw_starts[fit_range]))[0][0]
                x_data_full_length[start_pos:(start_pos + len(x_data))] = x_data
                y_args = np.array([ind_list[0] for ind_list in np.argwhere(x_data_full_length)])
                # y_data = self.odmr_plot_y[channel_index][y_args]
                y_data = self.odmr_plot_y[y_args]

            else:
                x_data = self.final_freq_list
                y_data = self.odmr_plot_y[channel_index]
        if fit_function is not None and isinstance(fit_function, str):
            if fit_function in self.get_fit_functions():
                self.fc.set_current_fit(fit_function)
            else:
                self.fc.set_current_fit('No Fit')
                if fit_function != 'No Fit':
                    self.log.warning('Fit function "{0}" not available in ODMRLogic fit container.'
                                     ''.format(fit_function))

        self.odmr_fit_x, self.odmr_fit_y, result = self.fc.do_fit(x_data, y_data)
        key = 'channel: {0}, range: {1}'.format(channel_index, fit_range)
        if fit_function != 'No Fit':
            self.fits_performed[key] = (self.odmr_fit_x, self.odmr_fit_y, result, self.fc.current_fit)
        else:
            if key in self.fits_performed:
                self.fits_performed.pop(key)

        if result is None:
            result_str_dict = {}
        else:
            result_str_dict = result.result_str_dict
        self.sigOdmrFitUpdated.emit(
            self.odmr_fit_x, self.odmr_fit_y, result_str_dict, self.fc.current_fit)
        return

    def save_odmr_data(self, tag=None, colorscale_range=None, percentile_range=None):
        """ Saves the current ODMR data to a file."""
        timestamp = datetime.datetime.now()
        filepath = self._save_logic.get_path_for_module(module_name='ODMR')

        if tag is None:
            tag = ''

        # first save raw data for each channel
        if len(tag) > 0:
            filelabel_raw = '{0}_ODMR_data_raw'.format(tag)

        data_raw = OrderedDict()
        data_raw['count data (counts/s)'] = self.odmr_raw_data
        parameters = OrderedDict()
        parameters['Microwave CW Power (dBm)'] = self.cw_mw_power
        parameters['Microwave Sweep Power (dBm)'] = self.sweep_mw_power
        parameters['Run Time (s)'] = self.run_time
        parameters['Number of frequency sweeps (#)'] = self.elapsed_sweeps
        parameters['Start Frequencies (Hz)'] = self.mw_starts
        parameters['Stop Frequencies (Hz)'] = self.mw_stops
        parameters['Step sizes (Hz)'] = self.mw_steps
        parameters['Frame Rate (Hz)'] = self.frame_rate
        self._save_logic.save_data(data_raw,
                                    filepath=filepath,
                                    parameters=parameters,
                                    filelabel=filelabel_raw,
                                    fmt='%.6e',
                                    delimiter='\t',
                                    timestamp=timestamp)

        # now create a plot for each scan range
        data_start_ind = 0
        for ii, frequency_arr in enumerate(self.frequency_lists):
            if len(tag) > 0:
                filelabel = '{0}_ODMR_data_range{2}'.format(tag, ii)
            else:
                filelabel = 'ODMR_data_range{1}'.format(ii)

            # prepare the data in a dict or in an OrderedDict:
            data = OrderedDict()
            data['frequency (Hz)'] = frequency_arr

            num_points = len(frequency_arr)
            data_end_ind = data_start_ind + num_points
            data['count data (counts/s)'] = self.odmr_plot_y[data_start_ind:data_end_ind]
            data_start_ind += num_points

            parameters = OrderedDict()
            parameters['Microwave CW Power (dBm)'] = self.cw_mw_power
            parameters['Microwave Sweep Power (dBm)'] = self.sweep_mw_power
            parameters['Run Time (s)'] = self.run_time
            parameters['Number of frequency sweeps (#)'] = self.elapsed_sweeps
            parameters['Start Frequency (Hz)'] = frequency_arr[0]
            parameters['Stop Frequency (Hz)'] = frequency_arr[-1]
            parameters['Step size (Hz)'] = frequency_arr[1] - frequency_arr[0]
            parameters['Frame Rate (Hz)'] = self.frame_rate
            parameters['frequency range'] = str(ii)

            key = 'range: {1}'.format(ii)
            if key in self.fits_performed.keys():
                parameters['Fit function'] = self.fits_performed[key][3]
                for name, param in self.fits_performed[key][2].params.items():
                    parameters[name] = str(param)
            # add all fit parameter to the saved data:

            fig = self.draw_figure(ii,
                                    cbar_range=colorscale_range,
                                    percentile_range=percentile_range)

            self._save_logic.save_data(data,
                                        filepath=filepath,
                                        parameters=parameters,
                                        filelabel=filelabel,
                                        fmt='%.6e',
                                        delimiter='\t',
                                        timestamp=timestamp,
                                        plotfig=fig)

        self.log.info('ODMR data saved to:\n{0}'.format(filepath))
        return

    def save_WF_data(self):
        """ Saves the current ODMR data to a file."""
        # filepath = self._save_logic.get_path_for_module(module_name='ODMR')

        data_raw = OrderedDict()
        data_raw['Count_data'] = self.odmr_raw_data
        data_raw['Sweep_values'] = self.odmr_plot_x

        data_raw['CWPower_dBm'] = self.cw_mw_power
        data_raw['SweepPower_dBm'] = self.sweep_mw_power
        data_raw['RunTime_s'] = self.run_time
        data_raw['NumSweeps'] = self.elapsed_sweeps
        data_raw['StartFreq_Hz'] = self.mw_starts
        data_raw['StopFreq_Hz'] = self.mw_stops
        data_raw['StepSize_Hz'] = self.mw_steps
        data_raw['FrameRate_Hz'] = self.frame_rate

        # eventually the name will be changed to depend on measurement
        filepath = self._save_logic._save_WF_data(data_raw,'ODMR')

        # # now create a plot for each scan range
        # data_start_ind = 0
        # for ii, frequency_arr in enumerate(self.frequency_lists):
           
        #     # prepare the data in a dict or in an OrderedDict:
        #     data = OrderedDict()
        #     data['frequency (Hz)'] = frequency_arr

        #     num_points = len(frequency_arr)
        #     data_end_ind = data_start_ind + num_points
        #     data['count data (counts/s)'] = self.odmr_plot_y[data_start_ind:data_end_ind]
        #     data_start_ind += num_points

        # self.log.info('WF data saved')
        self.log.info('WF data saved to:\n{0}'.format(filepath))

        return

    def get_camera_limits(self):
        """ Return limits from camera
        """
        limits = self._widefield_camera.get_limits()
        input_limits, output_limits = self._widefield_camera.get_channel_limits()
        return limits, input_limits, output_limits

    def draw_figure(self, channel_number, freq_range, cbar_range=None, percentile_range=None):
        """ Draw the summary figure to save with the data.

        @param: list cbar_range: (optional) [color_scale_min, color_scale_max].
                                 If not supplied then a default of data_min to data_max
                                 will be used.

        @param: list percentile_range: (optional) Percentile range of the chosen cbar_range.

        @return: fig fig: a matplotlib figure object to be saved to file.
        """
        key = 'channel: {0}, range: {1}'.format(channel_number, freq_range)
        freq_data = self.frequency_lists[freq_range]
        lengths = [len(freq_range) for freq_range in self.frequency_lists]
        cumulative_sum = list()
        tmp_val = 0
        cumulative_sum.append(tmp_val)
        for length in lengths:
            tmp_val += length
            cumulative_sum.append(tmp_val)

        ind_start = cumulative_sum[freq_range]
        ind_end = cumulative_sum[freq_range + 1]
        count_data = self.odmr_plot_y[channel_number][ind_start:ind_end]
        fit_freq_vals = self.frequency_lists[freq_range]
        if key in self.fits_performed:
            fit_count_vals = self.fits_performed[key][2].eval()
        else:
            fit_count_vals = 0.0

        # If no colorbar range was given, take full range of data
        if cbar_range is None:
            cbar_range = np.array([np.min(matrix_data), np.max(matrix_data)])
        else:
            cbar_range = np.array(cbar_range)

        prefix = ['', 'k', 'M', 'G', 'T']
        prefix_index = 0

        # Rescale counts data with SI prefix
        while np.max(count_data) > 1000:
            count_data = count_data / 1000
            fit_count_vals = fit_count_vals / 1000
            prefix_index = prefix_index + 1

        counts_prefix = prefix[prefix_index]

        # Rescale frequency data with SI prefix
        prefix_index = 0

        while np.max(freq_data) > 1000:
            freq_data = freq_data / 1000
            fit_freq_vals = fit_freq_vals / 1000
            prefix_index = prefix_index + 1

        mw_prefix = prefix[prefix_index]

        # Rescale matrix counts data with SI prefix
        prefix_index = 0

        while np.max(matrix_data) > 1000:
            matrix_data = matrix_data / 1000
            cbar_range = cbar_range / 1000
            prefix_index = prefix_index + 1

        cbar_prefix = prefix[prefix_index]

        # Use qudi style
        plt.style.use(self._save_logic.mpl_qd_style)

        # Create figure
        fig, (ax_mean, ax_matrix) = plt.subplots(nrows=2, ncols=1)

        ax_mean.plot(freq_data, count_data, linestyle=':', linewidth=0.5)

        # Do not include fit curve if there is no fit calculated.
        if hasattr(fit_count_vals, '__len__'):
            ax_mean.plot(fit_freq_vals, fit_count_vals, marker='None')

        ax_mean.set_ylabel('Fluorescence (' + counts_prefix + 'c/s)')
        ax_mean.set_xlim(np.min(freq_data), np.max(freq_data))

        matrixplot = ax_matrix.imshow(
            matrix_data,
            cmap=plt.get_cmap('inferno'),  # reference the right place in qd
            origin='lower',
            vmin=cbar_range[0],
            vmax=cbar_range[1],
            extent=[np.min(freq_data),
                    np.max(freq_data),
                    0,
                    self.number_of_lines
                    ],
            aspect='auto',
            interpolation='nearest')

        ax_matrix.set_xlabel('Frequency (' + mw_prefix + 'Hz)')
        ax_matrix.set_ylabel('Scan #')

        # Adjust subplots to make room for colorbar
        fig.subplots_adjust(right=0.8)

        # Add colorbar axis to figure
        cbar_ax = fig.add_axes([0.85, 0.15, 0.02, 0.7])

        # Draw colorbar
        cbar = fig.colorbar(matrixplot, cax=cbar_ax)
        cbar.set_label('Fluorescence (' + cbar_prefix + 'c/s)')

        # remove ticks from colorbar for cleaner image
        cbar.ax.tick_params(which=u'both', length=0)

        # If we have percentile information, draw that to the figure
        if percentile_range is not None:
            cbar.ax.annotate(str(percentile_range[0]),
                             xy=(-0.3, 0.0),
                             xycoords='axes fraction',
                             horizontalalignment='right',
                             verticalalignment='center',
                             rotation=90
                             )
            cbar.ax.annotate(str(percentile_range[1]),
                             xy=(-0.3, 1.0),
                             xycoords='axes fraction',
                             horizontalalignment='right',
                             verticalalignment='center',
                             rotation=90
                             )
            cbar.ax.annotate('(percentile)',
                             xy=(-0.3, 0.5),
                             xycoords='axes fraction',
                             horizontalalignment='right',
                             verticalalignment='center',
                             rotation=90
                             )

        return fig

    # def select_odmr_matrix_data(self, odmr_matrix, nch, freq_range):
    #     odmr_matrix_dp = odmr_matrix[:, nch]
    #     x_data = self.frequency_lists[freq_range]
    #     x_data_full_length = np.zeros(len(self.final_freq_list))
    #     mw_starts = [freq_arr[0] for freq_arr in self.frequency_lists]
    #     start_pos = np.where(np.isclose(self.final_freq_list,
    #                                     mw_starts[freq_range]))[0][0]
    #     x_data_full_length[start_pos:(start_pos + len(x_data))] = x_data
    #     y_args = np.array([ind_list[0] for ind_list in np.argwhere(x_data_full_length)])
    #     odmr_matrix_range = odmr_matrix_dp[:, y_args]
    #     return odmr_matrix_range

    def perform_odmr_measurement(self, freq_start, freq_step, freq_stop, power, channel, runtime,
                                 fit_function='No Fit', save_after_meas=True, name_tag=''):
        """ An independant method, which can be called by a task with the proper input values
            to perform an odmr measurement.

        @return
        """
        timeout = 30
        start_time = time.time()
        while self.module_state() != 'idle':
            time.sleep(0.5)
            timeout -= (time.time() - start_time)
            if timeout <= 0:
                self.log.error('perform_odmr_measurement failed. Logic module was still locked '
                               'and 30 sec timeout has been reached.')
                return tuple()

        # set all relevant parameter:
        self.set_sweep_parameters(freq_start, freq_stop, freq_step, power)
        self.set_runtime(runtime)

        # start the scan
        self.start_widefield_odmr_scan()

        # wait until the scan has started
        while self.module_state() != 'locked':
            time.sleep(1)
        # wait until the scan has finished
        while self.module_state() == 'locked':
            time.sleep(1)

        # Perform fit if requested
        if fit_function != 'No Fit':
            self.do_fit(fit_function, channel_index=channel)
            fit_params = self.fc.current_fit_param
        else:
            fit_params = None

        # Save data if requested
        if save_after_meas:
            self.save_odmr_data(tag=name_tag)

        return self.odmr_plot_x, self.odmr_plot_y, fit_params
    

#######################################################################
    ###             Sequence generator properties                       ###
    #######################################################################
    @property
    def pulse_generator_constraints(self):
        return self._sequencegeneratorlogic.pulse_generator_constraints

    @property
    def pulse_generator_settings(self):
        return self._sequencegeneratorlogic.pulse_generator_settings

    @property
    def generation_parameters(self):
        return self._sequencegeneratorlogic.generation_parameters

    @property
    def analog_channels(self):
        return self._sequencegeneratorlogic.analog_channels

    @property
    def digital_channels(self):
        return self._sequencegeneratorlogic.digital_channels

    @property
    def saved_pulse_blocks(self):
        return self._sequencegeneratorlogic.saved_pulse_blocks

    @property
    def saved_pulse_block_ensembles(self):
        return self._sequencegeneratorlogic.saved_pulse_block_ensembles

    @property
    def saved_pulse_sequences(self):
        return self._sequencegeneratorlogic.saved_pulse_sequences

    @property
    def sampled_waveforms(self):
        return self._sequencegeneratorlogic.sampled_waveforms

    @property
    def sampled_sequences(self):
        return self._sequencegeneratorlogic.sampled_sequences

    @property
    def loaded_asset(self):
        return self._sequencegeneratorlogic.loaded_asset

    @property
    def generate_methods(self):
        return getattr(self._sequencegeneratorlogic, 'generate_methods', dict())

    @property
    def generate_method_params(self):
        return getattr(self._sequencegeneratorlogic, 'generate_method_params', dict())   
    

    #######################################################################
    ###             Sequence generator methods                          ###
    #######################################################################

    @QtCore.Slot(str)
    @QtCore.Slot(str, bool)
    def sample_ensemble(self, ensemble_name, with_load=False):
        already_busy = self.status_dict['sampling_ensemble_busy'] or self.status_dict[
            'sampling_sequence_busy'] or self._sequencegeneratorlogic.module_state() == 'locked'
        if already_busy:
            self.log.error('Sampling of a different asset already in progress.\n'
                           'PulseBlockEnsemble "{0}" not sampled!'.format(ensemble_name))
        else:
            if with_load:
                self.status_dict['sampload_busy'] = True
            self.status_dict['sampling_ensemble_busy'] = True
            self.sigSampleBlockEnsemble.emit(ensemble_name)
        return

    @QtCore.Slot(object)
    def sample_ensemble_finished(self, ensemble):
        self.status_dict['sampling_ensemble_busy'] = False
        self.sigSampleEnsembleComplete.emit(ensemble)
        if self.status_dict['sampload_busy'] and not self.status_dict['sampling_sequence_busy']:
            if ensemble is None:
                self.status_dict['sampload_busy'] = False
                self.sigLoadedAssetUpdated.emit(*self.loaded_asset)
            else:
                self.load_ensemble(ensemble.name)
        return

    @QtCore.Slot(str)
    @QtCore.Slot(str, bool)
    def sample_sequence(self, sequence_name, with_load=False):
        already_busy = self.status_dict['sampling_ensemble_busy'] or self.status_dict[
            'sampling_sequence_busy'] or self._sequencegeneratorlogic.module_state() == 'locked'
        if already_busy:
            self.log.error('Sampling of a different asset already in progress.\n'
                           'PulseSequence "{0}" not sampled!'.format(sequence_name))
        else:
            if with_load:
                self.status_dict['sampload_busy'] = True
            self.status_dict['sampling_sequence_busy'] = True
            self.sigSampleSequence.emit(sequence_name)
        return

    @QtCore.Slot(object)
    def sample_sequence_finished(self, sequence):
        self.status_dict['sampling_sequence_busy'] = False
        self.sigSampleSequenceComplete.emit(sequence)
        if self.status_dict['sampload_busy']:
            if sequence is None:
                self.status_dict['sampload_busy'] = False
                self.sigLoadedAssetUpdated.emit(*self.loaded_asset)
            else:
                self.load_sequence(sequence.name)
        return

    @QtCore.Slot(str)
    def load_ensemble(self, ensemble_name):
        if self.status_dict['loading_busy']:
            self.log.error('Loading of a different asset already in progress.\n'
                           'PulseBlockEnsemble "{0}" not loaded!'.format(ensemble_name))
            self.loaded_asset_updated(*self.loaded_asset)
        elif self.status_dict['measurement_running']:
            self.log.error('Loading of ensemble not possible while measurement is running.\n'
                           'PulseBlockEnsemble "{0}" not loaded!'.format(ensemble_name))
            self.loaded_asset_updated(*self.loaded_asset)
        else:
            self.status_dict['loading_busy'] = True
            if self.status_dict['pulser_running']:
                self.log.warning('Can not load new asset into pulse generator while it is still '
                                 'running. Turned off.')
                self._pulsedmeasurementlogic.pulse_generator_off()
            self.sigLoadBlockEnsemble.emit(ensemble_name)
        return

    @QtCore.Slot(str)
    @QtCore.Slot(str, dict)
    @QtCore.Slot(str, dict, bool)
    def generate_predefined_sequence(self, generator_method_name, kwarg_dict=None, sample_and_load=False):
        """

        @param generator_method_name:
        @param kwarg_dict:
        @param sample_and_load:
        @return:
        """
        if not isinstance(kwarg_dict, dict):
            kwarg_dict = dict()
        self.status_dict['predefined_generation_busy'] = True
        if sample_and_load:
            self.status_dict['sampload_busy'] = True
        self.sigGeneratePredefinedSequence.emit(generator_method_name, kwarg_dict)
        self.curr_loaded_seq = generator_method_name
        return

    @QtCore.Slot(object, bool)
    def predefined_sequence_generated(self, asset_name, is_sequence):
        self.status_dict['predefined_generation_busy'] = False
        if asset_name is None:
            self.status_dict['sampload_busy'] = False
        self.sigPredefinedSequenceGenerated.emit(asset_name, is_sequence)
        if self.status_dict['sampload_busy']:
            if is_sequence:
                self.sample_sequence(asset_name, True)
            else:
                self.sample_ensemble(asset_name, True)
        return

    @QtCore.Slot(str)
    def load_sequence(self, sequence_name):
        if self.status_dict['loading_busy']:
            self.log.error('Loading of a different asset already in progress.\n'
                           'PulseSequence "{0}" not loaded!'.format(sequence_name))
            self.loaded_asset_updated(*self.loaded_asset)
        elif self.status_dict['measurement_running']:
            self.log.error('Loading of sequence not possible while measurement is running.\n'
                           'PulseSequence "{0}" not loaded!'.format(sequence_name))
            self.loaded_asset_updated(*self.loaded_asset)
        else:
            self.status_dict['loading_busy'] = True
            if self.status_dict['pulser_running']:
                self.log.warning('Can not load new asset into pulse generator while it is still '
                                 'running. Turned off.')
                self._pulsedmeasurementlogic.pulse_generator_off()
            self.sigLoadSequence.emit(sequence_name)
        return

    @QtCore.Slot(str, str)
    def loaded_asset_updated(self, asset_name, asset_type):
        """

        @param asset_name:
        @param asset_type:
        @return:
        """
        self.status_dict['sampload_busy'] = False
        self.status_dict['loading_busy'] = False
        self.sigLoadedAssetUpdated.emit(asset_name, asset_type)
        # Transfer sequence information from PulseBlockEnsemble or PulseSequence to
        # PulsedMeasurementLogic to be able to invoke measurement settings from them
        if not asset_type:
            # If no asset loaded or asset type unknown, clear sequence_information dict

            object_instance = None
        elif asset_type == 'PulseBlockEnsemble':
            object_instance = self.saved_pulse_block_ensembles.get(asset_name)
        elif asset_type == 'PulseSequence':
            object_instance = self.saved_pulse_sequences.get(asset_name)
        else:
            object_instance = None

        if object_instance is None:
            self._pulsedmeasurementlogic.sampling_information = dict()
            self._pulsedmeasurementlogic.measurement_information = dict()
        else:
            self._pulsedmeasurementlogic.sampling_information = object_instance.sampling_information
            self._pulsedmeasurementlogic.measurement_information = object_instance.measurement_information
        return

    def toggle_pulser_output(self,switch_on):

        # err = self._pulsedmeasurementlogic.toggle_pulse_generator(switch_on)
        if isinstance(switch_on,bool):    
            err = self.sigTogglePulser.emit(switch_on)
        else: 
            self.log.warning('Problem with pulser toggle')

        return err
        
    def clear_pulse_generator(self):
        still_busy = self.status_dict['sampling_ensemble_busy'] or self.status_dict[
            'sampling_sequence_busy'] or self.status_dict['loading_busy'] or self.status_dict[
                                   'sampload_busy']
        if still_busy:
            self.log.error('Can not clear pulse generator. Sampling/Loading still in progress.')
        elif self.status_dict['measurement_running']:
            self.log.error('Can not clear pulse generator. Measurement is still running.')
        else:
            if self.status_dict['pulser_running']:
                self.log.warning('Can not clear pulse generator while it is still running. '
                                 'Turned off.')
            self.pulsedmeasurementlogic().pulse_generator_off()
            self.sigClearPulseGenerator.emit()
        return