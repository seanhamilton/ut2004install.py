# ut2004install.py
# Unreal Tournament 2004 (UT2004) installer script for Mac OS X
#
# Copyright (C) 2012
# Sean C. Hamilton <seanhamilton@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.



import glob
import os
import os.path
import struct
import zlib
import time
import sys
import hashlib



# Incomplete MojoPatch reader.
# Sufficient to extract the necessary files from
# the UT2004 3369.2 patch.

class mojopatch ():
	def __init__ (self, f):
		self._f = f

	def _seek (self, offset):
		self._f.seek (offset)

	def _offset (self):
		return self._f.tell ()

	def _skip_bytes (self, length):
		self._f.seek (length, 1)

	def _read_bytes (self, length):
		return self._f.read (length)

	def _read_signature (self):
		MOJOPATCHSIG = 'mojopatch 0.0.7 (icculus@clutteredmind.org)\x0d\x0a\0'
		signature = self._read_bytes (len (MOJOPATCHSIG))
		assert signature == MOJOPATCHSIG
		return signature

	def _read_uint32 (self):
		uint32 = self._read_bytes (4)
		value = struct.unpack ('<I', uint32) [0]
		return value

	def _read_md5 (self):
		md5_bytes = self._read_bytes (16)
		return md5_bytes.encode ('hex')

	def _read_static_string (self):
		length = self._read_uint32 ()
		assert length < 1024
		string = self._read_bytes (length)
		return string

	def _read_asciz_string (self):
		string = ''
		while 1:
			char = self._read_bytes (1)
			if '\0' == char:
				break
			string += char
		return string

	def _read_header (self):
		signature   = self._read_signature ()
		product     = self._read_static_string ()
		identifier  = self._read_static_string ()
		version     = self._read_static_string ()
		newversion  = self._read_static_string ()
		readmefname = self._read_static_string ()
		readmedata  = self._read_asciz_string ()
		renamedir   = self._read_static_string ()
		titlebar    = self._read_static_string ()
		startupmsg  = self._read_static_string ()

	def _read_operation_delete (self):
		fname       = self._read_static_string ()
		return ('DELETE', fname)

	def _read_operation_deletedir (self):
		fname       = self._read_static_string ()
		return ('DELETEDIR', fname)

	def _read_operation_add (self):
		fname       = self._read_static_string ()
		length      = self._read_uint32 ()
		md5         = self._read_md5 ()
		mode        = self._read_uint32 ()
		offset      = self._offset ()
		self._skip_bytes (length)
		return ('ADD', fname, length, md5, mode, offset)

	def _read_operation_adddir (self):
		fname       = self._read_static_string ()
		mode        = self._read_uint32 ()
		return ('ADDDIR', fname, mode)

	def _read_operation_patch (self):
		fname       = self._read_static_string ()
		md5_1       = self._read_md5 ()
		md5_2       = self._read_md5 ()
		fsize       = self._read_uint32 ()
		deltasize   = self._read_uint32 ()
		mode        = self._read_uint32 ()
		offset      = _offset ()
		return ('PATCH', fname, md5_1, md5_2, fsize, deltasize, mode, offset)

	def _read_operation_replace (self):
		fname       = self._read_static_string ()
		length      = self._read_uint32 ()
		md5         = self._read_md5 ()
		mode        = self._read_uint32 ()
		offset      = self._offset ()
		self._skip_bytes (length)
		return ('REPLACE', fname, length, md5, mode, offset)

	def _read_operation_done (self):
		return ('DONE',)

	def _read_operation (self):
		op = self._read_bytes (1)
		if not op: raise EOFError ()
		op = ord (op)

		if   0 == op:   return self._read_operation_delete ()
		elif 1 == op:   return self._read_operation_deletedir ()
		elif 2 == op:   return self._read_operation_add ()
		elif 3 == op:   return self._read_operation_adddir ()
		elif 4 == op:   return self._read_operation_patch ()
		elif 5 == op:   return self._read_operation_replace ()
		elif 6 == op:   return self._read_operation_done ()
		else:           assert False

	def _operations (self):
		self._seek (0)
		self._read_header ()
		while 1:
			operation = self._read_operation ()
			yield operation
			if ('DONE',) == operation:
				break

	def file (self, fname, size=None, md5=None):
		# Returns a file-like object for reading the named
		# file in the MojoPatch archive. Any operations on
		# the mojopatch object will completely invalidate
		# the reader object.

		class mojopatch_subfile ():
			def __init__ (self, f, size):
				self._f = f
				self._size = size
				self._offset = 0

			def read (self, size):
				sz = min (size, self._size - self._offset)
				data = self._f.read (sz)
				self._offset += len (data)
				return data

			def close ():
				pass

		for operation in self._operations ():
			if (operation[0] in ('ADD', 'REPLACE')
					and fname == operation[1]
					and (size is None or size == operation[2])
					and (md5 is None or md5 == operation[3])):
				self._f.seek (operation[5])
				return mojopatch_subfile (self._f, operation[2])

		else:
			return None



class uz2file ():
	def __init__ (self, f):
		self._f = f

	def __enter__ (self):
		self._f.__enter__ ()
		return self

	def __exit__ (self, type, value, traceback):
		self._f.__exit__ (type, value, traceback)

	def read (self, size):
		header = self._f.read (8)

		if not header:
			return None

		(clength, ulength) = struct.unpack ('<II', header)

		assert ulength <= size

		# read compressed block
		cdata = self._f.read (clength)
		assert len (cdata) == clength

		# decompress block
		udata = zlib.decompress (cdata, 0, ulength)
		assert len (udata) == ulength

		# return uncompressed block
		return udata



def blocks (f, size=65536):
	while 1:
		block = f.read (size)
		if not block: break
		yield block

def md5_file (f):
	md5 = hashlib.md5 ()
	for block in blocks (f):
		md5.update (block)
	return md5.hexdigest ()

def copy_and_md5 (source, dest):
	size = 0
	md5 = hashlib.md5 ()

	for block in blocks (source):
		dest.write (block)
		md5.update (block)
		size += len (block)

	return (size, md5.hexdigest ())



def filesystem_sources (name, size=None):
	bases = (
		# install CDs
		'/Volumes/*U*T*2*4*',
		# install DVD
		'/Volumes/*U*T*2*4*/CD*',
		# patch and demo
		'/Volumes/*U*T*2*4*/*U*T*2*4*.app',
	)

	return (
		path
		for base in bases
		for path in glob.iglob (os.path.join (base, name))
		if size is None or size == os.path.getsize (path)
	)

def file_sources (name, size=None):
	for src in filesystem_sources (name, size):
		f = open (src)
		try: yield f
		finally: f.close ()

def uz2_file_sources (name):
	for src in file_sources (name + '.uz2'):
		yield uz2file (src)

def mojopatch_sources (name, size=None, md5=None):
	for src in file_sources ('*.mojopatch'):
		mp = mojopatch (src)
		mp_file = mp.file (name, size, md5)
		if mp_file: yield mp_file

def all_sources (name, size=None, md5=None):
	all_sources = (
		uz2_file_sources (name),
		file_sources (name, size),
		mojopatch_sources (name, size, md5))
	return ( s1 for s0 in all_sources for s1 in s0 )



class manifest_file ():
	def __init__ (self, name, source_name=None, size=None, md5=None, executable=False, mtime=None, source_media=None, optional=False):
		self._name = name
		self._source_name = source_name or name
		self._size = size
		self._md5 = md5
		self._executable = executable
		self._mtime = mtime
		self._source_media = source_media
		self._optional = optional

	def __str__ (self):
		return self._name

	def _verify_exists (self, base):
		target = os.path.join (base, self._name)
		return os.path.isfile (target)

	def _verify_size (self, base):
		if self._size is None: return True
		target = os.path.join (base, self._name)
		return self._size == os.path.getsize (target)

	def _verify_md5 (self, base):
		if self._md5 is None: return True
		target = os.path.join (base, self._name)
		md5 = hashlib.md5 ()
		f = open (target)
		try: target_md5 = md5_file (f)
		finally: f.close ()
		return self._md5 == target_md5

	def _verify (self, base):
		return (self._verify_exists (base)
			and self._verify_size (base)
		)#	and self._verify_md5 (base))

	def verify (self, base):
		if not self._verify_exists (base):
			yield (self, False, 'missing')
		elif not self._verify_size (base):
			yield (self, False, 'invalid size')
		elif not self._verify_md5 (base):
			yield (self, False, 'invalid md5')
		else:
			yield (self, True, 'verified')

	def _install_from_source (self, base, src):
		target = os.path.join (base, self._name)

		out = open (target, 'w')
		try: (out_size, out_md5) = copy_and_md5 (src, out)
		finally: out.close ()

		return ((self._size is None or self._size == out_size)
			and (self._md5 is None or self._md5 == out_md5))

	def _all_sources (self):
		return all_sources (self._source_name, self._size, self._md5)

	def _request_media (self):
		sys.stderr.write ('\n')
		sys.stderr.write ('  Insert media:\n')
		sys.stderr.write ('    %s\n' % (self._source_media or '(unknown)'))
		sys.stderr.write ('  containing file:\n')
		sys.stderr.write ('    %s\n' % self._source_name)

		if self._size is not None:
			sys.stderr.write ('    size: %d\n' % self._size)
		if self._md5 is not None:
			sys.stderr.write ('    md5: %s\n' % self._md5)

		sys.stderr.write ('\n')

		if self._optional:
			sys.stderr.write ('  or press Control+C to skip\n')
			sys.stderr.write ('  this optional file\n')
			sys.stderr.write ('\n')

	def install (self, base):
		try:
			target = os.path.join (base, self._name)

			if self._verify (base):
				yield (self, True, 'verified')
				return

			request_media = self._request_media

			while not any (
					self._install_from_source (base, src)
					for src in self._all_sources ()):

				request_media ()
				request_media = lambda: None

				time.sleep (1)

			if self._executable:
				os.chmod (target, 0755)

		except KeyboardInterrupt:
			if self._optional:
				sys.stdout.write ('\n')
				yield (self, True, 'skipped')
				return
			else:
				raise

		yield (self, True, 'installed')

class manifest_directory ():
	def __init__ (self, name):
		self._name = name

	def __str__ (self):
		if self._name: return self._name + '/'
		else: return '(base)'

	def _verify (self, base):
		return os.path.isdir (os.path.join (base, self._name))

	def verify (self, base):
		if self._verify (base):
			yield (self, True, 'verified')
		else:
			yield (self, False, 'missing/invalid')

	def install (self, base):
		if self._verify (base):
			yield (self, True, 'verified')
		else:
			os.mkdir (os.path.join (base, self._name))
			yield (self, True, 'created')

class manifest_symlink ():
	def __init__ (self, name, source):
		self._name = name
		self._source = source

	def __str__ (self):
		return '%s -> %s' % (self._name, self._source)

	def _verify (self, base):
		fullname = os.path.join (base, self._name)
		return (os.path.islink (fullname)
			and self._source == os.readlink (fullname))

	def verify (self, base):
		if self._verify (base):
			yield (self, True, 'verified')
		else:
			yield (self, False, 'missing/invalid')

	def install (self, base):
		if self._verify (base):
			yield (self, True, 'verified')

		else:
			os.symlink (
				self._source,
				os.path.join (base, self._name))
			yield (self, True, 'created')

class manifest ():
	def __init__ (self, name, items):
		self._name = name
		self._items = items

	def __str__ (self):
		return 'MANIFEST: %s' % self._name

	def verify (self, base):
		for item in self._items:
			for subitem, result, message in item.verify (base):
				yield (subitem, result, message)
		yield (self, True, 'verified')

	def install (self, base):
		for item in self._items:
			for subitem, result, message in item.install (base):
				yield (subitem, result, message)
		yield (self, True, 'installed')



media_ut2004_cd1 = 'Unreal Tournament 2004 DVD or CD #1'
media_ut2004_cd2 = 'Unreal Tournament 2004 DVD or CD #2'
media_ut2004_cd3 = 'Unreal Tournament 2004 DVD or CD #3'
media_ut2004_cd4 = 'Unreal Tournament 2004 DVD or CD #4'
media_ut2004_cd5 = 'Unreal Tournament 2004 DVD or CD #5'
media_ut2004_cd6 = 'Unreal Tournament 2004 DVD or CD #6 (Play Disc)'
media_ut2004_3369_2_patch = 'Unreal Tournament 2004 3369.2 Mac OS X patch'
media_ut2004_demo = 'Unreal Tournament 2004 Mac OS X demo'



# {{{ manifests

ut2004_3186 = manifest (
	'UT2004 3186 base installation',
	items=(

		# [SetupGroup]
		#manifest_file ('System/Manifest.det', size=2562, md5='67ab2de5fe8ffd57a2109b51b8422a08', mtime=1078360646, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.est', size=2619, md5='83dfdaefd5574bee3c4d363ad89ce90c', mtime=1078360684, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.frt', size=2467, md5='a2e960006efc3f87a1f2fd88841dbca4', mtime=1078360714, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.ini', size=277672, md5='c81e9352cb6ad6052cbe061d55f3f598', mtime=1078342971, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.int', size=2415, md5='fa0aac9ed1ae06d9323bb539b56cce7d', mtime=1077196289, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.itt', size=2545, md5='e5c0261dce97d998891c4b3218226cf0', mtime=1078360699, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.kot', size=3474, md5='d737e28c33078ddb8db104538eaa725d', mtime=1078270943, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.smt', size=3144, md5='92b0575de99823d7b1f31fa2e09b579c', mtime=1059564647, source_media=media_ut2004_cd1),
		#manifest_file ('System/Manifest.tmt', size=3146, md5='e66f9a6ce40ba15e0657ff1cc64af021', mtime=1059564647, source_media=media_ut2004_cd1),
		#manifest_file ('System/license.det', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1078008822, source_media=media_ut2004_cd1),
		#manifest_file ('System/license.est', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1077983486, source_media=media_ut2004_cd1),
		#manifest_file ('System/license.frt', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1077983486, source_media=media_ut2004_cd1),
		#manifest_file ('System/License.int', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1075532276, source_media=media_ut2004_cd1),
		#manifest_file ('System/license.itt', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1078008822, source_media=media_ut2004_cd1),
		#manifest_file ('System/License.kot', size=12702, md5='11c56e62bb03ff83feb42b533da46d74', mtime=1078270943, source_media=media_ut2004_cd1),
		#manifest_file ('System/License.smt', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1075532276, source_media=media_ut2004_cd1),
		#manifest_file ('System/License.tmt', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1075532276, source_media=media_ut2004_cd1),
		#manifest_file ('AutoRun.inf', size=49, md5='3d0afedbf1c8a663c1768cc609a9079f', mtime=1053699589, source_media=media_ut2004_cd1),
		#manifest_file ('AutoRun.inf', size=49, md5='98f2e7e1ef7f8541321c2dd03103a897', mtime=1053695990, source_media=media_ut2004_cd2),
		#manifest_file ('AutoRun.inf', size=49, md5='98f2e7e1ef7f8541321c2dd03103a897', mtime=1053699589, source_media=media_ut2004_cd3),
		#manifest_file ('AutoRun.inf', size=49, md5='98f2e7e1ef7f8541321c2dd03103a897', mtime=1053699589, source_media=media_ut2004_cd4),
		#manifest_file ('AutoRun.inf', size=49, md5='98f2e7e1ef7f8541321c2dd03103a897', mtime=1053699589, source_media=media_ut2004_cd5),
		#manifest_file ('AutoRun.inf', size=49, md5='98f2e7e1ef7f8541321c2dd03103a897', mtime=1053699589, source_media=media_ut2004_cd6),
		#manifest_file ('AutoRun.exe', size=23040, md5='1ef6e5f5893bdf3def76801fd92f93c9', mtime=1077121224, source_media=media_ut2004_cd2),
		#manifest_file ('AutoRun.exe', size=23040, md5='1ef6e5f5893bdf3def76801fd92f93c9', mtime=1077121222, source_media=media_ut2004_cd3),
		#manifest_file ('AutoRun.exe', size=23040, md5='1ef6e5f5893bdf3def76801fd92f93c9', mtime=1077121222, source_media=media_ut2004_cd4),
		#manifest_file ('AutoRun.exe', size=23040, md5='1ef6e5f5893bdf3def76801fd92f93c9', mtime=1077121222, source_media=media_ut2004_cd5),
		#manifest_file ('AutoRun.exe', size=22528, md5='5ec7cb3e10feffdb048282803a3bacf9', mtime=1077191247, source_media=media_ut2004_cd6),
		#manifest_file ('Help/Unreal.ico', size=24070, md5='fa30c7ab4ccb77f7da789689a55b2cb1', mtime=1075463927, source_media=media_ut2004_cd2),
		#manifest_file ('Help/Unreal.ico', size=24070, md5='fa30c7ab4ccb77f7da789689a55b2cb1', mtime=1075463927, source_media=media_ut2004_cd3),
		#manifest_file ('Help/Unreal.ico', size=24070, md5='fa30c7ab4ccb77f7da789689a55b2cb1', mtime=1075463927, source_media=media_ut2004_cd4),
		#manifest_file ('Help/Unreal.ico', size=24070, md5='fa30c7ab4ccb77f7da789689a55b2cb1', mtime=1075463927, source_media=media_ut2004_cd5),
		#manifest_file ('Help/Unreal.ico', size=24070, md5='fa30c7ab4ccb77f7da789689a55b2cb1', mtime=1075463927, source_media=media_ut2004_cd6),
		#manifest_file ('Setup.exe', size=32768, md5='383bba960053eebf21d0300ee71fedc4', mtime=1065033938, source_media=media_ut2004_cd1),

		# [HelpGroup]
		#manifest_file ('Help/InstallerLogo.bmp', size=29284, md5='e9e2937edae312d1739e309eee49ab65', mtime=1054120854, source_media=media_ut2004_cd1),
		#manifest_file ('Help/Unreal.ico', size=24070, md5='fa30c7ab4ccb77f7da789689a55b2cb1', mtime=1075463927, source_media=media_ut2004_cd1),
		#manifest_file ('Help/UnrealEd.ico', size=24070, md5='7bbe3ebe2f370baf22703ec343e7b017', mtime=1075463927, source_media=media_ut2004_cd1),
		#manifest_file ('Help/UT2004Logo.bmp', size=221240, md5='5ae96201944072524b84d33e8196e67c', mtime=1077191221, source_media=media_ut2004_cd1),

		# Speech API is not installed
		#manifest_file ('Help/SAPI-EULA.txt', size=1715, md5='2b9685795ef8f9956aa86616a5ab8c3c', mtime=1063025732, source_media=media_ut2004_cd1),

		manifest_directory ('Help'),
		manifest_file ('Help/ReadMe.int.txt', size=22631, md5='6bf9496dc974a2c93ce14080cf7aeb31', mtime=1077681711, source_media=media_ut2004_cd1),
		manifest_file ('Help/ReadMe.det.txt', size=20877, md5='0c162f8ea9106979ad6d10e0439b04d6', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('Help/ReadMe.frt.txt', size=25316, md5='137ea3c595fc284009480882bda1828e', mtime=1078148292, source_media=media_ut2004_cd1),
		manifest_file ('Help/ReadMe.itt.txt', size=22576, md5='339f4d09b1377fe8175476a5d18f7d61', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('Help/ReadMe.est.txt', size=19399, md5='011f61fa10093fcaf26ff2a03c085298', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('Help/ReadMe.kot.txt', size=28047, md5='5a16f19537b6db0c6a2e8659e2e410a5', mtime=1053699351, source_media=media_ut2004_cd1),

		manifest_directory ('Manual'),
		# listed in manifest but not on CD
		# int
		#manifest_file ('Manual/Manual.pdf', size=11522517, source_media=media_ut2004_cd1),
		# det
		#manifest_file ('Manual/Manual.pdf', size=3293821, source_media=media_ut2004_cd1),
		# frt
		#manifest_file ('Manual/Manual.pdf', size=2156142, source_media=media_ut2004_cd1),
		# itt
		#manifest_file ('Manual/Manual.pdf', size=4946290, source_media=media_ut2004_cd1),
		# est
		#manifest_file ('Manual/Manual.pdf', size=4946290, source_media=media_ut2004_cd1),
		# kot
		#manifest_file ('Manual/Manual.pdf', size=2319230, source_media=media_ut2004_cd1),

		# not in manifest
		#manifest_file ('Manual/Manual.pdf', size=2319230, md5='4bebf5f2b1aaec0ea832c9628b45488b', mtime=1076928342, source_media=media_ut2004_cd1),

		#manifest_file ('Manual/AdbeRdr60_enu_full.exe', size=16251072, md5='bfb738698619c4e1e1a8c0e67dec143d', mtime=1067277336, source_media=media_ut2004_cd1),

		# [EngineSystemGroup]
		manifest_directory ('System'),
		#manifest_file ('System/BugReport.exe', size=51832, md5='312933c8ba5690878b993b4810da5df4', mtime=1078272405, source_media=media_ut2004_cd1),
		#manifest_file ('System/Core.u', size=73774, md5='14699ec05c2aa75dbf11a71e2657eee9', mtime=1078271958, source_media=media_ut2004_cd1),
		#manifest_file ('System/Core.dll', size=756344, md5='147589199db3b25d79f57d32371d5556', mtime=1078272405, source_media=media_ut2004_cd1),
		#manifest_file ('System/dbghelp.dll', size=489984, md5='e458d88c71990f545ef941cd16080bad', mtime=1071236043, source_media=media_ut2004_cd1),
		#manifest_file ('System/D3DDrv.dll', size=502392, md5='7bde372903a73e7db326e3f8ec6fede8', mtime=1078272405, source_media=media_ut2004_cd1),
		#manifest_file ('System/OpenGLDrv.dll', size=223864, md5='8c46b4e6966f42b57af7af4a047c0372', mtime=1078272406, source_media=media_ut2004_cd1),
		#manifest_file ('System/PixoDrv.dll', size=146040, md5='c6a304ad7333a949c314b4d024961f62', mtime=1078272408, source_media=media_ut2004_cd1),
		#manifest_file ('System/Engine.dll', size=4610680, md5='fa18d56c10b9e7ddf78e19b5679be08b', mtime=1078272406, source_media=media_ut2004_cd1),
		manifest_file ('System/Engine.dat', size=3448832, md5='34642708ced4bb398d706438f7dde356', mtime=1053699591, source_media=media_ut2004_cd1),
		#manifest_file ('System/Engine.u', size=2666248, md5='739b1ae6a2357d11242dddae14c43fc0', mtime=1078272001, source_media=media_ut2004_cd1),
		#manifest_file ('System/Editor.u', size=458259, md5='6a496dd1bb22e2b45d03b6dcbbd1b4c3', mtime=1078272005, source_media=media_ut2004_cd1),
		#manifest_file ('System/Fire.dll', size=96888, md5='ecedace93b28a04610743e160f5f1a23', mtime=1078272406, source_media=media_ut2004_cd1),
		#manifest_file ('System/Fire.u', size=16281, md5='e42f476fa991f2a57c3f46a7d9baee73', mtime=1078272001, source_media=media_ut2004_cd1),
		#manifest_file ('System/IpDrv.dll', size=227960, md5='3b6a1cd75ac5ece6d47500a30129a4d8', mtime=1078272406, source_media=media_ut2004_cd1),
		#manifest_file ('System/IpDrv.u', size=77399, md5='b1eb2b2f193ec1e82d057cf155f14326', mtime=1078272011, source_media=media_ut2004_cd1),
		#manifest_file ('System/UWeb.dll', size=39032, md5='0b87f71d92a38bc32ae7dc510e067bfd', mtime=1078272407, source_media=media_ut2004_cd1),
		#manifest_file ('System/UWeb.u', size=34732, md5='2aa7d7311da75bc79b079242f14e79b5', mtime=1078272011, source_media=media_ut2004_cd1),
		#manifest_file ('System/MSVCR71.dll', size=348160, md5='86f1895ae8c5e8b17d99ece768a70732', mtime=1065033938, source_media=media_ut2004_cd1),
		#manifest_file ('System/DefOpenAL32.dll', size=159744, md5='ef595453582229f0e7b30a6ede1bfd64', mtime=1065033936, source_media=media_ut2004_cd1),
		#manifest_file ('System/RunServer.bat', size=113, md5='12b05d077e4cb8c633516409e6bc6ad9', mtime=1053699594, source_media=media_ut2004_cd1),
		#manifest_file ('System/Setup.exe', size=449144, md5='bab35768baf58716f5530ed676053b5b', mtime=1078272406, source_media=media_ut2004_cd1),
		#manifest_file ('System/UCC.exe', size=113272, md5='08cd3b73a403f8c7d3370c4cc42aa403', mtime=1078272406, source_media=media_ut2004_cd1),
		#manifest_file ('System/Window.dll', size=416376, md5='f47f954888537078947fe39402781073', mtime=1078272407, source_media=media_ut2004_cd1),
		#manifest_file ('System/WinDrv.dll', size=834168, md5='f1b7f8d31d746d947cef1971fa7dfa25', mtime=1078272408, source_media=media_ut2004_cd1),
		#manifest_file ('System/ogg.dll', size=13944, md5='1a3030dda1e45fee34a0952c267498af', mtime=1078272406, source_media=media_ut2004_cd1),
		#manifest_file ('System/vorbis.dll', size=137848, md5='93a8c0e788f730a0287d67f1c8832803', mtime=1078272407, source_media=media_ut2004_cd1),
		#manifest_file ('System/vorbisfile.dll', size=20600, md5='af0b9bd3bab7000b74cdde1d1e5f5d7b', mtime=1078272407, source_media=media_ut2004_cd1),
		#manifest_file ('System/pixomatic.dll', size=226873, md5='f75cfabbfe4acb2f4a45c6d715770fbf', mtime=1065033938, source_media=media_ut2004_cd1),
		#manifest_file ('System/IFC23.dll', size=237568, md5='a5a2dfdb4ddf0b9ac163cbaf77b841a9', mtime=1065714075, source_media=media_ut2004_cd1),
		#manifest_file ('System/ALAudio.dll', size=252536, md5='3940f14bed8cb9ff98cf846a069a6ac4', mtime=1078272405, source_media=media_ut2004_cd1),
		#manifest_file ('System/XInterface.dll', size=502392, md5='27a23a1142224438cb42b8d36624d4b6', mtime=1078272408, source_media=media_ut2004_cd1),
		#manifest_file ('System/XGame.dll', size=64120, md5='eca04d27595a8240a939e81ac3e717f2', mtime=1078272408, source_media=media_ut2004_cd1),
		#manifest_file ('System/Onslaught.dll', size=170616, md5='4088870620bcdfc871b59a6620ee102f', mtime=1078272408, source_media=media_ut2004_cd1),
		#manifest_file ('System/UnrealEd.u', size=13200, md5='b11b735d97acb080a80659f5b023da06', mtime=1078272008, source_media=media_ut2004_cd1),
		#manifest_file ('System/UnrealServerProxy.dll', size=45056, md5='7453f321b6bc114a15df8f6ba230e33c', mtime=1076974678, source_media=media_ut2004_cd1),
		#manifest_file ('System/udebugger.exe', size=2157176, md5='1309dc355ed3292ce5e2087c117ad749', mtime=1078329961, source_media=media_ut2004_cd1),
		#manifest_file ('System/dinterface.dll', size=1378816, md5='eecaa9ad989577cf529c3a0205f99ef6', mtime=1065033936, source_media=media_ut2004_cd1),
		#manifest_file ('System/GUIDesigner.dll', size=29304, md5='023fea11cc7aa793bf0f6efaee1918f8', mtime=1078272408, source_media=media_ut2004_cd1),
		#manifest_file ('System/UTV2004.dll', size=154232, md5='e447ffc777eff5c420570f9a3d3bdcdc', mtime=1078272408, source_media=media_ut2004_cd1),
		#manifest_file ('System/UTV2004c.u', size=73055, md5='0a6ffb3d8716f096e2b0cab5269a45d0', mtime=1078272284, source_media=media_ut2004_cd1),
		#manifest_file ('System/UTV2004s.u', size=6987, md5='d0f88c90cb7e188976cccf3fdda6027d', mtime=1078272285, source_media=media_ut2004_cd1),

		#manifest_file ('Benchmark/CSVs/DO_NOT_DELETE.ME', md5='d41d8cd98f00b204e9800998ecf8427e', mtime=1053699285, source_media=media_ut2004_cd1),
		#manifest_file ('Benchmark/Logs/DO_NOT_DELETE.ME', md5='d41d8cd98f00b204e9800998ecf8427e', mtime=1053699285, source_media=media_ut2004_cd1),
		#manifest_file ('Benchmark/Results/DO_NOT_DELETE.ME', md5='d41d8cd98f00b204e9800998ecf8427e', mtime=1053699285, source_media=media_ut2004_cd1),
		#manifest_file ('Benchmark/Stuff/timedemo.txt', md5='d41d8cd98f00b204e9800998ecf8427e', mtime=1076264405, source_media=media_ut2004_cd1),

		# [GameSystemGroup]

		#manifest_file ('System/ut2004.exe', size=2062968, md5='39e0f8dc0ea8ad973ff05c5bc4693f24', mtime=1078329968, source_media=media_ut2004_cd1),
		manifest_file ('System/xplayersL1.upl', size=40585, md5='18e217ed49e980c98c0c44444cc0d228', mtime=1074964018, source_media=media_ut2004_cd1),
		manifest_file ('System/xplayersL2.upl', size=12588, md5='30e5f5645bdd7c67bb7edea2bb22d3dd', mtime=1074964018, source_media=media_ut2004_cd1),
		manifest_file ('System/DefUser.ini', size=9516, md5='409d30c90187364e1433151406b8826d', mtime=1078360938, source_media=media_ut2004_cd1),

		# "master" is DefUser.ini, deleted by 3369.2 patch anyway
		#manifest_file ('System/User.ini', size=9463, md5='409d30c90187364e1433151406b8826d', mtime=1078360960, source_media=media_ut2004_cd1),

		manifest_file ('System/Default.ini', size=19022, md5='fdc6edcd02e5596d57b6ca16074020b0', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealEdTips.ini', size=612, md5='e3be04041b50e92806c095d9b782880d', mtime=1053699596, source_media=media_ut2004_cd1),
		manifest_file ('System/UDNHelpTopics.ini', size=550, md5='b0e90c74e119098d0120b38309583c2e', mtime=1053699596, source_media=media_ut2004_cd1),
		manifest_file ('System/DefUnrealEd.ini', size=2969, md5='f92bc8540bdb700911da680a3317c29d', mtime=1053699590, source_media=media_ut2004_cd1),
		# master is Default.ini, files are identical
		manifest_file ('System/UT2004.ini', size=19022, md5='fdc6edcd02e5596d57b6ca16074020b0', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/ServerFilters.ini', size=306, md5='bda9f82d56fb4ad4787502ebe0687a92', mtime=1077968057, source_media=media_ut2004_cd1),
		#manifest_file ('System/CacheRecords.ucl', size=165084, md5='70cb2557cf98387a68ace4a4c8592614', mtime=1078272401, source_media=media_ut2004_cd1),
		manifest_file ('System/Build.ini', size=55, md5='6135e316bdaa956d8c360f42bdfa155e', mtime=1078272404, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealTournament2004Web.url', size=148, md5='06c5f270ae78dc12c53c87582113fc41', mtime=1053699597, source_media=media_ut2004_cd1),
		#manifest_file ('System/BonusPack.u', size=161173, md5='093253f936d9e6a0c50dea60c64f5209', mtime=1078272159, source_media=media_ut2004_cd1),
		#manifest_file ('System/Core.u', size=73774, md5='14699ec05c2aa75dbf11a71e2657eee9', mtime=1078271958, source_media=media_ut2004_cd1),
		#manifest_file ('System/Editor.u', size=458259, md5='6a496dd1bb22e2b45d03b6dcbbd1b4c3', mtime=1078272005, source_media=media_ut2004_cd1),
		#manifest_file ('System/Engine.u', size=2666248, md5='739b1ae6a2357d11242dddae14c43fc0', mtime=1078272001, source_media=media_ut2004_cd1),
		#manifest_file ('System/Fire.u', size=16281, md5='e42f476fa991f2a57c3f46a7d9baee73', mtime=1078272001, source_media=media_ut2004_cd1),
		#manifest_file ('System/GamePlay.u', size=213306, md5='8e208995dc08060c04fa72aa02830b55', mtime=1078272013, source_media=media_ut2004_cd1),
		#manifest_file ('System/GUI2K4.u', size=2343952, md5='8324ef032aa32f37df682a5dca0f7674', mtime=1078272268, source_media=media_ut2004_cd1),
		#manifest_file ('System/IpDrv.u', size=77399, md5='b1eb2b2f193ec1e82d057cf155f14326', mtime=1078272011, source_media=media_ut2004_cd1),
		#manifest_file ('System/Onslaught.u', size=987764, md5='af5c102b45878afdb8b17e549a61e438', mtime=1078272234, source_media=media_ut2004_cd1),
		#manifest_file ('System/OnslaughtFull.u', size=151009, md5='f998cdb6b59609b4e9e913a7b5ccc625', mtime=1078272277, source_media=media_ut2004_cd1),
		#manifest_file ('System/SkaarjPack.u', size=299091, md5='ac3b3c7f60134f0ee8c5d3b35b4bd813', mtime=1078272168, source_media=media_ut2004_cd1),
		manifest_file ('System/SkaarjPack_rc.u', size=7867806, md5='efe07099c1454bbc3603bc135b9aaf83', mtime=1078272164, source_media=media_ut2004_cd1),
		manifest_file ('System/StreamLineFX.u', size=14478, md5='856d5b0876d75b6b9c676b195b5857bb', mtime=1078272282, source_media=media_ut2004_cd1),
		#manifest_file ('System/UnrealEd.u', size=13200, md5='b11b735d97acb080a80659f5b023da06', mtime=1078272008, source_media=media_ut2004_cd1),
		#manifest_file ('System/UnrealGame.u', size=1193857, md5='079eb1351b65f924965e2a1922578215', mtime=1078272035, source_media=media_ut2004_cd1),
		#manifest_file ('System/UT2k4Assault.u', size=1024077, md5='859922228f4241fde2a00d722d11ab83', mtime=1078272182, source_media=media_ut2004_cd1),
		#manifest_file ('System/UT2k4AssaultFull.u', size=231979, md5='6e2b46a6a9e296ce97e95d4e95e2b4fe', mtime=1078272273, source_media=media_ut2004_cd1),
		#manifest_file ('System/UTClassic.u', size=69504, md5='62776ec248eafeca71a79f5232d4fc22', mtime=1078272170, source_media=media_ut2004_cd1),
		#manifest_file ('System/UWeb.u', size=34732, md5='2aa7d7311da75bc79b079242f14e79b5', mtime=1078272011, source_media=media_ut2004_cd1),
		#manifest_file ('System/Vehicles.u', size=88104, md5='1eafb04f60bf588a517ba833ee1d5a8c', mtime=1078272154, source_media=media_ut2004_cd1),
		#manifest_file ('System/XAdmin.u', size=82759, md5='9221701bda59993b993b40fd1117a076', mtime=1078272151, source_media=media_ut2004_cd1),
		manifest_file ('System/XEffects.u', size=4569396, md5='8c7eba552a52f232a10c6e74850f0397', mtime=1078272069, source_media=media_ut2004_cd1),
		#manifest_file ('System/XGame.u', size=762451, md5='5e886a651bcbb8f06c0c10c3e9c3d350', mtime=1078272096, source_media=media_ut2004_cd1),
		manifest_file ('System/XGame_rc.u', size=2478934, md5='cb611de8c984583479992cbdd9d88595', mtime=1078272039, source_media=media_ut2004_cd1),
		#manifest_file ('System/XInterface.u', size=1992363, md5='1dde84ba3970202ef15ce9c200e489c9', mtime=1078272150, source_media=media_ut2004_cd1),
		#manifest_file ('System/XPickups.u', size=17723, md5='ec0ff02279e115c0b9030fe324438034', mtime=1078272072, source_media=media_ut2004_cd1),
		manifest_file ('System/XPickups_rc.u', size=107568, md5='190216a523ccc7a9f03dff263bbd75ee', mtime=1078272071, source_media=media_ut2004_cd1),
		#manifest_file ('System/XWeapons.u', size=657856, md5='fe7d166f4fbf2aeab59ceb277f19bd6e', mtime=1078272105, source_media=media_ut2004_cd1),
		manifest_file ('System/XWeapons_rc.u', size=539381, md5='c0bd6d365789738ff453acf2112761f2', mtime=1078272071, source_media=media_ut2004_cd1),
		#manifest_file ('System/XWebAdmin.u', size=277453, md5='751e2570716e988896e5299997cd6c55', mtime=1078272153, source_media=media_ut2004_cd1),
		#manifest_file ('System/XVoting.u', size=396104, md5='92e64bf6627c9f8982e8f889ae65c0ba', mtime=1078272281, source_media=media_ut2004_cd1),

		manifest_directory ('KarmaData'),
		manifest_file ('KarmaData/Alien.ka', size=56751, md5='d9ab3f5784cfe156c575f55797fd8dee', mtime=1053699352, source_media=media_ut2004_cd1),
		manifest_file ('KarmaData/Bot.ka', size=50011, md5='e0f575f3d19bfaa0d88bd5891fb23961', mtime=1053699352, source_media=media_ut2004_cd1),
		manifest_file ('KarmaData/Human.ka', size=118654, md5='1953114b26bc884c31321c791e22cbd8', mtime=1053699353, source_media=media_ut2004_cd1),
		manifest_file ('KarmaData/intro.ka', size=40442, md5='5e71b15ebf748bf12070358fdfbe69ac', mtime=1053699353, source_media=media_ut2004_cd1),
		manifest_file ('KarmaData/jugg.ka', size=51411, md5='2fb9b9d84a116cf2cbd470727021bac8', mtime=1053699353, source_media=media_ut2004_cd1),
		manifest_file ('KarmaData/Skaarj.ka', size=31834, md5='2204714cd3a3e4944f8f9969c73c63cc', mtime=1074251345, source_media=media_ut2004_cd1),

		# force feedback is probably Windows-only
		#manifest_file ('ForceFeedback/gamepad.ifr', size=241417, md5='e80db356b1d09fcad152b278998620cd', mtime=1065832228, source_media=media_ut2004_cd1),
		#manifest_file ('ForceFeedback/ifeel.ifr', size=242379, md5='c6c22c2c02cfcf3809c640d5961094c6', mtime=1065787817, source_media=media_ut2004_cd1),
		#manifest_file ('ForceFeedback/joystick.ifr', size=243826, md5='738ed7f7dda4243445f901a6599c2486', mtime=1065832228, source_media=media_ut2004_cd1),
		#manifest_file ('ForceFeedback/other.ifr', size=229543, md5='71ee0b78f6ae75a6b12dd10c96c71043', mtime=1065787817, source_media=media_ut2004_cd1),

		#manifest_file ('System/Packages.md5', size=5319, md5='5a4918094b305a2e6e6f71e7e0b0f24d', mtime=1078272357, source_media=media_ut2004_cd1),

		manifest_directory ('Web'),
		manifest_directory ('Web/images'),
		manifest_file ('Web/images/h_fill.gif', size=79, md5='ec298510e66bf967c73587c83c920712', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/h_logo.jpg', size=5943, md5='11682ca5cb2811c9072130fcd39c6a2b', mtime=1077019426, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/h_navseach.gif', size=120, md5='b807d4702f181bbe8c6cd2e9e3712add', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/h_rgfx.jpg', size=7456, md5='aa6dcff3873cc7e053e9ba56fc2fd314', mtime=1077019426, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/h_space.gif', size=318, md5='408c31f225ead0d8e4b23384f044ce00', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_botleft.gif', size=871, md5='8674493c004c7776bff4da6049a03de7', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_botmid.gif', size=825, md5='23be9e8012c4a8d2447a5fdec15c8cd2', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_botright.gif', size=871, md5='58bbbb908d42c08ad4af333d2985d050', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_left.gif', size=100, md5='902f7a67d8d3fd901c82b64ea9df6651', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_mid.gif', size=149, md5='30a050506d1b9b369271952b22f98cf6', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_right.gif', size=100, md5='55251bfc02ae5c16474d9ff4cc9563f4', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_topleft.gif', size=872, md5='f963311e8f3792de3b51b6c6d071bf89', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_topmid.gif', size=825, md5='f93614e4296eff689bcd2f42725bb67b', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/q_topright.gif', size=872, md5='1810d52b54665abe7421bcaa96e33724', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/t.gif', size=814, md5='70821775c8122a0cb210a89aeb54310b', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_directory ('Web/images/ClassicUT'),
		manifest_file ('Web/images/ClassicUT/1-1.gif', size=106, md5='e8df68ec9a8c1bc038a62a97e4e97721', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/1-2.gif', size=124, md5='599ea8d3073704af7aadd3a1940c84dd', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/1.gif', size=43, md5='fc94fb0c3ed8a8f909dbc7630a0987ff', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/2-1.gif', size=213, md5='98f83353a1637d8608a8e36d476b7f9a', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/2-2.gif', size=700, md5='9dafdc79652a9bbb47f09186c3aa60f2', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/3-1.gif', size=112, md5='91c8047b2fd7c6689a52d70aad609bd3', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/3-2.gif', size=132, md5='571e430ac07081b510964c8649319a24', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/4-1.gif', size=382, md5='59e5969d0dda3b438659ad7e30de58d7', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/4-2.gif', size=148, md5='7ceb3cbcb9f8b2050a6a0b579074de42', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/5-1.gif', size=218, md5='8722ea33e17380c7ef121706d3fec87a', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/5-2.gif', size=218, md5='19bf8cd580fe8cd666951e870a74f247', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/6-1.gif', size=105, md5='7cbfe648712ea8082d99c15b757811cb', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/6-2.gif', size=107, md5='b9e83c15090e39ae25e928e2101e8103', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/7-1.gif', size=189, md5='3f41b14c48ed2a1734122538bcd51cfb', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/7-2.gif', size=210, md5='ac12d19fec4dcedc0a1620cdcdbf9084', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/7-3.gif', size=256, md5='bef43c806fa215c5e8e16e7e8aa3b8df', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/image.gif', size=5916, md5='ac1f7b5caddb46d38b38fe2b70e85873', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/logo.gif', size=2795, md5='e477746a55e9cb499c1e8b419ba72efc', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/m1-1.gif', size=253, md5='6f56464b377fafb6002961549868749a', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/m1-2.gif', size=257, md5='01f987551e47836d2d5968f850a06ba4', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/m3-1.gif', size=226, md5='a311389f3e1281c1433870f1ea319f09', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/m3-2.gif', size=223, md5='76156f2baf36cc10ddee4b40323056dd', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/ClassicUT/right.gif', size=1016, md5='d3519f378ef4a97500d155becaef66f6', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_directory ('Web/images/UnrealAdminPage'),
		manifest_file ('Web/images/UnrealAdminPage/downloads.gif', size=436, md5='f9ae0bfd24a676a5065d1a2330866087', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/UnrealAdminPage/faqs.gif', size=348, md5='9e7a87575ad3c531ec0e909b467ee175', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/UnrealAdminPage/forums.gif', size=366, md5='3fa8a855a93ce42a0b458cc1831960b1', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/UnrealAdminPage/home.gif', size=332, md5='51978a7d98fd345637cef7d78927a639', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/UnrealAdminPage/how-tos.gif', size=379, md5='6721ce1cc496061dda7ba64c3a8fa23f', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/images/UnrealAdminPage/logo.gif', size=7557, md5='83640d8c4d0b4769d5e78a880f67b2ca', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_directory ('Web/ServerAdmin'),
		manifest_file ('Web/ServerAdmin/adminsframe.htm', size=568, md5='521d9664ed1db712dc501cedd99660a5', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/admins_account.htm', size=1356, md5='71556863ff109d00c06fa408dbb9fc38', mtime=1053699896, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/admins_home.htm', size=786, md5='fb834cf2d27830723188ca840345fe7e', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/admins_menu.htm', size=508, md5='276add9c33af72974aae414f7a557d38', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/admins_priv_table.inc', size=47, md5='a4840eaac461ee93699c625b7b7bc769', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/cell_center.inc', size=37, md5='068dd35670856cc3a445652d05a1ff52', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/cell_center_nowrap.inc', size=44, md5='4cd9e04f9bdb3655f507d80d7a4544fc', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/cell_colspan.inc', size=58, md5='49920e15760b4521fe89acf1b767adec', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/cell_left.inc', size=35, md5='e05681b77bb09b34a2510e966c29600f', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/cell_left_nowrap.inc', size=42, md5='801d34a5c0e8d4254ee526f1a494556d', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/cell_right.inc', size=36, md5='6182d329cb5932873c2ff170df1c05a7', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/cell_right_nowrap.inc', size=43, md5='ce24eacde7ee8a713ded987f9b173a56', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/checkbox.inc', size=101, md5='7e56d2e02cc042c659c9aef15ad16aa7', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/currentframe.htm', size=567, md5='d0abd6533f789adccbf16d18fda38214', mtime=1053699897, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/current_bots.htm', size=1615, md5='98c5e3243e11e20c33e46f409f9f2011', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_bots_row.inc', size=210, md5='6592558387be6702ef91129e6c0408d5', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_bots_row_sel.inc', size=272, md5='0383615b1540cbc242e8dcd4b0c09547', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_bots_species.inc', size=104, md5='590abadb7dcfb3cf35b1e0ed02b7e1f7', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_console.htm', size=570, md5='c8032f4610b659ef59ab4152eae8a87a', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_console_log.htm', size=106, md5='fe1a450a95083a9abd5b64d6d05070a7', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_console_send.htm', size=584, md5='f0b51616b6316df4e2ef6f09bf8a95a2', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_game.htm', size=491, md5='81844163abbf79c7afde2cd73dcc5ea8', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_game_stat_table.inc', size=631, md5='3a4897fa284a46292f7249d8c94bbbfc', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_game_stat_table_row.inc', size=287, md5='7bab89d8ef00055423393d2fcfcd594e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_menu.htm', size=541, md5='31dcf80dcc87cef727140d9ce87ab6fd', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_mutators.htm', size=298, md5='43352a731af0e7852b47712eae635f92', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_mutators_group.inc', size=231, md5='428bc06fc8934e16b69c2510b6df19be', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_mutators_group_row.inc', size=171, md5='40b5a7e9e6db22d99af69a518a115b9f', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_mutators_row.inc', size=154, md5='a5bae69cea85a5a7717d78e9c8fc0c40', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_mutators_selected.inc', size=59, md5='b91a06c00fa598b62e2479b0dc3a1238', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_mutators_table.inc', size=326, md5='9c2612a9ffdb9ad4568a5551639c99bd', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_players.htm', size=490, md5='34ba796cd16fbf3131339437c85091c5', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_players_ban_col.inc', size=115, md5='f2233ce275b91098e38bab51de33a465', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_players_empty_col.inc', size=15, md5='be83967a6facd4180a1df32864b5baf4', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_players_kick_col.inc', size=113, md5='22c1bc90356683814273d32260357169', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_players_list_head.inc', size=34, md5='f4ce06cd8d9aedd96327f0a6114408be', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_players_list_head_link.inc', size=127, md5='7606582e8ead46dca5ce07587cb7eea1', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/current_players_minp.inc', size=239, md5='932b82a569d42822cdff36f253a8e965', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaultsframe.htm', size=567, md5='3af6b0e586a970c65918ef7cbe92ed28', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_header.inc', size=101, md5='54bac6fd30481df9ec7f1ac16294a3ab', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_ippolicy.htm', size=644, md5='2106e7c6e17b49dcd7dbfd2221887278', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_ippolicy_row.inc', size=285, md5='914ff433d1e8497b2410e1b03bf7f832', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_maps.htm', size=2897, md5='891001faad2f1598a1c204158c1cfa87', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_mark.inc', size=61, md5='f81e9e710da1507326b5bcd9154cf722', mtime=1076677480, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_menu.htm', size=508, md5='111fc187bb0da01b0c7491887380abf3', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_menu_row.inc', size=61, md5='b4bd968c4bf4078d3818e6208fa8f65c', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_row.inc', size=191, md5='1a6be88932600016ddbdfd0cb39d58a3', mtime=1076677480, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_row_check.inc', size=150, md5='c2b187d4fec4a38568deb3a68c24b519', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_row_select.inc', size=145, md5='fb5901cd6ff66071d96ffcb662e99ccb', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_row_text.inc', size=226, md5='5c215079430c74fd0599e5acd9f69a46', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_rules.htm', size=606, md5='78887b6001861f1b6a65ad012e9ed3cd', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/defaults_votinggameconfig.htm', size=324, md5='7a65ca470c3deeed15048bbaae97b0c4', mtime=1072098495, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/footer.inc', size=318, md5='b3a6ccd41374b3453c8579dba7be4239', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/frame_header.inc', size=674, md5='afca0d969daae51f2808d3eb9add61c5', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/frame_message.htm', size=91, md5='3237794b79342804123104f8760c4e36', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/groups_add.htm', size=749, md5='ad9ccef1d0ecc7a8243b0f6cd012016b', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/groups_browse.htm', size=242, md5='5fe8e9c867cec4ae833c60882ed4068e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/groups_edit.htm', size=727, md5='d6b0c1d24aed9ccc17895e31be2cfb6b', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/groups_row.inc', size=104, md5='5c5c4a848f525d14f52aed7521927210', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/header.inc', size=1046, md5='aca244ebe2cc7caf9b7ff0543de6c116', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/hidden.inc', size=69, md5='ebfa0f80f8944a3b104909831231e5f1', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/mainmenu.htm', size=1389, md5='b20d670f603b464b5bfede67d8f0cbec', mtime=1077191250, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/mainmenu_item.inc', size=107, md5='9542380f974ce47760a8d2342d1d69d1', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/mainmenu_itemd.inc', size=89, md5='d66ee85bd014610bb5fd3026dd101206', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/mainmenu_items.inc', size=155, md5='17b4f1e2e28cf2773fbd2afddbb33651', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/menufooter.inc', size=320, md5='d8da4ae8b3d72a9ecea644111a55c44d', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/menuheader.inc', size=704, md5='c256e281f893aa1f7a5c658551c7ab5c', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/message.htm', size=85, md5='f3f6df670a3bb69328fd09e02df8e2a8', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/privs_element.inc', size=102, md5='8add8002b5261531f70749d451ef1fb3', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/privs_element_ro.inc', size=88, md5='e457a3dc7d14a806efe5ba5d57f83968', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/privs_header.inc', size=136, md5='b0d576d5d84ba305f82587cf96738842', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/privs_header_chk.inc', size=132, md5='eca54fb177784c84edfd1163f33bf7f7', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/radio_button.inc', size=79, md5='98ca0edd653508a1e9b4756c08187954', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/reset_button.inc', size=81, md5='d4a9708f294c3cbd37c0c3fe632c7b1e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/rootframe.htm', size=602, md5='2185e66e86949f63d9e8ff7bf94ce590', mtime=1076280331, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/row_center.inc', size=40, md5='241d22f494a0f99e3fb1b865fa0fce95', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/row_left.inc', size=38, md5='e95672d5b8a0f9094764b40eae1f2412', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/select.inc', size=69, md5='81960ebf72e844c5955df24da9680354', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/server_restart.htm', size=1099, md5='057241b532940f799318ad390916693f', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/server_restart_row.inc', size=227, md5='6af9fb71c95a051d4990ea4990f5ffd0', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/submit_button.inc', size=84, md5='0db8c9d549f823abaec848a98816f5f9', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/textbox.inc', size=107, md5='299cf9c649c3bf3e123df20350a2913b', mtime=1077877119, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/users.htm', size=4814, md5='45753e9868e6d61fa08b25777c7fcf19', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/users_add.htm', size=992, md5='27ed80e22d53990a72ec29f39cc7df56', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/users_browse.htm', size=250, md5='deb8658253c9b205d2e640f51f88e905', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/users_edit.htm', size=910, md5='36ffbd02c97394ac58086ed78ecd4b00', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/users_groups.htm', size=582, md5='bf96d5d15e475003564b77d2690018d6', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/users_groups_row.inc', size=117, md5='94e2d1df5e8a192df1328b6f2c21ecee', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/users_row.inc', size=113, md5='2d36d8c644e1d07576009c3de483f2e9', mtime=1053699897, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/ut2003.css', size=10495, md5='be7de01a5064d718c7dbaeb473556c07', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_directory ('Web/ServerAdmin/ClassicUT'),
		manifest_file ('Web/ServerAdmin/ClassicUT/adminsframe.htm', size=568, md5='521d9664ed1db712dc501cedd99660a5', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/admins_account.htm', size=2222, md5='c102733931b842c17749e1af43eda43d', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/admins_home.htm', size=394, md5='e56a820cf203b78c7bed492ca4cae564', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/admins_menu.htm', size=2963, md5='407124e6d8123598e0f6095e61e837d6', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/admins_priv_table.inc', size=47, md5='a4840eaac461ee93699c625b7b7bc769', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/cell_center.inc', size=37, md5='068dd35670856cc3a445652d05a1ff52', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/cell_center_nowrap.inc', size=44, md5='4cd9e04f9bdb3655f507d80d7a4544fc', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/cell_colspan.inc', size=58, md5='49920e15760b4521fe89acf1b767adec', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/cell_left.inc', size=35, md5='e05681b77bb09b34a2510e966c29600f', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/cell_left_nowrap.inc', size=42, md5='801d34a5c0e8d4254ee526f1a494556d', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/cell_right.inc', size=36, md5='6182d329cb5932873c2ff170df1c05a7', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/cell_right_nowrap.inc', size=43, md5='ce24eacde7ee8a713ded987f9b173a56', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/checkbox.inc', size=101, md5='7e56d2e02cc042c659c9aef15ad16aa7', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/classicut.css', size=10154, md5='875c500a4a9c43a42fe83251bc25addb', mtime=1077681740, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/currentframe.htm', size=567, md5='c981514cea14b974a3ff19f450c4853c', mtime=1053699896, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/ClassicUT/current_bots.htm', size=1769, md5='f7dae5b21438410942c8d3194672066b', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_bots_row.inc', size=210, md5='6592558387be6702ef91129e6c0408d5', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_bots_row_sel.inc', size=272, md5='0383615b1540cbc242e8dcd4b0c09547', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_bots_species.inc', size=104, md5='07d503a4f10fdba4b3148fbb0f535099', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_console.htm', size=570, md5='c8032f4610b659ef59ab4152eae8a87a', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_console_log.htm', size=106, md5='fe1a450a95083a9abd5b64d6d05070a7', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_console_send.htm', size=650, md5='26dbf064c745d432cc2a1a5642c4003d', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_game.htm', size=491, md5='81844163abbf79c7afde2cd73dcc5ea8', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_game_stat_table.inc', size=631, md5='3a4897fa284a46292f7249d8c94bbbfc', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_game_stat_table_row.inc', size=287, md5='7bab89d8ef00055423393d2fcfcd594e', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_menu.htm', size=2925, md5='f301714d9ceb157ab47319d1d84852f5', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_mutators.htm', size=298, md5='43352a731af0e7852b47712eae635f92', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_mutators_group.inc', size=231, md5='428bc06fc8934e16b69c2510b6df19be', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_mutators_group_row.inc', size=171, md5='40b5a7e9e6db22d99af69a518a115b9f', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_mutators_row.inc', size=154, md5='a5bae69cea85a5a7717d78e9c8fc0c40', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_mutators_selected.inc', size=59, md5='b91a06c00fa598b62e2479b0dc3a1238', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_mutators_table.inc', size=326, md5='9c2612a9ffdb9ad4568a5551639c99bd', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_players.htm', size=490, md5='34ba796cd16fbf3131339437c85091c5', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_players_ban_col.inc', size=115, md5='f2233ce275b91098e38bab51de33a465', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_players_empty_col.inc', size=15, md5='be83967a6facd4180a1df32864b5baf4', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_players_kick_col.inc', size=113, md5='22c1bc90356683814273d32260357169', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_players_list_head.inc', size=34, md5='f4ce06cd8d9aedd96327f0a6114408be', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_players_list_head_link.inc', size=127, md5='7606582e8ead46dca5ce07587cb7eea1', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/current_players_minp.inc', size=239, md5='932b82a569d42822cdff36f253a8e965', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaultsframe.htm', size=568, md5='4617d225abc1eebd16dada9985313204', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_header.inc', size=101, md5='54bac6fd30481df9ec7f1ac16294a3ab', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_ippolicy.htm', size=644, md5='2106e7c6e17b49dcd7dbfd2221887278', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_ippolicy_row.inc', size=285, md5='914ff433d1e8497b2410e1b03bf7f832', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_maps.htm', size=2897, md5='6569706f38a13df749e3022a3d42a714', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_mark.inc', size=61, md5='f81e9e710da1507326b5bcd9154cf722', mtime=1076677480, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_menu.htm', size=2972, md5='baf44839e7d6a3bba9d0309ef1a3de43', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_menu_row.inc', size=61, md5='b4bd968c4bf4078d3818e6208fa8f65c', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_row.inc', size=191, md5='1a6be88932600016ddbdfd0cb39d58a3', mtime=1076677480, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_row_check.inc', size=150, md5='c2b187d4fec4a38568deb3a68c24b519', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_row_select.inc', size=145, md5='fb5901cd6ff66071d96ffcb662e99ccb', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_row_text.inc', size=226, md5='5c215079430c74fd0599e5acd9f69a46', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_rules.htm', size=606, md5='78887b6001861f1b6a65ad012e9ed3cd', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/defaults_votinggameconfig.htm', size=324, md5='7a65ca470c3deeed15048bbaae97b0c4', mtime=1072098495, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/footer.inc', size=1742, md5='3d663ae461e584d96988886187842d75', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/frame_header.inc', size=856, md5='8ba53c16d60a905918e63fe5323beece', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/frame_message.htm', size=91, md5='3237794b79342804123104f8760c4e36', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/groups_add.htm', size=744, md5='254bacbf8e298f8ac23694169e0c4b11', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/groups_browse.htm', size=242, md5='5fe8e9c867cec4ae833c60882ed4068e', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/groups_edit.htm', size=727, md5='d6b0c1d24aed9ccc17895e31be2cfb6b', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/groups_row.inc', size=104, md5='5c5c4a848f525d14f52aed7521927210', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/header.inc', size=3066, md5='0943f77c3cfe166923ec9a501e7d2c00', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/hidden.inc', size=69, md5='ebfa0f80f8944a3b104909831231e5f1', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/mainmenu.htm', size=2339, md5='056e59321b9e41ab7b7499c5c03697bd', mtime=1077191250, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/mainmenu_item.inc', size=103, md5='7dab5b37daf2647a8d8a14a5990ceab3', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/mainmenu_itemd.inc', size=89, md5='d66ee85bd014610bb5fd3026dd101206', mtime=1053699896, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/mainmenu_items.inc', size=128, md5='999cf627de984553c02700650d58c248', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/menufooter.inc', size=320, md5='d8da4ae8b3d72a9ecea644111a55c44d', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/message.htm', size=85, md5='f3f6df670a3bb69328fd09e02df8e2a8', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/privs_element.inc', size=102, md5='8add8002b5261531f70749d451ef1fb3', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/privs_element_ro.inc', size=88, md5='e457a3dc7d14a806efe5ba5d57f83968', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/privs_header.inc', size=162, md5='226c0967b3a7c85f7a7e7355c0842ada', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/privs_header_chk.inc', size=132, md5='eca54fb177784c84edfd1163f33bf7f7', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/radio_button.inc', size=79, md5='98ca0edd653508a1e9b4756c08187954', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/reset_button.inc', size=81, md5='d4a9708f294c3cbd37c0c3fe632c7b1e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/rootframe.htm', size=602, md5='71e5394837034387be6ab6c2d12159e2', mtime=1077191250, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/row_center.inc', size=40, md5='241d22f494a0f99e3fb1b865fa0fce95', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/row_left.inc', size=38, md5='e95672d5b8a0f9094764b40eae1f2412', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/select.inc', size=69, md5='81960ebf72e844c5955df24da9680354', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/server_restart.htm', size=1099, md5='057241b532940f799318ad390916693f', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/server_restart_row.inc', size=227, md5='6af9fb71c95a051d4990ea4990f5ffd0', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/submit_button.inc', size=84, md5='0db8c9d549f823abaec848a98816f5f9', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/textbox.inc', size=107, md5='299cf9c649c3bf3e123df20350a2913b', mtime=1077877119, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/users.htm', size=4814, md5='45753e9868e6d61fa08b25777c7fcf19', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/users_add.htm', size=992, md5='27ed80e22d53990a72ec29f39cc7df56', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/users_browse.htm', size=250, md5='deb8658253c9b205d2e640f51f88e905', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/users_edit.htm', size=910, md5='36ffbd02c97394ac58086ed78ecd4b00', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/users_groups.htm', size=582, md5='bf96d5d15e475003564b77d2690018d6', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/users_groups_row.inc', size=117, md5='94e2d1df5e8a192df1328b6f2c21ecee', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/ClassicUT/users_row.inc', size=113, md5='2d36d8c644e1d07576009c3de483f2e9', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_directory ('Web/ServerAdmin/UnrealAdminPage'),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/adminsframe.htm', size=669, md5='c756b52bb4d4841965319ade2638453d', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/admins_account.htm', size=708, md5='8371eb557205fd9db96495ccb80198b2', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/admins_home.htm', size=690, md5='f48bbc3baa74737c25a48b078b0caabe', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/admins_menu.htm', size=1149, md5='fed164469e285e89cb19de6bc2a44686', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/admins_priv_table.inc', size=130, md5='c2dfcfe3c4bbfad1ff9f45ee7ae205d4', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/cell_center.inc', size=38, md5='e559470e6d0ec31455d2677f7a8a79b6', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/cell_center_nowrap.inc', size=45, md5='cf47ad2f78ecf2d880c50bd9ff35ce12', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/cell_colspan.inc', size=67, md5='a9bf71961944cd10bbc1bc516a8677bd', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/cell_left.inc', size=35, md5='e05681b77bb09b34a2510e966c29600f', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/cell_left_nowrap.inc', size=38, md5='3b91da5a296e98edf4c9565be46194ef', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/cell_right.inc', size=37, md5='dfd2d56914351cd67eb9227a6501c557', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/cell_right_nowrap.inc', size=53, md5='8687bbead34eb92cff9fe7b86dad3002', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/checkbox.inc', size=101, md5='7e56d2e02cc042c659c9aef15ad16aa7', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/currentframe.htm', size=669, md5='c756b52bb4d4841965319ade2638453d', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_bots.htm', size=1105, md5='9c44e90ee1f39fa3a984a85772724f1a', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_bots_row.inc', size=184, md5='6e9cc736550ae9e60ff1612f6e05ec57', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_bots_row_sel.inc', size=280, md5='e2ae2e0ae811368adcfa87aeaa1fd55b', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_bots_species.inc', size=77, md5='99801b6d35f465398a1059d358cb26f6', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_console.htm', size=651, md5='5bf6bba02cdf9cc509307dff5798b741', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_console_log.htm', size=106, md5='fe1a450a95083a9abd5b64d6d05070a7', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_console_send.htm', size=710, md5='54f39164e8076c284af00400bfded7c6', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_game.htm', size=459, md5='404c9649400c51f852bc678f3737bb91', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_game_stat_table.inc', size=190, md5='516f39977087e9a7cc213202a9ce67aa', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_game_stat_table_row.inc', size=229, md5='1618d00aa42885405bc7eb5cb02c9764', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_menu.htm', size=1155, md5='270d403b769ca91b86da41ecaba3b42f', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_mutators.htm', size=249, md5='0e3d87135366ae3c39c885f98af52eb1', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_mutators_group.inc', size=287, md5='bf8d2ea237afd9384138e9443fd19ade', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_mutators_group_row.inc', size=180, md5='6225212d4169fba709044e0b1c5b9a6d', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_mutators_row.inc', size=162, md5='a5109d819293bbc91b2b1b29209c5630', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_mutators_selected.inc', size=65, md5='1154c2fc2541089c8867558ce8036346', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_mutators_table.inc', size=208, md5='e099b3dd8572d0fee36c0a614ef97881', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_players.htm', size=404, md5='a9ac4124855ffd7acb97a90807e5e400', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_players_ban_col.inc', size=105, md5='ebec81921857607c908ef45d287bf325', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_players_empty_col.inc', size=9, md5='34f2be44fba776d675bd1c7fcbe02165', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_players_kick_col.inc', size=103, md5='f6b4c40fcaa91fd36983fec77f102ae8', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_players_list_head.inc', size=22, md5='f56e93fa06166086efcec7e23100542d', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_players_list_head_link.inc', size=114, md5='a4bd5390c9c2df8471d60438088ceb9d', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/current_players_minp.inc', size=178, md5='87126ed23c0b0884e5b6995f93046cce', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaultsframe.htm', size=622, md5='24f60c9a7593aa55e121d18ca76ac61c', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_header.inc', size=101, md5='54bac6fd30481df9ec7f1ac16294a3ab', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_ippolicy.htm', size=591, md5='79fd400cbcdc3560284758f91b37b757', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_ippolicy_row.inc', size=236, md5='739e9603c70ab7d3a3cb306db9d767ec', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_maps.htm', size=2284, md5='2cbe10e80726ef76bb167f9084e5f358', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_mark.inc', size=21, md5='08b5566b9d89ab104e957356c20089df', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_menu.htm', size=1115, md5='48b974d63b13cc0b400d8044899c6a2a', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_menu_row.inc', size=70, md5='f1cad18f9d18010c4da8a10e85117277', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_row.inc', size=160, md5='9876375b8112f305578e527619748999', mtime=1076677480, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_rules.htm', size=735, md5='d9bebf7777aa2a716818abc9edecd309', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/defaults_votinggameconfig.htm', size=325, md5='29f3aab56a3bb8f4502d4d0f2e5af34d', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/footer.inc', size=462, md5='b1002f9c7e713d641be667de706e99bf', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/frame_message.htm', size=91, md5='3237794b79342804123104f8760c4e36', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/groups_add.htm', size=744, md5='254bacbf8e298f8ac23694169e0c4b11', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/groups_browse.htm', size=242, md5='5fe8e9c867cec4ae833c60882ed4068e', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/groups_edit.htm', size=727, md5='d6b0c1d24aed9ccc17895e31be2cfb6b', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/groups_row.inc', size=104, md5='5c5c4a848f525d14f52aed7521927210', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/header.inc', size=641, md5='9879b46eed7ad5e0b915c7cfdc32e074', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/hidden.inc', size=69, md5='ebfa0f80f8944a3b104909831231e5f1', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/mainmenu.htm', size=1987, md5='04fffa4e0d3e57697ae67d332f99e5f2', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/mainmenu_item.inc', size=102, md5='73d289bfd2203010e23fdc5ebb2cae10', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/mainmenu_itemd.inc', size=94, md5='1e5041d6a51871aebad89a92a3c83b72', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/mainmenu_items.inc', size=95, md5='43d7c0f097d54da500acdd48c2801db2', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/menufooter.inc', size=320, md5='d8da4ae8b3d72a9ecea644111a55c44d', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/message.htm', size=85, md5='f3f6df670a3bb69328fd09e02df8e2a8', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/privs_element.inc', size=37, md5='f4380e470faf58bc5aae2efaadd150fc', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/privs_element_ro.inc', size=88, md5='e457a3dc7d14a806efe5ba5d57f83968', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/privs_header.inc', size=72, md5='783bdbe10895bba8dba63a87e9b33f84', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/radio_button.inc', size=79, md5='64bc0c30ea01412c4aa70a5072e2cdcc', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/reset_button.inc', size=81, md5='1cb303816f6d23a5d2edf44ce4f829d2', mtime=1074346219, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/rootframe.htm', size=688, md5='be4df634c9bf0a5802ab0aa8038ae124', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/row_center.inc', size=41, md5='0b86340caa3b8b8ad2cda0e16417dfbf', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/row_left.inc', size=38, md5='e95672d5b8a0f9094764b40eae1f2412', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/select.inc', size=56, md5='b5871a1c7d411b024d509a66c6a627ea', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/server_restart.htm', size=867, md5='14b1507159b496188836582bae9e166c', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/server_restart_row.inc', size=227, md5='6af9fb71c95a051d4990ea4990f5ffd0', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/submit_button.inc', size=84, md5='0db8c9d549f823abaec848a98816f5f9', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/textbox.inc', size=107, md5='299cf9c649c3bf3e123df20350a2913b', mtime=1077877119, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UnrealAdminPage/UnrealAdminPage.css', size=2095, md5='6d69e255f8b1880538c5a65d0afb962c', mtime=1075290033, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/users.htm', size=4814, md5='45753e9868e6d61fa08b25777c7fcf19', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/users_add.htm', size=992, md5='27ed80e22d53990a72ec29f39cc7df56', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/users_browse.htm', size=250, md5='deb8658253c9b205d2e640f51f88e905', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/users_edit.htm', size=910, md5='36ffbd02c97394ac58086ed78ecd4b00', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/users_groups.htm', size=605, md5='efba06245779fd7a19a64278a2d59de8', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/users_groups_row.inc', size=117, md5='94e2d1df5e8a192df1328b6f2c21ecee', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/users_row.inc', size=113, md5='2d36d8c644e1d07576009c3de483f2e9', mtime=1074346219, source_media=media_ut2004_cd1),
		manifest_directory ('Web/ServerAdmin/UT2K3Stats'),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/adminsframe.htm', size=568, md5='521d9664ed1db712dc501cedd99660a5', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/admins_account.htm', size=1404, md5='07a29f6c1510b9f1cb320be34723f161', mtime=1053699897, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UT2K3Stats/admins_home.htm', size=786, md5='fb834cf2d27830723188ca840345fe7e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/admins_menu.htm', size=508, md5='276add9c33af72974aae414f7a557d38', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/admins_priv_table.inc', size=60, md5='2bf7fdf20bcfd09c97b6c1c958191573', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/cell_center.inc', size=59, md5='5ab9d1d3c88b10aec6a932f5758c6601', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/cell_center_nowrap.inc', size=66, md5='c44bb4f8a956b9e84a4238233a8f2601', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/cell_colspan.inc', size=80, md5='7b95141006c5ea2f3d8aa9340e69a588', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/cell_left.inc', size=57, md5='026aa04a8edd46a8675ec2547e9fea67', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/cell_left_nowrap.inc', size=64, md5='ebbf0334664f76cd0c04b550c38ef061', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/cell_right.inc', size=58, md5='61cb1ee19e16d9146c2e2e7c0094780c', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/cell_right_nowrap.inc', size=65, md5='89e4ea8438f2e2d359d507b65a908134', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/checkbox.inc', size=101, md5='7e56d2e02cc042c659c9aef15ad16aa7', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/currentframe.htm', size=567, md5='d0abd6533f789adccbf16d18fda38214', mtime=1053699897, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UT2K3Stats/current_bots.htm', size=1634, md5='2130e914c1571bfb72651f29ceef5768', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_bots_row.inc', size=230, md5='36d4af1856f80469036a22a741d90b65', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_bots_row_sel.inc', size=286, md5='f08fa2ccbe90964362217fde6f173310', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_bots_species.inc', size=102, md5='d6fdbee617592919119a29cf8f072697', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_console.htm', size=570, md5='c8032f4610b659ef59ab4152eae8a87a', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_console_log.htm', size=106, md5='fe1a450a95083a9abd5b64d6d05070a7', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_console_send.htm', size=584, md5='f0b51616b6316df4e2ef6f09bf8a95a2', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_game.htm', size=489, md5='e0ed268f415a81833bfb5a706315eb16', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_game_stat_table.inc', size=631, md5='3a4897fa284a46292f7249d8c94bbbfc', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_game_stat_table_row.inc', size=287, md5='7bab89d8ef00055423393d2fcfcd594e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_menu.htm', size=541, md5='31dcf80dcc87cef727140d9ce87ab6fd', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_mutators.htm', size=298, md5='43352a731af0e7852b47712eae635f92', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_mutators_group.inc', size=288, md5='4b70adc9aac25c2a36a711d1b5fb7fc6', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_mutators_group_row.inc', size=217, md5='3621bd7f0ce8999b4eda575c878ee1ba', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_mutators_row.inc', size=154, md5='a5bae69cea85a5a7717d78e9c8fc0c40', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_mutators_selected.inc', size=85, md5='5c9683b3979aa2d7a5f18d6af06c16f5', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_mutators_table.inc', size=348, md5='812a7359210105138e8ac761f9f7e424', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_players.htm', size=490, md5='34ba796cd16fbf3131339437c85091c5', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_players_ban_col.inc', size=115, md5='f2233ce275b91098e38bab51de33a465', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_players_empty_col.inc', size=15, md5='be83967a6facd4180a1df32864b5baf4', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_players_kick_col.inc', size=117, md5='cf1721ad7d461be49f012e0bcf870973', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_players_list_head.inc', size=49, md5='24c8e3d08042cf7e3101a9bd967874d6', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_players_list_head_link.inc', size=142, md5='f0c6cb550707484556c387ff6e41be06', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/current_players_minp.inc', size=239, md5='932b82a569d42822cdff36f253a8e965', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaultsframe.htm', size=567, md5='3af6b0e586a970c65918ef7cbe92ed28', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_header.inc', size=101, md5='54bac6fd30481df9ec7f1ac16294a3ab', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_ippolicy.htm', size=694, md5='3ea7f2d9381f93af0bfe92080323bf07', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_ippolicy_row.inc', size=285, md5='914ff433d1e8497b2410e1b03bf7f832', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_maps.htm', size=2897, md5='891001faad2f1598a1c204158c1cfa87', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_mark.inc', size=68, md5='d762e4aa67e018938d56ca4960e45693', mtime=1076677480, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_menu.htm', size=503, md5='b72f235c86f5c32fc3aeb32e67d828bb', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_menu_row.inc', size=61, md5='b4bd968c4bf4078d3818e6208fa8f65c', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_row.inc', size=241, md5='9573b6e7c77693d0aaf67720a6291ef2', mtime=1076677480, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_row_check.inc', size=152, md5='c2612f53242b5a8667504c327879b948', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_row_select.inc', size=149, md5='9db1e1f1cb354b31958c11392a826d15', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_row_text.inc', size=232, md5='56926f3dda9175e323a4b4d9aa2170b9', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_rules.htm', size=606, md5='78887b6001861f1b6a65ad012e9ed3cd', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/defaults_votinggameconfig.htm', size=324, md5='7a65ca470c3deeed15048bbaae97b0c4', mtime=1072098495, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/footer.inc', size=318, md5='b3a6ccd41374b3453c8579dba7be4239', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/frame_header.inc', size=674, md5='afca0d969daae51f2808d3eb9add61c5', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/frame_message.htm', size=91, md5='3237794b79342804123104f8760c4e36', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/groups_add.htm', size=807, md5='565eb260402863ff1fa3c0bcff2623b8', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/groups_browse.htm', size=242, md5='5fe8e9c867cec4ae833c60882ed4068e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/groups_edit.htm', size=764, md5='3d29a86df6ef96eac16ee01764dcd9b6', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/groups_row.inc', size=104, md5='5c5c4a848f525d14f52aed7521927210', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/header.inc', size=1058, md5='433ae8e207ba66d4c477f2c2588e667e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/hidden.inc', size=69, md5='ebfa0f80f8944a3b104909831231e5f1', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/mainmenu.htm', size=1389, md5='b20d670f603b464b5bfede67d8f0cbec', mtime=1077191250, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/mainmenu_item.inc', size=107, md5='9542380f974ce47760a8d2342d1d69d1', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/mainmenu_itemd.inc', size=89, md5='d66ee85bd014610bb5fd3026dd101206', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/mainmenu_items.inc', size=155, md5='17b4f1e2e28cf2773fbd2afddbb33651', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/menufooter.inc', size=320, md5='d8da4ae8b3d72a9ecea644111a55c44d', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/menuheader.inc', size=704, md5='c256e281f893aa1f7a5c658551c7ab5c', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/message.htm', size=85, md5='f3f6df670a3bb69328fd09e02df8e2a8', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/privs_element.inc', size=102, md5='8add8002b5261531f70749d451ef1fb3', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/privs_element_ro.inc', size=90, md5='901be1d166647b86e28f9d321faee306', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/privs_header.inc', size=136, md5='b0d576d5d84ba305f82587cf96738842', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/privs_header_chk.inc', size=132, md5='eca54fb177784c84edfd1163f33bf7f7', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/radio_button.inc', size=79, md5='98ca0edd653508a1e9b4756c08187954', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/reset_button.inc', size=81, md5='d4a9708f294c3cbd37c0c3fe632c7b1e', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/rootframe.htm', size=602, md5='2185e66e86949f63d9e8ff7bf94ce590', mtime=1077191250, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/row_center.inc', size=40, md5='241d22f494a0f99e3fb1b865fa0fce95', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/row_left.inc', size=38, md5='e95672d5b8a0f9094764b40eae1f2412', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/select.inc', size=69, md5='81960ebf72e844c5955df24da9680354', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/server_restart.htm', size=1099, md5='057241b532940f799318ad390916693f', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/server_restart_row.inc', size=229, md5='1497b3120dfeb30df67af6789b53432d', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/submit_button.inc', size=84, md5='0db8c9d549f823abaec848a98816f5f9', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/textbox.inc', size=107, md5='299cf9c649c3bf3e123df20350a2913b', mtime=1077877119, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/users.htm', size=4814, md5='45753e9868e6d61fa08b25777c7fcf19', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/users_add.htm', size=992, md5='27ed80e22d53990a72ec29f39cc7df56', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/users_browse.htm', size=250, md5='deb8658253c9b205d2e640f51f88e905', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/users_edit.htm', size=910, md5='36ffbd02c97394ac58086ed78ecd4b00', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/users_groups.htm', size=584, md5='bf2f19d5843532374f1a5b71128ad7de', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/users_groups_row.inc', size=117, md5='94e2d1df5e8a192df1328b6f2c21ecee', mtime=1053699897, source_media=media_ut2004_cd1),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/users_row.inc', size=113, md5='2d36d8c644e1d07576009c3de483f2e9', mtime=1053699897, source_media=media_ut2004_cd1),
		#manifest_file ('Web/ServerAdmin/UT2K3Stats/ut2003stats.css', size=10621, md5='6ef0ee726d458578389c9c1cfb87e095', mtime=1053699897, source_media=media_ut2004_cd1),
		#manifest_file ('Web/Src/Web.vcproj', size=24605, md5='1d24d847ac010e75030b9da87eaf0138', mtime=1058149891, source_media=media_ut2004_cd1),

		manifest_directory ('Animations'),
		manifest_file ('Animations/2K4_NvidiaIntro.ukx', size=2825120, md5='a05ec45792a93bb02d1da247d1554589', mtime=1078276849, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Aliens.ukx', size=3252262, md5='f366dc20b68e09bac56558e9e4f5e191', mtime=1078276850, source_media=media_ut2004_cd1),
		manifest_file ('Animations/AS_VehiclesFull_M.ukx', size=3504561, md5='526281a6054227e8a4ee7372c0b50426', mtime=1078276850, source_media=media_ut2004_cd1),
		manifest_file ('Animations/AS_Vehicles_M.ukx', size=637087, md5='2897b0558e8d97cb33ff36c153395d08', mtime=1078276850, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Bot.ukx', size=2440663, md5='53b2fed5d5c427aa5cad9e2716124ec7', mtime=1078276851, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Cannons.ukx', size=116546, md5='f5dffec7d3b6eff81a42db71c00d2eb9', mtime=1078276851, source_media=media_ut2004_cd1),
		manifest_file ('Animations/DemoFemaleA.ukx', size=1682631, md5='c46448123672ce7f60d07316f1a22796', mtime=1078276851, source_media=media_ut2004_cd1),
		manifest_file ('Animations/DemoMaleA.ukx', size=1559000, md5='0e210a3272910bb208a993665d9dc01b', mtime=1078276851, source_media=media_ut2004_cd1),
		manifest_file ('Animations/GenericSD.ukx', size=2670058, md5='88486116856064578bb5749742f40913', mtime=1078276852, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Hellions.ukx', size=1810377, md5='db9828e25688b921d19a8afb0ce0db36', mtime=1078276852, source_media=media_ut2004_cd1),
		manifest_file ('Animations/HumanFemaleA.ukx', size=3953575, md5='ca894c114c06ed62847a1908f2cc137e', mtime=1078276853, source_media=media_ut2004_cd1),
		manifest_file ('Animations/HumanMaleA.ukx', size=4479538, md5='d7a3745bc7001c868ac101e3ab67e475', mtime=1078276854, source_media=media_ut2004_cd1),
		manifest_file ('Animations/intro_brock.ukx', size=7742712, md5='e6a343cff93519080d53d2db1141288c', mtime=1078276855, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Intro_brockfan.ukx', size=993477, md5='15d0829c6b6ca4fa5976194fd1c3be94', mtime=1078276855, source_media=media_ut2004_cd1),
		manifest_file ('Animations/intro_crowd.ukx', size=3581538, md5='7846d2e84efffad44c20c85c6cbecad0', mtime=1078276856, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Intro_gorge.ukx', size=3580867, md5='ca306419b508b20cfeeb010cd83b746c', mtime=1078276857, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Intro_gorgefan.ukx', size=2294605, md5='3fb59b7f8f3e6bdfc2be4ba12056b048', mtime=1078276857, source_media=media_ut2004_cd1),
		manifest_file ('Animations/intro_jugchick.ukx', size=3056276, md5='02b658c8784e8b03697215a411fb98c8', mtime=1078276857, source_media=media_ut2004_cd1),
		manifest_file ('Animations/intro_lauren.ukx', size=5191558, md5='9403628bcd0c218c2e6ea1524b9b6f53', mtime=1078276858, source_media=media_ut2004_cd1),
		manifest_file ('Animations/intro_malcom.ukx', size=4700056, md5='26dc761107ad6e2ed6bdf1da8409edf5', mtime=1078276859, source_media=media_ut2004_cd1),
		manifest_file ('Animations/intro_nikoli.ukx', size=3488142, md5='989e114ada3081f8fd39968bf9aab93a', mtime=1078276860, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Jugg.ukx', size=2628302, md5='f16b6116aeba82fc10cb75c5aba2661d', mtime=1078276860, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Merc_intro.ukx', size=938690, md5='a72a792ca6d10d1059f55ea07b5e912a', mtime=1078276860, source_media=media_ut2004_cd1),
		manifest_file ('Animations/NewNightmare.ukx', size=1203228, md5='8e5b89d5c773f0a167b027ca563576cd', mtime=1078276861, source_media=media_ut2004_cd1),
		manifest_file ('Animations/NewWeapons2004.ukx', size=1249681, md5='f1467ed45642e1d1bb608443b49229e4', mtime=1078276861, source_media=media_ut2004_cd1),
		manifest_file ('Animations/NvidiaGorge.ukx', size=1015289, md5='2a25d42ef82cc2cadfb4d04bc82e7dbf', mtime=1078276861, source_media=media_ut2004_cd1),
		manifest_file ('Animations/ONSFullAnimations.ukx', size=1469378, md5='a2310510be2ba2db097bae50951daa35', mtime=1078276861, source_media=media_ut2004_cd1),
		manifest_file ('Animations/ONSVehicles-A.ukx', size=1949548, md5='9e0065a140b1f01fda666f2ca46837ca', mtime=1078276862, source_media=media_ut2004_cd1),
		manifest_file ('Animations/ONSWeapons-A.ukx', size=3917835, md5='bc31172bb50361d4348f4388c0638e9e', mtime=1078276862, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Scene3_Garrett.ukx', size=774744, md5='7646f75b2ce87753b9a119403d4a9bb9', mtime=1078276863, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Scene3_Gitty.ukx', size=663168, md5='2d14f2789b26ebc9695635df5301eb22', mtime=1078276863, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Scene3_Jacob.ukx', size=722919, md5='383c15a91db69329cef564aa52221653', mtime=1078276863, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Scene3_Kane.ukx', size=786779, md5='41f648c2e4e2acd6e2b2cafe02b53779', mtime=1078276863, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Scene3_Malcom.ukx', size=1362462, md5='fe1da164cad6cc65e6fc39bffe368ab6', mtime=1078276863, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Scene3_Rae.ukx', size=479567, md5='8d681a04d5bcfd85bb6a91c26211df2a', mtime=1078276863, source_media=media_ut2004_cd1),
		manifest_file ('Animations/SkaarjAnims.ukx', size=4079034, md5='24b8f99aef24a7b47109fbfb7c8808cf', mtime=1078276864, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Skaarj_intro.ukx', size=1548325, md5='2622c93d56d02f5146b8b28df6b42b86', mtime=1078276864, source_media=media_ut2004_cd1),
		manifest_file ('Animations/SniperAnims.ukx', size=173555, md5='080d1f4f59850d285164327a5ed8e2ac', mtime=1078276864, source_media=media_ut2004_cd1),
		manifest_file ('Animations/StreamAnims.ukx', size=6040491, md5='65eb41f82439982fac1e3cc4c8281b32', mtime=1078276866, source_media=media_ut2004_cd1),
		manifest_file ('Animations/ThunderCrash.ukx', size=1384776, md5='8a822529a19bf029ad33ca79a35c3eaa', mtime=1078276866, source_media=media_ut2004_cd1),
		manifest_file ('Animations/Weapons.ukx', size=2837050, md5='746d1546b081597f9dfc0a0c5bc46d74', mtime=1078276866, source_media=media_ut2004_cd1),
		manifest_file ('Animations/XanRobots.ukx', size=1795728, md5='1f90774745ca00113fa3c03690967206', mtime=1078276867, source_media=media_ut2004_cd1),

		manifest_directory ('Maps'),
		manifest_file ('Maps/AS-Convoy.ut2', size=10173598, md5='6df00d73fcedaf13e1998390836d9bdc', mtime=1078276870, source_media=media_ut2004_cd1),
		manifest_file ('Maps/AS-FallenCity.ut2', size=24470195, md5='21ba914793457138ec423e53ba9649ba', mtime=1078276876, source_media=media_ut2004_cd1),
		manifest_file ('Maps/AS-Glacier.ut2', size=33183612, md5='c98522507732c30eac415847c772ffdc', mtime=1078276885, source_media=media_ut2004_cd1),
		manifest_file ('Maps/AS-Junkyard.ut2', size=11390498, md5='8c1827ae67d0d97df28871ae92b630c0', mtime=1078276888, source_media=media_ut2004_cd1),
		manifest_file ('Maps/AS-MotherShip.ut2', size=35833460, md5='9577da926db8f7e44e4f5a033bf889e1', mtime=1078276894, source_media=media_ut2004_cd1),
		manifest_file ('Maps/AS-RobotFactory.ut2', size=22995764, md5='7b31f60d2f918150b28371fb772933d1', mtime=1078276899, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Anubis.ut2', size=15261805, md5='8caa3d5b1ab1f2d52acf270fab0835e6', mtime=1078276902, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Bifrost.ut2', size=12048423, md5='ae9a1e2a75424cf1bb6fc85ab170477b', mtime=1078276904, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-BridgeOfFate.ut2', size=22209058, md5='aa91a28ec2eefe6fbc36d64ec59e7280', mtime=1078276910, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Canyon.ut2', size=9554574, md5='e55e4c8344ba96fc350ec7365f3bbdb6', mtime=1078276913, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Colossus.ut2', size=18119054, md5='15055dc551b85759a3c2f99c55a732cb', mtime=1078276916, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-DE-ElecFields.ut2', size=8584836, md5='4e8cf9e54a60ee05b02bfcdcb1069e3c', mtime=1078276919, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Disclosure.ut2', size=19677453, md5='43c12671336f1fda538546b5684a7178', mtime=1078276923, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-IceFields.ut2', size=5357647, md5='66fb8b3363f8eda1853826fb2c3f71af', mtime=1078276924, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Serenity.ut2', size=11062050, md5='08496d9d0e5bfd69522287c134fc7789', mtime=1078276927, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Skyline.ut2', size=5549282, md5='550d5b4fc025008b6e011a8d81211cbb', mtime=1078276928, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-Slaughterhouse.ut2', size=23531560, md5='43a62e33aac0508a8aaf8f70215afa34', mtime=1078276933, source_media=media_ut2004_cd1),
		manifest_file ('Maps/BR-TwinTombs.ut2', size=18866627, md5='bfd3486e4280d3ed8fe6a62e4fb97c8c', mtime=1078276937, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-1on1-Joust.ut2', size=4073392, md5='6b1fe9f785245282b8ceb59a2c3fe18e', mtime=1078276938, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-AbsoluteZero.ut2', size=46082446, md5='84c2e74c257e020409fa4a6ff9c3b81c', mtime=1078276948, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Avaris.ut2', size=23927079, md5='3c84d8abedac84c3eb6a586bab4e1c8c', mtime=1078276954, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-BridgeOfFate.ut2', size=27970106, md5='c9e58ce6c164d3df569b0ee1b6f06db0', mtime=1078276960, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Chrome.ut2', size=13393600, md5='3a744ede1ab3ec3019bcc2510bbdfbb0', mtime=1078276963, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Citadel.ut2', size=6135315, md5='ea6534d2469dcb6a63bda319e42cd2cb', mtime=1078276964, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Colossus.ut2', size=19274238, md5='d3f8e8fc34d25b51e82e5ba6c479752a', mtime=1078276969, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-DE-ElecFields.ut2', size=8731800, md5='d47cc225e8c9191d7457af9933e49ee8', mtime=1078276971, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-December.ut2', size=17605552, md5='d8b417f062391160f1b092fc98c7652f', mtime=1078276974, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-DoubleDammage.ut2', size=16670428, md5='3357039f8b78913a60148cd2adb1bcc7', mtime=1078276978, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Face3.ut2', size=13423349, md5='65c433b07436ead678d053e338950777', mtime=1078276981, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-FaceClassic.ut2', size=28141678, md5='6ec72a903388842529d10abbb5f97d5f', mtime=1078276987, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Geothermal.ut2', size=6445049, md5='13d7627aba6dbaa19fb91ad84bb7df73', mtime=1078276989, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Grassyknoll.ut2', size=28394908, md5='f594353009a0e6df1dc16e0268d6eed3', mtime=1078276995, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Grendelkeep.ut2', size=23548537, md5='128048cd4c46bacddf7a7286e32b57bf', mtime=1078277001, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-January.ut2', size=12328457, md5='bfb231c923ce9c8f70dac0a68cda08db', mtime=1078277003, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Lostfaith.ut2', size=13740052, md5='9874da39f05783d494febdc63eb54631', mtime=1078277006, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Magma.ut2', size=2425687, md5='34706a6c805d6179433a8cbf939b614c', mtime=1078277007, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Maul.ut2', size=3383607, md5='3e8b22e791c3552d503833a7d57af32b', mtime=1078277007, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-MoonDragon.ut2', size=12858778, md5='4c1430130b5d2af88090dc2139e84036', mtime=1078277010, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Orbital2.ut2', size=11869229, md5='aa1429183302893f07c4cd1d450616b4', mtime=1078277013, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-Smote.ut2', size=24791727, md5='bced2b79864d5b3f9e184e717764c969', mtime=1078277018, source_media=media_ut2004_cd1),
		manifest_file ('Maps/CTF-TwinTombs.ut2', size=26865440, md5='1ace7726c32b717c61ccb82862ed2c1e', mtime=1078277024, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Albatross.ut2', size=10520659, md5='b42f1dfa3947929a5ebfff54039644ef', mtime=1078277027, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Crash.ut2', size=6665725, md5='d61e614f4e966b6d5aad32c21d91018b', mtime=1078277028, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Desolation.ut2', size=51588300, md5='d0786c7290ab4691aa4337d8b3da1dea', mtime=1078277039, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Idoma.ut2', size=11895873, md5='af4af19675efba479f556d56a8142c62', mtime=1078277042, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Irondust.ut2', size=18609215, md5='0a44599ab2cf4e629b6dc0f44866d6f4', mtime=1078277045, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Mixer.ut2', size=11397825, md5='4053ecfb327ffe5c4697cd85c461da0f', mtime=1078277047, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Roughinery.ut2', size=7718987, md5='ac5865a769e260fc8a94d0524a97d81a', mtime=1078277049, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Serpentine.ut2', size=4150212, md5='121423b477ef7a3359525ccbf179cb00', mtime=1078277050, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Spirit.ut2', size=11082308, md5='6cb90e933361e1e276d740c7b7a6f1cd', mtime=1078277053, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Squader.ut2', size=4571350, md5='8ae639803d83165b5a74950743f553a7', mtime=1078277054, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-1on1-Trite.ut2', size=5731461, md5='04f4cb9970bfc5413c9246e88dde93ef', mtime=1078277055, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Antalus.ut2', size=3622798, md5='032b629ab11bfe1291d029f569287703', mtime=1078277056, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Asbestos.ut2', size=13502841, md5='2239a28c7823a6cf6c2008f1b6087dac', mtime=1078277059, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Compressed.ut2', size=7592621, md5='adcbb2267bf219b66f7c4cfe18ff0342', mtime=1078277061, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Corrugation.ut2', size=14764402, md5='f4f9fa334eef036101b8667bbaf8c96c', mtime=1078277064, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Curse4.ut2', size=5892054, md5='3aec59770698d27d57f8a621bfdbbb41', mtime=1078277065, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-DE-Grendelkeep.ut2', size=24012385, md5='ccd9f7d390d792b6ef5ce7beaf4aa556', mtime=1078277071, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-DE-Ironic.ut2', size=10929186, md5='ae8d040e267f924b0421a284fd1b5be9', mtime=1078277073, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-DE-Osiris2.ut2', size=13167709, md5='4c7a0dd8208dedc4e7429526bd76f574', mtime=1078277077, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Deck17.ut2', size=31831451, md5='4ef477cb738b4c98e05bb1ac2d34e8fe', mtime=1078277083, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-DesertIsle.ut2', size=11673351, md5='43866be54b87b43fd67b45c1492fae2f', mtime=1078277086, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Flux2.ut2', size=11414188, md5='71484df21dc100973a2fbd2ba6294989', mtime=1078277089, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Gael.ut2', size=3012441, md5='f42223b708361e80ee06877bde99f08b', mtime=1078277089, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Gestalt.ut2', size=10427507, md5='13408dc74a79ed0a1848ee58c415d8bc', mtime=1078277092, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Goliath.ut2', size=9568571, md5='e0c5cc2fe03e07a8df854ea7b4c1e8e3', mtime=1078277094, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-HyperBlast2.ut2', size=10315387, md5='398ce177a17c97a5100f08ba82425d96', mtime=1078351578, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Icetomb.ut2', size=6463152, md5='8853e6e6e631d6924f677f68cafdce24', mtime=1078277098, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Inferno.ut2', size=7217437, md5='5175f69f789d3df3ddbaaeaaefbba038', mtime=1078277100, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Injector.ut2', size=11087515, md5='b091403e603898319d33a5473d22f9e6', mtime=1078277102, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Insidious.ut2', size=4408541, md5='84336dc368a1430fac4f98bf905d922f', mtime=1078277103, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-IronDeity.ut2', size=9207894, md5='b83a481e47ad0229a7c84a4b691ddb36', mtime=1078277105, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Junkyard.ut2', size=9716721, md5='76f722e24cfe6eca40ad4e0bff28b57a', mtime=1078277107, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Leviathan.ut2', size=10293004, md5='34b5b4ec6ba5aeef50ca7597f60c0bff', mtime=1078277109, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Metallurgy.ut2', size=9857138, md5='527ab55006c93ae19a12527957d6689e', mtime=1078277111, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Morpheus3.ut2', size=7168331, md5='5f9921382a4ff9287ef243ca0ff4c722', mtime=1078277113, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Oceanic.ut2', size=4650099, md5='559d291187b556c837203af76e458055', mtime=1078277114, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Phobos2.ut2', size=12684226, md5='a6e5546dfd83ac472ec1d31a48a11d74', mtime=1078277117, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Plunge.ut2', size=5183520, md5='0aba03d542f8cde0eac6e39b699ee91f', mtime=1078277118, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Rankin.ut2', size=13400320, md5='bba95c7c30cb5de763accaa19b9d5377', mtime=1078277122, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Rrajigar.ut2', size=6038850, md5='fedd89a227fd30ee2ca236cafc8ba200', mtime=1078277123, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Rustatorium.ut2', size=9447374, md5='27a8a0408995946d705345a3fee97ea7', mtime=1078277125, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-Sulphur.ut2', size=3200500, md5='7b904d6405106ed2845518514285d90e', mtime=1078277126, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-TokaraForest.ut2', size=4830285, md5='f9fd9e33678cb994170bcdee952d000a', mtime=1078277127, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DM-TrainingDay.ut2', size=3068240, md5='90e3e93708d29e272bfd13fee870978e', mtime=1078277128, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Access.ut2', size=10842879, md5='d8e4a090879e98da15fbac6c7c805a06', mtime=1078277131, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Aswan.ut2', size=11124697, md5='82d84df5acdcbecd8d54fd3bbc63c351', mtime=1078277133, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Atlantis.ut2', size=5949228, md5='328ea4780467d4078dce2d6891254ab3', mtime=1078277134, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Conduit.ut2', size=7745086, md5='70255f94fff3f1f55aab9b396339451a', mtime=1078277136, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Core.ut2', size=13439392, md5='98b0c41fe6be49e63156f67f3a14b03b', mtime=1078277139, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Junkyard.ut2', size=9451687, md5='aa8e3037e210153d4978a1fc49460a1f', mtime=1078277141, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-OutRigger.ut2', size=22927122, md5='0c6298c5961f7d151bc67207912c4cd9', mtime=1078277146, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Renascent.ut2', size=8226489, md5='ad9f1df97cfd64fcac1d6a80074fcbea', mtime=1078277148, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Ruination.ut2', size=14298298, md5='c33d012e1820349a75e76a00adc1a6e9', mtime=1078277151, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-ScorchedEarth.ut2', size=12674143, md5='451d4fd8ab7647d07753a307dcadc122', mtime=1078277154, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-SepukkuGorge.ut2', size=4928615, md5='00a3b3c72cbc46738e98f6648d0a175d', mtime=1078277155, source_media=media_ut2004_cd1),
		manifest_file ('Maps/DOM-Suntemple.ut2', size=9949317, md5='a62f679c0556789dec90130f8dfbb397', mtime=1078277157, source_media=media_ut2004_cd1),
		manifest_file ('Maps/endgame.ut2', size=902260, md5='85423c697157aa1795def490e7ba4805', mtime=1078277157, source_media=media_ut2004_cd1),

		# Two copies of this file on CD1, both identical,
		# different mtimes. Only one is uz2'd.
		manifest_file ('Maps/Entry.ut2', size=336568, md5='16e44640d112697a78ed6284cf7a23ed', mtime=1076074087, source_media=media_ut2004_cd1),

		manifest_file ('Maps/Mov-UT2-intro.ut2', size=3124736, md5='959b657bd9feebcb8ae5ffdfc7da8cde', mtime=1078277158, source_media=media_ut2004_cd1),
		manifest_file ('Maps/MOV-UT2004-Intro.ut2', size=5242099, md5='33c59cd952b909ac681349a6afe8ab05', mtime=1078277159, source_media=media_ut2004_cd1),
		manifest_file ('Maps/NoIntro.ut2', size=334840, md5='3590983cd0fbb1c1c2239b56db936a5f', mtime=1078277159, source_media=media_ut2004_cd1),
		manifest_file ('Maps/NvidiaLogo.ut2', size=488268, md5='2f4cd2695dbdd31edd73b68b5d74cbdb', mtime=1078277159, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-ArcticStronghold.ut2', size=14169833, md5='606c3b3954d3f298e7eaffca011f0730', mtime=1078277163, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-Crossfire.ut2', size=9750714, md5='046a104605607eb6fd30d021d6b0d64f', mtime=1078277166, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-Dawn.ut2', size=11750367, md5='3fd2bdd3578cb911db7a3caf21f606ec', mtime=1078277169, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-Dria.ut2', size=11048573, md5='b33d763dcfba50e9614a3e3db3f56898', mtime=1078277171, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-FrostBite.ut2', size=14425518, md5='0a7d5e59831485fd062e0f6374eff24f', mtime=1078277175, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-Primeval.ut2', size=9934490, md5='4309950fa32c54b295cdf7a99e0b3dc6', mtime=1078277177, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-RedPlanet.ut2', size=7355777, md5='cb83d4569c66db0d63e7accd3f78f579', mtime=1078277179, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-Severance.ut2', size=7710115, md5='0c56d9a44ba45c7a7744ab567f0a019a', mtime=1078277181, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ONS-Torlan.ut2', size=7501910, md5='663a7e84a2aa951644858a9c6c5fa353', mtime=1078277182, source_media=media_ut2004_cd1),
		manifest_file ('Maps/ParticleExamples.ut2', size=373276, md5='55d25a77c1ce4fcd295f6102ff081c5e', mtime=1078277182, source_media=media_ut2004_cd1),
		manifest_file ('Maps/TUT-BR.ut2', size=31894712, md5='81a29a808ffcaab116b009898cec3c89', mtime=1078277189, source_media=media_ut2004_cd1),
		manifest_file ('Maps/TUT-CTF.ut2', size=12173343, md5='7dbf9303cb8a684e154382c79a4e1491', mtime=1078277191, source_media=media_ut2004_cd1),
		manifest_file ('Maps/TUT-DM.ut2', size=11103922, md5='fa111869092394d03c2e8983a6f2af44', mtime=1078277194, source_media=media_ut2004_cd1),
		manifest_file ('Maps/TUT-DOM2.ut2', size=7333860, md5='a45ff349eb0342dbe7e76d4d38c04aa7', mtime=1078277196, source_media=media_ut2004_cd1),
		manifest_file ('Maps/TUT-ONS.ut2', size=11343777, md5='f0b932a8ae9ec415af77228cde7ab606', mtime=1078277198, source_media=media_ut2004_cd1),
		manifest_directory ('Sounds'),
		manifest_file ('Sounds/2K4MenuSounds.uax', size=238288, md5='d3a93bf30556e5c65caff8c1d0ae165d', mtime=1078277198, source_media=media_ut2004_cd1),
		manifest_file ('Sounds/AlienMaleTaunts.uax', size=1444403, md5='776a9dd24b21f356c7f762738ffa8173', mtime=1078277199, source_media=media_ut2004_cd1),
		manifest_file ('Sounds/Announcer.uax', size=1416927, md5='749572bc98d6b9a7aa8bb4c0e229cb37', mtime=1078277199, source_media=media_ut2004_cd1),
		manifest_file ('Sounds/AnnouncerAssault_DEMO.uax', size=8807217, md5='affc0d110e7255ff5469285a890c1b0b', mtime=1078277214, source_media=media_ut2004_cd1),
		manifest_file ('Sounds/AnnouncerClassic.uax', size=1417150, md5='d68acfed1ba6af7e1eea7e4e8337c0ac', mtime=1078277215, source_media=media_ut2004_cd1),
		manifest_file ('Sounds/AnnouncerEVIL.uax', size=6798690, md5='a7e6fdf7906a72329a570594f8d7a1a8', mtime=1078277216, source_media=media_ut2004_cd1),
		manifest_file ('Sounds/AnnouncerFemale.uax', size=9544500, md5='9cc7eebac7686f22369398f22a80e0e1', mtime=1078277218, source_media=media_ut2004_cd1),
		manifest_file ('Sounds/AnnouncerSEXY.uax', size=9699734, md5='616e3415089452dc89048597c6165bc0', mtime=1077798540, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/AssaultSounds.uax', size=1562743, md5='2dbefa1e4943cd66994e4d01cb6aaca8', mtime=1077798540, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/GameSounds.uax', size=1623973, md5='d336081f01c251b545eaab963b7a4134', mtime=1077798540, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/GeneralAmbience.uax', size=14429518, md5='ac809d06dc39b9243dc1a38c4a5a0314', mtime=1077798544, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/GeneralImpacts.uax', size=304550, md5='09f449b69200193d26bf9d4af652f8ba', mtime=1077798544, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/IndoorAmbience.uax', size=12014137, md5='189a61a198c8741ebccdf04137dd3b64', mtime=1077798546, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/IntroSounds.uax', size=60397044, md5='42b45af41196de57dad90ad2c9dc8a70', mtime=1077798558, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/IntroTrack.uax', size=9429880, md5='b8c8ae104fe04b8b9a9e24d8bf73442c', mtime=1077798560, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/JWDecemberSnd.uax', size=4696502, md5='e6512b6fc1772dff1e482d4a06821bd3', mtime=1077798562, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/Male2Voice.uax', size=701269, md5='a7427fd50ce5d3e9b256f2817c5e6401', mtime=1077798562, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/MenuSounds.uax', size=107651, md5='0685658712afc216dfa11bd7c4501f7b', mtime=1077798562, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/MercFemaleTaunts.uax', size=1106201, md5='66ee14a0e4eb242e89cc2fb8d5882296', mtime=1077798562, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/MercMaleTaunts.uax', size=2058947, md5='ab136cc185869852bbaf85cfdf4131f4', mtime=1077798562, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/NewDeath.uax', size=3655981, md5='7373b2b1dc3ee5b52454e5df8ca216a8', mtime=1077798564, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/NewWeaponSounds.uax', size=443065, md5='426358c5ca0ee5aba4a639fb1e65d4cf', mtime=1077798568, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/NvidiaLogoSounds.uax', size=3893914, md5='e6b1a11e5d0603d8699a01fe1f88c511', mtime=1077798570, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/ONSVehicleSounds-S.uax', size=17891158, md5='f324f3409f4d269f7f2177abf40e680d', mtime=1077798574, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/OutdoorAmbience.uax', size=18657973, md5='52791e4276cf04625b6b76053ee18fe9', mtime=1077798578, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/PickupSounds.uax', size=914721, md5='719ad9e2b52d60deb877b49de1957735', mtime=1077798578, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/PlayerFootSteps.uax', size=50069, md5='dad454b226faa55625a32a930bf3364c', mtime=1077798578, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/PlayerSounds.uax', size=3013514, md5='8c9b15762b44da77792d9515b6a0f3b0', mtime=1077798578, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/SlaughterSounds.uax', size=3028157, md5='d48dc4beeaf9f83f8f3240911597a4ac', mtime=1077798580, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/TestCarS.uax', size=88039, md5='21884a861f48ee26c7bcbe4680c5c7b0', mtime=1077798582, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/VMGeneralSounds-S.uax', size=397572, md5='b19c06e618d94577aa4e082d4d084e19', mtime=1077798586, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/VMVehicleSounds-S.uax', size=430787, md5='0e09c1c4e535b856e95332c3c30d381b', mtime=1077798586, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/WeaponSounds.uax', size=7347042, md5='18a19eed7925fb6ed636d1f3f92e29dd', mtime=1077798588, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/wm_sounds.uax', size=348181, md5='5f9991a7b24f88c66dc537d1af81744b', mtime=1077798588, source_media=media_ut2004_cd2),

		manifest_directory ('Textures'),
		manifest_file ('Textures/2K4Chargers.utx', size=350415, md5='c37fb260284ee93248edb7b3b69f1611', mtime=1077798588, source_media=media_ut2004_cd2),
		manifest_file ('Textures/2K4Fonts.utx', size=3260571, md5='43023832582fafab42ec5ff2f847962a', mtime=1077798590, source_media=media_ut2004_cd2),

		# Both CD1 and CD2 have files with this name,
		# and they do not match.
		#manifest_file ('Textures/2k4Fonts_kot.utx', size=17124185, md5='deecc7468dc80f128da207fab32979c6', mtime=1078277290, source_media=media_ut2004_cd1),
		#manifest_file ('Textures/2K4Fonts_kot.utx', size=17100579, md5='ac4f705a279170fde9bf40714474cdfc', mtime=1077798592, source_media=media_ut2004_cd2),

		manifest_file ('Textures/2K4Hud.utx', size=2105210, md5='0a0fe412aec13df898c2a4343a5c96b5', mtime=1077798592, source_media=media_ut2004_cd2),
		manifest_file ('Textures/2K4Menus.utx', size=22949937, md5='afe8f56ef3fe5a7cbe480c26d6e4a2f2', mtime=1077798598, source_media=media_ut2004_cd2),
		manifest_file ('Textures/2K4reducedTEXTURES.utx', size=2564992, md5='80f04c55a0f718a68ee161c2922c6a50', mtime=1077798598, source_media=media_ut2004_cd2),
		manifest_file ('Textures/2K4TrophyTEX.utx', size=5681126, md5='3475b27b7b899b35dd7c93a3a14fef03', mtime=1077798600, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AbaddonArchitecture-epic.utx', size=15180003, md5='5b39d0522a88e0ade733cb8371624942', mtime=1077798602, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AbaddonArchitecture.utx', size=45949043, md5='151e5401a9fcb33b9e3dd6e01db09d25', mtime=1077798614, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AbaddonHardwareBrush.utx', size=20129226, md5='6825e02fef21bbb3709e1a46be5bd78b', mtime=1077798618, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AbaddonTerrain.utx', size=6470595, md5='d65c1b024ac8867d094955749e4c5cef', mtime=1077798618, source_media=media_ut2004_cd2),
		manifest_file ('Textures/Albatross_architecture.utx', size=9723103, md5='800df00ed1f50da7523e5eb7373a2729', mtime=1077798622, source_media=media_ut2004_cd2),
		manifest_file ('Textures/ALIENTEX.utx', size=6052987, md5='ea631f039a4c890552ddbf80d6d21d19', mtime=1077798624, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AlleriaArchitecture.utx', size=84549819, md5='f3ae8880abe03bd4d5b8ca507ac11335', mtime=1077798638, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AlleriaHardwareBrush.utx', size=32768171, md5='4405a504e9dc5019164ea3f8e24b63d1', mtime=1077798644, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AlleriaTerrain.utx', size=28670068, md5='34b40156b3f03caaa8f27916d4be16ee', mtime=1077798650, source_media=media_ut2004_cd2),
		manifest_file ('Textures/Animated.utx', size=64, md5='4049e1e7c46b104f791267efdd4e6ad2', mtime=1077798650, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AntalusTextures.utx', size=7713172, md5='9d5fa0f3f845fd8ea1e844c447f86b3f', mtime=1077798652, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AnubisSky.utx', size=4196138, md5='312bbb9d7dc9a8bbbfd80292c38c0cc9', mtime=1077798652, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AnubisTextures.utx', size=2797759, md5='9d05aa6c683f318818d73800444e0a1f', mtime=1077798652, source_media=media_ut2004_cd2),
		manifest_file ('Textures/ArboreaArchitecture.utx', size=31919044, md5='4f103f045637e20e80f66a71a55058bb', mtime=1077798658, source_media=media_ut2004_cd2),
		manifest_file ('Textures/ArboreaHardwareBrush.utx', size=6010632, md5='6152c4a8b1ba6ba6c9af4b6b83595393', mtime=1077798660, source_media=media_ut2004_cd2),
		manifest_file ('Textures/ArboreaTerrain.utx', size=18372641, md5='2bed3992602c623d6d2a6f10a5a5df58', mtime=1077798662, source_media=media_ut2004_cd2),
		manifest_file ('Textures/ArenaTex.utx', size=2443722, md5='404a341ee4dc71b79d6e885f39706749', mtime=1077798662, source_media=media_ut2004_cd2),
		manifest_file ('Textures/ASSAULTfilmGrain.utx', size=351179, md5='fe4f10ef48d8280a95301774e26f6166', mtime=1077798662, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AS_FX_TX.utx', size=1967814, md5='34f4cf3b29ca61d5869824e84466ed74', mtime=1077798664, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AS_Vehicles_TX.utx', size=10775517, md5='27133660a5d76f08a0627e940af78e13', mtime=1077798666, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AS_Weapons_TX.utx', size=19494671, md5='5bb3981cde772c461a407bc49c6e66ab', mtime=1077798672, source_media=media_ut2004_cd2),
		manifest_file ('Textures/Aurorae.utx', size=350843, md5='f4a4747b0c3d08844c6e72af28c75326', mtime=1077798672, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-2004Explosions.utx', size=2478004, md5='b503c82bb295d8c5abc8ffbfde3ec028', mtime=1077798674, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-2004Particles.utx', size=8643670, md5='c3219a112d492dc848a4d9488601b58c', mtime=1077798674, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-2004Shaders.utx', size=2286899, md5='761964bcd399c91b1eb7398789e9e54a', mtime=1077798674, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Alleria.utx', size=351164, md5='9f37ccc000cfd146b58a98fa22e1cdf2', mtime=1077798674, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Ancient.utx', size=875569, md5='eee5a85624adafa9670ab8d60b6a4f27', mtime=1077798676, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-BumpMaps.utx', size=5362915, md5='de5f9522e7997797795fbf2967a65622', mtime=1077798676, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-CellTest.utx', size=2262, md5='26e0a283b001551b7f794bacc4151b0f', mtime=1077798676, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-CityStuff.utx', size=3235259, md5='c576b003fc260b8edfae646b2776cdf1', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Clean.utx', size=355031, md5='260ab7ce1e4b83b89ddb24a1eb423f52', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Convert.utx', size=440009, md5='0e9be8c46053a1f70f3a3af025fa939c', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Cubes.utx', size=1294181, md5='46f1cb4e2901c74e678e50b1ead76ede', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Decals.utx', size=1369486, md5='e06330ea4462916ecb37296a1f9d3eb1', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Foliage.utx', size=3501159, md5='7c3951d7398eaac378ea2bfc3c09f488', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Generic.utx', size=188666, md5='e8510c62f31fa6b9c8755adb06492601', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Genesis.utx', size=1399781, md5='ae5298d7635a0c183336da4542503102', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Labels.utx', size=23479, md5='007d818cf51fe34528f32ac8e4d1c13e', mtime=1077798678, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Metals.utx', size=9538130, md5='bbc1bfbc5ae6f05e14e323624b12c64c', mtime=1077798680, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Metals2.utx', size=541, md5='3c5c499b84c2f7169ab92da38b21a5f2', mtime=1077798680, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Oceanic.utx', size=3604994, md5='32c7c005e7966e66537a1cbbc25af71c', mtime=1077798682, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-PoolSkins.utx', size=22742962, md5='7e39e1d1566703f2aa2a9406020e7368', mtime=1077798684, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-RustTex.utx', size=10796623, md5='61d780df7226120357fdee29fbf5f1b8', mtime=1077798686, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Shaders.utx', size=3417102, md5='e42c8dbf41723d59dd1a2a902a45a413', mtime=1077798688, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-ShieldShaders.utx', size=413285, md5='a30c185fa6c61f0eb48b70655b8ee394', mtime=1077798688, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Stone.utx', size=2362486, md5='0e7073275841d8d1bc4cf9020212ce9b', mtime=1077798688, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Stuff.utx', size=887592, md5='ea683434f506631c048fbae160520b26', mtime=1077798688, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW-Terrain.utx', size=3892316, md5='26c4c16ff706ec7c9b7230e8a7af443e', mtime=1077798688, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AWCity.utx', size=7702487, md5='18d90866d153f40611a8f653f203a10c', mtime=1077798690, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AWGlobal.utx', size=15750153, md5='9c8e77fa44d0000864fd57080588c3cc', mtime=1077798694, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AWMagic.utx', size=529394, md5='8c8dcb63cebb5d194eb8db85b369e997', mtime=1077798694, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AWStellar.utx', size=350114, md5='e0fd678937acf3a15fcd276d9ce40cdf', mtime=1077798694, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AWTroff.utx', size=1275702, md5='96d79ec23da1b6b6bc2e25f674b342d3', mtime=1077798694, source_media=media_ut2004_cd2),
		manifest_file ('Textures/AW_Research.utx', size=482408, md5='8b5fc227d97b486ec4f2d370a73ccf51', mtime=1077798694, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BaneTextures.utx', size=334894, md5='36352225047b7ddd45f37b37b4867e1e', mtime=1077798694, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BarrenHardwareDeux.utx', size=175428, md5='79fe1a56c2c25962230eb4ad6a2d7a9b', mtime=1077798694, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BarrensArchitecture-epic.utx', size=6110690, md5='da226a1941d4133acea8dba911878b7b', mtime=1077798696, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BarrensArchitecture-Scion.utx', size=12591040, md5='ab73b6d7f72cd8a49985bfac19c87b86', mtime=1077798698, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BarrensArchitecture.utx', size=32400298, md5='1daa10a3a341901f26b4a1fd0e691199', mtime=1077798704, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BarrensHardwareBrush.utx', size=132169, md5='70e207a3fcb770cc35ce41d3ab120cda', mtime=1077798704, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BarrensTerrain.utx', size=17134329, md5='2a4ca5c1a8c8df0660cf87d68b5d63fb', mtime=1077798708, source_media=media_ut2004_cd2),
		manifest_file ('Textures/Bastien.utx', size=2288079, md5='36ddb661418f8bc25cd2157c777f66e7', mtime=1077798708, source_media=media_ut2004_cd2),
		manifest_file ('Textures/Bastien_02.utx', size=2104148, md5='f01bbefd697480d0dbeb4b24cc8b968d', mtime=1077798710, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BenTex01.utx', size=8551188, md5='31f0041e0f9f6edfe70cc0be597044e5', mtime=1077798712, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BloodFX.utx', size=193703, md5='e99b79ab663cc2fd110146810c3360f9', mtime=1077798712, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BP_arch1.utx', size=10762499, md5='8e6a0b78294a7bde8af98807809c91ba', mtime=1077798714, source_media=media_ut2004_cd2),
		manifest_file ('Textures/Brdg_A.utx', size=724483, md5='6b0b8e00bbc948156e70b0ad93e2fe53', mtime=1077798714, source_media=media_ut2004_cd2),
		manifest_file ('Textures/Bridge.utx', size=112057, md5='d654c6c8cb0c743c0d18e711426b5b57', mtime=1077798714, source_media=media_ut2004_cd2),
		manifest_file ('Textures/BrightPlayerSkins.utx', size=40561289, md5='a8acbc047a5d37717c067af80e60ea36', mtime=1077798724, source_media=media_ut2004_cd2),
		manifest_file ('Textures/cassTextures2.utx', size=47913190, md5='033d8db616e9af086f4ddbd06c74761c', mtime=1077798732, source_media=media_ut2004_cd2),
		manifest_file ('Textures/CaveDecoTex.utx', size=1056089, md5='955c15a6fb9ab7a99276a80a30e8d1cb', mtime=1077798732, source_media=media_ut2004_cd2),
		manifest_file ('Textures/CavernTextures.utx', size=8110436, md5='cf6dc8d04b15405cfbf4532ce30d3bcd', mtime=1077798734, source_media=media_ut2004_cd2),
		manifest_file ('Textures/CB-Particles.utx', size=771425, md5='2b7f09d7ba4c77b6042ef516d7e8d23c', mtime=1077798734, source_media=media_ut2004_cd2),
		manifest_file ('Textures/cf1.utx', size=17337095, md5='78df366e764e8353271ea69634cc4eb0', mtime=1077798738, source_media=media_ut2004_cd2),
		manifest_file ('Textures/cf2.utx', size=900900, md5='ceaaa312985c1421f28bcb7f8f5b7bf7', mtime=1077798738, source_media=media_ut2004_cd2),
		manifest_file ('Textures/cf_mushrooms.utx', size=135341, md5='e9fc5a9a268768898067e78e97d1b3c7', mtime=1077798738, source_media=media_ut2004_cd2),
		manifest_file ('Textures/cf_tex01.utx', size=10961999, md5='000895d8baf7d6a605fcf26c64aaf0d6', mtime=1077798738, source_media=media_ut2004_cd2),
		manifest_file ('Textures/cf_tex02.utx', size=22406036, md5='ad51bf88066b393cca06ff600e95df40', mtime=1077798741, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cf_tex03.utx', size=350283, md5='c0bd53ecfbac6dcb3f6468f911cf885e', mtime=1077798741, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CheckerFX.utx', size=9226074, md5='d29fbf1059ffb471cc01d519414c32ef', mtime=1077798744, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CheckerFXB.utx', size=3061122, md5='e4a1f434687a0fe0663f77dba80e6194', mtime=1077798744, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Chrome_cp.utx', size=4549272, md5='a351333f3d17d3ae5e47a6743b911f0c', mtime=1077798745, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CitadelTextures.utx', size=6003288, md5='8987a1341fc9bf4b72737e6013d57789', mtime=1077798746, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CliffTest.utx', size=2079579, md5='9f5768f487f0cf08ac645f222358ae0c', mtime=1077798747, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Compress.utx', size=2034165, md5='eb46069a70b1936c5f95543088a44834', mtime=1077798747, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Coronas.utx', size=88955, md5='2cc9944f0af43b743ca33c3e56be3dd9', mtime=1077798747, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CorrosionTextures.utx', size=833929, md5='5f4b2a4321db7d1c593b7ca6efd36653', mtime=1077798747, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_cubemaps.utx', size=373544, md5='d95d02ef130131e0060a0dd9e5f03f85', mtime=1077798747, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CP_Effects1.utx', size=88170, md5='9cd11d9b25e9d16b847039403b1d630e', mtime=1077798747, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_envirotex1.utx', size=64, md5='f84cc3b085fa9f8f8375634af2baad01', mtime=1077798747, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_Evil2.utx', size=1269381, md5='dedaedacc37a93a5633383fcfd5cade6', mtime=1077798748, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_Evil3.utx', size=6919438, md5='4cf5eaefaba0e79f57b4b8011245fa38', mtime=1077798749, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_Evillandscape.utx', size=88143, md5='56fdc2f8e69b1645b09dbe7d0383cd1c', mtime=1077798749, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_Evilmetal.utx', size=351148, md5='b798be243f06def4f581f35100a2d4f3', mtime=1077798749, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_Forestswamp.utx', size=16797399, md5='399df147d15afb3d072537473855b9fe', mtime=1077798753, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_fx.utx', size=276471, md5='4b75221a791b42539f86edbd2536b2a2', mtime=1077798753, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_Junkyard.utx', size=8568517, md5='b37c50a93b0193e170e2963d1e4fddeb', mtime=1077798755, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_liquid1.utx', size=64, md5='b462c923d17169ac65b3340e36ba2471', mtime=1077798755, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_Mech1.utx', size=2275941, md5='6291f86f44defb26f8340428544f77ca', mtime=1077798755, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_misc_effects.utx', size=9964, md5='e17d716b5b02e6a4a8f16aa4b4fdc3af', mtime=1077798755, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_newskins1.utx', size=2099220, md5='c0ebe7ca5ae6de954a84db95a62c466a', mtime=1077798756, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_particles.utx', size=22443, md5='d752383755734b8f2dcfa3cb90b6b28e', mtime=1077798756, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_projectedtex.utx', size=4303592, md5='3375426589e8ebecd1692b46b04b4ed9', mtime=1077798756, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_projected_new.utx', size=2110162, md5='938a92ab70b2a96e7dea0401664afa2d', mtime=1077798756, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_staticmeshskin1.utx', size=7940350, md5='37e840741d5ed7846cb306b1ba22491c', mtime=1077798758, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_stevetest1.utx', size=64, md5='71045d7e90a3203bc87fab1ce2d4783b', mtime=1077798758, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_terrain1.utx', size=351261, md5='e08464cfae5323202ad5420f6bd08cea', mtime=1077798758, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_texturetest1.utx', size=87984, md5='83fbd9a2cc99c468469699878567cb40', mtime=1077798758, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CP_UT2K3_TechSet1.utx', size=5337025, md5='c52f3629fb68704ec2267bd3eaa1f035', mtime=1077798759, source_media=media_ut2004_cd3),
		manifest_file ('Textures/cp_wasteland.utx', size=24356406, md5='7a916fed96945f18ec571164a4bba8b2', mtime=1077798763, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Crosshairs.utx', size=80100, md5='c4f024d2ab3c8a1880b422a723b21e40', mtime=1077798763, source_media=media_ut2004_cd3),
		manifest_file ('Textures/CubeMaps.utx', size=9766503, md5='26f80330b30174afedbec985cf4f7b6e', mtime=1077798765, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DanFX.utx', size=6297533, md5='f0c0d89f388bcb8206226e5296fb77da', mtime=1077798766, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DanielsTextures.utx', size=3158031, md5='c52ad97d834f7b7105e8366c9b3d4929', mtime=1077798767, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DavesTextures.utx', size=26454550, md5='3727b944442c19e97969f5e6bc026ade', mtime=1077798771, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DEBonusTextures.utx', size=15255575, md5='383150930fe1e17f917e2d57a3300494', mtime=1077798773, source_media=media_ut2004_cd3),
		manifest_file ('Textures/December_cp.utx', size=5858850, md5='0a5ef53a1161beea707293bf9c576560', mtime=1077798775, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DecorationProjectors.utx', size=655965, md5='7c9a02c60298849f69604912176a4e96', mtime=1077798775, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DefaultFluid.utx', size=527942, md5='5afebadb06e5eab71cfb10f1b8f4c5f3', mtime=1077798775, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DemoPlayerSkins.utx', size=11584378, md5='0304a1347b1ac793adff371d1eeb0968', mtime=1077798778, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DeployableTex.utx', size=88369, md5='c83f7c50c69e71da8918fde6eeba693c', mtime=1077798778, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DeRez.utx', size=264570, md5='180b2ce5b5faed2399a861603dbc1bc8', mtime=1077798778, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DespFallenCity.utx', size=18192360, md5='00aeff077b6149c7288b80b417969e24', mtime=1077798783, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DespTech.utx', size=42578329, md5='23506f1a1a4f5b5ac79e9ae893f1e33d', mtime=1077798790, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Desp_SMS-Tex.utx', size=40110210, md5='c33aa422eb1c46555021dd1a30c6d21c', mtime=1077798799, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Detail.utx', size=1731042, md5='20444b0113878c7e32da9c6e9865da5a', mtime=1077798799, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Dom-goose.utx', size=13548287, md5='fdab7ca8b4cbb2674e3a537d8ce45c1e', mtime=1077798801, source_media=media_ut2004_cd3),
		manifest_file ('Textures/DS-textures.utx', size=699658, md5='458e5632dad7c3243a409caa96546dc1', mtime=1077798802, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Egypt_tech_Epic.utx', size=7313290, md5='3c05cc1e7228f0456deedd36c8523b22', mtime=1077798803, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Elecfeildsshine.utx', size=1556794, md5='faf316deeb89d2855608ea10db41d69c', mtime=1077798803, source_media=media_ut2004_cd3),
		manifest_file ('Textures/EmitterTextures.utx', size=1921553, md5='eb1aa3ebe99403008fd3eb27744ff69e', mtime=1077798803, source_media=media_ut2004_cd3),
		manifest_file ('Textures/EmitterTextures2.utx', size=721770, md5='5091648f63a8d7e76a140e3d1268c918', mtime=1077798804, source_media=media_ut2004_cd3),
		manifest_file ('Textures/EndTextures.utx', size=6643112, md5='80b4b6e1cb5c5e584e5ddb5746af4ded', mtime=1077798805, source_media=media_ut2004_cd3),
		manifest_file ('Textures/EpicParticles.utx', size=4879626, md5='7d02876e648afe0d6b5a8e9102012ac4', mtime=1077798806, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Epic_Phoboswing.utx', size=1936351, md5='20b2ee31459497d6575ceae5a5a71a38', mtime=1077798806, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ExitScreen.utx', size=703393, md5='69b897582490e3dfb2bb7f5fb16c5886', mtime=1077798807, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ExitScreenNoLogo.utx', size=791303, md5='56d81ca5373a1e2cdece6bf51a78e39d', mtime=1077798807, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ExplosionTex.utx', size=1596694, md5='5a5b9b701cbdcd353c1bd32eaf726ab6', mtime=1077798807, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Face3_deco.utx', size=1050150, md5='d640c4f793b1a91c25c6eb13f9d0592c', mtime=1077798808, source_media=media_ut2004_cd3),
		manifest_file ('Textures/FarEast.utx', size=61249340, md5='d2c831f3e8262713ed08932ec034f187', mtime=1077798818, source_media=media_ut2004_cd3),
		manifest_file ('Textures/FireEngine.utx', size=8980870, md5='d94808aa38bf2e4fc8a3970881df0e8a', mtime=1077798819, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Foliage.utx', size=350254, md5='ab51422c3cc06e1c117f7e71a808c82a', mtime=1077798819, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Fortress.utx', size=534944, md5='c06bf34f7dfc56dfbf2f599b4aaa3a8a', mtime=1077798820, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Futuretech1.utx', size=1489582, md5='41eaef7f7266c9fda8bbe00b245bd8e4', mtime=1077798820, source_media=media_ut2004_cd3),
		manifest_file ('Textures/GeneralStaticTextures.utx', size=2100113, md5='f92dc94c6210176cbcfe04758a5ef10d', mtime=1077798820, source_media=media_ut2004_cd3),
		manifest_file ('Textures/GeoThermalTextures.utx', size=5476718, md5='8118b45749c3b8f4e8fec98d362945ac', mtime=1077798822, source_media=media_ut2004_cd3),
		manifest_file ('Textures/GlacierTextures.utx', size=13685334, md5='1fc0d70e198ae3efc545e835e198ba2d', mtime=1077798825, source_media=media_ut2004_cd3),
		manifest_file ('Textures/GoldCubes.utx', size=64, md5='e6afa8ac4cb7a07650a90e27e3820177', mtime=1077798825, source_media=media_ut2004_cd3),
		manifest_file ('Textures/gooseFX.utx', size=90246, md5='b11c5bcd5c51b25ee669ca5b164966d8', mtime=1077798825, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Grendelfix.utx', size=44259, md5='46a2f313bf3e737889b8339b901fd50a', mtime=1077798825, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Gwotseffects.utx', size=2845155, md5='5cc1c9b8ab5c70fdb381c8259cb4f4e0', mtime=1077798825, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Gwotstuff.utx', size=89379, md5='e55ca0b73a455b092fa3314795f75855', mtime=1077798825, source_media=media_ut2004_cd3),
		manifest_file ('Textures/HourMoria.utx', size=5948982, md5='709c13431b6f92fa21eb930f3e9c0d0b', mtime=1077798826, source_media=media_ut2004_cd3),
		manifest_file ('Textures/HudContent.utx', size=790796, md5='de416098c9166aa49f1c62505ccb529e', mtime=1077798826, source_media=media_ut2004_cd3),
		manifest_file ('Textures/HumanoidArchitecture.utx', size=74573365, md5='54fd0454b83a77450600455f2b0a4ed1', mtime=1077798840, source_media=media_ut2004_cd3),
		manifest_file ('Textures/HumanoidArchitecture2.utx', size=7868046, md5='2497e039b8361a0c67f50a9b9e280e90', mtime=1077798842, source_media=media_ut2004_cd3),
		manifest_file ('Textures/HumanoidHardwareBrush.utx', size=32881466, md5='52bf5cf773f4dafc1a3865514b399698', mtime=1077798847, source_media=media_ut2004_cd3),
		manifest_file ('Textures/H_E_L_Ltx.utx', size=49506442, md5='1ddb9e90e1dc1f9def7deb6de87e6916', mtime=1077798857, source_media=media_ut2004_cd3),
		manifest_file ('Textures/IllumShaders.utx', size=176785, md5='a0ad835c6825dc8359fb9215116d0283', mtime=1077798857, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Imulsive.utx', size=441263, md5='c305918f8d890a57207ba2a0740d37c9', mtime=1077798857, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Industrial.utx', size=9357098, md5='e611d4c44c0370a13df132735c08968e', mtime=1077798859, source_media=media_ut2004_cd3),
		manifest_file ('Textures/InstagibEffects.utx', size=406, md5='2ad9a3d75051d08aca7e2881b16750c0', mtime=1077798859, source_media=media_ut2004_cd3),
		manifest_file ('Textures/InterfaceContent.utx', size=4833720, md5='9689ad715bf16bda9638eb877f16dd01', mtime=1077798860, source_media=media_ut2004_cd3),
		manifest_file ('Textures/intro_characters.utx', size=24215390, md5='466d67873cb11aedff3f1fa4dda439d5', mtime=1077798864, source_media=media_ut2004_cd3),
		manifest_file ('Textures/JamesEffects.utx', size=88018, md5='b2fc0c088eb70fd663186825bb38c6e4', mtime=1077798864, source_media=media_ut2004_cd3),
		manifest_file ('Textures/jm-particl2.utx', size=197505, md5='b77d929a1bbd1d3763ba10f9244f0abe', mtime=1077798864, source_media=media_ut2004_cd3),
		manifest_file ('Textures/jm-particles.utx', size=197081, md5='5d3cd5f6717c442ef79a982c44bba6c8', mtime=1077798864, source_media=media_ut2004_cd3),
		manifest_file ('Textures/jm-prefabs.utx', size=1573929, md5='7b0aa146eebfc97cd2c34c25d9f4f632', mtime=1077798864, source_media=media_ut2004_cd3),
		manifest_file ('Textures/jm-prefabs2.utx', size=8133620, md5='9a3fb037e7e98033a8af435908c817f2', mtime=1077798866, source_media=media_ut2004_cd3),
		manifest_file ('Textures/jm_manhatten_project.utx', size=48436, md5='14998afdc3143fb9e7aaa4e302113b83', mtime=1077798866, source_media=media_ut2004_cd3),
		manifest_file ('Textures/jwDecemberArchitecture.utx', size=4279497, md5='7978a57322d3c927ecb989a572321d43', mtime=1077798867, source_media=media_ut2004_cd3),
		manifest_file ('Textures/jw_jantex.utx', size=5943526, md5='cb82e1585d7bc70162c0e7aa41eae358', mtime=1077798868, source_media=media_ut2004_cd3),
		manifest_file ('Textures/LadderShots.utx', size=12585893, md5='4c20495e33e5e9fbc56ea9a227968009', mtime=1077798870, source_media=media_ut2004_cd3),
		manifest_file ('Textures/LastManStanding.utx', size=44218, md5='146a1f0d8ab8cb67dab7d5d56dbc86b1', mtime=1077798870, source_media=media_ut2004_cd3),
		manifest_file ('Textures/LavaMLFX.utx', size=1749565, md5='cbfce1d584bf85db88c72bad006df16a', mtime=1077798870, source_media=media_ut2004_cd3),
		manifest_file ('Textures/lavaskyX.utx', size=45662939, md5='cafe3167846597805a7471591805b161', mtime=1077798877, source_media=media_ut2004_cd3),
		manifest_file ('Textures/LeathamFX.utx', size=1226117, md5='4fe4f36c0f671a703f9dbd4563225b83', mtime=1077798877, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Lev_Particles.utx', size=860012, md5='0f45affe6c43bb1a79f6f24cb3aac0b6', mtime=1077798877, source_media=media_ut2004_cd3),
		manifest_file ('Textures/LightningCoreTex.utx', size=132498, md5='babad90c3d689508191c331708c3cd7c', mtime=1077798877, source_media=media_ut2004_cd3),
		manifest_file ('Textures/lp_scene_1_t.utx', size=350382, md5='aace6b0470aba0255e9eb0bb08a8517c', mtime=1077798877, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Malcom_scene3_textures.utx', size=7191529, md5='946dc04f864528cb186051dc75795ac6', mtime=1077798879, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MapThumbnails.utx', size=7877590, md5='fa51060a6de1477c5ae69363b5d9c3b3', mtime=1077798880, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Mechcity1_CP.utx', size=1399040, md5='2e5f32cee468fa1bd715508a6123c7ff', mtime=1077798881, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MechStandard.utx', size=881772, md5='e8e757d4dd2c02e4b592c2cda040c24b', mtime=1077798881, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Mech_decayed.utx', size=2933463, md5='5a41fb1a05eed902edcde46fddf9cb41', mtime=1077798881, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Mech_Decay_New.utx', size=1532350, md5='863c4bec5aa51871c57888e97b4d8bcd', mtime=1077798882, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MenuEffects.utx', size=189869, md5='7fa385ddf7274b9fbaa42d418986cb14', mtime=1077798882, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MikeDemoLevel.utx', size=9714886, md5='8537b2457a656381ca50685dbc85662c', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MiscEpicTex01.utx', size=2819679, md5='70bf7b2940adf3d491a8c36db28d4833', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MiscPhysicsMeshesTex.utx', size=64, md5='9fc4b2f16ad12ede6ed66d55b0680bcf', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MutantSkins.utx', size=373182, md5='41371626977e1dd0e9613734fe52eed5', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/MutatorArt.utx', size=110706, md5='b3bc47bb04256b987d0e5a127c73aee4', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/NaThCrossfire.utx', size=898480, md5='7b1d7b61b46aea1f4e267d48259bd3f9', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/NatureFX.utx', size=179696, md5='f153fcf37f4345e4c54c416d27f7b124', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/NatureOne.utx', size=396236, md5='5f53d41ff7b0207c65a888a42b0770fb', mtime=1077798884, source_media=media_ut2004_cd3),
		manifest_file ('Textures/newsniperrifle.utx', size=3234702, md5='e5e1f182471e13fe2e74a8cf23fe26a0', mtime=1077798885, source_media=media_ut2004_cd3),
		manifest_file ('Textures/NormalMaps.utx', size=701998, md5='5201f83c276c3d2304a691cbd5fba8a7', mtime=1077798885, source_media=media_ut2004_cd3),
		manifest_file ('Textures/November2ship.utx', size=2472677, md5='cf9859c88458b9c33af7f4d48095d560', mtime=1077798886, source_media=media_ut2004_cd3),
		manifest_file ('Textures/NvidiaLogo_T.utx', size=6078243, md5='38f83fd6edccb2ccb8cafbd5413d3da9', mtime=1077798887, source_media=media_ut2004_cd3),
		manifest_file ('Textures/n_StaticMeshFX_T_SC.utx', size=1419888, md5='fae4443632f0afa4b7690d8c9b498a38', mtime=1077798887, source_media=media_ut2004_cd3),
		manifest_file ('Textures/OldTreeSkins.utx', size=489986, md5='0f656f8544bd94103cd09994af897dab', mtime=1077798887, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ONSDeadVehicles-TX.utx', size=6337439, md5='ebd58e6ded216dd3e65e5a10551c3dd3', mtime=1077798889, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ONSFullTextures.utx', size=8610798, md5='08748ee4009e55bef86e07056de98ebe', mtime=1077798891, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ONSInterface-TX.utx', size=273994, md5='72251c1086e09f3fce72fb7c50c47b37', mtime=1077798891, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ONSstructureTextures.utx', size=5034031, md5='957a4f26cccb20aa89bdf8a3a6df7fac', mtime=1077798892, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ONSTorlanREDONE.utx', size=4196407, md5='a2da920840fdfceb197bf9681c168397', mtime=1077798893, source_media=media_ut2004_cd3),
		manifest_file ('Textures/OtherWorld.utx', size=4623061, md5='af0fb83da305121ad9888e4b7ffea75d', mtime=1077798894, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Palettes.utx', size=426810, md5='a65c3c09fe0e20467b934b2d5d0bd357', mtime=1077798894, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Particles.utx', size=466840, md5='e7a1413e09a665080b13df4c2c4f4591', mtime=1077798894, source_media=media_ut2004_cd3),
		manifest_file ('Textures/PC_ConvoyTextures.utx', size=20579084, md5='4035207f9044795d4356c4721b3bafcd', mtime=1077798899, source_media=media_ut2004_cd3),
		manifest_file ('Textures/PC_NewWeaponFX.utx', size=384041, md5='e89bcf22c9353bbe18e36990bf3943d2', mtime=1077798899, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Phobos2_cp.utx', size=12507551, md5='6ecb3e53e794e706cc744abfacf0eeec', mtime=1077798901, source_media=media_ut2004_cd3),
		manifest_file ('Textures/PickupSkins.utx', size=739485, md5='2828ccce77a5695762506ff1f05183ac', mtime=1077798901, source_media=media_ut2004_cd3),
		manifest_file ('Textures/PipeTextures.utx', size=7082335, md5='484fc1e05321413bdbc615fde6d40453', mtime=1077798903, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Pipe_Set.utx', size=17386217, md5='1b9596713274c2111296bb87048a59f0', mtime=1077798906, source_media=media_ut2004_cd3),
		manifest_file ('Textures/PlayerPictures.utx', size=19606530, md5='39237145386806415001cf03e7ee1758', mtime=1077798909, source_media=media_ut2004_cd3),
		manifest_file ('Textures/PlayerSkins.utx', size=109093914, md5='40d7c6649855b7f3aedc9b113af6b72e', mtime=1077798930, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Plutonic_BP2_textures.utx', size=13358453, md5='236a27c5761d8b844b3a70ef38e2b06e', mtime=1077798933, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Plutonic_Robot_TX.utx', size=3672310, md5='e54e1c4bd46f28be32c19f253587a67b', mtime=1077798933, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Primeval_Tex.utx', size=2103618, md5='1b9ca867ab4914e6a780103554a94343', mtime=1077798934, source_media=media_ut2004_cd3),
		manifest_file ('Textures/PSDria.utx', size=5508478, md5='c00179e61ede5f28192daf01adc2011a', mtime=1077798935, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Rimlight.utx', size=265383, md5='339ef68e6486545b4e5c2aaa93d1a341', mtime=1077798935, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC-City.utx', size=437736, md5='02faf536af490bcdd2da12e7ec402819', mtime=1077798935, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_Animated.utx', size=345917, md5='2c87051a1f8e8ffb21ce5775bfe031e1', mtime=1077798935, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_BuggyTest.utx', size=7344659, md5='dc4768357c3bbc367a7ee6be5ab119cd', mtime=1077798937, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_Froth.utx', size=7194022, md5='190520e6470ea58875e0a5b9b6e0fb3c', mtime=1077798938, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_GDC.utx', size=27288279, md5='82bfd40f91197001aff053d5074ca455', mtime=1077798942, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_GDC_FX.utx', size=2821069, md5='aa9c13f64d38759be29b8773d37bf922', mtime=1077798942, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_Intro.utx', size=48239398, md5='c8a8e85fe9984172de27622a893c39c1', mtime=1077798960, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_Jungle.utx', size=2449906, md5='a3d5f568a0452c8266e58e394df30c65', mtime=1077798960, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_MeshParticleTex.utx', size=158263, md5='91eb321ccf3a073abb09776d699e7ea2', mtime=1077798961, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_Volcano_T.utx', size=23749648, md5='f7db81a5442cd342320ea313fc87a204', mtime=1077798965, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SC_Water.utx', size=6794707, md5='814669143fa13b4cca65e0bbb8697b42', mtime=1077798967, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SD-Generic.utx', size=1862054, md5='255e9e7a860929c67c7de47ed21d1678', mtime=1077798967, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ServerIcons.utx', size=10709, md5='d61059618aa96cac9a71a383bc803b77', mtime=1077798967, source_media=media_ut2004_cd3),
		manifest_file ('Textures/sg-Mech.utx', size=175371, md5='00a08b05bb2d04dbbdefc39f5ede7ef9', mtime=1077798967, source_media=media_ut2004_cd3),
		manifest_file ('Textures/sg_floorsandgrates_alpha.utx', size=700110, md5='53484a2b16c3984dc04fb2ff6c7dd0ee', mtime=1077798967, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SG_Giest_redset.utx', size=7719579, md5='37d563954a2042efe4ae9c44cf5005df', mtime=1077798969, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SG_Hud.utx', size=1545922, md5='0b66c04eb277ada6127709ac5e4eb386', mtime=1077798969, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SG_Lost_Outpost.utx', size=12768573, md5='95b5df6715fd29be82fe6fcb739e08cb', mtime=1077798972, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SG_Special_Decos.utx', size=2363805, md5='7522353694bba12332e9ba01325b4b95', mtime=1077798972, source_media=media_ut2004_cd3),
		manifest_file ('Textures/sg_UT2003_Jumpboots.utx', size=351754, md5='6db07b338f88ad49d5a7c4e217784c19', mtime=1077798972, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ShaneDay.utx', size=388794, md5='42781db56a525d79e7de72f6b326f7e2', mtime=1077798972, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ShaneDemoHead.utx', size=64, md5='5b8aeec9f19b775f344988d5836a1303', mtime=1077798972, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ShaneJungle.utx', size=351150, md5='921af4b30ddedf5821d9ca6e573db2f6', mtime=1077798972, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Shiptech.utx', size=28755698, md5='7356d9d98e92550d1cb01b44d93fef72', mtime=1077798978, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Shiptech2.utx', size=20976737, md5='db8688f5cab42362e0a468e89acdc96d', mtime=1077798982, source_media=media_ut2004_cd3),
		manifest_file ('Textures/ShiptechHardwareBrush.utx', size=70014532, md5='ec679e422d71997a899620b290fae920', mtime=1077798995, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SinglePlayerThumbs.utx', size=4004643, md5='325c2ba3ff747535d8551c238064d4ea', mtime=1077798996, source_media=media_ut2004_cd3),
		manifest_file ('Textures/skaarjintrotextures.utx', size=6294168, md5='831dbe511ca7faeb7b6a9408ced185d9', mtime=1077798998, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SkaarjPackSkins.utx', size=779632, md5='f1c007f8beb810752a98229320e311d2', mtime=1077798998, source_media=media_ut2004_cd3),
		manifest_file ('Textures/Skies.utx', size=2449805, md5='2bc33d549b91a2b7f03127e89850d502', mtime=1077798998, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SkyBox.utx', size=930722, md5='77711283f716c61c7264a8e0c9f74f8f', mtime=1077798999, source_media=media_ut2004_cd3),
		manifest_file ('Textures/skyline-epic.utx', size=11808246, md5='991b9cf6d61b0b4737e69850379c30a5', mtime=1077799002, source_media=media_ut2004_cd3),
		manifest_file ('Textures/SkyRenders.utx', size=67873271, md5='0304cee91ee73200bf12e446091ecc7f', mtime=1077799015, source_media=media_ut2004_cd4),
		manifest_file ('Textures/StreamlineIntro.utx', size=21617902, md5='1695476760f4419cd800fa966bdde25d', mtime=1077799020, source_media=media_ut2004_cd4),
		manifest_file ('Textures/StreamlineTakeOffTex1.utx', size=3940109, md5='f244b19d33be9de8ae035cd7ace64770', mtime=1077799021, source_media=media_ut2004_cd4),
		manifest_file ('Textures/streamlinewater.utx', size=2888378, md5='a65634869739c6b17491565ac0e358cd', mtime=1077799022, source_media=media_ut2004_cd4),
		manifest_file ('Textures/strplants.utx', size=1488373, md5='c60c527e94206b171c447da8bc17ea14', mtime=1077799022, source_media=media_ut2004_cd4),
		manifest_file ('Textures/SurvivalGuideSMskins.utx', size=9136298, md5='dac8ef41ef613f5f5f17c503104f44a7', mtime=1077799024, source_media=media_ut2004_cd4),
		manifest_file ('Textures/TeamSymbols.utx', size=34755, md5='092a545ef6fd575e8910de3bce30c444', mtime=1077799024, source_media=media_ut2004_cd4),
		manifest_file ('Textures/TeamSymbols_UT2003.utx', size=6132642, md5='64548091142313ca25d8fd8258354b25', mtime=1077799025, source_media=media_ut2004_cd4),
		manifest_file ('Textures/TeamSymbols_UT2004.utx', size=2191649, md5='4b8a59b7ffb6d9952aadd94dab8db4fb', mtime=1077799026, source_media=media_ut2004_cd4),
		manifest_file ('Textures/Terrain.utx', size=1493455, md5='0f69b9e0e9d38f424cb6d86c954d260b', mtime=1077799026, source_media=media_ut2004_cd4),
		manifest_file ('Textures/Terrain2.utx', size=64, md5='01942ce4619e52e98c105f8bebd00119', mtime=1077799026, source_media=media_ut2004_cd4),
		manifest_file ('Textures/Terrain_w.utx', size=1139989, md5='c6d109341613a909f3c42f1db136e74a', mtime=1077799026, source_media=media_ut2004_cd4),
		manifest_file ('Textures/TowerTerrain.utx', size=11470716, md5='7ac4cc2cc1245d9d9faf04fe50d89bdf', mtime=1077799029, source_media=media_ut2004_cd4),
		manifest_file ('Textures/TrophyRoom_END.utx', size=22371, md5='b2c7873d962b1bd2c46df323c28bd196', mtime=1077799029, source_media=media_ut2004_cd4),
		manifest_file ('Textures/TurretParticles.utx', size=111038, md5='b56bdf0234d6fcfc47019ef4fe81205e', mtime=1077799029, source_media=media_ut2004_cd4),
		manifest_file ('Textures/Turrets.utx', size=1586314, md5='601500c1876e4eff5a2349c6918a5388', mtime=1077799029, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UCGameSpecific.utx', size=88222, md5='2c0cd6ffd6785d1d40bbbb6da5ae25f7', mtime=1077799029, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UCGeneric.utx', size=8058550, md5='76d711d9d49b1058f9cffe9fe648ebc2', mtime=1077799031, source_media=media_ut2004_cd4),
		manifest_file ('Textures/ULogo.utx', size=1500547, md5='fee7662ddf22a0423c1df4164bc953cd', mtime=1077799031, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UT2003Fonts.utx', size=6022246, md5='db3421b060563521b52fd8bebfc79cf7', mtime=1077799032, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UT2003Fonts_kot.utx', size=16435639, md5='4c9e21033c9e297d421b48804a02dc73', mtime=1077799035, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UT2003Fonts_smt.utx', size=28488557, md5='20f8f92cf1ba6fd0927811a87594ac81', mtime=1077799042, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UT2003Fonts_tmt.utx', size=28762418, md5='212d38a35b6fffa78bcdce0c86fbb94b', mtime=1077799048, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UT2004PlayerSkins.utx', size=109128202, md5='ab95f210654398ce2f99178ab63a1ac2', mtime=1077799074, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UT2004Thumbnails.utx', size=2631597, md5='3a40856e9c0a35f20428a4fc9bbc51ea', mtime=1077799075, source_media=media_ut2004_cd4),
		manifest_file ('Textures/UT2004Weapons.utx', size=6520561, md5='a559a8d888ecb60a01813aaf79184245', mtime=1077799076, source_media=media_ut2004_cd4),
		manifest_file ('Textures/VehicleFX.utx', size=1658043, md5='15a5c4905e82c26379590d7fc7a9c908', mtime=1077799077, source_media=media_ut2004_cd4),
		manifest_file ('Textures/VehicleSkins.utx', size=2802291, md5='e57547a2ea08e14429fff3bbc1dca489', mtime=1077799077, source_media=media_ut2004_cd4),
		manifest_file ('Textures/Village.utx', size=1689041, md5='b1d0cb6381b5663cad2e680038a04233', mtime=1077799077, source_media=media_ut2004_cd4),
		manifest_file ('Textures/VMdeadVehicles.utx', size=1398778, md5='1d01c7d50090d3aa1ce2eedabcbf1d9a', mtime=1077799078, source_media=media_ut2004_cd4),
		manifest_file ('Textures/VMparticleTextures.utx', size=8437865, md5='0456158e458d60d5bf3c4e18467b73ac', mtime=1077799080, source_media=media_ut2004_cd4),
		manifest_file ('Textures/VMVehicles-TX.utx', size=8536941, md5='9ec03c97fd06e7f94775f1084f1fa3e6', mtime=1077799082, source_media=media_ut2004_cd4),
		manifest_file ('Textures/VMWeaponsTX.utx', size=10697664, md5='b207a20d221493e599d49f37dc68598b', mtime=1077799085, source_media=media_ut2004_cd4),
		manifest_file ('Textures/WarEffectsTextures.utx', size=350888, md5='b6aa12719c5afa1b67e910e47c97b818', mtime=1077799085, source_media=media_ut2004_cd4),
		manifest_file ('Textures/WarFx.utx', size=55631, md5='69d07c8e37b7a08b160e3d01bd46df72', mtime=1077799085, source_media=media_ut2004_cd4),
		manifest_file ('Textures/Warroomtech.utx', size=64, md5='91c314f957f05dc259b7c8ff3027e9e0', mtime=1077799085, source_media=media_ut2004_cd4),
		manifest_file ('Textures/WeaponSkins.utx', size=27597624, md5='3887f30764bfcaf01c246af71a6da1d4', mtime=1077799091, source_media=media_ut2004_cd4),
		manifest_file ('Textures/WinX.utx', size=5397652, md5='dda179a50747293a320d292d9f9db5dc', mtime=1077799093, source_media=media_ut2004_cd4),
		manifest_file ('Textures/wm_misc.utx', size=908, md5='69e6e7933ec510b07ce2093b4c00e595', mtime=1077799093, source_media=media_ut2004_cd4),
		manifest_file ('Textures/wm_textures.utx', size=7565120, md5='078c1ee361783637c7109a978dd4ffdc', mtime=1077799094, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XceptOne.utx', size=37845079, md5='1aeb654ffcbcda8afa8875087a28cea5', mtime=1077799100, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XceptThree.utx', size=39499019, md5='70974ada420ec20e40765d00c695f4d9', mtime=1077799105, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XceptTwo.utx', size=1771558, md5='ba9ada190312fd64566380113e223e27', mtime=1077799106, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XEffectMat.utx', size=2287890, md5='af7f6dc3cc3161de4854da7af7cb9a52', mtime=1077799106, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XGameShaders.utx', size=6831349, md5='7e8b7a8c1e1dcf8ecffa36d46a28173c', mtime=1077799108, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XGameShaders2004.utx', size=1215, md5='5fae84392cef40ba259232ca71955d06', mtime=1077799108, source_media=media_ut2004_cd4),
		manifest_file ('Textures/xGameShadersB.utx', size=506198, md5='adf95ad88257ed8c78d569e001b48a60', mtime=1077799108, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XGameTextures.utx', size=5537566, md5='b66b1043015966cd50fc33d1677414a5', mtime=1077799109, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XMiscEffects.utx', size=175558, md5='e82db2457e1aaa197c612218f5b07f11', mtime=1077799109, source_media=media_ut2004_cd4),
		manifest_file ('Textures/XPlantTextures.utx', size=350389, md5='b875351969bf94a2af4cb806f8330081', mtime=1077799109, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Animated.utx', size=24195, md5='024adfaf9c8ecd02a6751028b0e410f2', mtime=1077799109, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_AW-CellTest.utx', size=640, md5='8fb4aaf4c92a395071607575e5f13d67', mtime=1077799109, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_AW-Convert.utx', size=17292601, md5='9b54143f2cd863f775e0152f123d02a1', mtime=1077799113, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_AW-Cubes.utx', size=13439420, md5='c8fe3988d4b34598dc9563ae952402f1', mtime=1077799115, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_AW-MechTex.utx', size=2994433, md5='f8de34abe3f7fcbe5f4190b391680b06', mtime=1077799115, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_AW-Shaders.utx', size=15715153, md5='8e6fc20aa257294a0ecaad449a89c78f', mtime=1077799118, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_BG-FloraGen_tex.utx', size=8922272, md5='bfe77a858f370c90d654d8dda424330e', mtime=1077799119, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_CliffTest.utx', size=22935151, md5='1771b242a4d44e395dc6ac1dad7303b0', mtime=1077799123, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_cubemaps.utx', size=1123099, md5='0d6de7d2f3580f783c4d99a925836e3a', mtime=1077799123, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_envirotex1.utx', size=175364, md5='d99ec1a147f9712c3a42fcc8536c982c', mtime=1077799123, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_Evil1.utx', size=31841478, md5='46de7512576264b130394c18b159bc50', mtime=1077799129, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_Evil2.utx', size=16619971, md5='3a989f7844a178499710518728172bea', mtime=1077799132, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_Evil3.utx', size=24512970, md5='cdbf72e3280a69e499a8acac10666ae7', mtime=1077799137, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_Evillandscape.utx', size=176037, md5='66e1d6152059ec3c53391053190c84fb', mtime=1077799137, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_Evilmetal.utx', size=482868, md5='27261ea91d6a78e94f2a7a8e5ca159a5', mtime=1077799137, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_fx.utx', size=1053215, md5='5cadea953fded766d0271e448815c70d', mtime=1077799137, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_liquid1.utx', size=1661349, md5='1dfe0df48231bd2ff712145ad7a2a65d', mtime=1077799138, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_Mech1.utx', size=4836051, md5='86b877db7c51b00d251cdda6891c5b80', mtime=1077799139, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_particles.utx', size=155048, md5='ad563e30023e372bf63f0bf97370ea1d', mtime=1077799139, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_projected_new.utx', size=379, md5='1aa1f8d72e3c557e4d59beeebdeebf46', mtime=1077799139, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_staticmeshskin1.utx', size=6137391, md5='7a46c078315b3356a5f463652a786199', mtime=1077799140, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_stevetest1.utx', size=554103, md5='d01229de46605cae62f4872c5da070c0', mtime=1077799140, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_terrain1.utx', size=8245042, md5='6b95261fb75a3e4365f86627cec1c738', mtime=1077799141, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_cp_texturetest1.utx', size=380504, md5='39a25f75fe13804bdc47446902ffc818', mtime=1077799141, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_DeployableTex.utx', size=2386625, md5='7730c2c09fd5914344a081da9528d28c', mtime=1077799142, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Foliage.utx', size=4858616, md5='c50339f7945fce2b6e933e743edd27f9', mtime=1077799143, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Futuretech1.utx', size=24535991, md5='1e1f3d5d6d167e78d458871cb0198931', mtime=1077799148, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_GoldCubes.utx', size=11255835, md5='3bdafc188b9caf4a4a22e05f29885bc0', mtime=1077799150, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_jm-particl2.utx', size=231060, md5='2f0884d6dfee8b7d05d9a55c11e1236f', mtime=1077799150, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_jm-prefabs.utx', size=29899375, md5='7e7e10d7754afd0cd9170fb3649f210a', mtime=1077799155, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_jm-prefabs2.utx', size=1159158, md5='6162b3a2803e5b1df8440757739e078b', mtime=1077799155, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_jm_manhatten_project.utx', size=743, md5='70a96072b1c8b40a5d61c62d4a68ffc8', mtime=1077799155, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_lp_scene_1_t.utx', size=44228, md5='055d21c220324e881620f534d926da2a', mtime=1077799155, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Mechcity1_CP.utx', size=23005111, md5='f5e1876c6c112d91582fc7e94e062d83', mtime=1077799161, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_MechStandard.utx', size=23363847, md5='7ed13e02527ca9528c5770b241277f7f', mtime=1077799166, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Mech_decayed.utx', size=11273407, md5='6aec8933d4de4c00d647052d5096a3a5', mtime=1077799168, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Mech_Decay_New.utx', size=2169129, md5='5690af30dcb9ec4b61383c69baba596f', mtime=1077799169, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_MiscPhysicsMeshesTex.utx', size=613148, md5='6b45fe4ff65da759e52e321fdbf75648', mtime=1077799169, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_SC-City.utx', size=9147018, md5='68154ddacabe20be0d0510a95c10882b', mtime=1077799171, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_sg-Mech.utx', size=1489996, md5='ba141eb9a05bbc65636e877a15c0693d', mtime=1077799171, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_sg_Evil1.utx', size=5597372, md5='c46fc7b32c8046db72666c5d140ba3d7', mtime=1077799172, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_sg_floorsandgrates_alpha.utx', size=4896005, md5='8469feba22becd4a77975326cf9abad0', mtime=1077799173, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_SG_Hud.utx', size=699872, md5='eb4bc78eadd2deec2ec1430f791fe740', mtime=1077799173, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_SG_Lost_Outpost.utx', size=13402895, md5='23141e90d9210e9866e57384f3d48931', mtime=1077799175, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_SG_Special_Decos.utx', size=11027092, md5='96173b3ddfc8bc3957de889aa52c8e36', mtime=1077799177, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_ShaneJungle.utx', size=2303614, md5='a86bc86a879214780a2f95563b5ef647', mtime=1077799177, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Skies.utx', size=1933729, md5='5ef481f253d64f1d2945efb46fe103f4', mtime=1077799178, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_Terrain2.utx', size=1794451, md5='c6c7bea886cd36ecfac47757feaff1ef', mtime=1077799178, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_WarEffectsTextures.utx', size=7085388, md5='532fb93aedd04fb52c7b078224584bb9', mtime=1077799179, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_WarFx.utx', size=9722031, md5='7a1701e0ab6d7ea79715a7b16808fa16', mtime=1077799181, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_WarMechGunner.utx', size=219312, md5='4608022337cd1a21c475207dcd667363', mtime=1077799181, source_media=media_ut2004_cd4),
		manifest_file ('Textures/X_wm_misc.utx', size=7154310, md5='df72239ce3967bbeb4eb581981297855', mtime=1077799182, source_media=media_ut2004_cd4),

		manifest_directory ('StaticMeshes'),
		manifest_file ('StaticMeshes/2K4chargerMESHES.usx', size=162047, md5='56092d18b7faa4546b48420ddfad13eb', mtime=1077799182, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/2k4Trophies.usx', size=719286, md5='3c3f5974c5fe52a37b7f9faef1ae7b03', mtime=1077799182, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/2K4_Nvidia.usx', size=2212552, md5='0353618b5d60c344cc638a27add6fe17', mtime=1077799182, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AbaddonHardware.usx', size=8209271, md5='4416153984e1116d0bacc39259fe0b42', mtime=1077799184, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Albatross_architecture.usx', size=9722944, md5='0ced0b6985c9b61afb7b0d1b8f0800e2', mtime=1077799186, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AlienBrushes.usx', size=1472577, md5='25819c5a5bc5553185ab2421a43496d4', mtime=1077799186, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Aliencrystal.usx', size=25800, md5='7f27be3f163ad2a8daf34a06bda76d44', mtime=1077799186, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AlienTech.usx', size=3330807, md5='5046dcaceb8302f9ac708aaf7f2533b6', mtime=1077799187, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AlleriaHardware.usx', size=12028948, md5='c6c4eb01e8ac00243438c00d79e0c6d7', mtime=1077799189, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AntalusStatic.usx', size=1441371, md5='80ee25b2d3d3a70b28c1d425e3cdd62d', mtime=1077799189, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AnubisStatic.usx', size=1201937, md5='390b0d2b4c787b8f36fcb5c888efe1a0', mtime=1077799190, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ArboreaHardware.usx', size=9325211, md5='674434fed87e2d962eac412bef3c4fbf', mtime=1077799191, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ArboreaLanscape.usx', size=423251, md5='1128fbf4bea7f7e65e28ae3d6677b961', mtime=1077799191, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AS_Decos.usx', size=330616, md5='6379f8583f27baded47f1b1186b46659', mtime=1077799192, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AS_Vehicles_SM.usx', size=1882287, md5='56053011d33c48dafb88f8bb94d42469', mtime=1077799192, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AS_Weapons_SM.usx', size=2922507, md5='019abb60cae4d6582d9ff3d1677d3431', mtime=1077799193, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-2004Crystals.usx', size=1209099, md5='d0baf539820ccf2a2ac1b335ca413d0e', mtime=1077799193, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-Bridge.usx', size=108416, md5='fe2aa4413991253d53fd4f63c53ea9ac', mtime=1077799193, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-DemoMeshes.usx', size=234737, md5='09f1d7682087b8b380c5bc2ddeb5cfd2', mtime=1077799193, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-Junk.usx', size=4023782, md5='1993cb46e2f9b3227ebc3333d17e3881', mtime=1077799194, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-Junk2.usx', size=873843, md5='d462cb591047f4d035e4bdd60a8ac42b', mtime=1077799194, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-MechMeshes.usx', size=21774, md5='e1a0a29d58b684397e9cf5392e9d88cc', mtime=1077799194, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-Natural.usx', size=25661, md5='9b028dd3b46755bd440f37979ff69475', mtime=1077799194, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-Nature.usx', size=411177, md5='85f818114ee64504a7d637b817acdc5c', mtime=1077799194, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/aw-neutral.usx', size=285310, md5='ade3a760b8566c2b07341586adb87264', mtime=1077799194, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-PhysicMeshes.usx', size=212327, md5='fd2225414d1b6ce90c20dc56ef560111', mtime=1077799194, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-RustMeshes.usx', size=2221321, md5='234ce3c80fb593bd946d0400e737a0b4', mtime=1077799195, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-Steel.usx', size=363055, md5='f4e66d108a74019785828d39a2089b01', mtime=1077799195, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW-Tech.usx', size=2315515, md5='72bea46bb60a6dba50a7d4abb359b95a', mtime=1077799195, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AWHardware.usx', size=3633971, md5='fd71072acd720b88ecca0a34e429d361', mtime=1077799196, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AWMagicHardware.usx', size=17601, md5='041ca8cb66b15ff87c05a862c9f00fd3', mtime=1077799196, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AWPipes.usx', size=424362, md5='4cfa78562e0a39cf26d9449936423cc8', mtime=1077799196, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AWStellarMeshes.usx', size=122844, md5='ff88a1ac6218357a98a54b2dd1ad7d89', mtime=1077799196, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/AW_AlleriaHW.usx', size=265712, md5='e60be3e07c369a9ee41c1690c5f19d1e', mtime=1077799196, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/BarrenHardware-epic.usx', size=1724747, md5='8589631b3251eb3894828f12e44764c1', mtime=1077799197, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/BarrenHardware.usx', size=3226704, md5='2f4473e27b78ad1ca74e4b2146539c23', mtime=1077799197, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/BastienHardware.usx', size=544119, md5='02a4e87ce68a39f0efd43083fb561e70', mtime=1077799198, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/BastienHardware_02.usx', size=4685271, md5='b75bec72ae651226cf6ba1ad4fb549b3', mtime=1077799198, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/BenMesh01.usx', size=776991, md5='fdd688b171b0aca72c3fc7068cbcac41', mtime=1077799198, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/BP_egyptnew.usx', size=594160, md5='9d4ec3a652ab5831bbc52ba72ba8bcf8', mtime=1077799199, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/BulldogMeshes.usx', size=486964, md5='4b8c5adf18abee370748194f00f4599b', mtime=1077799199, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cass_staticmesh.usx', size=14840570, md5='2ba270c22cd4698e2313676baf66d4ae', mtime=1077799202, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/CaveDecoMeshes.usx', size=163807, md5='8776dbd6db21bae75f0e3d81c78981be', mtime=1077799202, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/CavernStatic.usx', size=1699326, md5='fef3072d506376a234cfc761b6b51003', mtime=1077799202, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/CB-Desert1.usx', size=2053518, md5='5b8149ebad339150a3d3fc319602bb15', mtime=1077799202, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/CB-Desert2.usx', size=197905, md5='c94f3455d6f46b3bc8f66479ca393a74', mtime=1077799202, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/CB-StaticMesh.usx', size=293403, md5='ccd159432ee77340653df61ff1df1a75', mtime=1077799202, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cf_DE.usx', size=2249959, md5='828cc7d325c18e06f507e491bee99b83', mtime=1077799203, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cf_sm01.usx', size=1338344, md5='9455985a215cd22eeb88a487d22a533b', mtime=1077799203, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cf_sm02.usx', size=3349562, md5='244ddf5203e1af2289771a81196c290d', mtime=1077799203, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cf_static1.usx', size=239037, md5='4de5542f5a2e64390156ff8252ff7661', mtime=1077799203, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cf_staticMushrooms.usx', size=512797, md5='3deadb5b42a02840b4587f0286247905', mtime=1077799204, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Citadel_Static.usx', size=3130106, md5='ea7d86f31c8023ae3edf5fd24fa9c883', mtime=1077799204, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Comp.usx', size=1152884, md5='c6f8307c066aed1c7cd3c73aa1ca842f', mtime=1077799204, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Corrosion_Hardware.usx', size=453139, md5='611d00139d275990022c5b745898ef87', mtime=1077799204, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cp_enviromesh1.usx', size=32385, md5='dc55f1fd4d4b90519cff176c9eb614a1', mtime=1077799204, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cp_Evil.usx', size=1075466, md5='fd42934b29c0358dcaa052f949b69e28', mtime=1077799204, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cp_Evilstatic2.usx', size=134072, md5='f0917031262ac08931e5b21340fb9869', mtime=1077799204, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cp_Mechstaticpack1.usx', size=7225488, md5='2c32d87bdf4357bd79cd9a037ed7ef15', mtime=1077799206, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/CP_Nightmare1_Epic.usx', size=7845896, md5='72b03107b867b88cfd5ae2681666197c', mtime=1077799207, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cp_simplewall_meshs.usx', size=1916334, md5='b82523b0e10c95d004ba2ed89f1321af', mtime=1077799208, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cp_stevetest1.usx', size=64, md5='2759bda499633e4d443a6547b838c683', mtime=1077799208, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/CP_UT2K3_TechSetMesh1.usx', size=3446252, md5='c8851ebc56440e3db86f94efa6da3a14', mtime=1077799208, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/cp_wasteland_mesh.usx', size=3301756, md5='6d1a24c60a3c3a862f3e6f9034bb8994', mtime=1077799209, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DanielsMeshes.usx', size=212873, md5='181cc472282fae42d4ba49fb76440ec3', mtime=1077799209, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DEBonusMeshes.usx', size=136891, md5='31fc6e7e8867011897cedb13847dd1d8', mtime=1077799209, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DEBPchecker.usx', size=696129, md5='743d0fe10d4ca0269c59db01c04fef26', mtime=1077799209, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DemoMeshes.usx', size=3776171, md5='43b34ca7db7326b3437705e9436df67e', mtime=1077799210, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DESP-MS.usx', size=1499260, md5='c998289f92000f77e3ef9236b5f35bf8', mtime=1077799210, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DespFallencity-SM.usx', size=2010178, md5='f6079e9729663102cf7457eb7d0a3fcd', mtime=1077799210, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DespTech-STA.usx', size=4058794, md5='df8761d4b1a21746d7e34a173e6ef35e', mtime=1077799211, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Desp_SMS-SM.usx', size=8329970, md5='ad88246899de0d011105c95775f5c1c3', mtime=1077799213, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/DS-staticMeshes.usx', size=498045, md5='7fed81f9b980efb70e2e602a13d44527', mtime=1077799214, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/EffectMeshes.usx', size=13108, md5='7885f0f0f70b031ab9ba57e5d3ff3782', mtime=1077799214, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Egypt_techmeshes_Epic.usx', size=2269215, md5='f4881bd21bc6d775f782d972b8c1d3e4', mtime=1077799214, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/EndGame-New.usx', size=136169, md5='fdffe2b3b87acc80cc19f72fca38adec', mtime=1077799214, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/EndStatic.usx', size=2084908, md5='971a57466f1ad0972f7331f2eec56c8c', mtime=1077799214, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Epic_November2.usx', size=1481996, md5='4c002992e9bea09e9bf005711b696a7c', mtime=1077799215, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/epic_phobos.usx', size=211376, md5='c8e10983143f1c6b328c089541b998b6', mtime=1077799215, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/E_Pickups.usx', size=523667, md5='8c03912559e5124dae7f3b73663df28a', mtime=1077799215, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Face3_decomeshes.usx', size=116076, md5='332b57ebd002e9c97639441c40701733', mtime=1077799215, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/far.usx', size=13076056, md5='310866111540947ae993aa26a16880ba', mtime=1077799217, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/forest.usx', size=1999, md5='bd77cd798cd7205b0d46f9467f9bf288', mtime=1077799217, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/GDC_Meshes.usx', size=1530384, md5='c997e40d50ca1d97cdf51e44144c288c', mtime=1077799217, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/GeneralStatic.usx', size=9570, md5='febddebfae65ea3e83255cfbe0665149', mtime=1077799217, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/GeothermalStatic.usx', size=423347, md5='94ab803fae6fcf23f57db716a7af3e26', mtime=1077799217, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Goose.usx', size=86641, md5='246e4835f47b627cac6c0b9e93c1c3f9', mtime=1077799217, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/GroundCover.usx', size=1717894, md5='3ca7535ad5b267fb86ae8788c6e02c5b', mtime=1077799218, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/GroundCovernew.usx', size=590325, md5='35f7b496e108e71f8fc6e3242bae3fab', mtime=1077799218, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/GunMeshes.usx', size=185764, md5='a7f2f48669753b18c6e091fd82420e09', mtime=1077799218, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/G_Finalset1_M_CP.usx', size=2641385, md5='346ce09ad1ce9962dae5ca2d89f948a2', mtime=1077799218, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/HourMoriaStatics.usx', size=3568436, md5='226aedbd7cef79f4d909e9acb760450f', mtime=1077799219, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/HumanoidHardware.usx', size=7285344, md5='d079c40ce6715ee1eb8fdf4900a667d6', mtime=1077799220, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/IceCliffs.usx', size=871077, md5='7c6170cda3dcf5d0e2a589cf1aaf7f72', mtime=1077799220, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Industrial_Static.usx', size=1763986, md5='5f59e258ce83892a768d7cc6c1b7fe35', mtime=1077799220, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/jm-staticmeshes.usx', size=2161671, md5='98df9f78a78bd703028e68577d868557', mtime=1077799221, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/jmalienwellc.usx', size=1238194, md5='6dbeaedf47b24944e668c09af9883359', mtime=1077799221, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/JWAssaultMeshes.usx', size=330791, md5='704296341c519c0ce979661b964c337b', mtime=1077799221, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/JWDecember.usx', size=377510, md5='cc7e4463a6e3e1aefababcc2d75fc77d', mtime=1077799221, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/jwjanbrushes.usx', size=5718, md5='30ee6ed4012334919ff57ad5d6ed7086', mtime=1077799221, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/KarmaShapes.usx', size=249343, md5='4a31f05820fa659d7f25d20f5bafeca4', mtime=1077799222, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/LP_Evil1.usx', size=1621259, md5='5e1eb48e058b398c1bc9c35cdf04e20c', mtime=1077799222, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/LP_Junk.usx', size=524767, md5='94b8f6d14eaa019d17d8c62aa35b1e60', mtime=1077799222, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/lp_scene2_m.usx', size=295953, md5='74226d565b5e2670ed68d202c38779aa', mtime=1077799222, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/lp_scene3_m.usx', size=368118, md5='f65fbf5188554a2f28cad3cf3e734bd8', mtime=1077799222, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/MiscPhysicsMeshes.usx', size=72671, md5='8fab2d0c677e2ccf046d05d59c0da6aa', mtime=1077799222, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/MiscStaticMeshes.usx', size=5516086, md5='ad9f6707963b100e470f55c1c7ac5574', mtime=1077799223, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/NaThAncientPack.usx', size=835005, md5='5dc2e2d994da89a9e3d7b4fd63919637', mtime=1077799223, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/NewWeaponPickups.usx', size=410858, md5='1904cab0958359fac1fa7383f6d1ba11', mtime=1077799224, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/NewWeaponStatic.usx', size=351769, md5='f6e4154708474076383345759443fc29', mtime=1077799224, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Nirvana.usx', size=13398349, md5='9ebfff0f2a3ac53b8ce310f11a1d9aff', mtime=1077799226, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/NvidiaLogo_M.usx', size=2427586, md5='fdd230e04b21674e6e8a8047df3226dd', mtime=1077799226, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/N_StaticMeshFX_M_SC.usx', size=17461, md5='79c8df4a066934358919a26ca0301d70', mtime=1077799227, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ONSDeadVehicles-SM.usx', size=3168944, md5='60f1ece3ac05827701dc5dc3dcf18896', mtime=1077799227, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ONSFullStaticMeshes.usx', size=1714289, md5='9c24eae0b7318e7a54f07c6f74fd3a22', mtime=1077799228, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ONSstaticMeshVehicles.usx', size=2536851, md5='70282d13b29a92a2ae209e88747c72c8', mtime=1077799228, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ONSWeapons-SM.usx', size=760839, md5='4938e3f4d4e6df9354a704af5d6e276f', mtime=1077799228, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ParticleMeshes.usx', size=3564401, md5='95389453cf0ea14fc3fd8e7bf1d79444', mtime=1077799229, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/PC_ConvoyStatics.usx', size=7299232, md5='fc779bc96ebf55117265f8b8305af990', mtime=1077799231, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/PC_NewFX.usx', size=29694, md5='834d131e16f34afb6203b8b644e82a8e', mtime=1077799231, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Pipe_Static.usx', size=6978631, md5='3adf3a14071f3c8066dcb00937ae3583', mtime=1077799232, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Pipe_staticmeshes.usx', size=1387610, md5='dcb08a5091dc0f66959b29f524b4eaff', mtime=1077799233, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/PlungeMeshes.usx', size=602372, md5='2591f035693d13f723aab2d5a676301b', mtime=1077799233, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Plutonic_BP2_static.usx', size=4022876, md5='9df56190566fbce3d16ccda72576a5c4', mtime=1077799234, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Plutonic_Robot_SM.usx', size=2825378, md5='18a62dde02eed99cf8fc70c721d054a7', mtime=1077799234, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Primeval_SM.usx', size=213270, md5='0889ccd9a1f5985f0ef1e6874457db66', mtime=1077799234, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ProcMeshes.usx', size=88189, md5='800da5b27a533811de5fbbc2ed5045d5', mtime=1077799234, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Rahnem_Glacier.usx', size=6797923, md5='821fb358e78c08d02f13b49e28ff47d8', mtime=1077799236, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/RiseSM.usx', size=510438, md5='01c314a83138cde9d5acd073b494c7c3', mtime=1077799236, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC-Intro_Meshes.usx', size=7699217, md5='6f9bef64bfb9834404e83a49903f1a06', mtime=1077799237, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC_Beach.usx', size=258661, md5='595b7946eb34e951b7c9d9f6ec318aae', mtime=1077799237, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC_CityPrefabs.usx', size=1280802, md5='fe97f077765beb2df8ebdd4543699033', mtime=1077799238, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC_FrothStuff.usx', size=161264, md5='8b9f42b5e662288740678911ec65ae78', mtime=1077799238, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC_GDC_M.usx', size=5759383, md5='05e0c30f08ca8a58aca70a3fbe2b8609', mtime=1077799239, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC_JungleMeshes.usx', size=1050866, md5='6933f6a5c5c6407d27c2acdcfc017618', mtime=1077799239, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC_MeshParticles.usx', size=73264, md5='55acae5429b80516300a4207c6940624', mtime=1077799239, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SC_Volcano_M.usx', size=8451671, md5='a4d2301f54332274b264f92039575b6e', mtime=1077799240, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SG_LO_meshes.usx', size=3759319, md5='5108121ee190c79bba7b548cffa70609', mtime=1077799241, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SG_Special.usx', size=424589, md5='207f5ea6bdde404791ffb5a246005e40', mtime=1077799241, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/sg_UT2003_pickups.usx', size=83308, md5='eec8c2e9ef42be8fd06c159655c0af6d', mtime=1077799241, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ShiptechHardware.usx', size=7834285, md5='2c1a080871773836c902ed96b9c59a49', mtime=1077799242, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/skyline-meshes-epic.usx', size=1745466, md5='a211c0e70240bf0d20af07fe509ab8b4', mtime=1077799243, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/streamlineforest.usx', size=123261, md5='ee5b31f1dc83fae6cbf83ae78b5172c2', mtime=1077799243, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/StreamlineMeshes.usx', size=27389122, md5='b615e304db2994021f5b77697abe1816', mtime=1077799249, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/StreamlineTakeOff1.usx', size=3588344, md5='f8a72f912d308fce3ce1f54f1be38b9c', mtime=1077799249, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/str_plant_meshes.usx', size=698529, md5='2c0898ab591026e0968432054bcda395', mtime=1077799249, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/SurvivalGuideMeshes.usx', size=299084, md5='ff43fa9dbe25bbfcdcab9ee52f8f35f4', mtime=1077799250, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/ThorSM.usx', size=357168, md5='923fde33160d9e2ee7eafbf33c8cf4f7', mtime=1077799250, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/TowerStatic.usx', size=2422988, md5='39894cfb5030b49184fac9402390eee3', mtime=1077799250, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/TroffHardware.usx', size=247058, md5='d411bf251d0094ebadad2f18a818ae31', mtime=1077799250, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/Trophy_endroom.usx', size=10422813, md5='d578b283b6ec828cc0e4dd60a775f78e', mtime=1077799252, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/VehicleMeshes.usx', size=345750, md5='4f67ba4525137a6aa7d10efe359bed05', mtime=1077799252, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/VMmeshEmitted.usx', size=361727, md5='4f291d75a2a246ff04de1cd68600155a', mtime=1077799252, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/VMruinedVehicles.usx', size=811622, md5='c63889bdea6ecb35167edb905bd13887', mtime=1077799252, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/VMStructures.usx', size=1712618, md5='d4ab03c547ad47ecbb99ff298a6f7718', mtime=1077799253, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/VMWeaponsSM.usx', size=749291, md5='079f51da8d994a5f227d908f06763983', mtime=1077799253, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/WarEffectsMeshes.usx', size=244353, md5='cc1d32a8b293c9521a0e0c01b2ab37a2', mtime=1077799253, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/WastelandHardware.usx', size=1383938, md5='d2b7f1556c52397ac2e025e15915374e', mtime=1077799253, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/WeaponStaticMesh.usx', size=1563523, md5='9bc4eadb224775382aa55464a2f184e5', mtime=1077799254, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/WM-StaticMesh.usx', size=5950, md5='cf969d2cfd468534e5ae0c9e9aeaf261', mtime=1077799254, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/wm_meshes.usx', size=2047309, md5='3d8622c6855d72f5c4d2294b0996771e', mtime=1077799254, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/XceptOneObjA.usx', size=41554, md5='671913453d426f5c786587834e4af47b', mtime=1077799254, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/XGame_StaticMeshes.usx', size=1345282, md5='b56d8877685c2d41ff047200d170a6ac', mtime=1077799254, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_AW-Bridge.usx', size=89092, md5='b2dbe818e79a7748ca0d0b25fdff2c4b', mtime=1077799254, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_AW-EvilMeshes.usx', size=991850, md5='740fd51f7e7c82c24d037616b154f9a1', mtime=1077799254, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_AW-MechMeshes.usx', size=3547959, md5='25c808766208a64ce56bab9f3c743fbf', mtime=1077799255, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_AW-Natural.usx', size=1370913, md5='70ae3376bd7204c064cc9356a1a4ac51', mtime=1077799256, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_AW-PhysicMeshes.usx', size=229958, md5='1ea67e2062a13509d64a548bc869cb81', mtime=1077799256, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_AW-Tech.usx', size=2249828, md5='e2bccabac28cef7a22dd8dc5899994b5', mtime=1077799256, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_BG-FloraGen.usx', size=1334411, md5='5538c1adba686a34bbefc9ba3fbfae77', mtime=1077799256, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_cp_enviromesh1.usx', size=2418844, md5='7a7046817229580b3518f03d248e839d', mtime=1077799257, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_cp_Evil.usx', size=13028994, md5='523fab95334ed5237135b204b3346d14', mtime=1077799259, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_cp_Evilstatic2.usx', size=5971171, md5='2b53c7d83b4ee18d5cb1e00b92baff53', mtime=1077799260, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_cp_simplewall_meshs.usx', size=575950, md5='75e67fdb3ac767d01f91c0150ec01442', mtime=1077799260, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_cp_stevetest1.usx', size=471358, md5='d477d5d652d0c457782e2aa838c1d7f7', mtime=1077799260, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_jm-staticmeshes.usx', size=1357053, md5='f8a6fa6a4b8f007f269d70e5daf58773', mtime=1077799261, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_LP_Evil1.usx', size=5642195, md5='54fe76ecf7418d17d07c65d0518f6808', mtime=1077799262, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_lp_scene2_m.usx', size=4867238, md5='1a25a06d1b36fd5c469d7956b139375a', mtime=1077799263, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_lp_scene3_m.usx', size=3551029, md5='0e5d6f6ede7ae7b06a770050e14a24df', mtime=1077799264, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_MiscPhysicsMeshes.usx', size=23828, md5='69a1f578cc6c9b2257d2470cd8b79c1a', mtime=1077799264, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_SC-MechBase1.usx', size=2936282, md5='89eb702aebe2c8a2a8781062e7091bd4', mtime=1077799264, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_SC-NewMech1.usx', size=2418250, md5='16a834a9241611650c0cdc519567d414', mtime=1077799265, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_SC_CityPrefabs.usx', size=1245550, md5='1a617836696878a6fcf5dc9b47e23a07', mtime=1077799265, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_sg_Evilstatpak1.usx', size=552706, md5='f9e3958cc6f4804dddc9969b3ab6dba6', mtime=1077799265, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_SG_LO_meshes.usx', size=12787131, md5='0cd0574b307e9e42aa317c459a2cf497', mtime=1077799267, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_sg_Mech_hbrushes.usx', size=367466, md5='2d92a1db25fe2153452986931e6889c8', mtime=1077799267, source_media=media_ut2004_cd4),
		manifest_file ('StaticMeshes/X_SG_Special.usx', size=417191, md5='3980d50ba9af7a73fabdc53a577e433f', mtime=1077799267, source_media=media_ut2004_cd4),

		manifest_directory ('Music'),
		manifest_file ('Music/Intro_Music.ogg', size=1424773, md5='7b9d1c0ad8d226276b5ca6d8476312b6', mtime=1053699459, source_media=media_ut2004_cd4),
		manifest_file ('Music/Jugs-Entrance.ogg', size=521852, md5='4d51bff81946eff9ced1a447e4153b4c', mtime=1053699459, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Absolute_Zero.ogg', size=1649936, md5='37bb51883e93d0670835b2d77fcd5fdb', mtime=1066222688, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Action1.ogg', size=1584437, md5='527e57784d24c23158551ca938cc2a83', mtime=1066393906, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Action2v2.ogg', size=1950894, md5='ce12581061949b59b59a370c52abb686', mtime=1066222689, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Action3.ogg', size=1525191, md5='39028f27863304e1ee2a2729b7928bd7', mtime=1066393906, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Assault.ogg', size=999791, md5='346033d4c868f0e3d330f3b2166a4c83', mtime=1053699459, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Atlantis.ogg', size=1559619, md5='9293ba6b753927d7950f9229072c7313', mtime=1065699536, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Chemical-Burn.ogg', size=1030810, md5='c12216ced3c53f277a5340f0d23c76fe', mtime=1053699459, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-City.ogg', size=2006128, md5='837ff85ca29e6b4d1f43528f63b5b09b', mtime=1066222689, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Collision-Course.ogg', size=1079209, md5='efe1b2dc33518ccca6c531143daca60f', mtime=1053699459, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Conduit-v2.ogg', size=1583437, md5='79c893136c36f0943be6e57900da7046', mtime=1065699537, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Convoy.ogg', size=2082133, md5='889cbfb12b85a984302965348d259b97', mtime=1065699537, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Corrugation-Rise.ogg', size=1652592, md5='0b7a20a75128fead89150787b4c6839d', mtime=1065699537, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-DM1.ogg', size=1072931, md5='ad81c0d667efe144bcaf692d9c71c1ff', mtime=1053699459, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-EndingSequence.ogg', size=741634, md5='c2c79435f294efe24a11e54ce7c2dd39', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-From-Below-v2.ogg', size=1011006, md5='f1161db66698f97d6034413d8018e6a4', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Ghosts-of-Anubis.ogg', size=974654, md5='00282cdeae4b42efb846a7f2a3bdeed3', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Glacier.ogg', size=1607713, md5='b9f6bc77d9931bc764f51c8a06e7ccc4', mtime=1065699537, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-HELL.ogg', size=997579, md5='4de5864016013df793c3fb2602756a56', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Hyperblast-Redux.ogg', size=1691264, md5='a2047cd8855648f63ad51db1364e32f2', mtime=1063976241, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Infernal-Realm.ogg', size=963276, md5='1fdf4681bd4eaa682f50ce812cfd70e4', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Infiltrate.ogg', size=1045762, md5='ccec67af344dbdbc06090d34aea9eee0', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Junkyard.ogg', size=2078571, md5='05dfd1eac912f2421aada6f5e628da16', mtime=1065699537, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-MenuMusic-v2.ogg', size=777362, md5='6555c6b2912e39d9de9f8d02a16876a0', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Metallurgy.ogg', size=1555005, md5='17079611b18d7447fb4e52cd9efe992d', mtime=1065699538, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Morpheus3.ogg', size=1516718, md5='ed911ca411936aaabe369a4bd8558eb6', mtime=1065699538, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Pharaohs-Revenge.ogg', size=972419, md5='06e33621ad3ade53455f5f2227d1e54a', mtime=1053699460, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Rankin.ogg', size=1752303, md5='125a586c62ae933934ae8d8c7fa06adb', mtime=1065699538, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-RobotFactory.ogg', size=2077546, md5='36711d6c153610f65f69ef516178e943', mtime=1065699538, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Roughinery.ogg', size=1588596, md5='decfa76ca5abea59e56c92ee9950e008', mtime=1065699539, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Serenity.ogg', size=1488736, md5='9a39b6c60face96ed1ffb9dd86722347', mtime=1065699539, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-SkaarjAssault.ogg', size=1575061, md5='6b04c298a6c008239fb00ac7940af3a3', mtime=1053699461, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-SkyScraper.ogg', size=1097623, md5='680825a5d27a6e531d44f82cd733001b', mtime=1053699461, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Slaughter.ogg', size=1167166, md5='9da17936c98c3e900513889fa93436e0', mtime=1053699461, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Sniper-Time.ogg', size=1028197, md5='df34cb0d9857ca91b0cf339731655e4f', mtime=1053699461, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Sulphur.ogg', size=1432168, md5='fceaf66def25b3355b239be7c0ae4ae7', mtime=1065699539, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-Tomb-of-Horus.ogg', size=966602, md5='55c9c23d8d2b001fafde0129775b3a78', mtime=1053699461, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-UT2003-Menu.ogg', size=742391, md5='6104ace6ebc73eb06b09379f382ebf6c', mtime=1053699461, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-UT2004-Menu.ogg', size=2125203, md5='aa60f186fa006e9df6e1ca0a87f62960', mtime=1065699539, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-UT2004_Intro_v2.ogg', size=2700217, md5='7710ae734af3e117998859a8ed298ea5', mtime=1074167726, source_media=media_ut2004_cd4),
		manifest_file ('Music/KR-WasteLand.ogg', size=971574, md5='010846cef6d7f3e6e3c2bc0ecde62b56', mtime=1053699461, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level11.ogg', size=3324371, md5='f1d0870b216aa314c2bc489076fdf9c2', mtime=1053699462, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level13.ogg', size=4221778, md5='f1c8ada11ea7f36f7c62d453bc4c86c1', mtime=1053699462, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level15.ogg', size=3634112, md5='4b941df65f4a41def6cbe93be501f1f2', mtime=1053699463, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level16.ogg', size=4079121, md5='deb1daf0ef53fb5e4430473ae55656dc', mtime=1053699463, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level2.ogg', size=4138184, md5='88471dee86b553a9e2510a7c02f2e19a', mtime=1053699464, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level3.ogg', size=2214611, md5='e2425688fbc6ee5771fbd8ae194020fe', mtime=1053699464, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level5.ogg', size=3882025, md5='471dbc4cd5ed04741b49284e04e73bc4', mtime=1053699464, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level6.ogg', size=3742427, md5='072f974cb4eec45035ef4f99b411698f', mtime=1053699465, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level7.ogg', size=4305649, md5='23ea2c57c63c9367485298dd71dd4a0d', mtime=1053699465, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level8.ogg', size=3536728, md5='c4c88778f6fa12758331ca2db11aba5b', mtime=1053699466, source_media=media_ut2004_cd4),
		manifest_file ('Music/Level9.ogg', size=4367931, md5='dcc674b704d9032984f9945ead998e89', mtime=1053699466, source_media=media_ut2004_cd4),
		manifest_file ('Music/Menu1.ogg', size=1877648, md5='eaeaaec32ef89b73087318f8fb666ce7', mtime=1053699466, source_media=media_ut2004_cd5),
		manifest_file ('Music/Mercs-Entrance.ogg', size=637309, md5='55aeab8eee029a9dcef8e1b1d968fa96', mtime=1053699466, source_media=media_ut2004_cd5),
		manifest_file ('Music/SDG-ONS01.ogg', size=3944344, md5='fffac10ec11922d47864dda29f5a3206', mtime=1061196215, source_media=media_ut2004_cd5),
		manifest_file ('Music/SDG-ONS02.ogg', size=3620263, md5='d6e6db29e27481093597ba1fe3cc4073', mtime=1061196215, source_media=media_ut2004_cd5),
		manifest_file ('Music/SDG-ONS03.ogg', size=6164360, md5='1f19a6759cdcd90397b8b1414d3e5cc1', mtime=1061196215, source_media=media_ut2004_cd5),
		manifest_file ('Music/SDG-ONS04.ogg', size=3260961, md5='c82d22ba4d04a40be3073b58d973b77a', mtime=1061196215, source_media=media_ut2004_cd5),
		manifest_file ('Music/SDG-ONS05.ogg', size=4124420, md5='a67c5c499de2ae36c06d09f580e16860', mtime=1061196216, source_media=media_ut2004_cd5),
		manifest_file ('Music/SDG-ONS06.ogg', size=4468505, md5='95185bac82d8bf344128a7fc7f516115', mtime=1061196216, source_media=media_ut2004_cd5),
		manifest_file ('Music/SDG-ONS08.ogg', size=3430610, md5='85662194a097c2123e5cbd381f6992e8', mtime=1066049247, source_media=media_ut2004_cd5),
		manifest_file ('Music/StageMusic.ogg', size=426213, md5='2de258257855b14de778ce8a12dd3d67', mtime=1053699466, source_media=media_ut2004_cd5)))

		# Speech recognition is Windows-only
		#manifest_file ('Speech/br.xml', size=1433, md5='4de0f1b83eb2c87dc171f6b7dc500b93', mtime=1077191247, source_media=media_ut2004_cd5),
		#manifest_file ('Speech/ctf.xml', size=1434, md5='636b85c231c99c73f784ff04507826f6', mtime=1068464205, source_media=media_ut2004_cd5),
		#manifest_file ('Speech/dom.xml', size=2796, md5='250c0ce134f09c81ca53e9d12493ecb9', mtime=1076120649, source_media=media_ut2004_cd5),
		#manifest_file ('Speech/ons.xml', size=1288, md5='4ac7254b10b6c130b11eb471c6fcf34f', mtime=1075981385, source_media=media_ut2004_cd5),
		#manifest_file ('Speech/tdm.xml', size=1251, md5='d218fb6faf61c8347ed75047abe0f890', mtime=1068464205, source_media=media_ut2004_cd5)))

ut2004_3186_audio_det = manifest (
	'UT2004 3186 German audio',
	items=(
		manifest_file ('Sounds/AnnouncerAssault.uax', source_name='Sounds/AnnouncerAssault.det_uax', size=64227399, md5='6706b9a3b3ac8a10ab8948ca7b119472', mtime=1077799332, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerMale2k4.uax', source_name='Sounds/AnnouncerMale2k4.det_uax', size=34511049, md5='ab7f7b93b5667a614ba59e73ac5f61b2', mtime=1077799400, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerFemale2k4.uax', source_name='Sounds/AnnouncerFemale2k4.det_uax', size=32352621, md5='559eb754e6a834fadf1e4a9c223c6921', mtime=1077799407, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerLong.uax', source_name='Sounds/AnnouncerLong.det_uax', size=3725504, md5='8e6246705100d335a236f9423412bcb1', mtime=1077799458, source_media=media_ut2004_cd6),
		manifest_file ('Sounds/announcermain.uax', source_name='Sounds/announcermain.det_uax', size=11510147, md5='f22a98f836eaf0f3d298c57657d17dea', mtime=1077799460, source_media=media_ut2004_cd6),
		manifest_file ('Sounds/AnnouncerNames.uax', source_name='Sounds/AnnouncerNames.det_uax', size=4630904, md5='a4a75b1800306315b627b596cc730646', mtime=1077799461, source_media=media_ut2004_cd6),
		manifest_file ('Sounds/EndGameAudio.uax', source_name='Sounds/EndGameAudio.det_uax', size=668477, md5='11f22b9420360f5842879398c6b3720c', mtime=1077799461, source_media=media_ut2004_cd6),
		manifest_file ('Sounds/IntroAnnouncers.uax', source_name='Sounds/IntroAnnouncers.det_uax', size=4035230, md5='0c05a556880ddc4f8961e465d0e4bcb3', mtime=1077799462, source_media=media_ut2004_cd6),
		manifest_file ('Sounds/NewTutorialSounds.uax', source_name='Sounds/NewTutorialSounds.det_uax', size=17382189, md5='295a0f800db33b4a41d1dc78b262b3dc', mtime=1077799465, source_media=media_ut2004_cd6),
		manifest_file ('Sounds/TauntPack.uax', source_name='Sounds/TauntPack.det_uax', size=10337992, md5='de398aabab4fdc27165ae53d2ed270f7', mtime=1077799467, source_media=media_ut2004_cd6),
		manifest_file ('Sounds/TutorialSounds.uax', source_name='Sounds/TutorialSounds.det_uax', size=20436462, md5='14937aba28d2e66b9ceff716eaec7a09', mtime=1077799472, source_media=media_ut2004_cd6)))

ut2004_3186_audio_est = manifest (
	'UT2004 3186 Spanish audio',
	items=(
		manifest_file ('Sounds/AnnouncerAssault.uax', source_name='Sounds/AnnouncerAssault.est_uax', size=63502191, md5='3103680289c669cfb45956f0ac4ada26', mtime=1077799361, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerMale2k4.uax', source_name='Sounds/AnnouncerMale2k4.est_uax', size=24290964, md5='ae525bdab8a057d38f7fac5c703929a9', mtime=1077799374, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerFemale2k4.uax', source_name='Sounds/AnnouncerFemale2k4.est_uax', size=31488276, md5='573a9df54e6d896a67788ec58fe1fbcd', mtime=1077799381, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerLong.uax', source_name='Sounds/AnnouncerLong.est_uax', size=3929307, md5='12c9a1d09dd7bfddadcc107747e061a9', mtime=1077799442, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/announcermain.uax', source_name='Sounds/announcermain.est_uax', size=12615570, md5='db26a67138ee814cd6ea974468d3e7f5', mtime=1077799445, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerNames.uax', source_name='Sounds/AnnouncerNames.est_uax', size=3768572, md5='9e21e1ce4b75770052fd90687e68566a', mtime=1077799446, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/EndGameAudio.uax', source_name='Sounds/EndGameAudio.est_uax', size=668495, md5='70a5a654c1df51e09312c1f285c05037', mtime=1077799446, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/IntroAnnouncers.uax', source_name='Sounds/IntroAnnouncers.est_uax', size=4409852, md5='ead1746b5dadc8de4ce2830fa917f319', mtime=1077799447, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/NewTutorialSounds.uax', source_name='Sounds/NewTutorialSounds.est_uax', size=19940423, md5='e293b3a93bc4005103e741bae12b18dd', mtime=1077799450, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/TauntPack.uax', source_name='Sounds/TauntPack.est_uax', size=10704007, md5='4e2b86323e6751f902c3b89815320104', mtime=1077799453, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/TutorialSounds.uax', source_name='Sounds/TutorialSounds.est_uax', size=19222742, md5='f95817f3265be6e10e881af136a6e47d', mtime=1077799457, source_media=media_ut2004_cd6)))

ut2004_3186_audio_frt = manifest (
	'UT2004 3186 French audio',
	items=(
		manifest_file ('Sounds/AnnouncerAssault.uax', source_name='Sounds/AnnouncerAssault.frt_uax', size=63105998, md5='3c2b4fc6fa5aa73b08a9395fbc296c60', mtime=1077799317, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerMale2k4.uax', source_name='Sounds/AnnouncerMale2k4.frt_uax', size=10567163, md5='c73d6e884e41cb2c699c1df274e5918e', mtime=1077799363, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerFemale2k4.uax', source_name='Sounds/AnnouncerFemale2k4.frt_uax', size=27339661, md5='ba528e5374e83d6bbc0076b4e15fac4d', mtime=1077799368, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerLong.uax', source_name='Sounds/AnnouncerLong.frt_uax', size=4386502, md5='870c27ae1b9c576895cf389c64dd39e2', mtime=1077799408, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/announcermain.uax', source_name='Sounds/announcermain.frt_uax', size=10861005, md5='25ee3ecd9605cf922fe575ecfa42a89c', mtime=1077799410, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerNames.uax', source_name='Sounds/AnnouncerNames.frt_uax', size=4301747, md5='87d4f4fc108f33ab17c7242c07d95fc4', mtime=1077799410, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/EndGameAudio.uax', source_name='Sounds/EndGameAudio.frt_uax', size=706843, md5='8686a2754ce8808b88ea00329d494274', mtime=1077799410, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/IntroAnnouncers.uax', source_name='Sounds/IntroAnnouncers.frt_uax', size=3839456, md5='144504a66a3900b3385d8ae97cc0403f', mtime=1077799411, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/NewTutorialSounds.uax', source_name='Sounds/NewTutorialSounds.frt_uax', size=19931345, md5='affcacf86576402fdec67d89b3ac2226', mtime=1077799415, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/TauntPack.uax', source_name='Sounds/TauntPack.frt_uax', size=10674278, md5='9b8343cecae7f98e037162fbac8dcb99', mtime=1077799417, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/TutorialSounds.uax', source_name='Sounds/TutorialSounds.frt_uax', size=19676848, md5='4021b51155458a193e953f051b7edba3', mtime=1077799422, source_media=media_ut2004_cd5)))

ut2004_3186_audio_int = manifest (
	'UT2004 3186 English audio',
	items=(
		manifest_file ('Sounds/AnnouncerAssault.uax', size=42028727, md5='48abe5567476642701d9eeb4685eabe5', mtime=1077799301, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/announcermale2k4.uax', size=14028319, md5='b5d3ca76af0c430404111ae5150fa665', mtime=1077798536, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/announcerfemale2k4.uax', size=28377227, md5='025399a818681de88aad3e35968e4fc5', mtime=1077798528, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/AnnouncerLong.uax', size=4309044, md5='35a9cb0488eacc46203a8a1696d93c8f', mtime=1077798528, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/AnnouncerMain.uax', size=12419394, md5='944d54b70228a6066d9d77a10468f094', mtime=1077798532, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/AnnouncerNames.uax', size=5385219, md5='7cb1b249c0f90f07e4b988f13cc17c4e', mtime=1077798538, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/EndGameAudio.uax', size=781851, md5='25705757b26a0020d4290ae44242a5b3', mtime=1077798540, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/IntroAnnouncers.uax', size=4561042, md5='48a77f4af71ac7b939de439225cb8ae0', mtime=1077798546, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/NewTutorialSounds.uax', size=19022099, md5='827da05be7711a9bd126ccc1f421d41b', mtime=1077798568, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/TauntPack.uax', size=11002707, md5='6ea806e8307734aacd2f2659ef671d3a', mtime=1077798582, source_media=media_ut2004_cd2),
		manifest_file ('Sounds/TutorialSounds.uax', size=20651978, md5='762cebc8fdc3983e0459e3b3efcc4c53', mtime=1077798586, source_media=media_ut2004_cd2)))

ut2004_3186_audio_itt = manifest (
	'UT2004 3186 Italian audio',
	items=(
		manifest_file ('Sounds/AnnouncerAssault.uax', source_name='Sounds/AnnouncerAssault.itt_uax', size=60836345, md5='7eee2889ac2166fa3a43ad52322c4a1c', mtime=1077799346, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerMale2k4.uax', source_name='Sounds/AnnouncerMale2k4.itt_uax', size=22323195, md5='f62263215238b679d5b2f1391aae45ea', mtime=1077799386, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerFemale2k4.uax', source_name='Sounds/AnnouncerFemale2k4.itt_uax', size=27087268, md5='bad3d17aec329c8ef511008bdb209db5', mtime=1077799392, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerLong.uax', source_name='Sounds/AnnouncerLong.itt_uax', size=4331338, md5='3cca697845ecde348fc91601c7898206', mtime=1077799423, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/announcermain.uax', source_name='Sounds/announcermain.itt_uax', size=11954867, md5='73029294b742a960261c2e8689f517d3', mtime=1077799425, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/AnnouncerNames.uax', source_name='Sounds/AnnouncerNames.itt_uax', size=5379106, md5='3b86670bc6770ec097aed521f42d52e0', mtime=1077799426, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/EndGameAudio.uax', source_name='Sounds/EndGameAudio.itt_uax', size=720469, md5='0058ef713ffcb30b215ce695bb787eb6', mtime=1077799426, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/IntroAnnouncers.uax', source_name='Sounds/IntroAnnouncers.itt_uax', size=4931333, md5='5b9303f42abcfff7cab7a8f54d048942', mtime=1077799427, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/NewTutorialSounds.uax', source_name='Sounds/NewTutorialSounds.itt_uax', size=23146910, md5='feb750a63c498ca9311533d81522b9ed', mtime=1077799433, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/TauntPack.uax', source_name='Sounds/TauntPack.itt_uax', size=16589804, md5='f4e4e7adc88efdf45058e0e0535c53c0', mtime=1077799436, source_media=media_ut2004_cd5),
		manifest_file ('Sounds/TutorialSounds.uax', source_name='Sounds/TutorialSounds.itt_uax', size=22343132, md5='63fca00f95be9f7a9d768d09bef0fd70', mtime=1077799442, source_media=media_ut2004_cd5)))

ut2004_3186_audio_kot = manifest (
	'UT2004 3186 Korean audio',
	items=(
		manifest_file ('Sounds/NewTutorialSounds.uax', source_name='Sounds/NewTutorialSounds.kot_uax', size=21034026, md5='475fd349efe3dfbc060e457d9346659d', mtime=1077799476, source_media=media_ut2004_cd6)))

ut2004_3186_audio_smt = manifest (
	'UT2004 3186 Simplified Mandarin audio',
	items=(
		manifest_file ('Sounds/NewTutorialSounds.uax', source_name='Sounds/NewTutorialSounds.smt_uax', size=17106551, md5='d387005e1ca2ba2d5978201b69d53126', mtime=1077799482, source_media=media_ut2004_cd6)))

ut2004_3186_audio_tmt = manifest (
	'UT2004 3186 Traditional Mandarin audio',
	items=(
		manifest_file ('Sounds/NewTutorialSounds.uax', source_name='Sounds/NewTutorialSounds.tmt_uax', size=17106551, md5='d387005e1ca2ba2d5978201b69d53126', mtime=1077799479, source_media=media_ut2004_cd6)))


		#manifest_file ('DirectX9/BDA.cab', size=695962, md5='8900f15a6bb4e88a40e61dff0383904c', mtime=1059564642, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/BDANT.cab', size=1149019, md5='08938174a6e3174795d6f173da953e7c', mtime=1059564642, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/BDAXP.cab', size=968156, md5='3d48496dd6669692bc69de5f1694b817', mtime=1059564642, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/DirectX.cab', size=15443578, md5='8395203fb63b22a35764e90868da5fd5', mtime=1059564643, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/DSETUP.dll', size=60416, md5='91865aec9c49bee70ed3ab5ec4365127', mtime=1059564643, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/dsetup32.dll', size=1978368, md5='54a2e8e8b8672ab0921017b704d0eec7', mtime=1059564643, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/dxnt.cab', size=13160291, md5='1451b2aa63243bc6639694b6d472c41e', mtime=1059564644, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/dxsetup.exe', size=467456, md5='50ca7683aca3e726583aa99f1621decc', mtime=1059564644, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/ManagedDX.CAB', size=1104358, md5='4f35b8a97ecb14ee8bda8e8b7aa626fd', mtime=1059564644, source_media=media_ut2004_cd6),
		#manifest_file ('DirectX9/mdxredist.msi', size=1127936, md5='ff9252312b1a32ee095060878d9e67e8', mtime=1059564645, source_media=media_ut2004_cd6),

		#manifest_file ('Speech/Redist/InstMsiA.Exe', size=1707856, md5='cd91a545478263b4e6902e7d5932077d', mtime=1059474918, source_media=media_ut2004_cd6),
		#manifest_file ('Speech/Redist/InstMsiW.Exe', size=1821008, md5='d0ef61e0a6eb919ba51229d14c3ef5d5', mtime=1059474918, source_media=media_ut2004_cd6),
		#manifest_file ('Speech/Redist/Setup.Exe', size=110592, md5='73f0db11f10e7d007d721bb498254bdd', mtime=1059474918, source_media=media_ut2004_cd6),
		#manifest_file ('Speech/Redist/Setup.Ini', size=43, md5='6d5738fb45222f46046cf087e9305d2e', mtime=1059474918, source_media=media_ut2004_cd6),
		#manifest_file ('Speech/Redist/SpeechRedist.msi', size=52125184, md5='0ae030bda245dd95d49efdd125b1b701', mtime=1059474920, source_media=media_ut2004_cd6),

		#manifest_file ('Extras/Readme.txt', size=4201, md5='4269f0ca5f0d7b1acc141ecdd59546e9', mtime=1077774265, source_media=media_ut2004_cd6),
		#manifest_file ('Extras/AliasSketchBookPro/AliasSketchBookPro_1.0.3.exe', size=9790066, md5='3d9c985ce7d64de013988ccdde1e45d4', mtime=1077624850, source_media=media_ut2004_cd6),
		#manifest_file ('Extras/KAT/KAT_1_2_UT2003_Setup.exe', size=2295863, md5='9ecd6820bb8d710f5b3fe6324ba9b0ca', mtime=1053699290, source_media=media_ut2004_cd6),
		#manifest_file ('Extras/MayaPLE/MayaPersonalLearningEditionEN_US.exe', size=135714780, md5='6a5524b4cadeb8c28b6c721f01642692', mtime=1077710621, source_media=media_ut2004_cd6),
		#manifest_file ('Extras/MayaPLE/UT2004Plug-inForMaya5.0PersonalLearningEdition.exe', size=6978082, md5='37aacd944f90942ffa759e9980394ca6', mtime=1077787076, source_media=media_ut2004_cd6),

ut2004_3186_frt = manifest (
	'UT2004 3186 French text',
	items=(
		manifest_file ('System/ALAudio.frt', size=259, md5='3fa98a5f46663b6da0752b8f6dd779d2', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Convoy.frt', size=6337, md5='fa72218ff16218d4afafa2097eb9c676', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-FallenCity.frt', size=4620, md5='0250a21419e09e0c989c5b61180ed448', mtime=1078171857, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Glacier.frt', size=8369, md5='e75496c2018296d8c621465732d01cd7', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Junkyard.frt', size=4060, md5='278fff1da4ad1f414ff2aa94ca04bb25', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-MotherShip.frt', size=10765, md5='70ccb21bc338bdfdd35f576dea64fbe4', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-RobotFactory.frt', size=5850, md5='0b9cf8eae4e0172ede111d731ff59cea', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/bonuspack.frt', size=4304, md5='62d82df55b8d2498c14b89552f1e9e92', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Anubis.frt', size=2019, md5='979c3aca97d219c2e059d28c0c243d9f', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Bifrost.frt', size=665, md5='8ac3d5fd81a3a11033afe119640de620', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-BridgeOfFate.frt', size=1414, md5='08df8f3327ef7b08ab3e8c63bb243e77', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Canyon.frt', size=782, md5='f6371a3569b89975a5170b0d7ebfc316', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Colossus.frt', size=669, md5='c85a234c45299ec613d753336a7dff65', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-DE-ElecFields.frt', size=1972, md5='ce1d5ac98b585b209da32301c3b828ee', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Disclosure.frt', size=2945, md5='953e352e6ba6e9b4544fc3f309cc153b', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-IceFields.frt', size=511, md5='61ab4cc913a12ec42cbdea4230b7e97d', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Serenity.frt', size=863, md5='62a72176e1b51a1a162a94fd32e0a90b', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Skyline.frt', size=285, md5='4e8ba5d5d85324b3129f86d05edc5dc0', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Slaughterhouse.frt', size=2028, md5='aff7ca577a59481f053c4d7f388898cf', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-TwinTombs.frt', size=1874, md5='08cc598f48f80d8a689c4e6d92567182', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/Core.frt', size=3435, md5='9777ae8f9d6d95469f491e9024d65f13', mtime=1077019415, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-1on1-Joust.frt', size=738, md5='88db2427ee5389165d40c794cccd2963', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-AbsoluteZero.frt', size=2057, md5='d3fb582798ba4a31d426f1b9d44cc83c', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Avaris.frt', size=3028, md5='de5361f79b54c1b23286564937a5bd47', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-BridgeOfFate.frt', size=2327, md5='bd6dbe05923639e89bbda32c79694397', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Chrome.frt', size=1288, md5='3ace5d81a5320f448f4a466ef48d9528', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Citadel.frt', size=1090, md5='9294f0fc48fc5256c8da09040fa179d9', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Colossus.frt', size=763, md5='c9c69281e6fa5fd2d474a959a111f0c1', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-ElecFields.frt', size=2014, md5='3179ad91d6ea1052ff39e475c9d68a80', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-LavaGiant2.frt', size=1118, md5='1c14abffec4c5667d19733c5f3b8997e', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-December.frt', size=2199, md5='344fc45ccb33dc1bcb35b0bb45a29645', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DoubleDammage.frt', size=3214, md5='2225958d23ccf6979b00bed193f7bddc', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Face3.frt', size=651, md5='3fea6b78e23c6586023ffa18191e1a5e', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-FaceClassic.frt', size=1668, md5='33f3fe25f76cb1136b421085fcf5a19b', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Geothermal.frt', size=1273, md5='fd15b5730f24ca081b468a82532e97f5', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grassyknoll.frt', size=952, md5='d81a87db663ea6de0bd4eb6fbe74096b', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grendelkeep.frt', size=3572, md5='729f62dc8d81828c72084b02edc71294', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-January.frt', size=3632, md5='30af531da181e4da63f9a262eb49b5d3', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Lostfaith.frt', size=316, md5='3aad8717b44ea368cfd40d07fc8ee2b9', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Magma.frt', size=1012, md5='b5cf98be91f9aaa273d53486d038e619', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Maul.frt', size=298, md5='f5e131a6a2c7320145f2037a652a151a', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-MoonDragon.frt', size=936, md5='640eacfd690fd2526dfdace65df4ee0a', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Orbital2.frt', size=1548, md5='7ff6d26ec09b2587c0e9eb8c4295190d', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Smote.frt', size=2432, md5='815281825f3727c3d3183da9692fd4c3', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-TwinTombs.frt', size=2205, md5='6bd9743312c179fd0230f3cfd93707f5', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/D3DDrv.frt', size=358, md5='8518a26120ff273b9572ff115739e3fc', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DemoLicense.frt', size=15794, md5='ae6a5b3ddff07443b10df0dbd8c01460', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Albatross.frt', size=923, md5='c3cd4160c8fea16954f66bb273b86819', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Crash.frt', size=758, md5='cf6f67357aa56a346d698fbb1f7e2ad0', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Desolation.frt', size=884, md5='f217bf5fbd207bbd9bc40fff217a92c9', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Idoma.frt', size=311, md5='f9ae1a56a0c34de874bfe7351e6dacf5', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Irondust.frt', size=586, md5='dcfd6012133b91e92cd01cc0bca20669', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Mixer.frt', size=665, md5='1a633d75c0251f9d1197be006c1bef54', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Roughinery.frt', size=409, md5='044ab29d23644c97ea4c8feb2e2d681f', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Serpentine.frt', size=262, md5='1f940388582e914fd529b86e65f8a980', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Spirit.frt', size=530, md5='d3c471505d4e11c03d3430c01b826d0a', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Squader.frt', size=889, md5='8b98dffb09999c0c6029db69c7b92d07', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Trite.frt', size=457, md5='b331d37653422b9c596d113216e981ec', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Antalus.frt', size=729, md5='1635721ba4f433424ee82b899282e5af', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-asbestos.frt', size=748, md5='28e3133554284d2d5ebd0b5b72202759', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Compressed.frt', size=874, md5='a30c1e24f2563783deee40d5e2b88f47', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Corrugation.frt', size=1189, md5='f745515d179e7834520977af7ee72e35', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-curse4.frt', size=1757, md5='dce1b7e2c1ada116d872b0cf79aff41d', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Grendelkeep.frt', size=1441, md5='e5f0e176228f3ada267e32370e3a54ac', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Ironic.frt', size=1276, md5='2a9f6ae3bd131a7920a56e58876c2e1e', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Osiris2.frt', size=1015, md5='e211c8c74993214b450e33f83b633a44', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Deck17.frt', size=2936, md5='d33c7d2619844a0af028149851a6529c', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DesertIsle.frt', size=457, md5='cdb44e1bf1d18c16923c67944151502b', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Flux2.frt', size=376, md5='cf785a291e53e6b25262558ed69774e4', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gael.frt', size=107, md5='cb80ae3604d84f244b0ca28154a87ccf', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gestalt.frt', size=563, md5='b7a196069c211545e307d2c97617ac16', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Goliath.frt', size=1113, md5='62012cbeca64822a321ad17185b794f8', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-HyperBlast2.frt', size=1033, md5='39e0ca463755074ff3e154fa30a9b027', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Icetomb.frt', size=970, md5='e13d5ab884ce398d147a11e599e73b10', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Inferno.frt', size=828, md5='3845f600832110f1f2e1c59bac0ca90a', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Injector.frt', size=986, md5='c08724899e2d35e66dc6ab2de8122141', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Insidious.frt', size=756, md5='f648becc12cea76f113c0edc61bd3319', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-IronDeity.frt', size=846, md5='5aeb26be6e69ba94a20561b56749c917', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Junkyard.frt', size=422, md5='37c59159526a864e132e4e3c53c59819', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Leviathan.frt', size=637, md5='30829dcad8a8382567333e38c8128653', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Metallurgy.frt', size=1414, md5='19c7108bdf3731efe2f8a2815e17eb97', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Morpheus3.frt', size=947, md5='32931945ccba2dc5681b5ea484679f45', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Oceanic.frt', size=553, md5='49e6e16b5f4388de302abe12f86c4eec', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Phobos2.frt', size=1480, md5='161d10525aa626299512984bd4bab35d', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-plunge.frt', size=123, md5='12b9c8e4ab1e7194797cfc4ae2943d01', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rankin.frt', size=375, md5='6246d156b04e1ac21b63fe73c2944962', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rrajigar.frt', size=328, md5='dbad0a10d8abd27f78f8976ef19628ff', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rustatorium.frt', size=332, md5='e4ca5c86432ab8be029fb981db7ced0e', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Sulphur.frt', size=525, md5='21a0cedafb7121822e7978bf3c8673a5', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TokaraForest.frt', size=200, md5='dff84db429adcd7c664febd8084f0916', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TrainingDay.frt', size=235, md5='bd7439f329f0fd3b410027fb6886e169', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Access.frt', size=872, md5='0b468305e47d2ad1cb6cde15e7ade181', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Aswan.frt', size=964, md5='f679d5de99160d8fa049ba4c77d4f3b8', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Atlantis.frt', size=1123, md5='4bd9007983b19a31e580a67e480a08cb', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Conduit.frt', size=568, md5='560bceac037d100b5b457f2794319667', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Core.frt', size=98, md5='3dbad1c7816008ad8b8c5e252a08e5a7', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Junkyard.frt', size=420, md5='96b01666fd5815c3e818b2fa1c3b1f7f', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-OutRigger.frt', size=1100, md5='88cdd7be99ecea6cb7d31d6536dc266e', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Renascent.frt', size=535, md5='880a5c4024c022949a4573ee20719d8f', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Ruination.frt', size=280, md5='1bd4e3b1709d396e76826d8337be1b4b', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-ScorchedEarth.frt', size=997, md5='ce7a263d86833f0092fd1375823faea6', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-SepukkuGorge.frt', size=339, md5='2183431c68cd6201d90e19304b6d15cb', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Suntemple.frt', size=1028, md5='25e2e436d187389be446e0f049da5d9e', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Editor.frt', size=5885, md5='cfd6c173d3bbbd98d12f6d3dfafb93b2', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Engine.frt', size=19431, md5='8ccf8bb36577b22d2b50c37587d5fcbd', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/GamePlay.frt', size=7915, md5='dd39f52e7fd0f7913216a0e2c8d956c7', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/GUI2K4.frt', size=87564, md5='ed1ca7bac265d3c8a6c5ab8c8a0a1576', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/IpDrv.frt', size=1567, md5='218f5895a982625d380f6b17f193c76c', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/license.frt', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Manifest.frt', size=2308, md5='a2e960006efc3f87a1f2fd88841dbca4', mtime=1078360714, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-ArcticStronghold.frt', size=837, md5='4f1a9a1d304f3f134ca5f0243327a855', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Crossfire.frt', size=998, md5='9e668112c584598ec756599b1f216851', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dawn.frt', size=811, md5='c55c510e52f168de49aded1be27a7328', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dria.frt', size=1131, md5='040a3d90a699db5f0ae6c1a1998bf2b3', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-FrostBite.frt', size=1487, md5='a9ce39d36dd43e6b6c291dac19fd0f6f', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Primeval.frt', size=473, md5='1f9fe55f7cdee96cf674e4e9c62e5c55', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-RedPlanet.frt', size=892, md5='2dffff7bc5adade9fa76a5d780afb63b', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Severance.frt', size=825, md5='f8deea0ffd4a4ca7169157478d68026a', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Torlan.frt', size=1128, md5='fd0f6ea8807fa111ad33cae8ee87ef45', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/Onslaught.frt', size=15696, md5='23b30aa13ce90ecbbab646bcffcef575', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/onslaughtfull.frt', size=1562, md5='647f8c018df73ebcf52af47df8e0bc4f', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/Setup.frt', size=9923, md5='5deef943fb8df7fc70b489ddce772da1', mtime=1078360858, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Demo.frt', size=1786, md5='01ba52fe7641f5ce7f7da1353107a7de', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Full.frt', size=2453, md5='9479291f4d20e146aa71cbd3bb8d14fc', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2004Demo.frt', size=1486, md5='c2b98010f765e83e3110fc2137fb90e8', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/setuput2004full.frt', size=2308, md5='af94d2749995b3292285de4e96c77e7e', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/skaarjpack.frt', size=4055, md5='6e3368df6803f6e0235fb2b98d1a376b', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/Startup.frt', size=1777, md5='f557bad58c30dde332f8ce511fe50f01', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-BR.frt', size=2082, md5='fe798bf4eb6998008e83d6e1e530b846', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-CTF.frt', size=84, md5='4b7b413b670d90a6bdfb6c57364c5a09', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DM.frt', size=132, md5='02264eaaa01771d902260e1d70790de9', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DOM2.frt', size=801, md5='dd7ed249024a9eaeb2e90751a1473ccb', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-ONS.frt', size=81, md5='2ad17a75870b42fd2b95926d6c7d77e5', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealEd.frt', size=172, md5='247f190f0c0df1a208fc5b84596a8b52', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealGame.frt', size=14354, md5='1633265ba903994820e33583eef102e5', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2003.frt', size=202, md5='5987101d9f7a5004a279d1394a972e00', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2004.frt', size=202, md5='788e3235d5bee5667e278440e36041c6', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4Assault.frt', size=7409, md5='2d2a4bbc5557c3a2a5d41b44ece2a3cb', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4AssaultFull.frt', size=1795, md5='72f869866c810f706c3b8aff3437585c', mtime=1078171858, source_media=media_ut2004_cd1),
		manifest_file ('System/utclassic.frt', size=2376, md5='5300acd7a2d43173cff06f3d98c49986', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UTV2004s.frt', size=260, md5='43da802d02d535339bb5add81caa73f3', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UWeb.frt', size=127, md5='535cb63be233451269b8d944fab4e5c1', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/Vehicles.frt', size=224, md5='2d5bcc62c7a9782b6f2a7107e0fe0825', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/Window.frt', size=2334, md5='4a1c12d9ad713cfe32846157b6a93fff', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/WinDrv.frt', size=683, md5='50ea23b700ab38d835dc6113ea31b2af', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XAdmin.frt', size=2825, md5='365e8fbe78ecee2606fe801a8ee6c2fd', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XDemoMaps.frt', size=1268, md5='d7135fe3ecfbabacb2899d35c92843c4', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XGame.frt', size=21942, md5='1c26853b57f45e98b9fb22e5eadb756f', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XInterface.frt', size=53331, md5='6d9c1151eba9abcf319e4bc6b9faa78a', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XMaps.frt', size=8919, md5='5428d98386e49c86a98b3f7389e5cc82', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XPickups.frt', size=378, md5='0e15d08fb8b4a601e7fafc53c6f02586', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XPlayers.frt', size=26926, md5='a29fdfc89b431d899217ea60ad93cd3b', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/xVoting.frt', size=11641, md5='40ecea8a461283942d0e8f8320ea8f47', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XWeapons.frt', size=19874, md5='f736e1b95087a4521fb7c0174c5523d1', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XWebAdmin.frt', size=6843, md5='77b06f2a8cdccccbccec670925fef421', mtime=1077983487, source_media=media_ut2004_cd1)))

ut2004_3186_det = manifest (
	'UT2004 3186 German text',
	items=(
		manifest_file ('System/ALAudio.det', size=263, md5='473a2566734ed2a31dd79f44b48a2539', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Convoy.det', size=6375, md5='d2616a7d6a24a520462785d6512a0390', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-FallenCity.det', size=5009, md5='94b52a16d2a2251a0a570fc39fb845d7', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Glacier.det', size=8797, md5='e00a039f30673e64d51b39958ac2ada5', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Junkyard.det', size=4513, md5='782c4eae0a947f9cc6845bb6c3dbcb71', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-MotherShip.det', size=10033, md5='8d3d8c60e3a987bb6a28017c70066498', mtime=1078171857, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-RobotFactory.det', size=6041, md5='b43898ee7dff44c1b932b8cd79c7cf3c', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/bonuspack.det', size=4724, md5='f659666dc1cd540920e271817ddb0e94', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Anubis.det', size=1911, md5='19ac02cdb04da093e16e16cc829f3e79', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Bifrost.det', size=791, md5='34e6b738ced4b11da5e06fab33508676', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-BridgeOfFate.det', size=1407, md5='17007af103419daa0f13b5fb1e70946b', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Canyon.det', size=771, md5='25e6a84efd7ea18192d88de8a886212a', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Colossus.det', size=706, md5='af3ca3643c9daff748a7845a27d94be2', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-DE-ElecFields.det', size=1997, md5='c45a2cee30d3ccaab83ebac8c5ca5f8f', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Disclosure.det', size=2913, md5='0a99df5b5dd33f5974d53f8a42003901', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-IceFields.det', size=441, md5='8342059f2c0f80d37b8b570e5ece82fd', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Serenity.det', size=822, md5='f3274469866b27994a22690ac92bd459', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Skyline.det', size=355, md5='6c46db76c15733b7255b5329b7b880dc', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Slaughterhouse.det', size=1984, md5='fedeba152648c71baac5dbba38ab5416', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-TwinTombs.det', size=1879, md5='b78e3b7029ae90a6d30a26989b1c78b4', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-1on1-Joust.det', size=658, md5='a0f4fec92232df258b2785f32e8e2cff', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-AbsoluteZero.det', size=2076, md5='ce96503399d01720441054778ff5d218', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Avaris.det', size=3078, md5='823a2761fd1cfd1058f1e84514985cb5', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-BridgeOfFate.det', size=2262, md5='3d44458c8c4d449b1002b89e24a3212b', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Chrome.det', size=1275, md5='a15245b9f9fd05f532fee48f461f10d5', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Citadel.det', size=1106, md5='5cfcacf1ec2af642417931f4ae719c0f', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Colossus.det', size=811, md5='9fa141bf0a87f857f07d417afb9bc711', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-ElecFields.det', size=1997, md5='816d02a25fd7eaecbbd55087c556930a', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-LavaGiant2.det', size=1140, md5='6c2601f4c44dd8c512231cdc539c10da', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-December.det', size=2213, md5='fff84ce40e9c253337013a5190875c22', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DoubleDammage.det', size=3240, md5='edce1aa3fb9b5fc81a56f90c520cd1d3', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Face3.det', size=1139, md5='7ad605a1988e2e7e57887cf67eb9531b', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-FaceClassic.det', size=1535, md5='8aa20a1f9bc91b44fd7773671980b456', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Geothermal.det', size=1236, md5='2e61cf311a208e63efab5b52398111fc', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grassyknoll.det', size=1025, md5='b3c5bf19ee1b64a5c04ae2e40113f585', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grendelkeep.det', size=3497, md5='3e7a219256caa1b340387df7fa4c8c4f', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-January.det', size=3690, md5='de77e52877cb78af86544eee89c6601b', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Lostfaith.det', size=456, md5='c112a03db2dd3a04e374bfd4efb67f86', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Magma.det', size=991, md5='12e5e71b561fd9bc199c7e92ea9201b8', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Maul.det', size=404, md5='e4a0ff6911ae32f710c4b44fd42933d1', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-MoonDragon.det', size=987, md5='0b872b917da0b79ffcb38c9dbec0dcd7', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Orbital2.det', size=1447, md5='569067046ff6ceb5b15ce2d1d2794ee9', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Smote.det', size=3137, md5='6f712c2d67892ffda8a0e7487575585b', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-TwinTombs.det', size=2131, md5='506857905a5de457c7e42b8471bb5002', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/D3DDrv.det', size=361, md5='0043021b8553d4ffb4044cba2865b091', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DemoLicense.det', size=15794, md5='ae6a5b3ddff07443b10df0dbd8c01460', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Albatross.det', size=834, md5='a7786f3902edb1092add0138f00ca9a9', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Crash.det', size=792, md5='ea313f5deaf82647840d239d24e274bc', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Desolation.det', size=740, md5='eee704ee05792a062b5d47eb92a00752', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Idoma.det', size=339, md5='00f3a1c206ca55c18b14c9ba7e156399', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Irondust.det', size=565, md5='dd1155ad710d2c58efe480d92236ac90', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Mixer.det', size=654, md5='501eebccfbdc2b45c6ea22b0235bee09', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Roughinery.det', size=418, md5='38c18e8a420e15dc5e53fb52ed9edcd7', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Serpentine.det', size=250, md5='e08aeb9a4995c9aff714a8c16f50bfcc', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Spirit.det', size=444, md5='5cca2fec6fa5737c3598d57be9616812', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Squader.det', size=839, md5='d327889384fecba6a60c88d368a97547', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Trite.det', size=439, md5='dfb3a0d851685d53bd75e143a8ea0190', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Antalus.det', size=636, md5='ce58f21e52ef5883f640a03f4a4268f5', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-asbestos.det', size=834, md5='47fff8bd888ee01064d933b4c9e6472b', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Compressed.det', size=799, md5='fcd00feda8ed823db3fbfb5491521e13', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Corrugation.det', size=1267, md5='600c56c75aa968e5b6a80bf2121236fb', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-curse4.det', size=1795, md5='a413978892ee24d250a1e3aad83e6c6b', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Grendelkeep.det', size=1634, md5='2bc0178ba90184f6e3a97957686f0f56', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Ironic.det', size=1264, md5='1672854fd9967bf4cd9918bd15a2d284', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Osiris2.det', size=1047, md5='dc86d88ad9c29b8e6f27d20d2dd2836a', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Deck17.det', size=2815, md5='c26cc18127cdb577d131cfa49aa3ab04', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DesertIsle.det', size=448, md5='da9110ef9e4d3722a5e052db05a8ea2c', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Flux2.det', size=347, md5='b7543f0c2c761bb0d4a8da5f7dbf4e0a', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gael.det', size=104, md5='87f64f4a4c07fc1fc186850a001a5976', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gestalt.det', size=613, md5='3cb58b7de973f0d2a8ab7746e3620427', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Goliath.det', size=1077, md5='f101f930301e5e45caa2937288034c05', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-HyperBlast2.det', size=1002, md5='343353d07b39b7be51d2839d8a1623fb', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Icetomb.det', size=950, md5='52e6e4d132e22d8d383d000fd8ce4970', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Inferno.det', size=873, md5='56fcbf18fce78950a232da5e653d275c', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Injector.det', size=1050, md5='945af4e1c66cd5e2781983e978a3dd59', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Insidious.det', size=696, md5='3ec649da3dc57cbac5295eab2edc760e', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-IronDeity.det', size=915, md5='77f0da983a8e6c96ca0238ba18e818f2', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Junkyard.det', size=452, md5='ab3888c46a6b1583238b8c08b781f9b2', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Leviathan.det', size=656, md5='af84462b8493ecf7ad3b2bc71b317088', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Metallurgy.det', size=1466, md5='8e309c926aede1a1961340b9494f4623', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Morpheus3.det', size=1055, md5='5f5df457f6369632d4aa290bdbf34d4d', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Oceanic.det', size=689, md5='cf79941559ccad441a6abee95e151b73', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Phobos2.det', size=1505, md5='dcc4b3b09f3216fd4a48e26118dc3523', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-plunge.det', size=115, md5='b3718a1f0e68173e101493c142f3139a', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rankin.det', size=372, md5='ccc978922c4b17066a4321fe9106e6ce', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rrajigar.det', size=329, md5='e112befad425179b532b1a1d2dd61bea', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rustatorium.det', size=352, md5='cb6745f50b81033cb1f37c59266c6631', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Sulphur.det', size=607, md5='7512517e0927d1c204ac78f844b584a9', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TokaraForest.det', size=244, md5='3279dba83561506c8c4d7d4a30ff42fc', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TrainingDay.det', size=227, md5='47133c01852e3269f2575de8d40b3a76', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Access.det', size=798, md5='4ef29da67ddf0c25999c526804d4773e', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Aswan.det', size=971, md5='25d17a0a64ae5f014327fcaea480a03c', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Atlantis.det', size=1095, md5='3e11eda6ce930483b20f268198285454', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Conduit.det', size=589, md5='a867ea52dc5312508dd62df5c525c4fe', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Core.det', size=177, md5='7270e7f5063996b37df2ed86d8c61763', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Junkyard.det', size=447, md5='9433e72532eca57d4004637d19402904', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-OutRigger.det', size=1181, md5='d68b5a6485c3d4649fb0164c19290334', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Renascent.det', size=527, md5='e70f4b456d75452adb0a0e9d82e8349e', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Ruination.det', size=285, md5='d2d9ea8231469b906e7306fe3b30c7b2', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-ScorchedEarth.det', size=951, md5='37b33aefa36542f93e064dfa44e930ae', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-SepukkuGorge.det', size=318, md5='3420ecdc7d833fafd80936f3421f29d5', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Suntemple.det', size=1092, md5='71d32e2547ec8e9553138388fa30741a', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Editor.det', size=5878, md5='2bb79af02d738f563d17587e54a9749d', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Engine.det', size=20033, md5='2321b56b90b1ca135e907f6aa9134938', mtime=1078012996, source_media=media_ut2004_cd1),
		manifest_file ('System/GamePlay.det', size=8638, md5='87643b65e5df3ac49275d4e325fb2973', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/GUI2K4.det', size=93160, md5='613da04f1e940cedb89488af7e2042d7', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/IpDrv.det', size=1608, md5='048e00d0117af51ca88aac4f30da2f1f', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/license.det', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/Manifest.det', size=2452, md5='67ab2de5fe8ffd57a2109b51b8422a08', mtime=1078360646, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-ArcticStronghold.det', size=858, md5='5b80c88445c79d58cf9a1c5ab6784f73', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Crossfire.det', size=1038, md5='273ee241a40e2824021548d22821ed59', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dawn.det', size=824, md5='82db8d3d28157e9537cea6ab3cd4bde7', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dria.det', size=1225, md5='b48681d42317637be57216561282dbe8', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-FrostBite.det', size=2051, md5='579baa8da4e43dfb1fd4ce7ac87051ee', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Primeval.det', size=483, md5='d3509b46322b6917b1d00647e73bce61', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-RedPlanet.det', size=929, md5='b5d2480feb03080b0e6696b460288a5a', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Severance.det', size=843, md5='360fda5a909ee1cecde94f5993621669', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Torlan.det', size=1284, md5='eed0610390ec5fb2f78316b1073d1d20', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/Onslaught.det', size=16463, md5='825774150ce6225f6e6b88a1279781f1', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/OnslaughtFull.det', size=1691, md5='6e8f588ede1ac8546b4a0f82198a7b8b', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/Setup.det', size=10649, md5='064d7d5e21533aa2756a7522b1ef1928', mtime=1078360873, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Demo.det', size=1754, md5='ded2d200fcdc1afb7bc055badf3a39fc', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Full.det', size=2385, md5='7c212568a63652fbd6d498c47e0fc968', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2004Demo.det', size=1444, md5='0cfe8a431808ad5e72c424b75c2a194a', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/setuput2004full.det', size=2452, md5='4332a6db007b18507f82caeb5a30b6cf', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/skaarjpack.det', size=4301, md5='0a5487442610045f4f1ad320c8acfe62', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/Startup.det', size=1775, md5='a4e28bf8c6c08aa652baa8b58ba3fb71', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-BR.det', size=2051, md5='8f76ec8741a67f060530d1bb07a37687', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-CTF.det', size=78, md5='b32459de18cc663b7578db155d2dbc2a', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DM.det', size=134, md5='ddd7ad7d6f65de3c905d1cf0f240ae4e', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DOM2.det', size=797, md5='e697a0222ea93230450b63c9edf24460', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-ONS.det', size=124, md5='b0f64a5d8176ffcbfff6e131cf2d9d68', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealEd.det', size=180, md5='6d1c0d13ad91199f6bb31da3897ae2e6', mtime=1078056055, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealGame.det', size=15194, md5='cfa416376f423142acd509235f12545e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2003.det', size=193, md5='81b817ae9fe666812b6532a7ce5bf3e1', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2004.det', size=204, md5='a9348dff0a7f3d95b10c01fab93f02f6', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4Assault.det', size=6943, md5='1c42556ea8893e6989bb853c61e5e617', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4AssaultFull.det', size=1731, md5='adc7f46f32f26ab5a942613a9f0ea6e1', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/utclassic.det', size=2482, md5='752a5789a3592f363efb22a7c870b724', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/UTV2004s.det', size=266, md5='bbdb7dade6772bbea59723c35402d5d5', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/UWeb.det', size=126, md5='3eb88e7f550fa69bb10b298050c22f99', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/Vehicles.det', size=290, md5='2fce0bb78738c9d342340b4c058fad54', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/Window.det', size=2475, md5='2684d23dc32b4cc5cde4d0929e6a3fbf', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/WinDrv.det', size=709, md5='4e6bd669086290dd91f16e812ad76041', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/XAdmin.det', size=2942, md5='d228898389378fe010f6e1c0f60c98d5', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/XDemoMaps.det', size=1385, md5='44bb1504edff41ef913fc62831ea8660', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/XGame.det', size=23283, md5='c705068237c0b0cc1fa0f35dae5c8702', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XInterface.det', size=56346, md5='ac0af079e779560c97bbe53f10d78b04', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XMaps.det', size=9775, md5='65f128cd7547e0ea481c9f1e62e6ac77', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/XPickups.det', size=448, md5='bfec9777f96db1ea6c78bac26a413821', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/XPlayers.det', size=27243, md5='de685f434ea2072c278de4ca75377ade', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/xplayers2.det', size=5550, md5='b0194b32fffe5c641a646d42dd5d6054', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/xVoting.det', size=12172, md5='333ddaddb3d0e5664f3786b085af9e5f', mtime=1078087645, source_media=media_ut2004_cd1),
		manifest_file ('System/XWeapons.det', size=22079, md5='a02344e46ef99eccbbb1bb4c234f22ab', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XWebAdmin.det', size=7698, md5='092d6fc2940ede34dc045259276f4baf', mtime=1078087645, source_media=media_ut2004_cd1)))

ut2004_3186_est = manifest (
	'UT2004 3186 Spanish text',
	items=(
		manifest_file ('System/ALAudio.est', size=261, md5='ebf08811a587d93909bb11770c3ed83d', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Convoy.est', size=6603, md5='a6fee48919dbac8fd91b4d463ca885e9', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-FallenCity.est', size=4827, md5='e584c90102545189a9ca624d95012fcb', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Glacier.est', size=9647, md5='b1eaaa421a78d5c7b2d6e320783afdad', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Junkyard.est', size=4355, md5='41ee5eae446dd093a865e59233fdd767', mtime=1078171857, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-MotherShip.est', size=10941, md5='0138c4c10b8f771dfc1fda28505ae720', mtime=1078171857, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-RobotFactory.est', size=6072, md5='2dcea9083d228bc3fb12ed8801fcb227', mtime=1078171858, source_media=media_ut2004_cd1),
		manifest_file ('System/bonuspack.est', size=4627, md5='381f0c83d3d8295f51a375d268df4965', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Anubis.est', size=1982, md5='fed05e42820e11427d221e3cdd02cc05', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Bifrost.est', size=705, md5='8ebe9bfc91da4cefa54d43038a4d4655', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-BridgeOfFate.est', size=1421, md5='27fabffdf55a25c9959007514fbfaa6d', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Canyon.est', size=781, md5='24ac54e8d7048204bcbefc0d92b3cd83', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Colossus.est', size=692, md5='ee103a407f2502497aaa32ee9a22d6c2', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-DE-ElecFields.est', size=2184, md5='c419f5787f3c762b6ca679ed71dc9422', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Disclosure.est', size=2902, md5='2d8285fb6f14db0780f057ce5016f4a3', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-IceFields.est', size=511, md5='851e9357e34a5601af710de96bf042ed', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Serenity.est', size=875, md5='16339a8e805a712c9592d08fb06010a4', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Skyline.est', size=287, md5='5dff95fd1d01ef6c0a6f90508816e2be', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Slaughterhouse.est', size=1997, md5='cbc945d33cefcef5778ace1d8bb6502e', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-TwinTombs.est', size=1983, md5='df773b26db103c6872e6d7e441525643', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/Core.est', size=3997, md5='59f35f7bfb028006d2fde102f0c6a869', mtime=1077019415, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-1on1-Joust.est', size=528, md5='0395c6262a988e383b473c17a2fc1366', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-AbsoluteZero.est', size=2263, md5='9fbb199e15b697deb81ab48a518d9854', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Avaris.est', size=3129, md5='8329ecdca5ec4b482fbdfc77da44dc39', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-BridgeOfFate.est', size=2378, md5='7cd7a1194b1ffdb7a7e03f619fbe502f', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Chrome.est', size=1261, md5='fcbd5b39dd3c4d3b45e09c4312ca0775', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Citadel.est', size=1136, md5='bba7ab12f339b31df40996e6af7743e5', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Colossus.est', size=746, md5='6bfda67feb5f5d822d077730e0af13e1', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-ElecFields.est', size=2240, md5='ad752fdcec5e89031c05aa507a876016', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-LavaGiant2.est', size=1082, md5='cad3236d5728c148529c966994e5aaf3', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-December.est', size=2275, md5='bb2adce932ac0fb0f7ae88efa8350312', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DoubleDammage.est', size=3540, md5='1477cd8ca0f1e12f3a0817f8cdf86869', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Face3.est', size=657, md5='fd72aad703f068d93c27f133e459a569', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-FaceClassic.est', size=1723, md5='bc8f721c44ee23cb39aa6be72a5ebef6', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Geothermal.est', size=1282, md5='4538a87d638cc1db8dbed53ac33a2f42', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grassyknoll.est', size=1002, md5='afff99a2ae2db2f10990e71fc24974d6', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grendelkeep.est', size=3781, md5='01d939a0c842e67f6d00b98c48e34c90', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-January.est', size=4602, md5='c33c7ea6639a2ed87a794c5027dbf551', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Lostfaith.est', size=291, md5='42b26eb435098e634090dabcddcf69e6', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Magma.est', size=1032, md5='1713e0730bd23014f9232f5f571e8c33', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Maul.est', size=310, md5='186f752be633046b77f02f73a8587336', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-MoonDragon.est', size=957, md5='9b7b7023da254d647537790af45ab18d', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Orbital2.est', size=1564, md5='c0f696e3222b921fbb7279117ed34f14', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Smote.est', size=2656, md5='194ca3e2331d8159301c6acbd71de512', mtime=1077983483, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-TwinTombs.est', size=2235, md5='94e47c7d1e7fd933297881325ab7334d', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/D3DDrv.est', size=382, md5='dd7a3f34e66d5f136374e2d7285858db', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DemoLicense.est', size=15794, md5='ae6a5b3ddff07443b10df0dbd8c01460', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Albatross.est', size=931, md5='dc6893a5f6ed565689a179c0a4da5065', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Crash.est', size=827, md5='b39af1e778d4673d453d745bed7d2b50', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Desolation.est', size=949, md5='7e14fba9daf312ec5786a20d7e065701', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Idoma.est', size=340, md5='4ccf323b1e276ca4b20cb7df7f8e8ffa', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Irondust.est', size=602, md5='97fc4bf09acbb739a161c5466691322e', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Mixer.est', size=648, md5='8b71f693db97057f21bb12103f11f46a', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Roughinery.est', size=399, md5='a1f9a09c0fe4cc6f50b09be57aae97aa', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Serpentine.est', size=248, md5='cd4c0adab1525ad5e49ac8a8044c9599', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Spirit.est', size=559, md5='2e2723b01d51c7db71c8d94781e425c2', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Squader.est', size=885, md5='1040fcfcbcdeca5285671b97f2d5ca73', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Trite.est', size=448, md5='045fb4baa2ae570f2270553001221d49', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Antalus.est', size=730, md5='c4782daf8ebf11789ec0bb16ed9c2b8f', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-asbestos.est', size=799, md5='1953854a69e2b5d6636de2f7f2c602ac', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Compressed.est', size=844, md5='e8124d0b0a21a86e3cd228f9f2a2d22e', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Corrugation.est', size=1267, md5='968ea1921ed5734be6c2e2ee8b25bfa5', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-curse4.est', size=1823, md5='2a7e31d1c8c46af5c5f396e88bf8a129', mtime=1077983484, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Grendelkeep.est', size=1588, md5='cb2883534b424c5589cf28e8f027c21e', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Ironic.est', size=1329, md5='2fc0d964ef75e5b39e2e6959d9a08b01', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Osiris2.est', size=1053, md5='3c076be00c4dd7aeed564dab7a75e5e7', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Deck17.est', size=2962, md5='5fecb6484970497f1b39feee88abc507', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DesertIsle.est', size=452, md5='6c375cfc5942bae51cc4ce3d3405e2c0', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Flux2.est', size=382, md5='7f92f2072c1492a481c7411da451b4d0', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gael.est', size=103, md5='2a774783f4f008258322974dd7030ee2', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gestalt.est', size=599, md5='148ff3bf0b20acffb0f2f83f9a2dc5f9', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Goliath.est', size=1163, md5='d7c31a791b056e813f4d3c434d119b16', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-HyperBlast2.est', size=1120, md5='a1f534ffb54fc5e6247045206434618e', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Icetomb.est', size=991, md5='663d7dcaa0dde1fe08cf6c6b3aa4ac35', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Inferno.est', size=928, md5='a3e68a7b0a2cc9040feb0f2d3ffb7546', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Injector.est', size=957, md5='baaa20063e7fe1aafa73805337b91e50', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Insidious.est', size=762, md5='f6a6085c93bf54d6f2886e85d6a75201', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-IronDeity.est', size=882, md5='bf3170484f82c682c0d3dca9fcbd2125', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Junkyard.est', size=424, md5='200bd3251217f559bee387a8db784d70', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Leviathan.est', size=647, md5='6f1469e71b51aaee12702e02a56327de', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Metallurgy.est', size=1440, md5='81186b9c4bd153dcf25c52915aea2c6d', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Morpheus3.est', size=1088, md5='77df5260b81b40e5671b8b3141443013', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Oceanic.est', size=562, md5='f538db13102ea6ffd214b4310420b6cd', mtime=1077983485, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Phobos2.est', size=1471, md5='5386241dff64e8acb2bfaf622acacd45', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-plunge.est', size=121, md5='f7cd622c60bf4ec6509543b0435f2925', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rankin.est', size=403, md5='f9109323f87ac444dac3d368a766e82f', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rrajigar.est', size=328, md5='1b7000cea025d9bafc9589383965b77f', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rustatorium.est', size=322, md5='e690d79f52d96f3044d0dfc90b84084e', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Sulphur.est', size=561, md5='30726af50f378ef2f52b8ef9992bb413', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TokaraForest.est', size=214, md5='286367461e5c63c0a87975159f8733d3', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TrainingDay.est', size=235, md5='768aa4a9a50f005aab8e3f1b85cc565d', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Access.est', size=885, md5='405880ea417fccbf46e3cf8dea033eb1', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Aswan.est', size=958, md5='d57b6651356264a66c5fe2518fb4b9a7', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Atlantis.est', size=1122, md5='620c3d997fd30ac7a7688081d59a415b', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Conduit.est', size=614, md5='fa0511e9de69e38e0a9681c599975f83', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Core.est', size=101, md5='027f104f60acb26a2d8e00fb708b2551', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Junkyard.est', size=422, md5='32a113d065e6c84e406b8dd63b8492a6', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-OutRigger.est', size=1097, md5='b2ff8c187f8e59cbc9c86c8b85482fea', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Renascent.est', size=560, md5='d17f0b0aeedae7b0766ab23fc2abfd44', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Ruination.est', size=291, md5='bc2ecba19ecced1e03037ca69cfc9ceb', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-ScorchedEarth.est', size=930, md5='a055373f0f5730590bb930a04c2e62ad', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-SepukkuGorge.est', size=338, md5='8a10125daee638e9c8f426e2c2039f90', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Suntemple.est', size=1022, md5='592cd967089b75fab420dd89710c55c3', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Editor.est', size=6025, md5='cfb828807711756338be73c5e0a0d102', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Engine.est', size=21038, md5='89d2c5f06730f7534cbefb3bceaf86f0', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/GamePlay.est', size=7868, md5='e61409016f031e337cb15d07ddf32333', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/Gestalt.est', size=599, md5='a538d6ef869cafcf6a21628e9ec5a55b', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/GUI2K4.est', size=93094, md5='3ed14c0f84d69b1028c8e71859755da2', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/IpDrv.est', size=1587, md5='260c8f49860120395942d3fa01a3238b', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/license.est', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/Manifest.est', size=2459, md5='83dfdaefd5574bee3c4d363ad89ce90c', mtime=1078360684, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-ArcticStronghold.est', size=824, md5='8c6ddee2c2d8617ea2ad64894de0037e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Crossfire.est', size=978, md5='d7762b96761c9fdd871486769a8eef25', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dawn.est', size=767, md5='40d5a904961c2c457235c89017ea4565', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dria.est', size=1312, md5='6082d0b3ca09789677c308399dadd87d', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-FrostBite.est', size=2272, md5='a4c684e1d492c24e26d789247d47b4a1', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Primeval.est', size=501, md5='a94021a5674819574e3c6276ffc35dad', mtime=1077983486, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-RedPlanet.est', size=883, md5='e994753b1582e1e6a210611f253917a9', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Severance.est', size=847, md5='c7615ae9df5ddba23a37c88c3b82e432', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Torlan.est', size=1237, md5='13c6a7c11ae3ce1582a189e832ce49f9', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Onslaught.est', size=16316, md5='ebccbc71152194a78d2632418ccfd880', mtime=1078361029, source_media=media_ut2004_cd1),
		manifest_file ('System/OnslaughtFull.est', size=1892, md5='542cd6eded23a29e309cb35ba1d6084c', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/Setup.est', size=9773, md5='00d613b3760efdd886e39e3552ca8b1a', mtime=1078360834, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupBonusPack.est', size=559, md5='7c9e0885a796ec636e09022be5b05050', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/setupbrightskinsmod.est', size=567, md5='e891cb0fbf4aef18053996a445e0706c', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Demo.est', size=1799, md5='7d8ac9c2db593125975839757465aa5c', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Full.est', size=2372, md5='f1d43e5c0570a88ee03bf585f8216e36', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2004Demo.est', size=1539, md5='0cbb767907638a1027c3884f5e74655d', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/setuput2004full.est', size=2459, md5='adea55b6c49db0ddfc485363b9ca6cbb', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/skaarjpack.est', size=4371, md5='28c6f1d42ab206cae7332b37eaef4a9e', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/Startup.est', size=1867, md5='2cde2a387cc3ec6e8bae2c1bca982605', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-BR.est', size=2159, md5='f9c10468790caf23245abd2abe25c0ce', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-CTF.est', size=78, md5='4b4b3e6d639a7a0442de6654f8247d85', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DM.est', size=136, md5='8302396ae5fef04a595fe95c85c31540', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DOM2.est', size=808, md5='7bb9365a2a3a7537e149351eb333b010', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-ONS.est', size=121, md5='5e8508a09e6bde702036efb817404f10', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UC.est', size=172, md5='e3a5ed1fe959233c2c10aec4e02e36ba', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealEd.est', size=164, md5='8c1da3d603e66d7d361cb7698d74f9c7', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealGame.est', size=14567, md5='651ef88c277e15925dd920c4f06f517a', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2003.est', size=199, md5='f24b5efd19fa24d5b2215e399d8e92e9', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2004.est', size=192, md5='e2b83ddfc925ca857c07bf4453466963', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4Assault.est', size=8147, md5='3147700f6879d34ca49d321ce24bbc73', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4AssaultFull.est', size=1926, md5='53c72aed1260a54e8c47eb8d27a7ffe9', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/utclassic.est', size=2537, md5='2e4438d62b51073a86447e5af504569a', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UTV2004s.est', size=264, md5='3a57ad65190dec238327d6cee06272a6', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UWeb.est', size=123, md5='c7b9e1c82be901d36261b2a7f2ba4803', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/Vehicles.est', size=234, md5='13909d88fe67e6ea45f2f60a0334a9f8', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/Window.est', size=2352, md5='7594c978cde907ac02d8695014145e13', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/WinDrv.est', size=702, md5='237feca67088c2a9d75dd74851d83786', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XAdmin.est', size=2805, md5='60779eef8a8766f8d0c7559d6623c299', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XDemoMaps.est', size=1371, md5='b19397a3cd6d051d2d0353bed076786f', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XGame.est', size=22731, md5='214c61b4c84beb35a01ec99b1db9b437', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/XInterface.est', size=55655, md5='d7501652364c55d7ee18c198ecdeb852', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/XMaps.est', size=9885, md5='7b6147f2ba97283f935ef5bb31fb59f9', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/XPickups.est', size=374, md5='f58a34c7907ccb45ef2137fef1abb30a', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XPlayers.est', size=27547, md5='87faa8aeb773d821c1ba01c7ff3932bf', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/xplayers2.est', size=4994, md5='ebfcc8d6126dcf3fe9a08bf6a0379c41', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/xVoting.est', size=12388, md5='830835cf2e05229f72ec4d4bcb146f86', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XWeapons.est', size=21652, md5='1a214a2772f19e29c0951eabfb3541a0', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XWebAdmin.est', size=7195, md5='c822d5dd9475c924b4b4ce358a918ebd', mtime=1077983487, source_media=media_ut2004_cd1)))

ut2004_3186_int = manifest (
	'UT2004 3186 English text',
	items=(
		manifest_file ('System/Core.int', size=3612, md5='0ded2a6395057dccdd963920cb7b45b9', mtime=1075465732, source_media=media_ut2004_cd1),
		manifest_file ('System/D3DDrv.int', size=367, md5='57058058fb3ec0c0cc4636250b3319c6', mtime=1074322953, source_media=media_ut2004_cd1),
		#manifest_file ('System/Engine.int', size=18934, md5='9e450d4d7806ed0386bf9aedf7c039a0', mtime=1078117369, source_media=media_ut2004_cd1),
		manifest_file ('System/IpDrv.int', size=1564, md5='5e1560ab69cb4eaf3923d20280838bb6', mtime=1075880872, source_media=media_ut2004_cd1),
		manifest_file ('System/UWeb.int', size=127, md5='535cb63be233451269b8d944fab4e5c1', mtime=1074322954, source_media=media_ut2004_cd1),
		#manifest_file ('System/Setup.int', size=8908, md5='3b61ffa8d7447ef11836d88ec7ca6d9a', mtime=1077591890, source_media=media_ut2004_cd1),
		manifest_file ('System/Startup.int', size=1885, md5='4af75727ce092e78199a8254593b28e7', mtime=1076268428, source_media=media_ut2004_cd1),
		manifest_file ('System/Window.int', size=2398, md5='018dbc86085ff307af39f370e9c6409a', mtime=1074322954, source_media=media_ut2004_cd1),
		manifest_file ('System/WinDrv.int', size=701, md5='23ec786f1d73f9b8a694e1813a6d9ab3', mtime=1074322954, source_media=media_ut2004_cd1),
		manifest_file ('System/ALAudio.int', size=260, md5='5d7929da6bdf79507394418632d58d5e', mtime=1074322953, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2004.int', size=192, md5='098c7227725ca941ca01716379889b5d', mtime=1074322954, source_media=media_ut2004_cd1),
		manifest_file ('System/XMaps.int', size=8784, md5='14b6bc40dc1e60f8be363c4f9dc90c25', mtime=1077830163, source_media=media_ut2004_cd1),
		manifest_file ('System/TeamSymbols_UT2003.int', size=3850, md5='243cdf99d9b25a916cc471a62aeb1e2f', mtime=1077104877, source_media=media_ut2004_cd1),
		manifest_file ('System/TeamSymbols_UT2004.int', size=1851, md5='9610b60c0cf5966eb64d95559ad5c864', mtime=1077104878, source_media=media_ut2004_cd1),
		#manifest_file ('System/XPlayers.int', size=25965, md5='47849576a5f52979b5d92eb781852aa1', mtime=1077234134, source_media=media_ut2004_cd1),
		manifest_file ('System/BonusPack.int', size=4338, md5='2d3e2517d8e73684b3de0a4af2d6397e', mtime=1075290027, source_media=media_ut2004_cd1),
		manifest_file ('System/Core.int', size=3612, md5='0ded2a6395057dccdd963920cb7b45b9', mtime=1075465732, source_media=media_ut2004_cd1),
		#manifest_file ('System/Editor.int', size=5952, md5='538d94f4da98d8603877b73ff7ca34cc', mtime=1074322953, source_media=media_ut2004_cd1),
		#manifest_file ('System/Engine.int', size=18934, md5='9e450d4d7806ed0386bf9aedf7c039a0', mtime=1078117369, source_media=media_ut2004_cd1),
		#manifest_file ('System/GamePlay.int', size=7687, md5='9dc230261ae8b57c4b81868bdfef87dd', mtime=1077681734, source_media=media_ut2004_cd1),
		#manifest_file ('System/GUI2K4.int', size=84637, md5='7dbb5c545ec19feaad0b355ec1b5a221', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/IpDrv.int', size=1564, md5='5e1560ab69cb4eaf3923d20280838bb6', mtime=1075880872, source_media=media_ut2004_cd1),
		#manifest_file ('System/Onslaught.int', size=14645, md5='5e7fd4a005ce20d1ec54fa16247b5729', mtime=1078070859, source_media=media_ut2004_cd1),
		manifest_file ('System/SkaarjPack.int', size=4000, md5='8e009ba4ef6f61492377794d781120a5', mtime=1075290027, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealEd.int', size=168, md5='936f1425201b6fc08e334caf4ad4c7ac', mtime=1074322954, source_media=media_ut2004_cd1),
		#manifest_file ('System/UnrealGame.int', size=13478, md5='f5deccac24fcf9279d6b84616eb5ca6b', mtime=1077730382, source_media=media_ut2004_cd1),
		#manifest_file ('System/UT2k4Assault.int', size=6919, md5='ceea125d18ce21c363a88725473892e0', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/UTClassic.int', size=2200, md5='931fc81764c269c7a80fc840ec694089', mtime=1074322954, source_media=media_ut2004_cd1),
		manifest_file ('System/UWeb.int', size=127, md5='535cb63be233451269b8d944fab4e5c1', mtime=1074322954, source_media=media_ut2004_cd1),
		manifest_file ('System/XAdmin.int', size=2415, md5='116ab1df5bef85c3410d02c19d6ee228', mtime=1074817186, source_media=media_ut2004_cd1),
		#manifest_file ('System/XGame.int', size=21384, md5='49720484a7c28a5233b31f69225532de', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/XInterface.int', size=51911, md5='7d1a0e3d991302dd446d416749953425', mtime=1078117369, source_media=media_ut2004_cd1),
		manifest_file ('System/XPickups.int', size=449, md5='5bd4afdee4d1f8ca458872695241b426', mtime=1074322954, source_media=media_ut2004_cd1),
		manifest_file ('System/XWeapons.int', size=20148, md5='1dd678646af6b8b8e0f9a1264a6c765d', mtime=1078171858, source_media=media_ut2004_cd1)))
		#manifest_file ('System/XWebAdmin.int', size=6655, md5='b66b246a4c96bc3356c8dde465050224', mtime=1076677474, source_media=media_ut2004_cd1),
		#manifest_file ('System/XVoting.int', size=10996, md5='9296c2888f22ad19f7bb44606b3bd4ea', mtime=1077191247, source_media=media_ut2004_cd1)))

ut2004_3186_itt = manifest (
	'UT2004 3186 Italian text',
	items=(
		manifest_file ('System/ALAudio.itt', size=260, md5='0baf74f73ae5e6772f2b6b087fdab41e', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Convoy.itt', size=5769, md5='12b2778609e9c39a1631bc884a51da7a', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-FallenCity.itt', size=4926, md5='cb6129f5e0103d83f6e38d963bea6318', mtime=1078171857, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Glacier.itt', size=8831, md5='b10584e1381a4fd49fe421cfb2c673b0', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Junkyard.itt', size=4496, md5='10337768608c4f94b37cda410281e67a', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-MotherShip.itt', size=10854, md5='3a396b4727049ebd22b53b3525888595', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-RobotFactory.itt', size=6189, md5='82fc1ad700e1624f610a063374ac05a4', mtime=1078148296, source_media=media_ut2004_cd1),
		manifest_file ('System/BonusPack.itt', size=4770, md5='bdbb5c28144cd45db7e53bd1833dfbca', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Anubis.itt', size=2015, md5='3b112d0c4fdb548ef5da1490b4ee96e4', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Bifrost.itt', size=865, md5='3071647aa3d81e8bc542a0d17e17c74a', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-BridgeOfFate.itt', size=1575, md5='97242292c14cc5eaffd99d35df9fa7ad', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Canyon.itt', size=780, md5='5b763355784c4895e1108703e2b7ba4b', mtime=1077983482, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Colossus.itt', size=649, md5='13128a37b66d1f307bac7853310c42f4', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-DE-ElecFields.itt', size=2142, md5='1678e84ae441107651dc02a3036f85fa', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Disclosure.itt', size=3117, md5='9ebb97e08d6ccac06c288f6aac60eb6e', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-IceFields.itt', size=432, md5='ca15610bd9a02f6745a5f1f750a3a497', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Serenity.itt', size=885, md5='750d0e2b42a7b9843920e4095a3ad8ae', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Skyline.itt', size=362, md5='f33164a2993093f8442ce67c7b53be0b', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Slaughterhouse.itt', size=2123, md5='4a722a07c484a60d63692361b558f037', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-TwinTombs.itt', size=1954, md5='728365dcbaf248ef218f0d65b9e086c6', mtime=1077992297, source_media=media_ut2004_cd1),
		manifest_file ('System/Core.itt', size=4063, md5='7e5e3437551c9bef2212f4b1a3af7913', mtime=1077019415, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-1on1-Joust.itt', size=520, md5='0a241c1bbd6b6e2c1b4185db897ea9cf', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-AbsoluteZero.itt', size=2265, md5='aec43ece50d9d7b644aa1c234b6dc9a8', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Avaris.itt', size=3083, md5='e8dfd561fd85e56f77ca1b0972988e1a', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-BridgeOfFate.itt', size=2591, md5='def2815ef4dc4f4fc8c9ec87a6fdf7a0', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Chrome.itt', size=1306, md5='11bd8fdcf40e1bec1758a26a073e262b', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Citadel.itt', size=1134, md5='f71908cbd78f589361520d7761177634', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Colossus.itt', size=770, md5='1562f865dccd62b158b85d4a17ee73d9', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-ElecFields.itt', size=2142, md5='1678e84ae441107651dc02a3036f85fa', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-LavaGiant2.itt', size=1177, md5='c88159a1191a873c9af41672b1c8ae9a', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-December.itt', size=2266, md5='57fbd642602a291b8dc3a03cc3dadca6', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DoubleDammage.itt', size=3450, md5='7ba23a1310ad4597f19cb3cad1661ef5', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Face3.itt', size=1153, md5='10cb058ea59502f8e9d7f1b472d4030f', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-FaceClassic.itt', size=1811, md5='f4ebfac02ccdc72726c707319a58a5f4', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Geothermal.itt', size=1333, md5='2c58a28729c79d2616bba6f66f8f7b1b', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grassyknoll.itt', size=1002, md5='9eca276b1dc9be555e65c904ff6bc56b', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grendelkeep.itt', size=3809, md5='bf8ec62136286ce49f0c7ea52c32e638', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-January.itt', size=3702, md5='6e400d6dbe0bd2738a67aa3d4f3d4653', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Lostfaith.itt', size=287, md5='258cd8ec4fa02362d5d78d99685fe25f', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Magma.itt', size=988, md5='4c1519c8fc8ede3b0fb4361a7cc4c5ab', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Maul.itt', size=296, md5='3a2f0c6d4d0b3ce537ab3cc8d88547c4', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-MoonDragon.itt', size=989, md5='d04230d8fa81473617e23d064b7e0063', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Orbital2.itt', size=1527, md5='c31b8f62268aca3d631d8398cdb240d2', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Smote.itt', size=3409, md5='ee62fa4ac604c06f1c4efccaa52d7377', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-TwinTombs.itt', size=2275, md5='17bcf695fa1e5713a2bbcccf9cf975d3', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/D3DDrv.itt', size=367, md5='404a40fc17324bcd818f7492ee6b9780', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DemoLicense.itt', size=15794, md5='ae6a5b3ddff07443b10df0dbd8c01460', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Albatross.itt', size=879, md5='3d12b11092477783265bc30353a7b021', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Crash.itt', size=823, md5='56d17dc6f2a605aa8e2b8c5adb84468a', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Desolation.itt', size=945, md5='5a3c4e528add42e3bf026c5a0beb1f1d', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Idoma.itt', size=328, md5='7f808f99f40e57ea13aaad215d9c263f', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Irondust.itt', size=611, md5='ea75abc6e5a045d7cb30cdcb6df67574', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Mixer.itt', size=674, md5='4dbee07b3741a44bd632d7e4198f4985', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Roughinery.itt', size=441, md5='2ce27756b03e4bbadce95bb8926bc962', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Serpentine.itt', size=255, md5='27e63757019fae2acfd52dd42efee658', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Spirit.itt', size=556, md5='53428c9ee102bd8c7ac82fb07a80e9e2', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Squader.itt', size=959, md5='3682e20d0d6b327ccdd3ce29e2b029ad', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Trite.itt', size=483, md5='6a0eef890a9d691aea96e877ea35c0a1', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Antalus.itt', size=625, md5='cfa7d00694df9f0c29d807be43e24f55', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-asbestos.itt', size=834, md5='5c26e06ac82a64e6512ceddfb9f50166', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Compressed.itt', size=868, md5='8ef797703effad5ce349c5c52b985209', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Corrugation.itt', size=1221, md5='17e4268a373fd50c10d6973530a474dc', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-curse4.itt', size=1869, md5='237811f83ff8560c4cb6563ad3fbb56b', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Grendelkeep.itt', size=1613, md5='67955bfb99b92b8698115f73dc7b097c', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Ironic.itt', size=1311, md5='cbbb4be7ee95186582b227f822410a8a', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Osiris2.itt', size=1058, md5='c216caf6992fb7fe8e90fc2b0552fb16', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Deck17.itt', size=3016, md5='c94d35ef23c518c1d43beb696dceff2d', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DesertIsle.itt', size=497, md5='5ac5ad90410030fdea79660c85220129', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Flux2.itt', size=375, md5='89bb918db1c58ad9095c80bd1313241d', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gael.itt', size=107, md5='0678b141e29f755ab0fefdaf31a260a0', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gestalt.itt', size=615, md5='590043bbb1673851258b3793fde475b8', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Goliath.itt', size=1115, md5='53949077299207388fa72357caab680e', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-HyperBlast2.itt', size=833, md5='3138f51e2351f8789c194e9d67680850', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Icetomb.itt', size=1026, md5='cca9a33f0d56ecf026d45f2f7acf8bb2', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Inferno.itt', size=861, md5='094323d08efdccd38337d4829ad9b284', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Injector.itt', size=1000, md5='6779be93d3eed2d742fbe011d5ee4f66', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Insidious.itt', size=761, md5='cb0e57d7c5ee44637c0dbef21d2db95d', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-IronDeity.itt', size=906, md5='a3fcfebd3bb6c5bec10e07db89370fc7', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Junkyard.itt', size=446, md5='5d1dc32a9b98ce1606c444b8e10746ee', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Leviathan.itt', size=652, md5='5a6791d10dcac9639c2a331b7fb37023', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Metallurgy.itt', size=1415, md5='c12723a1713dc9f0861d056cf44de4b2', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Morpheus3.itt', size=1028, md5='3e028378a61f29b3dfbcef9d9adc420e', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Oceanic.itt', size=674, md5='ec098cdd01c9f5f545836c76211c1e7c', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Phobos2.itt', size=1472, md5='5519b95fc511f4e4012de333e0af35e5', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-plunge.itt', size=125, md5='fb41589255e5c9ec6cc2d7fa48309435', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rankin.itt', size=427, md5='a358890ac129b323fe1baf6e3bfb63fa', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rrajigar.itt', size=329, md5='df5762b4987f19359e7a7136be2f9530', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rustatorium.itt', size=340, md5='7bc21214955dc1205b738ca00acd61cc', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Sulphur.itt', size=583, md5='3df698ee4ba14fb788069a04902c3134', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TokaraForest.itt', size=252, md5='ace8fd8006c0c950bd44ce35f1303252', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TrainingDay.itt', size=229, md5='93b7eceb4c1fdeccc0ac72c4bb8ebbff', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Access.itt', size=852, md5='209d705d3a76a3a2ec2c7fcda86832d7', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Aswan.itt', size=951, md5='f2c5eaeb261d456b2bffae6437fb186f', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Atlantis.itt', size=1117, md5='d4d0036896794d27f3a04f654e102beb', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Conduit.itt', size=646, md5='79070060df901cdeae6d48570a1ed6a3', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Core.itt', size=179, md5='a33a407ff867c1f442c985474e653d38', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Junkyard.itt', size=424, md5='b527f847b10c3a91a35804a33101b174', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-OutRigger.itt', size=1127, md5='3cdf9fb5210ea0c1067714109c6457f7', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Renascent.itt', size=538, md5='79277a10e496e731b99363f1a8466613', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Ruination.itt', size=284, md5='9893217abaede1065847b251417108aa', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-ScorchedEarth.itt', size=1024, md5='8550a8018e98024b84c352f22c083d58', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-SepukkuGorge.itt', size=322, md5='f48f16e666664862478bf1855c2ddba5', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Suntemple.itt', size=1042, md5='a7dedc0382e895ed88c3f67890669126', mtime=1077992298, source_media=media_ut2004_cd1),
		manifest_file ('System/Editor.itt', size=6434, md5='f37c3055c3a9a97417aaef8361ca44c2', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/Engine.itt', size=20548, md5='1105d8dc8610c64f2179f58725b45edb', mtime=1078087645, source_media=media_ut2004_cd1),
		manifest_file ('System/GamePlay.itt', size=8235, md5='efa1e625fd46872def503ef59a42fecb', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/GUI2K4.itt', size=90921, md5='d3508463c8cfe095d93874d52f69a09c', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/IpDrv.itt', size=1600, md5='7460fa3d70f133931ebf2ba2eba0ef9a', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/license.itt', size=19924, md5='2cffbeb161d18b4cc4491568d631bc3a', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/Manifest.itt', size=2502, md5='e5c0261dce97d998891c4b3218226cf0', mtime=1078360699, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-ArcticStronghold.itt', size=792, md5='343af78f97ea2de527b2abbc8c46f2ce', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Crossfire.itt', size=1016, md5='9148d6981a73275b64cc4c4d0ca4e890', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dawn.itt', size=905, md5='35ba02ab671136768ffc57b091894f3d', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dria.itt', size=1252, md5='b9354f049de61798e3e0c0d02a835284', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-FrostBite.itt', size=2088, md5='ef8e3d07f77b79141711bedec309399d', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Primeval.itt', size=495, md5='dae4ded39db8849dce1ed2fecd0e175f', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-RedPlanet.itt', size=913, md5='a956717bd666dbba412ffe6847d8fe80', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Severance.itt', size=824, md5='c027c1989ee8f67bdaa8174e923e2386', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Torlan.itt', size=1230, md5='617fa23cd03d5f077cc2986d90364405', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/Onslaught.itt', size=16228, md5='9a20ed294c1cfc091cdab0ef6c46ed43', mtime=1078361058, source_media=media_ut2004_cd1),
		manifest_file ('System/OnslaughtFull.itt', size=1653, md5='2606072b1ae6ecc5eef08e4c054de350', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/Setup.itt', size=9612, md5='2cae06977554be593dbc43af84791e74', mtime=1078360865, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Demo.itt', size=1453, md5='e8a9e9297bb85556b8d024e35b5acc46', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Full.itt', size=2378, md5='f5f3e03ec4e5dd9da04e9014ea21653e', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2004Demo.itt', size=1529, md5='d7fe6e180b23a0597d646ca307f3e1d1', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/setuput2004full.itt', size=2502, md5='2d1b613a1586fc42b3db1db28d13845e', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/SkaarjPack.itt', size=4265, md5='5c164847a13e147b80cb81036901dce0', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/Startup.itt', size=2025, md5='2173e68b028f321d56d3ce7d96329d30', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-BR.itt', size=2030, md5='ff53128a31e9114c88c9e732943226ed', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-CTF.itt', size=78, md5='c9f6faf4f76d0aae67c7a393a4d4301a', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DM.itt', size=134, md5='946acd6b5a65be8f137c51b3d98686c2', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DOM2.itt', size=858, md5='f04a01daef6e07ebcc069492ab938fa6', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-ONS.itt', size=126, md5='764b54138627d0bb26463c82ebf81bf5', mtime=1078008822, source_media=media_ut2004_cd1),
		manifest_file ('System/UC.itt', size=167, md5='eb67acf953d11607ea2dd29ab347aba2', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealEd.itt', size=174, md5='0de397e99219786102620896e7782941', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealGame.itt', size=14421, md5='6789a6af6f501752dc56dcb37a7c3a92', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2003.itt', size=192, md5='a183212856365ec54314d6e96148c072', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2004.itt', size=191, md5='f2255c4ef75843b6c2bd0d26250a0f03', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4Assault.itt', size=7498, md5='f479e99d4c3ebfbc4a12b52928aaf94e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4AssaultFull.itt', size=1794, md5='f407cd094cb34ad01ff798a21b76daaa', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/utclassic.itt', size=2561, md5='349957a38e16a114f0ba50dbdb8b7889', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UTV2004s.itt', size=272, md5='5c0b3eb6e884a5f105fe263479c12aec', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/UWeb.itt', size=122, md5='4aee0dfbe96d727a9ad0332f4374e121', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/Vehicles.itt', size=228, md5='f6d45710a569beabbc71a747eb9aef01', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/Window.itt', size=2463, md5='837a94a840e86907aa16cc8c341da5bd', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/WinDrv.itt', size=730, md5='210e43cc49b1af51055835ece0055de7', mtime=1078171858, source_media=media_ut2004_cd1),
		manifest_file ('System/XAdmin.itt', size=2843, md5='94fc3b7c9f373b1e40d2ef538087a8dc', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XDemoMaps.itt', size=1294, md5='f9629d45f82a2b79e70ed5e889546385', mtime=1077983487, source_media=media_ut2004_cd1),
		manifest_file ('System/XGame.itt', size=23145, md5='fe74bb68ea9784b42e9ba7cca30a426c', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/XInterface.itt', size=56035, md5='4151e77eed4db3f7702a1d2ddc7254f2', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/XMaps.itt', size=9458, md5='ea28966d2be0be54d542da8ab12dc98e', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/XPickups.itt', size=481, md5='c40685798ff7840c081738100626ae5b', mtime=1078237828, source_media=media_ut2004_cd1),
		manifest_file ('System/XPlayers.itt', size=27132, md5='92020e71f73f9e04727e7932873d79fd', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/xVoting.itt', size=12315, md5='c830bb3f16ad67cb421b59f49d41d6c8', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/Xweapons.itt', size=22434, md5='fd16afc5abffcec3f6957ffd4d9fdd8f', mtime=1078081003, source_media=media_ut2004_cd1),
		manifest_file ('System/XWebAdmin.itt', size=7121, md5='b5668faeeece7243692f7bbb8789d00e', mtime=1078081003, source_media=media_ut2004_cd1)))

ut2004_3186_kot = manifest (
	'UT2004 3186 Korean text',
	items=(
		manifest_file ('System/ALAudio.kot', size=480, md5='4a5af14d2bf358ac7ffacf00ab8b1186', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Convoy.kot', size=7780, md5='52910a60bcc33fd89d29209f76d0f9cb', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-FallenCity.kot', size=6016, md5='4683fbdac1e10115eb41cab7a3df8ae3', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Glacier.kot', size=11900, md5='0b279644fca5fba90ead0b4e6610eb8e', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-Junkyard.kot', size=5614, md5='93a9a180507e9ae74e66da446142dc49', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-MotherShip.kot', size=14912, md5='79eb78cb2d6f07f3582d80f111d41798', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/AS-RobotFactory.kot', size=8114, md5='b6a2741f3b1cc33e11310e265bf00595', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BonusPack.kot', size=7100, md5='ce6bdc4d254eba0d386483cc713821a9', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Anubis.kot', size=3042, md5='ff19934e8f8e03c6cee0c22ac9817bb5', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Bifrost.kot', size=1358, md5='5428779ea7f95ffc71a421d5d4a9609c', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-BridgeOfFate.kot', size=2214, md5='01f00393654defc3f63d9bc7ace85830', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Canyon.kot', size=1136, md5='f4b0ab6cf46b0eed57ebe668357b903b', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Colossus.kot', size=932, md5='107cfb6caca0ff13ef46b477f71abb8b', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-DE-ElecFields.kot', size=2988, md5='8478cdfaab8ec6cd3c2a813031c966b3', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Disclosure.kot', size=4524, md5='ee103d99c74d2a971e51f74d26914c7f', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-IceFields.kot', size=740, md5='4bdf13968409dc717b47cf33d639493c', mtime=1078270941, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Serenity.kot', size=1224, md5='a20e6243609ca659ba4732a8762d654c', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Skyline.kot', size=618, md5='c9f62b29d1fc83e674abef779297c5a3', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-Slaughterhouse.kot', size=3270, md5='bc7f72f8a49836c19cd45bc0a4e0142a', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/BR-TwinTombs.kot', size=3086, md5='ced0f2b5ae1c8abd2173216ec0f7aab4', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-1on1-Joust.kot', size=422, md5='5d83896e60a8bf79a15be457d1ac0745', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-AbsoluteZero.kot', size=2994, md5='2b8357f68a855d66fe62222d991e5814', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Avaris.kot', size=4882, md5='c14ff560fc3b1db982fce1911f02f62f', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-BridgeOfFate.kot', size=3610, md5='45b1195d3bf1a3b2c46a47ef67202710', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Chrome.kot', size=2112, md5='77518db37dbba974c396c3127929f32a', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Citadel.kot', size=1768, md5='aabb143118a63c904f282df3ad5a586e', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Colossus.kot', size=1000, md5='8c1027d787b81224c695de9e717ee79c', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-ElecFields.kot', size=3096, md5='99127eee40880adf2d7c162724bb74c9', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DE-LavaGiant2.kot', size=1664, md5='5dc28fc107423b0c1522fa55621f5378', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-December.kot', size=3534, md5='c34cc62e5927ac93f3c7ff49e4967710', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-DoubleDammage.kot', size=5184, md5='8300c61156f900b2aac23b17ec032bc6', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Face3.kot', size=1980, md5='8c7dd7d6a347d89b54ddd559ce312af5', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-FaceClassic.kot', size=2376, md5='56115195509f9224c35bbd2a35f6dcd6', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Geothermal.kot', size=1996, md5='6143083bb4f13e9bc876bfd7165aaa5f', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grassyknoll.kot', size=1396, md5='db5548ddd6bdb3d373411b5574333f08', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Grendelkeep.kot', size=5572, md5='6805e6ddead5c92e94b695561cdc5032', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-January.kot', size=2810, md5='32a963ff8c40e2bea54e0da0627ba7fc', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Lostfaith.kot', size=494, md5='02b8dde2952b04564b609aefcdebaf75', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Magma.kot', size=1702, md5='7b5b08c05c272ad891553186002651b4', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Maul.kot', size=526, md5='7e1be6a24a15cea915a41248d7d1ee0b', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-MoonDragon.kot', size=1538, md5='47c3bb238e80da437c4f3e066789704a', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Orbital2.kot', size=2320, md5='52d7d3e79232ffeb0c2ffa7908fc0805', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-Smote.kot', size=4938, md5='fe220fc9fc3c243e847f8a4f40ef3958', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/CTF-TwinTombs.kot', size=3342, md5='fea414f4250610fd84df04249786621e', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/D3DDrv.kot', size=646, md5='1956492d7bf861bfe95ffec9cf998a09', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DemoLicense.kot', size=6937, md5='bf222b06a51aa7eb04423627a8795f08', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Albatross.kot', size=1266, md5='e336cd9a41385ecac5574ac40a18ea3d', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Crash.kot', size=1160, md5='b1373741dcfd06a39de08a22e61f1736', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Desolation.kot', size=1144, md5='0e151a38320856aaf3cce7d3f4c0aef5', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Idoma.kot', size=498, md5='1d00fabad87bb1833dbd72ef19ac709c', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Irondust.kot', size=940, md5='e654d18a6cc34697df810f930f5988d4', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Mixer.kot', size=1138, md5='14bfaaa8bce3ff84bb3dde1bc81f5bd3', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Roughinery.kot', size=552, md5='d05e1fd4aff87182c2c58b29e8e43a0a', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Serpentine.kot', size=404, md5='73e648b801209563854fd673282b7385', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Spirit.kot', size=770, md5='bc6be78068ee4a163d111e3d17454263', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Squader.kot', size=1300, md5='d2061f027f10743645c7202f7eded819', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-1on1-Trite.kot', size=726, md5='550d6c0a29aa69e8ab5eda6cbb0cca91', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Antalus.kot', size=1036, md5='f7f210e2708d99eef1e2fc776d20c627', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Asbestos.kot', size=1436, md5='013131001693ac3bda97bd3c508258e8', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Compressed.kot', size=1324, md5='239e11df1ba540fc4b62e10e155fb191', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Corrugation.kot', size=1858, md5='4e7f6aa4b35355d8b0e082cca955801e', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/dm-curse4.kot', size=2632, md5='327b07c883f05bce0dcb5d611c8052d2', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Grendelkeep.kot', size=2134, md5='04f894f407e92682a8491d1ba719c17d', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Ironic.kot', size=1892, md5='740625362164d219a0c1a48ddbbd7f19', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DE-Osiris2.kot', size=1418, md5='42e6a3aa23407f034145188b9ab5de25', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Deck17.kot', size=4252, md5='7cef2568e1820090e79b3638edcdd010', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-DesertIsle.kot', size=640, md5='26500fe2c4b4560445adc72ed465fa58', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Flux2.kot', size=626, md5='395b227f3b4c3745103e68426f9f53b6', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gael.kot', size=190, md5='be6447bfc580d311c6a4ee71a07ff29a', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Gestalt.kot', size=788, md5='a269d9e523c54d6783f6dceeb827083c', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Goliath.kot', size=1388, md5='eddb7d3fc06a8ac2a1a32688e9c6ab2a', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-HyperBlast2.kot', size=1562, md5='23da98fb6f94bee7b1be0f6138eba8ab', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Icetomb.kot', size=1534, md5='e8d587e2c8acfc32e0210b3135a39edc', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Inferno.kot', size=1436, md5='54c90c919c0da17a40ae5bb8445014a2', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Injector.kot', size=1454, md5='072d7f60df091ca59b041be3fa40bcba', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Insidious.kot', size=1180, md5='17aec8256c926500faceedb3f211f8b9', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-IronDeity.kot', size=1278, md5='c1fc51d67de6e7932e7825385a6505c4', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Junkyard.kot', size=626, md5='8ffa4b993f5f9484ebaa1569f3285b78', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Leviathan.kot', size=960, md5='5c84c7815577152cc07d15c03ead38d6', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Metallurgy.kot', size=1972, md5='04a3ff2bd8dda3796cb3e8f56b25408f', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Morpheus3.kot', size=1394, md5='5b1a776d07d319541848ca009399e95d', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Oceanic.kot', size=1068, md5='4a48eae0aa1c95e10fb509bf98d212b1', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Phobos2.kot', size=2326, md5='5a330a734d8398d0229cd5feaf478f90', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Plunge.kot', size=202, md5='2e6d6cc2804be6373fd3ac916258a66d', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rankin.kot', size=602, md5='5042cd629a85f9d1b3ab65e1478a282e', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rrajigar.kot', size=528, md5='ec58daca1787dee3834949a01362d148', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Rustatorium.kot', size=446, md5='e205e9eca0db4298a3016ccf099cb17c', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-Sulphur.kot', size=658, md5='44db8400bd0f1d3eae59b99fdb01da8f', mtime=1078270942, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TokaraForest.kot', size=396, md5='da41122e05cef26ade6d496116c1d306', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DM-TrainingDay.kot', size=354, md5='ca26fffbf64abc883d45a2514adbe88e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Access.kot', size=1220, md5='6bd268c805ed24baa9cbfaf5b88a23b6', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Aswan.kot', size=1242, md5='c12196c4b56a28e41f5d0d387587c563', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Atlantis.kot', size=1720, md5='2b1f9c6edc133e6ce8631b77c6e47f7a', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Conduit.kot', size=766, md5='6fa321f0f0ec04950f24f58d9d6bae02', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Junkyard.kot', size=620, md5='c2fd522213f53bc0a329409c4c25c3d1', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-OutRigger.kot', size=1814, md5='822dfb6cef6ba7c176220b8fbb905534', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Renascent.kot', size=752, md5='0e6a6b29cf766767690f805ce2529a99', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Ruination.kot', size=488, md5='2f9bb77d89db11de4a1b48b13a6d6019', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-ScorchedEarth.kot', size=1556, md5='a6c0668c3a6c161909d10808b6d2da47', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-SepukkuGorge.kot', size=542, md5='29c4fa02f6706dba62ee6f80083b79bd', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/DOM-Suntemple.kot', size=1696, md5='ca61f1baeb6334654e0194804bb10bbf', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Editor.kot', size=10524, md5='ce325218ef78ab862afdbf2f697f8728', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Engine.kot', size=31480, md5='8c2475d09219cbc17d1addca15820db0', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/GamePlay.kot', size=12874, md5='4d100369730a38b28a8b44defe0be810', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/GUI2K4.kot', size=127234, md5='315c9cbf963720b2f6bfb338d40274ca', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/IpDrv.kot', size=2754, md5='aaf56d79c1ef9e95bec01a14e73794a8', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/License.kot', size=12702, md5='11c56e62bb03ff83feb42b533da46d74', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Manifest.kot', size=3474, md5='d737e28c33078ddb8db104538eaa725d', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-ArcticStronghold.kot', size=516, md5='b137cb3a6cf97cbeec533803d127f6f3', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Crossfire.kot', size=510, md5='8c1a65d4d9feda54ba2c4aa70aa215d2', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dawn.kot', size=378, md5='f76129044c95e946d28abcd4b902ebe2', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Dria.kot', size=610, md5='e8ce0abc82cd73c34d2d2dc01aee937c', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-FrostBite.kot', size=2506, md5='e27d0a4e1353eba71113a6badab610c1', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Primeval.kot', size=716, md5='99303cfe64fccb4ceaa92c873faced80', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-RedPlanet.kot', size=548, md5='13a1fa6942b3b19140a121933a77785d', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Severance.kot', size=1210, md5='a64f10bd5b89e3992618f57ca99576ec', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ONS-Torlan.kot', size=1528, md5='571fb6c65cb888056f51d09b8b24ef7e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Onslaught.kot', size=21896, md5='2f1081ef17a59340ce6bfea7c354cc32', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/OnslaughtFull.kot', size=2484, md5='9296260747204920bcc0c984055b6971', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/PROUI.kot', size=7536, md5='b4ddced4d39033f05017fa02607bc3a1', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Setup.kot', size=12318, md5='40bbb6b7cac9fbea9a052a628f138582', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupBonusPack.kot', size=1092, md5='2b3306941e6798bce9f8114bbda68c5c', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/setupbrightskinsmod.kot', size=1104, md5='314b5499a3edca00c7d7c0b40dea084e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/setuput2003patch.kot', size=744, md5='0d993d7efb22d4f0b9b8b0af8a9abe15', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Demo.kot', size=2274, md5='ae02a6b75bb823fcd8990603b1f40346', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2003_Full.kot', size=3452, md5='07fa5b09d53957c75ac6bd4455313713', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/SetupUT2004Demo.kot', size=2376, md5='7c2f3fd2a910134cba75be709038904c', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/setuput2004full.kot', size=3474, md5='d737e28c33078ddb8db104538eaa725d', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/SkaarjPack.kot', size=6458, md5='5e9800aa93c4f813b5cac3e4c4ad74fe', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Startup.kot', size=2566, md5='a8848078aac948404e790f366dcaed74', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-BR.kot', size=3140, md5='85b26e2a750b1238335833906ba81713', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-CTF.kot', size=146, md5='ad20fe518b93af63cb7a103b47cfae4b', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DM.kot', size=254, md5='7e280b1eaf128cae38c9c12ff4b03867', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-DOM2.kot', size=1312, md5='94327a5e9fee918e0d122ab8dc427856', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/TUT-ONS.kot', size=190, md5='5a366cad27408007675ab7e266dcb569', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UC.kot', size=242, md5='0f9967245c3bb11e62760eb43f40045b', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealEd.kot', size=282, md5='f5f5f359b8dc6c4eb3d35cdb2da9c79e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UnrealGame.kot', size=18922, md5='02814e8a4c1ba43d9e50d2b3770e3124', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2003.kot', size=290, md5='02beec07cb90a5f66d92a4dd588f60a6', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/ut2004.kot', size=290, md5='2666b9a9fb307169386da5744587663d', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UT2k4Assault.kot', size=9858, md5='98970d75354804bd7d397f99683eac89', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/utclassic.kot', size=3486, md5='95a8433eaae7c08851175f7009d75c18', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/UWeb.kot', size=232, md5='caab15cc45927d637f42754b2a365b39', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Vehicles.kot', size=342, md5='fd1bc0d72166a316bcc2de19e98085a9', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/Window.kot', size=3686, md5='dfb38c591f8cf6c7604f027066e169f2', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/WinDrv.kot', size=1186, md5='c39654bdf39b8aadc704ea595524e10c', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XAdmin.kot', size=3720, md5='2e9772406d7bc8d00dbed226f0d40509', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XDemoMaps.kot', size=1276, md5='8951b121c495ff998e704032a7aacfa9', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XGame.kot', size=32084, md5='5b4a642325709080acc1de006b82627e', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XInterface.kot', size=81024, md5='0b9dbb9264955928f46382e7980361db', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XMaps.kot', size=9442, md5='feb79a6301109f2a52704272d7b65c07', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XPickups.kot', size=692, md5='3de76510ce07a432dbfd8f675010c88c', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XPlayers.kot', size=32108, md5='718138291a475e96ff0edd1af2e498b3', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/xVoting.kot', size=16122, md5='e844768af6045be122c9aa44f37a9f92', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XWeaponList.kot', size=4718, md5='baf98d369731b4f9aaae406af5c5ed5d', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XWeapons.kot', size=24824, md5='0e800d8c49eca7236ff198d4770eb4d0', mtime=1078270943, source_media=media_ut2004_cd1),
		manifest_file ('System/XWebAdmin.kot', size=8768, md5='561c500f56ee1ab4df49548e759db76d', mtime=1078270943, source_media=media_ut2004_cd1)))

ut2004_3369_2 = manifest (
	'UT2004 3369.2 patch',
	items=(
		manifest_directory ('Animations'),
		manifest_file ('Animations/MechaSkaarjAnims.ukx', size=496077, md5='7836f3b4b1b9836f4b80c4cbc39e1fa7', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Animations/MetalGuardAnim.ukx', size=428825, md5='1920da5831c1c7d36fdd7412e68bbe7d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Animations/NecrisAnim.ukx', size=445581, md5='620b2900f3f6cdbae9cce2f736fc4e2a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Animations/ONSBPAnimations.ukx', size=4067595, md5='c64ab49910aa5c90a8fb65c3f01b2b90', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Animations/ONSNewTank-A.ukx', size=226325, md5='f1252647551b508830c42b9bc73ac08b', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Help'),
		manifest_file ('Help/BonusPackReadme.txt', size=4780, md5='56419f675278cbcdbb0602a68cb7530b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Help/UT2004Logo.bmp', size=221238, md5='bfbbb59fa17c0be1f6312a6e5e0a1352', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Manual'),
		manifest_file ('Manual/Manual.pdf', size=4098760, md5='9b90bddedd3c773a0c3b5d330cd050cf', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Manual/Unreal_CH_3_Excerpt.pdf', size=1848387, md5='41bd72e293a871b4b77dabc1f38b3891', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Maps'),
		manifest_file ('Maps/AS-BP2-Acatana.ut2', size=27248098, md5='bdc0aa73e08f3584949a8a7c33fdff90', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/AS-BP2-Jumpship.ut2', size=34694300, md5='5e950f707af33cd15b6fd270ca2c6ac4', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/AS-BP2-Outback.ut2', size=33024125, md5='03499e69b8da7263873624f039745d9b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/AS-BP2-SubRosa.ut2', size=21109082, md5='506af53e583540b0696b822df912a5c8', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/AS-BP2-Thrust.ut2', size=28001510, md5='e07c3b3b9f71877a7872063c21810b91', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/CTF-BP2-Concentrate.ut2', size=23598920, md5='2bbd4eef091788dff191cb93028cbea0', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/CTF-BP2-Pistola.ut2', size=19549858, md5='363ae86514bcf53a0c8c53745a7b5218', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/DM-BP2-Calandras.ut2', size=29877347, md5='b3ead46227c7a6beaa882dd3eba5e97c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/DM-BP2-GoopGod.ut2', size=22261333, md5='0c4013e1092640bab8abc0d1767a63ef', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/ONS-Adara.ut2', size=9784251, md5='04e5ce99c4e4ee00fc5ff48d6f4c61ef', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/ONS-IslandHop.ut2', size=11489239, md5='0e4a8d418ac506e07438b9e3e30fa539', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/ONS-Tricky.ut2', size=9540116, md5='b7efa1c47f378513829fc9053666dac0', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Maps/ONS-Urban.ut2', size=27155290, md5='0a55185f4f109a01fa140a2962fbdedc', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Music'),
		manifest_file ('Music/APubWithNoBeer.ogg', size=1285984, md5='eec872bdb55f3676e111e82714454246', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Sounds'),
		manifest_file ('Sounds/A_Announcer_BP2.uax', size=27286938, md5='4333372aa0359d444785c1080c1af8f7', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Sounds/CicadaSnds.uax', size=1070922, md5='2a73cb8eb0ecc348fec3d04e590eed0d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Sounds/DistantBooms.uax', size=211342, md5='619b12592cb5ea68ab3090c475bdd63a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Sounds/ONSBPSounds.uax', size=3309887, md5='e94459edcc242c5e1818f50fc8c309b2', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Speech'),
		manifest_file ('Speech/Dom.xml', size=1387, md5='ef2aeefd5190582a654d1ef8ae83c440', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('StaticMeshes'),
		manifest_file ('StaticMeshes/BenMesh02.usx', size=2164239, md5='437e43eb0c48e8a8fea2dbb178b6f687', source_media=media_ut2004_3369_2_patch),
		manifest_file ('StaticMeshes/BenTropicalSM01.usx', size=1856531, md5='02020c5d49bddc08d82abfea59fe9c80', source_media=media_ut2004_3369_2_patch),
		manifest_file ('StaticMeshes/HourAdara.usx', size=2869780, md5='0877fe01e125d19b83b8131264207167', source_media=media_ut2004_3369_2_patch),
		manifest_file ('StaticMeshes/JumpShipObjects.usx', size=5041804, md5='b7f983ea84c81b91c0b3ae27499f3434', source_media=media_ut2004_3369_2_patch),
		manifest_file ('StaticMeshes/ONS-BPJW1.usx', size=1173907, md5='e62eb602c8afb4b3e5e9f1a0acad3d25', source_media=media_ut2004_3369_2_patch),
		manifest_file ('StaticMeshes/PC_UrbanStatic.usx', size=3384813, md5='602d6afb2fbb891c38c726c77c2de95c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('StaticMeshes/Ty_RocketSMeshes.usx', size=812372, md5='b8dbcbc3fffd05e312f02f8a58f9d426', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('System'),
		manifest_file ('System/AssaultBP.u', size=871, md5='f28de65fc9ddfe38f1e99d39579b4905', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/BonusPack.u', size=161218, md5='f63df930572a211681fb99e64c90cab2', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Build.ini', size=55, md5='38a4f15186a4aa49578ff4a57009676e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CacheRecords.ucl', size=173664, md5='df2270cdd5837b1f5155f10929998c62', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Core.u', size=74837, md5='7c56df7e3b1d3ba9ab22bc2409838c5e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Editor.u', size=458731, md5='8691b7d6d30f0e8d55aea36f30c5c0f3', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Engine.u', size=2720630, md5='1972d14c57d05ffdc82c51be76c13d29', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Fire.u', size=16865, md5='64ef0e15f9cffcbf367931f69c4c5b46', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GamePlay.u', size=219726, md5='3dd9b1f931e09b6ed9c0596925077e24', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GUI2K4.u', size=2400421, md5='2f8d1294832ac5f3e4f93ebeabf1f391', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/IpDrv.u', size=81436, md5='5ca83787542093a1fd90163580022202', source_media=media_ut2004_3369_2_patch),

		manifest_file ('System/Manifest.ini', size=16118, md5='5a8cadc67cf9775278b535c001bca625', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Onslaught.u', size=1052899, md5='19fe213e4fe93b04f63443fc1dc3947c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtBP.u', size=326140, md5='4ea9135f97d97c4cef350c760011265c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtBP.ucl', size=1461, md5='6b114905e91d6bbba1ff94caff447abb', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtFull.u', size=155983, md5='ed4a6c9479731fe22ebc3e1f41cda7f6', source_media=media_ut2004_3369_2_patch),

		manifest_file ('System/Packages.md5', size=64146, md5='0b8cccc89cd5e8c3a4083d81f8bddb54', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/SkaarjPack.u', size=300335, md5='8e060e901a5c61d8d5f2703814aa351b', source_media=media_ut2004_3369_2_patch),

		manifest_file ('System/UnrealEd.u', size=16345, md5='19889324d6db28cbfc5c163779c8613e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UnrealGame.u', size=1215037, md5='c3b686458fc25e5b069238ffef56a8bd', source_media=media_ut2004_3369_2_patch),

		manifest_file ('System/UT2k4Assault.u', size=1025891, md5='fc5fe8ee346c285e06078516fdf35968', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2k4AssaultFull.u', size=234189, md5='b1beb39b0be7024aabd46b73a4a79eca', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UTClassic.u', size=71779, md5='41c404c2b7d99fdb45c6982fa477b626', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UTV2004c.u', size=79305, md5='36680a4779a6994301c7913e9f298ad7', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UTV2004s.u', size=13317, md5='02425602e908050baa9a32105e9eb9d1', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UWeb.u', size=35219, md5='6116413e82bb2ac4d33ec4da9c40ce68', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Vehicles.u', size=88554, md5='a2f03e3b5295a6349066dc7019642794', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XAdmin.u', size=83092, md5='2f36a67e966b79bb14d28e1e23430757', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xaplayersl3.upl', size=2306, md5='5879a410cd702ea7c2e3a5bdf3d4bc8b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XGame.u', size=943405, md5='dcd6f59ff5bf6ef1e284f454446ba626', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XInterface.u', size=1999988, md5='122c943b76791512fcb2f70f5130cd48', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XPickups.u', size=18753, md5='098f23cba3b593074f98a4d2fc514ab6', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XVoting.u', size=404816, md5='fd62ff83dbc37cb2ce3d30a7fb37e4ff', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWeapons.u', size=665037, md5='fca1b41d868d93624556376fbdc56fea', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWebAdmin.u', size=288545, md5='3b9f48fc17408a56db019d227ad91d79', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Textures'),
		manifest_file ('Textures/AW-2k4XP.utx', size=1055954, md5='2bc86dabfb646d356bbd49a2099ac1c3', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/BenTex02.utx', size=10916717, md5='f513bfc3aded054d96431b4464be26e4', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/BenTropical01.utx', size=11878293, md5='1b0f08586b08ca922599706ac5246804', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/BonusParticles.utx', size=204869, md5='e49340bd4a86eb4769ad618bd1da0361', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/CicadaTex.utx', size=106905, md5='e4a2506b6b6cc7c3437aa529e387eabc', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/Construction_S.utx', size=30978056, md5='ebe36178d4c7a8ef2a930d85ee724cf3', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/HourAdaraTexor.utx', size=8334858, md5='144c0fd25fa6b6b0625ea9955ca490a0', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/JumpShipTextures.utx', size=12999295, md5='50eac2dd51372a9094cc02eb9d09bcf8', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/jwfasterfiles.utx', size=175512, md5='545b8e20b7fa12bed4746236de25132f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/ONSBP_DestroyedVehicles.utx', size=6067170, md5='c03539bf7d723257be31471f51675d6f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/ONSBPTextures.utx', size=11896262, md5='6f46f9369fd117da36c742f1d6520cbc', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/PC_UrbanTex.utx', size=11132887, md5='d8b68ad74a179962430f5f099c11c99d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/T_Epic2k4BP2.utx', size=1621141, md5='cd5f286410f7495ba61bbacce5029e9b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/Ty_RocketTextures.utx', size=15432103, md5='57ee4a47ccccb5b1defaeae272d79ea7', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Textures/UT2004ECEPlayerSkins.utx', size=22905347, md5='76ea74bbb952d97be7793d828c1688c3', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Web'),
		manifest_directory ('Web/ServerAdmin'),
		manifest_file ('Web/ServerAdmin/Admins_home.htm', size=773, md5='6328acfcbfabd9ac3286e5fe7a5219d2', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Web/ServerAdmin/ClassicUT'),
		manifest_file ('Web/ServerAdmin/ClassicUT/Current_bots.htm', size=1170, md5='cbfe89f8dd808351f121f4c149df3d8a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/Current_bots.htm', size=1155, md5='e7be612c4d42af60000473fc3381a895', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/current_bots_species_group.inc', size=111, md5='ef646539a8eab7f570b594ab59d2f904', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Web/ServerAdmin/UnrealAdminPage'),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Admins_home.htm', size=679, md5='d4e15d564f4668a2166d3a1029b87b2b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Admins_menu.htm', size=1208, md5='89b8afd0dea240f66aad5dbe7b727a24', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Adminsframe.htm', size=711, md5='2a9f8b8982035d2ea685bf6701e53899', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Current_bots.htm', size=946, md5='cb2ad42396b806ee6cb75c0fb32b4509', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Current_menu.htm', size=1199, md5='db6c09d4e7b607c82b5528ac86c8242f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Currentframe.htm', size=728, md5='286e0612944f255f2121876a7d56cd5c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Defaults_menu.htm', size=1161, md5='cf0e17e5e25da069166a8973155ff803', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Defaultsframe.htm', size=683, md5='f7d41c771d6c9dee124f4b2133ea4d59', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Footer.inc', size=530, md5='a284512ce254997bfdded0332e47b46c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Mainmenu.htm', size=1990, md5='34e860c8c7aea03422106822cfb48d99', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Mainmenu_itemd.inc', size=74, md5='c8f418e8e4cccb9831dc6912e8455160', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/Rootframe.htm', size=690, md5='990040ccd5b70b711ba428c11d4729c6', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UnrealAdminPage/UnrealAdminPage.css', size=2222, md5='2ec4571340e95e342cd414561fcd90c1', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/Ut2003.css', size=10597, md5='4e6dd4ce3365429c18095f76e968e57a', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Web/ServerAdmin/UT2K3Stats'),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/Admins_home.htm', size=773, md5='6328acfcbfabd9ac3286e5fe7a5219d2', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/Current_bots.htm', size=1045, md5='66e43c1ccc94983fa078b55f8637c57c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('Web/ServerAdmin/UT2K3Stats/UT2003stats.css', size=10725, md5='291d2c7f845a2ddb80d31239e323fe7f', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Contents'),
		manifest_file ('Contents/Info.plist', size=1185, md5='13a84ebf4f00aae4dfd13d983d57b819', source_media=media_ut2004_3369_2_patch),

		manifest_directory ('Contents/MacOS'),
		manifest_symlink ('Contents/MacOS/Unreal Tournament 2004', '../../System/ut2004-bin')))

ut2004_3369_2_det = manifest (
	'UT2004 3369.2 German text',
	items=(
		manifest_file ('System/Bonuspack.det', size=4724, md5='f659666dc1cd540920e271817ddb0e94', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Core.det', size=3681, md5='2dc088f6ada0fb3aae8265954b71adc3', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Editor.det', size=5878, md5='2bb79af02d738f563d17587e54a9749d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Engine.det', size=20443, md5='19d49497d106e3bf3a89c97c9ff04f64', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Gameplay.det', size=8638, md5='87643b65e5df3ac49275d4e325fb2973', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GUI2K4.det', size=95577, md5='ed45dd2cc00ba997272c90a56957ae1f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Onslaught.det', size=16852, md5='c83c4871b521f241d09d080ba3fa381a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtFull.det', size=1691, md5='6e8f588ede1ac8546b4a0f82198a7b8b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Setup.det', size=10817, md5='445d6ce262ab46b4b072d7ab1361545b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Skaarjpack.det', size=4301, md5='0a5487442610045f4f1ad320c8acfe62', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UnrealGame.det', size=15194, md5='cfa416376f423142acd509235f12545e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4Assault.det', size=7155, md5='1bcd6116d49ef8c3b1e0527ecf2ed3d6', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4AssaultFull.det', size=1731, md5='adc7f46f32f26ab5a942613a9f0ea6e1', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Window.det', size=2475, md5='2684d23dc32b4cc5cde4d0929e6a3fbf', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XGame.det', size=23283, md5='c705068237c0b0cc1fa0f35dae5c8702', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XInterface.det', size=56346, md5='ac0af079e779560c97bbe53f10d78b04', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XMaps.det', size=9775, md5='65f128cd7547e0ea481c9f1e62e6ac77', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xPickups.det', size=448, md5='bfec9777f96db1ea6c78bac26a413821', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XPlayers.det', size=28779, md5='13986990d6e79384c6e9b3e95995f7a9', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xVoting.det', size=12516, md5='5b1e7f1bec1abbb5129dd2653482d209', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWeapons.det', size=22079, md5='a02344e46ef99eccbbb1bb4c234f22ab', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xWebAdmin.det', size=8099, md5='a4a5bfdb2ddd7f00152a961f121b2337', source_media=media_ut2004_3369_2_patch)))

ut2004_3369_2_est = manifest (
	'UT2004 3369.2 Spanish text',
	items=(
		manifest_file ('System/Bonuspack.est', size=4627, md5='381f0c83d3d8295f51a375d268df4965', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Core.est', size=3997, md5='59f35f7bfb028006d2fde102f0c6a869', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Editor.est', size=6025, md5='cfb828807711756338be73c5e0a0d102', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Engine.est', size=20308, md5='bb45221b04d00ad96ee78357e2c3685e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Gameplay.est', size=7868, md5='e61409016f031e337cb15d07ddf32333', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GUI2K4.est', size=93126, md5='d13bacda455e22bdc0e77a7802efc0da', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Onslaught.est', size=16367, md5='0232af892c982e56330185cc889fbb51', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtFull.est', size=1892, md5='542cd6eded23a29e309cb35ba1d6084c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Setup.est', size=9934, md5='7e484f77f04ad5e48c86fff146af5e82', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Skaarjpack.est', size=4371, md5='28c6f1d42ab206cae7332b37eaef4a9e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UnrealGame.est', size=14567, md5='651ef88c277e15925dd920c4f06f517a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4Assault.est', size=8354, md5='956ec358d3a8b9a251eb62914824f2c9', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4AssaultFull.est', size=1926, md5='53c72aed1260a54e8c47eb8d27a7ffe9', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Window.est', size=2355, md5='c909fcdff05707baf4d2d0cd6c7e7291', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XGame.est', size=22731, md5='214c61b4c84beb35a01ec99b1db9b437', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XInterface.est', size=55655, md5='d7501652364c55d7ee18c198ecdeb852', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XMaps.est', size=9885, md5='7b6147f2ba97283f935ef5bb31fb59f9', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xPickups.est', size=374, md5='f58a34c7907ccb45ef2137fef1abb30a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XPlayers.est', size=28923, md5='b525257882a2529a12d8deba3decc32b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xVoting.est', size=12620, md5='122082805b0902223451fe130edc9811', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWeapons.est', size=21652, md5='1a214a2772f19e29c0951eabfb3541a0', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xWebAdmin.est', size=7826, md5='194d7519e68c27325c07b4c77d8990c3', source_media=media_ut2004_3369_2_patch)))

ut2004_3369_2_frt = manifest (
	'UT2004 3369.2 French text',
	items=(
		manifest_file ('System/Bonuspack.frt', size=4304, md5='62d82df55b8d2498c14b89552f1e9e92', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Core.frt', size=3435, md5='9777ae8f9d6d95469f491e9024d65f13', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Editor.frt', size=5885, md5='cfd6c173d3bbbd98d12f6d3dfafb93b2', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Engine.frt', size=19483, md5='5e84ae849745693fac8a49c275351691', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Gameplay.frt', size=7915, md5='dd39f52e7fd0f7913216a0e2c8d956c7', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GUI2K4.frt', size=90205, md5='3216ce72740d67eefdf3058dd5802b47', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Onslaught.frt', size=15725, md5='6c68d6e7482bebd9a27c54c0987e2824', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtFull.frt', size=1562, md5='647f8c018df73ebcf52af47df8e0bc4f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Setup.frt', size=10067, md5='aa6e2fa5616504371ee61155ba49660f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Skaarjpack.frt', size=4055, md5='6e3368df6803f6e0235fb2b98d1a376b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UnrealGame.frt', size=14354, md5='1633265ba903994820e33583eef102e5', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4Assault.frt', size=7609, md5='0084805771fa06d25c2010991e53fc44', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4AssaultFull.frt', size=1795, md5='72f869866c810f706c3b8aff3437585c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Window.frt', size=2337, md5='adc05ef074882a1cbc24e297904d6770', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XGame.frt', size=21942, md5='1c26853b57f45e98b9fb22e5eadb756f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XInterface.frt', size=53331, md5='ab5cadec8d30ff5a7977b891704341af', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xPickups.frt', size=378, md5='0e15d08fb8b4a601e7fafc53c6f02586', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XPlayers.frt', size=28229, md5='074af9c8c964f372ed181f12c5080e41', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xVoting.frt', size=11867, md5='5ed93d753b53a308886d0ec80c39ef71', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWeapons.frt', size=19874, md5='f736e1b95087a4521fb7c0174c5523d1', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xWebAdmin.frt', size=7455, md5='64995fa2f2619270ea190795fe53610a', source_media=media_ut2004_3369_2_patch)))

ut2004_3369_2_int = manifest (
	'UT2004 3369.2 English text',
	items=(
		manifest_file ('Help/ReadMePatch.int.txt', size=37937, md5='496ebbb735207f7ea6136fb98ae93091', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-Convoy.int', size=6028, md5='c9c94783a628c33a1d46bb5ff46454d9', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-FallenCity.int', size=4453, md5='c7f26ec7063d24e299efa141f955d283', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-Glacier.int', size=7956, md5='441c36a0b24bd2c7536e2ce5e4d2c045', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-Junkyard.int', size=4107, md5='b1d0f4ba8cfa5cb05825f5febed47a1d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-Mothership.int', size=9735, md5='0e9e56c846fbb8900154d5b9dd9c832a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-RobotFactory.int', size=5755, md5='47b56abd5647ae59b5730d861948ff9d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Bonuspack.int', size=4338, md5='2d3e2517d8e73684b3de0a4af2d6397e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/BR-Serenity.int', size=838, md5='3cb79c49aaae0a13a24b4a7e1e98f3ce', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Core.int', size=3612, md5='0ded2a6395057dccdd963920cb7b45b9', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CTF-AbsoluteZero.int', size=2000, md5='d9124fa29997a465e7a323e21e8219f8', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CTF-BridgeOfFate.int', size=2268, md5='f9861c60eab24dbf90018f9c3ad4c89c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CTF-DE-ElecFields.int', size=1913, md5='80b2efd9e9f75f9b93da51a5d6a2d488', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CTF-DoubleDammage.int', size=3140, md5='f3af323afc431cff41e8452b9df369cf', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CTF-January.int', size=3368, md5='eceb9dd2b2f93977b38f43fd5d975e74', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CTF-LostFaith.int', size=287, md5='a7d7394be861a2ab0d7d4b07814f5f62', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DM-1on1-Albatross.int', size=848, md5='7994b8bd667af394f7de4f4414c549e6', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DM-1on1-Desolation.int', size=860, md5='96cc49ce52fd28fdf313b9c60348ff57', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DM-1on1-Mixer.int', size=635, md5='e0ccf7e7a8a9bf2f7f644b6a66360852', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DM-Corrugation.int', size=1170, md5='cca17affc055f1f673740d04a02a8d28', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DM-IronDeity.int', size=849, md5='952a336b73816287495d36870781a00e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DM-JunkYard.int', size=405, md5='f3e23bd8763ffed58c81ba137a49af44', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DOM-Atlantis.int', size=1128, md5='0e8cbaeb7fd3c42cfb64a76d2c6151cb', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Editor.int', size=6189, md5='e16609ded405b4b096e409eb3d48e2be', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Engine.int', size=18998, md5='4d0876a0cc31fb5c2a2bc565d1094049', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GamePlay.int', size=7814, md5='a331a71d40190240dccd05cc98d60f29', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GUI2K4.int', size=87109, md5='b77a5c68a8f73275a9b2069c516049c4', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/License.int', size=26738, md5='f33704555ece350b697bdb34b726f98f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Manifest.int', size=568, md5='65342b089ebfc774027164d841e5a388', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/ONS-Adara.int', size=741, md5='db7f2df15be6ebd8992aec4591462bee', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/ONS-IslandHop.int', size=1792, md5='43e3b1aa6b7fac5a9c48fe8756af4a61', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/ONS-Tricky.int', size=1135, md5='99a56a4da625f4d853c44207a7e8f726', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/ONS-Urban.int', size=512, md5='9a281413f8cc66e4ad935b1b918be45c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Onslaught.int', size=15030, md5='66e5a7c77bf462780b564dcf3b884b56', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtBP.int', size=1344, md5='7bd58c866a7b2cff755c1fd5651f343f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtFull.int', size=1743, md5='3c3cc06b565ed3a421d3bcb36c6e270a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Setup.int', size=9053, md5='8d3f71d83d2e14d6f1304542c0c8908c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Skaarjpack.int', size=4000, md5='8e009ba4ef6f61492377794d781120a5', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UnrealGame.int', size=13474, md5='ab4741cb8205bd53f3ef21a633563ff3', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2k4Assault.int', size=7142, md5='e4fd4c623c3e5aac08ed5e44e67227ed', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4AssaultFull.int', size=1716, md5='04540ce9e0c82ab623f87c8a20f2f294', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Window.int', size=2398, md5='018dbc86085ff307af39f370e9c6409a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XGame.int', size=21508, md5='c7441fdf75c39e7e00bf36803daf5a42', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XInterface.int', size=51911, md5='7d1a0e3d991302dd446d416749953425', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xPickups.int', size=449, md5='5bd4afdee4d1f8ca458872695241b426', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XPlayers.int', size=27406, md5='ea181a0c2e37a13b63c4bf41cf7a2c59', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xVoting.int', size=11299, md5='50c7dd94addf5271179161562014dbae', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWeapons.int', size=20148, md5='1dd678646af6b8b8e0f9a1264a6c765d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWebAdmin.int', size=7015, md5='3d8da6ecd16d7eab2c23936425718099', source_media=media_ut2004_3369_2_patch)))

ut2004_3369_2_itt = manifest (
	'UT2004 3369.2 Italian text',
	items=(
		manifest_file ('System/Bonuspack.itt', size=4770, md5='bdbb5c28144cd45db7e53bd1833dfbca', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Core.itt', size=4063, md5='7e5e3437551c9bef2212f4b1a3af7913', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Editor.itt', size=6434, md5='f37c3055c3a9a97417aaef8361ca44c2', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Engine.itt', size=20981, md5='a00503357d78cc2aec4b035ac13d7ae5', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Gameplay.itt', size=8235, md5='efa1e625fd46872def503ef59a42fecb', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GUI2K4.itt', size=93319, md5='953959ebaf46ea9cd8275088d0d6f39e', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Onslaught.itt', size=16608, md5='3de3d443c5a789c246ef27bffa3f7f4c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtFull.itt', size=1653, md5='2606072b1ae6ecc5eef08e4c054de350', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Setup.itt', size=9765, md5='78678a87e5683519dc97061476a11d43', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Skaarjpack.itt', size=4265, md5='5c164847a13e147b80cb81036901dce0', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UnrealGame.itt', size=14421, md5='6789a6af6f501752dc56dcb37a7c3a92', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4Assault.itt', size=7780, md5='a737c5831b7ea9cfe5385860714e858b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UT2K4AssaultFull.itt', size=1794, md5='f407cd094cb34ad01ff798a21b76daaa', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Window.itt', size=2466, md5='83b242b924ee7b5bbcee14b8278c78c4', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XGame.itt', size=23145, md5='fe74bb68ea9784b42e9ba7cca30a426c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XInterface.itt', size=56035, md5='4151e77eed4db3f7702a1d2ddc7254f2', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xPickups.itt', size=481, md5='c40685798ff7840c081738100626ae5b', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XPlayers.itt', size=28545, md5='5b67b02350d68b88ac643a12601ab0b8', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xVoting.itt', size=12554, md5='aad57ec9616e61435f9ae1c91e8ef4fb', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XWeapons.itt', size=22434, md5='fd16afc5abffcec3f6957ffd4d9fdd8f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xWebAdmin.itt', size=7764, md5='16eadcc176176eb4dabc60a6523eeb99', source_media=media_ut2004_3369_2_patch)))

ut2004_3369_2_kot = manifest (
	'UT2004 3369.2 Korean text',
	items=(
		manifest_file ('System/ALAudio.kot', size=478, md5='2054d91437a55ce4f4e8440b5f816dc3', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-Convoy.kot', size=7856, md5='006c80bd1600d9352842278907025abb', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-FallenCity.kot', size=6126, md5='13b33503eecd14a10981c342cb8406db', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/AS-Glacier.kot', size=11958, md5='80b5cc36c1c7d6af551ed58be1ea89cd', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Core.kot', size=5484, md5='1f6a747177cbb63e062c8fe4a8831a2d', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/CTF-January.kot', size=2790, md5='430378d4763d343e8d54075c7373a23c', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/D3DDrv.kot', size=640, md5='3beee78f2c44d051c825cf350e2f97d6', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/DM-1on1-Squader.kot', size=1304, md5='bf0de8ac31de730be47c87ca51f7781f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/GUI2K4.kot', size=136498, md5='a26d95626821e2999e88f4b73ef808ef', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/ONS-ArcticStronghold.kot', size=1116, md5='8ced583740c44ccd805a52c15e28b94a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Onslaught.kot', size=24066, md5='8addc3b84b6e1e973578f7b0bfe34ea7', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/OnslaughtBP.kot', size=1303, md5='d78ca3b55b02c8f9eb8e0856c9ffa5c3', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Setup.kot', size=12310, md5='6e8b66e913d64aef7f4b781e1d87f37a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Skaarjpack.kot', size=6718, md5='068d7e7c1ad31022eef2732dffbe3d23', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UTV2004.kot', size=1167, md5='ccef4cfb22ed571a2209d1f51ee38575', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/UTV2004s.kot', size=265, md5='6983701d80446ea0536b86cc035bdbb8', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Vehicles.kot', size=354, md5='94410601bfa042fac404ecad9914668a', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/Window.kot', size=3692, md5='11ba65622683d615b14b00e76f33509f', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/xAdmin.kot', size=7066, md5='904477383aad0e64488aab08ebeb08eb', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/XGame.kot', size=34740, md5='617baed4b94915456b4293da95fa5be3', source_media=media_ut2004_3369_2_patch)))

ut2004_3369_2_binaries = manifest (
	'UT2004 3369.2 binaries',
	items=(
		manifest_file ('System/libSDL-1.2.0.dylib', size=759388, md5='a3e630be48c6645e56d90f3badbb0271', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/openal.dylib', size=299616, md5='5f4b7d9a186a97540ba6eb4fa4fe9c87', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/osxterminal.sh', size=9662, md5='4d3577ba8ac88c906572b914b8b90211', source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/ucc-bin', size=30933856, md5='058df48d8b9262a1e83bba4ae7f87be9', executable=True, source_media=media_ut2004_3369_2_patch),
		manifest_file ('System/ut2004-bin', size=32449156, md5='6131450d4172cb1a4a9ceb0151490615', executable=True, source_media=media_ut2004_3369_2_patch)))

ut2004_icon = manifest (
	'UT2004 icon (e.g. from demo)',
	items=(
		manifest_directory ('Contents/Resources'),
		manifest_file ('Contents/Resources/ut2004.icns', size=56707, md5='80f65838f8b434796acd635f8b7c062e', optional=True, source_media=media_ut2004_demo)))

ut2004 = manifest (
	'Unreal Tournament 2004',
	items=(
		manifest_directory (''),
		ut2004_3186,
		ut2004_3186_audio_det,
		ut2004_3186_int,
		ut2004_3369_2,
		ut2004_3369_2_int,
		ut2004_3369_2_binaries,
		ut2004_icon))

# }}}

def verify (manifest, base):
	for item, result, message in manifest.verify (base):
		sys.stdout.write ('%s -- %s' % (item, message))

def install (manifest, base):
	for item, result, message in manifest.install (base):
		sys.stdout.write ('%s -- %s\n' % (item, message))

def main ():
	base = 'Unreal Tournament 2004.app'
	install (ut2004, base)

if '__main__' == __name__:
	main ()
