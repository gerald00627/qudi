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

from interface.camera_interface import CameraInterface
# from core.connector import Connector
from interface.fast_counter_interface import FastCounterInterface

from qtpy import QtCore

class CameraBasler_FastCounter(Base, CameraInterface, FastCounterInterface):
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
    _camera_index = ConfigOption('camera_index', True)
    _input_line = ConfigOption('input_line', True)
    _output_line = ConfigOption('output_line', True)
    _pixel_format = ConfigOption('pixel_format',True)
    _support_live = ConfigOption('support_live', True)
    _resolution = ConfigOption('resolution', (1936, 1216)) 
    
    # camera settings
    _exposure = ConfigOption('exposure', 10000)
    _num_img = ConfigOption('num_images',50)
    _gain = 1
    
    # bools for threadlock 
    _live = False
    _acquiring = False

    # setup signals for triggering GUI 
    sigUpdateDisplay = QtCore.Signal()
    sigAcquisitionFinished = QtCore.Signal()

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self.camera = []
        self.camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
        self.camera.Open()

        self.camera.PixelFormat.SetValue(self._pixel_format)

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self.stop_acquisition()
        self.camera.Close()

        # if self.module_state() == 'locked':
        # self.pulsed.stop()
        # self.pulsed.clear()
        # self.pulsed = None


        pass

    # def get_name(self):
        
    #     return self._camera_ID

    # def get_size(self):
    #     """ Retrieve size of the image in pixel

    #     @return tuple: Size (width, height)
    #     """
    #     return self._resolution

    # def support_live_acquisition(self):
    #     """ Return whether or not the camera can take care of live acquisition

    #     @return bool: True if supported, False if not
    #     """
    #     return self._support_live

    # def start_live_acquisition(self):
    #     """ Start a continuous acquisition

    #     @return bool: Success ?
    #     """
        
    #     if self._support_live:
    #         self._live = True
    #         self._acquiring = False
   
    #     self.camera.StartGrabbingMax(self._num_img)
    #     self._acquiring = self.camera.IsGrabbing()
    #     self.grabResult = self.camera.RetrieveResult(100, pylon.TimeoutHandling_ThrowException)
                    
    #     if self._support_live:
    #         self._live = False
    #         self._acquiring = False

    # def start_single_acquisition(self):
    #     """ Start a single acquisition

    #     @return bool: Success ?
    #     """
    #     self.camera.StartGrabbingMax(self._num_img)

    #     if self._live:
    #         return False
    #     else:
    #         # Wait for image and retrieve. 5000ms timeout. 
    #         self._acquiring = self.camera.IsGrabbing()
    #         self.grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
    #         if self.grabResult.GrabSucceeded():
    #             # time.sleep(float(self._exposure+10/1000))
    #             self._acquiring = False
    #             return True
    #         else:
    #             print("Error: ", self.grabResult.ErrorCode, self.grabResult.ErrorDescription)
    #             return False
    
    # def stop_acquisition(self):
    #     """ Stop/abort live or single acquisition

    #     @return bool: Success ?
    #     """

    #     self.camera.StopGrabbing()
    #     self._live = False
    #     self._acquiring = False
        
    # def get_acquired_data(self):
    #     """ Return an array of last acquired image.

    #     @return numpy array: image data in format [[row],[row]...]

    #     Each pixel might be a float, integer or sub pixels
    #     """
    #     data = self.grabResult.Array
    #     # print data.shape
        
    #     return data

    #     # data = np.random.random(self._resolution)*self._exposure*self._gain
    #     # return data.transpose()

    # def set_exposure(self, exposure):
    #     """ Set the exposure time in seconds

    #     @param float time: desired new exposure time

    #     @return float: setted new exposure time
    #     """
    #     self._exposure = exposure
    #     return self._exposure

    # def get_exposure(self):
    #     """ Get the exposure time in seconds

    #     @return float exposure time
    #     """
    #     self._exposure = self.camera.ExposureTime.GetValue()
    #     return self._exposure

    # def set_gain(self, gain):
    #     """ Set the gain

    #     @param float gain: desired new gain

    #     @return float: new exposure gain
    #     """
    #     self._gain = gain
    #     return self._gain

    # def get_gain(self):
    #     """ Get the gain

    #     @return float: exposure gain
    #     """
    #     self._gain = self.camera.Gain.GetValue()

    #     return self._gain


    # def get_ready_state(self):
    #     """ Is the camera ready for an acquisition ?

    #     @return bool: ready ?
    #     """
    #     return not (self._live or self._acquiring)


######################################################################################
########## FastCounter Interface Implementation BEGIN ################################
######################################################################################
    
    def get_constraints(self):
        """ Get camera parameters
        """
        width = self.camera.Width.GetValue()
        height = self.camera.Height.GetValue()
        return width, height


    def configure(self, bin_width_s, record_length_s, number_of_gates=0):
        """ Configuration of the fast counter.

        @param float bin_width_s: Length of a single time bin in the time race histogram in seconds.
        @param float record_length_s: Total length of the timetrace/each single gate in seconds.
        @param int number_of_gates: optional, number of gates in the pulse sequence. Ignore for not gated counter.

        @return tuple(binwidth_s, record_length_s, number_of_gates):
                    binwidth_s: float the actual set binwidth in seconds
                    gate_length_s: the actual record length in seconds
                    number_of_gates: the number of gated, which are accepted, None if not-gated
        """

        # #Restarts to default settings
        # self.camera.UserSetSelector = 'Default'
        # self.camera.UserSetLoad.Execute()

        self.camera.LineSelector = 'Line4'
        self.camera.LineMode = 'Input'

        self.camera.TriggerSelector = 'FrameStart'
        self.camera.TriggerSource = self._input_line
        self.camera.TriggerMode = 'On'
        self.camera.TriggerActivation.Value = 'RisingEdge'

        return 0

    def get_status(self):
        """ Receives the current status of the Fast Counter and outputs it as
            return value.

        0 = unconfigured
        1 = idle
        2 = running
        3 = paused
        -1 = error state
        """
        return self.statusvar

    def start_measure(self):
        
            # initialize array for num_imgs = num_avgs

        width = self.get_constraints()[0]
        height = self.get_constraints()[1]
        imgs = np.zeros((height,width,self._num_img),dtype='float64')
        ind = 0

        # self.camera.StartGrabbingMax(self._num_img)
        while self.camera.IsGrabbing():
            output = self.camera.RetrieveResult(200000, pylon.TimeoutHandling_ThrowException) # Camera exposure time must be less than retrieval timeout
            if output.GrabSucceeded():
                imgs[:,:,ind] += output.Array
                ind += 1
                # imgs[:,:] += output.Array


        #       self.module_state.lock()
        # self.pulsed.clear()
        # self.pulsed.start()
        # self._tagger.sync()
        # self.statusvar = 2

        return imgs       

    def stop_measure(self):
        """ Stop the fast counter. """
        if self.module_state() == 'locked':
            self.pulsed.stop()
            self.module_state.unlock()
        self.statusvar = 1
        return 0

    def pause_measure(self):
        """ Pauses the current measurement.

        Fast counter must be initially in the run state to make it pause.
        """
        if self.module_state() == 'locked':
            self.pulsed.stop()
            self.statusvar = 3
        return 0

    def continue_measure(self):
        """ Continues the current measurement.

        If fast counter is in pause state, then fast counter will be continued.
        """
        if self.module_state() == 'locked':
            self.pulsed.start()
            self._tagger.sync()
            self.statusvar = 2
        return 0

    def is_gated(self):
        """ Check the gated counting possibility.

        Boolean return value indicates if the fast counter is a gated counter
        (TRUE) or not (FALSE).
        """
        return True

    def get_binwidth(self):
        """ Returns the width of a single timebin in the timetrace in seconds. """
        width_in_seconds = self._bin_width * 1e-9
        return width_in_seconds

    def get_data_trace(self):
        """ Polls the current timetrace data from the fast counter.

        @return numpy.array: 2 dimensional array of dtype = int64. This counter
                             is gated the the return array has the following
                             shape:
                                returnarray[gate_index, timebin_index]

        The binning, specified by calling configure() in forehand, must be taken
        care of in this hardware class. A possible overflow of the histogram
        bins must be caught here and taken care of.
        """
        info_dict = {'elapsed_sweeps': self.pulsed.getCounts(),
                     'elapsed_time': None}  
        return np.array(self.pulsed.getData(), dtype='int64'), info_dict
