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
from core.util.helpers import in_range

from interface.camera_interface import CameraInterface
# from core.connector import Connector

# from interface.odmr_counter_interface import ODMRCounterInterface
from interface.widefield_camera_interface import WidefieldCameraInterface
# from interface.slow_counter_interface import SlowCounterConstraints
# from interface.slow_counter_interface import CountingMode

from qtpy import QtCore



# class CameraBasler(Base, SlowCounterInterface, ODMRCounterInterface):
class CameraBasler(Base, CameraInterface, WidefieldCameraInterface):
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
    _camera_ID = ConfigOption('camera_ID', '')
    _camera_index = ConfigOption('camera_index', 0)
    _input_line = ConfigOption('input_line', 4)
    _output_line = ConfigOption('output_line', 3)
    _pixel_format = ConfigOption('pixel_format','Mono12')
    _support_live = ConfigOption('support_live', True)
    _image_size = ConfigOption('image_size', (1936, 1216))
    _image_offset = ConfigOption('image_offset', (602, 812))
    _plot_pixel = ConfigOption('plot_pixel', (90, 90)) 
    _trigger_mode = ConfigOption('trigger_mode', False)
    _exposure_mode = ConfigOption('exposure_mode','Timed')
    _exposure = ConfigOption('exposure', 10e-3)
    
    # camera settings
    _gain = 1
    
    # bools for threadlock 
    _live = False
    _acquiring = False

    # setup signals for triggering GUI 
    sigUpdateDisplay = QtCore.Signal()
    sigAcquisitionFinished = QtCore.Signal()

    _gpio_input = {"LineMode": "Input",
                   "TriggerSelector": "FrameStart",
                   "TriggerDelay": 0,
                   "TriggerActivation": "RisingEdge",
                   "LineInverter": False}

    _gpio_output = {"LineMode": "Output",
                    "LineInverter": False,
                    "MinimumOutputPulse": 0,
                    "LineSource": "ExposureActive"}

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """

        try:
            self.camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
            self.camera.Open()
        except:
            self.log.error('Could not connect to the device {}'.format(self._camera_ID))


        self._camera_ID = self.camera.GetDeviceInfo().GetModelName()

        self.limits = self.get_limits()

        self._gpio_input["LineSelector"] = self._input_line
        self._gpio_output["LineSelector"] = self._output_line

        self._image_size = self.set_size(eval(self._image_size))
        self._exposure = self.set_exposure(self._exposure)
        self._gain = self.set_gain(self._gain)
        self._pixel_format = self.set_pixel_format(self._pixel_format)
        self._trigger_mode = self.set_trigger_mode(self._trigger_mode)
        self._exposure_mode = self.set_exposure_mode(self._exposure_mode)
        self._image_offset = self.set_offset(eval(self._image_offset))
        self._plot_pixel = eval(self._plot_pixel)

        self.set_gpio_channel(self._gpio_input)
        self.set_gpio_channel(self._gpio_output)

        self.input_channel_limits, self.output_channel_limits = self.get_channel_limits()


    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self.stop_acquisition()
        self.camera.Close()
        pass

    ######################################################################
    ####                Begin Camera Interface                        ####
    ###################################################################### 

    def get_name(self):
        """ Returns the camera ID from the class, without explicitly references device
        """
        return self._camera_ID

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
   
        self.camera.StartGrabbingMax(1)
        self._acquiring = self.camera.IsGrabbing()
        self.grabResult = self.camera.RetrieveResult(1000, pylon.TimeoutHandling_ThrowException)
                    
        if self._support_live:
            self._live = False
            self._acquiring = False

    def start_single_acquisition(self):
        """ Start a single acquisition

        @return bool: Success ?
        """
        self.camera.StartGrabbingMax(1)

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
        return data

    def get_offset(self):
        """ Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        self._image_offset = (self.camera.OffsetX.GetValue(), self.camera.OffsetY.GetValue())
        return self._image_offset

    def set_offset(self, image_offset):
        """ Set the OffsetX and Offset Y of the exposure in pixels
        
        @return tuple: Actual Offset (offsetX, offsetY)
        """
        offset_x_min = self.limits["offset_x"][0]
        offset_x_max = self.limits["offset_x"][1]
        offset_x_inc = self.limits["offset_x"][2]

        offset_x = offset_x_inc * (in_range(image_offset[0], offset_x_min, offset_x_max) // offset_x_inc)

        offset_y_min = self.limits["offset_y"][0]
        offset_y_max = self.limits["offset_y"][1]
        offset_y_inc = self.limits["offset_y"][2]

        offset_y = offset_y_inc * (in_range(image_offset[1], offset_y_min, offset_y_max) // offset_y_inc)
        
        self.camera.OffsetX.SetValue(offset_x)
        self.camera.OffsetY.SetValue(offset_y)

        self._image_offset = self.get_offset()

        self.limits = self.get_limits()

        return self._image_offset

    def get_size(self):
        """ Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        self._image_size = (self.camera.Width.GetValue(), self.camera.Height.GetValue())
        return self._image_size

    def set_size(self, image_size):
        """ Set the height and width of the exposure in pixels
        
        @return tuple: Actual Size (width, height)
        """
        width_min = self.limits["image_width"][0]
        width_max = self.limits["image_width"][1]
        width_inc = self.limits["image_width"][2]

        width = width_inc * (in_range(image_size[0], width_min, width_max) // width_inc)

        if width < width_min:
            width = width_min
        elif width > width_max:
            width = width_max

        height_min = self.limits["image_height"][0]
        height_max = self.limits["image_height"][1]
        height_inc = self.limits["image_height"][2]

        height = height_inc * (in_range(image_size[1], height_min, height_max) // height_inc)

        if height < height_min:
            height = height_min
        elif height > height_max:
            height = height_max
        
        self.camera.Width.SetValue(width)
        self.camera.Height.SetValue(height)

        self._image_size = self.get_size()

        self.limits = self.get_limits()

        return self._image_size

    def set_exposure(self, exposure):
        """ Set the exposure time in seconds

        @param float time: desired new exposure time

        @return float: setted new exposure time
        """
        if self._exposure_mode != "Timed":
            return 0.12345

        exposure_min = self.limits["exposure_time"][0]
        exposure_max = self.limits["exposure_time"][1]
        exposure_inc = self.limits["exposure_time"][2]
    
        new_exposure = exposure_inc * (in_range(exposure, exposure_min, exposure_max) // exposure_inc)

        if new_exposure < exposure_min:
            new_exposure = exposure_min
        
        elif new_exposure > exposure_max:
            new_exposure = exposure_max

        self.camera.ExposureTime.SetValue(new_exposure*1e6)

        self._exposure = self.get_exposure()

        return self._exposure

    def get_exposure(self):
        """ Get the exposure time in seconds

        @return float exposure time
        """
        self._exposure = self.camera.ExposureTime.GetValue()
        return self._exposure * 1e-6

    def set_gain(self, gain):
        """ Set the gain

        @param float gain: desired new gain

        @return float: new exposure gain
        """
        gain_min = self.limits["gain"][0]
        gain_max = self.limits["gain"][1]

        new_gain = in_range(gain, gain_min, gain_max)
        self.camera.Gain.SetValue(new_gain)

        self._gain = self.get_gain()
        return self._gain

    def get_gain(self):
        """ Get the gain

        @return float: exposure gain
        """
        self._gain = self.camera.Gain.GetValue()
        return self._gain

    def set_pixel_format(self, pixel_format):
        """ Set values can each pixel return ("Mono8", "Mono12", etc.)

        @return string: new pixel format
        """ 
        if pixel_format in self.limits["pixel_formats"]:
            try:
                self.camera.PixelFormat.SetValue(pixel_format)
                self._pixel_format = self.get_pixel_format()
            except:
                self.log.warn("Could not reset camera Pixel Format")
            

        return self._pixel_format

    def get_pixel_format(self):
        """ Get values can each pixel return ("Mono8", "Mono12", etc.)

        @return string: new pixel format
        """ 
        self._pixel_format = self.camera.PixelFormat.GetValue()
        return self._pixel_format


    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?

        @return bool: ready ?
        """
        return not (self._live or self._acquiring)

    ######################################################################
    ####                End Camera Interface                          ####
    ###################################################################### 

    ######################################################################
    ####                Start Widefield Camera Interface              ####
    ###################################################################### 

    def get_limits(self):
        """ Get camera limits
        """
        limits = dict()
        limits["gain"] = (self.camera.Gain.Min, self.camera.Gain.Max)
        limits["trigger_mode"] = (True, False)
        limits["exposure_modes"] = self.camera.ExposureMode.Symbolics
        if self.get_exposure_mode() == "Timed":
            limits["exposure_time"] = (self.camera.ExposureTime.Min * 1e-6, 
                                    self.camera.ExposureTime.Max * 1e-6, 
                                    self.camera.ExposureTime.GetInc() * 1e-6)
        else:
            limits["exposure_time"] = (0, 0, 0)
        limits["image_width"] = (self.camera.Width.Min, self.camera.Width.Max, self.camera.Width.GetInc())
        limits["image_height"] = (self.camera.Height.Min, self.camera.Height.Max, self.camera.Height.GetInc())
        limits["offset_x"] = (self.camera.OffsetX.Min, self.camera.OffsetX.Max, self.camera.OffsetX.GetInc())
        limits["offset_y"] = (self.camera.OffsetY.Min, self.camera.OffsetY.Max, self.camera.OffsetY.GetInc())
        limits["pixel_formats"] = self.camera.PixelFormat.Symbolics
        limits["plot_pixel_x"] = (0, self.camera.Width.GetValue())
        limits["plot_pixel_y"] = (0, self.camera.Height.GetValue())
        return limits
    
    def get_channel_limits(self):
        """ Get camera channel limits
        """
        input_channel_limits = dict()
        output_channel_limits = dict()

        self.set_gpio_channel({'LineSelector': self._input_line,
                               'LineMode': 'Input'})

        input_channel_limits['LineSelector'] = [self._input_line]
        input_channel_limits['TriggerSelectors'] = self.camera.TriggerSelector.Symbolics
        input_channel_limits['TriggerDelays'] = (self.camera.TriggerDelay.Min, self.camera.TriggerDelay.Max, self.camera.TriggerDelay.GetInc())
        input_channel_limits['TriggerActivations'] = self.camera.TriggerActivation.Symbolics

        self.set_gpio_channel({'LineSelector': self._output_line,
                               'LineMode': 'Output'})

        output_channel_limits['LineSelector'] = [self._output_line]
        output_channel_limits['MinimumOutputPulse'] = (self.camera.LineMinimumOutputPulseWidth.Min, self.camera.LineMinimumOutputPulseWidth.Max, self.camera.LineMinimumOutputPulseWidth.GetInc())
        output_channel_limits['LineSource'] = self.camera.LineSource.Symbolics

        return input_channel_limits, output_channel_limits

    def set_gpio_channel(self, properties):
        """ Set properties for input and output GPIO channels
        """

        self.camera.LineSelector.SetValue('{}'.format(properties['LineSelector']))
        self.camera.LineMode.SetValue(properties["LineMode"])

        if "LineSource" in properties:
            self.camera.LineSource.SetValue(properties["LineSource"])
        
        if "TriggerSelector" in properties:
            self.camera.TriggerSelector.SetValue(properties["TriggerSelector"])

        if "TriggerDelay" in properties:
            self.camera.TriggerDelay.SetValue(properties["TriggerDelay"])
    
        if "LineInverter" in properties:
            self.camera.LineInverter.SetValue(properties["LineInverter"])

        if "TriggerActivation" in properties:
            self.camera.TriggerActivation.SetValue(properties["TriggerActivation"])

        if "MinimumOutputPulse" in properties:
            self.camera.LineMinimumOutputPulseWidth.SetValue(properties["MinimumOutputPulse"])
 
    def begin_acquisition(self, num_imgs):
        """ Prepare camera to take images 
        """
        self.camera.StartGrabbingMax(num_imgs)

        return 

    def grab(self, nframes=0):
        """ Returns an array of PL from the camera
        """
    
        # initialize array for num_imgs = num_avgs

        width = self._image_size[0]
        height = self._image_size[1]
        imgs = np.zeros((height, width, nframes),dtype='float64')
        ind = 0

        error = False

        # self.camera.StartGrabbingMax(self._num_img)
        while self.camera.IsGrabbing():
            output = self.camera.RetrieveResult(200000, pylon.TimeoutHandling_ThrowException) # Camera exposure time must be less than retrieval timeout
            if output.GrabSucceeded():
                imgs[:,:,ind] += output.Array
                ind += 1
                # time.sleep(0.01)
            else:
                error = True
                    
        return error, imgs

    def set_plot_pixel(self, plot_pixel):
        """ 
        """
        plot_pixel_x_min = self.limits["plot_pixel_x"][0]
        plot_pixel_x_max = self.limits["plot_pixel_x"][1]

        plot_pixel_x = in_range(int(plot_pixel[0]), plot_pixel_x_min, plot_pixel_x_max)

        plot_pixel_y_min = self.limits["plot_pixel_y"][0]
        plot_pixel_y_max = self.limits["plot_pixel_y"][1]

        plot_pixel_y = in_range(int(plot_pixel[1]), plot_pixel_y_min, plot_pixel_y_max)

        self._plot_pixel = (plot_pixel_x, plot_pixel_y)
        return self._plot_pixel

    def get_plot_pixel(self):
        """ Get the plot pixel coordinates

        @return tuple: plot pixel
        """
        return self._plot_pixel

    def set_camera_parameters(self, camera_params):
        """ Set the camera parameters
        
        @return dict: dict of actual parameters that were set on the camera.
        """

        set_params = dict()

        if "exposure_time" in camera_params:
            set_params["exposure_time"] = self.set_exposure(camera_params["exposure_time"])

        if "trigger_mode" in camera_params:
            set_params["trigger_mode"] = self.set_trigger_mode(camera_params["trigger_mode"])

        if "exposure_mode" in camera_params:
            set_params["exposure_mode"] = self.set_exposure_mode(camera_params["exposure_mode"])

        if "gain" in camera_params:
            set_params["gain"] = self.set_gain(camera_params["gain"])

        if "image_size" in camera_params:
            set_params["image_size"] = self.set_size(camera_params["image_size"])

        if "image_offset" in camera_params:
            set_params["image_offset"] = self.set_offset(camera_params["image_offset"])

        if "pixel_format" in camera_params:
            set_params["pixel_format"] = self.set_pixel_format(camera_params["pixel_format"])

        if "plot_pixel" in camera_params:
            set_params["plot_pixel"] = self.set_plot_pixel(camera_params["plot_pixel"])

        limits = self.get_limits()

        return set_params, limits

    def set_trigger_mode(self, mode):
        """ Set the trigger mode (bool)

        @return bool: trigger mode
        """
        if mode:
            self.camera.TriggerMode.SetValue('On')
        else:
            self.camera.TriggerMode.SetValue('Off')

        self.limits = self.get_limits()

        self._trigger_mode = self.get_trigger_mode()
        return self._trigger_mode

    def get_trigger_mode(self):
        """ Get the trigger mode (bool)

        @return bool: trigger mode
        """
        string_mode = self.camera.TriggerMode.GetValue()

        if string_mode == 'On':
            self._trigger_mode = True
        else:
            self._trigger_mode = False

        return self._trigger_mode

    def set_exposure_mode(self, mode):
        """ Set the exposure mode (string)

        @return string: exposure mode
        """
        if mode in self.limits["exposure_modes"]:
            try:
                self.camera.ExposureMode.SetValue(mode)
                self._exposure_mode = self.get_exposure_mode()
            except:
                self.log.warn("Could not reset camera exposure mode")
            
        return self._exposure_mode

    def get_exposure_mode(self):
        """ Get the exposure mode (string)

        @return string: exposure mode
        """
        self._exposure_mode = self.camera.ExposureMode.GetValue()
        return self._exposure_mode
    
    def get_channel_parameters(self):
        """ Get camera channel limits
        """
        input_channel = dict()
        output_channel = dict()

        self.set_gpio_channel({'LineSelector': self._input_line,
                               'LineMode': 'Input'})

        input_channel['LineSelector'] = self._input_line
        input_channel['TriggerSelectors'] = self.camera.TriggerSelector.GetValue()
        input_channel['TriggerDelays'] = self.camera.TriggerDelay.GetValue()
        input_channel['TriggerActivations'] = self.camera.TriggerActivation.GetValue()
        input_channel['LineInverter'] = self.camera.LineInverter.GetValue()

        self.set_gpio_channel({'LineSelector': self._output_line,
                               'LineMode': 'Output'})

        output_channel['LineSelector'] = self._output_line
        output_channel['LineInverter'] = self.camera.LineInverter.GetValue()
        output_channel['MinimumOutputPulse'] = self.camera.LineMinimumOutputPulseWidth.GetValue()
        output_channel['LineSource'] = self.camera.LineSource.GetValue()

        return input_channel, output_channel

    def close_odmr(self):
        self.camera.Close()
        return

######################################################################
####                End Widefield Camera Interface                ####
###################################################################### 