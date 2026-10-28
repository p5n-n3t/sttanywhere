#!/usr/bin/env python3
"""Private X11 activity guard. Records only a changed/not-changed flag, never keys."""
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import re
import signal
import sys


class Range8(C.Structure):
    _fields_ = [('first', C.c_ubyte), ('last', C.c_ubyte)]


class Range16(C.Structure):
    _fields_ = [('first', C.c_ushort), ('last', C.c_ushort)]


class ExtRange(C.Structure):
    _fields_ = [('major', Range8), ('minor', Range16)]


class RecordRange(C.Structure):
    _fields_ = [('requests', Range8), ('replies', Range8), ('ext_requests', ExtRange),
                ('ext_replies', ExtRange), ('delivered', Range8), ('device', Range8),
                ('errors', Range8), ('started', C.c_int), ('died', C.c_int)]


class Intercept(C.Structure):
    _fields_ = [('id', C.c_ulong), ('time', C.c_ulong), ('sequence', C.c_ulong),
                ('category', C.c_int), ('swapped', C.c_int), ('data', C.POINTER(C.c_ubyte)),
                ('length', C.c_ulong)]


def xlib():
    lib = C.CDLL(ctypes.util.find_library('X11'))
    lib.XOpenDisplay.argtypes = [C.c_char_p];lib.XOpenDisplay.restype = C.c_void_p
    lib.XGetInputFocus.argtypes = [C.c_void_p,C.POINTER(C.c_ulong),C.POINTER(C.c_int)]
    lib.XDefaultRootWindow.argtypes = [C.c_void_p];lib.XDefaultRootWindow.restype = C.c_ulong
    lib.XStringToKeysym.argtypes = [C.c_char_p];lib.XStringToKeysym.restype = C.c_ulong
    lib.XKeysymToKeycode.argtypes = [C.c_void_p,C.c_ulong];lib.XKeysymToKeycode.restype = C.c_ubyte
    lib.XSync.argtypes = [C.c_void_p,C.c_int]
    return lib


def focus_id():
    lib=xlib();display=lib.XOpenDisplay(None)
    if not display: raise ValueError('X11 display unavailable')
    try:
        window=C.c_ulong();revert=C.c_int()
        lib.XGetInputFocus(display,C.byref(window),C.byref(revert))
        return str(window.value)
    finally:
        lib.XCloseDisplay.argtypes=[C.c_void_p];lib.XCloseDisplay(display)


def main():
    os.umask(0o077)
    path=Path(sys.argv[1]);shortcut=sys.argv[2]
    signal.alarm(int(sys.argv[3]))
    lib=xlib();control=lib.XOpenDisplay(None);data_display=lib.XOpenDisplay(None)
    if not control or not data_display: raise ValueError('Cannot monitor X11 display')
    record=C.CDLL(ctypes.util.find_library('Xtst'))
    record.XRecordQueryVersion.argtypes=[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_int)]
    major=C.c_int();minor=C.c_int()
    if not record.XRecordQueryVersion(control,C.byref(major),C.byref(minor)):
        raise ValueError('X11 RECORD extension unavailable')
    record.XRecordAllocRange.restype=C.POINTER(RecordRange)
    requested=record.XRecordAllocRange();requested.contents.device.first=2;requested.contents.device.last=4
    requested.contents.delivered.first=9;requested.contents.delivered.last=10
    clients=(C.c_ulong*1)(3);ranges=(C.POINTER(RecordRange)*1)(requested)
    record.XRecordCreateContext.argtypes=[C.c_void_p,C.c_int,C.POINTER(C.c_ulong),C.c_int,C.POINTER(C.POINTER(RecordRange)),C.c_int]
    record.XRecordCreateContext.restype=C.c_ulong
    context=record.XRecordCreateContext(control,0,clients,1,ranges,1)
    if not context: raise ValueError('X11 input monitor could not start')
    lib.XSync(control,0)
    key=lambda name:lib.XKeysymToKeycode(control,lib.XStringToKeysym(name.encode()))
    modifiers={key(name) for name in ('Alt_L','Alt_R','Control_L','Control_R','Shift_L','Shift_R','Super_L','Super_R')}
    trigger=key(re.sub(r'<[^>]+>','',shortcut))
    masks={'Alt':8,'Control':4,'Ctrl':4,'Primary':4,'Shift':1,'Super':64}
    mask=0
    for tag in re.findall(r'<([^>]+)>',shortcut):mask|=masks.get(tag,0)
    record.XRecordFreeData.argtypes=[C.POINTER(Intercept)]
    record.XRecordDisableContext.argtypes=[C.c_void_p,C.c_ulong]
    callback_type=C.CFUNCTYPE(None,C.c_void_p,C.POINTER(Intercept))
    changed=False
    @callback_type
    def callback(_,pointer):
        nonlocal changed
        item=pointer.contents
        if changed:
            record.XRecordFreeData(pointer)
            return
        if item.category==4:
            path.write_text(json.dumps({'ready':True,'dirty':False,'focus':focus_id()}))
        elif item.category==0 and item.length:
            data=C.string_at(item.data,item.length*4)
            for i in range(0,len(data)-31,32):
                event=data[i:i+32];kind=event[0]&127
                detail=event[1];state=int.from_bytes(event[28:30],sys.byteorder)
                if kind==2 and (detail in modifiers or (detail==trigger and mask and state&mask==mask)):
                    continue
                # Normal focus transitions invalidate the target even if the
                # user later returns. Passive shortcut grabs/ungrabs do not.
                focus_change=kind in (9,10) and event[8]==0
                if kind in (2,4) or focus_change:
                    path.write_text(json.dumps({'ready':True,'dirty':True,'reason':'focus changed' if focus_change else 'input changed'}))
                    changed=True
                    record.XRecordDisableContext(control,context)
                    lib.XSync(control,0)
                    break
        record.XRecordFreeData(pointer)
    record.XRecordEnableContext.argtypes=[C.c_void_p,C.c_ulong,callback_type,C.c_void_p]
    result=record.XRecordEnableContext(data_display,context,callback,None)
    if not result and not changed:
        raise ValueError('X11 input monitor stopped')


if __name__=='__main__':
    try:main()
    except Exception:
        if len(sys.argv)>1:
            Path(sys.argv[1]).write_text(json.dumps({'ready':False,'dirty':True,'reason':'input monitor unavailable'}))
        sys.exit(1)
