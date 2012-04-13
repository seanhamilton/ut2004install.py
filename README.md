ut2004install.py
================

ut2004install.py is a Python script to install Unreal Tournament 2004
(UT2004) on Mac OS X. It is unofficial and barely functional.

Supported installation media
----------------------------

Currently the only supported installation media are the retail PC
version CDs or DVD. Editor's Choice Edition should work but is
untested. Notably the Mac version DVD is not currently supported.

UT2004 3369.2 Mac OS X patch
----------------------------

You must download and mount the 3369.2 patch disk image, normally
distributed as ut2004macpatch33692.dmg.bz2, 208169681 bytes,
MD5 275f63c2535afb5867a791a52b38660f. It is available from the
following sites:

* [MacGameFiles](http://www.macgamefiles.com/detail.php?item=18155)
* [FileFront](http://unrealtournament2004.filefront.com/file/UT2004_33692_patch_for_Mac_OS_X;56261)

Installation
------------

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

Tweaks
------

UT2004 includes an outdated and broken version of the OpenAL audio
library, which prevents character voices from playing. This can be
fixed by replacing the broken library with a symbolic link to the
working OpenAL library included with Mac OS X.

    $ cd /Applications/U*T*2004.app/System
    $ mv -i openal.dylib openal.dylib.broken
    $ ln -s /System/Library/Frameworks/OpenAL.framework/OpenAL openal.dylib
