# -*- coding: utf-8 -*-
"""
This file contains the Qudi Interfuse file for ODMRCounter and Pulser.

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
import numpy as np
import time
import scipy.io as sio
from datetime import date
import os
import math

from core.connector import Connector
from logic.generic_logic import GenericLogic
from interface.odmr_counter_interface import ODMRCounterInterface
from interface.microwave_interface import MicrowaveInterface
from interface.microwave_interface import TriggerEdge
from core.configoption import ConfigOption

import time
from interface.simple_pulse_objects import PulseBlock, PulseSequence

class ODMRCounter_MW_Basler_Interfuse(GenericLogic, ODMRCounterInterface, MicrowaveInterface):
    """ This is the Interfuse class supplies the controls for a simple ODMR with counter and pulser."""

    # slowcounter = Connector(interface='RecorderInterface')
    slowcounter = Connector(interface='SlowCounterInterface')
    pulser = Connector(interface='PulserInterface')
    microwave1 = Connector(interface='MicrowaveInterface')
    _save_path = ConfigOption('savepath',True)


    # load pi pulse duration from config
    # pi_pulse_len = ConfigOption('pi_pulse', missing= 'warn',converter=float)
    pi_pulse_len = 94e-9

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._odmr_length = 100

    def on_activate(self):
        """ Initialisation performed during activation of the module."""
        self._pulser = self.pulser()
        self._sc_device = self.slowcounter()  # slow counter device
        self._mw_device = self.microwave1()

        self._lock_in_active = False
        self._oversampling = 10
        self._odmr_length = 100
        self.final_freq_list = []
        
        self.bin_width_s = 1e-9 #def 1e-9
        self.record_length_s = 3.5e-6 #def = 3e-6

        self.counts = []

    def on_deactivate(self):
        pass

    ### ODMR counter interface commands

    def set_up_odmr_clock(self, clock_frequency=None, clock_channel=None, pi_pulse= pi_pulse_len):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: if defined, this sets the frequency of the
                                      clock
        @param str clock_channel: if defined, this is the physical channel of
                                  the clock

        @return int: error code (0:OK, -1:error)
        """

        # uploads pulse sequence to the pulse streamer 

        d_ch = {0: False , 1: False , 2: False , 3: False , 4: False , 5: False , 6: False , 7: False }
        clear = lambda x: {i:False for i in x.keys()}
        
        seq = PulseSequence()
            
        block_1 = PulseBlock()

        d_ch = clear(d_ch)
        d_ch[self._pulser._laser_channel] = True
        d_ch[self._pulser._mw1_switch] = True
        d_ch[self._pulser._mw2_switch] = True
        block_1.append(init_length = 5e-6, channels = d_ch, repetition = 1)

        d_ch = clear(d_ch)
        # d_ch[self._pulser._laser_channel] = False
        # d_ch[self._pulser._mw1_switch] = True
        block_1.append(init_length = 0.5e-6, channels = d_ch, repetition = 1)

        seq.append([(block_1, 1)])

        pulse_dict = seq.pulse_dict

        self._pulser.load_swabian_sequence(pulse_dict)
        return 0

    def set_up_odmr(self, counter_channel=None, photon_source=None,
                    clock_channel=None, odmr_trigger_channel=None):
        """ Configures the actual counter with a given clock.

        @param str counter_channel: if defined, this is the physical channel of
                                    the counter
        @param str photon_source: if defined, this is the physical channel where
                                  the photons are to count from
        @param str clock_channel: if defined, this specifies the clock for the
                                  counter
        @param str odmr_trigger_channel: if defined, this specifies the trigger
                                         output for the microwave

        @return int: error code (0:OK, -1:error)
        """

        # Configure Basler for hardware triggering
        self._sc_device.set_up_counter()


        
        return 0

    def set_odmr_length(self, length=100):
        """Set up the trigger sequence for the ODMR and the triggered microwave.

        @param int length: length of microwave sweep in pixel

        @return int: error code (0:OK, -1:error)
        """
        # self._sc_device.configure_recorder(
        #     mode=HWRecorderMode.ESR,
        #     params={'mw_frequency_list': np.zeros(length),
        #             'num_meas': 1 } )

        # self._sc_device.configure_recorder(
        #     mode=HWRecorderMode.GENERAL_PULSED,
        #     params={'laser_pulses': 1, 'bin_width_s': 1 , 'record_length_s': 1 ,'max_counts': 1})

        # self._sc_device.configure_recorder(
        #                 mode=HWRecorderMode.GENERAL_PULSED, # pulsed mode
        #                 params={'laser_pulses': len(self.final_freq_list),
        #                         'bin_width_s': self.bin_width_s,
        #                         'record_length_s': self.record_length_s,
        #                         'max_counts': 1} ) 

        width, height = self._sc_device.get_constraints()
        self._WF_data = np.zeros((height, width, length),dtype="float64")
        self._odmr_length = length
        
        return 0

    def count_odmr(self, length = 100):
        """ Sweeps the microwave and returns the counts on that sweep.

        @param int length: length of microwave sweep in pixel

        @return float[]: the photon counts per second
        """
#  ################################
        # self._sc_device.start_recorder()
        # print(self._sc_device.recorder.getHistogramIndex())
        # self._pulser.pulser_on(n=-1,final=self._pulser._laser_off_state) # not sure why n=length fails
        # self._mw_device._command_wait(':FREQ:MODE SWEEP')

        # counts = self._sc_device.get_measurements(['counts'])[0].T
        # counts = np.sum(counts[83:400,:],0)
#  ################################

        # Laser and MW switch constant output
        self._pulser.pulser_on(n=-1,final=self._pulser._laser_off_state) 

        # Set up camera to grab _num_img photos and average them
        self._sc_device._num_img = length
      
        # For plotting central pixel
        counts = np.zeros((1, length))

        # self.set_power(self._mw_power)

        self._sc_device.camera.StartGrabbingMax(self._sc_device._num_img)

        # Cam triggered by MW, measurement starts with an initiate single sweep instruction
        # MW dwell time must be longer than exposure time
        self._mw_device._command_wait('SOUR1:LIST:TRIG:EXEC')
      
        output = self._sc_device.get_counter()
        
        self._WF_data[:,:,:] = self._WF_data[:,:,:] + output
        
        #find the PL data at the center of the camara view and output
        temp = output[math.ceil(0.5*output.shape[0]), math.ceil(0.5*output.shape[1]),:]
        counts = temp

        return False, counts

    def close_odmr(self):
        """ Close the odmr and clean up afterwards.     

        @return int: error code (0:OK, -1:error)
        """

        # self._sc_device.stop_measurement()
        self._pulser.pulser_off()
        self._mw_device.off()

        return self._sc_device.close_counter()

    def close_odmr_clock(self):
        """ Close the odmr and clean up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        # self._sc_device.stop_measurement()

        return 0

    def get_odmr_channels(self):
        """ Return a list of channel names.

        @return list(str): channels recorded during ODMR measurement
        """
        return ['APD0']
    
    ### ----------- Microwave interface commands -----------

    def trigger(self):

        return self._mw_device.trigger()

    def off(self):
        """
        Switches off any microwave output.
        Must return AFTER the device is actually stopped.

        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.off()

    def get_status(self):
        """
        Gets the current status of the MW source, i.e. the mode (cw, list or sweep) and
        the output state (stopped, running)

        @return str, bool: mode ['cw', 'list', 'sweep'], is_running [True, False]
        """
        return self._mw_device.get_status()

    def get_power(self):
        """
        Gets the microwave output power for the currently active mode.

        @return float: the output power in dBm
        """
        return self._mw_device.get_power()

    def set_power(self, power=None):
        """ Sets the microwave source in CW mode, and sets the MW power.
        Method ignores whether the output is on or off

        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.set_power(power)

    def get_frequency(self):
        """
        Gets the frequency of the microwave output.
        Returns single float value if the device is in cw mode.
        Returns list like [start, stop, step] if the device is in sweep mode.
        Returns list of frequencies if the device is in list mode.

        @return [float, list]: frequency(s) currently set for this device in Hz
        """
        return self._mw_device.get_frequency()

    def set_frequency(self, frequency=None):
        """ Sets the microwave source in CW mode, and sets the MW frequency.
        Method ignores whether the output is on or off
        
        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.set_frequency(frequency)
        
    def cw_on(self):
        """
        Switches on cw microwave output.
        Must return AFTER the device is actually running.

        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.cw_on()

    def set_cw(self, frequency=None, power=None):
        """
        Configures the device for cw-mode and optionally sets frequency and/or power

        @param float frequency: frequency to set in Hz
        @param float power: power to set in dBm

        @return tuple(float, float, str): with the relation
            current frequency in Hz,
            current power in dBm,
            current mode
        """
        return self._mw_device.set_cw(frequency=frequency, power=power)

    def list_on(self):
        """
        Switches on the list mode microwave output.
        Must return AFTER the device is actually running.

        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.list_on()

    def set_list(self, frequency=None, power=None, trig_mode=None):
        """
        Configures the device for list-mode and optionally sets frequencies and/or power

        @param list frequency: list of frequencies in Hz
        @param float power: MW power of the frequency list in dBm

        @return list, float, str: current frequencies in Hz, current power in dBm, current mode
        """
        return self._mw_device.set_list(frequency=frequency, power=power, mw_trigger_mode = trig_mode)

    def reset_listpos(self):
        """
        Reset of MW list mode position to start (first frequency step)

        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.reset_listpos()

    def sweep_on(self):
        """ Switches on the sweep mode.

        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.sweep_on()

    def set_sweep(self, start=None, stop=None, step=None, power=None):
        """
        Configures the device for sweep-mode and optionally sets frequency start/stop/step
        and/or power

        @return float, float, float, float, str: current start frequency in Hz,
                                                 current stop frequency in Hz,
                                                 current frequency step in Hz,
                                                 current power in dBm,
                                                 current mode
        """
        return self._mw_device.set_sweep(start=start, stop=stop, step=step,
                                         power=power)

    def reset_sweeppos(self):
        """
        Reset of MW sweep mode position to start (start frequency)

        @return int: error code (0:OK, -1:error)
        """
        return self._mw_device.reset_sweeppos()

    def set_ext_trigger(self, pol, timing):
        """ Set the external trigger for this device with proper polarization.

        @param TriggerEdge pol: polarisation of the trigger (basically rising edge or falling edge)
        @param timing: estimated time between triggers

        @return object: current trigger polarity [TriggerEdge.RISING, TriggerEdge.FALLING]
        """

        #Set trigger to Falling edge

        return self._mw_device.set_ext_trigger(pol=TriggerEdge.FALLING, timing=timing)

    def get_limits(self):
        """ Return the device-specific limits in a nested dictionary.

          @return MicrowaveLimits: Microwave limits object
        """
        return self._mw_device.get_limits()

    @property
    def lock_in_active(self):
        return self._lock_in_active

    @lock_in_active.setter
    def lock_in_active(self, val):
        if not isinstance(val, bool):
            self.log.error('lock_in_active has to be boolean.')
        else:
            self._lock_in_active = val
            if self._lock_in_active:
                self.log.warn('Lock-In is not implemented')
    
    @property
    def oversampling(self):
        return self._oversampling

    @oversampling.setter
    def oversampling(self, val):
        if not isinstance(val, (int, float)):
            self.log.error('oversampling has to be int of float.')
        else:
            self._oversampling = int(val)


