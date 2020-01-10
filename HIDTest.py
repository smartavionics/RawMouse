# Copyright (c) 2020 burtoogle.
# HIDTest is released under the terms of the AGPLv3 or higher.

import json
import sys
import os

from threading import Thread

#from UM.Controller import Controller
from UM.Extension import Extension
from UM.Logger import Logger
from cura.CuraApplication import CuraApplication

from PyQt5.QtCore import QObject, pyqtProperty, pyqtSignal

from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")

if sys.platform == "linux":
    sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hidapi", "hidapi-0.9.0-py3.5-linux-" + os.uname()[4] + ".egg"))
elif sys.platform == "win32":
    sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hidapi", "hidapi-0.9.0-py3.5-win-amd64.egg"))
import hid
del sys.path[-1]

class HIDTest(Extension, QObject,):
    def __init__(self, parent = None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        self._application = CuraApplication.getInstance()
        self._camera_tool = self._application.getController().getCameraTool()

        #self.setMenuName(catalog.i18nc("@item:inmenu", "HIDTest"))
        #self.addMenuItem(catalog.i18nc("@item:inmenu", "Enumerate HID Devices"), self._enumerate)

        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hid.json"), "r", encoding = "utf-8") as f:
            _config = json.load(f)

        self._hid_dev = None
        for hid_dev in hid.enumerate():
            for known_dev in _config["devices"]:
                if hid_dev["vendor_id"] == int(known_dev[0], base = 16) and hid_dev["product_id"] == int(known_dev[1], base = 16):
                    self._hid_dev = known_dev
                    break
            if self._hid_dev is not None:
                break

        if self._hid_dev is not None:
            Logger.log("d", "Using HID device %s", self._hid_dev[3])
            self._runner = Thread(target = self._run, daemon = True, name = "HID Event Reader")
            self._runner.start()
        else:
            Logger.log("w", "No known HID device found")

    def _run(self):
        h = hid.device()
        h.open(int(self._hid_dev[0], base = 16), int(self._hid_dev[1], base = 16))

        #print("Manufacturer: %s" % h.get_manufacturer_string())
        #print("Product: %s" % h.get_product_string())
        #print("Serial No: %s" % h.get_serial_number_string())

        sys.stdout.flush()

        # enable non-blocking mode
        #h.set_nonblocking(1)

        while True:
            d = h.read(64)
            if d:
                self._decodeHIDEvent(d)
            else:
                break

    def _decodeHIDEvent(self, buf):
        self._decodeAxisEvent(buf)

    def _decodeAxisEvent(self, buf):
        if len(buf) == 7 and (buf[0] == 1 or buf[0] == 2):
            for a in range(0, 3):
                val = buf[2 * a + 1] | buf[2 * a + 2] << 8
                if val & 0x8000:
                    val = val - 0x10000
                val = val / 350.0
                if abs(val) > 0.01:
                    self._axisEvent((buf[0] - 1) * 3 + a, val)
        elif len(buf) == 13 and buf[0] == 1:
            for a in range(0, 6):
                val = buf[2 * a + 1] | buf[2 * a + 2] << 8
                if val & 0x8000:
                    val = val - 0x10000
                val = val / 350.0
                if abs(val) > 0.01:
                    self._axisEvent(a, val)
        else:
            Logger.log("d", "Unknown HID event code = %x, len = %d", buf[0], len(buf))

    def _axisEvent(self, axis, val):
        Logger.log("d", "axis[%d] = %f", axis, val)

