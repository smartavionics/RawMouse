# Copyright (c) 2020 burtoogle.
# HIDTest is released under the terms of the AGPLv3 or higher.

from . import HIDTest

def getMetaData():
    return { }

def register(app):
    return { "extension": HIDTest.HIDTest() }
