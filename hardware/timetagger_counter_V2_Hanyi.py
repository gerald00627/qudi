# -*- coding: utf-8 -*-

"""
This file contains the Qudi hardware module to use TimeTagger as a counter.

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

"""Modified by Hanyi Lu @04.07.2022
Start implementing the ODMRcounter interface for the sweep mode with timetagger
"""

import TimeTagger as tt
import time
import numpy as np
import re

from core.module import Base
from core.configoption import ConfigOption
from interface.slow_counter_interface import SlowCounterInterface
from interface.slow_counter_interface import SlowCounterConstraints
from interface.slow_counter_interface import CountingMode
from interface.odmr_counter_interface import ODMRCounterInterface


class TimeTaggerCounter(Base, SlowCounterInterface, ODMRCounterInterface):
    """ Using the TimeTagger as a slow counter.

    Example config for copy-paste:

    timetagger_slowcounter:
        module.Class: 'timetagger_counter.TimeTaggerCounter'
        timetagger_channel_apd_0: 0
        timetagger_channel_apd_1: 1
        timetagger_sum_channels: 2

    """

    _channel_apd_0 = ConfigOption('timetagger_channel_apd_0', missing='error')
    _channel_apd_1 = ConfigOption('timetagger_channel_apd_1', None, missing='warn')
    _sum_channels = ConfigOption('timetagger_sum_channels', False)
    _trigger_channel = ConfigOption('timetagger_channel_trigger', None, missing = 'warn')
    #Add the measurement type for the pulsed measurement option. The default is continuous 
    #measurement, and the default value is selected if no config was specified.
    _measure_type = ConfigOption('timetagger_measure_type', False)

    def on_activate(self):
        """ Start up TimeTagger interface
        """
        self._tagger = tt.createTimeTagger()
        self._count_frequency = 50  # Hz
        self._odmr_length = None
        self._line_length = None

        if self._sum_channels and self._channel_apd_1 is None:
            self.log.error('Cannot sum channels when only one apd channel given')

        ## self._mode can take 3 values:
        # 0: single channel, no summing
        # 1: single channel, summed over apd_0 and apd_1
        # 2: dual channel for apd_0 and apd_1
        if self._sum_channels:
            self._mode = 1
        elif self._channel_apd_1 is None:
            self._mode = 0
            self._channel_apd = self._channel_apd_0
        else:
            self._mode = 2

    def on_deactivate(self):
        """ Shut down the TimeTagger.
        """
        tt.freeTimeTagger(self._tagger)
        pass

    ###### SlowCounter Interface Implementation BEGIN ######

    def set_up_clock(self, clock_frequency=None, clock_channel=None):
        """ Configures the hardware clock of the TimeTagger for timing

        @param float clock_frequency: if defined, this sets the frequency of
                                      the clock
        @param string clock_channel: if defined, this is the physical channel
                                     of the clock

        @return int: error code (0:OK, -1:error)
        """

        self._count_frequency = clock_frequency
        return 0

    def set_up_counter(self,
                       counter_channels=None,
                       sources=None,
                       clock_channel=None,
                       counter_buffer=None):
        """ Configures the actual counter with a given clock.

        @param str counter_channel: optional, physical channel of the counter
        @param str photon_source: optional, physical channel where the photons
                                  are to count from
        @param str counter_channel2: optional, physical channel of the counter 2
        @param str photon_source2: optional, second physical channel where the
                                   photons are to count from
        @param str clock_channel: optional, specifies the clock channel for the
                                  counter
        @param int counter_buffer: optional, a buffer of specified integer
                                   length, where in each bin the count numbers
                                   are saved.

        @return int: error code (0:OK, -1:error)
        """

        # currently, parameters passed to this function are ignored -- the channels used and clock frequency are
        # set at startup
        if self._mode == 1:
            channel_combined = tt.Combiner(self._tagger, channels = [self._channel_apd_0, self._channel_apd_1])
            self._channel_apd = channel_combined.getChannel()

            self.counter = tt.Counter(
                self._tagger,
                channels=[self._channel_apd],
                binwidth=int((1 / self._count_frequency) * 1e12),
                n_values=1
            )
        elif self._mode == 2:
            self.counter0 = tt.Counter(
                self._tagger,
                channels=[self._channel_apd_0],
                binwidth=int((1 / self._count_frequency) * 1e12),
                n_values=1
            )

            self.counter1 = tt.Counter(
                self._tagger,
                channels=[self._channel_apd_1],
                binwidth=int((1 / self._count_frequency) * 1e12),
                n_values=1
            )
        else:
            self._channel_apd = self._channel_apd_0
            self.counter = tt.Counter(
                self._tagger,
                channels=[self._channel_apd],
                binwidth=int((1 / self._count_frequency) * 1e12),
                n_values=1
            )

        self.log.info('set up counter with {0}'.format(self._count_frequency))
        return 0

    def get_counter_channels(self):
        if self._mode < 2:
            return [self._channel_apd]
        else:
            return [self._channel_apd_0, self._channel_apd_1]

    def get_constraints(self):
        """ Get hardware limits the device

        @return SlowCounterConstraints: constraints class for slow counter

        FIXME: ask hardware for limits when module is loaded
        """
        constraints = SlowCounterConstraints()
        constraints.max_detectors = 2
        constraints.min_count_frequency = 1e-3
        constraints.max_count_frequency = 10e9
        constraints.counting_mode = [CountingMode.CONTINUOUS]
        return constraints

    def get_counter(self, samples=None):
        """ Returns the current counts per second of the counter.

        @param int samples: if defined, number of samples to read in one go

        @return numpy.array(uint32): the photon counts per second
        """

        time.sleep(2 / self._count_frequency)
        if self._mode < 2:
            return self.counter.getData() * self._count_frequency
        else:
            return np.array([self.counter0.getData() * self._count_frequency,
                             self.counter1.getData() * self._count_frequency])

    def close_counter(self):
        """ Closes the counter and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        self._tagger.reset()
        return 0

    def close_clock(self):
        """ Closes the clock and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return 0

    ###### SlowCounter Interface Implementation END ######

    ###### ODMRCounterInterface Interface Implementation BEGIN ######

    def set_up_odmr_clock(self, clock_frequency=None, clock_channel=None):
        """ Configures the hardware clock of the NiDAQ card to give the timing.

        @param float clock_frequency: if defined, this sets the frequency of the
                                      clock
        @param str clock_channel: if defined, this is the physical channel of
                                  the clock

        @return int: error code (0:OK, -1:error)
        """
        return self.set_up_clock(
        clock_frequency=clock_frequency,
        clock_channel=clock_channel)

    def set_up_odmr(self, 
                    counter_channel=None, 
                    photon_source=None,
                    clock_channel=None, 
                    odmr_trigger_channel=None):
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

        # currently, parameters passed to this function are ignored -- the channels used and clock frequency are
        # set at startup
        
        # Hanyi Lu @04.07.2022. 
        # It seems that the combination of two APDs are not necessary so here
        # I am not including the options for different APD modes.

        # Hanyi Lu @04.13.2022
        #The counters here are bypassed. The real one would be called in count_odmr

        # if self._trigger_channel is None:
        #     #Setting up bin counter
        #     self.counter = tt.Counter(
        #         self._tagger,
        #         channels=[self._channel_apd_0],
        #         binwidth=int((1 / self._count_frequency) * 1e12),
        #         n_values=1
        #     )
        # else:
        #     #Setting up pulsed counter
        #     self.pulsed = tt.CounterBetweenMarkers(
        #         self._tagger,
        #         channels=[self._channel_apd_0],
        #         begin_channel = [self._trigger_channel],
        #         end_channel = [self._trigger_channel],
        #         n_values=1 #not sure if this is the right config, need to check.
        #     )
        # self.log.info('set up counter with {0}'.format(self._count_frequency))
        return 0

    def set_odmr_length(self, length=100):
        """Set up the trigger sequence for the ODMR and the triggered microwave.

        @param int length: length of microwave sweep in pixel

        @return int: error code (0:OK, -1:error)
        """
        self._odmr_length = length
        return 0

    def count_odmr(self, length = 100):
        """ Sweeps the microwave and returns the counts on that sweep.

        @param int length: length of microwave sweep in pixel

        @return (bool, float[]): tuple: was there an error, the photon counts per second
        """
        #Hanyi Lu @2022.04.30
        #Add the component for the pulsed ESR measurement
        #The counter setup scheme is similar to the continuous ESR
        if self._measure_type == 'pulsed':
            return 0
        else:
            #Hanyi Lu @05.01.2022
            #Just implemented the external trigger functionality for the SMB100B
            #MW source, and therefore the synchronization of the frequency sweep
            #could now be implemented using external trigger with pulse sequence.

            self.ctscounter = tt.CountBetweenMarkers(
                self._tagger,
                click_channel=self._channel_apd_0,
                begin_channel=self._trigger_channel,
                end_channel=self._trigger_channel,
                n_values=length
            )

            try:
                # prepare array to return data
                all_data = np.full((len(self.get_odmr_channels()), length),
                                    222,
                                    dtype=np.float64)

                self.ctscounter.waitUntilFinished()

                all_data = self.ctscounter.getData()
                return False, all_data
            except:
                self.log.exception('Error while counting for ODMR.')
                return True, np.full((len(self.get_odmr_channels()), 1), [-1.])

    def close_odmr(self):
        """ Close the odmr and clean up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return 0

    def close_odmr_clock(self):
        """ Close the odmr and clean up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return 0

    def get_odmr_channels(self):
        """ Return a list of channel names.

        @return list(str): channels recorded during ODMR measurement
        """
        return [self._channel_apd_0]

    def oversampling(self):
        pass


    def lock_in_active(self):
        pass

    def lock_in_active(self, val):
        pass