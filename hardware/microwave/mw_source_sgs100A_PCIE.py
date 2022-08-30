# -*- coding: utf-8 -*-

"""
This file contains the Qudi hardware file to control R&S SMB100A or SMBV100A microwave device.

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

Parts of this file were developed from a PI3diamond module which is
Copyright (C) 2009 Helmut Rathgen <helmut.rathgen@gmail.com>

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""

"""
03.08.2022 Hanyi Lu
Change the methods for the frequency sweep since this instrument doesn't support sweep mode.

"""

import visa
import time
import numpy as np
import ctypes

from core.module import Base
from core.configoption import ConfigOption
from interface.microwave_interface import MicrowaveInterface
from interface.microwave_interface import MicrowaveLimits
from interface.microwave_interface import MicrowaveMode
from interface.microwave_interface import TriggerEdge


class MicrowaveSGS100A(Base, MicrowaveInterface):
    """ Hardware file to control a R&S SMBV100A microwave device.

    Example config for copy-paste:

    mw_source_sgs100A:
        module.Class: 'microwave.mw_source_sgs100A.MicrowaveSGS100A'
        tcpip_address: 'TCPIP0::172.16.27.118::inst0::INSTR'
        tcpip_timeout: 10

    """

    # visa address of the hardware : this can be over ethernet, the name is here for
    # backward compatibility
    _address = ConfigOption('tcpip_address', missing='error')
    _timeout = ConfigOption('tcpip_timeout', 10, missing='warn')

    # to limit the power to a lower value that the hardware can provide
    _max_power = ConfigOption('max_power', None)

    # Indicate how fast frequencies within a list or sweep mode can be changed:
    _FREQ_SWITCH_SPEED = 0.003  # Frequency switching speed in s (acc. to specs)

    def on_activate(self):
        """ Initialisation performed during activation of the module. """
        self._timeout = self._timeout * 1000
        # trying to load the visa connection to the module
        self.rm = visa.ResourceManager()

        self.final_freq_list = []
        self.mw_power = -30

        try:
            self._connection = self.rm.open_resource(self._address,
                                                          timeout=self._timeout)
        except:
            self.log.error('Could not connect to the address >>{}<<.'.format(self._address))
            raise

        self.model = self._connection.query('*IDN?').split(',')[1]
        self.log.info('MW {} initialised and connected.'.format(self.model))
        self._command_wait('*CLS')
        self._command_wait('*RST')
        return

    def on_deactivate(self):
        """ Cleanup performed during deactivation of the module. """
        self.rm.close()
        return

    def _command_wait(self, command_str):
        """
        Writes the command in command_str via ressource manager and waits until the device has finished
        processing it.

        @param command_str: The command to be written
        """
        self._connection.write(command_str)
        self._connection.write('*WAI')
        while int(float(self._connection.query('*OPC?'))) != 1:
            time.sleep(0.2)
        return

    def get_limits(self):
        """ Create an object containing parameter limits for this microwave source.

            @return MicrowaveLimits: device-specific parameter limits
        """
        limits = MicrowaveLimits()
        limits.supported_modes = (MicrowaveMode.CW)

        # values for SMBV100A
        limits.min_power = -145
        limits.max_power = -1

        limits.min_frequency = 9e3
        limits.max_frequency = 6e9

        if self.model == 'SMB100A':
            limits.max_frequency = 3.2e9

        limits.cw_minstep = 0.1
        limits.cw_maxstep = limits.max_frequency - limits.min_frequency
        limits.cw_maxentries = 10001 

        # in case a lower maximum is set in config file
        if self._max_power is not None and self._max_power < limits.max_power:
            limits.max_power = self._max_power

        return limits

    def off(self):
        """
        Switches off any microwave output.
        Must return AFTER the device is actually stopped.

        @return int: error code (0:OK, -1:error)
        """
        mode, is_running = self.get_status()
        if not is_running:
            return 0

        self._connection.write('OUTP:STAT OFF')
        self._connection.write('*WAI')
        while int(float(self._connection.query('OUTP:STAT?'))) != 0:
            time.sleep(0.2)
        return 0

    def get_status(self):
        """
        Gets the current status of the MW source, i.e. the mode (cw, list or sweep) and
        the output state (stopped, running)

        @return str, bool: mode ['cw', 'list', 'sweep'], is_running [True, False]
        """
        is_running = bool(int(float(self._connection.query('OUTP:STAT?'))))
        mode = self._connection.query(':FREQ:MODE?').strip('\n').lower()
        if mode == 'swe':
            mode = 'sweep'
        return mode, is_running

    def get_power(self):
        """
        Gets the microwave output power.

        @return float: the power set at the device in dBm
        """
        # This case works for cw AND sweep mode
        return float(self._connection.query(':POW?'))

    def get_frequency(self):
        """
        Gets the frequency of the microwave output.
        Returns single float value if the device is in cw mode.
        Returns list like [start, stop, step] if the device is in sweep mode.
        Returns list of frequencies if the device is in list mode.

        @return [float, list]: frequency(s) currently set for this device in Hz
        """
        mode, is_running = self.get_status()
        if 'cw' in mode:
            return_val = float(self._connection.query(':FREQ?'))
        else:
            self._command_wait(':FREQ:MODE CW')
            return_val = float(self._connection.query(':FREQ?'))
        return return_val

    def cw_on(self):
        """
        Switches on cw microwave output.
        Must return AFTER the device is actually running.

        @return int: error code (0:OK, -1:error)
        """
        current_mode, is_running = self.get_status()
        if is_running:
            if current_mode == 'cw':
                return 0
            else:
                self.off()

        if current_mode != 'cw':
            self._command_wait(':FREQ:MODE CW')

        self._connection.write(':OUTP:STAT ON')
        self._connection.write('*WAI')
        dummy, is_running = self.get_status()
        while not is_running:
            time.sleep(0.2)
            dummy, is_running = self.get_status()
        return 0

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
        mode, is_running = self.get_status()
        if is_running:
            self.off()

        # Activate CW mode
        if mode != 'cw':
            self._command_wait(':FREQ:MODE CW')

        # Set CW frequency
        if frequency is not None:
            self._command_wait(':FREQ {0:f}'.format(frequency))

        # Set CW power
        if power is not None:
            self._command_wait(':POW {0:f}'.format(power))

        # Return actually set values
        mode, dummy = self.get_status()
        actual_freq = self.get_frequency()
        actual_power = self.get_power()
        return actual_freq, actual_power, mode

    def list_on(self):
        """ Switches on the list mode.

        @return int: error code (1: ready, 0:not ready, -1:error)
        """
        self.log.error('List mode not available for this microwave hardware!')
        return -1

    def set_list(self, freq=None, power=None):
        """ 
        There is no list mode for SGS100A

        @param list freq: list of frequencies in Hz
        @param float power: MW power of the frequency list in dBm

        """
        self.log.error('List mode not available for this microwave hardware!')
        mode, dummy = self.get_status()
        return self.get_frequency(), self.get_power(), mode

    def reset_listpos(self,frequency=None,power=None):
        """ Reset of MW List Mode position to start from first given frequency

        @return int: error code (0:OK, -1:error)
        """
        self.log.error('List mode not available for this microwave hardware!')
        return -1


    def sweep_on(self):
        """ 03.08.2022 @Hanyi Lu
        Method is modified in accordance with the ODMR logic for this instrument
        """
        self.log.error('Sweep mode not available for this microwave hardware!')
        return -1


    def set_sweep(self, start=None, stop=None, step=None, power=None):
        """ 03.08.2022 @Hanyi Lu
        Method is modified in accordance with the ODMR logic for this instrument
        """

        self.log.error('Sweep mode not available for this microwave hardware!')
        mode, dummy = self.get_status()
        return self.get_frequency(), self.get_power(), mode

    def reset_sweeppos(self,frequency=None,power=None):
        """
        Reset of MW sweep mode position to start (start frequency)

        @return int: error code (0:OK, -1:error)
        """
        self.log.error('Sweep mode not available for this microwave hardware!')
        return -1

    def set_ext_trigger(self, pol, timing):
        """ Set the external trigger for this device with proper polarization.

        @param TriggerEdge pol: polarisation of the trigger (basically rising edge or falling edge)
        @param float timing: estimated time between triggers

        @return object, float: current trigger polarity [TriggerEdge.RISING, TriggerEdge.FALLING],
            trigger timing
        """
        mode, is_running = self.get_status()
        if is_running:
            self.off()

        if pol == TriggerEdge.RISING:
            edge = 'POS'
        elif pol == TriggerEdge.FALLING:
            edge = 'NEG'
        else:
            self.log.warning('No valid trigger polarity passed to microwave hardware module.')
            edge = None

        if edge is not None:
            self._command_wait('PULM:TRIG1:EXT:SLOP {0}'.format(edge))
            self._command_wait(':SWEep:FREQuency:DWELl {}'.format(timing))

        polarity = self._connection.query('PULM:TRIG1:EXT:SLOP?')
        if 'NEG' in polarity:
            return TriggerEdge.FALLING, timing
        else:
            return TriggerEdge.RISING, timing

    def trigger(self):
        """ Trigger the next element in the list or sweep mode programmatically.

        @return int: error code (0:OK, -1:error)

        Ensure that the Frequency was set AFTER the function returns, or give
        the function at least a save waiting time.
        """

        # WARNING:
        # The manual trigger functionality was not tested for this device!
        # Might not work well! Please check that!

        self._connection.write('*TRG')
        time.sleep(self._FREQ_SWITCH_SPEED)  # that is the switching speed
        return 0

    def set_cw_freq_PCIE(self,index=None):
        """03.09 @Hanyi Lu This specific method is added to work with the 
        odmr_counter_microwave_interfuse_SGS100A.py
        """
        try:
            self._connection.write(':FREQ {0:f}'.format(self.final_freq_list[index]))
        except:
            self.log.error('No index frequencies available')
            raise
        time.sleep(self._FREQ_SWITCH_SPEED)  # that is the switching speed
        return 0

    def set_cw_sweep(self, frequency=None, power=None):
        """ 

        @param list freq: list of frequencies in Hz
        @param float power: MW power of the frequency list in dBm

        """
        """
        Configures the device for cw-mode and optionally sets frequency and/or power

        @param float frequency: frequency to set in Hz
        @param float power: power to set in dBm

        @return tuple(float, float, str): with the relation
            current frequency in Hz,
            current power in dBm,
            current mode
        """
        mode, is_running = self.get_status()
        if is_running:
            self.off()

        self.final_freq_list = frequency
        self.mw_power = power

        # Activate CW mode
        if mode != 'cw':
            self._command_wait(':FREQ:MODE CW')

        # Set CW frequency
        if frequency is not None:
            self._command_wait(':FREQ {0:f}'.format(frequency[0]))

        # Set CW power
        if power is not None:
            self._command_wait(':POW {0:f}'.format(power))

        # self.set_ext_trigger()

        # Return actually set values
        mode, dummy = self.get_status()
        actual_freq = frequency
        actual_power = self.get_power()
        return actual_freq, actual_power, mode
