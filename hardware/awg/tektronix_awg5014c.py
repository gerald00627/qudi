# -*- coding: utf-8 -*-

"""
This file contains the Qudi hardware module for AWG5000 Series.

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

from core.util.modules import get_home_dir
import time
from ftplib import FTP
from socket import socket, AF_INET, SOCK_STREAM
import os
from collections import OrderedDict
from fnmatch import fnmatch
import re

from core.module import Base
from core.configoption import ConfigOption
from interface.pulser_interface import PulserInterface, PulserConstraints, SequenceOption


class AWG5014C(Base, PulserInterface):
    """ A hardware module for the Tektronix AWG5000 series for generating
        waveforms and sequences thereof.

    Unstable and in construction, Alexander Stark

    Example config for copy-paste:

    pulser_awg5014c:
        module.Class: 'awg.tektronix_awg5014c.AWG5014C'
        awg_ip_address: '10.42.0.211'
        awg_port: 3000 # the port number as integer
        timeout: 20
        # tmp_work_dir: 'C:\\Software\\qudi_pulsed_files' # optional
        # ftp_root_dir: 'C:\\inetpub\\ftproot' # optional, root directory on AWG device
        # ftp_login: 'anonymous' # optional, the username for ftp login
        # ftp_passwd: 'anonymous@' # optional, the password for ftp login
        # default_sample_rate: 600.0e6 # optional, the default sampling rate
    """

    # config options
    ip_address = ConfigOption('awg_ip_address', missing='error')
    port = ConfigOption('awg_port', missing='error')
    _timeout = ConfigOption('timeout', 10, missing='warn')
    _tmp_work_dir = ConfigOption('tmp_work_dir', missing='warn') # default path will be assigned in activation
    ftp_root_directory = ConfigOption('ftp_root_dir', 'C:\\inetpub\\ftproot', missing='warn')
    user = ConfigOption('ftp_login', 'anonymous', missing='warn')
    passwd = ConfigOption('ftp_passwd', 'anonymous@', missing='warn')
    default_sample_rate = ConfigOption('default_sample_rate', missing='warn')

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

        self.connected = False

        self._marker_byte_dict = {0: b'\x00', 1: b'\x01', 2: b'\x02', 3: b'\x03'}
        self.current_loaded_asset = ''

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        config = self.getConfiguration()

        # Use a socket connection via IPv4 connection and use a the most common
        # stream socket.
        self.soc = socket(AF_INET, SOCK_STREAM)
        self.soc.settimeout(self._timeout)  # set the timeout if no answer comes

        # Use connect and not the bind method. Bind is always performed by the
        # server where connect is done by the client!
        self.soc.connect((self.ip_address, self.port))
        self.connected = True

        # choose the buffer size appropriated, have a look here:
        #   https://docs.python.org/3/library/socket.html#socket.socket.recv
        self.input_buffer = int(4096)   # buffer length for received text

        # the ftp connection will be established during runtime if needed and
        # closed directly afterwards. This makes the connection stable.

        if 'default_sample_rate' in config.keys():
            self._sample_rate = self.set_sample_rate(config['default_sample_rate'])
        else:
            self.log.warning('No parameter "default_sample_rate" found in '
                    'the config for the AWG5014C! The maximum sample rate is '
                    'used instead.')
            self._sample_rate = self.get_constraints().sample_rate.max

        # settings for remote access on the AWG PC
        self.asset_directory = '\\waves'

        if 'tmp_work_dir' in config.keys():
            self._tmp_work_dir = config['tmp_work_dir']

            if not os.path.exists(self._tmp_work_dir):

                homedir = get_home_dir()
                self._tmp_work_dir = os.path.join(homedir, 'pulsed_files')
                self.log.warning('The directory defined in parameter '
                    '"tmp_work_dir" in the config for '
                    'SequenceGeneratorLogic class does not exist!\n'
                    'The default home directory\n{0}\n will be taken '
                    'instead.'.format(self._tmp_work_dir))
        else:
            homedir = get_home_dir()
            self._tmp_work_dir = os.path.join(homedir, 'pulsed_files')
            self.log.warning('No parameter "tmp_work_dir" was specified in the config for '
                             'SequenceGeneratorLogic as directory for the pulsed files!\n'
                             'The default home directory\n{0}\nwill be taken instead.'
                             ''.format(self._tmp_work_dir))

        self.host_waveform_directory = self._get_dir_for_name('sampled_hardware_files')
        self.awg_model = self._get_model_ID()[1]
        self.log.debug('Found the following model: {0}'.format(self.awg_model))

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self.connected = False
        self.soc.shutdown(0)  # tell the connection that the host will not listen
                              # any more to messages from it.
        self.soc.close()

    # =========================================================================
    # Below all the Pulser Interface routines.
    # =========================================================================

    # -------------------- BEGIN NEW FUNCTIONS FROM tektronix_awg70k ------------------------ #

    def delete_sequence(self, sequence_name):
        """ Delete the sequence with name "sequence_name" from the device memory.

        @param str sequence_name: The name of the sequence to be deleted
                                  Optionally a list of sequence names can be passed.

        @return list: a list of deleted sequence names.
        """
        if isinstance(sequence_name, str):
            sequence_name = [sequence_name]

        avail_sequences = self.get_sequence_names()
        deleted_sequences = list()
        for sequence in sequence_name:
            if sequence in avail_sequences:
                self.write('SLIS:SEQ:DEL "{0}"'.format(sequence))
                deleted_sequences.append(sequence)
        return deleted_sequences

    def write_waveform(self, name, analog_samples, digital_samples, is_first_chunk, is_last_chunk,
                       total_number_of_samples):
        """
        Write a new waveform or append samples to an already existing waveform on the device memory.
        The flags is_first_chunk and is_last_chunk can be used as indicator if a new waveform should
        be created or if the write process to a waveform should be terminated.

        NOTE: All sample arrays in analog_samples and digital_samples must be of equal length!

        @param str name: the name of the waveform to be created/append to
        @param dict analog_samples: keys are the generic analog channel names (i.e. 'a_ch1') and
                                    values are 1D numpy arrays of type float32 containing the
                                    voltage samples.
        @param dict digital_samples: keys are the generic digital channel names (i.e. 'd_ch1') and
                                     values are 1D numpy arrays of type bool containing the marker
                                     states.
        @param bool is_first_chunk: Flag indicating if it is the first chunk to write.
                                    If True this method will create a new empty wavveform.
                                    If False the samples are appended to the existing waveform.
        @param bool is_last_chunk:  Flag indicating if it is the last chunk to write.
                                    Some devices may need to know when to close the appending wfm.
        @param int total_number_of_samples: The number of sample points for the entire waveform
                                            (not only the currently written chunk)

        @return (int, list): Number of samples written (-1 indicates failed process) and list of
                             created waveform names
        """
        waveforms = list()

        # Sanity checks
        if len(analog_samples) == 0:
            self.log.error('No analog samples passed to write_waveform method in awg5014c.')
            return -1, waveforms

        min_samples = int(self.query('WLIS:WAV:LMIN?'))
        if total_number_of_samples < min_samples:
            self.log.error('Unable to write waveform.\nNumber of samples to write ({0:d}) is '
                           'smaller than the allowed minimum waveform length ({1:d}).'
                           ''.format(total_number_of_samples, min_samples))
            return -1, waveforms

        # determine active channels
        activation_dict = self.get_active_channels()
        active_channels = {chnl for chnl in activation_dict if activation_dict[chnl]}
        active_analog = natural_sort(chnl for chnl in active_channels if chnl.startswith('a'))

        # Sanity check of channel numbers
        if active_channels != set(analog_samples.keys()).union(set(digital_samples.keys())):
            self.log.error('Mismatch of channel activation and sample array dimensions for '
                           'waveform creation.\nChannel activation is: {0}\nSample arrays have: '
                           ''.format(active_channels,
                                     set(analog_samples.keys()).union(set(digital_samples.keys()))))
            return -1, waveforms

        # Write waveforms. One for each analog channel.
        for a_ch in active_analog:
            # Get the integer analog channel number
            a_ch_num = int(a_ch.split('ch')[-1])
            # Get the digital channel specifiers belonging to this analog channel markers
            mrk_ch_1 = 'd_ch{0:d}'.format(a_ch_num * 2 - 1)
            mrk_ch_2 = 'd_ch{0:d}'.format(a_ch_num * 2)

            start = time.time()
            # Encode marker information in an array of bytes (uint8). Avoid intermediate copies!!!
            if mrk_ch_1 in digital_samples and mrk_ch_2 in digital_samples:
                mrk_bytes = digital_samples[mrk_ch_2].view('uint8')
                tmp_bytes = digital_samples[mrk_ch_1].view('uint8')
                np.left_shift(mrk_bytes, 1, out=mrk_bytes)
                np.add(mrk_bytes, tmp_bytes, out=mrk_bytes)
            elif mrk_ch_1 in digital_samples:
                mrk_bytes = digital_samples[mrk_ch_1].view('uint8')
            else:
                mrk_bytes = None
            self.log.debug('Prepare digital channel data: {0}'.format(time.time()-start))

            # Create waveform name string
            wfm_name = '{0}_ch{1:d}'.format(name, a_ch_num)

            # Check if waveform already exists and delete if necessary.
            if wfm_name in self.get_waveform_names():
                self.delete_waveform(wfm_name)

            # Write WFMX file for waveform
            start = time.time()
            self._write_wfmx(filename=wfm_name,
                             analog_samples=analog_samples[a_ch],
                             marker_bytes=mrk_bytes,
                             is_first_chunk=is_first_chunk,
                             is_last_chunk=is_last_chunk,
                             total_number_of_samples=total_number_of_samples)
            self.log.debug('Write WFMX file: {0}'.format(time.time() - start))

            # transfer waveform to AWG and load into workspace
            start = time.time()
            self._send_file(filename=wfm_name + '.wfmx')
            self.log.debug('Send WFMX file: {0}'.format(time.time() - start))

            start = time.time()
            self.write('MMEM:OPEN "{0}"'.format(os.path.join(
                self._ftp_dir, self.ftp_working_dir, wfm_name + '.wfmx')))
            # Wait for everything to complete
            timeout_old = self.awg.timeout
            # increase this time so that there is no timeout for loading longer sequences
            # which might take some minutes
            self.awg.timeout = 5e6
            # the answer of the *opc-query is received as soon as the loading is finished
            opc = int(self.query('*OPC?'))
            # Just to make sure
            while wfm_name not in self.get_waveform_names():
                time.sleep(0.25)

            # reset the timeout
            self.awg.timeout = timeout_old
            self.log.debug('Load WFMX file into workspace: {0}'.format(time.time() - start))

            # Append created waveform name to waveform list
            waveforms.append(wfm_name)
        return total_number_of_samples, waveforms

    def write_sequence(self, name, sequence_parameter_list):
        """
        Write a new sequence on the device memory.

        @param name: str, the name of the waveform to be created/append to
        @param sequence_parameter_list: list, contains the parameters for each sequence step and
                                        the according waveform names.

        @return: int, number of sequence steps written (-1 indicates failed process)
        """
        # Check if device has sequencer option installed
        if not self._has_sequence_mode():
            self.log.error('Direct sequence generation in AWG not possible. Sequencer option not '
                           'installed.')
            return -1

        # Check if all waveforms are present on device memory
        avail_waveforms = set(self.get_waveform_names())
        for waveform_tuple, param_dict in sequence_parameter_list:
            if not avail_waveforms.issuperset(waveform_tuple):
                self.log.error('Failed to create sequence "{0}" due to waveforms "{1}" not '
                               'present in device memory.'.format(name, waveform_tuple))
                return -1

        active_analog = natural_sort(chnl for chnl in self.get_active_channels() if chnl.startswith('a'))
        num_tracks = len(active_analog)
        num_steps = len(sequence_parameter_list)

        # Create new sequence and set jump timing to immediate.
        # Delete old sequence by the same name if present.
        self.new_sequence(name=name, steps=num_steps)

        # Fill in sequence information
        for step, (wfm_tuple, seq_step) in enumerate(sequence_parameter_list, 1):
            # Set waveforms to play
            if num_tracks == len(wfm_tuple):
                for track, waveform in enumerate(wfm_tuple, 1):
                    self.sequence_set_waveform(name, waveform, step, track)
            else:
                self.log.error('Unable to write sequence.\nLength of waveform tuple "{0}" does not '
                               'match the number of sequence tracks.'.format(waveform_tuple))
                return -1

            # Set event jump trigger
            if seq_step.event_trigger != 'OFF':
                self.sequence_set_event_jump(name,
                                             step,
                                             seq_step.event_trigger,
                                             seq_step.event_jump_to)
            # Set wait trigger
            if seq_step.wait_for != 'OFF':
                self.sequence_set_wait_trigger(name, step, seq_step.wait_for)
            # Set repetitions
            if seq_step.repetitions != 0:
                self.sequence_set_repetitions(name, step, seq_step.repetitions)
            # Set go_to parameter
            if seq_step.go_to > 0:
                if seq_step.go_to <= num_steps:
                    self.sequence_set_goto(name, step, seq_step.go_to)
                else:
                    self.log.error('Assigned "go_to = {0}" is larger than the number of steps '
                                   '"{1}".'.format(seq_step.go_to, num_steps))
                    return -1
            # Set flag states
            self.sequence_set_flags(name, step, seq_step.flag_trigger, seq_step.flag_high)

        # Wait for everything to complete
        while int(self.query('*OPC?')) != 1:
            time.sleep(0.25)
        return num_steps

    def load_waveform(self, load_dict):
        """ Loads a waveform to the specified channel of the pulsing device.
        For devices that have a workspace (i.e. AWG) this will load the waveform from the device
        workspace into the channel.
        For a device without mass memory this will make the waveform/pattern that has been
        previously written with self.write_waveform ready to play.

        @param load_dict:  dict|list, a dictionary with keys being one of the available channel
                                      index and values being the name of the already written
                                      waveform to load into the channel.
                                      Examples:   {1: rabi_ch1, 2: rabi_ch2} or
                                                  {1: rabi_ch2, 2: rabi_ch1}
                                      If just a list of waveform names if given, the channel
                                      association will be invoked from the channel
                                      suffix '_ch1', '_ch2' etc.

        @return (dict, str): Dictionary with keys being the channel number and values being the
                             respective asset loaded into the channel, string describing the asset
                             type ('waveform' or 'sequence')
        """
        if isinstance(load_dict, list):
            new_dict = dict()
            for waveform in load_dict:
                channel = int(waveform.rsplit('_ch', 1)[1])
                new_dict[channel] = waveform
            load_dict = new_dict

        # Get all active channels
        chnl_activation = self.get_active_channels()
        analog_channels = natural_sort(
            chnl for chnl in chnl_activation if chnl.startswith('a') and chnl_activation[chnl])

        # Check if all channels to load to are active
        channels_to_set = {'a_ch{0:d}'.format(chnl_num) for chnl_num in load_dict}
        if not channels_to_set.issubset(analog_channels):
            self.log.error('Unable to load waveforms into channels.\n'
                           'One or more channels to set are not active.')
            return self.get_loaded_assets()

        # Check if all waveforms to load are present on device memory
        if not set(load_dict.values()).issubset(self.get_waveform_names()):
            self.log.error('Unable to load waveforms into channels.\n'
                           'One or more waveforms to load are missing on device memory.')
            return self.get_loaded_assets()

        # Load waveforms into channels
        for chnl_num, waveform in load_dict.items():
            self.write('SOUR{0:d}:CASS:WAV "{1}"'.format(chnl_num, waveform))
            while self.query('SOUR{0:d}:CASS?'.format(chnl_num)) != waveform:
                time.sleep(0.1)

        return self.get_loaded_assets()

    def load_sequence(self, sequence_name):
        """ Loads a sequence to the channels of the device in order to be ready for playback.
        For devices that have a workspace (i.e. AWG) this will load the sequence from the device
        workspace into the channels.

        @param sequence_name:  str, name of the sequence to load

        @return (dict, str): Dictionary with keys being the channel number and values being the
                             respective asset loaded into the channel, string describing the asset
                             type ('waveform' or 'sequence')
        """
        if sequence_name not in self.get_sequence_names():
            self.log.error('Unable to load sequence.\n'
                           'Sequence to load is missing on device memory.')
            return self.get_loaded_assets()

        # Get all active channels
        chnl_activation = self.get_active_channels()
        analog_channels = natural_sort(
            chnl for chnl in chnl_activation if chnl.startswith('a') and chnl_activation[chnl])

        # Check if number of sequence tracks matches the number of analog channels
        trac_num = int(self.query('SLIS:SEQ:TRAC? "{0}"'.format(sequence_name)))
        if trac_num != len(analog_channels):
            self.log.error('Unable to load sequence.\nNumber of tracks in sequence to load does '
                           'not match the number of active analog channels.')
            return self.get_loaded_assets()

        # Load sequence
        for chnl in range(1, trac_num + 1):
            self.write('SOUR{0:d}:CASS:SEQ "{1}", {2:d}'.format(chnl, sequence_name, chnl))
            while self.query('SOUR{0:d}:CASS?'.format(chnl)) != '{0},{1:d}'.format(
                    sequence_name, chnl):
                time.sleep(0.2)

        return self.get_loaded_assets()

    def get_waveform_names(self):
        """ Retrieve the names of all uploaded waveforms on the device.

        @return list: List of all uploaded waveform name strings in the device workspace.
        """
        try:
            query_return = self.query('WLIS:LIST?')
        except visa.VisaIOError:
            query_return = None
            self.log.error('Unable to read waveform list from device. VisaIOError occured.')
        waveform_list = natural_sort(query_return.split(',')) if query_return else list()
        return waveform_list

    def get_sequence_names(self):
        """ Retrieve the names of all uploaded sequence on the device.

        @return list: List of all uploaded sequence name strings in the device workspace.
        """
        sequence_list = list()

        if not self._has_sequence_mode():
            return sequence_list

        try:
            number_of_seq = int(self.query('SLIS:SIZE?'))
            for ii in range(number_of_seq):
                sequence_list.append(self.query('SLIS:NAME? {0:d}'.format(ii + 1)))
        except visa.VisaIOError:
            self.log.error('Unable to read sequence list from device. VisaIOError occurred.')
        return sequence_list

    def delete_waveform(self, waveform_name):
        """ Delete the waveform with name "waveform_name" from the device memory.

        @param str waveform_name: The name of the waveform to be deleted
                                  Optionally a list of waveform names can be passed.

        @return list: a list of deleted waveform names.
        """
        if isinstance(waveform_name, str):
            waveform_name = [waveform_name]

        avail_waveforms = self.get_waveform_names()
        deleted_waveforms = list()
        for waveform in waveform_name:
            if waveform in avail_waveforms:
                self.write('WLIS:WAV:DEL "{0}"'.format(waveform))
                deleted_waveforms.append(waveform)
        return deleted_waveforms

    def get_waveform_names(self):
        """ Retrieve the names of all uploaded waveforms on the device.

        @return list: List of all uploaded waveform name strings in the device workspace.
        """
        try:
            query_return = self.query('WLIS:LIST?')
        except visa.VisaIOError:
            query_return = None
            self.log.error('Unable to read waveform list from device. VisaIOError occured.')
        waveform_list = natural_sort(query_return.split(',')) if query_return else list()
        return waveform_list

    def load_sequence(self, sequence_name):
        """ Loads a sequence to the channels of the device in order to be ready for playback.
        For devices that have a workspace (i.e. AWG) this will load the sequence from the device
        workspace into the channels.

        @param sequence_name:  str, name of the sequence to load

        @return (dict, str): Dictionary with keys being the channel number and values being the
                             respective asset loaded into the channel, string describing the asset
                             type ('waveform' or 'sequence')
        """
        if sequence_name not in self.get_sequence_names():
            self.log.error('Unable to load sequence.\n'
                           'Sequence to load is missing on device memory.')
            return self.get_loaded_assets()

        # Get all active channels
        chnl_activation = self.get_active_channels()
        analog_channels = natural_sort(
            chnl for chnl in chnl_activation if chnl.startswith('a') and chnl_activation[chnl])

        # Check if number of sequence tracks matches the number of analog channels
        trac_num = int(self.query('SLIS:SEQ:TRAC? "{0}"'.format(sequence_name)))
        if trac_num != len(analog_channels):
            self.log.error('Unable to load sequence.\nNumber of tracks in sequence to load does '
                           'not match the number of active analog channels.')
            return self.get_loaded_assets()

        # Load sequence
        for chnl in range(1, trac_num + 1):
            self.write('SOUR{0:d}:CASS:SEQ "{1}", {2:d}'.format(chnl, sequence_name, chnl))
            while self.query('SOUR{0:d}:CASS?'.format(chnl)) != '{0},{1:d}'.format(
                    sequence_name, chnl):
                time.sleep(0.2)

        return self.get_loaded_assets()

    def get_loaded_assets(self):
        """
        Retrieve the currently loaded asset names for each active channel of the device.
        The returned dictionary will have the channel numbers as keys.
        In case of loaded waveforms the dictionary values will be the waveform names.
        In case of a loaded sequence the values will be the sequence name appended by a suffix
        representing the track loaded to the respective channel (i.e. '<sequence_name>_1').

        @return (dict, str): Dictionary with keys being the channel number and values being the
                             respective asset loaded into the channel,
                             string describing the asset type ('waveform' or 'sequence')
        """
        # Get all active channels
        chnl_activation = self.get_active_channels()
        channel_numbers = sorted(int(chnl.split('_ch')[1]) for chnl in chnl_activation if
                                 chnl.startswith('a') and chnl_activation[chnl])

        # Get assets per channel
        loaded_assets = dict()
        current_type = None
        for chnl_num in channel_numbers:
            # Ask AWG for currently loaded waveform or sequence. The answer for a waveform will
            # look like '"waveformname"\n' and for a sequence '"sequencename,1"\n'
            # (where the number is the current track)
            asset_name = self.query('SOUR1:CASS?')
            # Figure out if a sequence or just a waveform is loaded by splitting after the comma
            splitted = asset_name.rsplit(',', 1)
            # If the length is 2 a sequence is loaded and if it is 1 a waveform is loaded
            asset_name = splitted[0]
            if len(splitted) > 1:
                if current_type is not None and current_type != 'sequence':
                    self.log.error('Unable to determine loaded assets.')
                    return dict(), ''
                current_type = 'sequence'
                asset_name += '_' + splitted[1]
            else:
                if current_type is not None and current_type != 'waveform':
                    self.log.error('Unable to determine loaded assets.')
                    return dict(), ''
                current_type = 'waveform'
            loaded_assets[chnl_num] = asset_name

        return loaded_assets, current_type


        # -------------------- END NEW FUNCTIONS FROM tektronix_awg70k ------------------------ #

    def get_constraints(self):
        """
        Retrieve the hardware constrains from the Pulsing device.

        @return constraints object: object with pulser constraints as attributes.

        Provides all the constraints (e.g. sample_rate, amplitude, total_length_bins,
        channel_config, ...) related to the pulse generator hardware to the caller.

            SEE PulserConstraints CLASS IN pulser_interface.py FOR AVAILABLE CONSTRAINTS!!!

        If you are not sure about the meaning, look in other hardware files to get an impression.
        If still additional constraints are needed, then they have to be added to the
        PulserConstraints class.

        Each scalar parameter is an ScalarConstraints object defined in cor.util.interfaces.
        Essentially it contains min/max values as well as min step size, default value and unit of
        the parameter.

        PulserConstraints.activation_config differs, since it contain the channel
        configuration/activation information of the form:
            {<descriptor_str>: <channel_list>,
             <descriptor_str>: <channel_list>,
             ...}

        If the constraints cannot be set in the pulsing hardware (e.g. because it might have no
        sequence mode) just leave it out so that the default is used (only zeros).
        """
        constraints = PulserConstraints()

        # The file formats are hardware specific.
        constraints.waveform_format = ['wfm']
        constraints.sequence_format = ['seq']

        constraints.sample_rate.min = 10.0e6
        constraints.sample_rate.max = 1200.0e6
        constraints.sample_rate.step = 1.0e6
        constraints.sample_rate.default = 1200.0e6

        constraints.a_ch_amplitude.min = 0.02
        constraints.a_ch_amplitude.max = 4.5
        constraints.a_ch_amplitude.step = 0.001
        constraints.a_ch_amplitude.default = 4.5

        constraints.a_ch_offset.min = -2.25
        constraints.a_ch_offset.max = 2.25
        constraints.a_ch_offset.step = 0.001
        constraints.a_ch_offset.default = 0.0

        constraints.d_ch_low.min = -1.0
        constraints.d_ch_low.max = 2.6
        constraints.d_ch_low.step = 0.01
        constraints.d_ch_low.default = 0.0

        constraints.d_ch_high.min = -0.9
        constraints.d_ch_high.max = 2.7
        constraints.d_ch_high.step = 0.01
        constraints.d_ch_high.default = 2.7

        constraints.waveform_length.min = 1
        constraints.waveform_length.max = 32400000
        constraints.waveform_length.step = 1
        constraints.waveform_length.default = 1

        constraints.waveform_num.min = 1
        constraints.waveform_num.max = 32000
        constraints.waveform_num.step = 1
        constraints.waveform_num.default = 1

        constraints.sequence_num.min = 1
        constraints.sequence_num.max = 4000
        constraints.sequence_num.step = 1
        constraints.sequence_num.default = 1

        constraints.subsequence_num.min = 1
        constraints.subsequence_num.max = 8000
        constraints.subsequence_num.step = 1
        constraints.subsequence_num.default = 1

        # If sequencer mode is available then these should be specified
        constraints.repetitions.min = 0
        constraints.repetitions.max = 65536
        constraints.repetitions.step = 1
        constraints.repetitions.default = 0

        # ToDo: Check how many external triggers are available
        constraints.event_triggers = ['A', 'B']
        constraints.flags = list()

        constraints.sequence_steps.min = 0
        constraints.sequence_steps.max = 8000
        constraints.sequence_steps.step = 1
        constraints.sequence_steps.default = 0

        # the name a_ch<num> and d_ch<num> are generic names, which describe UNAMBIGUOUSLY the
        # channels. Here all possible channel configurations are stated, where only the generic
        # names should be used. The names for the different configurations can be customary chosen.
        activation_config = OrderedDict()
        activation_config['config1'] = frozenset(
            {'a_ch1', 'd_ch1', 'd_ch2', 'a_ch2', 'd_ch3', 'd_ch4'})
        activation_config['config2'] = frozenset({'a_ch1', 'd_ch1', 'd_ch2'})
        activation_config['config3'] = frozenset({'a_ch2', 'd_ch3', 'd_ch4'})

        # AWG5014C has possibility for sequence output
        constraints.sequence_option = SequenceOption.OPTIONAL
        constraints.activation_config = activation_config

        return constraints

    def pulser_on(self):
        """ Switches the pulsing device on.

        @return int: error code (0:OK, -1:error, higher number corresponds to
                                 current status of the device. Check then the
                                 class variable status_dic.)
        """

        self.tell('AWGC:RUN\n')

        return self.get_status()[0]

    def pulser_off(self):
        """ Switches the pulsing device off.

        @return int: error code (0:OK, -1:error, higher number corresponds to
                                 current status of the device. Check then the
                                 class variable status_dic.)
        """
        self.tell('AWGC:STOP\n')

        return self.get_status()[0]

    def upload_asset(self, asset_name=None):
        """ Upload an already hardware conform file to the device.
        Does NOT load into channels.

        @param str asset_name: name of the ensemble/sequence to be uploaded

        @return int: error code (0:OK, -1:error)

        If nothing is passed, method will be skipped.
        """

        if asset_name is None:
            self.log.warning('No asset name provided for upload!\nCorrect that!\n'
                             'Command will be ignored.')
            return -1

        # at first delete all the name, which might lead to confusions in the
        # upload procedure:
        self.delete_asset(asset_name)

        # create list of filenames to be uploaded
        upload_names = []
        filelist = os.listdir(self.host_waveform_directory)
        for filename in filelist:

            is_wfm = filename.endswith('.wfm')

            if is_wfm and (asset_name + '_ch') in filename:
                upload_names.append(filename)

            if (asset_name + '.seq') in filename:
                upload_names.append(filename)

        # upload files
        for name in upload_names:
            self._send_file(name)
        return 0

    def _send_file(self, filename):
        """ Sends an already hardware specific waveform file to the pulse
            generators waveform directory.

        @param string filename: The file name of the source file

        @return int: error code (0:OK, -1:error)

        Unused for digital pulse generators without sequence storage capability
        (PulseBlaster, FPGA).
        """

        filepath = os.path.join(self.host_waveform_directory, filename)

        with FTP(self.ip_address) as ftp:
            ftp.login()  # login as default user anonymous, passwd anonymous@
            ftp.cwd(self.asset_directory)
            with open(filepath, 'rb') as uploaded_file:
                ftp.storbinary('STOR '+filename, uploaded_file)

    def load_asset(self, asset_name, load_dict=None):
        """ Loads a sequence or waveform to the specified channel of the pulsing
            device.

        @param str asset_name: The name of the asset to be loaded

        @param dict load_dict:  a dictionary with keys being one of the
                                available channel numbers and items being the
                                name of the already sampled
                                waveform/sequence files.
                                Examples:   {1: rabi_Ch1, 2: rabi_Ch2}
                                            {1: rabi_Ch2, 2: rabi_Ch1}
                                This parameter is optional. If none is given
                                then the channel association is invoked from
                                the sequence generation,
                                i.e. the filename appendix (_Ch1, _Ch2 etc.)

        @return int: error code (0:OK, -1:error)

        Unused for digital pulse generators without sequence storage capability
        (PulseBlaster, FPGA).
        """

        if load_dict is None:
            load_dict = {}

        path = self.ftp_root_directory + self.get_asset_dir_on_device()

        # Find all files associated with the specified asset name
        file_list = self._get_filenames_on_device()
        filename = []

        # Be careful which asset_name to specify as the current_loaded_asset
        # because a loaded sequence contains also individual waveforms, which
        # should not be used as the current asset!!

        if (asset_name + '.seq') in file_list:
            file_name = asset_name + '.seq'

            self.tell('SOUR1:FUNC:USER "{0}/{1}"\n'.format(path, file_name))
            # set the AWG to the event jump mode:
            self.tell('AWGCONTROL:EVENT:JMODE EJUMP')

            self.current_loaded_asset = asset_name
        else:

            for file in file_list:
                if file == asset_name+'_ch1.wfm':
                    self.tell('SOUR1:FUNC:USER "{0}/{1}"\n'.format(path, asset_name+'_ch1.wfm'))
                    # if the asset is not a sequence file, then it must be a wfm
                    # file and either both or one of the channels should contain
                    # the asset name:
                    self.current_loaded_asset = asset_name

                    filename.append(file)
                elif file == asset_name+'_ch2.wfm':
                    self.tell('SOUR2:FUNC:USER "{0}/{1}"\n'.format(path, asset_name+'_ch2.wfm'))
                    filename.append(file)
                    # if the asset is not a sequence file, then it must be a wfm
                    # file and either both or one of the channels should contain
                    # the asset name:
                    self.current_loaded_asset = asset_name

            if load_dict == {} and filename == []:
                self.log.warning('No file and channel provided for load!\nCorrect that!\n'
                                 'Command will be ignored.')

        for channel_num in list(load_dict):
            file_name = str(load_dict[channel_num]) + '_ch{0}.wfm'.format(int(channel_num))
            self.tell('SOUR{0}:FUNC:USER "{1}/{2}"\n'.format(channel_num, path, file_name))

        if len(load_dict) > 0:
            self.current_loaded_asset = asset_name

        return 0

    def get_loaded_asset(self):
        """ Retrieve the currently loaded asset name of the device.

        @return str: Name of the current asset, that can be either a filename
                     a waveform, a sequence ect.
        """
        return self.current_loaded_asset

    def clear_all(self):
        """ Clears the loaded waveform from the pulse generators RAM.

        @return int: error code (0:OK, -1:error)

        Delete all waveforms and sequences from Hardware memory and clear the
        visual display. Unused for digital pulse generators without sequence
        storage capability (PulseBlaster, FPGA).
        """

        self.tell('WLIST:WAVEFORM:DELETE ALL\n')
        self.current_loaded_asset = ''
        return

    def get_status(self):
        """ Retrieves the status of the pulsing hardware

        @return (int, dict): inter value of the current status with the
                             corresponding dictionary containing status
                             description for all the possible status variables
                             of the pulse generator hardware.
                0 indicates that the instrument has stopped.
                1 indicates that the instrument is running.
                2 indicates that the instrument is waiting for trigger.
               -1 indicates that the request of the status for AWG has failed.
        """

        status_dic = {-1: 'Failed Request or Failed Communication with device.',
                      0: 'Device has stopped, but can receive commands.', 1: 'Device is active and running.',
                      2: 'Device is active and waiting for trigger.'}
        # the possible status of the AWG have the following meaning:

        # Keep in mind that the received integer number for the running status
        # is 2 for this specific AWG5000 series device. Therefore a received
        # message of 2 should be converted to a integer status variable of 1:

        try:
            message = int(self.ask('AWGC:RSTate?\n'))
        except:
            # if nothing comes back than the output should be marked as error
            return -1

        if message == 2:
            return 1, status_dic
        elif message == 1:
            return 2, status_dic
        else:
            return message, status_dic

    def get_sample_rate(self):
        """ Get the sample rate of the pulse generator hardware

        @return float: The current sample rate of the device (in Hz)

        Do not return a saved sample rate in a class variable, but instead
        retrieve the current sample rate directly from the device.
        """

        self._sample_rate = float(self.ask('SOURCE1:FREQUENCY?'))
        return self._sample_rate

    def set_sample_rate(self, sample_rate):
        """ Set the sample rate of the pulse generator hardware.

        @param float sample_rate: The sampling rate to be set (in Hz)

        @return float: the sample rate returned from the device.

        Note: After setting the sampling rate of the device, retrieve it again
              for obtaining the actual set value and use that information for
              further processing.
        """

        self.tell('SOURCE1:FREQUENCY {0:.4G}MHz\n'.format(sample_rate/1e6))
        time.sleep(0.2)
        return self.get_sample_rate()

    def get_analog_level(self, amplitude=None, offset=None):
        """ Retrieve the analog amplitude and offset of the provided channels.

        @param list amplitude: optional, if a specific amplitude value (in Volt
                               peak to peak, i.e. the full amplitude) of a
                               channel is desired.
        @param list offset: optional, if a specific high value (in Volt) of a
                            channel is desired.

        @return: (dict, dict): tuple of two dicts, with keys being the channel
                               number and items being the values for those
                               channels. Amplitude is always denoted in
                               Volt-peak-to-peak and Offset in (absolute)
                               Voltage.

        Note: Do not return a saved amplitude and/or offset value but instead
              retrieve the current amplitude and/or offset directly from the
              device.

        If no entries provided then the levels of all channels where simply
        returned. If no analog channels provided, return just an empty dict.
        Example of a possible input:
            amplitude = [1,4], offset =[1,3]
        to obtain the amplitude of channel 1 and 4 and the offset
            {1: -0.5, 4: 2.0} {}
        since no high request was performed.

        The major difference to digital signals is that analog signals are
        always oscillating or changing signals, otherwise you can use just
        digital output. In contrast to digital output levels, analog output
        levels are defined by an amplitude (here total signal span, denoted in
        Voltage peak to peak) and an offset (a value around which the signal
        oscillates, denoted by an (absolute) voltage).

        In general there is no bijective correspondence between
        (amplitude, offset) and (value high, value low)!
        """
        if amplitude is None:
            amplitude = []
        if offset is None:
            offset = []
        amp = {}
        off = {}

        pattern = re.compile('[0-9]+')

        if (amplitude == []) and (offset == []):

            # since the available channels are not going to change for this
            # device you are asking directly:
            amp['a_ch1'] = float(self.ask('SOURCE1:VOLTAGE:AMPLITUDE?'))
            amp['a_ch2'] = float(self.ask('SOURCE2:VOLTAGE:AMPLITUDE?'))

            off['a_ch1'] = float(self.ask('SOURCE1:VOLTAGE:OFFSET?'))
            off['a_ch2'] = float(self.ask('SOURCE2:VOLTAGE:OFFSET?'))

        else:

            for a_ch in amplitude:
                ch_num = int(re.search(pattern, a_ch).group(0))
                amp[a_ch] = float(self.ask('SOURCE{0}:VOLTAGE:AMPLITUDE?'.format(ch_num)))

            for a_ch in offset:
                ch_num = int(re.search(pattern, a_ch).group(0))
                off[a_ch] = float(self.ask('SOURCE{0}:VOLTAGE:OFFSET?'.format(ch_num)))

        return amp, off

    def set_analog_level(self, amplitude=None, offset=None):
        """ Set amplitude and/or offset value of the provided analog channel.

        @param dict amplitude: dictionary, with key being the channel and items
                               being the amplitude values (in Volt peak to peak,
                               i.e. the full amplitude) for the desired channel.
        @param dict offset: dictionary, with key being the channel and items
                            being the offset values (in absolute volt) for the
                            desired channel.

        @return (dict, dict): tuple of two dicts with the actual set values for
                              amplitude and offset.

        If nothing is passed then the command will return two empty dicts.

        Note: After setting the analog and/or offset of the device, retrieve
              them again for obtaining the actual set value(s) and use that
              information for further processing.

        The major difference to digital signals is that analog signals are
        always oscillating or changing signals, otherwise you can use just
        digital output. In contrast to digital output levels, analog output
        levels are defined by an amplitude (here total signal span, denoted in
        Voltage peak to peak) and an offset (a value around which the signal
        oscillates, denoted by an (absolute) voltage).

        In general there is no bijective correspondence between
        (amplitude, offset) and (value high, value low)!
        """
        if amplitude is None:
            amplitude = {}
        if offset is None:
            offset = {}

        constraints = self.get_constraints()

        pattern = re.compile('[0-9]+')

        for a_ch in amplitude:
            constr = constraints.a_ch_amplitude

            ch_num = int(re.search(pattern, a_ch).group(0))

            if not(constr.min <= amplitude[a_ch] <= constr.max):
                self.log.warning('Not possible to set for analog channel {0} the amplitude '
                                 'value {1}Vpp, since it is not within the interval [{2},{3}]! '
                                 'Command will be ignored.'.format(a_ch, amplitude[a_ch],
                                                                   constr.min, constr.max))
            else:
                self.tell('SOURCE{0}:VOLTAGE:AMPLITUDE {1}'.format(ch_num, amplitude[a_ch]))

        for a_ch in offset:
            constr = constraints.a_ch_offset

            ch_num = int(re.search(pattern, a_ch).group(0))

            if not(constr.min <= offset[a_ch] <= constr.max):
                self.log.warning('Not possible to set for analog channel {0} the offset value '
                                 '{1}V, since it is not within the interval [{2},{3}]! Command '
                                 'will be ignored.'.format(a_ch, offset[a_ch], constr.min,
                                                           constr.max))
            else:
                self.tell('SOURCE{0}:VOLTAGE:OFFSET {1}'.format(ch_num, offset[a_ch]))

        return self.get_analog_level(amplitude=list(amplitude), offset=list(offset))

    def get_digital_level(self, low=None, high=None):
        """ Retrieve the digital low and high level of the provided channels.

        @param list low: optional, if a specific low value (in Volt) of a
                         channel is desired.
        @param list high: optional, if a specific high value (in Volt) of a
                          channel is desired.

        @return: (dict, dict): tuple of two dicts, with keys being the channel
                               number and items being the values for those
                               channels. Both low and high value of a channel is
                               denoted in (absolute) Voltage.

        Note: Do not return a saved low and/or high value but instead retrieve
              the current low and/or high value directly from the device.

        If no entries provided then the levels of all channels where simply
        returned. If no digital channels provided, return just an empty dict.

        Example of a possible input:
            low = [1,4]
        to obtain the low voltage values of digital channel 1 an 4. A possible
        answer might be
            {1: -0.5, 4: 2.0} {}
        since no high request was performed.

        The major difference to analog signals is that digital signals are
        either ON or OFF, whereas analog channels have a varying amplitude
        range. In contrast to analog output levels, digital output levels are
        defined by a voltage, which corresponds to the ON status and a voltage
        which corresponds to the OFF status (both denoted in (absolute) voltage)

        In general there is no bijective correspondence between
        (amplitude, offset) and (value high, value low)!
        """
        if low is None:
            low = []
        if high is None:
            high = []

        low_val = {}
        high_val = {}

        if (low == []) and (high == []):

            low_val[1] = float(self.ask('SOURCE1:MARKER1:VOLTAGE:LOW?'))
            high_val[1] = float(self.ask('SOURCE1:MARKER1:VOLTAGE:HIGH?'))
            low_val[2] = float(self.ask('SOURCE1:MARKER2:VOLTAGE:LOW?'))
            high_val[2] = float(self.ask('SOURCE1:MARKER2:VOLTAGE:HIGH?'))
            low_val[3] = float(self.ask('SOURCE2:MARKER1:VOLTAGE:LOW?'))
            high_val[3] = float(self.ask('SOURCE2:MARKER1:VOLTAGE:HIGH?'))
            low_val[4] = float(self.ask('SOURCE2:MARKER2:VOLTAGE:LOW?'))
            high_val[4] = float(self.ask('SOURCE2:MARKER2:VOLTAGE:HIGH?'))

        else:

            for d_ch in low:
                # a fast way to map from a channel list [1, 2, 3, 4] to  a
                # list like [[1,2], [1,2]]:
                if (d_ch-2) <= 0:
                    # the conversion to integer is just for safety.
                    low_val[d_ch] = float(self.ask('SOURCE1:MARKER{0}:VOLTAGE:LOW?'.format(int(d_ch))))
                else:
                    low_val[d_ch] = float(self.ask('SOURCE2:MARKER{0}:VOLTAGE:LOW?'.format(int(d_ch-2))))

            for d_ch in high:
                # a fast way to map from a channel list [1, 2, 3, 4] to a list like [[1,2], [1,2]]:
                if (d_ch-2) <= 0:
                    # the conversion to integer is just for safety.
                    high_val[d_ch] = float(
                        self.ask('SOURCE1:MARKER{0}:VOLTAGE:HIGH?'.format(int(d_ch))))
                else:
                    high_val[d_ch] = float(
                        self.ask('SOURCE2:MARKER{0}:VOLTAGE:HIGH?'.format(int(d_ch-2))))

        return low_val, high_val

    def set_digital_level(self, low=None, high=None):
        """ Set low and/or high value of the provided digital channel.

        @param dict low: dictionary, with key being the channel and items being
                         the low values (in volt) for the desired channel.
        @param dict high: dictionary, with key being the channel and items being
                         the high values (in volt) for the desired channel.

        @return (dict, dict): tuple of two dicts where first dict denotes the
                              current low value and the second dict the high
                              value.

        If nothing is passed then the command will return two empty dicts.

        Note: After setting the high and/or low values of the device, retrieve
              them again for obtaining the actual set value(s) and use that
              information for further processing.

        The major difference to analog signals is that digital signals are
        either ON or OFF, whereas analog channels have a varying amplitude
        range. In contrast to analog output levels, digital output levels are
        defined by a voltage, which corresponds to the ON status and a voltage
        which corresponds to the OFF status (both denoted in (absolute) voltage)

        In general there is no bijective correspondence between
        (amplitude, offset) and (value high, value low)!
        """
        if low is None:
            low = {}
        if high is None:
            high = {}

        constraints = self.get_constraints()

        pattern = re.compile('[0-9]+')

        for d_ch in low:
            constr = constraints.d_ch_low

            ch_num = int(re.search(pattern, d_ch).group(0))

            if not(constr.min <= low[d_ch] <= constr.max):
                self.log.warning('Not possible to set for analog channel {0} the amplitude '
                                 'value {1}Vpp, since it is not within the interval [{2},{3}]! '
                                 'Command will be ignored.'.format(d_ch, low[d_ch], constr.min,
                                                                   constr.max))
            else:
                # a fast way to map from a channel list [1, 2, 3, 4] to  a
                # list like [[1,2], [1,2]]:
                if (ch_num-2) <= 0:
                    self.tell('SOURCE1:MARKER{0}:VOLTAGE:LOW {1}'.format(ch_num, low[d_ch]))
                else:
                    self.tell('SOURCE2:MARKER{0}:VOLTAGE:LOW {1}'.format(ch_num-2, low[d_ch]))

        for d_ch in high:
            constr = constraints.d_ch_high

            ch_num = int(re.search(pattern, d_ch).group(0))

            if not(constr.min <= high[d_ch] <= constr.max):
                self.log.warning('Not possible to set for analog channel {0} the amplitude '
                                 'value {1}Vpp, since it is not within the interval [{2},{3}]! '
                                 'Command will be ignored.'.format(d_ch, high[d_ch], constr.min,
                                                                   constr.max))
            else:
                # a fast way to map from a channel list [1, 2, 3, 4] to  a
                # list like [[1,2], [1,2]]:
                if (ch_num-2) <= 0:
                    self.tell('SOURCE1:MARKER{0}:VOLTAGE:HIGH {1}'.format(ch_num, high[d_ch]))
                else:
                    self.tell('SOURCE2:MARKER{0}:VOLTAGE:HIGH {1}'.format(ch_num-2, high[d_ch]))

        return self.get_digital_level(low=list(low), high=list(high))

    def get_active_channels(self, ch=None):
        """ Get the active channels of the pulse generator hardware.

        @param list ch: optional, if specific analog or digital channels are
                        needed to be asked without obtaining all the channels.

        @return dict:  where keys denoting the channel number and items boolean
                       expressions whether channel are active or not.

        Example for an possible input (order is not important):
            ch = ['a_ch2', 'd_ch2', 'a_ch1', 'd_ch5', 'd_ch1']
        then the output might look like
            {'a_ch2': True, 'd_ch2': False, 'a_ch1': False, 'd_ch5': True, 'd_ch1': False}

        If no parameters are passed to this method all channels will be asked
        for their setting.
        """
        if ch is None:
            ch = []

        active_ch = {}

        if not ch:

            # because 0 = False and 1 = True
            active_ch['a_ch1'] = bool(int(self.ask('OUTPUT1:STATE?')))
            active_ch['a_ch2'] = bool(int(self.ask('OUTPUT2:STATE?')))

            # For the AWG5000 series, the resolution of the DAC for the analog
            # channel is fixed to 14bit. Therefore the digital channels are
            # always active and cannot be deactivated. For other AWG devices the
            # command
            #   self.ask('SOURCE1:DAC:RESOLUTION?'))
            # might be useful from which the active digital channels can be
            # obtained.
            active_ch['d_ch1'] = True
            active_ch['d_ch2'] = True
            active_ch['d_ch3'] = True
            active_ch['d_ch4'] = True
        else:
            for channel in ch:
                if 'a_ch' in channel:
                    ana_chan = int(channel[4:])
                    if 0 <= ana_chan <= self._get_num_a_ch():
                        # because 0 = False and 1 = True
                        active_ch[channel] = bool(int(self.ask('OUTPUT{0}:STATE?'.format(ana_chan))))
                    else:
                        self.log.warning('The device does not support that many analog channels! '
                                         'A channel number "{0}" was passed, but only "{1}" '
                                         'channels are available!\nCommand will be ignored.'
                                         ''.format(ana_chan, self._get_num_a_ch()))
                elif 'd_ch'in channel:
                    digi_chan = int(channel[4:])
                    if 0 <= digi_chan <= self._get_num_d_ch():
                        active_ch[channel] = True
                    else:
                        self.log.warning('The device does not support that many digital channels! '
                                         'A channel number "{0}" was passed, but only "{1}" '
                                         'channels are available!\nCommand will be ignored.'
                                         ''.format(digi_chan, self._get_num_d_ch()))
        return active_ch

    def set_active_channels(self, ch=None):
        """
        Set the active/inactive channels for the pulse generator hardware.
        The state of ALL available analog and digital channels will be returned
        (True: active, False: inactive).
        The actually set and returned channel activation must be part of the available
        activation_configs in the constraints.
        You can also activate/deactivate subsets of available channels but the resulting
        activation_config must still be valid according to the constraints.
        If the resulting set of active channels can not be found in the available
        activation_configs, the channel states must remain unchanged.

        @param dict ch: dictionary with keys being the analog or digital string generic names for
                        the channels (i.e. 'd_ch1', 'a_ch2') with items being a boolean value.
                        True: Activate channel, False: Deactivate channel

        @return dict: with the actual set values for ALL active analog and digital channels

        If nothing is passed then the command will simply return the unchanged current state.

        Note: After setting the active channels of the device, use the returned dict for further
              processing.

        Example for possible input:
            ch={'a_ch2': True, 'd_ch1': False, 'd_ch3': True, 'd_ch4': True}
        to activate analog channel 2 digital channel 3 and 4 and to deactivate
        digital channel 1. All other available channels will remain unchanged.

        AWG5000 Series instruments support only 14-bit resolution. Therefore
        this command will have no effect on the DAC for these instruments. On
        other devices the deactivation of digital channels increase the DAC
        resolution of the analog channels.
        """
        if ch is None:
            ch = {}

        for channel in ch:
            if 'a_ch' in channel:
                ana_chan = int(channel[4:])
                if 0 <= ana_chan <= self._get_num_a_ch():
                    if ch[channel]:
                        state = 'ON'
                    else:
                        state = 'OFF'
                    self.tell('OUTPUT{0}:STATE {1}'.format(ana_chan, state))

                else:
                    self.log.warning('The device does not support that many analog channels! A '
                                     'channel number "{0}" was passed, but only "{1}" channels are '
                                     'available!\nCommand will be ignored.'
                                     ''.format(ana_chan, self._get_num_a_ch()))

        # if d_ch != {}:
        #     self.log.info('Digital Channel of the AWG5000 series will always be '
        #                 'active. This configuration cannot be changed.')

        return self.get_active_channels(ch=list(ch))

    def get_uploaded_asset_names(self):
        """ Retrieve the names of all uploaded assets on the device.

        @return list: List of all uploaded asset name strings in the current
                      device directory.

        Unused for digital pulse generators without sequence storage capability
        (PulseBlaster, FPGA).
        """
        uploaded_files = self._get_filenames_on_device()
        name_list = []
        for filename in uploaded_files:
            if fnmatch(filename, '*_ch?.wfm'):
                asset_name = filename.rsplit('_', 1)[0]
                if asset_name not in name_list:
                    name_list.append(asset_name)
            if fnmatch(filename, '*.seq'):
                name_list.append(filename[:-4])
        return name_list

    def get_saved_asset_names(self):
        """ Retrieve the names of all sampled and saved assets on the host PC.
        This is no list of the file names.

        @return list: List of all saved asset name strings in the current
                      directory of the host PC.
        """
        # list of all files in the waveform directory ending with .wfm
        file_list = self._get_filenames_on_host()
        # exclude the channel specifier for multiple analog channels and create return list
        saved_assets = []
        for filename in file_list:
            if fnmatch(filename, '*_ch?.wfm'):
                asset_name = filename.rsplit('_', 1)[0]
                if asset_name not in saved_assets:
                    saved_assets.append(asset_name)
        return saved_assets

    def delete_asset(self, asset_name):
        """ Delete all files associated with an asset with the passed
            asset_name from the device memory.

        @param str asset_name: The name of the asset to be deleted
                               Optionally a list of asset names can be passed.

        @return list: a list with strings of the files which were deleted.

        Unused for digital pulse generators without sequence storage capability
        (PulseBlaster, FPGA).
        """
        if not isinstance(asset_name, list):
            asset_name = [asset_name]

        # get all uploaded files
        uploaded_files = self._get_filenames_on_device()

        # list of uploaded files to be deleted
        files_to_delete = []
        # determine files to delete
        for name in asset_name:
            for filename in uploaded_files:
                if fnmatch(filename, name+'_ch?.wfm'):
                    files_to_delete.append(filename)
                elif fnmatch(filename, name+'.seq'):
                    files_to_delete.append(filename)

        # delete files
        with FTP(self.ip_address) as ftp:
            ftp.login() # login as default user anonymous, passwd anonymous@
            ftp.cwd(self.asset_directory)
            for filename in files_to_delete:
                ftp.delete(filename)

        # clear the AWG if the deleted asset is the currently loaded asset
        # if self.current_loaded_asset == asset_name:
        #     self.clear_all()
        return files_to_delete

    def set_asset_dir_on_device(self, dir_path):
        """ Change the directory where the assets are stored on the device.

        @param string dir_path: The target directory

        @return int: error code (0:OK, -1:error)

        Unused for digital pulse generators without changeable file structure
        (PulseBlaster, FPGA).
        """

        # check whether the desired directory exists:
        with FTP(self.ip_address) as ftp:
            ftp.login()  # login as default user anonymous, passwd anonymous@

            try:
                ftp.cwd(dir_path)
            except:
                self.log.info('Desired directory {0} not found on AWG device.\n'
                              'Create new.'.format(dir_path))
                ftp.mkd(dir_path)

        self.asset_directory = dir_path
        return 0

    def get_asset_dir_on_device(self):
        """ Ask for the directory where the assets are stored on the device.

        @return string: The current sequence directory

        Unused for digital pulse generators without changeable file structure
        (PulseBlaster, FPGA).
        """

        return self.asset_directory

    def get_interleave(self):
        """ Check whether Interleave is on in AWG.
        Unused for pulse generator hardware other than an AWG. The AWG 5000
        Series does not have an interleave mode and this method exists only for
        compability reasons.

        @return bool: will be always False since no interleave functionality
        """

        return False

    def set_interleave(self, state=False):
        """ Turns the interleave of an AWG on or off.

        @param bool state: The state the interleave should be set to
                           (True: ON, False: OFF)

        @return bool: actual interleave status (True: ON, False: OFF)

        Note: After setting the interleave of the device, retrieve the
              interleave again and use that information for further processing.

        Unused for pulse generator hardware other than an AWG. The AWG 5000
        Series does not have an interleave mode and this method exists only for
        compability reasons.
        """
        self.log.warning('Interleave mode not available for the AWG 5000 Series!\n'
                         'Method call will be ignored.')
        return self.get_interleave()

    def tell(self, command):
        """Send a command string to the AWG.

        @param command: string containing the command

        @return int: error code (0:OK, -1:error)
        """

        # check whether the return character was placed at the end. Otherwise
        # the communication will stuck:
        if not command.endswith('\n'):
            command += '\n'

        # In Python 3.x the socket send command only accepts byte type arrays
        # and no str
        command = bytes(command, 'UTF-8')
        self.soc.send(command)
        return 0

    def ask(self, question):
        """ Asks the device a 'question' and receive an answer from it.

        @param string question: string containing the command

        @return string: the answer of the device to the 'question'
        """
        if not question.endswith('\n'):
            question += '\n'

        # In Python 3.x the socket send command only accepts byte type arrays
        #  and no str.
        question = bytes(question, 'UTF-8')
        self.soc.send(question)
        time.sleep(0.3)  # you need to wait until AWG generating an answer.
                         # This number was determined experimentally.
        try:
            message = self.soc.recv(self.input_buffer)  # receive an answer
            message = message.decode('UTF-8')   # decode bytes into a python str
        except OSError:
            self.log.error('Most propably timeout was reached during querying the AWG5000 Series '
                           'device with the question:\n{0}\nThe question text must be wrong.'
                           ''.format(question))
            message = str(-1)

        # cut away the characters\r and \n.
        message = message.strip()

        return message

    def reset(self):
        """Reset the device.

        @return int: error code (0:OK, -1:error)
        """
        self.tell('*RST\n')

        return 0

    # =========================================================================
    # Below all the low level routines which are needed for the communication
    # and establishment of a connection.
    # ========================================================================

    def _get_model_ID(self):
        """ Obtain the device identification.

        @return: str representing the model id of the AWG.
        """

        model_id = self.ask('*IDN?').replace('\n', '').split(',')
        return model_id

    def set_lowpass_filter(self, a_ch, cutoff_freq):
        """ Set a lowpass filter to the analog channels ofawg    the AWG.

        @param int a_ch: To which channel to apply, either 1 or 2.
        @param cutoff_freq: Cutoff Frequency of the lowpass filter in Hz.
        """
        if a_ch == 1:
            self.tell('OUTPUT1:FILTER:LPASS:FREQUENCY {0:f}MHz\n'.format(cutoff_freq/1e6))
        elif a_ch == 2:
            self.tell('OUTPUT2:FILTER:LPASS:FREQUENCY {0:f}MHz\n'.format(cutoff_freq/1e6))

    def set_jump_timing(self, synchronous=False):
        """Sets control of the jump timing in the AWG.

        @param bool synchronous: if True the jump timing will be set to
                                 synchornous, otherwise the jump timing will be
                                 set to asynchronous.

        If the Jump timing is set to asynchornous the jump occurs as quickly as
        possible after an event occurs (e.g. event jump tigger), if set to
        synchornous the jump is made after the current waveform is output. The
        default value is asynchornous.
        """
        if synchronous:
            self.tell('EVEN:JTIM SYNC\n')
        else:
            self.tell('EVEN:JTIM ASYNC\n')

    def set_mode(self, mode):
        """Change the output mode of the AWG5000 series.

        @param str mode: Options for mode (case-insensitive):
                            continuous - 'C'
                            triggered  - 'T'
                            gated      - 'G'
                            sequence   - 'S'

        """

        look_up = {'C': 'CONT',
                   'T': 'TRIG',
                   'G': 'GAT',
                   'E': 'ENH',
                   'S': 'SEQ'}
        self.tell('AWGC:RMOD {0!s}\n'.format(look_up[mode.upper()]))

    def get_sequencer_mode(self, output_as_int=False):
        """ Asks the AWG which sequencer mode it is using.

        @param: bool output_as_int: optional boolean variable to set the output
        @return: str or int with the following meaning:
                'HARD' or 0 indicates Hardware Mode
                'SOFT' or 1 indicates Software Mode
                'Error' or -1 indicates a failure of request

        It can be either in Hardware Mode or in Software Mode. The optional
        variable output_as_int sets if the returned value should be either an
        integer number or string.
        """

        message = self.ask('AWGControl:SEQuencer:TYPE?\n')
        if output_as_int:
            if 'HARD' in message:
                return 0
            elif 'SOFT' in message:
                return 1
            else:
                return -1
        else:
            if 'HARD' in message:
                return 'Hardware-Sequencer'
            elif 'SOFT' in message:
                return 'Software-Sequencer'
            else:
                return 'Request-Error'

    # =========================================================================
    # Below all the higher level routines are situated which use the
    # wrapped routines as a basis to perform the desired task.
    # =========================================================================

    def _get_dir_for_name(self, name):
        """ Get the path to the pulsed sub-directory 'name'.

        @param str name:  name of the folder
        @return: str, absolute path to the directory with folder 'name'.
        """

        path = os.path.join(self._tmp_work_dir, name)
        if not os.path.exists(path):
            os.makedirs(os.path.abspath(path))

        return os.path.abspath(path)

    def _get_filenames_on_device(self):
        """ Get the full filenames of all assets saved on the device.

        @return: list, The full filenames of all assets saved on the device.
        """
        filename_list = []
        with FTP(self.ip_address) as ftp:
            ftp.login()  # login as default user anonymous, passwd anonymous@
            ftp.cwd(self.asset_directory)
            # get only the files from the dir and skip possible directories
            log =[]
            file_list = []
            ftp.retrlines('LIST', callback=log.append)
            for line in log:
                if '<DIR>' not in line:
                    # that is how a potential line is looking like:
                    #   '05-10-16  05:22PM                  292 SSR aom adjusted.seq'
                    # One can see that the first part consists of the date
                    # information. Remove those information and separate then
                    # the first number, which indicates the size of the file,
                    # from the following. That is necessary if the filename has
                    # whitespaces in the name:
                    size_filename = line[18:].lstrip()

                    # split after the first appearing whitespace and take the
                    # rest as filename, remove for safety all trailing
                    # whitespaces:
                    actual_filename = size_filename.split(' ', 1)[1].lstrip()
                    file_list.append(actual_filename)
            for filename in file_list:
                if filename.endswith('.wfm') or filename.endswith('.seq'):
                    if filename not in filename_list:
                        filename_list.append(filename)

        return filename_list

    def _get_filenames_on_host(self):
        """ Get the full filenames of all assets saved on the host PC.

        @return: list, The full filenames of all assets saved on the host PC.
        """
        filename_list = [f for f in os.listdir(self.host_waveform_directory) if
                         f.endswith('.wfm') or f.endswith('.seq')]
        return filename_list

    def _get_num_a_ch(self):
        """ Retrieve the number of available analog channels.

        @return int: number of analog channels.
        """
        config = self.get_constraints().activation_config

        all_a_ch = []
        for conf in config:

            # extract all analog channels from the config
            curr_a_ch = [entry for entry in config[conf] if 'a_ch' in entry]

            # append all new analog channels to a temporary array
            for a_ch in curr_a_ch:
                if a_ch not in all_a_ch:
                    all_a_ch.append(a_ch)

        # count the number of entries in that array
        return len(all_a_ch)

    def _get_num_d_ch(self):
        """ Retrieve the number of available digital channels.

        @return int: number of digital channels.
        """
        config = self.get_constraints().activation_config

        all_d_ch = []
        for conf in config:

            # extract all digital channels from the config
            curr_d_ch = [entry for entry in config[conf] if 'd_ch' in entry]

            # append all new analog channels to a temporary array
            for d_ch in curr_d_ch:
                if d_ch not in all_d_ch:
                    all_d_ch.append(d_ch)

        # count the number of entries in that array
        return len(all_d_ch)
