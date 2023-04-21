# -*- coding: utf-8 -*-

"""
This file contains the Qudi Predefined Methods for sequence generator

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
from logic.pulsed.pulse_objects import PulseBlock, PulseBlockEnsemble, PulseSequence
from logic.pulsed.pulse_objects import PredefinedGeneratorBase
from core.util.helpers import csv_2_list

"""
General Pulse Creation Procedure:
=================================
- Create at first each PulseBlockElement object
- add all PulseBlockElement object to a list and combine them to a
  PulseBlock object.
- Create all needed PulseBlock object with that idea, that means
  PulseBlockElement objects which are grouped to PulseBlock objects.
- Create from the PulseBlock objects a PulseBlockEnsemble object.
- If needed and if possible, combine the created PulseBlockEnsemble objects
  to the highest instance together in a PulseSequence object.
"""


class BasicPredefinedGenerator(PredefinedGeneratorBase):
    """

    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    ################################################################################################
    #                             Generation methods for waveforms                                 #
    ################################################################################################
    
    # def generate_WF_laser_on(self, name='laser_on', length=3.0e-6):
    #     """ Generates Laser on.

    #     @param str name: Name of the PulseBlockEnsemble
    #     @param float length: laser duration in seconds

    #     @return object: the generated PulseBlockEnsemble object.
    #     """
    #     created_blocks = list()
    #     created_ensembles = list()
    #     created_sequences = list()

    #     # create the laser element
    #     laser_element = self._get_laser_element(length=length, increment=0)
    #     # Create block and append to created_blocks list
    #     laser_block = PulseBlock(name=name)
    #     laser_block.append(laser_element)
    #     created_blocks.append(laser_block)
    #     # Create block ensemble and append to created_ensembles list
    #     block_ensemble = PulseBlockEnsemble(name=name, rotating_frame=False)
    #     block_ensemble.append((laser_block.name, 0))
    #     created_ensembles.append(block_ensemble)
    #     return created_blocks, created_ensembles, created_sequences

    # def generate_WF_laser_mw_on(self, name='laser_mw_on', length=3.0e-6):
    #     """ General generation method for laser on and microwave on generation.

    #     @param string name: Name of the PulseBlockEnsemble to be generated
    #     @param float length: Length of the PulseBlockEnsemble in seconds

    #     @return object: the generated PulseBlockEnsemble object.
    #     """
    #     created_blocks = list()
    #     created_ensembles = list()
    #     created_sequences = list()

    #     # create the laser_mw element
    #     laser_mw_element = self._get_mw_laser_element(length=length,
    #                                                   increment=0,
    #                                                   amp=self.microwave1_amplitude,
    #                                                   freq=self.microwave1_frequency,
    #                                                   phase=0)
    #     # Create block and append to created_blocks list
    #     laser_mw_block = PulseBlock(name=name)
    #     laser_mw_block.append(laser_mw_element)
    #     created_blocks.append(laser_mw_block)
    #     # Create block ensemble and append to created_ensembles list
    #     block_ensemble = PulseBlockEnsemble(name=name, rotating_frame=False)
    #     block_ensemble.append((laser_mw_block.name, 0))
    #     created_ensembles.append(block_ensemble)
    #     return created_blocks, created_ensembles, created_sequences

    def generate_WF_rabi(self, name='rabiWF', tau_start=10.0e-9, tau_step=10.0e-9, num_of_points=40, reference=False):
        """

        """
        created_blocks = list()
        created_ensembles = list()
        created_sequences = list()

        # get tau array for measurement ticks
        tau_array = tau_start + np.arange(num_of_points) * tau_step
        
        # find how long to repeat pulses for. 
        exp_dur = self._get_camera_exposure() # s
        block_dur = self.laser_length+self.laser_delay+tau_array[-1] # sum of green+space+MW
        gap_dur = 10e-6 # gap at end after repeated pulses to pad out exposure time

        #calculate number of reps that can fit into exposure time
        pulse_reps = np.floor((exp_dur-gap_dur)/block_dur).astype(int)

        #sequence generator already does increments automatically of tau so just need to write a single camera pulse and tau block

        camera_trig_element = self._get_camera_trig_element(length = 5000e-9, increment=0)
        mw_wait_element = self._get_idle_element(length=tau_array[-2], increment=-tau_step)
        no_mw_wait_element = self._get_idle_element(length=tau_array[-1], increment=0)
        mw_element = self._get_mw1_element(length=tau_start,
                                          increment=tau_step,
                                          amp=self.microwave1_amplitude,
                                          freq=self.microwave1_frequency,
                                          phase=0)
        # laser_element = self._get_laser_gate_element(length=self.laser_length, increment=0)
        laser_element = self._get_laser_element(length=self.laser_length, increment=0)
        delay_element = self._get_delay_gate_element() # dur = laser delay dur = 300ns
        waiting_element = self._get_idle_element(length=self.wait_time,
                                                 increment=0) # dur = wait_time = 700ns

        #create pulseblock object
        rabi_block = PulseBlock(name=name)

        #append first camera triggerblock
        rabi_block.append(camera_trig_element)
        # for loop for adding n_pulse_reps of laser and mw pulses
        for i in range(pulse_reps):           
            rabi_block.append(mw_wait_element) # mw_wait_element + mw_element = tau_tot
            rabi_block.append(mw_element)
            rabi_block.append(laser_element)
            rabi_block.append(delay_element)
        # gap for padding exposure time
        rabi_block.append(waiting_element)

        if reference:
            rabi_block.append(camera_trig_element)
            for i in range(pulse_reps):        
                rabi_block.append(no_mw_wait_element) # dur = tau_tot
                rabi_block.append(laser_element)
                rabi_block.append(delay_element)
            # gap for padding exposure time
            rabi_block.append(waiting_element)
        
        created_blocks.append(rabi_block)
        
        # Create block ensemble
        block_ensemble = PulseBlockEnsemble(name=name, rotating_frame=False)
        block_ensemble.append((rabi_block.name, num_of_points - 1))

        # Create and append sync trigger block if needed
        self._add_trigger(created_blocks=created_blocks, block_ensemble=block_ensemble)

        # add metadata to invoke settings later on
        number_of_lasers = 2 * num_of_points if reference else num_of_points
        block_ensemble.measurement_information['number_of_curves'] = 2 if reference else 1
        block_ensemble.measurement_information['laser_ignore_list'] = list()
        block_ensemble.measurement_information['controlled_variable'] = tau_array
        block_ensemble.measurement_information['units'] = ('s', '')
        block_ensemble.measurement_information['labels'] = ('Tau<sub>pulse spacing</sub>', 'Signal')
        block_ensemble.measurement_information['number_of_lasers'] = number_of_lasers
        block_ensemble.measurement_information['counting_length'] = self._get_ensemble_count_length(
            ensemble=block_ensemble, created_blocks=created_blocks)

        # Append ensemble to created_ensembles list
        created_ensembles.append(block_ensemble)
        return created_blocks, created_ensembles, created_sequences

    def generate_WF_t1_3exponential(self, name='T1WFexp3', tau_start=1.0e-6, tau_end=1.0e-5,
                                num_of_points=10):

                                
        created_blocks = list()
        created_ensembles = list()
        created_sequences = list()

        # get tau array for measurement ticks
        if tau_start == 0.0:
            tau_array = np.geomspace(1e-9, tau_end, num_of_points - 1)
            tau_array = np.insert(tau_array, 0, 0.0)
        else:
            tau_array = np.geomspace(tau_start, tau_end, num_of_points)

        pulse_reps = 2000 # Camera misses triggers if too low

        # create the elements with camera exposure throughout
        waiting_element = self._get_idle_cam_element(length= self.wait_time, increment = 0)
        mw_wait_element = self._get_idle_cam_element(length=self.rabi_period1, increment=0) #divide by 2? or avg?
        laser_element = self._get_laser_cam_element(length=self.laser_length, increment=0)
        delay_element = self._get_idle_cam_element(length = self.laser_delay,increment = 0)
        no_exp_wait_element = self._get_idle_element(length = 100e-6, increment = 0)

        pi1_element = self._get_mw1_cam_element(length=self.rabi_period1 / 2,
                                            increment=0,
                                            amp=self.microwave1_amplitude,
                                            freq=self.microwave1_frequency,
                                            phase=0)
        pi2_element = self._get_mw2_cam_element(length=self.rabi_period2 / 2,
                                            increment=0,
                                            amp=self.microwave2_amplitude,
                                            freq=self.microwave2_frequency,
                                            phase=0)

        t1_block = PulseBlock(name=name)
        for tau in tau_array:
            tau_element = self._get_idle_cam_element(length=tau, increment=0.0)
            
            t1_block.append(no_exp_wait_element)
            
            for i in range(pulse_reps):
                # -1
                t1_block.append(tau_element)
                t1_block.append(pi1_element)
                t1_block.append(laser_element)
                t1_block.append(delay_element)

            t1_block.append(waiting_element)
            t1_block.append(no_exp_wait_element)

            for i in range(pulse_reps):
                # 0
                t1_block.append(tau_element)
                t1_block.append(mw_wait_element)
                t1_block.append(laser_element)
                t1_block.append(delay_element)
                
            t1_block.append(waiting_element)
            t1_block.append(no_exp_wait_element)

            for i in range(pulse_reps):
                # +1
                t1_block.append(tau_element)
                t1_block.append(pi2_element)
                t1_block.append(laser_element)
                t1_block.append(delay_element)

            t1_block.append(waiting_element)
            t1_block.append(no_exp_wait_element)

        created_blocks.append(t1_block)

        # Create block ensemble
        block_ensemble = PulseBlockEnsemble(name=name, rotating_frame=False)
        block_ensemble.append((t1_block.name, 0))

        # Create and append sync trigger block if needed
        self._add_trigger(created_blocks=created_blocks, block_ensemble=block_ensemble)

        # add metadata to invoke settings later on
        number_of_lasers = 3 * num_of_points
        block_ensemble.measurement_information['number_of_curves'] = 3
        block_ensemble.measurement_information['laser_ignore_list'] = list()
        block_ensemble.measurement_information['controlled_variable'] = tau_array
        block_ensemble.measurement_information['units'] = ('s', '')
        block_ensemble.measurement_information['labels'] = ('Tau<sub>pulse spacing</sub>', 'Signal')
        block_ensemble.measurement_information['number_of_lasers'] = number_of_lasers
        block_ensemble.measurement_information['counting_length'] = self._get_ensemble_count_length(
            ensemble=block_ensemble, created_blocks=created_blocks)
        # append ensemble to created ensembles
        created_ensembles.append(block_ensemble)
        return created_blocks, created_ensembles, created_sequences
   
    def generate_WF_t1_2exponential(self, name='T1WFtwocurve', tau_start=1.0e-6, tau_end=1.0e-5,
                                num_of_points=10):
        """

        """
        created_blocks = list()
        created_ensembles = list()
        created_sequences = list()

        # get tau array for measurement ticks
        if tau_start == 0.0:
            tau_array = np.geomspace(1e-9, tau_end, num_of_points - 1)
            tau_array = np.insert(tau_array, 0, 0.0)
        else:
            tau_array = np.geomspace(tau_start, tau_end, num_of_points)

        pulse_reps = 5000 # Camera misses triggers if too low

        # create the elements with camera exposure throughout
        waiting_element = self._get_idle_cam_element(length= self.wait_time, increment = 0)
        mw_wait_element = self._get_idle_cam_element(length=self.rabi_period1, increment=0) #divide by 2? or avg?
        laser_element = self._get_laser_cam_element(length=self.laser_length, increment=0)
        delay_element = self._get_idle_cam_element(length = self.laser_delay,increment = 0)
        no_exp_wait_element = self._get_idle_element(length = 200e-6, increment = 0)

        pi1_element = self._get_mw1_cam_element(length=self.rabi_period1 / 2,
                                            increment=0,
                                            amp=self.microwave1_amplitude,
                                            freq=self.microwave1_frequency,
                                            phase=0)
        # pi2_element = self._get_mw2_cam_element(length=self.rabi_period2 / 2,
        #                                     increment=0,
        #                                     amp=self.microwave2_amplitude,
        #                                     freq=self.microwave2_frequency,
        #                                     phase=0)

        t1_block = PulseBlock(name=name)
        for tau in tau_array:
            tau_element = self._get_idle_cam_element(length=tau, increment=0.0)
            
            t1_block.append(no_exp_wait_element)

            for i in range(pulse_reps):
                # 0
                t1_block.append(tau_element)
                t1_block.append(mw_wait_element)
                t1_block.append(laser_element)
                t1_block.append(delay_element)
                
            t1_block.append(waiting_element)
            t1_block.append(no_exp_wait_element)

            for i in range(pulse_reps):
                # -1
                t1_block.append(tau_element)
                t1_block.append(pi1_element)
                t1_block.append(laser_element)
                t1_block.append(delay_element)

            t1_block.append(waiting_element)
            t1_block.append(no_exp_wait_element)

            # for i in range(pulse_reps):
            #     # +1
            #     t1_block.append(tau_element)
            #     t1_block.append(pi2_element)
            #     t1_block.append(laser_element)
            #     t1_block.append(delay_element)

            # t1_block.append(waiting_element)
            # t1_block.append(no_exp_wait_element)

        created_blocks.append(t1_block)

        # Create block ensemble
        block_ensemble = PulseBlockEnsemble(name=name, rotating_frame=False)
        block_ensemble.append((t1_block.name, 0))

        # Create and append sync trigger block if needed
        self._add_trigger(created_blocks=created_blocks, block_ensemble=block_ensemble)

        # add metadata to invoke settings later on
        number_of_lasers = 2 * num_of_points
        block_ensemble.measurement_information['number_of_curves'] = 2
        block_ensemble.measurement_information['laser_ignore_list'] = list()
        block_ensemble.measurement_information['controlled_variable'] = tau_array
        block_ensemble.measurement_information['units'] = ('s', '')
        block_ensemble.measurement_information['labels'] = ('Tau<sub>pulse spacing</sub>', 'Signal')
        block_ensemble.measurement_information['number_of_lasers'] = number_of_lasers
        block_ensemble.measurement_information['counting_length'] = self._get_ensemble_count_length(
            ensemble=block_ensemble, created_blocks=created_blocks)
        # append ensemble to created ensembles
        created_ensembles.append(block_ensemble)
        return created_blocks, created_ensembles, created_sequences

    def generate_WF_ODMR(self, name='ODMR', length=5.0e-6, ranges=True):
        """ Generates Laser on.

        @param str name: Name of the PulseBlockEnsemble
        @param float length: laser duration in seconds

        @return object: the generated PulseBlockEnsemble object.
        """
        created_blocks = list()
        created_ensembles = list()
        created_sequences = list()

        # create the laser element
        laser_element = self._get_mw1_mw2_laser_cam_element(length=length, increment=0)

        # Create block and append to created_blocks list
        laser_block = PulseBlock(name=name)
        laser_block.append(laser_element)
        created_blocks.append(laser_block)
        # Create block ensemble and append to created_ensembles list
        block_ensemble = PulseBlockEnsemble(name=name, rotating_frame=False)
        block_ensemble.append((laser_block.name, 0))
        created_ensembles.append(block_ensemble)
        return created_blocks, created_ensembles, created_sequences