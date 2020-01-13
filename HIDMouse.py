# Copyright (c) 2020 burtoogle.
# HIDMouse is released under the terms of the AGPLv3 or higher.

import json
import sys
import time
import os

from threading import Thread

from UM.Event import MouseEvent, WheelEvent
from UM.Extension import Extension
from UM.Logger import Logger
#from UM.Math.Vector import Vector

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

class HIDMouse(Extension, QObject,):
    def __init__(self, parent = None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        self._decoders = {
            "spacemouse": self._decodeSpacemouseEvent,
            "tiltpad":    self._decodeTiltpadEvent
        }

        self._application = None
        self._camera_tool = None

        self.setMenuName(catalog.i18nc("@item:inmenu", "HIDMouse"))
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Restart"), self._restart)

        self._buttons = 0
        self._running = False
        self._runner = None
        self._reload()
        self._start()

    def _restart(self):
        self._stop()
        self._reload()
        self._start()

    def _reload(self):
        self._config = {}
        try:
            with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hidmouse.json"), "r", encoding = "utf-8") as f:
                self._config = json.load(f)
        except Exception as e:
            Logger.log("e", "Exception loading configuration: %s", e)

    def _cacheProfileValues(self, profile_name):
        self._hid_profile_name = profile_name
        self._hid_profile = self._config["profiles"][profile_name]
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
            Logger.log("d", "%s: axis %d, scale = %f, threshold = %f, offset = %f, target = %s", self._hid_profile_name, i, self._axis_scale[i], self._axis_threshold[i], self._axis_offset[i], self._axis_target[i])

    def _start(self):
        self._hid_dev = None
        try:
            for hid_dev in hid.enumerate():
                for known_dev in self._config["devices"]:
                    if hid_dev["vendor_id"] == int(known_dev[0], base = 16) and hid_dev["product_id"] == int(known_dev[1], base = 16):
                        self._hid_dev = hid_dev
                        self._cacheProfileValues(known_dev[2])
                        break
                if self._hid_dev:
                    break
        except Exception as e:
            Logger.log("e", "Exception initialising profile: %s", e)

        if self._hid_dev:
            self._runner = Thread(target = self._run, daemon = True, name = "HID Event Reader")
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

            self._last_event_at = QTime()
            self._last_event_at.start()
            while self._running:
                if self._application is None:
                    self._application = CuraApplication.getInstance()
                elif self._camera_tool is None:
                    self._camera_tool = self._application.getController().getCameraTool()
                if self._application and not self._application.checkWindowMinimizedState():
                    d = h.read(64, 1000)
                    if d and self._last_event_at.elapsed() > 50:
                        self._last_event_at.start()
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
            "resetview": None
        }

    def _processTargetValues(self):
        if self._target_values["resetview"]:
            self._resetView(self._target_values["resetview"])
        elif self._camera_tool:
            if self._target_values["movx"] != 0.0 or self._target_values["movy"] != 0.0:
                self._camera_tool._moveCamera(MouseEvent(MouseEvent.MouseMoveEvent, self._target_values["movx"], self._target_values["movy"], 0, 0))
            if self._target_values["rotx"] != 0 or self._target_values["roty"] != 0:
                self._camera_tool._rotateCamera(self._target_values["rotx"], self._target_values["roty"])
            if self._target_values["zoom"] != 0:
                self._camera_tool._zoomCamera(self._target_values["zoom"])

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
                    self._spacemouseButtonEvent(b, (buttons & mask) >> b)
            self._buttons = buttons
        else:
            Logger.log("d", "Unknown spacemouse event: code = %x, len = %d", buf[0], len(buf))

    def _spacemouseAxisEvent(self, vals):
        Logger.log("d", "Axes [%f,%f,%f,%f,%f,%f]", vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])
        self._initTargetValues()
        for i in range(0, 6):
            if abs(vals[i]) > self._axis_threshold[i]:
                self._target_values[self._axis_target[i]] = vals[i]
        self._processTargetValues();

    def _spacemouseButtonEvent(self, button, val):
        Logger.log("d", "button[%d] = %f", button, val)

    def _decodeTiltpadEvent(self, buf):
        self._initTargetValues()
        scale = 1.0
        #tilt
        for a in range(0, 2):
            val = (buf[a] - 127) * scale * self._axis_scale[a] + self._axis_offset[a]
            if abs(val) > self._axis_threshold[a]:
                self._target_values[self._axis_target[a]] = val
        buttons = buf[3] & 0x7f
        if buttons != 0:
            button_defs = self._hid_profile["buttons"]
            for b in button_defs:
                if buttons == int(b, base = 16):
                    self._target_values[button_defs[b]["target"]] = button_defs[b]["value"]
        self._processTargetValues()

    def _decodeUnknownEvent(self, buf):
        Logger.log("d", "Unknown event: len = %d [0] = %x", len(buf), buf[0])

    def _resetView(self, view):
        if self._application:
            scene = self._application.getController().setCameraRotation(*view)

