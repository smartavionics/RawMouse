# Copyright (c) 2020 burtoogle.
# RawMouse is released under the terms of the AGPLv3 or higher.

import json
import sys
import time
import os

from threading import Thread

from UM.Event import MouseEvent, WheelEvent
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message
from UM.Signal import Signal, signalemitter

from cura.CuraApplication import CuraApplication

from PyQt5.QtCore import QObject, QTime
from PyQt5 import QtCore, QtWidgets

from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")

if sys.platform == "linux":
    sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hidapi", "hidapi-0.9.0-py3.5-linux-" + os.uname()[4] + ".egg"))
elif sys.platform == "win32":
    sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hidapi", "hidapi-0.9.0-py3.5-win-amd64.egg"))
elif sys.platform == "darwin":
    sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hidapi", "hidapi-0.9.0-py3.5-macosx-10.13-intel.egg"))
import hid
del sys.path[-1]

@signalemitter
class RawMouse(Extension, QObject,):
    def __init__(self, parent = None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        self._decoders = {
            "spacemouse": self._decodeSpacemouseEvent,
            "tiltpad":    self._decodeTiltpadEvent
        }

        self._application = None
        self._controller = None
        self._scene = None
        self._camera_tool = None

        self.setMenuName(catalog.i18nc("@item:inmenu", "RawMouse"))
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Restart"), self._restart)
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Show Device Information"), self._showDeviceInformation)

        self._buttons = 0
        self._running = False
        self._runner = None
        self._battery_level = None
        self._message = Message(title=catalog.i18nc("@info:title", "RawMouse"))
        self._redraw_pending = False

        self.processTargetValues.connect(self._processTargetValues)

        self._reload()
        self._start()

    def _restart(self):
        self._stop()
        self._reload()
        self._start()

    def _reload(self):
        self._config = {}
        try:
            with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.json"), "r", encoding = "utf-8") as f:
                self._config = json.load(f)
        except Exception as e:
            Logger.log("e", "Exception loading configuration: %s", e)

    def _cacheProfileValues(self, profile_name):
        self._hid_profile_name = profile_name
        self._hid_profile = self._config["profiles"][profile_name]
        if "maxhz" in self._config:
            self._min_camera_update_period = 1000 / self._config["maxhz"]
        else:
            self._min_camera_update_period = 100
        if "verbose" in self._config:
            self._verbose = self._config["verbose"]
        else:
            self._verbose = 0
        self._axis_threshold = []
        self._axis_scale = []
        self._axis_offset = []
        self._axis_target = []
        self._axis_value = []
        if self._hid_profile_name in self._decoders:
            self._decoder = self._decoders[self._hid_profile_name]
        else:
            self._decoder = self._decodeUnknownEvent
        hid_profile_axes = self._hid_profile["axes"]
        Logger.log("d", "Device %s / %s, profile %s", self._hid_dev["manufacturer_string"], self._hid_dev["product_string"], self._hid_profile_name);
        for i in range(0, len(hid_profile_axes)):
            axis_vals = hid_profile_axes[i]
            self._axis_threshold.append(axis_vals["threshold"])
            self._axis_scale.append(axis_vals["scale"])
            self._axis_offset.append(axis_vals["offset"])
            if "target" in axis_vals:
                self._axis_target.append(axis_vals["target"])
            else:
                self._axis_target.append("")
            self._axis_value.append(0.0)
            Logger.log("d", "axis %d, scale = %f, threshold = %f, offset = %f, target = %s", i, self._axis_scale[i], self._axis_threshold[i], self._axis_offset[i], self._axis_target[i])

    def _start(self):
        self._hid_dev = None
        try:
            for hid_dev in hid.enumerate():
                for known_dev in self._config["devices"]:
                    if hid_dev["vendor_id"] == int(known_dev[0], base = 16) and hid_dev["product_id"] == int(known_dev[1], base = 16):
                        if sys.platform != "linux" and len(known_dev) > 4:
                            if "usage_page" in known_dev[4]:
                                if hid_dev["usage_page"] != known_dev[4]["usage_page"]:
                                    continue
                            if "usage" in known_dev[4]:
                                if hid_dev["usage"] != known_dev[4]["usage"]:
                                    continue
                        self._hid_dev = hid_dev
                        self._cacheProfileValues(known_dev[2])
                        break
                if self._hid_dev:
                    break
        except Exception as e:
            Logger.log("e", "Exception initialising profile: %s", e)

        if self._hid_dev:
            self._runner = Thread(target = self._run, daemon = True, name = "RawMouse")
            self._runner.start()
        else:
            Logger.log("w", "No known HID device found")

    def _stop(self):
        self._running = False
        while self._runner:
            self._runner.join(timeout = 2.0)

    def _run(self):
        self._running = True
        try:
            h = hid.device()
            if self._hid_dev["path"]:
                Logger.log("d", "Trying to open %s", self._hid_dev["path"].decode("utf-8"))
                h.open_path(self._hid_dev["path"])
            else:
                Logger.log("d", "Trying to open [%x,%x]", self._hid_dev["vendor_id"], self._hid_dev["product_id"])
                h.open(self._hid_dev["vendor_id"], self._hid_dev["product_id"])

            Logger.log("i", "Manufacturer: %s", h.get_manufacturer_string())
            Logger.log("i", "Product: %s", h.get_product_string())
            #Logger.log("i", "Serial No: %s", h.get_serial_number_string())

            self._last_camera_update_at = QTime()
            self._last_camera_update_at.start()
            while self._running:
                if self._application is None:
                    self._application = CuraApplication.getInstance()
                elif self._controller is None:
                    self._controller = self._application.getController()
                elif self._camera_tool is None:
                    self._camera_tool = self._controller.getCameraTool()
                    self._scene = self._controller.getScene()
                if self._application and not self._application.checkWindowMinimizedState():
                    d = h.read(64, 1000)
                    if d:
                        self._decoder(d)
                else:
                    time.sleep(1.0)
            h.close()
        except Exception as e:
            Logger.log("e", "Exception while reading HID events: %s", e)
        self._running = False
        self._runner = None

    def _initTargetValues(self):
        self._target_values = {
            "movx": 0.0,
            "movy": 0.0,
            "rotx": 0.0,
            "roty": 0.0,
            "zoom": 0.0,
            "resetview": None,
            "toggleview": None
        }

    processTargetValues = Signal()

    def _processTargetValues(self):
        try:
            if self._target_values["resetview"]:
                if self._controller:
                    self._controller.setCameraRotation(*self._target_values["resetview"])
            elif self._target_values["toggleview"]:
                if self._controller:
                    if self._controller.getActiveView().getPluginId() == "SimulationView":
                        self._controller.setActiveStage("PrepareStage")
                        self._controller.setActiveView("SolidView")
                    else:
                        self._controller.setActiveStage("PreviewStage")
                        self._controller.setActiveView("SimulationView")
            elif self._camera_tool and self._last_camera_update_at.elapsed() > self._min_camera_update_period:
                if self._target_values["movx"] != 0.0 or self._target_values["movy"] != 0.0:
                    self._last_camera_update_at.start()
                    self._camera_tool._moveCamera(MouseEvent(MouseEvent.MouseMoveEvent, self._target_values["movx"], self._target_values["movy"], 0, 0))
                if self._target_values["rotx"] != 0 or self._target_values["roty"] != 0:
                    self._last_camera_update_at.start()
                    self._camera_tool._rotateCamera(self._target_values["rotx"], self._target_values["roty"])
                if self._target_values["zoom"] != 0:
                    self._last_camera_update_at.start()
                    self._camera_tool._zoomCamera(self._target_values["zoom"])
        except Exception as e:
            Logger.log("e", "Exception while processing target values: %s", e)
        self._redraw_pending = False

    def _decodeSpacemouseEvent(self, buf):
        scale = 1.0 / 350.0
        if len(buf) == 7 and (buf[0] == 1 or buf[0] == 2):
            for a in range(0, 3):
                val = buf[2 * a + 1] | buf[2 * a + 2] << 8
                if val & 0x8000:
                    val = val - 0x10000
                axis = (buf[0] - 1) * 3 + a
                self._axis_value[axis] = val * scale * self._axis_scale[axis] + self._axis_offset[axis]
            self._spacemouseAxisEvent(self._axis_value)
        elif len(buf) == 13 and buf[0] == 1:
            for a in range(0, 6):
                val = buf[2 * a + 1] | buf[2 * a + 2] << 8
                if val & 0x8000:
                    val = val - 0x10000
                self._axis_value[a] = val * scale * self._axis_scale[a] + self._axis_offset[a]
            self._spacemouseAxisEvent(self._axis_value)
        elif len(buf) >= 3 and buf[0] == 3:
            buttons = buf[1] | buf[2] << 8
            for b in range(0, 16):
                mask = 1 << b
                if ((buttons & mask) != (self._buttons & mask)):
                    self._spacemouseButtonEvent(b + 1, (buttons & mask) >> b)
            self._buttons = buttons
        elif len(buf) >= 3 and buf[0] == 0x17:
            self._battery_level = buf[1]
            Logger.log("d", "Spacemouse battery level %d%%", buf[1])
        else:
            Logger.log("d", "Unknown spacemouse event: code = %x, len = %d", buf[0], len(buf))

    def _spacemouseAxisEvent(self, vals):
        if self._verbose > 0:
            Logger.log("d", "Axes [%f,%f,%f,%f,%f,%f]", vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])
        self._initTargetValues()
        process = False
        scale = self._getScalingDueToZoom()
        for i in range(0, 6):
            if vals[i] > self._axis_threshold[i]:
                self._target_values[self._axis_target[i]] = (vals[i] - self._axis_threshold[i]) * scale
                process = True
            elif vals[i] < -self._axis_threshold[i]:
                self._target_values[self._axis_target[i]] = (vals[i] + self._axis_threshold[i]) * scale
                process = True
        if process:
            if not self._redraw_pending:
                self._redraw_pending = True
                self.processTargetValues.emit();

    def _spacemouseButtonEvent(self, button, val):
        if self._verbose > 0:
            Logger.log("d", "button[%d] = %f", button, val)
        if val == 1:
            self._initTargetValues();
            process = False
            button_defs = self._hid_profile["buttons"]
            for b in button_defs:
                if button == int(b):
                    self._target_values[button_defs[b]["target"]] = button_defs[b]["value"]
                    process = True
            if process:
                if not self._redraw_pending:
                    self._redraw_pending = True
                    self.processTargetValues.emit()

    def _decodeTiltpadEvent(self, buf):
        self._initTargetValues()
        scale = self._getScalingDueToZoom()
        process = False
        #tilt
        for a in range(0, 2):
            val = (buf[a] - 127) * self._axis_scale[a] + self._axis_offset[a]
            if val > self._axis_threshold[a]:
                self._target_values[self._axis_target[a]] = (val - self._axis_threshold[a]) * scale
                process = True
            elif val < -self._axis_threshold[a]:
                self._target_values[self._axis_target[a]] = (val + self._axis_threshold[a]) * scale
                process = True
        buttons = buf[3] & 0x7f
        if buttons != 0:
            button_defs = self._hid_profile["buttons"]
            for b in button_defs:
                if buttons == int(b, base = 16):
                    self._target_values[button_defs[b]["target"]] = button_defs[b]["value"]
                    process = True
        if process:
            if not self._redraw_pending:
                self._redraw_pending = True
                self.processTargetValues.emit();

    def _decodeUnknownEvent(self, buf):
        Logger.log("d", "Unknown event: len = %d [0] = %x", len(buf), buf[0])

    def _getScalingDueToZoom(self):
        scale = 1.0
        if self._scene:
            zoom_factor = self._scene.getActiveCamera().getZoomFactor();
            if zoom_factor < -0.4:
                scale = 0.1 + 9 * (zoom_factor - -0.5)
                #Logger.log("d", "scale = %f", scale)
        return scale

    def _showDeviceInformation(self):
        try:
            message = "No device found"
            if self._hid_dev:
                message = "Manufacturer: " + self._hid_dev["manufacturer_string"] + "\nProduct: " + self._hid_dev["product_string"] + "\nProfile: " + self._hid_profile_name;
            if self._battery_level is not None:
                message = message + "\nBattery level: " + str(self._battery_level) + "%"
            if self._hid_profile:
                message = message + "\nAxes:"
                for i in range(0, len(self._axis_scale)):
                    message = message + "\n [" + str(i) + "] scale " + str(self._axis_scale[i]) + " threshold " + str(self._axis_threshold[i]) + " offset " + str(self._axis_offset[i]) + " -> " + self._axis_target[i]
            self._showMessage(message)
        except Exception as e:
            Logger.log("e", "Exception while showing device information: %s", e)

    def _showMessage(self, str):
        self._message.hide()
        self._message.setText(catalog.i18nc("@info:status", str))
        self._message.show()
