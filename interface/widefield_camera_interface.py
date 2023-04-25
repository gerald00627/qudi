# -*- coding: utf-8 -*-

"""
This file contains the Qudi Interface for a camera.


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

from core.interface import abstract_interface_method
from core.meta import InterfaceMetaclass


class WidefieldCameraInterface(metaclass=InterfaceMetaclass):
    """ This interface is used to manage and visualize a simple camera
    """

    @abstract_interface_method
    def get_limits(self):
        """ Get camera limits
        """
        pass

    @abstract_interface_method
    def get_channel_limits(self):
        """ Get camera limits
        """
        pass

    @abstract_interface_method
    def set_gpio_channel(self, properties):
        """ Set properties for input and output GPIO channels
        """
        pass

    @abstract_interface_method
    def grab(self, nframes):
        """ Grab a number of images, using current camera settings
        """
        pass

    @abstract_interface_method
    def set_plot_pixel(self, plot_pixel):
        """ Set the exposure time in seconds

        @param float time: desired new exposure time

        @return float: setted new exposure time
        """
        pass

    @abstract_interface_method
    def get_plot_pixel(self):
        """ Get the plot pixel coordinates

        @return tuple: plot pixel
        """
        pass

    @abstract_interface_method
    def set_camera_parameters(self, camera_params):
        """ Set the camera parameters
        
        @return dict: dict of actual parameters that were set on the camera.
        """
        pass

    @abstract_interface_method
    def set_trigger_mode(self, mode):
        """ Set the trigger mode (bool)

        @return bool: trigger mode
        """
        pass

    @abstract_interface_method
    def get_trigger_mode(self):
        """ Get the trigger mode (bool)

        @return bool: trigger mode
        """
        pass

    @abstract_interface_method
    def set_exposure_mode(self, mode):
        """ Set the exposure mode (string)

        @return string: exposure mode
        """
        pass

    @abstract_interface_method
    def get_exposure_mode(self):
        """ Get the exposure mode (string)

        @return string: exposure mode
        """
        pass

    @abstract_interface_method
    def begin_acquisition(self,num_imgs):
        """ Get the exposure mode (string)

        @return string: 
        """  
        pass 

    @abstract_interface_method
    def close_odmr(self):
        """
            Stops ODMR capture, discuonnects camera
        """
        pass