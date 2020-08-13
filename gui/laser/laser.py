# -*- coding: utf-8 -*-

"""
This file contains a gui for the laser controller logic.

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
import os
import pyqtgraph as pg
import time

from core.module import Connector
from core.util import units
from gui.colordefs import QudiPalettePale as palette
from gui.guiutils import ColorBar
from gui.colordefs import ColorScaleViridis
from gui.guibase import GUIBase
from interface.simple_laser_interface import ControlMode, ShutterState, LaserState
from qtpy import QtCore
from qtpy import QtWidgets
from qtpy import uic

class LaserWindow(QtWidgets.QMainWindow):
    """ Create the Main Window based on the *.ui file. 
    """

    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_laser.ui')

        # Load it
        super().__init__()
        uic.loadUi(ui_file, self)
        self.show()


class LaserGUI(GUIBase):
    """ FIXME: Please document
    """
    _modclass = 'lasergui'
    _modtype = 'gui'

    ## declare connectors
    laserlogic = Connector(interface='LaserLogic')
    counter_logic = Connector(interface='CounterLogic')

    sigPower = QtCore.Signal(float)
    sigCurrent = QtCore.Signal(float)
    sigCtrlMode = QtCore.Signal(ControlMode)
    sigStartSaturation = QtCore.Signal()
    sigStopSaturation = QtCore.Signal()
    sigSaveMeasurement = QtCore.Signal(str)
    sigSaturationParamsChanged = QtCore.Signal(float, float, int, float)
    sigStartOOPMeasurement = QtCore.Signal()
    sigStopOOPMeasurement = QtCore.Signal()
    sigStartBayopt = QtCore.Signal()
    sigStopBayopt = QtCore.Signal()

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Definition and initialisation of the GUI.
        """
        self._laser_logic = self.laserlogic()
        self._counterlogic = self.counter_logic()

        #####################
        # Configuring the dock widgets
        # Use the inherited class 'LaserWindow' to create the GUI window
        # Hiding the central widget and tabifying the dockwidgets
        self._mw = LaserWindow()
        self._mw.centralwidget.hide()
        self._mw.tabifyDockWidget(self._mw.saturation_fit_DockWidget, self._mw.OOP_DockWidget)
        self._mw.tabifyDockWidget(self._mw.OOP_DockWidget, self._mw.BayOpt_DockWidget)
        # Resize the window
        dw = QtWidgets.QDesktopWidget()
        x = dw.availableGeometry().width() * 0.5
        y = dw.availableGeometry().height() * 0.6
        self._mw.setMinimumSize(0, 0)
        self._mw.resize(x, y)

        # Create a QSettings object for the mainwindow and store the actual GUI layout
        self.mwsettings = QtCore.QSettings("QUDI", "Saturation")
        self.mwsettings.setValue("geometry", self._mw.saveGeometry())
        self.mwsettings.setValue("windowState", self._mw.saveState())

        ########################################################################
        #                    Configuration of the plots                        #
        ########################################################################

        self._pw = self._mw.saturation_Curve_PlotWidget
        self._pw.setLabel('left', 'Fluorescence', units='counts/s')
        self._pw.setLabel('bottom', 'Laser Power', units='W')

        self._matrix_pw = self._mw.matrix_PlotWidget
        self._matrix_pw.setLabel(axis='left', text='Laser power', units='W')
        self._matrix_pw.setLabel(axis='bottom', text='MW power', units='dBm')

        self._bayopt_pw = self._mw.bayopt_PlotWidget
        self._bayopt_pw.setLabel(axis='left', text='Laser power', units='W')
        self._bayopt_pw.setLabel(axis='bottom', text='MW power', units='dBm')

        #Setting up the curves.
        self.saturation_curve = pg.PlotDataItem(pen=pg.mkPen(palette.c1, style=QtCore.Qt.DotLine), 
                                                  symbol='o', symbolPen=palette.c1,
                                                  symbolBrush=palette.c1,
                                                  symbolSize=7 )
        self.background_curve = pg.PlotDataItem(pen=pg.mkPen(palette.c4, style=QtCore.Qt.DotLine), 
                                                  symbol='o', symbolPen=palette.c4,
                                                  symbolBrush=palette.c4,
                                                  symbolSize=7 )
        self.sat_errorbar = pg.ErrorBarItem(x=np.array([0]), y =np.array([0]), pen=pg.mkPen(palette.c6, style=QtCore.Qt.SolidLine), beam=1)
        self.bg_errorbar = pg.ErrorBarItem(x=np.array([0]), y =np.array([0]), pen=pg.mkPen(palette.c6, style=QtCore.Qt.SolidLine), beam=1)
        self.saturation_fit_image = pg.PlotDataItem(pen=pg.mkPen(palette.c2), symbol=None)  
        self.double_fit_image_saturation = pg.PlotDataItem(pen=pg.mkPen(palette.c2), symbol=None)
        self.double_fit_image_background = pg.PlotDataItem(pen=pg.mkPen(palette.c2), symbol=None)
        
        self.matrix_image = pg.ImageItem()                
        self.bayopt_image = pg.ImageItem()
        self.bayopt_points = pg.PlotDataItem(pen=None, symbol='o', symbolPen=palette.c5,
                                                  symbolBrush=palette.c5,
                                                  symbolSize=7) 

        self.bayopt_vert_line = pg.InfiniteLine(pos=None, angle=90, pen=pg.mkPen(palette.c2), movable=False)
        self.bayopt_horiz_line = pg.InfiniteLine(pos=None, angle=0, pen=pg.mkPen(palette.c2), movable=False)

        self._pw.addItem(self.saturation_curve)
        self._pw.addItem(self.sat_errorbar)
        self._matrix_pw.addItem(self.matrix_image)
        self._bayopt_pw.addItem(self.bayopt_image)
        self._bayopt_pw.addItem(self.bayopt_points)
        self._bayopt_pw.addItem(self.bayopt_vert_line)
        self._bayopt_pw.addItem(self.bayopt_horiz_line)

        # Get the colorscales at set LUT
        my_colors = ColorScaleViridis()
        self.matrix_image.setLookupTable(my_colors.lut)
        self.bayopt_image.setLookupTable(my_colors.lut)

        ########################################################################
        #                  Configuration of the Colorbars                      #
        ########################################################################
        self.oop_cb = ColorBar(my_colors.cmap_normed, 100, 0, 100)
        self.bayopt_cb = ColorBar(my_colors.cmap_normed, 100, 0, 1)

        # adding colorbar to ViewWidget
        self._mw.oop_cb_PlotWidget.addItem(self.oop_cb)
        self._mw.oop_cb_PlotWidget.hideAxis('bottom')
        self._mw.oop_cb_PlotWidget.hideAxis('left')
        self._mw.oop_cb_PlotWidget.setLabel('right')

        self._mw.bayopt_cb_PlotWidget.addItem(self.bayopt_cb)
        self._mw.bayopt_cb_PlotWidget.hideAxis('bottom')
        self._mw.bayopt_cb_PlotWidget.hideAxis('left')
        self._mw.bayopt_cb_PlotWidget.setLabel('right', units='T/sqrt(Hz)')

        ########################################################################
        #          Configuration of the various display Widgets                #
        ########################################################################

        #Setting up the constraints and values for the saturation measurement.
        lpr = self._laser_logic.laser_power_range
        self._mw.startPowerDoubleSpinBox.setRange(lpr[0], lpr[1])
        self._mw.startPowerDoubleSpinBox.setValue(self._laser_logic.power_start)
        self._mw.stopPowerDoubleSpinBox.setRange(lpr[0], lpr[1])
        self._mw.stopPowerDoubleSpinBox.setValue(self._laser_logic.power_stop)
        self._mw.numPointsSpinBox.setRange(1,100)
        self._mw.numPointsSpinBox.setValue(self._laser_logic.number_of_points)
        self._mw.timeDoubleSpinBox.setRange(1,1000)
        self._mw.timeDoubleSpinBox.setValue(self._laser_logic.time_per_point)

        #Setting up the constraints and values for the OOP measurement.
        odmr_constraints = self._laser_logic.get_odmr_constraints()
        self._mw.laser_power_start_DoubleSpinBox.setRange(lpr[0], lpr[1])
        self._mw.laser_power_start_DoubleSpinBox.setValue(self._laser_logic.laser_power_start)
        self._mw.laser_power_stop_DoubleSpinBox.setRange(lpr[0], lpr[1])
        self._mw.laser_power_stop_DoubleSpinBox.setValue(self._laser_logic.laser_power_stop)
        self._mw.laser_power_num_SpinBox.setValue(self._laser_logic.laser_power_num)
        self._mw.mw_power_start_DoubleSpinBox.setRange(odmr_constraints.min_power, odmr_constraints.max_power)
        self._mw.mw_power_start_DoubleSpinBox.setValue(self._laser_logic.mw_power_start)
        self._mw.mw_power_stop_DoubleSpinBox.setRange(odmr_constraints.min_power, odmr_constraints.max_power)
        self._mw.mw_power_stop_DoubleSpinBox.setValue(self._laser_logic.mw_power_stop)
        self._mw.mw_power_num_SpinBox.setValue(self._laser_logic.mw_power_num)
        self._mw.freq_start_DoubleSpinBox.setRange(odmr_constraints.min_frequency, odmr_constraints.max_frequency)
        self._mw.freq_start_DoubleSpinBox.setValue(self._laser_logic.freq_start)
        self._mw.freq_stop_DoubleSpinBox.setRange(odmr_constraints.min_frequency, odmr_constraints.max_frequency)
        self._mw.freq_stop_DoubleSpinBox.setValue(self._laser_logic.freq_stop)
        self._mw.freq_num_SpinBox.setRange(1, 1000)
        self._mw.freq_num_SpinBox.setValue(self._laser_logic.freq_num)
        self._mw.counter_runtime_DoubleSpinBox.setRange(1, 1000)
        self._mw.counter_runtime_DoubleSpinBox.setValue(self._laser_logic.counter_runtime)
        self._mw.odmr_runtime_DoubleSpinBox.setRange(1, 1000)
        self._mw.odmr_runtime_DoubleSpinBox.setValue(self._laser_logic.odmr_runtime)
        self._mw.channel_SpinBox.setValue(self._laser_logic.channel)
        self._mw.optimize_CheckBox.setChecked(self._laser_logic.optimize)
        for fit in self._laser_logic.get_odmr_fits():
            self._mw.fit_ComboBox.addItem(fit)
        self._mw.fit_ComboBox.setCurrentText(self._laser_logic.odmr_fit_function)
        self._mw.nametag_LineEdit.setText(self._laser_logic.OOP_nametag)
        self._mw.bayopt_laser_power_start_DoubleSpinBox.setRange(lpr[0], lpr[1])
        self._mw.bayopt_laser_power_start_DoubleSpinBox.setValue(self._laser_logic.laser_power_start)
        self._mw.bayopt_laser_power_stop_DoubleSpinBox.setRange(lpr[0], lpr[1])
        self._mw.bayopt_laser_power_stop_DoubleSpinBox.setValue(self._laser_logic.laser_power_stop)
        self._mw.bayopt_mw_power_start_DoubleSpinBox.setRange(odmr_constraints.min_power, odmr_constraints.max_power)
        self._mw.bayopt_mw_power_start_DoubleSpinBox.setValue(self._laser_logic.mw_power_start)
        self._mw.bayopt_mw_power_stop_DoubleSpinBox.setRange(odmr_constraints.min_power, odmr_constraints.max_power)
        self._mw.bayopt_mw_power_stop_DoubleSpinBox.setValue(self._laser_logic.mw_power_stop)
        self._mw.bayopt_freq_start_DoubleSpinBox.setRange(odmr_constraints.min_frequency, odmr_constraints.max_frequency)
        self._mw.bayopt_freq_start_DoubleSpinBox.setValue(self._laser_logic.freq_start)
        self._mw.bayopt_freq_stop_DoubleSpinBox.setRange(odmr_constraints.min_frequency, odmr_constraints.max_frequency)
        self._mw.bayopt_freq_stop_DoubleSpinBox.setValue(self._laser_logic.freq_stop)
        self._mw.bayopt_freq_num_SpinBox.setRange(1, 1000)
        self._mw.bayopt_freq_num_SpinBox.setValue(self._laser_logic.freq_num)
        self._mw.bayopt_odmr_runtime_DoubleSpinBox.setRange(1, 1000)
        self._mw.bayopt_odmr_runtime_DoubleSpinBox.setValue(self._laser_logic.odmr_runtime)
        self._mw.bayopt_channel_SpinBox.setValue(self._laser_logic.channel)
        for fit in self._laser_logic.get_odmr_fits():
            self._mw.bayopt_fit_ComboBox.addItem(fit)
        self._mw.bayopt_fit_ComboBox.setCurrentText(self._laser_logic.odmr_fit_function)
        self._mw.bayopt_num_meas_SpinBox.setValue(self._laser_logic.bayopt_num_meas)

        #Setting up laser state
        self.update_laser_buttons()
        self.update_control_mode()
        
        ########################################################################
        #                       Connect signals                                #
        ########################################################################

        # Internal user input changed signals
        self._mw.LaserdoubleSpinBox.editingFinished.connect(self.updatePowerFromSpinBox)
        self._mw.startPowerDoubleSpinBox.editingFinished.connect(self.change_saturation_params)
        self._mw.stopPowerDoubleSpinBox.editingFinished.connect(self.change_saturation_params)
        self._mw.numPointsSpinBox.editingFinished.connect(self.change_saturation_params)
        self._mw.timeDoubleSpinBox.editingFinished.connect(self.change_saturation_params)
        self._mw.laser_power_start_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_laser_power_start)
        self._mw.laser_power_stop_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_laser_power_stop)
        self._mw.laser_power_num_SpinBox.valueChanged.connect(self._laser_logic.set_laser_power_num)
        self._mw.mw_power_start_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_mw_power_start)
        self._mw.mw_power_stop_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_mw_power_stop)
        self._mw.mw_power_num_SpinBox.valueChanged.connect(self._laser_logic.set_mw_power_num)
        self._mw.freq_start_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_freq_start) 
        self._mw.freq_stop_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_freq_stop)
        self._mw.freq_num_SpinBox.valueChanged.connect(self._laser_logic.set_freq_num)
        self._mw.counter_runtime_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_counter_runtime)
        self._mw.odmr_runtime_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_odmr_runtime)
        self._mw.channel_SpinBox.valueChanged.connect(self._laser_logic.set_OOP_channel)
        self._mw.optimize_CheckBox.stateChanged.connect(self._laser_logic.set_OOP_optimize)
        self._mw.fit_ComboBox.currentTextChanged.connect(self._laser_logic.set_odmr_fit)
        self._mw.data_ComboBox.currentTextChanged.connect(self.OOP_update_data)
        #FIXME: it may be better to use editingFinished for not to send a signal for each letter typed
        self._mw.nametag_LineEdit.textChanged.connect(self._laser_logic.set_OOP_nametag)
        self._mw.bayopt_laser_power_start_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_laser_power_start)
        self._mw.bayopt_laser_power_stop_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_laser_power_stop)
        self._mw.bayopt_mw_power_start_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_mw_power_start)
        self._mw.bayopt_mw_power_stop_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_mw_power_stop)
        self._mw.bayopt_freq_start_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_freq_start) 
        self._mw.bayopt_freq_stop_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_freq_stop)
        self._mw.bayopt_freq_num_SpinBox.valueChanged.connect(self._laser_logic.set_freq_num)
        self._mw.bayopt_odmr_runtime_DoubleSpinBox.valueChanged.connect(self._laser_logic.set_odmr_runtime)
        self._mw.bayopt_channel_SpinBox.valueChanged.connect(self._laser_logic.set_OOP_channel)
        self._mw.bayopt_fit_ComboBox.currentTextChanged.connect(self._laser_logic.set_odmr_fit)
        self._mw.bayopt_num_meas_SpinBox.valueChanged.connect(self._laser_logic.set_bayopt_num_meas)
        self._mw.cb_high_percentile_DoubleSpinBox.valueChanged.connect(self.colorscale_changed)
        self._mw.cb_low_percentile_DoubleSpinBox.valueChanged.connect(self.colorscale_changed)
        self._mw.bayopt_cb_high_percentile_DoubleSpinBox.valueChanged.connect(self.bayopt_colorscale_changed)
        self._mw.bayopt_cb_low_percentile_DoubleSpinBox.valueChanged.connect(self.bayopt_colorscale_changed)

        # Internal trigger signals
        self._mw.start_saturation_Action.triggered.connect(self.run_stop_saturation)
        # self._mw.start_saturation_Action.triggered.connect(self.update_settings)
        self._mw.save_curve_Action.triggered.connect(self.save_saturation_curve_clicked)
        self._mw.action_Save.triggered.connect(self.save_saturation_curve_clicked)
        self._mw.action_RestoreDefault.triggered.connect(self.restore_defaultview)
        self._mw.controlModeButtonGroup.buttonClicked.connect(self.changeControlMode)
        self._mw.dofit_Button.clicked.connect(self.dofit_button_clicked)
        self._mw.double_fit_Button.clicked.connect(self.double_fit_button_clicked)
        self._mw.run_stop_measurement_Action.triggered.connect(self.run_stop_OOP_measurement)
        self._mw.run_stop_bayopt_Action.triggered.connect(self.run_stop_bayopt)
        self._mw.background_PushButton.clicked.connect(self.background_button_clicked)

        # Control/values-changed signals to logic
        self.sigSaveMeasurement.connect(self._laser_logic.save_saturation_data, QtCore.Qt.QueuedConnection)
        self._mw.laser_ON_Action.triggered.connect(self._laser_logic.on)
        self._mw.laser_OFF_Action.triggered.connect(self._laser_logic.off)
        self.sigCurrent.connect(self._laser_logic.set_current)
        self.sigPower.connect(self._laser_logic.set_power)
        self.sigCtrlMode.connect(self._laser_logic.set_control_mode)
        self.sigStartSaturation.connect(self._laser_logic.start_saturation_curve_data)
        self.sigStopSaturation.connect(self._laser_logic.stop_saturation_curve_data)
        self.sigSaturationParamsChanged.connect(self._laser_logic.set_saturation_params)
        self.sigStartOOPMeasurement.connect(self._laser_logic.start_OOP_measurement, QtCore.Qt.QueuedConnection)
        self.sigStopOOPMeasurement.connect(self._laser_logic.stop_OOP_measurement, QtCore.Qt.QueuedConnection)
        self.sigStartBayopt.connect(self._laser_logic.start_bayopt, QtCore.Qt.QueuedConnection)
        self.sigStopBayopt.connect(self._laser_logic.stop_bayopt, QtCore.Qt.QueuedConnection)
        
        # Update signals coming from logic:
        self._laser_logic.sigSaturationStarted.connect(self.saturation_started)
        self._laser_logic.sigSaturationStopped.connect(self.saturation_stopped)
        self._laser_logic.sigSaturationFitUpdated.connect(self.update_fit, QtCore.Qt.QueuedConnection)
        self._laser_logic.sigDoubleFitUpdated.connect(self.update_double_fit)
        self._laser_logic.sigRefresh.connect(self.update_gui)
        # self._laser_logic.sigAbortedMeasurement.connect(self.aborted_saturation_measurement)
        self._laser_logic.sigSaturationParameterUpdated.connect(self.update_saturation_params)
        self._laser_logic.sigOOPStarted.connect(self.OOP_started)
        self._laser_logic.sigOOPStopped.connect(self.OOP_stopped)
        self._laser_logic.sigOOPUpdateData.connect(self.OOP_update_data)
        self._laser_logic.sigParameterUpdated.connect(self.update_parameters)
        self._laser_logic.sigDataAvailableUpdated.connect(self.fill_combobox)
        self._laser_logic.sigLaserStateChanged.connect(self.update_laser_buttons)
        self._laser_logic.sigControlModeChanged.connect(self.update_control_mode)
        self._laser_logic.sigPowerSet.connect(self.update_power)
        self._laser_logic.sigBayoptStarted.connect(self.bayopt_started)
        self._laser_logic.sigBayoptStopped.connect(self.bayopt_stopped)
        self._laser_logic.sigBayoptUpdateData.connect(self.bayopt_update_data)

    def on_deactivate(self):
        """ Deactivate the module properly.
        """
        # Disconnect signals
        self._mw.LaserdoubleSpinBox.editingFinished.disconnect()
        self._mw.startPowerDoubleSpinBox.editingFinished.disconnect()
        self._mw.stopPowerDoubleSpinBox.editingFinished.disconnect()
        self._mw.numPointsSpinBox.editingFinished.disconnect()
        self._mw.timeDoubleSpinBox.editingFinished.disconnect()
        self._mw.laser_power_start_DoubleSpinBox.valueChanged.disconnect()
        self._mw.laser_power_stop_DoubleSpinBox.valueChanged.disconnect()
        self._mw.laser_power_num_SpinBox.valueChanged.disconnect()
        self._mw.mw_power_start_DoubleSpinBox.valueChanged.disconnect()
        self._mw.mw_power_stop_DoubleSpinBox.valueChanged.disconnect()
        self._mw.mw_power_num_SpinBox.valueChanged.disconnect()
        self._mw.freq_start_DoubleSpinBox.valueChanged.disconnect() 
        self._mw.freq_stop_DoubleSpinBox.valueChanged.disconnect()
        self._mw.freq_num_SpinBox.valueChanged.disconnect()
        self._mw.counter_runtime_DoubleSpinBox.valueChanged.disconnect()
        self._mw.odmr_runtime_DoubleSpinBox.valueChanged.disconnect()
        self._mw.channel_SpinBox.valueChanged.disconnect()
        self._mw.optimize_CheckBox.stateChanged.disconnect()
        self._mw.fit_ComboBox.currentTextChanged.disconnect()
        self._mw.data_ComboBox.currentTextChanged.disconnect()
        self._mw.nametag_LineEdit.textChanged.disconnect()
        self._mw.bayopt_laser_power_start_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_laser_power_stop_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_mw_power_start_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_mw_power_stop_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_freq_start_DoubleSpinBox.valueChanged.disconnect() 
        self._mw.bayopt_freq_stop_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_freq_num_SpinBox.valueChanged.disconnect()
        self._mw.bayopt_odmr_runtime_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_channel_SpinBox.valueChanged.disconnect()
        self._mw.bayopt_fit_ComboBox.currentTextChanged.disconnect()
        self._mw.bayopt_num_meas_SpinBox.valueChanged.disconnect()
        self._mw.cb_high_percentile_DoubleSpinBox.valueChanged.disconnect()
        self._mw.cb_low_percentile_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_cb_high_percentile_DoubleSpinBox.valueChanged.disconnect()
        self._mw.bayopt_cb_low_percentile_DoubleSpinBox.valueChanged.disconnect()
        self._mw.start_saturation_Action.triggered.disconnect()
        self._mw.save_curve_Action.triggered.disconnect()
        self._mw.action_Save.triggered.disconnect()
        self._mw.action_RestoreDefault.triggered.disconnect()
        self._mw.controlModeButtonGroup.buttonClicked.disconnect()
        self._mw.dofit_Button.clicked.disconnect()
        self._mw.run_stop_measurement_Action.triggered.disconnect()
        self._mw.run_stop_bayopt_Action.triggered.disconnect()
        self.sigSaveMeasurement.disconnect()
        self._mw.laser_ON_Action.triggered.disconnect()
        self._mw.laser_OFF_Action.triggered.disconnect()
        self.sigCurrent.disconnect()
        self.sigPower.disconnect()
        self.sigCtrlMode.disconnect()
        self.sigStartSaturation.disconnect()
        self.sigStopSaturation.disconnect()
        self.sigSaturationParamsChanged.disconnect()
        self.sigStartOOPMeasurement.disconnect()
        self.sigStopOOPMeasurement.disconnect()
        self.sigStartBayopt.disconnect()
        self.sigStopBayopt.disconnect()
        self._laser_logic.sigSaturationStarted.disconnect()
        self._laser_logic.sigSaturationStopped.disconnect()
        self._laser_logic.sigSaturationFitUpdated.disconnect()
        self._laser_logic.sigRefresh.disconnect()
        self._laser_logic.sigSaturationParameterUpdated.disconnect()
        self._laser_logic.sigOOPStarted.disconnect()
        self._laser_logic.sigOOPStopped.disconnect()
        self._laser_logic.sigOOPUpdateData.disconnect()
        self._laser_logic.sigParameterUpdated.disconnect()
        self._laser_logic.sigDataAvailableUpdated.disconnect()
        self._laser_logic.sigLaserStateChanged.disconnect()
        self._laser_logic.sigControlModeChanged.disconnect()
        self._laser_logic.sigPowerSet.disconnect()
        self._laser_logic.sigBayoptStarted.disconnect()
        self._laser_logic.sigBayoptStopped.disconnect()
        self._laser_logic.sigBayoptUpdateData.disconnect()
        self._mw.close()
        return 0

    # Not used 
    # def show(self):
    #     """Make window visible and put it above all other windows.
    #     """
    #     QtWidgets.QMainWindow.show(self._mw)
    #     self._mw.activateWindow()
    #     self._mw.raise_()

    ###########################################################################
    #                             Laser methods                               #
    ###########################################################################

    @QtCore.Slot()
    def update_laser_buttons(self):
        """ Enable the appropriate button depending on the laser state.
        """
        laser_state = self._laser_logic.get_laser_state()
        if laser_state == LaserState.ON:
            self._mw.laser_ON_Action.setEnabled(False)
            self._mw.laser_OFF_Action.setEnabled(True)
        elif self._laser_logic.get_laser_state() == LaserState.OFF:
            self._mw.laser_OFF_Action.setEnabled(False)
            self._mw.laser_ON_Action.setEnabled(True)
        else:
            self._mw.laser_ON_Action.setText('Laser: ?')
        return 

    @QtCore.Slot(QtWidgets.QAbstractButton)
    def changeControlMode(self):
        """ Process signal from laser control mode radio button group. 
        """
        cur = self._mw.currentRadioButton.isChecked()
        pwr = self._mw.powerRadioButton.isChecked()
        dig_mod = self._mw.digModulationRadioButton.isChecked()
        analog_mod = self._mw.analogModulationRadioButton.isChecked()

        if pwr:
            self.sigCtrlMode.emit(ControlMode.POWER)
        elif cur:
            self.sigCtrlMode.emit(ControlMode.CURRENT)
        elif dig_mod:
            self.sigCtrlMode.emit(ControlMode.MODULATION_DIGITAL)
        elif analog_mod:
            self.sigCtrlMode.emit(ControlMode.MODULATION_ANALOG)
        else:
            self.log.error('How did you mess up the radio button group?')

    @QtCore.Slot()
    def update_control_mode(self):
        """ Process signal from the logic regarding the control mode and apply 
        it on the GUI.
        """
        # Enabling the right buttons
        if self._laser_logic.laser_can_power:
            self._mw.powerRadioButton.setEnabled(True)
        else:
            self._mw.powerRadioButton.setEnabled(False)

        if self._laser_logic.laser_can_current:
            self._mw.currentRadioButton.setEnabled(True)
        else:
            self._mw.currentRadioButton.setEnabled(False)

        if self._laser_logic.laser_can_digital_mod:
            self._mw.digModulationRadioButton.setEnabled(True)
        else:
            self._mw.digModulationRadioButton.setEnabled(False)

        if self._laser_logic.laser_can_analog_mod:
            self._mw.analogModulationRadioButton.setEnabled(True)
        else:
            self._mw.analogModulationRadioButton.setEnabled(False)

        # Updating the spin box
        control_mode = self._laser_logic.get_control_mode()
        if control_mode == ControlMode.POWER:
            self._mw.powerRadioButton.setChecked(True)
            self._mw.LaserdoubleSpinBox.setSuffix('W')
            lpr = self._laser_logic.laser_power_range
            self._mw.LaserdoubleSpinBox.setRange(lpr[0], lpr[1])
            self._mw.LaserdoubleSpinBox.setValue(self._laser_logic.laser_power_setpoint)
        elif control_mode == ControlMode.CURRENT:
            self._mw.currentRadioButton.setChecked(True)
            self._mw.LaserdoubleSpinBox.setSuffix('mA')
            lcr = self._laser_logic.laser_current_range
            self._mw.LaserdoubleSpinBox.setRange(lcr[0], lcr[1])
            self._mw.LaserdoubleSpinBox.setValue(self._laser_logic.laser_current_setpoint)
        elif control_mode == ControlMode.MODULATION_DIGITAL:
            self._mw.digModulationRadioButton.setChecked(True)
            self._mw.LaserdoubleSpinBox.setSuffix('W')
            lpr = self._laser_logic.laser_power_range
            self._mw.LaserdoubleSpinBox.setRange(lpr[0], lpr[1])
            self._mw.LaserdoubleSpinBox.setValue(self._laser_logic.laser_power_setpoint)
        elif control_mode == ControlMode.MODULATION_ANALOG:
            self._mw.analogModulationRadioButton.setChecked(True)
            self._mw.LaserdoubleSpinBox.setSuffix('W')
            lpr = self._laser_logic.laser_power_range
            self._mw.LaserdoubleSpinBox.setRange(lpr[0], lpr[1])
            self._mw.LaserdoubleSpinBox.setValue(self._laser_logic.laser_power_setpoint)

    @QtCore.Slot()
    def updatePowerFromSpinBox(self):
        """ The user has changed the spinbox, update the value in the logic. 
        """
        #self._mw.setValueVerticalSlider.setValue(self._mw.setValueDoubleSpinBox.value())
        cur = self._mw.currentRadioButton.isChecked()
        pwr = self._mw.powerRadioButton.isChecked()
        dig_mod = self._mw.digModulationRadioButton.isChecked()
        analog_mod = self._mw.analogModulationRadioButton.isChecked()

        if pwr or dig_mod or analog_mod:
            self.sigPower.emit(self._mw.LaserdoubleSpinBox.value())
        elif cur:
            self.sigCurrent.emit(self._mw.LaserdoubleSpinBox.value())

    @QtCore.Slot(float)
    def update_power(self, power):
        """ The value of the logic have changed, update the GUI.
        """
        self._mw.LaserdoubleSpinBox.setValue(power)

    ###########################################################################
    #                      Saturation curve methods                           #
    ###########################################################################

    @QtCore.Slot()
    def update_gui(self):
        """ Update labels, the plot and errorbars with new data. 
        """
        sat_data = self._laser_logic.get_saturation_data()
        #Background data if it has been measured
        bg_data = self._laser_logic.get_saturation_data(is_background=True)

        if sat_data:
            counts_value = sat_data['Fluorescence'][-1]
            scale_fact = units.ScaledFloat(counts_value).scale_val
            unit_prefix = units.ScaledFloat(counts_value).scale
            self._mw.saturation_Curve_Label.setText('{0:6.3f} {1}{2}'.format(counts_value / scale_fact,  unit_prefix, 'counts/s'))

        elif bg_data:
            counts_value = bg_data['Fluorescence'][-1]
            scale_fact = units.ScaledFloat(counts_value).scale_val
            unit_prefix = units.ScaledFloat(counts_value).scale
            self._mw.saturation_Curve_Label.setText('{0:6.3f} {1}{2}'.format(counts_value / scale_fact,  unit_prefix, 'counts/s'))
        
        if sat_data:
            self.saturation_curve.setData(sat_data['Power'], sat_data['Fluorescence'])    
            self.sat_errorbar.setData(x=sat_data['Power'], y=sat_data['Fluorescence'], height=sat_data['Stddev'])
            if len(sat_data['Power']) > 1:
                self.sat_errorbar.setData(beam=(sat_data['Power'][1] - sat_data['Power'][0])/4) 
        
        if bg_data:
            self.background_curve.setData(bg_data['Power'], bg_data['Fluorescence'])    
            self.bg_errorbar.setData(x=bg_data['Power'], y=bg_data['Fluorescence'], height=bg_data['Stddev'])
            if len(bg_data['Power']) > 1:
                self.bg_errorbar.setData(beam=(bg_data['Power'][1] - bg_data['Power'][0])/4)
                              
    def background_button_clicked(self, is_checked):
        """ Display/remove the background data on the plot widget when the button
        is pressed/released.
        """
        if is_checked:
            self._pw.addItem(self.background_curve)
            self._pw.addItem(self.bg_errorbar)
        else:
            self._pw.removeItem(self.background_curve)
            self._pw.removeItem(self.bg_errorbar)
            self._mw.double_fit_Button.setChecked(False)
            self.double_fit_button_clicked(False)

    @QtCore.Slot()       
    def restore_defaultview(self):
        self._mw.restoreGeometry(self.mwsettings.value("geometry", ""))
        self._mw.restoreState(self.mwsettings.value("windowState", ""))

    # def update_settings(self):
    #     """ Write the new settings from the gui to the logic. """
    #     self._laser_logic.power_start = self._mw.startPowerDoubleSpinBox.value()
    #     self._laser_logic.power_stop = self._mw.stopPowerDoubleSpinBox.value()
    #     self._laser_logic.number_of_points = self._mw.numPointsSpinBox.value()
    #     self._laser_logic.time_per_point = self._mw.timeDoubleSpinBox.value()
    #     return

    @QtCore.Slot(np.ndarray, np.ndarray, dict)
    def update_fit(self, x_data, y_data, result_str_dict):
        """ Update the plot of the fit and the fit results displayed.

        @params np.array x_data: 1D arrays containing the x values of the fitting function
        @params np.array y_data: 1D arrays containing the y values of the fitting function
        @params dict result_str_dict: a dictionary with the relevant fit parameters. Each entry has
                                            to be a dict with two needed keywords 'value' and 'unit'
                                            and one optional keyword 'error'.
        """
        self._mw.saturation_fit_results_DisplayWidget.clear()
        try:
            formated_results = units.create_formatted_output(result_str_dict)
        except:
            formated_results = 'this fit does not return formatted results'
        self._mw.saturation_fit_results_DisplayWidget.setPlainText(formated_results)
        self.saturation_fit_image.setData(x=x_data, y=y_data)
        if self.saturation_fit_image not in self._pw.listDataItems():
            self._pw.addItem(self.saturation_fit_image)
        self._mw.dofit_Button.setChecked(True)

    def update_double_fit(self, x_data, y_data, result_str_dict):
        """ Update the plot of the fit and the fit results displayed for the fit with the background.

        @params np.array x_data: 2D arrays containing the x values of the fitting functions:
                                 the first row correspond to the NV saturation curve and the second 
                                 row to the background curve.
        @params np.array y_data: 2D arrays containing the y values of the fitting functions, first row 
                                 for NV curve and second row for background curve. 
        @params dict result_str_dict: a dictionary with the relevant fit parameters. Each entry has
                                            to be a dict with two needed keywords 'value' and 'unit'
                                            and one optional keyword 'error'.
        """
        self._mw.double_fit_results_DisplayWidget.clear()
        try:
            formated_results = units.create_formatted_output(result_str_dict)
        except:
            formated_results = 'this fit does not return formatted results'
        self._mw.double_fit_results_DisplayWidget.setPlainText(formated_results)
        self.double_fit_image_saturation.setData(x=x_data[0], y=y_data[0])
        self.double_fit_image_background.setData(x=x_data[1], y=y_data[1])
        if self.double_fit_image_saturation not in self._pw.listDataItems():
            self._pw.addItem(self.double_fit_image_saturation)
        if self.double_fit_image_background not in self._pw.listDataItems():
            self._pw.addItem(self.double_fit_image_background)
        self._mw.double_fit_Button.setChecked(True)


    @QtCore.Slot(bool)
    def run_stop_saturation(self, is_checked):
        """ Manages what happens if start/stop action is triggered. """
        if is_checked:

            self._laser_logic.is_background = self._mw.background_CheckBox.isChecked()
            if self._laser_logic.is_background:
                self._mw.background_PushButton.setChecked(True)
                self.background_button_clicked(True)

            self._mw.start_saturation_Action.setEnabled(False)
            self.sigStartSaturation.emit()
            self._pw.removeItem(self.saturation_fit_image)
            self._pw.removeItem(self.double_fit_image_saturation)
            self._pw.removeItem(self.double_fit_image_background)
            self._mw.saturation_fit_results_DisplayWidget.clear()
            self._mw.double_fit_results_DisplayWidget.clear()
            self._mw.dofit_Button.setChecked(False)
        else:
            self._mw.start_saturation_Action.setEnabled(False)
            self.sigStopSaturation.emit()
        return

    @QtCore.Slot()
    def saturation_started(self):
        """ Manages what happens when saturation measurement has started. 
        """
        self.update_laser_buttons()
        self._mw.start_saturation_Action.setEnabled(True)
        self._mw.laser_power_GroupBox.setEnabled(False)
        self._mw.saturation_GroupBox.setEnabled(False)
        self._mw.background_CheckBox.setEnabled(False)
        self._mw.start_saturation_Action.setChecked(True)
        self._mw.start_saturation_Action.setText('Stop saturation')
        self._mw.run_stop_measurement_Action.setEnabled(False)
        self._mw.run_stop_bayopt_Action.setEnabled(False)
        return

    @QtCore.Slot()
    def saturation_stopped(self):
        """ Manages what happens when saturation measurement has stopped. 
        """
        self.update_laser_buttons()
        self._mw.start_saturation_Action.setEnabled(True)
        self._mw.laser_power_GroupBox.setEnabled(True)
        self._mw.saturation_GroupBox.setEnabled(True)
        self._mw.background_CheckBox.setEnabled(True)
        self._mw.start_saturation_Action.setChecked(False)
        self._mw.start_saturation_Action.setText('Start saturation')
        self._mw.run_stop_measurement_Action.setEnabled(True)
        self._mw.run_stop_bayopt_Action.setEnabled(True)
        return

    @QtCore.Slot()
    def save_saturation_curve_clicked(self):
        """ Save the saturation curve data and the figure
        """
        filetag = self._mw.save_tag_LineEdit.text()

        self.sigSaveMeasurement.emit(filetag)
        self._mw.save_curve_Action.setChecked(False)
        return

    # #TODO: remove this method ?
    # @QtCore.Slot()
    # def aborted_saturation_measurement(self):
    #     """ Makes sure everything goes back to normal if a measurement is aborted.
    #     """
    #     self._mw.start_saturation_Action.setChecked(False)
    #     self._mw.start_saturation_Action.setEnabled(True)
    #     self._mw.start_saturation_Action.setText('Start saturation')
    #     self._mw.LaserdoubleSpinBox.setEnabled(True)
    #     self._mw.analogModulationRadioButton.setEnabled(True)
    #     self._mw.currentRadioButton.setEnabled(True)
    #     self._mw.digModulationRadioButton.setEnabled(True)
    #     self._mw.powerRadioButton.setEnabled(True)
    #     self._mw.numPointsSpinBox.setEnabled(True)
    #     self._mw.startPowerDoubleSpinBox.setEnabled(True)
    #     self._mw.stopPowerDoubleSpinBox.setEnabled(True)
    #     self._mw.timeDoubleSpinBox.setEnabled(True)

    #     return

    @QtCore.Slot(bool)
    def dofit_button_clicked(self, checked):
        """ Manages what happens when the fit button is clicked. 
        """
        if checked:
            self._mw.dofit_Button.setChecked(False)
            self._laser_logic.do_fit()
        else: 
            self._pw.removeItem(self.saturation_fit_image)
            self._mw.saturation_fit_results_DisplayWidget.clear()

    def double_fit_button_clicked(self, checked):
        """ Manages what happens when the button for the fit with background is clicked. 
        """
        if checked:
            self._mw.background_PushButton.setChecked(True)
            self.background_button_clicked(True)
            self._mw.double_fit_Button.setChecked(False)
            self._laser_logic.do_double_fit()
        else: 
            self._pw.removeItem(self.double_fit_image_saturation)
            self._pw.removeItem(self.double_fit_image_background)
            self._mw.double_fit_results_DisplayWidget.clear()

    @QtCore.Slot()
    def change_saturation_params(self):
        """ Write the new parameters from the gui to the logic. 
        """
        power_start = self._mw.startPowerDoubleSpinBox.value()
        power_stop = self._mw.stopPowerDoubleSpinBox.value()
        number_of_points = self._mw.numPointsSpinBox.value()
        time_per_point = self._mw.timeDoubleSpinBox.value()
        self.sigSaturationParamsChanged.emit(power_start, power_stop, number_of_points, time_per_point)
        return

    @QtCore.Slot()
    def update_saturation_params(self):
        """ The parameters have changed in the logic, update them in the GUI.
        """
        param_dict = self._laser_logic.get_saturation_parameters()

        param = param_dict.get('power_start')
        self._mw.startPowerDoubleSpinBox.setValue(param)

        param = param_dict.get('power_stop')
        self._mw.stopPowerDoubleSpinBox.setValue(param)

        param = param_dict.get('number_of_points')
        self._mw.numPointsSpinBox.setValue(param)

        param = param_dict.get('time_per_point')
        self._mw.timeDoubleSpinBox.setValue(param)

        return


    ###########################################################################
    #              Optimal operation point measurement methods                #
    ###########################################################################

    @QtCore.Slot(bool)
    def run_stop_OOP_measurement(self, is_checked):
        """ Manages what happens if operation point measurement is started/stopped. """
        if is_checked:
            self._mw.run_stop_measurement_Action.setEnabled(False)
            self.sigStartOOPMeasurement.emit()
        else:
            self.sigStopOOPMeasurement.emit()
            self._mw.run_stop_measurement_Action.setEnabled(False)
        return


    @QtCore.Slot()
    def OOP_started(self):
        """ The OOP measurement has started, manage the buttons. 
        """
        self._mw.run_stop_measurement_Action.setChecked(True)
        self._mw.parameters_GroupBox.setEnabled(False)
        self._mw.start_saturation_Action.setEnabled(False)
        self._mw.laser_ON_Action.setEnabled(False)
        self._mw.laser_OFF_Action.setEnabled(False)
        self._mw.run_stop_bayopt_Action.setEnabled(False)
        self._mw.laser_power_GroupBox.setEnabled(False)
        self._mw.saturation_GroupBox.setEnabled(False)
        self._mw.bayopt_parameters_GroupBox.setEnabled(False)
        self._mw.run_stop_measurement_Action.setEnabled(True)

    @QtCore.Slot()
    def OOP_stopped(self):
        """ The OOP measurement has stopped, manage the buttons. 
        """
        self._mw.run_stop_measurement_Action.setChecked(False)
        self._mw.parameters_GroupBox.setEnabled(True)
        self._mw.start_saturation_Action.setEnabled(True)
        self._mw.laser_ON_Action.setEnabled(True)
        self._mw.laser_OFF_Action.setEnabled(True)
        self._mw.run_stop_bayopt_Action.setEnabled(True)
        self._mw.laser_power_GroupBox.setEnabled(True)
        self._mw.saturation_GroupBox.setEnabled(True)
        self._mw.bayopt_parameters_GroupBox.setEnabled(True)
        self._mw.run_stop_measurement_Action.setEnabled(True)

    @QtCore.Slot()
    def OOP_update_data(self):
        """ Update the colorbar and display the matrix.
        """
        matrix_scaled, unit_scaled, error = self.get_scaled_data()
        if error:
            return
        
        low_centile = self._mw.cb_low_percentile_DoubleSpinBox.value()
        high_centile = self._mw.cb_high_percentile_DoubleSpinBox.value()
        cb_range = self.get_matrix_cb_range(matrix_scaled, low_centile, high_centile)
        
        self.update_colorbar(cb_range, unit_scaled)

        self.matrix_image.setImage(image=matrix_scaled,
                                    axisOrder='row-major',
                                    levels=(cb_range[0], cb_range[1]))
        self.matrix_image.setRect(
            QtCore.QRectF(
                self._laser_logic.mw_power_start,
                self._laser_logic.laser_power_start,
                self._laser_logic.mw_power_stop - self._laser_logic.mw_power_start,
                self._laser_logic.laser_power_stop - self._laser_logic.laser_power_start
            )
        )

    #FIXME: The matrix should not need to be scaled but it is done here because
    # of an issue in the displaying of the colorbar otherwise.
    def get_scaled_data(self):
        """ Return the matrix containing the OOP data scaled, the associated unit and
        an error code (0:OK, -1:error).
        """
        data_name = self._mw.data_ComboBox.currentText()
        if data_name != '':

            matrix, unit = self._laser_logic.get_data(data_name) 

            scale_fact = units.ScaledFloat(np.max(matrix)).scale_val
            unit_prefix = units.ScaledFloat(np.max(matrix)).scale
            matrix_scaled = matrix / scale_fact
            unit_scaled = unit_prefix + unit
            return matrix_scaled, unit_scaled, 0
        return [], '', -1

    def get_matrix_cb_range(self, matrix, low_centile, high_centile):
        """ Take a matrix as an argument and return a list with the minimum and
        maximum values of the colorbar.

        @param numpy.ndarray matrix: Matrix containing the measured data points and 
        zeros for the points which have not been measured yet.
        """
        matrix_nonzero = matrix[np.nonzero(matrix)]
        if np.size(matrix_nonzero)==0:
            return [0, 1]
        cb_min = np.percentile(matrix_nonzero, low_centile)
        cb_max = np.percentile(matrix_nonzero, high_centile)
        cb_range = [cb_min, cb_max]
        return cb_range

    #FIXME: Colorbar not properly displayed for big numbers (>1e9) or small numbers (<1e-3)
    def update_colorbar(self, cb_range, unit):
        self.oop_cb.refresh_colorbar(cb_range[0], cb_range[1])
        self._mw.oop_cb_PlotWidget.setLabel('right', units=unit)
        return

    @QtCore.Slot()
    def colorscale_changed(self):
        """
        Updates the range of the displayed colorscale in both the colorbar and the matrix plot.
        """
        matrix_scaled, unit_scaled, error = self.get_scaled_data()
        if error:
            return
        
        low_centile = self._mw.cb_low_percentile_DoubleSpinBox.value()
        high_centile = self._mw.cb_high_percentile_DoubleSpinBox.value()
        cb_range = self.get_matrix_cb_range(matrix_scaled, low_centile, high_centile)
        
        self.update_colorbar(cb_range, unit_scaled)
        self.matrix_image.setImage(image=matrix_scaled, levels=(cb_range[0], cb_range[1]))
        return

    @QtCore.Slot(list)
    def fill_combobox(self, data_list):
        """Add the parameters available from the fit in a combobox so that the
        user can choose which one he wants to display.

        @param: list data_list: List containing the names of the parameters as 
        strings.
        """
        self._mw.data_ComboBox.clear()
        for data_name in data_list:
            self._mw.data_ComboBox.addItem(data_name)

    @QtCore.Slot()
    def update_parameters(self):
        """ The measurement parameters have changed in the logic, update the GUI.
        """
        param_dict = self._laser_logic.get_OOP_parameters()

        param = param_dict.get('laser_power_start')
        self._mw.laser_power_start_DoubleSpinBox.setValue(param)
        self._mw.bayopt_laser_power_start_DoubleSpinBox.setValue(param)

        param = param_dict.get('laser_power_stop')
        self._mw.laser_power_stop_DoubleSpinBox.setValue(param)
        self._mw.bayopt_laser_power_stop_DoubleSpinBox.setValue(param)

        param = param_dict.get('laser_power_num')
        self._mw.laser_power_num_SpinBox.setValue(param)

        param = param_dict.get('mw_power_start')
        self._mw.mw_power_start_DoubleSpinBox.setValue(param)
        self._mw.bayopt_mw_power_start_DoubleSpinBox.setValue(param)

        param = param_dict.get('mw_power_stop')
        self._mw.mw_power_stop_DoubleSpinBox.setValue(param)
        self._mw.bayopt_mw_power_stop_DoubleSpinBox.setValue(param)

        param = param_dict.get('mw_power_num')
        self._mw.mw_power_num_SpinBox.setValue(param)

        param = param_dict.get('freq_start')
        self._mw.freq_start_DoubleSpinBox.setValue(param)
        self._mw.bayopt_freq_start_DoubleSpinBox.setValue(param)

        param = param_dict.get('freq_stop')
        self._mw.freq_stop_DoubleSpinBox.setValue(param)
        self._mw.bayopt_freq_stop_DoubleSpinBox.setValue(param)
        
        param = param_dict.get('freq_num')
        self._mw.freq_num_SpinBox.setValue(param)
        self._mw.bayopt_freq_num_SpinBox.setValue(param)
        
        param = param_dict.get('counter_runtime')
        self._mw.counter_runtime_DoubleSpinBox.setValue(param)

        param = param_dict.get('odmr_runtime')
        self._mw.odmr_runtime_DoubleSpinBox.setValue(param)
        self._mw.bayopt_odmr_runtime_DoubleSpinBox.setValue(param)

        param = param_dict.get('channel')
        self._mw.channel_SpinBox.setValue(param)
        self._mw.bayopt_channel_SpinBox.setValue(param)

        param = param_dict.get('optimize')
        self._mw.optimize_CheckBox.setChecked(param)

        param = param_dict.get('odmr_fit_function')
        self._mw.fit_ComboBox.setCurrentText(param)
        self._mw.bayopt_fit_ComboBox.setCurrentText(param)

        param = param_dict.get('OOP_nametag')
        self._mw.nametag_LineEdit.setText(param)

        param = param_dict.get('bayopt_num_meas')
        self._mw.bayopt_num_meas_SpinBox.setValue(param)

        return


    @QtCore.Slot(int)
    def bayopt_update_data(self, n_iter):
        """ Update the colorbar and display the matrix.
        """
        bayopt_data = self._laser_logic.get_bayopt_data()
        image = bayopt_data['predicted_sensitivity']

        low_centile = self._mw.bayopt_cb_low_percentile_DoubleSpinBox.value()
        high_centile = self._mw.bayopt_cb_high_percentile_DoubleSpinBox.value()
        cb_range = self.get_matrix_cb_range(image, low_centile, high_centile)
        
        self.bayopt_cb.refresh_colorbar(cb_range[0], cb_range[1])
        
        self.bayopt_image.setImage(image=image,
                                    axisOrder='row-major',
                                    levels=(cb_range[0], cb_range[1]))

        self.bayopt_image.setRect(
            QtCore.QRectF(
                self._laser_logic.mw_power_start,
                self._laser_logic.laser_power_start,
                self._laser_logic.mw_power_stop - self._laser_logic.mw_power_start,
                self._laser_logic.laser_power_stop - self._laser_logic.laser_power_start
            )
        )
        self.bayopt_points.setData(bayopt_data['mw_power_list'][:n_iter + 1], bayopt_data['laser_power_list'][:n_iter + 1])

        index_min = np.argmin(bayopt_data['measured_sensitivity'][:n_iter + 1])
        min_mw_power = bayopt_data['mw_power_list'][index_min]
        min_laser_power = bayopt_data['laser_power_list'][index_min]
        self.bayopt_vert_line.setValue(min_mw_power)
        self.bayopt_horiz_line.setValue(min_laser_power)

        self._mw.elapsed_measurements_DisplayWidget.display(n_iter + 1)
    
    @QtCore.Slot()
    def bayopt_colorscale_changed(self):
        image = self.bayopt_image.image
        low_centile = self._mw.bayopt_cb_low_percentile_DoubleSpinBox.value()
        high_centile = self._mw.bayopt_cb_high_percentile_DoubleSpinBox.value()
        cb_range = self.get_matrix_cb_range(image, low_centile, high_centile)
        self.bayopt_cb.refresh_colorbar(cb_range[0], cb_range[1])
        self.bayopt_image.setImage(image=image, axisOrder='row-major', levels=(cb_range[0], cb_range[1]))
        return           

    @QtCore.Slot(bool)
    def run_stop_bayopt(self, is_checked):
        if is_checked:
            self._mw.run_stop_bayopt_Action.setEnabled(False)
            self.sigStartBayopt.emit()
        else:
            self.sigStopBayopt.emit()
            self._mw.run_stop_bayopt_Action.setEnabled(False)
        return

    @QtCore.Slot()
    def bayopt_started(self):
        self._mw.run_stop_bayopt_Action.setChecked(True)
        self._mw.parameters_GroupBox.setEnabled(False)
        self._mw.bayopt_parameters_GroupBox.setEnabled(False)
        self._mw.start_saturation_Action.setEnabled(False)
        self._mw.laser_ON_Action.setEnabled(False)
        self._mw.laser_OFF_Action.setEnabled(False)
        self._mw.run_stop_measurement_Action.setEnabled(False)
        self._mw.laser_power_GroupBox.setEnabled(False)
        self._mw.saturation_GroupBox.setEnabled(False)
        self._mw.run_stop_bayopt_Action.setEnabled(True)

    @QtCore.Slot()
    def bayopt_stopped(self):
        self._mw.run_stop_bayopt_Action.setChecked(False)
        self._mw.parameters_GroupBox.setEnabled(True)
        self._mw.bayopt_parameters_GroupBox.setEnabled(True)
        self._mw.start_saturation_Action.setEnabled(True)
        self._mw.laser_ON_Action.setEnabled(True)
        self._mw.laser_OFF_Action.setEnabled(True)
        self._mw.run_stop_measurement_Action.setEnabled(True)
        self._mw.laser_power_GroupBox.setEnabled(True)
        self._mw.saturation_GroupBox.setEnabled(True)
        self._mw.run_stop_bayopt_Action.setEnabled(True)
