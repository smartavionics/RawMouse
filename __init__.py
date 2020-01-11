# Copyright (c) 2020 burtoogle.
# HIDMouse is released under the terms of the AGPLv3 or higher.

from . import HIDMouse

def getMetaData():
    return { }

def register(app):
    return { "extension": HIDMouse.HIDMouse() }
