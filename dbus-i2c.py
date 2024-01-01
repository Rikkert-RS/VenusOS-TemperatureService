#!/usr/bin/env python

# Copyright (c) 2021 LHardwick-git Edit by Rikkert-RS
# Licensed under the BSD 3-Clause license. See LICENSE file in the project root for full license information.
#
# takes data from the i2c and adc channels (which are not used by venus) and publishes the data on the bus.

# If edditing then use 
# svc -d /service/VenusOS-TemperatureService and
# svc -u /service/VenusOS-TemperatureService
# to stop and restart the service 

#--------------------- support python 2 and 3
import sys
if sys.version_info.major == 3:
	python3 = True
else:
	python3 = False

from dbus.mainloop.glib import DBusGMainLoop

if python3:
    from gi.repository import GLib # for Python 3
else:
	from gobject import idle_add
	import gobject as GLib
#---------------------

import dbus
import dbus.service
import inspect
import platform
from threading import Timer
import argparse
import logging
import os
from pprint import pprint
#---------------------
# Import i2c interface driver, this is a modified library stored in the same directory as this file
from i2c import AM2320 as AM2320

# our own packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-modem'))
from vedbus import VeDbusService, VeDbusItemExport, VeDbusItemImport 
from settingsdevice import SettingsDevice  # available in the velib_python repository

SCount = 0
dbusservice = None

def update():
# Calls to update ADC and I2C interfaces have been commented out
# The is in case someone runes this who does not know what they are doing 
# and does not have i2c devices and/or does not want or have the extra ADC channels.
# I have left the code in in case you wanton enable them
#
# So the only service left running is the Raspberry pi CPU temperature.
#
#   update_rpi()
    update_W1()
#    update_i2c()
   update_adc()
    return True

# update i2c interface values
def update_i2c():
    if not os.path.exists('/dev/i2c-1'):
        if dbusservice['i2c-humidity']['/Connected'] != 0:
            logging.info("i2c interface disconnected")
            dbusservice['i2c-humidity']['/Connected'] = 0
            dbusservice['i2c-temperature']['/Connected'] = 0
        logging.info("i2c bus not available")
    else:
        am2320 = AM2320(1)
        (t,h,e, report) = am2320.readSensor()
#       Returns temperature, humidity, error ststus, and text report
        if e != 0:
            logging.info("Error in i2c bus read, "+ report)
            dbusservice['i2c-humidity']['/Status'] = e
            dbusservice['i2c-temp']['/Status'] = e
            dbusservice['i2c-humidity']['/Humidity'] = []
            dbusservice['i2c-temp']['/Temperature'] = []
        else:
            if dbusservice['i2c-humidity']['/Connected'] != 1:
               logging.info("i2c bus device connected")
               dbusservice['i2c-humidity']['/Connected'] = 1            
               dbusservice['i2c-temp']['/Connected'] = 1
            dbusservice['i2c-humidity']['/Status'] = 0
            dbusservice['i2c-temp']['/Status'] = 0
        logging.debug("values now are temperature %s, humidity %s" % (t, h))
        dbusservice['i2c-humidity']['/Humidity'] = h
        dbusservice['i2c-temp']['/Temperature'] = t

def update_adc():
#   update adc interface values
#   scale is hard coded here but could be implemented as a /scale setting in the dbus object
    scale = 1

#   the device iio:device 0 is the device running all adc channels 
#   there are repeated calls here to check the device exists to set the ststus for every channel
#   it is assumed there is little overhead in this repeated call to the system.

    for channel in [0, 1, 7]:
        if not os.path.exists('/sys/bus/iio/devices/iio:device0'):
            if dbusservice['adc-temp'+str(channel)]['/Connected'] != 0:
                logging.info("adc interface disconnected")
                dbusservice['adc-temp'+str(channel)]['/Connected'] = 0
        else:
            if dbusservice['adc-temp'+str(channel)]['/Connected'] != 1:
                logging.info("adc interface channel " + str(channel) + " connected")
                dbusservice['adc-temp'+str(channel)]['/Connected'] = 1
            fd  = open('/sys/bus/iio/devices/iio:device0/in_voltage'+str(channel)+'_raw','r')

            value = 0
            for loop in range (0,10):
                value += int(fd.read())
                fd.seek(0)
            fd.close
            value = value / 10
            value = dbusservice['adc-temp'+str(channel)]['/Offset']+round(2.1+(value-2015)*0.135*scale,1)
            # logging.info(" Temperature "+str(value))
            # added stuff here for short circuit and disconnect status
            if value > 140:
                dbusservice['adc-temp'+str(channel)]['/Status'] = 1
                dbusservice['adc-temp'+str(channel)]['/Temperature'] = []
            elif value < -100:
                dbusservice['adc-temp'+str(channel)]['/Status'] = 2
                dbusservice['adc-temp'+str(channel)]['/Temperature'] = []
            else:
                dbusservice['adc-temp'+str(channel)]['/Status'] = 0
                dbusservice['adc-temp'+str(channel)]['/Temperature'] = value
 
   

#   update Pi CPU temperature 

#update W1 temp
def update_W1():
#check, create and update 1 Wire devices

    #read list of slaves
    if os.path.isfile('/sys/devices/w1_bus_master1/w1_master_slaves'):
        fd = open('/sys/devices/w1_bus_master1/w1_master_slaves','r')
        w1Slaves = fd.read().splitlines()
        fd.close
        
        #Loop through all connected 1Wire devices, create dbusService if necessary
        for id in w1Slaves: 
            familyID = id[0:2]
            deviceID = id[3:]
            logging.debug("1Wire Family ID:" + familyID + " Full DevicesID:" + id)
            
            #DS18B20 Temp Sensors
            if familyID == '28':
                if ('W1-temp:'+ id) not in dbusservice:
                    logging.info("1Wire Sensor found with no Service -> Create:")
                                    
                    dbusservice['W1-temp:'+ id] = new_service(base, 'temperature', 'Wire', '1Wire', SCount+1, 100+SCount, deviceID)
                    dbusservice['W1-temp:'+ id]['/ProductName'] = '1Wire Sensor ' + id
                    dbusservice['W1-temp:'+ id]['/HardwareVersion'] = deviceID
                    dbusservice['W1-temp:'+ id]['/FirmwareVersion'] = familyID
                    initSettings(newSettings)
                    readSettings(settingObjects)
                    logging.info("Created Service 1Wire ID: " + str(SCount) + " Settings ID:" + str(SCount))
                
                #read Temp value
                value = None #invalidate value
                if os.path.exists('/sys/devices/w1_bus_master1/'+ id +'/temperature'):
                    fd  = open('/sys/devices/w1_bus_master1/'+ id +'/temperature','r')
                    lines = fd.read().splitlines()
                    if lines: 
                        logging.debug("RawValue ID" + id + ":" + lines[0])
                        if lines[0].strip('-').isnumeric():
                            value = float(lines[0])
                            value = round(value / 1000.0, 1)
                    fd.close
                    
                dbusservice['W1-temp:'+ id]['/Temperature'] = value

    #Check 1 Wire Service Connection
    for item in dbusservice:
        logging.debug("Search for 1Wire Service Current Service: " + item)
        if dbusservice[item]['/Mgmt/Connection'] == '1Wire':
            logging.debug("Found 1 Wire Service Check connection")
            if not os.path.exists('/sys/devices/w1_bus_master1/'+ item[8:]):
                if dbusservice[item]['/Connected'] != 0:
                    logging.info(item + " temperature interface disconnected")
                    dbusservice[item]['/Connected'] = 0
                    dbusservice[item]['/Status'] = 1
                    dbusservice[item]['/Temperature'] = None
            else:
                if dbusservice[item]['/Connected'] != 1:
                    logging.info(item + " temperature interface connected")
                    dbusservice[item]['/Connected'] = 1
                    dbusservice[item]['/Status'] = 0
    

# =========================== Start of settings interface ================
#  The settings interface handles the persistent storage of changes to settings
#  This should probably be created as a new class extension to the settingDevice object
#  The complexity is because this python service handles temperature and humidity
#  Data for about 6 different service paths so we need different dBusObjects for each device
#
newSettings = {}     # Used to gather new settings to create/check as each dBus object is created
settingObjects = {}  # Used to identify the dBus object and path for each setting
                     # settingsObjects = {setting: [path,object],}
                     # each setting is the complete string e.g. /Settings/Temperature/4/Scale

settingDefaults = {'/Offset': [0, -10, 10],
                   '/Scale'  : [1.0, -5, 5],
                   '/TemperatureType'   : [0, 0, 3],
                   '/CustomName'        : ['', 0, 0]}

# Values changed in the GUI need to be updated in the settings
# Without this changes made through the GUI change the dBusObject but not the persistent setting
# (as tested in venus OS 2.54 August 2020)
def handle_changed_value(setting, path, value):
    global settings
    print("some value changed")
    # The callback to the handle value changes has been modified by using an anonymouse function (lambda)
    # the callback is declared each time a path is added see example here
    # self.add_path(path, 0, writeable=True, onchangecallback = lambda x,y: handle_changed_value(setting,x,y) )
    logging.info(" ".join(("Storing change to setting", setting+path, str(value) )) )
    settings[setting+path] = value
    return True

# Changes made to settings need to be reflected in the GUI and in the running service
def handle_changed_setting(setting, oldvalue, newvalue):
    logging.info('Setting changed, setting: %s, old: %s, new: %s' % (setting, oldvalue, newvalue))
    [path, object] = settingObjects[setting]
    object[path] = newvalue
    return True

# Add setting is called each time a new service path is created that needs a persistent setting
# If the setting already exists the existing recored is unchanged
# If the setting does not exist it is created when the serviceDevice object is created
def addSetting(base, path, dBusObject):
    global settingObjects
    global newSettings
    global settingDefaults
    setting = base + path
    logging.info(" ".join(("Add setting", setting, str(settingDefaults[path]) )) )
    settingObjects[setting] = [path, dBusObject]             # Record the dBus Object and path for this setting 
    newSettings[setting] = [setting] + settingDefaults[path] # Add the setting to the list to be created

# initSettings is called when all the required settings have been added
def initSettings(newSettings):
    global settings

#   settingsDevice is the library class that handles the reading and setting of persistent settings
    settings = SettingsDevice(
        bus=dbus.SystemBus() if (platform.machine() == 'armv7l') else dbus.SessionBus(),
        supportedSettings = newSettings,
        eventCallback     = handle_changed_setting)

# readSettings is called after init settings to read all the stored settings and
# set the initial values of each of the service object paths
# Note you can not read or set a setting if it has not be included in the newSettings
#      list passed to create the new settingsDevice class object

def readSettings(list):
    global settings
    for setting in list:
        [path, object] = list[setting]
        logging.info(" ".join(("Retreived setting", setting, path, str(settings[setting]))))
        object[path] = settings[setting]


# =========================== end of settings interface ======================

class SystemBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SYSTEM)

class SessionBus(dbus.bus.BusConnection):
    def __new__(cls):
        return dbus.bus.BusConnection.__new__(cls, dbus.bus.BusConnection.TYPE_SESSION)

def dbusconnection():
    return SessionBus() if 'DBUS_SESSION_BUS_ADDRESS' in os.environ else SystemBus()


# Argument parsing
parser = argparse.ArgumentParser(description='dbusMonitor.py demo run')
parser.add_argument("-n", "--name", help="the D-Bus service you want me to claim", type=str, default="com.victronenergy.i2c")
parser.add_argument("-i", "--deviceinstance", help="the device instance you want me to be", type=str, default="0")
parser.add_argument("-d", "--debug", help="set logging level to debug", action="store_true")
args = parser.parse_args()

#args.debug = True

# Init logging
logging.basicConfig(level=(logging.DEBUG if args.debug else logging.INFO))
if python3:
	logging.info(__file__ + " is starting up - python 3")
else:
	logging.info(__file__ + " is starting up - python 2")
logLevel = {0: 'NOTSET', 10: 'DEBUG', 20: 'INFO', 30: 'WARNING', 40: 'ERROR'}
logging.info('Loglevel set to ' + logLevel[logging.getLogger().getEffectiveLevel()])

# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
DBusGMainLoop(set_as_default=True)

def new_service(base, type, physical, logical, id, instance, settingId = False):
    global SCount
    self =  VeDbusService("{}.{}.{}_id{:02d}".format(base, type, physical,  id), dbusconnection())
    # physical is the physical connection 
    # logical is the logical connection to allign with the numbering of the console display
    # Create the management objects, as specified in the ccgx dbus-api document
    self.add_path('/Mgmt/ProcessName', __file__)
    self.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self.add_path('/Mgmt/Connection', logical)

    # Create the mandatory objects, note these may need to be customised after object creation
    self.add_path('/DeviceInstance', instance)
    self.add_path('/ProductId', 0)
    self.add_path('/ProductName', '')
    self.add_path('/FirmwareVersion', 0)
    self.add_path('/HardwareVersion', 0)
    self.add_path('/Connected', 0)  # Mark devices as disconnected until they are confirmed

    # Create device type specific objects set values to empty until connected
    if settingId :
        setting = "/Settings/" + type.capitalize() + "/" + str(settingId)
    else:
        print("no setting required")
        setting = "" 
    if type == 'temperature':
        self.add_path('/Temperature', [])
        self.add_path('/Status', 0)
        if settingId:
            addSetting(setting , '/TemperatureType', self)
            addSetting(setting , '/CustomName', self)
        self.add_path('/TemperatureType', 0, writeable=True, onchangecallback = lambda x,y: handle_changed_value(setting,x,y) )
        self.add_path('/CustomName', '', writeable=True, onchangecallback = lambda x,y: handle_changed_value(setting,x,y) )
        self.add_path('/Function', 1, writeable=True )
        if 'adc' in physical:
            if settingId:
                addSetting(setting,'/Scale',self)
                addSetting(setting,'/Offset',self)
            self.add_path('/Scale', 1.0, writeable=True, onchangecallback = lambda x,y: handle_changed_value(setting,x,y) )
            self.add_path('/Offset', 0, writeable=True, onchangecallback = lambda x,y: handle_changed_value(setting,x,y) )
    if type == 'humidity':
        self.add_path('/Humidity', [])
        self.add_path('/Status', 0)
    SCount += 1
    return self

dbusservice = {} # Dictionary to hold the multiple services

base = 'com.victronenergy'

# Init setting - create setting object to read any existing settings
# Init is called again later to set anything that does not exist
# this gets round the Chicken and Egg bootstrap problem,

# service defined by (base*, type*, connection*, logical, id*, instance, settings ID):
# The setting iD is used with settingsDevice library to create a persistent setting
# Items marked with a (*) are included in the service name
#
# I have commented out the bits that will make new services for i2C and ADC services here
# If you want to re-enable these you need to uncomment the right lines
# !!! Importand do NOT set an Dash in "connection" Parameter

#dbusservice['i2c-temp']     = new_service(base, 'temperature', 'i2c',      'i2c Device 1',  0, 25, 7) 
#dbusservice['i2c-humidity'] = new_service(base, 'humidity',    'i2c',      'i2c Device 1',  0, 25)
# Tidy up custom or missing items
#dbusservice['i2c-temp']    ['/ProductName']     = 'Encased i2c AM2315'
#dbusservice['i2c-humidity']['/ProductName']     = 'Encased i2c AM2315'

dbusservice['adc-temp0']    = new_service(base, 'temperature', 'RPi_adc0', 'Temperature sensor input 3',  0, 26, 3)
#dbusservice['adc-temp1']    = new_service(base, 'temperature', 'RPi_adc1', 'Temperature sensor input 4',  1, 27, 4)
#dbusservice['adc-temp7']    = new_service(base, 'temperature', 'RPi_adc7', 'Temperature sensor input 5',  2, 28, 5)
# Tidy up custom or missing items
dbusservice['adc-temp0']   ['/ProductName']     = 'Custard Pi-3 8x12bit adc'
#dbusservice['adc-temp1']   ['/ProductName']     = 'Custard Pi-3 8x12bit adc'
#dbusservice['adc-temp7']   ['/ProductName']     = 'Custard Pi-3 8x12bit adc'

# Raspy CPU Temp
#dbusservice['cpu-temp'] = new_service(base, 'temperature', 'RPi_cpu', 'Raspberry Pi OS', SCount+1, 100, SCount+1)
# Tidy up custom or missing items

# Persistent settings obejects in settingsDevice will not exist before this is executed
initSettings(newSettings)
# Do something to read the saved settings and apply them to the objects
readSettings(settingObjects)

# Do a first update so that all the readings appear.
update()
# update every 10 seconds - temperature and humidity should move slowly so no need to demand
# too much CPU time
#

#---------------------- support python 2 and 3
GLib.timeout_add(10000, update)
mainloop = GLib.MainLoop()
logging.info ('Connected to dbus, and switching over to GLib.MainLoop() (= event based)')
mainloop.run()
#----------------------


