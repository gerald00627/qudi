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

# from interface.odmr_counter_interface import ODMRCounterInterface
from interface.slow_counter_interface import SlowCounterInterface
# from interface.slow_counter_interface import SlowCounterConstraints
# from interface.slow_counter_interface import CountingMode

from qtpy import QtCore



# class CameraBasler(Base, SlowCounterInterface, ODMRCounterInterface):
class CameraBasler(Base, CameraInterface, SlowCounterInterface):
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
    _exposure = 15000
    _num_img = 10
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

        pass

    def get_name(self):
        
        return self._camera_ID

    def get_size(self):
        """ Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        return self._resolution

    def support_live_acquisition(self):
        """ Return whether or not the camera can take care of live acquisition

        @return bool: True if supported, False if not
        """
        return self._support_live

    def start_live_acquisition(self):
        """ Start a continuous acquisition

        @return bool: Success ?
        """
        
        if self._support_live:
            self._live = True
            self._acquiring = False
   
        self.camera.StartGrabbingMax(self._num_img)
        self._acquiring = self.camera.IsGrabbing()
        self.grabResult = self.camera.RetrieveResult(100, pylon.TimeoutHandling_ThrowException)
                    
        if self._support_live:
            self._live = False
            self._acquiring = False

    def start_single_acquisition(self):
        """ Start a single acquisition

        @return bool: Success ?
        """
        self.camera.StartGrabbingMax(self._num_img)

        if self._live:
            return False
        else:
            # Wait for image and retrieve. 5000ms timeout. 
            self._acquiring = self.camera.IsGrabbing()
            self.grabResult = self.camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
            if self.grabResult.GrabSucceeded():
                # time.sleep(float(self._exposure+10/1000))
                self._acquiring = False
                return True
            else:
                print("Error: ", self.grabResult.ErrorCode, self.grabResult.ErrorDescription)
                return False
    
    def stop_acquisition(self):
        """ Stop/abort live or single acquisition

        @return bool: Success ?
        """

        self.camera.StopGrabbing()
        self._live = False
        self._acquiring = False
        
    def get_acquired_data(self):
        """ Return an array of last acquired image.

        @return numpy array: image data in format [[row],[row]...]

        Each pixel might be a float, integer or sub pixels
        """
        data = self.grabResult.Array
        # print data.shape
        
        return data

        # data = np.random.random(self._resolution)*self._exposure*self._gain
        # return data.transpose()

    def set_exposure(self, exposure):
        """ Set the exposure time in seconds

        @param float time: desired new exposure time

        @return float: setted new exposure time
        """
        self._exposure = exposure
        return self._exposure

    def get_exposure(self):
        """ Get the exposure time in seconds

        @return float exposure time
        """
        self._exposure = self.camera.ExposureTime.GetValue()
        return self._exposure

    def set_gain(self, gain):
        """ Set the gain

        @param float gain: desired new gain

        @return float: new exposure gain
        """
        self._gain = gain
        return self._gain

    def get_gain(self):
        """ Get the gain

        @return float: exposure gain
        """
        self._gain = self.camera.Gain.GetValue()

        return self._gain


    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?

        @return bool: ready ?
        """
        return not (self._live or self._acquiring)

    def get_offset(self):
        """ Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        # self._image_offset = (self.camera.OffsetX.GetValue(), self.camera.OffsetY.GetValue())
        # return self._image_offset

        pass

    def get_pixel_format(self):
        """ Get values can each pixel return ("Mono8", "Mono12", etc.)

        @return string: new pixel format
        """ 
        # self._pixel_format = self.camera.PixelFormat.GetValue()
        # return self._pixel_format

        pass

    def set_pixel_format(self, pixel_format):
        """ Set values can each pixel return ("Mono8", "Mono12", etc.)

        @return string: new pixel format
        """ 
        # if pixel_format in self.limits["pixel_formats"]:
        #     try:
        #         self.camera.PixelFormat.SetValue(pixel_format)
        #         self._pixel_format = self.get_pixel_format()
        #     except:
        #         self.log.warn("Could not reset camera Pixel Format")

        pass
            
    def set_size(self, image_size):
        """ Set the height and width of the exposure in pixels
        
        @return tuple: Actual Size (width, height)
        """
        # width_min = self.limits["image_width"][0]
        # width_max = self.limits["image_width"][1]
        # width_inc = self.limits["image_width"][2]

        # width = width_inc * (in_range(image_size[0], width_min, width_max) // width_inc)

        # if width < width_min:
        #     width = width_min
        # elif width > width_max:
        #     width = width_max

        # height_min = self.limits["image_height"][0]
        # height_max = self.limits["image_height"][1]
        # height_inc = self.limits["image_height"][2]

        # height = height_inc * (in_range(image_size[1], height_min, height_max) // height_inc)

        # if height < height_min:
        #     height = height_min
        # elif height > height_max:
        #     height = height_max
        
        # self.camera.Width.SetValue(width)
        # self.camera.Height.SetValue(height)

        # self._image_size = self.get_size()

        # self.limits = self.get_limits()

        pass


######################################################################################
########## SlowCounter Interface Implementation BEGIN ################################
######################################################################################
    
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
        """ Set up camera for hardware triggering 
        @return int: error code (0:OK, -1:error)
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
        
        # line 3 needs to be output, exposure active and inverted line. for MW trig cam


        return 0

    def get_counter_channels(self):
        return [1]

    def get_constraints(self):
        """ Get camera parameters
        """
        width = self.camera.Width.GetValue()
        height = self.camera.Height.GetValue()
        return width, height

    def get_counter(self, samples=None):
        """ Returns an array of PL from the camera
        """
    
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
        return imgs

    def close_counter(self):
        """ Closes the counter and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        # self.camera.Close()
        return 0

    def close_clock(self):
        """ Closes the clock and cleans up afterwards.

        @return int: error code (0:OK, -1:error)
        """
        return 0

    ##### ODMRCounterInterface Interface Implementation BEGIN ######

    # def set_up_odmr_clock(self, clock_frequency=None, clock_channel=None):
    #     """ Configures the hardware clock of the NiDAQ card to give the timing.

    #     @param float clock_frequency: if defined, this sets the frequency of the
    #                                   clock
    #     @param str clock_channel: if defined, this is the physical channel of
    #                               the clock

    #     @return int: error code (0:OK, -1:error)
    #     """
    #     return 0

    # def set_up_odmr(self, 
    #                 counter_channel=None, 
    #                 photon_source=None,
    #                 clock_channel=None, 
    #                 odmr_trigger_channel=None):
    #     """ Configures the actual counter with a given clock.

    #     @param str counter_channel: if defined, this is the physical channel of
    #                                 the counter
    #     @param str photon_source: if defined, this is the physical channel where
    #                               the photons are to count from
    #     @param str clock_channel: if defined, this specifies the clock for the
    #                               counter
    #     @param str odmr_trigger_channel: if defined, this specifies the trigger
    #                                      output for the microwave

    #     @return int: error code (0:OK, -1:error)
    #     """
    #     return 0

    # def set_odmr_length(self, length=100):
    #     """Set up the trigger sequence for the ODMR and the triggered microwave.

    #     @param int length: length of microwave sweep in pixel

    #     @return int: error code (0:OK, -1:error)
    #     """
    #     return 0

    # def count_odmr(self, length = 100):
    #     """ Sweeps the microwave and returns the counts on that sweep.

    #     @param int length: length of microwave sweep in pixel

    #     @return (bool, float[]): tuple: was there an error, the photon counts per second
    #     """
    #     return 0

    # def close_odmr(self):
    #     """ Close the odmr and clean up afterwards.

    #     @return int: error code (0:OK, -1:error)
    #     """
    #     return 0

    # def close_odmr_clock(self):
    #     """ Close the odmr and clean up afterwards.

    #     @return int: error code (0:OK, -1:error)
    #     """
    #     return 0

    # def get_odmr_channels(self):
    #     """ Return a list of channel names.

    #     @return list(str): channels recorded during ODMR measurement
    #     """
    #     return [1]

    # def oversampling(self):
    #     pass

    # def lock_in_active(self):
    #     pass

    # def lock_in_active(self, val):
    #     pass