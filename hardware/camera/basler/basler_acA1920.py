# -*- coding: utf-8 -*-

"""
Hardware module for Basler ace camera acA1920 155um

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

from dataclasses import dataclass
import numpy as np
# import matplotlib.pyplot as plt
import time
from core.module import Base
from core.configoption import ConfigOption
from interface.camera_interface import CameraInterface
from qtpy import QtCore
from core.connector import Connector


from pypylon import pylon

class BaslerCam(Base, CameraInterface):

    _camera_name = 'Basler_ace_acA1920_155um'                                                     

    _support_live = ConfigOption('support_live', True)
    _resolution = ConfigOption('resolution', (1936, 1216)) 

    _live = False
    _acquiring = False
    _exposure = 1000
    _gain = 2
    _num_img = 1
    _trig_source = 'Line4'
    _pixel_format = 'Mono12'

    # setup signals
    sigUpdateDisplay = QtCore.Signal()
    sigAcquisitionFinished = QtCore.Signal()

    # self.signal_scan_lines_next.connect(self._scan_line, QtCore.Qt.QueuedConnection)

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        # Create an instance of the camera object 
        self.camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
        self.camera.Open()

        # self.camera.TriggerSelector = "FrameStart"
        # self.camera.TriggerSource = "Line1"
        self.camera.PixelFormat.SetValue(self._pixel_format)
    
        
        pass

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        
        """
        self.stop_acquisition()
        self.camera.Close()
        
    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print

        @return string: name for the camera
        """
        return self._camera_name

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


