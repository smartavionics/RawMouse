# Copyright (c) 2020-2021 burtoogle.
# RawMouse is released under the terms of the AGPLv3 or higher.

import json
import math
import sys
import time
import os
import os.path
import platform

from ctypes import *

from threading import Thread

from UM.Event import MouseEvent, WheelEvent
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Math.Vector import Vector
from UM.Math.Matrix import Matrix
from UM.Message import Message
from UM.Signal import Signal, signalemitter
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Scene.SceneNode import SceneNode
from UM.Scene.Selection import Selection

from cura.CuraApplication import CuraApplication

from PyQt5.QtCore import QObject, QTime
from PyQt5 import QtCore, QtWidgets

from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")

libspnav = None

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
        self._main_window = None
        self._controller = None
        self._scene = None
        self._camera_tool = None

        self.setMenuName(catalog.i18nc("@item:inmenu", "RawMouse"))
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Stop"), self._stop)
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Restart"), self._restart)
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Show Device Information"), self._showDeviceInformation)

        self._buttons = 0
        self._running = False
        self._runner = None
        self._battery_level = None
        self._message = None
        self._redraw_pending = False
        self._roll = 0
        self._hidapi = None

        self.processTargetValues.connect(self._processTargetValues)

        self._reload(False)
        self._start()

    def _getComponents(self):
        if self._application is None:
            self._application = CuraApplication.getInstance()
        elif self._controller is None:
            self._controller = self._application.getController()
        elif self._camera_tool is None:
            self._camera_tool = self._controller.getCameraTool()
            self._scene = self._controller.getScene()
        elif self._main_window is None:
            self._main_window = self._application.getMainWindow()

    def _restart(self):
        self._stop()
        self._reload(True)
        self._start()

    def _reload(self, restarted):
        self._config = {}
        try:
            with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.json"), "r", encoding = "utf-8") as f:
                self._config = json.load(f)
        except Exception as e:
            Logger.log("e", "Exception loading configuration: %s", e)
            if restarted:
                self._showMessage("Exception loading configuration: " + str(e))

    def _cacheProfileValues(self, profile_name):
        self._profile_name = profile_name
        self._profile = self._config["profiles"][profile_name]
        self._min_camera_update_period = 1000 / (int(self._config["maxhz"]) if "maxhz" in self._config else 30)
        if "verbose" in self._config:
            self._verbose = self._config["verbose"]
        else:
            self._verbose = 0
        if "fastview" in self._config:
            self._auto_fast_view = self._config["fastview"]
        else:
            self._auto_fast_view = 0
        self._axis_threshold = []
        self._axis_scale = []
        self._axis_offset = []
        self._axis_target = []
        self._axis_value = []
        self._layer_change_increment = 1
        if self._profile_name in self._decoders:
            self._decoder = self._decoders[self._profile_name]
        else:
            self._decoder = self._decodeUnknownEvent
        profile_axes = self._profile["axes"]
        if self._hid_dev is not None:
            Logger.log("d", "Device %s / %s, profile %s", self._hid_dev["manufacturer_string"], self._hid_dev["product_string"], self._profile_name);
        for i in range(0, len(profile_axes)):
            axis_vals = profile_axes[i]
            self._axis_threshold.append(axis_vals["threshold"])
            self._axis_scale.append(axis_vals["scale"])
            self._axis_offset.append(axis_vals["offset"])
            target = ""
            if "target" in axis_vals:
                target = axis_vals["target"]
                aliases = {
                    "rotx": "rotyaw",
                    "roty": "rotpitch"
                }
                if target in aliases:
                    target = aliases[target]
                if target == "movy" and axis_vals["scale"] > 0.0:
                    self._layer_change_increment = -1
            self._axis_target.append(target)
            self._axis_value.append(0.0)
            Logger.log("d", "axis %d, scale = %f, threshold = %f, offset = %f, target = %s", i, self._axis_scale[i], self._axis_threshold[i], self._axis_offset[i], self._axis_target[i])

    def _start(self):
        self._hid_dev = None
        if "devices" in self._config:
            try:
                if self._hidapi is None:
                    if sys.platform == "linux":
                        sys_name = "linux-" + os.uname()[4]
                    elif sys.platform == "win32":
                        sys_name = "win-amd64"
                    elif sys.platform == "darwin":
                        sys_name = "macosx-10.13-intel"
                    else:
                        sys_name = "unknown"
                    egg_name = "hidapi-0.9.0-py" + ".".join(platform.python_version_tuple()[0:2]) + "-" + sys_name + ".egg";
                    sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), "hidapi", egg_name))
                    import hid
                    Logger.log("d", "Imported %s", str(hid))
                    self._hidapi = hid
                    del sys.path[-1]

                for hid_dev in self._hidapi.enumerate():
                    for known_dev in self._config["devices"]:
                        if hid_dev["vendor_id"] == int(known_dev[0], base = 16) and hid_dev["product_id"] == int(known_dev[1], base = 16):
                            if len(known_dev) > 4:
                                options = known_dev[4]
                                if "platform" in options and platform.system() != options["platform"]:
                                    continue
                                if "usage_page" in options and hid_dev["usage_page"] != options["usage_page"]:
                                    continue
                                if "usage" in options and hid_dev["usage"] != options["usage"]:
                                    continue
                                if "interface_number" in options and hid_dev["interface_number"] != options["interface_number"]:
                                    continue
                            self._hid_dev = hid_dev
                            Logger.log("d", "Found HID device with vendor_id = %x, product_id = %x, interface_number = %x", self._hid_dev["vendor_id"], self._hid_dev["product_id"], self._hid_dev["interface_number"])
                            self._cacheProfileValues(known_dev[2])
                            break
                    if self._hid_dev:
                        break
            except Exception as e:
                Logger.log("e", "Exception initialising profile: %s", e)

        if self._hid_dev:
            self._runner = Thread(target = self._run_hid, daemon = True, name = "RawMouse")
            self._runner.start()
        elif "libspnav" in self._config and os.path.exists(self._config["libspnav"]):
            Logger.log("d", "Trying libspnav...")
            global libspnav
            if libspnav is None:
                try:
                    libspnav = cdll.LoadLibrary(self._config["libspnav"])
                    setup_libspnav_fns()
                    Logger.log("d", "Initialised libspnav")
                except Exception as e:
                    Logger.log("e", "Exception initialising libspnav: %s", e)
            try:
                self._cacheProfileValues("libspnav")
            except Exception as e:
                Logger.log("e", "Exception initialising profile: %s", e)
            if libspnav is not None:
                self._runner = Thread(target = self._run_libspnav, daemon = True, name = "RawMouse")
                self._runner.start()
        if self._runner is None:
            Logger.log("w", "No mouse found!")

    def _stop(self):
        self._running = False
        while self._runner:
            self._runner.join(timeout = 2.0)

    def _run_hid(self):
        runner_started_at = QTime()
        runner_started_at.start()
        auto_restart = False
        self._running = True
        try:
            h = self._hidapi.device()
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
            self._fast_view = False
            while self._running:
                if self._main_window:
                    d = h.read(64, 50 if self._fast_view else 1000)
                    if d:
                        if self._main_window.isActive():
                            self._decoder(d)
                    elif self._fast_view:
                        self._controller.setActiveView("SimulationView")
                        self._fast_view = False
                else:
                    self._getComponents()
                    time.sleep(0.1)
            h.close()
        except IOError as e:
            Logger.log("e", "IOError while reading HID events: %s", e)
            auto_restart = (sys.platform == "win32")
        except Exception as e:
            Logger.log("e", "Exception while reading HID events: %s", e)
        self._running = False
        if auto_restart:
            # throttle restarts to avoid hogging the CPU
            min_restart_seconds = 5
            run_time = runner_started_at.elapsed() / 1000
            if  run_time < min_restart_seconds:
                Logger.log("d", "Delaying restart...")
                time.sleep(min_restart_seconds - run_time)
            if not self._running:
                self._runner = None
                self._restart()
        else:
            self._runner = None

    def _initTargetValues(self):
        self._target_values = {
            "movx": 0.0,
            "movy": 0.0,
            "rotyaw": 0.0,
            "rotpitch": 0.0,
            "rotroll": 0.0,
            "zoom": 0.0,
            "resetview": None,
            "toggleview": None,
            "maxlayer": None,
            "minlayer": None,
            "colorscheme": None,
            "cameramode": None,
            "centerobj": None
        }

    processTargetValues = Signal()

    def _processTargetValues(self):
        try:
            modifiers = QtWidgets.QApplication.queryKeyboardModifiers()
            ctrl_is_active = (modifiers & QtCore.Qt.ControlModifier) == QtCore.Qt.ControlModifier
            shift_is_active = (modifiers & QtCore.Qt.ShiftModifier) == QtCore.Qt.ShiftModifier
            alt_is_active = (modifiers & QtCore.Qt.AltModifier) == QtCore.Qt.AltModifier
            current_view = self._controller.getActiveView()
            if self._target_values["resetview"]:
                self._roll = 0
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
            elif self._target_values["maxlayer"]:
                if current_view.getPluginId() == "SimulationView":
                    layer = self._target_values["maxlayer"]
                    if layer == "max":
                        current_view.setLayer(current_view.getMaxLayers())
                    elif layer == "min":
                        current_view.setLayer(0)
                    elif isinstance(layer, int):
                        delta = layer * (10 if shift_is_active else 1)
                        current_view.setLayer(current_view.getCurrentLayer() + delta)
            elif self._target_values["minlayer"]:
                if current_view.getPluginId() == "SimulationView":
                    layer = self._target_values["minlayer"]
                    if layer == "max":
                        current_view.setMinimumLayerLayer(current_view.getMaxLayers())
                    elif layer == "min":
                        current_view.setMinimumLayer(0)
                    elif isinstance(layer, int):
                        delta = layer * (10 if shift_is_active else 1)
                        current_view.setMinimumLayer(current_view.getMinimumLayer() + delta)
            elif isinstance(self._target_values["colorscheme"], int):
                if current_view.getPluginId() == "SimulationView":
                    color_scheme = self._target_values["colorscheme"]
                    if color_scheme >= 0 and color_scheme <= 3:
                        self._application.getPreferences().setValue("layerview/layer_view_type", color_scheme)
            elif self._target_values["colorscheme"]:
                if current_view.getPluginId() == "SimulationView":
                    if self._target_values["colorscheme"] == "next":
                        color_scheme = current_view.getSimulationViewType() + 1
                        if color_scheme > 3:
                            color_scheme = 0
                        self._application.getPreferences().setValue("layerview/layer_view_type", color_scheme)
                    elif self._target_values["colorscheme"] == "prev":
                        color_scheme = current_view.getSimulationViewType() - 1
                        if color_scheme < 0:
                            color_scheme = 3
                        self._application.getPreferences().setValue("layerview/layer_view_type", color_scheme)
            elif self._target_values["cameramode"]:
                camera_mode = self._target_values["cameramode"]
                if camera_mode != "perspective" and camera_mode != "orthographic":
                    camera_mode = self._application.getPreferences().getValue("general/camera_perspective_mode")
                    camera_mode = "perspective" if camera_mode == "orthographic" else "orthographic"
                self._application.getPreferences().setValue("general/camera_perspective_mode", camera_mode)
            elif self._target_values["centerobj"]:
                target_node = None
                if Selection.getSelectedObject(0):
                    target_node = Selection.getSelectedObject(0)
                else:
                    for node in DepthFirstIterator(self._scene.getRoot()):
                        if isinstance(node, SceneNode) and node.getMeshData() and node.isSelectable():
                            target_node = node
                            break
                if target_node:
                    self._camera_tool.setOrigin(target_node.getWorldPosition())
                    camera = self._scene.getActiveCamera()
                    camera_pos = camera.getWorldPosition()
                    #Logger.log("d", "Camera pos = " + str(camera_pos))
                    if camera_pos.y < 0:
                        camera.setPosition(Vector(camera_pos.x, target_node.getBoundingBox().height, camera_pos.z))
                        camera.lookAt(target_node.getWorldPosition())
                    self._roll = 0
            elif self._camera_tool and self._last_camera_update_at.elapsed() > self._min_camera_update_period:
                if self._auto_fast_view or ctrl_is_active:
                    if self._controller.getActiveStage().getPluginId() == "PreviewStage" and self._controller.getActiveView().getPluginId() != "FastView":
                        self._controller.setActiveView("FastView")
                        self._fast_view = True
                elif self._fast_view:
                    self._controller.setActiveView("SimulationView")
                    self._fast_view = False
                if (shift_is_active or alt_is_active) and current_view.getPluginId() == "SimulationView":
                    if self._target_values["movy"] != 0.0:
                        delta = self._layer_change_increment if self._target_values["movy"] > 0 else -self._layer_change_increment
                        self._last_camera_update_at.start()
                        if shift_is_active:
                            current_view.setLayer(current_view.getCurrentLayer() + delta)
                        if alt_is_active:
                            current_view.setMinimumLayer(current_view.getMinimumLayer() + delta)
                else:
                    if self._target_values["movx"] != 0.0 or self._target_values["movy"] != 0.0:
                        self._last_camera_update_at.start()
                        self._camera_tool._moveCamera(MouseEvent(MouseEvent.MouseMoveEvent, self._target_values["movx"], self._target_values["movy"], 0, 0))
                    if self._target_values["rotyaw"] != 0 or self._target_values["rotpitch"] != 0  or self._target_values["rotroll"] != 0:
                        self._last_camera_update_at.start()
                        self._rotateCamera(self._target_values["rotyaw"], self._target_values["rotpitch"], self._target_values["rotroll"])
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
            if buf[1] != self._battery_level:
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
                self.processTargetValues.emit()

    def _spacemouseButtonEvent(self, button, val):
        if self._verbose > 0:
            Logger.log("d", "button[%d] = %f", button, val)
        if val == 1:
            self._initTargetValues();
            process = False
            button_defs = self._profile["buttons"]
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
            button_defs = self._profile["buttons"]
            for b in button_defs:
                if buttons == int(b, base = 16):
                    self._target_values[button_defs[b]["target"]] = button_defs[b]["value"]
                    process = True
        if process:
            if not self._redraw_pending:
                self._redraw_pending = True
                self.processTargetValues.emit()

    def _decodeUnknownEvent(self, buf):
        Logger.log("d", "Unknown event: len = %d [0] = %x", len(buf), buf[0])

    def _getScalingDueToZoom(self):
        scale = 1.0
        if self._scene:
            zoom_factor = self._scene.getActiveCamera().getZoomFactor()
            if zoom_factor < -0.4:
                scale = 0.1 + 9 * (zoom_factor - -0.5)
                #Logger.log("d", "scale = %f", scale)
        return scale

    def _showDeviceInformation(self):
        try:
            message = "No device found"
            if self._hid_dev:
                message = "Manufacturer: " + self._hid_dev["manufacturer_string"] + "\nProduct: " + self._hid_dev["product_string"] + "\nProfile: " + self._profile_name
            elif libspnav is not None:
                message = "Using libspnav"
            if self._battery_level is not None:
                message += "\nBattery level: " + str(self._battery_level) + "%"
            if self._profile:
                message += "\nAxes:"
                for i in range(0, len(self._axis_scale)):
                    message += "\n&nbsp;[" + str(i) + "] scale " + str(self._axis_scale[i]) + " threshold " + str(self._axis_threshold[i]) + " offset " + str(self._axis_offset[i]) + " -> " + self._axis_target[i]
                message += "\nButttons:"
                button_defs = self._profile["buttons"]
                for b in sorted(button_defs):
                    message += "\n&nbsp;[" + b + "] target " + button_defs[b]["target"] + " value " + str(button_defs[b]["value"])
            message += "\nModifiers:\n " + ("Cmd" if sys.platform == "darwin" else "Ctrl") + " = switch from preview to fastview\n Shift-movy = move max layer slider\n Alt-movy = move min layer slider"
            self._showMessage(message)
        except Exception as e:
            Logger.log("e", "Exception while showing device information: %s", e)

    def _showMessage(self, str):
        if self._message is None:
            self._message = Message(title=catalog.i18nc("@info:title", "RawMouse " + self.getVersion()))
        self._message.hide()
        self._message.setText(catalog.i18nc("@info:status", str))
        self._message.show()

    def _rotateCamera(self, yaw: float, pitch: float, roll: float) -> None:
        camera = self._scene.getActiveCamera()
        if not camera or not camera.isEnabled():
            return

        dyaw = math.radians(yaw * 180.0)
        dpitch = math.radians(pitch * 180.0)
        droll = math.radians(roll * 180.0)

        diff = camera.getPosition() - self._camera_tool._origin

        myaw = Matrix()
        myaw.setByRotationAxis(dyaw, Vector.Unit_Y)

        mpitch = Matrix(myaw.getData())
        mpitch.rotateByAxis(dpitch, Vector.Unit_Y.cross(diff))

        n = diff.multiply(mpitch)

        try:
            angle = math.acos(Vector.Unit_Y.dot(n.normalized()))
        except ValueError:
            return

        if angle < 0.1 or angle > math.pi - 0.1:
            n = diff.multiply(myaw)

        n += self._camera_tool._origin

        camera.setPosition(n)

        if abs(self._roll + droll) < math.pi * 0.45:
            self._roll += droll;
        mroll = Matrix()
        mroll.setByRotationAxis(self._roll, (n - self._camera_tool._origin))
        camera.lookAt(self._camera_tool._origin, Vector.Unit_Y.multiply(mroll))

    def _run_libspnav(self):
        self._running = True
        Logger.log("d", "Reading events from libspnav...")
        try:
            if spnavOpen() == False:
                self._last_camera_update_at = QTime()
                self._last_camera_update_at.start()
                self._fast_view = False
                while self._running:
                    if self._main_window:
                        event = spnavWaitEvent()
                        if event is not None:
                            if self._main_window.isActive():
                                if event.type == SPNAV_EVENT_MOTION:
                                    if event.motion.x == 0 and event.motion.y == 0 and event.motion.z == 0 and event.motion.rx == 0 and event.motion.ry == 0 and event.motion.rz == 0:
                                        if self._fast_view:
                                            self._controller.setActiveView("SimulationView")
                                            self._fast_view = False
                                    scale = 1 / 500.0
                                    self._spacemouseAxisEvent([
                                        event.motion.x * scale * self._axis_scale[0] + self._axis_offset[0],
                                        event.motion.y * scale * self._axis_scale[1] + self._axis_offset[1],
                                        event.motion.z * scale * self._axis_scale[2] + self._axis_offset[2],
                                        event.motion.rx * scale * self._axis_scale[3] + self._axis_offset[3],
                                        event.motion.ry * scale * self._axis_scale[4] + self._axis_offset[4],
                                        event.motion.rz * scale * self._axis_scale[5] + self._axis_offset[5]
                                    ])
                                elif event.type == SPNAV_EVENT_BUTTON:
                                    self._spacemouseButtonEvent(event.button.bnum, event.button.press)
                    else:
                        self._getComponents()
                        time.sleep(0.1)
                spnavClose()
            else:
                Logger.log("e", "spnavOpen() failed")
        except Exception as e:
            Logger.log("e", "Exception while reading libspnav events: %s", e)
        self._running = False
        self._runner = None

# -----------------------------------------------------------------------------
# Definitions for data structures of spnav library
#
# Copied from https://github.com/xythobuz/spacenav-plus, thanks!

# enum {
#     SPNAV_EVENT_ANY = 0,	/* used by spnav_remove_events() */
#     SPNAV_EVENT_MOTION = 1,
#     SPNAV_EVENT_BUTTON = 2	/* includes both press and release */
# };
(SPNAV_EVENT_ANY, SPNAV_EVENT_MOTION, SPNAV_EVENT_BUTTON) = (0, 1, 2)

# struct spnav_event_motion {
#     int type;
#     int x, y, z;
#     int rx, ry, rz;
#     unsigned int period;
#     int *data;
# };
class SpnavMotionEvent(Structure): pass
SpnavMotionEvent._fields_ = [
    ('type', c_int),
    ('x', c_int),
    ('y', c_int),
    ('z', c_int),
    ('rx', c_int),
    ('ry', c_int),
    ('rz', c_int),
    ('period', c_uint),
    ('data', POINTER(c_uint))
]

# struct spnav_event_button {
#     int type;
#     int press;
#     int bnum;
# };
class SpnavButtonEvent(Structure): pass
SpnavButtonEvent._fields_ = [
    ('type', c_int),
    ('press', c_int),
    ('bnum', c_int)
]

# typedef union spnav_event {
#     int type;
#     struct spnav_event_motion motion;
#     struct spnav_event_button button;
# } spnav_event;
class SpnavEvent(Union): pass
SpnavEvent._fields_ = [
    ('type', c_int),
    ('motion', SpnavMotionEvent),
    ('button', SpnavButtonEvent)
]

# -----------------------------------------------------------------------------
# Actual python wrapper methods

# Open connection to the daemon via AF_UNIX socket
# Returns 'True' on error, 'False' on success
def spnavOpen():
    result = libspnav.spnav_open()
    if result == -1:
        return True
    return False

# Close connection to the daemon
# Returns 'True' on error, 'False' on success
def spnavClose():
    result = libspnav.spnav_close()
    if result == -1:
        return True
    return False

# Blocks waiting for space-nav events
# Returns 'None' on error or an event on success
def spnavWaitEvent():
    event = SpnavEvent(SPNAV_EVENT_ANY,
                  SpnavMotionEvent(0, 0, 0, 0, 0, 0, 0, 0, None),
                  SpnavButtonEvent(0, 0, 0))
    result = libspnav.spnav_wait_event(byref(event))
    if result == 0:
        return None
    return event

# Checks for the availability of space-nav events (non-blocking)
# Returns 'None' if no event available or an event on success
def spnavPollEvent():
    event = SpnavEvent(SPNAV_EVENT_ANY,
                  SpnavMotionEvent(0, 0, 0, 0, 0, 0, 0, 0, None),
                  SpnavButtonEvent(0, 0, 0))
    result = libspnav.spnav_poll_event(byref(event))
    if result == 0:
        return None
    return event

# Removes any pending events from the specified type, or all pending
# events if the type argument is SPNAV_EVENT_ANY. Returns the number
# of removed events.
def spnavRemoveEvents(eventType):
    return libspnav.spnav_remove_events(eventType)

def setup_libspnav_fns():
    # int spnav_open(void);
    libspnav.spnav_open.restype = c_int
    #libspnav.spnav_open.argtypes = [None]
    # int spnav_close(void);
    libspnav.spnav_close.restype = c_int
    #libspnav.spnav_close.argtypes = [None]
    # int spnav_wait_event(spnav_event *event);
    libspnav.spnav_wait_event.restype = c_int
    libspnav.spnav_wait_event.argtypes = [POINTER(SpnavEvent)]
    # int spnav_poll_event(spnav_event *event);
    libspnav.spnav_poll_event.restype = c_int
    libspnav.spnav_poll_event.argtypes = [POINTER(SpnavEvent)]
    # int spnav_remove_events(int type);
    libspnav.spnav_remove_events.restype = c_int
    libspnav.spnav_remove_events.argtypes = [c_int]

