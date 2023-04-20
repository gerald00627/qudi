# -*- coding: utf-8 -*-
"""
This module contains a GUI for operating the spectrometer camera logic module.

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

import os
import pyqtgraph as pg
import numpy as np

from core.connector import Connector
from gui.colordefs import QudiPalettePale as Palette
from gui.guibase import GUIBase
from gui.colordefs import ColorScaleInferno
from gui.colordefs import QudiPalettePale as palette
from gui.fitsettings import FitSettingsDialog, FitSettingsComboBox
from qtpy import QtCore, QtWidgets, uic
from core.util.helpers import natural_sort
from qtwidgets.scientific_spinbox import ScienDSpinBox, ScienSpinBox

from qtpy import QtGui
from gui.guiutils import ColorBar

import numpy as np
from enum import Enum

import time

class CameraSettingDialog(QtWidgets.QDialog):
    """ Create the SettingsDialog window, based on the corresponding *.ui file."""

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_camera_odmr_settings.ui')

        # Load it
        super(CameraSettingDialog, self).__init__()
        uic.loadUi(ui_file, self)

class ChannelSettingDialog(QtWidgets.QDialog):
    """ Create the SettingsDialog window, based on the corresponding *.ui file."""

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_camera_odmr_channel_settings.ui')

        # Load it
        super(ChannelSettingDialog, self).__init__()
        uic.loadUi(ui_file, self)


class WidefieldWindow(QtWidgets.QMainWindow):
    """ Class defined for the main window (not the module)

    """

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_odmrgui_camera.ui')

        # Load it
        super().__init__()
        uic.loadUi(ui_file, self)
        self.show()


class WidefieldGUI(GUIBase):
    """ Main spectrometer camera class.
    """

    camera_logic = Connector(interface='CameraLogic')
    widefieldlogic1 = Connector(interface='WidefieldMeasurementLogic')
    savelogic = Connector(interface='SaveLogic')


    # Camera Signals
    sigVideoStart = QtCore.Signal()
    sigVideoStop = QtCore.Signal()
    sigImageStart = QtCore.Signal()
    sigImageStop = QtCore.Signal()

    # ODMR Signals
    sigStartOdmrScan = QtCore.Signal()
    sigStopOdmrScan = QtCore.Signal()
    sigContinueOdmrScan = QtCore.Signal()
    sigClearData = QtCore.Signal()
    sigCwMwOn = QtCore.Signal()
    sigMwOff = QtCore.Signal()
    sigMwPowerChanged = QtCore.Signal(float)
    sigMwCwParamsChanged = QtCore.Signal(float, float)
    sigCamParamsChanged = QtCore.Signal(dict)
    sigMwSweepParamsChanged = QtCore.Signal(list, list, list, float)
    sigFrameRateChanged = QtCore.Signal(float)
    sigGPIOSettingsChanged = QtCore.Signal(dict,dict)
    sigFitChanged = QtCore.Signal(str)
    sigRuntimeChanged = QtCore.Signal(float)
    sigDoFit = QtCore.Signal(str, object, object, int, int)
    sigSaveMeasurement = QtCore.Signal(str, list, list)
    sigChangeMeasurementType = QtCore.Signal(str)

    # sigMeasurementChanged = QtCore.Signal(str)

    def __init__(self, config, **kwargs):

        # load connection
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Initializes all needed UI files and establishes the connectors.
        """

        self._camera_logic = self.camera_logic()
        self._save_logic = self.savelogic()
        self._widefield_logic = self.widefieldlogic1()

        # ODMR Setup

        # Use the inherited class 'Ui_ODMRGuiUI' to create now the GUI element:
        self._mw = WidefieldWindow()
        self.restoreWindowPos(self._mw)

        self.initSettingsUI()
        self.initChannelSettingsUI()

        # Create a QSettings object for the mainwindow and store the actual GUI layout
        self.mwsettings = QtCore.QSettings("QUDI", "ODMR")
        self.mwsettings.setValue("geometry", self._mw.saveGeometry())
        self.mwsettings.setValue("windowState", self._mw.saveState())

        # Get hardware constraints to set limits for input widgets
        constraints = self._widefield_logic.get_hw_constraints()

        # Adjust range of scientific spinboxes above what is possible in Qt Designer
        self._mw.cw_frequency_DoubleSpinBox.setMaximum(constraints.max_frequency)
        self._mw.cw_frequency_DoubleSpinBox.setMinimum(constraints.min_frequency)
        self._mw.cw_power_DoubleSpinBox.setMaximum(constraints.max_power)
        self._mw.cw_power_DoubleSpinBox.setMinimum(constraints.min_power)
        self._mw.sweep_power_DoubleSpinBox.setMaximum(constraints.max_power)
        self._mw.sweep_power_DoubleSpinBox.setMinimum(constraints.min_power)

        self._create_predefined_methods()

        # Add save file tag input box
        self._mw.save_tag_LineEdit = QtWidgets.QLineEdit(self._mw)
        self._mw.save_tag_LineEdit.setMaximumWidth(500)
        self._mw.save_tag_LineEdit.setMinimumWidth(200)
        self._mw.save_tag_LineEdit.setToolTip('Enter a nametag which will be\n'
                                              'added to the filename.')

        self._mw.save_ToolBar.addWidget(self._mw.save_tag_LineEdit)

        # add a clear button to clear the ODMR plots:
        self._mw.clear_odmr_PushButton = QtWidgets.QPushButton(self._mw)
        self._mw.clear_odmr_PushButton.setText('Clear ODMR')
        self._mw.clear_odmr_PushButton.setToolTip('Clear the data of the\n'
                                                  'current ODMR measurements.')
        self._mw.clear_odmr_PushButton.setEnabled(False)
        self._mw.toolBar.addWidget(self._mw.clear_odmr_PushButton)

        # Set up and connect channel combobox
        self.display_channel = 0
        # TODO: Reimplement channels, maybe?
        # odmr_channels = self._widefield_logic.get_odmr_channels()
        # for n, ch in enumerate(odmr_channels):
        #     self._mw.odmr_channel_ComboBox.addItem(str(ch), n)

        # self._mw.odmr_channel_ComboBox.activated.connect(self.update_channel)

        self.odmr_image = pg.PlotDataItem(self._widefield_logic.odmr_plot_x,
                                          self._widefield_logic.odmr_plot_y,
                                          pen=pg.mkPen(palette.c1, style=QtCore.Qt.DotLine),
                                          symbol='o',
                                          symbolPen=palette.c1,
                                          symbolBrush=palette.c1,
                                          symbolSize=7)

        self.odmr_fit_image = pg.PlotDataItem(self._widefield_logic.odmr_fit_x,
                                              self._widefield_logic.odmr_fit_y,
                                              pen=pg.mkPen(palette.c2))

        # Add the display item to the xy and xz ViewWidget, which was defined in the UI file.
        self._mw.odmr_PlotWidget.addItem(self.odmr_image)
        self._mw.odmr_PlotWidget.setLabel(axis='left', text='Counts', units='Counts/s')
        self._mw.odmr_PlotWidget.setLabel(axis='bottom', text='Frequency', units='Hz')
        self._mw.odmr_PlotWidget.showGrid(x=True, y=True, alpha=0.8)

        # Get the colorscales at set LUT
        self.my_colors = ColorScaleInferno()

        ########################################################################
        #                  Configuration of the Colorbar                       #
        ########################################################################
        # create color bar
        self.xy_cb = ColorBar(self.my_colors.cmap_normed, width=100, cb_min=0, cb_max=100)

        self._mw.xy_cb_PlotWidget.addItem(self.xy_cb)
        self._mw.xy_cb_PlotWidget.hideAxis('bottom')
        self._mw.xy_cb_PlotWidget.setLabel('left', 'Fluorescence', units='c')
        self._mw.xy_cb_PlotWidget.setMouseEnabled(x=False, y=False)

        ########################################################################
        #          Configuration of the various display Widgets                #
        ########################################################################
        # Take the default values from logic:

        self.update_camera_limits(self._widefield_logic.get_camera_limits())

        self._mw.cw_frequency_DoubleSpinBox.setValue(self._widefield_logic.cw_mw_frequency)
        self._mw.cw_power_DoubleSpinBox.setValue(self._widefield_logic.cw_mw_power)
        self._mw.sweep_power_DoubleSpinBox.setValue(self._widefield_logic.sweep_mw_power)

        self._mw.runtime_DoubleSpinBox.setValue(self._widefield_logic.run_time)
        self._mw.elapsed_time_lcd.display(int(np.rint(self._widefield_logic.elapsed_time)))
        self._mw.elapsed_sweeps_lcd.display(self._widefield_logic.elapsed_sweeps)

        self._sd.frame_rate_DoubleSpinBox.setValue(self._widefield_logic.frame_rate)

        self._mw.gainSpinBox.setValue(self._widefield_logic.gain)
        self._mw.triggerMode_checkBox.setChecked(self._widefield_logic.trigger_mode)

        self._mw.exposuremode_comboBox.clear()
        for mode in self._widefield_logic.exposure_modes:
            self._mw.exposuremode_comboBox.addItem(mode)
        self._mw.exposuremode_comboBox.setCurrentText(self._widefield_logic.exposure_mode)

        self._mw.measurement_type_comboBox.clear()
        for mode in self._widefield_logic.predefined_generate_methods:
            if "WF_" in mode:
                self._mw.measurement_type_comboBox.addItem(mode)
        self._mw.measurement_type_comboBox.setCurrentText(self._widefield_logic.measurement_type)

        self._mw.exposureDSpinBox.setValue(self._widefield_logic.exposure_time)
        self._mw.x_pixels_SpinBox.setValue(self._widefield_logic.image_width)
        self._mw.y_pixels_SpinBox.setValue(self._widefield_logic.image_height)
        self._mw.offset_x_spinBox.setValue(self._widefield_logic.offset_x)
        self._mw.offset_y_spinBox.setValue(self._widefield_logic.offset_y)

        self._mw.pixel_format_comboBox.clear()
        for mode in self._widefield_logic.pixel_formats:
            self._mw.pixel_format_comboBox.addItem(mode)
        self._mw.pixel_format_comboBox.setCurrentText(self._widefield_logic.pixel_format)

        self._mw.plot_pixel_x_spinBox.setValue(self._widefield_logic.plot_pixel_x)
        self._mw.plot_pixel_y_spinBox.setValue(self._widefield_logic.plot_pixel_y)

        self.apply_predefined_methods_config()

        # # fit settings
        self._fsd = FitSettingsDialog(self._widefield_logic.fc)
        self._fsd.sigFitsUpdated.connect(self._mw.fit_methods_ComboBox.setFitFunctions)
        self._fsd.applySettings()
        self._mw.action_FitSettings.triggered.connect(self._fsd.show)

        ########################################################################
        #                       Connect signals                                #
        ########################################################################
        # Internal user input changed signals
        self._mw.cw_frequency_DoubleSpinBox.editingFinished.connect(self.change_cw_params)

        self._mw.gainSpinBox.editingFinished.connect(self.change_camera_params)
        self._mw.triggerMode_checkBox.stateChanged.connect(self.change_camera_params)
        self._mw.exposuremode_comboBox.currentTextChanged.connect(self.change_camera_params)
        self._mw.exposureDSpinBox.editingFinished.connect(self.change_camera_params)
        self._mw.x_pixels_SpinBox.editingFinished.connect(self.change_camera_params)
        self._mw.y_pixels_SpinBox.editingFinished.connect(self.change_camera_params)
        self._mw.offset_x_spinBox.editingFinished.connect(self.change_camera_params)
        self._mw.offset_y_spinBox.editingFinished.connect(self.change_camera_params)
        self._mw.pixel_format_comboBox.currentTextChanged.connect(self.change_camera_params)
        self._mw.plot_pixel_x_spinBox.editingFinished.connect(self.change_camera_params)
        self._mw.plot_pixel_y_spinBox.editingFinished.connect(self.change_camera_params)

        self._mw.sweep_power_DoubleSpinBox.editingFinished.connect(self.change_sweep_params)
        self._mw.cw_power_DoubleSpinBox.editingFinished.connect(self.change_cw_params)
        self._mw.runtime_DoubleSpinBox.editingFinished.connect(self.change_runtime)

        # Internal trigger signals
        self._mw.clear_odmr_PushButton.clicked.connect(self.clear_odmr_data)
        self._mw.action_run_stop.triggered.connect(self.run_stop_odmr)
        self._mw.action_resume_odmr.triggered.connect(self.resume_odmr)
        self._mw.action_toggle_cw.triggered.connect(self.toggle_cw_mode)
        self._mw.action_Save.triggered.connect(self.save_data)
        self._mw.action_RestoreDefault.triggered.connect(self.restore_defaultview)
        self._mw.do_fit_PushButton.clicked.connect(self.do_fit)
        self._mw.fit_range_SpinBox.editingFinished.connect(self.update_fit_range)
        self._mw.measurement_type_comboBox.currentTextChanged.connect(self._change_measurement_type)

        # Control/values-changed signals to logic
        self.sigCwMwOn.connect(self._widefield_logic.mw_cw_on, QtCore.Qt.QueuedConnection)
        self.sigMwOff.connect(self._widefield_logic.mw_off, QtCore.Qt.QueuedConnection)
        self.sigClearData.connect(self._widefield_logic.clear_widefield_odmr_data, QtCore.Qt.QueuedConnection)
        self.sigStartOdmrScan.connect(self._widefield_logic.start_widefield_odmr_scan, QtCore.Qt.QueuedConnection)
        self.sigStopOdmrScan.connect(self._widefield_logic.stop_widefield_odmr_scan, QtCore.Qt.QueuedConnection)
        self.sigContinueOdmrScan.connect(self._widefield_logic.continue_widefield_odmr_scan,
                                         QtCore.Qt.QueuedConnection)
        self.sigDoFit.connect(self._widefield_logic.do_fit, QtCore.Qt.QueuedConnection)
        self.sigMwCwParamsChanged.connect(self._widefield_logic.set_cw_parameters,
                                          QtCore.Qt.QueuedConnection)
        self.sigCamParamsChanged.connect(self._widefield_logic.set_camera_parameters,
                                         QtCore.Qt.QueuedConnection)
        self.sigMwSweepParamsChanged.connect(self._widefield_logic.set_sweep_parameters,
                                             QtCore.Qt.QueuedConnection)
        self.sigRuntimeChanged.connect(self._widefield_logic.set_runtime, QtCore.Qt.QueuedConnection)
        self.sigFrameRateChanged.connect(self._widefield_logic.set_frame_rate,
                                         QtCore.Qt.QueuedConnection)
        self.sigGPIOSettingsChanged.connect(self._widefield_logic.set_gpio_settings, QtCore.Qt.QueuedConnection)
        self.sigSaveMeasurement.connect(self._widefield_logic.save_odmr_data, QtCore.Qt.QueuedConnection)
        self.sigChangeMeasurementType.connect(self._widefield_logic.change_measurement_type, QtCore.Qt.QueuedConnection)

        # Update signals coming from logic:
        self._widefield_logic.sigParameterUpdated.connect(self.update_parameter,
                                                     QtCore.Qt.QueuedConnection)
        self._widefield_logic.sigCameraLimits.connect(self.update_camera_limits,
                                                     QtCore.Qt.QueuedConnection)
        self._widefield_logic.sigOutputStateUpdated.connect(self.update_status,
                                                       QtCore.Qt.QueuedConnection)
        self._widefield_logic.sigOdmrPlotsUpdated.connect(self.update_plots, QtCore.Qt.QueuedConnection)
        self._widefield_logic.sigOdmrFitUpdated.connect(self.update_fit, QtCore.Qt.QueuedConnection)
        self._widefield_logic.sigOdmrElapsedTimeUpdated.connect(self.update_elapsedtime,
                                                           QtCore.Qt.QueuedConnection)
        self._widefield_logic.sigMeasurementChanged.connect(self._change_measurement_type,
                                                            QtCore.Qt.QueuedConnection)
        

        # self._widefield_logic.sigMeasurementDataUpdated.connect(self.measurement_data_updated)
        # self._widefield_logic.sigTimerUpdated.connect(self.measurement_timer_updated)
        # self._widefield_logic.sigFitUpdated.connect(self.fit_data_updated)
        # self._widefield_logic.sigMeasurementStatusUpdated.connect(self.measurement_status_updated)
        # self._widefield_logic.sigPulserRunningUpdated.connect(self.pulser_running_updated)
        # self._widefield_logic.sigExtMicrowaveRunningUpdated.connect(self.microwave_running_updated)
        # self._widefield_logic.sigExtMicrowaveSettingsUpdated.connect(self.microwave_settings_updated)
        # self._widefield_logic.sigFastCounterSettingsUpdated.connect(self.fast_counter_settings_updated)
        # self._widefield_logic.sigMeasurementSettingsUpdated.connect(self.measurement_settings_updated)
        # self._widefield_logic.sigAnalysisSettingsUpdated.connect(self.analysis_settings_updated)
        # self._widefield_logic.sigExtractionSettingsUpdated.connect(self.extraction_settings_updated)
        # self._widefield_logic.sigSampleBlockEnsemble.connect(self.sampling_or_loading_busy)
        # self._widefield_logic.sigLoadBlockEnsemble.connect(self.sampling_or_loading_busy)
        # self._widefield_logic.sigLoadSequence.connect(self.sampling_or_loading_busy)
        # self._widefield_logic.sigSampleSequence.connect(self.sampling_or_loading_busy)
        # self._widefield_logic.sigLoadedAssetUpdated.connect(self.sampling_or_loading_finished)

        # self._widefield_logic.sigBlockDictUpdated.connect(self.update_block_dict)
        # self._widefield_logic.sigEnsembleDictUpdated.connect(self.update_ensemble_dict)
        # self._widefield_logic.sigSequenceDictUpdated.connect(self.update_sequence_dict)
        # self._widefield_logic.sigAvailableWaveformsUpdated.connect(self.waveform_list_updated)
        # self._widefield_logic.sigAvailableSequencesUpdated.connect(self.sequence_list_updated)
        self._widefield_logic.sigSampleEnsembleComplete.connect(self.sample_ensemble_finished)
        # self._widefield_logic.sigSampleSequenceComplete.connect(self.sample_sequence_finished)
        # self._widefield_logic.sigLoadedAssetUpdated.connect(self.loaded_asset_updated)
        # self._widefield_logic.sigGeneratorSettingsUpdated.connect(self.pulse_generator_settings_updated)
        # self._widefield_logic.sigSamplingSettingsUpdated.connect(self.generation_parameters_updated)
        # self._widefield_logic.sigPredefinedSequenceGenerated.connect(self.predefined_generated)

        # connect settings signals
        self._mw.actionSettings.triggered.connect(self._menu_settings)
        self._sd.accepted.connect(self.update_settings)
        self._sd.rejected.connect(self.reject_settings)
        self._sd.buttonBox.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.update_settings)
        self.reject_settings()

        # connect channel settings signals
        self._mw.actionChannel_Settings.triggered.connect(self._menu_channel_settings)
        self._sd.accepted.connect(self.update_channel_settings)
        self._sd.rejected.connect(self.reject_channel_settings)
        self._sd.buttonBox.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self.update_channel_settings)
        self.reject_channel_settings()


        # Camera Setup

        self._mw.start_video_Action.setEnabled(True)
        self._mw.start_video_Action.setChecked(self._camera_logic.enabled)
        self._mw.start_video_Action.triggered.connect(self.start_video_clicked)

        self._mw.start_image_Action.setEnabled(True)
        self._mw.start_image_Action.setChecked(self._camera_logic.enabled)
        self._mw.start_image_Action.triggered.connect(self.start_image_clicked)

        self._camera_logic.sigUpdateDisplay.connect(self.update_data)
        self._camera_logic.sigAcquisitionFinished.connect(self.acquisition_finished)
        self._camera_logic.sigVideoFinished.connect(self.enable_start_image_action)

        # starting the physical measurement
        self.sigVideoStart.connect(self._camera_logic.start_loop)
        self.sigVideoStop.connect(self._camera_logic.stop_loop)
        self.sigImageStart.connect(self._camera_logic.start_single_acquistion)

        # connect Settings action under Options menu
        # connect save action to save function
        # TODO: save XY data
        # self._mw.actionSave_XY_Scan.triggered.connect(self.save_xy_scan_data)

        raw_data_image = self._camera_logic.get_last_image()
        self._image = pg.ImageItem(image=raw_data_image, axisOrder='row-major')
        self._mw.image_PlotWidget.addItem(self._image)
        self._mw.image_PlotWidget.setAspectLocked(True)

        self._image.setLookupTable(self.my_colors.lut)

        # Connect the buttons and inputs for the colorbar
        self._mw.xy_cb_manual_RadioButton.clicked.connect(self.update_xy_cb_range)
        self._mw.xy_cb_centiles_RadioButton.clicked.connect(self.update_xy_cb_range)

        self._mw.xy_cb_min_DoubleSpinBox.valueChanged.connect(self.shortcut_to_xy_cb_manual)
        self._mw.xy_cb_max_DoubleSpinBox.valueChanged.connect(self.shortcut_to_xy_cb_manual)
        self._mw.xy_cb_low_percentile_DoubleSpinBox.valueChanged.connect(self.shortcut_to_xy_cb_centiles)
        self._mw.xy_cb_high_percentile_DoubleSpinBox.valueChanged.connect(self.shortcut_to_xy_cb_centiles)

        # Show the Main ODMR GUI:
        self.show()

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        # Disconnect signals
        self._sd.buttonBox.button(QtWidgets.QDialogButtonBox.Apply).clicked.disconnect()
        self._sd.accepted.disconnect()
        self._sd.rejected.disconnect()
        self._mw.actionSettings.triggered.disconnect()
        self._mw.actionChannel_Settings.triggered.disconnect()
        self._widefield_logic.sigParameterUpdated.disconnect()
        self._widefield_logic.sigMeasurementChanged.disconnect()
        self._widefield_logic.sigCameraLimits.disconnect()
        self._widefield_logic.sigOutputStateUpdated.disconnect()
        self._widefield_logic.sigOdmrPlotsUpdated.disconnect()
        self._widefield_logic.sigOdmrFitUpdated.disconnect()
        self._widefield_logic.sigOdmrElapsedTimeUpdated.disconnect()
        self._widefield_logic.sigMeasurementDataUpdated.disconnect()
        self._widefield_logic.sigTimerUpdated.disconnect()
        self._widefield_logic.sigFitUpdated.disconnect()
        self._widefield_logic.sigMeasurementStatusUpdated.disconnect()
        self._widefield_logic.sigPulserRunningUpdated.disconnect()
        self._widefield_logic.sigExtMicrowaveRunningUpdated.disconnect()
        self._widefield_logic.sigExtMicrowaveSettingsUpdated.disconnect()
        self._widefield_logic.sigFastCounterSettingsUpdated.disconnect()
        self._widefield_logic.sigMeasurementSettingsUpdated.disconnect()
        self._widefield_logic.sigAnalysisSettingsUpdated.disconnect()
        self._widefield_logic.sigExtractionSettingsUpdated.disconnect()

        self._widefield_logic.sigBlockDictUpdated.disconnect()
        self._widefield_logic.sigEnsembleDictUpdated.disconnect()
        self._widefield_logic.sigSequenceDictUpdated.disconnect()
        self._widefield_logic.sigAvailableWaveformsUpdated.disconnect()
        self._widefield_logic.sigAvailableSequencesUpdated.disconnect()
        self._widefield_logic.sigSampleEnsembleComplete.disconnect()
        self._widefield_logic.sigSampleSequenceComplete.disconnect()
        self._widefield_logic.sigLoadedAssetUpdated.disconnect()
        self._widefield_logic.sigGeneratorSettingsUpdated.disconnect()
        self._widefield_logic.sigSamplingSettingsUpdated.disconnect()
        self._widefield_logic.sigPredefinedSequenceGenerated.disconnect()
        self.sigCwMwOn.disconnect()
        self.sigMwOff.disconnect()
        self.sigClearData.disconnect()
        self.sigStartOdmrScan.disconnect()
        self.sigStopOdmrScan.disconnect()
        self.sigContinueOdmrScan.disconnect()
        self.sigDoFit.disconnect()
        self.sigMwCwParamsChanged.disconnect()
        self.sigCamParamsChanged.disconnect()
        self.sigMwSweepParamsChanged.disconnect()
        self.sigRuntimeChanged.disconnect()
        self.sigFrameRateChanged.disconnect()
        self.sigGPIOSettingsChanged.disconnect()
        self.sigSaveMeasurement.disconnect()
        self.sigChangeMeasurementType.disconnect()
        # self.sigMeasurementChanged.disconnect()
        self._mw.xy_cb_manual_RadioButton.clicked.disconnect()
        self._mw.xy_cb_centiles_RadioButton.clicked.disconnect()
        self._mw.clear_odmr_PushButton.clicked.disconnect()
        self._mw.action_run_stop.triggered.disconnect()
        self._mw.action_resume_odmr.triggered.disconnect()
        self._mw.action_Save.triggered.disconnect()
        self._mw.action_toggle_cw.triggered.disconnect()
        self._mw.action_RestoreDefault.triggered.disconnect()
        self._mw.do_fit_PushButton.clicked.disconnect()
        self._mw.cw_frequency_DoubleSpinBox.editingFinished.disconnect()
        self._mw.gainSpinBox.editingFinished.disconnect()
        self._mw.triggerMode_checkBox.stateChanged.disconnect()
        self._mw.exposuremode_comboBox.currentTextChanged.disconnect()
        self._mw.exposureDSpinBox.editingFinished.disconnect()
        self._mw.x_pixels_SpinBox.editingFinished.disconnect()
        self._mw.y_pixels_SpinBox.editingFinished.disconnect()
        self._mw.offset_x_spinBox.editingFinished.disconnect()
        self._mw.offset_y_spinBox.editingFinished.disconnect()
        self._mw.pixel_format_comboBox.currentTextChanged.disconnect()
        self._mw.plot_pixel_x_spinBox.editingFinished.disconnect()
        self._mw.plot_pixel_y_spinBox.editingFinished.disconnect()

        dspinbox_dict = self.get_all_dspinboxes_from_groupbox()
        for identifier_name in dspinbox_dict:
            dspinbox_type_list = dspinbox_dict[identifier_name]
            [dspinbox_type.editingFinished.disconnect() for dspinbox_type in dspinbox_type_list]

        self._mw.cw_power_DoubleSpinBox.editingFinished.disconnect()
        self._mw.sweep_power_DoubleSpinBox.editingFinished.disconnect()
        self._mw.runtime_DoubleSpinBox.editingFinished.disconnect()
        self._mw.xy_cb_max_DoubleSpinBox.valueChanged.disconnect()
        self._mw.xy_cb_min_DoubleSpinBox.valueChanged.disconnect()
        self._mw.xy_cb_high_percentile_DoubleSpinBox.valueChanged.disconnect()
        self._mw.xy_cb_low_percentile_DoubleSpinBox.valueChanged.disconnect()
        self._fsd.sigFitsUpdated.disconnect()
        self._mw.fit_range_SpinBox.editingFinished.disconnect()
        self._mw.action_FitSettings.triggered.disconnect()
        self.saveWindowGeometry(self._mw)
        self._mw.close()
        return 0

    def show(self):
        """Make window visible and put it above all other windows.
        """
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def _menu_settings(self):
        """ Open the settings menu """
        self._sd.exec_()

    def _menu_channel_settings(self):
        """ Open the channel settings menu """
        self._cs.exec_()

    def add_ranges_gui_elements_clicked(self):
        """
        When button >>add range<< is pushed add some buttons to the gui and connect accordingly to the
        logic.
        :return:
        """
        # make sure the logic keeps track
        groupBox = self._mw.measurement_control_DockWidget.ranges_GroupBox
        gridLayout = groupBox.layout()
        constraints = self._widefield_logic.get_hw_constraints()

        insertion_row = self._widefield_logic.ranges
        # start
        start_label = QtWidgets.QLabel(groupBox)
        start_label.setText('Start:')
        setattr(self._mw.measurement_control_DockWidget, 'start_label_{}'.format(insertion_row), start_label)
        start_freq_DoubleSpinBox = ScienDSpinBox(groupBox)
        start_freq_DoubleSpinBox.setSuffix('Hz')
        start_freq_DoubleSpinBox.setMaximum(constraints.max_frequency)
        start_freq_DoubleSpinBox.setMinimum(constraints.min_frequency)
        start_freq_DoubleSpinBox.setMinimumSize(QtCore.QSize(80, 0))
        start_freq_DoubleSpinBox.setValue(self._widefield_logic.mw_starts[0])
        start_freq_DoubleSpinBox.setMinimumWidth(75)
        start_freq_DoubleSpinBox.setMaximumWidth(100)
        start_freq_DoubleSpinBox.editingFinished.connect(self.change_sweep_params)
        setattr(self._mw.measurement_control_DockWidget, 'start_freq_DoubleSpinBox_{}'.format(insertion_row),
                start_freq_DoubleSpinBox)
        gridLayout.addWidget(start_label, insertion_row, 1, 1, 1)
        gridLayout.addWidget(start_freq_DoubleSpinBox, insertion_row, 2, 1, 1)

        # step
        step_label = QtWidgets.QLabel(groupBox)
        step_label.setText('Step:')
        setattr(self._mw.measurement_control_DockWidget, 'step_label_{}'.format(insertion_row), step_label)
        step_freq_DoubleSpinBox = ScienDSpinBox(groupBox)
        step_freq_DoubleSpinBox.setSuffix('Hz')
        step_freq_DoubleSpinBox.setMaximum(100e9)
        step_freq_DoubleSpinBox.setMinimumSize(QtCore.QSize(80, 0))
        step_freq_DoubleSpinBox.setValue(self._widefield_logic.mw_steps[0])
        step_freq_DoubleSpinBox.setMinimumWidth(75)
        step_freq_DoubleSpinBox.setMaximumWidth(100)
        step_freq_DoubleSpinBox.editingFinished.connect(self.change_sweep_params)
        setattr(self._mw.measurement_control_DockWidget, 'step_freq_DoubleSpinBox_{}'.format(insertion_row),
                step_freq_DoubleSpinBox)
        gridLayout.addWidget(step_label, insertion_row, 3, 1, 1)
        gridLayout.addWidget(step_freq_DoubleSpinBox, insertion_row, 4, 1, 1)

        # stop
        stop_label = QtWidgets.QLabel(groupBox)
        stop_label.setText('Stop:')
        setattr(self._mw.measurement_control_DockWidget, 'stop_label_{}'.format(insertion_row), stop_label)
        stop_freq_DoubleSpinBox = ScienDSpinBox(groupBox)
        stop_freq_DoubleSpinBox.setSuffix('Hz')
        stop_freq_DoubleSpinBox.setMaximum(constraints.max_frequency)
        stop_freq_DoubleSpinBox.setMinimum(constraints.min_frequency)
        stop_freq_DoubleSpinBox.setMinimumSize(QtCore.QSize(80, 0))
        stop_freq_DoubleSpinBox.setValue(self._widefield_logic.mw_stops[0])
        stop_freq_DoubleSpinBox.setMinimumWidth(75)
        stop_freq_DoubleSpinBox.setMaximumWidth(100)
        stop_freq_DoubleSpinBox.editingFinished.connect(self.change_sweep_params)
        setattr(self._mw.measurement_control_DockWidget, 'stop_freq_DoubleSpinBox_{}'.format(insertion_row),
                stop_freq_DoubleSpinBox)

        gridLayout.addWidget(stop_label, insertion_row, 5, 1, 1)
        gridLayout.addWidget(stop_freq_DoubleSpinBox, insertion_row, 6, 1, 1)

        starts = self.get_frequencies_from_spinboxes('start')
        stops = self.get_frequencies_from_spinboxes('stop')
        steps = self.get_frequencies_from_spinboxes('step')
        power = self._mw.sweep_power_DoubleSpinBox.value()

        self.sigMwSweepParamsChanged.emit(starts, stops, steps, power)
        self._mw.fit_range_SpinBox.setMaximum(self._widefield_logic.ranges)
        self._widefield_logic.ranges += 1

        # remove stuff that remained from the old range that might have been in place there
        key = 'channel: {0}, range: {1}'.format(self.display_channel, self._widefield_logic.ranges - 1)
        if key in self._widefield_logic.fits_performed:
            self._widefield_logic.fits_performed.pop(key)
        return

    def remove_ranges_gui_elements_clicked(self):
        if self._widefield_logic.ranges == 1:
            return

        remove_row = self._widefield_logic.ranges - 1

        groupBox = self._mw.measurement_control_DockWidget.ranges_GroupBox
        gridLayout = groupBox.layout()

        object_dict = self.get_objects_from_groupbox_row(remove_row)

        for object_name in object_dict:
            if 'DoubleSpinBox' in object_name:
                object_dict[object_name].editingFinished.disconnect()
            object_dict[object_name].hide()
            gridLayout.removeWidget(object_dict[object_name])
            del self._mw.measurement_control_DockWidget.__dict__[object_name]

        starts = self.get_frequencies_from_spinboxes('start')
        stops = self.get_frequencies_from_spinboxes('stop')
        steps = self.get_frequencies_from_spinboxes('step')
        power = self._mw.sweep_power_DoubleSpinBox.value()
        self.sigMwSweepParamsChanged.emit(starts, stops, steps, power)

        # in case the removed range is the one selected for fitting right now adjust the value
        self._widefield_logic.ranges -= 1
        max_val = self._widefield_logic.ranges - 1
        self._mw.fit_range_SpinBox.setMaximum(max_val)
        if self._widefield_logic.range_to_fit > max_val:
            self._widefield_logic.range_to_fit = max_val

        self._mw.fit_range_SpinBox.setMaximum(max_val)
        
        return

    def get_objects_from_groupbox_row(self, row):
        # get elements from the row
        # first strings

        start_label_str = 'start_label_{}'.format(row)
        step_label_str = 'step_label_{}'.format(row)
        stop_label_str = 'stop_label_{}'.format(row)

        # get widgets
        start_freq_DoubleSpinBox_str = 'start_freq_DoubleSpinBox_{}'.format(row)
        step_freq_DoubleSpinBox_str = 'step_freq_DoubleSpinBox_{}'.format(row)
        stop_freq_DoubleSpinBox_str = 'stop_freq_DoubleSpinBox_{}'.format(row)

        # now get the objects
        start_label = getattr(self._mw.measurement_control_DockWidget, start_label_str)
        step_label = getattr(self._mw.measurement_control_DockWidget, step_label_str)
        stop_label = getattr(self._mw.measurement_control_DockWidget, stop_label_str)

        start_freq_DoubleSpinBox = getattr(self._mw.measurement_control_DockWidget, start_freq_DoubleSpinBox_str)
        step_freq_DoubleSpinBox = getattr(self._mw.measurement_control_DockWidget, step_freq_DoubleSpinBox_str)
        stop_freq_DoubleSpinBox = getattr(self._mw.measurement_control_DockWidget, stop_freq_DoubleSpinBox_str)

        return_dict = {start_label_str: start_label, step_label_str: step_label,
                       stop_label_str: stop_label,
                       start_freq_DoubleSpinBox_str: start_freq_DoubleSpinBox,
                       step_freq_DoubleSpinBox_str: step_freq_DoubleSpinBox,
                       stop_freq_DoubleSpinBox_str: stop_freq_DoubleSpinBox
                       }

        return return_dict

    def get_freq_dspinboxes_from_groubpox(self, identifier):
        dspinboxes = []
        for name in self._mw.measurement_control_DockWidget.__dict__:
            box_name = identifier + '_freq_DoubleSpinBox'
            if box_name in name:
                freq_DoubleSpinBox = getattr(self._mw.measurement_control_DockWidget, name)
                dspinboxes.append(freq_DoubleSpinBox)

        return dspinboxes

    def get_all_dspinboxes_from_groupbox(self):
        identifiers = ['start', 'step', 'stop']

        all_spinboxes = {}
        for identifier in identifiers:
            all_spinboxes[identifier] = self.get_freq_dspinboxes_from_groubpox(identifier)

        return all_spinboxes

    def get_frequencies_from_spinboxes(self, identifier):
        dspinboxes = self.get_freq_dspinboxes_from_groubpox(identifier)
        freqs = [dspinbox.value() for dspinbox in dspinboxes]
        return freqs

    def run_stop_odmr(self, is_checked):
        """ Manages what happens if odmr scan is started/stopped. """
        if is_checked:
            # change the axes appearance according to input values:
            self._mw.action_run_stop.setEnabled(False)
            self._mw.action_resume_odmr.setEnabled(False)
            self._mw.action_toggle_cw.setEnabled(False)
            self._mw.odmr_PlotWidget.removeItem(self.odmr_fit_image)
            self._mw.cw_power_DoubleSpinBox.setEnabled(False)
            self._mw.sweep_power_DoubleSpinBox.setEnabled(False)
            self._mw.cw_frequency_DoubleSpinBox.setEnabled(False)
            self._mw.gainSpinBox.setEnabled(False)
            self._mw.triggerMode_checkBox.stateChanged.setEnabled(False)
            self._mw.exposuremode_comboBox.currentTextChanged.setEnabled(False)
            self._mw.exposureDSpinBox.setEnabled(False)
            self._mw.x_pixels_SpinBox.setEnabled(False)
            self._mw.y_pixels_SpinBox.setEnabled(False)
            self._mw.offset_x_spinBox.setEnabled(False)
            self._mw.offset_y_spinBox.setEnabled(False)
            self._mw.pixel_format_comboBox.currentTextChanged.setEnabled(False)
            self._mw.plot_pixel_x_spinBox.setEnabled(False)
            self._mw.plot_pixel_y_spinBox.setEnabled(False)
            
            dspinbox_dict = self.get_all_dspinboxes_from_groupbox()
            for identifier_name in dspinbox_dict:
                dspinbox_type_list = dspinbox_dict[identifier_name]
                [dspinbox_type.setEnabled(False) for dspinbox_type in dspinbox_type_list]
            self._mw.measurement_control_DockWidget.add_range_button.setEnabled(False)
            self._mw.measurement_control_DockWidget.remove_range_button.setEnabled(False)
            self._mw.runtime_DoubleSpinBox.setEnabled(False)
            self._sd.frame_rate_DoubleSpinBox.setEnabled(False)
            self.sigStartOdmrScan.emit()
        else:
            self._mw.action_run_stop.setEnabled(False)
            self._mw.action_resume_odmr.setEnabled(False)
            self._mw.action_toggle_cw.setEnabled(False)
            self.sigStopOdmrScan.emit()
        return

    def resume_odmr(self, is_checked):
        if is_checked:
            self._mw.action_run_stop.setEnabled(False)
            self._mw.action_resume_odmr.setEnabled(False)
            self._mw.action_toggle_cw.setEnabled(False)
            self._mw.cw_power_DoubleSpinBox.setEnabled(False)
            self._mw.sweep_power_DoubleSpinBox.setEnabled(False)
            self._mw.cw_frequency_DoubleSpinBox.setEnabled(False)
            self._mw.gainSpinBox.setEnabled(False)
            self._mw.triggerMode_checkBox.stateChanged.setEnabled(False)
            self._mw.exposuremode_comboBox.currentTextChanged.setEnabled(False)
            self._mw.exposureDSpinBox.setEnabled(False)
            self._mw.x_pixels_SpinBox.setEnabled(False)
            self._mw.y_pixels_SpinBox.setEnabled(False)
            self._mw.offset_x_spinBox.setEnabled(False)
            self._mw.offset_y_spinBox.setEnabled(False)
            self._mw.pixel_format_comboBox.currentTextChanged.setEnabled(False)
            self._mw.plot_pixel_x_spinBox.setEnabled(False)
            self._mw.plot_pixel_y_spinBox.setEnabled(False)

            dspinbox_dict = self.get_all_dspinboxes_from_groupbox()
            for identifier_name in dspinbox_dict:
                dspinbox_type_list = dspinbox_dict[identifier_name]
                [dspinbox_type.setEnabled(False) for dspinbox_type in dspinbox_type_list]
            self._mw.measurement_control_DockWidget.add_range_button.setEnabled(False)
            self._mw.measurement_control_DockWidget.remove_range_button.setEnabled(False)
            self._mw.runtime_DoubleSpinBox.setEnabled(False)
            self._sd.frame_rate_DoubleSpinBox.setEnabled(False)
            self.sigContinueOdmrScan.emit()
        else:
            self._mw.action_run_stop.setEnabled(False)
            self._mw.action_resume_odmr.setEnabled(False)
            self._mw.action_toggle_cw.setEnabled(False)
            self.sigStopOdmrScan.emit()
        return

    def toggle_cw_mode(self, is_checked):
        """ Starts or stops CW microwave output if no measurement is running. """
        if is_checked:
            self._mw.action_run_stop.setEnabled(False)
            self._mw.action_resume_odmr.setEnabled(False)
            self._mw.action_toggle_cw.setEnabled(False)
            self._mw.cw_power_DoubleSpinBox.setEnabled(False)
            self._mw.cw_frequency_DoubleSpinBox.setEnabled(False)
            self.sigCwMwOn.emit()
        else:
            self._mw.action_toggle_cw.setEnabled(False)
            self.sigMwOff.emit()
        return

    def update_status(self, mw_mode, is_running):
        """
        Update the display for a change in the microwave status (mode and output).

        @param str mw_mode: is the microwave output active?
        @param bool is_running: is the microwave output active?
        """
        # Block signals from firing
        self._mw.action_run_stop.blockSignals(True)
        self._mw.action_resume_odmr.blockSignals(True)
        self._mw.action_toggle_cw.blockSignals(True)

        # Update measurement status (activate/deactivate widgets/actions)
        if is_running:
            self._mw.action_resume_odmr.setEnabled(False)
            self._mw.cw_power_DoubleSpinBox.setEnabled(False)
            self._mw.cw_frequency_DoubleSpinBox.setEnabled(False)
            self._mw.gainSpinBox.setEnabled(False)
            self._mw.triggerMode_checkBox.stateChanged.setEnabled(False)
            self._mw.exposuremode_comboBox.currentTextChanged.setEnabled(False)
            self._mw.exposureDSpinBox.setEnabled(False)
            self._mw.x_pixels_SpinBox.setEnabled(False)
            self._mw.y_pixels_SpinBox.setEnabled(False)
            self._mw.offset_x_spinBox.setEnabled(False)
            self._mw.offset_y_spinBox.setEnabled(False)
            self._mw.pixel_format_comboBox.currentTextChanged.setEnabled(False)
            self._mw.plot_pixel_x_spinBox.setEnabled(False)
            self._mw.plot_pixel_y_spinBox.setEnabled(False)
            if mw_mode != 'cw':
                self._mw.clear_odmr_PushButton.setEnabled(True)
                self._mw.action_run_stop.setEnabled(True)
                self._mw.action_toggle_cw.setEnabled(False)
                dspinbox_dict = self.get_all_dspinboxes_from_groupbox()
                for identifier_name in dspinbox_dict:
                    dspinbox_type_list = dspinbox_dict[identifier_name]
                    [dspinbox_type.setEnabled(False) for dspinbox_type in dspinbox_type_list]
                self._mw.measurement_control_DockWidget.add_range_button.setEnabled(False)
                self._mw.measurement_control_DockWidget.remove_range_button.setEnabled(False)
                self._mw.sweep_power_DoubleSpinBox.setEnabled(False)
                self._mw.runtime_DoubleSpinBox.setEnabled(False)
                self._sd.frame_rate_DoubleSpinBox.setEnabled(False)
                self._mw.action_run_stop.setChecked(True)
                self._mw.action_resume_odmr.setChecked(True)
                self._mw.action_toggle_cw.setChecked(False)
            else:
                self._mw.clear_odmr_PushButton.setEnabled(False)
                self._mw.action_run_stop.setEnabled(False)
                self._mw.action_toggle_cw.setEnabled(True)
                dspinbox_dict = self.get_all_dspinboxes_from_groupbox()
                for identifier_name in dspinbox_dict:
                    dspinbox_type_list = dspinbox_dict[identifier_name]
                    [dspinbox_type.setEnabled(True) for dspinbox_type in dspinbox_type_list]
                self._mw.measurement_control_DockWidget.add_range_button.setEnabled(True)
                self._mw.measurement_control_DockWidget.remove_range_button.setEnabled(True)
                self._mw.sweep_power_DoubleSpinBox.setEnabled(True)
                self._mw.runtime_DoubleSpinBox.setEnabled(True)
                self._sd.frame_rate_DoubleSpinBox.setEnabled(True)
                self._mw.action_run_stop.setChecked(False)
                self._mw.action_resume_odmr.setChecked(False)
                self._mw.action_toggle_cw.setChecked(True)
        else:
            self._mw.action_resume_odmr.setEnabled(True)
            self._mw.cw_power_DoubleSpinBox.setEnabled(True)
            self._mw.sweep_power_DoubleSpinBox.setEnabled(True)
            self._mw.cw_frequency_DoubleSpinBox.setEnabled(True)
            self._mw.gainSpinBox.setEnabled(True)
            self._mw.triggerMode_checkBox.stateChanged.setEnabled(True)
            self._mw.exposuremode_comboBox.currentTextChanged.setEnabled(True)
            self._mw.exposureDSpinBox.setEnabled(True)
            self._mw.x_pixels_SpinBox.setEnabled(True)
            self._mw.y_pixels_SpinBox.setEnabled(True)
            self._mw.offset_x_spinBox.setEnabled(True)
            self._mw.offset_y_spinBox.setEnabled(True)
            self._mw.pixel_format_comboBox.currentTextChanged.setEnabled(True)
            self._mw.plot_pixel_x_spinBox.setEnabled(True)
            self._mw.plot_pixel_y_spinBox.setEnabled(True)
            self._mw.clear_odmr_PushButton.setEnabled(False)
            self._mw.action_run_stop.setEnabled(True)
            self._mw.action_toggle_cw.setEnabled(True)
            dspinbox_dict = self.get_all_dspinboxes_from_groupbox()
            for identifier_name in dspinbox_dict:
                dspinbox_type_list = dspinbox_dict[identifier_name]
                [dspinbox_type.setEnabled(True) for dspinbox_type in dspinbox_type_list]
            if self._widefield_logic.mw_scanmode.name == 'SWEEP':
                self._mw.measurement_control_DockWidget.add_range_button.setDisabled(True)
            elif self._widefield_logic.mw_scanmode.name == 'LIST':
                self._mw.measurement_control_DockWidget.add_range_button.setEnabled(True)
            self._mw.measurement_control_DockWidget.remove_range_button.setEnabled(True)
            self._mw.runtime_DoubleSpinBox.setEnabled(True)
            self._sd.frame_rate_DoubleSpinBox.setEnabled(True)
            self._mw.action_run_stop.setChecked(False)
            self._mw.action_resume_odmr.setChecked(False)
            self._mw.action_toggle_cw.setChecked(False)

        # Unblock signal firing
        self._mw.action_run_stop.blockSignals(False)
        self._mw.action_resume_odmr.blockSignals(False)
        self._mw.action_toggle_cw.blockSignals(False)
        return

    def clear_odmr_data(self):
        """ Clear the ODMR data. """
        self.sigClearData.emit()
        return

    def update_plots(self, odmr_data_x, odmr_data_y):
        """ Refresh the plot widgets with new data. """
        # Update mean signal plot
        self.odmr_image.setData(odmr_data_x, odmr_data_y[self.display_channel])

    def update_channel(self, index):
        self.display_channel = int(
            self._mw.odmr_channel_ComboBox.itemData(index, QtCore.Qt.UserRole))
        self.update_plots(
            self._widefield_logic.odmr_plot_x,
            self._widefield_logic.odmr_plot_y)

    def update_colorbar(self, cb_range):
        """
        Update the colorbar to a new range.

        @param list cb_range: List or tuple containing the min and max values for the cb range
        """
        self.xy_cb.refresh_colorbar(cb_range[0], cb_range[1])
        return

    def restore_defaultview(self):
        self._mw.restoreGeometry(self.mwsettings.value("geometry", ""))
        self._mw.restoreState(self.mwsettings.value("windowState", ""))

    def update_elapsedtime(self, elapsed_time, scanned_lines):
        """ Updates current elapsed measurement time and completed frequency sweeps """
        self._mw.elapsed_time_lcd.display(int(np.rint(elapsed_time)))
        self._mw.elapsed_sweeps_lcd.display(scanned_lines)
        return

    def update_settings(self):
        """ Write the new settings from the gui to the file. """
        frame_rate = self._sd.frame_rate_DoubleSpinBox.value()
        self.sigFrameRateChanged.emit(frame_rate)
        return

    def reject_settings(self):
        """ Keep the old settings and restores the old settings in the gui. """
        self._sd.frame_rate_DoubleSpinBox.setValue(self._widefield_logic.frame_rate)
        return
    
    def update_channel_settings(self):
        """ Write the new channel settings from the gui to the file. """
        input_channel_parameters = dict()
        output_channel_parameters = dict()

        input_channel_parameters['LineMode'] = "Input"
        input_channel_parameters['LineSelector'] = int(self._cs.inputline_comboBox.currentText())
        input_channel_parameters['TriggerSelector'] = self._cs.inputtriggerselector_comboBox.currentText()
        input_channel_parameters['TriggerActivation'] = self._cs.inputtriggeractivation_comboBox.currentText()
        input_channel_parameters['TriggerDelay'] = self._cs.inputTriggerDelay_DoubleSpinBox.value()
        input_channel_parameters['LineInverter'] = self._cs.inputlineinverter_checkBox.isChecked()

        output_channel_parameters['LineMode'] = "Output"
        output_channel_parameters['LineSelector'] = int(self._cs.outputline_comboBox.currentText())
        output_channel_parameters['LineInverter'] = self._cs.outputlineinverter_checkBox.isChecked()
        output_channel_parameters['MinimumOutputPulse'] = self._cs.outputpulsemin_DoubleSpinBox.value()
        output_channel_parameters['LineSource'] = self._cs.outputlinesource_comboBox.isChecked()

        self.sigGPIOSettingsChanged.emit(input_channel_parameters, output_channel_parameters)
        return

    def reject_channel_settings(self):
        """ Keep the old channel settings and restores the old settings in the gui. """
        self._sd.frame_rate_DoubleSpinBox.setValue(self._widefield_logic.frame_rate)
        return

    def do_fit(self):
        fit_function = self._mw.fit_methods_ComboBox.getCurrentFit()[0]
        self.sigDoFit.emit(fit_function, None, None, self._mw.odmr_channel_ComboBox.currentIndex(),
                           self._mw.fit_range_SpinBox.value())
        return

    def update_fit(self, x_data, y_data, result_str_dict, current_fit):
        """ Update the shown fit. """
        if current_fit != 'No Fit':
            # display results as formatted text
            self._mw.odmr_fit_results_DisplayWidget.clear()
            try:
                formated_results = units.create_formatted_output(result_str_dict)
            except:
                formated_results = 'this fit does not return formatted results'
            self._mw.odmr_fit_results_DisplayWidget.setPlainText(formated_results)

        self._mw.fit_methods_ComboBox.blockSignals(True)
        self._mw.fit_methods_ComboBox.setCurrentFit(current_fit)
        self._mw.fit_methods_ComboBox.blockSignals(False)

        # check which Fit method is used and remove or add again the
        # odmr_fit_image, check also whether a odmr_fit_image already exists.
        if current_fit != 'No Fit':
            self.odmr_fit_image.setData(x=x_data, y=y_data)
            if self.odmr_fit_image not in self._mw.odmr_PlotWidget.listDataItems():
                self._mw.odmr_PlotWidget.addItem(self.odmr_fit_image)
        else:
            if self.odmr_fit_image in self._mw.odmr_PlotWidget.listDataItems():
                self._mw.odmr_PlotWidget.removeItem(self.odmr_fit_image)

        self._mw.odmr_PlotWidget.getViewBox().updateAutoRange()
        return

    def update_fit_range(self):
        self._widefield_logic.range_to_fit = self._mw.fit_range_SpinBox.value()
        return
    
    def update_parameter(self, param_dict):
        """ Update the parameter display in the GUI.

        @param param_dict:
        @return:

        Any change event from the logic should call this update function.
        The update will block the GUI signals from emitting a change back to the
        logic.
        """
        param = param_dict.get('sweep_mw_power')
        if param is not None:
            self._mw.sweep_power_DoubleSpinBox.blockSignals(True)
            self._mw.sweep_power_DoubleSpinBox.setValue(param)
            self._mw.sweep_power_DoubleSpinBox.blockSignals(False)

        mw_starts = param_dict.get('mw_starts')
        mw_steps = param_dict.get('mw_steps')
        mw_stops = param_dict.get('mw_stops')

        if mw_starts is not None:
            start_frequency_boxes = self.get_freq_dspinboxes_from_groubpox('start')
            for mw_start, start_frequency_box in zip(mw_starts, start_frequency_boxes):
                start_frequency_box.blockSignals(True)
                start_frequency_box.setValue(mw_start)
                start_frequency_box.blockSignals(False)

        if mw_steps is not None:
            step_frequency_boxes = self.get_freq_dspinboxes_from_groubpox('step')
            for mw_step, step_frequency_box in zip(mw_steps, step_frequency_boxes):
                step_frequency_box.blockSignals(True)
                step_frequency_box.setValue(mw_step)
                step_frequency_box.blockSignals(False)

        if mw_stops is not None:
            stop_frequency_boxes = self.get_freq_dspinboxes_from_groubpox('stop')
            for mw_stop, stop_frequency_box in zip(mw_stops, stop_frequency_boxes):
                stop_frequency_box.blockSignals(True)
                stop_frequency_box.setValue(mw_stop)
                stop_frequency_box.blockSignals(False)

        param = param_dict.get('run_time')
        if param is not None:
            self._mw.runtime_DoubleSpinBox.blockSignals(True)
            self._mw.runtime_DoubleSpinBox.setValue(param)
            self._mw.runtime_DoubleSpinBox.blockSignals(False)

        param = param_dict.get('frame_rate')
        if param is not None:
            self._sd.frame_rate_DoubleSpinBox.blockSignals(True)
            self._sd.frame_rate_DoubleSpinBox.setValue(param)
            self._sd.frame_rate_DoubleSpinBox.blockSignals(False)

        param = param_dict.get('cw_mw_frequency')
        if param is not None:
            self._mw.cw_frequency_DoubleSpinBox.blockSignals(True)
            self._mw.cw_frequency_DoubleSpinBox.setValue(param)
            self._mw.cw_frequency_DoubleSpinBox.blockSignals(False)

        param = param_dict.get('cw_mw_power')
        if param is not None:
            self._mw.cw_power_DoubleSpinBox.blockSignals(True)
            self._mw.cw_power_DoubleSpinBox.setValue(param)
            self._mw.cw_power_DoubleSpinBox.blockSignals(False)

        param = param_dict.get('gain')
        if param is not None:
            self._mw.gainSpinBox.blockSignals(True)
            self._mw.gainSpinBox.setValue(param)
            self._mw.gainSpinBox.blockSignals(False)

        param = param_dict.get('trigger_mode')
        if param is not None:
            self._mw.triggerMode_checkBox.blockSignals(True)
            self._mw.triggerMode_checkBox.setChecked(param)
            self._mw.triggerMode_checkBox.blockSignals(False)

        param = param_dict.get('exposure_mode')
        if param is not None:
            self._mw.exposuremode_comboBox.blockSignals(True)
            self._mw.exposuremode_comboBox.setCurrentText(param)
            self._mw.exposuremode_comboBox.blockSignals(False)
        
        param = param_dict.get('exposure_time')
        if param is not None:
            self._mw.exposureDSpinBox.blockSignals(True)
            self._mw.exposureDSpinBox.setValue(param)
            self._mw.exposureDSpinBox.blockSignals(False)
        
        param = param_dict.get('image_size')
        if param is not None:
            self._mw.x_pixels_SpinBox.blockSignals(True)
            self._mw.x_pixels_SpinBox.setValue(param[0])
            self._mw.x_pixels_SpinBox.blockSignals(False)

            self._mw.y_pixels_SpinBox.blockSignals(True)
            self._mw.y_pixels_SpinBox.setValue(param[1])
            self._mw.y_pixels_SpinBox.blockSignals(False)
        
        param = param_dict.get('image_offset')
        if param is not None:
            self._mw.offset_x_spinBox.blockSignals(True)
            self._mw.offset_x_spinBox.setValue(param[0])
            self._mw.offset_x_spinBox.blockSignals(False)

            self._mw.offset_y_spinBox.blockSignals(True)
            self._mw.offset_y_spinBox.setValue(param[1])
            self._mw.offset_y_spinBox.blockSignals(False)
        
        param = param_dict.get('pixel_format')
        if param is not None:
            self._mw.pixel_format_comboBox.blockSignals(True)
            self._mw.pixel_format_comboBox.setCurrentText(param)
            self._mw.pixel_format_comboBox.blockSignals(False)
        
        param = param_dict.get('plot_pixel')
        if param is not None:
            self._mw.plot_pixel_x_spinBox.blockSignals(True)
            self._mw.plot_pixel_x_spinBox.setValue(param[0])
            self._mw.plot_pixel_x_spinBox.blockSignals(False)

            self._mw.plot_pixel_y_spinBox.blockSignals(True)
            self._mw.plot_pixel_y_spinBox.setValue(param[1])
            self._mw.plot_pixel_y_spinBox.blockSignals(False)

        return

    def update_camera_limits(self, constraints):
        """ Update the limits on all the camera properties """

        
        limits = constraints[0]
        input_limits = constraints[1]
        output_limits = constraints[2] 

        self._mw.gainSpinBox.setMinimum(limits["gain"][0])
        self._mw.gainSpinBox.setMaximum(limits["gain"][1])
        
        self._mw.exposureDSpinBox.setMinimum(limits["exposure_time"][0])
        self._mw.exposureDSpinBox.setMaximum(limits["exposure_time"][1])

        self._mw.x_pixels_SpinBox.setMinimum(limits["image_width"][0])
        self._mw.x_pixels_SpinBox.setMaximum(limits["image_width"][1])

        self._mw.y_pixels_SpinBox.setMinimum(limits["image_height"][0])
        self._mw.y_pixels_SpinBox.setMaximum(limits["image_height"][1])

        self._mw.offset_x_spinBox.setMinimum(limits["offset_x"][0])
        self._mw.offset_x_spinBox.setMaximum(limits["offset_x"][1])

        self._mw.offset_y_spinBox.setMinimum(limits["offset_y"][0])
        self._mw.offset_y_spinBox.setMaximum(limits["offset_y"][1])

        self._mw.plot_pixel_x_spinBox.setMinimum(limits["plot_pixel_x"][0])
        self._mw.plot_pixel_x_spinBox.setMaximum(limits["plot_pixel_x"][1])

        self._mw.plot_pixel_y_spinBox.setMinimum(limits["plot_pixel_y"][0])
        self._mw.plot_pixel_y_spinBox.setMaximum(limits["plot_pixel_y"][1])

        self._mw.exposuremode_comboBox.blockSignals(True)
        self._mw.exposuremode_comboBox.clear()
        for mode in limits["exposure_modes"]:
            self._mw.exposuremode_comboBox.addItem(mode)
        self._mw.exposuremode_comboBox.setCurrentText(self._widefield_logic.exposure_mode)
        self._mw.exposuremode_comboBox.blockSignals(False)

        self._mw.pixel_format_comboBox.blockSignals(True)
        self._mw.pixel_format_comboBox.clear()
        for mode in limits["pixel_formats"]:
            self._mw.pixel_format_comboBox.addItem(mode)
        self._mw.pixel_format_comboBox.setCurrentText(self._widefield_logic.pixel_format)
        self._mw.pixel_format_comboBox.blockSignals(False)

        self._cs.inputline_comboBox.blockSignals(True)
        self._cs.inputline_comboBox.clear()
        for mode in input_limits["LineSelector"]:
            self._cs.inputline_comboBox.addItem(str(mode))
        self._cs.inputline_comboBox.setCurrentText(str(self._widefield_logic.input_line))
        self._cs.inputline_comboBox.blockSignals(False)

        self._cs.inputtriggerselector_comboBox.blockSignals(True)
        self._cs.inputtriggerselector_comboBox.clear()
        for mode in input_limits["TriggerSelectors"]:
            self._cs.inputtriggerselector_comboBox.addItem(mode)
        self._cs.inputtriggerselector_comboBox.setCurrentText(self._widefield_logic.input_line_trigger_selector)
        self._cs.inputtriggerselector_comboBox.blockSignals(False)

        self._cs.inputtriggeractivation_comboBox.blockSignals(True)
        self._cs.inputtriggeractivation_comboBox.clear()
        for mode in input_limits["TriggerActivations"]:
            self._cs.inputtriggeractivation_comboBox.addItem(mode)
        self._cs.inputtriggeractivation_comboBox.setCurrentText(self._widefield_logic.input_line_activation)
        self._cs.inputtriggeractivation_comboBox.blockSignals(False)


        self._cs.inputTriggerDelay_DoubleSpinBox.setMinimum(input_limits["TriggerDelays"][0])
        self._cs.inputTriggerDelay_DoubleSpinBox.setMaximum(input_limits["TriggerDelays"][1])

        self._cs.outputline_comboBox.blockSignals(True)
        self._cs.outputline_comboBox.clear()
        for mode in output_limits["LineSelector"]:
            self._cs.outputline_comboBox.addItem(str(mode))
        self._cs.outputline_comboBox.setCurrentText(str(self._widefield_logic.output_line))
        self._cs.outputline_comboBox.blockSignals(False)

        self._cs.outputlinesource_comboBox.blockSignals(True)
        self._cs.outputlinesource_comboBox.clear()
        for mode in output_limits["LineSource"]:
            self._cs.outputlinesource_comboBox.addItem(mode)
        self._cs.outputlinesource_comboBox.setCurrentText(self._widefield_logic.output_line_source)
        self._cs.outputlinesource_comboBox.blockSignals(False)

        self._cs.outputpulsemin_DoubleSpinBox.setMinimum(output_limits["MinimumOutputPulse"][0])
        self._cs.outputpulsemin_DoubleSpinBox.setMaximum(output_limits["MinimumOutputPulse"][1])

    ############################################################################
    #                           Change Methods                                 #
    ############################################################################

    def change_cw_params(self):
        """ Change CW frequency and power of microwave source """
        frequency = self._mw.cw_frequency_DoubleSpinBox.value()
        power = self._mw.cw_power_DoubleSpinBox.value()
        self.sigMwCwParamsChanged.emit(frequency, power)
        return

    def change_camera_params(self):
        """ Change camera properties """

        cam_params = dict()
        cam_params["gain"] = self._mw.gainSpinBox.value()
        cam_params["trigger_mode"] = self._mw.triggerMode_checkBox.isChecked()
        cam_params["exposure_mode"] = self._mw.exposuremode_comboBox.currentText()
        cam_params["exposure_time"] = self._mw.exposureDSpinBox.value()
        cam_params["image_size"] = (self._mw.x_pixels_SpinBox.value(), self._mw.y_pixels_SpinBox.value())
        cam_params["image_offset"] = (self._mw.offset_x_spinBox.value(), self._mw.offset_y_spinBox.value())
        cam_params["pixel_format"] = self._mw.pixel_format_comboBox.currentText()
        cam_params["plot_pixel"] = (self._mw.plot_pixel_x_spinBox.value(), self._mw.plot_pixel_y_spinBox.value())

        self.sigCamParamsChanged.emit(cam_params)

    def change_sweep_params(self):
        """ Change start, stop and step frequency of frequency sweep """
        starts = []
        steps = []
        stops = []

        num = self._widefield_logic.ranges

        for counter in range(num):
            # construct strings
            start, stop, step = self.get_frequencies_from_row(counter)

            starts.append(start)
            steps.append(step)
            stops.append(stop)

        power = self._mw.sweep_power_DoubleSpinBox.value()
        self.sigMwSweepParamsChanged.emit(starts, stops, steps, power)
        return

    def change_fit_range(self):
        self._widefield_logic.fit_range = self._mw.fit_range_SpinBox.value()
        return

    def get_frequencies_from_row(self, row):
        object_dict = self.get_objects_from_groupbox_row(row)
        for object_name in object_dict:
            if "DoubleSpinBox" in object_name:
                if "start" in object_name:
                    start = object_dict[object_name].value()
                elif "step" in object_name:
                    step = object_dict[object_name].value()
                elif "stop" in object_name:
                    stop = object_dict[object_name].value()

        return start, stop, step

    def change_runtime(self):
        """ Change time after which microwave sweep is stopped """
        runtime = self._mw.runtime_DoubleSpinBox.value()
        self.sigRuntimeChanged.emit(runtime)
        return

    def save_data(self):
        """ Save the sum plot, the scan marix plot and the scan data """
        filetag = self._mw.save_tag_LineEdit.text()

        # Percentile range is None, unless the percentile scaling is selected in GUI.
        pcile_range = None
        if self._mw.xy_cb_centiles_RadioButton.isChecked():
            low_centile = self._mw.xy_cb_low_percentile_DoubleSpinBox.value()
            high_centile = self._mw.xy_cb_high_percentile_DoubleSpinBox.value()
            pcile_range = [low_centile, high_centile]

        self.sigSaveMeasurement.emit(filetag, cb_range, pcile_range)
        return


    def initSettingsUI(self):
        """ Definition, configuration and initialisation of the settings GUI.

        This init connects all the graphic modules, which were created in the
        *.ui file and configures the event handling between the modules.
        Moreover it sets default values if not existed in the logic modules.
        """
        # Create the Settings window
        self._sd = CameraSettingDialog()
        # Connect the action of the settings window with the code:
        self._sd.accepted.connect(self.update_settings)
        self._sd.rejected.connect(self.reject_settings)
        self._sd.buttonBox.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.update_settings)

        # write the configuration to the settings window of the GUI.
        self.reject_settings()

    def initChannelSettingsUI(self):
        """ Definition, configuration and initialisation of the settings GUI.

        This init connects all the graphic modules, which were created in the
        *.ui file and configures the event handling between the modules.
        Moreover it sets default values if not existed in the logic modules.
        """
        # Create the Settings window
        self._cs = ChannelSettingDialog()

    def menu_settings(self):
        """ This method opens the settings menu. """
        self._sd.exec_()

    def start_image_clicked(self):
        self.sigImageStart.emit()
        self._mw.start_image_Action.setDisabled(True)
        self._mw.start_video_Action.setDisabled(True)

    def acquisition_finished(self):
        self._mw.start_image_Action.setChecked(False)
        self._mw.start_image_Action.setDisabled(False)
        self._mw.start_video_Action.setDisabled(False)

    def start_video_clicked(self):
        """ Handling the Start button to stop and restart the counter.
        """
        self._mw.start_image_Action.setDisabled(True)
        if self._camera_logic.enabled:
            self._mw.start_video_Action.setText('Start Video')
            self.sigVideoStop.emit()
        else:
            self._mw.start_video_Action.setText('Stop Video')
            self.sigVideoStart.emit()

    def enable_start_image_action(self):
        self._mw.start_image_Action.setEnabled(True)

    def update_data(self):
        """
        Get the image data from the logic and print it on the window
        """
        raw_data_image = self._camera_logic.get_last_image()
        levels = (0., 1.)
        self._image.setImage(image=raw_data_image)
        self.update_xy_cb_range()
        # self._image.setImage(image=raw_data_image, levels=levels)

    def updateView(self):
        """
        Update the view when the model change
        """
        pass

# color bar functions
    def get_xy_cb_range(self):
        """ Determines the cb_min and cb_max values for the xy scan image
        """
        # If "Manual" is checked, or the image data is empty (all zeros), then take manual cb range.
        if self._mw.xy_cb_manual_RadioButton.isChecked() or np.max(self._image.image) == 0.0:
            cb_min = self._mw.xy_cb_min_DoubleSpinBox.value()
            cb_max = self._mw.xy_cb_max_DoubleSpinBox.value()

        # Otherwise, calculate cb range from percentiles.
        else:
            # xy_image_nonzero = self._image.image[np.nonzero(self._image.image)]

            # Read centile range
            low_centile = self._mw.xy_cb_low_percentile_DoubleSpinBox.value()
            high_centile = self._mw.xy_cb_high_percentile_DoubleSpinBox.value()

            cb_min = np.percentile(self._image.image, low_centile)
            cb_max = np.percentile(self._image.image, high_centile)

        cb_range = [cb_min, cb_max]

        return cb_range

    def refresh_xy_colorbar(self):
        """ Adjust the xy colorbar.

        Calls the refresh method from colorbar, which takes either the lowest
        and higherst value in the image or predefined ranges. Note that you can
        invert the colorbar if the lower border is bigger then the higher one.
        """
        cb_range = self.get_xy_cb_range()
        self.xy_cb.refresh_colorbar(cb_range[0], cb_range[1])

    def refresh_xy_image(self):
        """ Update the current XY image from the logic.

        Everytime the scanner is scanning a line in xy the
        image is rebuild and updated in the GUI.
        """
        self._image.getViewBox().updateAutoRange()

        xy_image_data = self._camera_logic._last_image

        cb_range = self.get_xy_cb_range()

        # Now update image with new color scale, and update colorbar
        self._image.setImage(image=xy_image_data, levels=(cb_range[0], cb_range[1]))
        self.refresh_xy_colorbar()

    def shortcut_to_xy_cb_manual(self):
        """Someone edited the absolute counts range for the xy colour bar, better update."""
        self._mw.xy_cb_manual_RadioButton.setChecked(True)
        self.update_xy_cb_range()

    def shortcut_to_xy_cb_centiles(self):
        """Someone edited the centiles range for the xy colour bar, better update."""
        self._mw.xy_cb_centiles_RadioButton.setChecked(True)
        self.update_xy_cb_range()

    def update_xy_cb_range(self):
        """Redraw xy colour bar and scan image."""
        self.refresh_xy_colorbar()
        self.refresh_xy_image()

# save functions

    def save_xy_scan_data(self):
        """ Run the save routine from the logic to save the xy confocal data."""
        cb_range = self.get_xy_cb_range()

        # Percentile range is None, unless the percentile scaling is selected in GUI.
        pcile_range = None
        if not self._mw.xy_cb_manual_RadioButton.isChecked():
            low_centile = self._mw.xy_cb_low_percentile_DoubleSpinBox.value()
            high_centile = self._mw.xy_cb_high_percentile_DoubleSpinBox.value()
            pcile_range = [low_centile, high_centile]

        self._camera_logic.save_xy_data(colorscale_range=cb_range, percentile_range=pcile_range)

        # TODO: find a way to produce raw image in savelogic.  For now it is saved here.
        filepath = self._save_logic.get_path_for_module(module_name='Confocal')
        filename = filepath + os.sep + time.strftime('%Y%m%d-%H%M-%S_confocal_xy_scan_raw_pixel_image')

        self._image.save(filename + '_raw.png')

    def _change_measurement_type(self, measurement):
        """
        Controls which predefined method option is available at any given time.
        """
        self.sigChangeMeasurementType.emit(self._mw.measurement_type_comboBox.currentText())
        self.apply_predefined_methods_config()
        return

    def _create_predefined_methods(self):
        """
        Initializes the GUI elements for the predefined methods
        """
        # Empty reference containers
        self._mw.gen_buttons = dict()
        self._mw.samplo_buttons = dict()
        self._mw.method_param_widgets = dict()

        self._mw.dockWidgetContents_4_grid_layout = self._mw.dockWidgetContents_4.layout()

        method_params = self._widefield_logic.generate_method_params
        for method_name in natural_sort(self._widefield_logic.predefined_generate_methods):
            
            # Create the widgets for the predefined methods dialogue
            # Create GroupBox for the method to reside in
            groupBox = QtWidgets.QGroupBox(self._mw.dockWidgetContents_4)
            groupBox.setVisible(False)
            groupBox.setAlignment(QtCore.Qt.AlignLeft)
            groupBox.setTitle(method_name)
            # Create layout within the GroupBox
            gridLayout = QtWidgets.QGridLayout(groupBox)
            # Create generate buttons
            gen_button = QtWidgets.QPushButton(groupBox)
            gen_button.setText('Generate')
            gen_button.setObjectName('gen_' + method_name)
            gen_button.clicked.connect(self.generate_predefined_clicked)
            samplo_button = QtWidgets.QPushButton(groupBox)
            samplo_button.setText('GenSampLo')
            samplo_button.setObjectName('samplo_' + method_name)
            samplo_button.clicked.connect(self.generate_predefined_clicked)
            gridLayout.addWidget(gen_button, 0, 0, 1, 1)
            gridLayout.addWidget(samplo_button, 1, 0, 1, 1)
            self._mw.gen_buttons[method_name] = gen_button
            self._mw.samplo_buttons[method_name] = samplo_button

            # run through all parameters of the current method and create the widgets
            self._mw.method_param_widgets[method_name] = dict()
            for param_index, (param_name, param) in enumerate(method_params[method_name].items()):
                    
                    if param_name == "ranges" and param is True:
                        # Add grid layout for ranges
                        ranges_GroupBox = QtWidgets.QGroupBox(self._mw.dockWidgetContents_4)
                        ranges_GroupBox.setVisible(False)
                        ranges_GroupBox.setAlignment(QtCore.Qt.AlignLeft)
                        ranges_GroupBox.setMaximumWidth(900)
                        ranges_gridLayout = QtWidgets.QGridLayout(ranges_GroupBox)
                        constraints = self._widefield_logic.get_hw_constraints()
                        for row in range(self._widefield_logic.ranges):
                            # start
                            start_label = QtWidgets.QLabel(ranges_GroupBox)
                            start_label.setText('Start:')
                            setattr(self._mw.measurement_control_DockWidget, 'start_label_{}'.format(row), start_label)
                            start_freq_DoubleSpinBox = ScienDSpinBox(ranges_GroupBox)
                            start_freq_DoubleSpinBox.setSuffix('Hz')
                            start_freq_DoubleSpinBox.setMaximum(constraints.max_frequency)
                            start_freq_DoubleSpinBox.setMinimum(constraints.min_frequency)
                            start_freq_DoubleSpinBox.setMinimumSize(QtCore.QSize(80, 0))
                            start_freq_DoubleSpinBox.setValue(self._widefield_logic.mw_starts[row])
                            start_freq_DoubleSpinBox.setMinimumWidth(75)
                            start_freq_DoubleSpinBox.setMaximumWidth(100)
                            setattr(self._mw.measurement_control_DockWidget, 'start_freq_DoubleSpinBox_{}'.format(row),
                                    start_freq_DoubleSpinBox)
                            ranges_gridLayout.addWidget(start_label, row, 1, 1, 1)
                            ranges_gridLayout.addWidget(start_freq_DoubleSpinBox, row, 2, 1, 1)
                            start_freq_DoubleSpinBox.editingFinished.connect(self.change_sweep_params)
                            # step
                            step_label = QtWidgets.QLabel(ranges_GroupBox)
                            step_label.setText('Step:')
                            setattr(self._mw.measurement_control_DockWidget, 'step_label_{}'.format(row), step_label)
                            step_freq_DoubleSpinBox = ScienDSpinBox(ranges_GroupBox)
                            step_freq_DoubleSpinBox.setSuffix('Hz')
                            step_freq_DoubleSpinBox.setMaximum(100e9)
                            step_freq_DoubleSpinBox.setMinimumSize(QtCore.QSize(80, 0))
                            step_freq_DoubleSpinBox.setValue(self._widefield_logic.mw_steps[row])
                            step_freq_DoubleSpinBox.setMinimumWidth(75)
                            step_freq_DoubleSpinBox.setMaximumWidth(100)
                            step_freq_DoubleSpinBox.editingFinished.connect(self.change_sweep_params)
                            setattr(self._mw.measurement_control_DockWidget, 'step_freq_DoubleSpinBox_{}'.format(row),
                                    step_freq_DoubleSpinBox)
                            ranges_gridLayout.addWidget(step_label, row, 3, 1, 1)
                            ranges_gridLayout.addWidget(step_freq_DoubleSpinBox, row, 4, 1, 1)

                            # stop
                            stop_label = QtWidgets.QLabel(ranges_GroupBox)
                            stop_label.setText('Stop:')
                            setattr(self._mw.measurement_control_DockWidget, 'stop_label_{}'.format(row), stop_label)
                            stop_freq_DoubleSpinBox = ScienDSpinBox(ranges_GroupBox)
                            stop_freq_DoubleSpinBox.setSuffix('Hz')
                            stop_freq_DoubleSpinBox.setMaximum(constraints.max_frequency)
                            stop_freq_DoubleSpinBox.setMinimum(constraints.min_frequency)
                            stop_freq_DoubleSpinBox.setMinimumSize(QtCore.QSize(80, 0))
                            stop_freq_DoubleSpinBox.setValue(self._widefield_logic.mw_stops[row])
                            stop_freq_DoubleSpinBox.setMinimumWidth(75)
                            stop_freq_DoubleSpinBox.setMaximumWidth(100)
                            stop_freq_DoubleSpinBox.editingFinished.connect(self.change_sweep_params)
                            setattr(self._mw.measurement_control_DockWidget, 'stop_freq_DoubleSpinBox_{}'.format(row),
                                    stop_freq_DoubleSpinBox)
                            ranges_gridLayout.addWidget(stop_label, row, 5, 1, 1)
                            ranges_gridLayout.addWidget(stop_freq_DoubleSpinBox, row, 6, 1, 1)

                            # on the first row add buttons to add and remove measurement ranges
                            if row == 0:
                                add_range_button = QtWidgets.QPushButton(ranges_GroupBox)
                                add_range_button.setText('Add Range')
                                add_range_button.setMinimumWidth(75)
                                add_range_button.setMaximumWidth(100)
                                if self._widefield_logic.mw_scanmode.name == 'SWEEP':
                                    add_range_button.setDisabled(True)
                                add_range_button.clicked.connect(self.add_ranges_gui_elements_clicked)
                                ranges_gridLayout.addWidget(add_range_button, row, 7, 1, 1)
                                setattr(self._mw.measurement_control_DockWidget, 'add_range_button',
                                        add_range_button)

                                remove_range_button = QtWidgets.QPushButton(ranges_GroupBox)
                                remove_range_button.setText('Remove Range')
                                remove_range_button.setMinimumWidth(75)
                                remove_range_button.setMaximumWidth(100)
                                remove_range_button.clicked.connect(self.remove_ranges_gui_elements_clicked)
                                ranges_gridLayout.addWidget(remove_range_button, row, 8, 1, 1)
                                setattr(self._mw.measurement_control_DockWidget, 'remove_range_button',
                                        remove_range_button)

                        self._mw.fit_range_SpinBox.setMaximum(self._widefield_logic.ranges - 1)
                        setattr(self._mw.measurement_control_DockWidget, 'ranges_GroupBox', ranges_GroupBox)
                        self._mw.fit_range_SpinBox.valueChanged.connect(self.change_fit_range)
                        # (QWidget * widget, int row, int column, Qt::Alignment alignment = Qt::Alignment())

                        self._mw.dockWidgetContents_4_grid_layout.addWidget(ranges_GroupBox, 7, 1, 1, 5)
                    else:
                        # create a label for the parameter
                        param_label = QtWidgets.QLabel(groupBox)
                        param_label.setText(param_name)
                        # create proper input widget for the parameter depending on default value type
                        if type(param) is bool:
                            input_obj = QtWidgets.QCheckBox(groupBox)
                            input_obj.setChecked(param)
                        elif type(param) is float:
                            input_obj = ScienDSpinBox(groupBox)
                            if 'amp' in param_name or 'volt' in param_name:
                                input_obj.setSuffix('V')
                            elif 'freq' in param_name:
                                input_obj.setSuffix('Hz')
                            elif 'time' in param_name or 'period' in param_name or 'tau' in param_name:
                                input_obj.setSuffix('s')
                            input_obj.setMinimumSize(QtCore.QSize(80, 0))
                            input_obj.setValue(param)
                        elif type(param) is int:
                            input_obj = ScienSpinBox(groupBox)
                            input_obj.setValue(param)
                        elif type(param) is str:
                            input_obj = QtWidgets.QLineEdit(groupBox)
                            input_obj.setMinimumSize(QtCore.QSize(80, 0))
                            input_obj.setText(param)
                        elif issubclass(type(param), Enum):
                            input_obj = QtWidgets.QComboBox(groupBox)
                            for option in type(param):
                                input_obj.addItem(option.name, option)
                            input_obj.setCurrentText(param.name)
                            # Set size constraints
                            input_obj.setMinimumSize(QtCore.QSize(80, 0))
                        else:
                            self.log.error('The predefined method "{0}" has an argument "{1}" which '
                                        'has no default argument or an invalid type (str, float, '
                                        'int, bool or Enum allowed)!\nCreation of the viewbox aborted.'
                                        ''.format('generate_' + method_name, param_name))
                            continue
                        # Adjust size policy
                        input_obj.setMinimumWidth(75)
                        input_obj.setMaximumWidth(100)
                        gridLayout.addWidget(param_label, 0, param_index + 1, 1, 1)
                        gridLayout.addWidget(input_obj, 1, param_index + 1, 1, 1)
                        self._mw.method_param_widgets[method_name][param_name] = input_obj
                        # attach the GroupBox widget to the predefined methods widget.
            setattr(self._mw, method_name + '_GroupBox', groupBox)
               
            self._mw.dockWidgetContents_4_grid_layout.addWidget(groupBox,4,1)
        return

    @QtCore.Slot(bool)
    def generate_predefined_clicked(self, button_obj=None):
        """

        @param button_obj:
        @return:
        """
        if isinstance(button_obj, bool):
            button_obj = self.sender()
        method_name = button_obj.objectName()
        if method_name.startswith('gen_'):
            sample_and_load = False
            method_name = method_name[4:]
        elif method_name.startswith('samplo_'):
            sample_and_load = True
            method_name = method_name[7:]
        else:
            self.log.error('Strange naming of generate buttons in predefined methods occured.')
            return

        # get parameters from input widgets
        # Store parameters together with the parameter names in a dictionary
        param_dict = dict()
        for param_name, widget in self._mw.method_param_widgets[method_name].items():
            if hasattr(widget, 'isChecked'):
                param_dict[param_name] = widget.isChecked()
            elif hasattr(widget, 'value'):
                param_dict[param_name] = widget.value()
            elif hasattr(widget, 'text'):
                param_dict[param_name] = widget.text()
            elif hasattr(widget, 'currentIndex') and hasattr(widget, 'itemData'):
                param_dict[param_name] = widget.itemData(widget.currentIndex())
            else:
                self.log.error('Not possible to get the value from the widgets, since it does not '
                               'have one of the possible access methods!')
                return

        if sample_and_load:
            # disable buttons
            for button in self._mw.gen_buttons.values():
                button.setEnabled(False)
            for button in self._mw.samplo_buttons.values():
                button.setEnabled(False)

        self._widefield_logic.generate_predefined_sequence(
            method_name, param_dict, sample_and_load)
        return

    @QtCore.Slot(object)
    def sample_ensemble_finished(self, ensemble):
        """
        This method reactivates the GenSampLo button after the ensemble has been uploaded
        """
        # enable buttons
        # TODO add in sampload busy stuff
        # if not self._pulsedmasterlogic.status_dict['sampload_busy']:
            # Reactivate predefined method buttons
        for button in self._mw.gen_buttons.values():
            button.setEnabled(True)
        for button in self._mw.samplo_buttons.values():
            button.setEnabled(True)
        return
    
    def apply_predefined_methods_config(self):
        current_measurement = self._mw.measurement_type_comboBox.currentText()

        ranges_groupBox = self._mw.measurement_control_DockWidget.ranges_GroupBox
        for method_name in self._widefield_logic.generate_methods:
            groupbox = getattr(self._mw, method_name + '_GroupBox')
            groupbox.setVisible(method_name == current_measurement)

        method_params = self._widefield_logic.generate_method_params[current_measurement]    
        ranges_groupBox.setVisible("ranges" in method_params)
            
        return