# -*- coding: utf-8 -*-

"""
Written by Hanyi Lu @2022.06.08

Basler implementation for camera_interface.

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

from pypylon import pylon

import re
import numpy as np
import time
from core.module import Base
from core.configoption import ConfigOption
from interface.odmr_counter_interface import ODMRCounterInterface
from interface.slow_counter_interface import SlowCounterInterface
from interface.slow_counter_interface import SlowCounterConstraints
from interface.slow_counter_interface import CountingMode


class CameraBasler(Base, SlowCounterInterface, ODMRCounterInterface):
    """ Basler hardware for camera interface

    Example config for copy-paste:

    cameraBasler:
        module.Class: 'camera.Basler_camera.CameraBasler'
        camera_ID : 'acA1920-155um'
        camera_Index: '0'
        image_Format: 'Mono12p'
        input_line: 'Line4'
        output_line: 'Line3'
        num_images: 100
    """

    _camera_ID = ConfigOption('camera_ID', True)
    _camera_index = ConfigOption('camera_Index', True)
    _input_line = ConfigOption('input_line', True)
    _output_line = ConfigOption('output_line', True)
    _image_format = ConfigOption('image_Format',True)
    _num_images = ConfigOption('num_images',True)


    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._camera = []
        self._camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
        self._camera.Open()

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self._camera.Close()
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
        return 0

    def get_counter_channels(self):
        return [1]

    def get_constraints(self):
        """ Get camera parameters
        """
        width = self._camera.Width.GetValue()
        height = self._camera.Height.GetValue()
        return width, height

    def get_counter(self, samples=None):
        """ Returns an array of PL from the camera
        """
        self._camera.StartGrabbingMax(self._num_images)
        while self._camera.IsGrabbing():
            output = self._camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
            if output.GrabSucceeded():
                img = output.Array
        return img

    def close_counter(self):
        """ Closes the counter and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        self._camera.Close()
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
        return 0

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
        return 0

    def set_odmr_length(self, length=100):
        """Set up the trigger sequence for the ODMR and the triggered microwave.

        @param int length: length of microwave sweep in pixel

        @return int: error code (0:OK, -1:error)
        """
        return 0

    def count_odmr(self, length = 100):
        """ Sweeps the microwave and returns the counts on that sweep.

        @param int length: length of microwave sweep in pixel

        @return (bool, float[]): tuple: was there an error, the photon counts per second
        """
        return 0

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
        return [1]

    def oversampling(self):
        pass

    def lock_in_active(self):
        pass

    def lock_in_active(self, val):
        pass