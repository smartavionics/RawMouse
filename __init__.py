# Copyright (c) 2020 burtoogle.
# RawMouse is released under the terms of the AGPLv3 or higher.

from . import RawMouse

def getMetaData():
    return { }

def register(app):
    return { "extension": RawMouse.RawMouse() }
