Introduction
============

ut2004install.py is a Python script to install Unreal Tournament 2004
(UT2004) on Mac OS X. It is unofficial and barely functional.

Supported installation media
============================

Currently the only supported installation media are the retail PC
version CDs or DVD. Editor's Choice Edition should work but is
untested. Notably the Mac version DVD is not currently supported.

UT2004 3369.2 Mac OS X patch
============================

You must download and mount the 3369.2 patch disk image, normally
distributed as ut2004macpatch33692.dmg.bz2, 208169681 bytes,
MD5 275f63c2535afb5867a791a52b38660f. It is available from the
following sites:

* [MacGameFiles](http://www.macgamefiles.com/detail.php?item=18155)
* [FileFront](http://unrealtournament2004.filefront.com/file/UT2004_33692_patch_for_Mac_OS_X;56261)

Installation
============

After downloading ut2004install.py, open Terminal.app and execute:

    $ cd /Applications
    $ python ~/Downloads/ut2004install.py

With time and luck you will have a complete Unreal Tournament 2004.app
in your Applications folder. If you already had one, its contents will
be verified, and it will be patched and repaired as necessary.

If this is a new installation, you will have to set your CD key with
the following commands:

    $ echo YOUR-CD-KEY > /Applications/U*T*2004.app/System/cdkey

A future version of the script should automate this.

Tweaks and fixes
================

Outdated OpenAL library
-----------------------

UT2004 includes an outdated and broken version of the OpenAL audio
library, which prevents character voices from playing. This can be
fixed by replacing the broken library with a symbolic link to the
updated OpenAL library included with Mac OS X.

    $ cd /Applications/U*T*2004.app/System
    $ mv -i openal.dylib openal.dylib.broken
    $ ln -s /System/Library/Frameworks/OpenAL.framework/OpenAL openal.dylib

A future version of this script should automate this.

OpenGL VARSize option
---------------------

By default UT2004 does not make optimal use of graphics hardware in
newer machines. If you have at least 128 MB of video memory, increasing
the VARSize option from 32 to 64 in the [OpenGLDrv.OpenGLRenderDevice]
section of UT2004.ini can significantly improve graphics performance.
A future version of this script should automate this.

Unused loading screen background
--------------------------------

UT2004 contains an unreferenced loading screen background image. In the
[GUI2K4.UT2K4ServerLoading] section of User.ini, there are two lines
with references to "loadingscreen2." Changing one of these to
"loadingscreen3" will resolve this issue. A future version of this
script should automate this.

Outdated SDL library
--------------------

UT2004 includes an outdated SDL library, which seems to have problems
holding the mouse pointer. Pressing Control+G will re-capture the mouse
when this issue comes up, but it would be preferable to fix this with
an updated SDL library. Unfortunately the latest SDL releases do not
seem to be binary-compatible with UT2004, so some sort of wrapper may
be necessary to permanently resolve this issue.
