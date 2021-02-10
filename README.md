
# RawMouse

---

RawMouse is a Cura plugin that provides raw (driverless) access to HID mice such as the 3Dconnexion spacemouse.

Primarily intended for use on Linux (tested on Ubuntu 16.04.6), it does also work on Windows (tested on Windows 10) and MacOS (tested on MacOS 10.13).

The plugin includes binary components (cython-hidapi) that are required to access USB devices.

On Linux and MacOS, as an alternative to accessing HID devices, RawMouse can use the libspnav library to access spacemice if that is installed on the system.

---

### Limitations

This plugin can only be used with devices whose HID message protocol it knows about. At this time, the only supported devices are a bunch of 3Dconnexion Spacemice products
and a Gravis Tiltpad (which I don't seriously expect anyone to try and use with Cura). If you have some other device that you would like to use and have a description of the
HID messages it uses then it can be added.

On systems that have an existing driver installed, you may need to disable that driver so that RawMouse can gain access to the device. On Windows, there is a *Stop 3DxWare* command that disables the
normal Spacemouse driver. (**edit 25/04/20, users report that on Windows you do not need to stop or disable the existing driver when using RawMouse**)

**Does not work on MacOS Big Sur with the 3Dconnexion driver active, may possibly work with that driver disabled. Works OK on earlier MacOS versions.**

---

### Installation

Download or clone this repository into [Cura configuration folder]/plugins/RawMouse
The configuration folder can be found via **Help -> Show Configuration Folder** inside Cura.

Alternatively, download and unzip a release.

Cloning this repository is best because then you can make local edits to the configuration file and even RawMouse.py and still be able to merge future updates without losing any changes you have made.

---

### Linux Permissions

On Linux, you need to allow non-root users access to the hidraw devices. That can be done by creating a file **/etc/udev/rules.d/10-hidraw.rules** that contains the following:

`KERNEL=="hidraw*", SUBSYSTEM=="hidraw", MODE="0666"`

If you don't like giving everyone r/w access to all HID devices you can use a different rule to allow only users of a particular group to have access, e.g:

`KERNEL=="hidraw*", SUBSYSTEM=="hidraw", MODE="0660" GROUP="plugdev"`

---

### Configuration

RawMouse is configured using a JSON file (config.json) that is located in the RawMouse plugin directory.

The configuration file can be edited when Cura is already running and reloaded using the Extensions -> RawMouse -> Restart menu item.

JSON syntax is quite unforgiving so it's easy to make an invalid file by missing (or adding) a comma, bracket, etc. If there are any problems with the configuration,
it will be reported in the cura.log file.

The configuration file elements are:

**maxhz** max number of screen updates per second

**fastview** set to non-zero to automatically switch to the fast view when moving the layer view

**verbose** set to non-zero to increase logging verbosity

**devices** is an array of device definitions, one for each supported device. Each definition is an array whose elements specify the vendor and product USB ids for the device, the name of the device profile to use and a description. Optionally, an extra dictionary of additional values can be specified.
> Currently, the additional values *platform*, *usage_page*, *usage* and *interface_number* values are recognised and they are used to select a particular HID device/interface when the device
 presents multiple interfaces. By default, *interface_number* is not required but you may need to add this if you are using a wireless receiver that is paired with multiple devices.

This configuration file element (devices) is not required if libspnav (see below) is used to access a spacemouse.

**profiles** is dictionary of profile definitions. Each profile definition defines the axes and buttons the profile knows about.
>
>**axes** is an array of axis definitions, one for each of the device's axes. Each definition specifies the *offset*, *scale*, *threshold* and *target* values for the axis.
>>
>>**offset** is added to the axis value to remove any bias the device may have.
>>
>>**scale** scales the axis value. If you want to make the axis faster, increase the value. To slow the axis down, reduce the value. To flip the direction of movement, change the sign.
>>
>>**threshold** is the minimum value an axis must have before it has any effect.
>>
>>**target** is the name of the function that will be invoked when the axis value is greater than the threshold. Current target names are: "movx", "movy", "zoom", "rotpitch", "rotroll" and "rotyaw".

>**buttons** is a dictionary of button definitions. The element keys are strings that match the button state and the value is a dictionary that specifies *value* and and *target* for the button.
When a button is activated, the specified target function is passed the value. The supported target functions are:
>>**resetview** sets the view to the orientation specified by the value which should be one of ["3d"], ["home"], ["x", *dir*] or ["y", *dir*] where *dir* is an angle such as 90. You need the square brackets.
>>
>>**toggleview** toggles between the prepare and preview screens, it requires a non-zero value.
>>
>>**maxlayer** and **minlayer** adjust the preview layer slider max and min values. A value of "max" selects the topmost layer, a value of "min" selects the first layer. Alternatively, an integer value (positive or negative) will be added to the current layer and if you hold the shift key down at the same time, the value is multiplied by 10.
>>
>>**colorscheme** sets the preview colour scheme. Integer values from 1 to 4 select from "Material Color", "Line Type", "Speed" or "Layer Thickness", a value of "next" cycles to the next option and a value of "prev" cycles to the previous option.
>>
>>**cameramode** sets the camera mode, the value can be either "perspective" or "orthographic" to set the specified mode or any other non-false value to toggle between the modes.
>>
>>**centreobj** if an object is selected, move the camera so that the object is centered on the screen. If no object is selected, center the first object on the screen. It requires a non-zero value.
>>

**libspnav** on Linux and MacOS, this can be set to the pathname of the libspnav dynamic library (e.g."/usr/local/lib/libspnav.so"). Devices accessed using this library will use the *libspnav* profile.

The Spacemice are configured so that button 1 resets the view (useful when you get lost in space) and button 2 toggles between the Cura prepare and preview screens.

---

### Menu

The menu **Extensions -> RawMouse** provides these items:

**Stop** stops the thread that reads the mouse events.

**Restart** stops the event reading thread, reloads the configuration file and restarts the thread. Use this to make RawMouse aware of changes to config.json.

**Show Device Information** pops up a dialog showing some information about the HID device in use along with the current axis definitions and some help blurb.

---

### Warranty & License

RawMouse is supplied with no warranty.

RawMouse is released under the terms of the [AGPLv3](LICENSE) or higher.

---

### Kudos

RawMouse uses [cython-hidapi](https://github.com/trezor/cython-hidapi) to access the HID devices.

---

### Known Issues

* Complex models can be slow to move when the preview screen is active but there's not much that can be done about that here. As of version 1.0.6, holding the CTRL key
 (CMD key on MacOS) down while moving the layer view will switch to a faster simple shaded view for the duration of the move and then go back to the layer view when the movement finishes.

* The rotation motion is rather weird because it's still using the original 2D mouse code.

---

### History

1.0.0 - initial release.

1.0.1 - fix meta data blunder.

1.0.2 - fix Universal Receiver not working on Windows.

1.0.3 - implemented rotroll target and renamed rotx -> rotyaw and roty -> rotpitch.

1.0.4 - fix Universal Receiver not working on MacOS.

1.0.5 - now ignores HID device when Cura loses the focus.

1.0.6 - holding CTRL (CMD on MacOS) while moving the layer view displays a simple shaded view.

1.0.7 - fixed yet another blunder with the Universal Receiver (3rd time lucky?)

1.0.8 - minor tweaks, added Space Mouse Enterprise device.

1.0.9 - added support for libspnav (Linux and MacOS only).

1.0.10 - now heeds interface_number (if specified) to select HID device + shift-movy moves the top layer slider handle, alt-movy moves the bottom layer slider handle.

1.0.11 - added support for 64 bit ARM platforms.

1.0.12 - added maxlayer, minlayer, colorscheme, cameramode and centreobj button functions and made centreobj the default for button 1.

---

