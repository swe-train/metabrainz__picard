# -*- coding: utf-8 -*-
#
# Picard, the next-generation MusicBrainz tagger
# Copyright (C) 2004 Robert Kaye
# Copyright (C) 2006 Lukáš Lalinský
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.

import os
import ntpath
import re
import sys
import unicodedata
if sys.platform == 'win32':
	from ctypes import windll

from time import time
from PyQt4 import QtCore
from encodings import rot_13
from string import Template
# Required for compatibility with lastfmplus which imports this from here rather than loading it direct.
from functools import partial
from collections import defaultdict


class LockableObject(QtCore.QObject):

    """Read/write lockable object."""

    def __init__(self):
        QtCore.QObject.__init__(self)
        self.__lock = QtCore.QReadWriteLock()

    def lock_for_read(self):
        """Lock the object for read operations."""
        self.__lock.lockForRead()

    def lock_for_write(self):
        """Lock the object for write operations."""
        self.__lock.lockForWrite()

    def unlock(self):
        """Unlock the object."""
        self.__lock.unlock()


_io_encoding = sys.getfilesystemencoding()


# The following was adapted from k3b's source code:
#// On a glibc system the system locale defaults to ANSI_X3.4-1968
#// It is very unlikely that one would set the locale to ANSI_X3.4-1968
#// intentionally
def check_io_encoding():
    if _io_encoding == "ANSI_X3.4-1968":
        from picard import log
        log.warning("""
System locale charset is ANSI_X3.4-1968
Your system's locale charset (i.e. the charset used to encode filenames)
is set to ANSI_X3.4-1968. It is highly unlikely that this has been done
intentionally. Most likely the locale is not set at all. An invalid setting
will result in problems when creating data projects.
To properly set the locale charset make sure the LC_* environment variables
are set. Normally the distribution setup tools take care of this.

Translation: Picard will have problems with non-english characters
               in filenames until you change your charset.
""")


def encode_filename(filename):
    """Encode unicode strings to filesystem encoding."""
    if isinstance(filename, unicode):
        if os.path.supports_unicode_filenames and sys.platform != "darwin":
            return filename
        else:
            return filename.encode(_io_encoding, 'replace')
    else:
        return filename


def decode_filename(filename):
    """Decode strings from filesystem encoding to unicode."""
    if isinstance(filename, unicode):
        return filename
    else:
        return filename.decode(_io_encoding)


def pathcmp(a, b):
    return os.path.normcase(a) == os.path.normcase(b)


def format_time(ms):
    """Formats time in milliseconds to a string representation."""
    ms = float(ms)
    if ms == 0:
        return "?:??"
    else:
        return "%d:%02d" % (round(ms / 1000.0) / 60, round(ms / 1000.0) % 60)


def sanitize_date(datestr):
    """Sanitize date format.

    e.g.: "YYYY-00-00" -> "YYYY"
          "YYYY-  -  " -> "YYYY"
          ...
    """
    date = []
    for num in datestr.split("-"):
        try:
            num = int(num.strip())
        except ValueError:
            break
        if num:
            date.append(num)
    return ("", "%04d", "%04d-%02d", "%04d-%02d-%02d")[len(date)] % tuple(date)


_re_win32_incompat = re.compile(r'["*:<>?|]', re.UNICODE)
def replace_win32_incompat(string, repl=u"_"):
    """Replace win32 filename incompatible characters from ``string`` by
       ``repl``."""
    # Don't replace : with _ for windows drive
    if sys.platform == "win32" and os.path.isabs(string):
        drive, rest = ntpath.splitdrive(string)
        return drive + _re_win32_incompat.sub(repl, rest)
    else:
        return _re_win32_incompat.sub(repl, string)


_re_non_alphanum = re.compile(r'\W+', re.UNICODE)
def strip_non_alnum(string):
    """Remove all non-alphanumeric characters from ``string``."""
    return _re_non_alphanum.sub(u" ", string).strip()


_re_slashes = re.compile(r'[\\/]', re.UNICODE)
def sanitize_filename(string, repl="_"):
    return _re_slashes.sub(repl, string)


def _reverse_sortname(sortname):
    """Reverse sortnames."""
    chunks = [a.strip() for a in sortname.split(",")]
    if len(chunks) == 2:
        return "%s %s" % (chunks[1], chunks[0])
    elif len(chunks) == 3:
        return "%s %s %s" % (chunks[2], chunks[1], chunks[0])
    elif len(chunks) == 4:
        return "%s %s, %s %s" % (chunks[1], chunks[0], chunks[3], chunks[2])
    else:
        return sortname.strip()


def translate_from_sortname(name, sortname):
    """'Translate' the artist name by reversing the sortname."""
    for c in name:
        ctg = unicodedata.category(c)
        if ctg[0] == "L" and unicodedata.name(c).find("LATIN") == -1:
            for separator in (" & ", "; ", " and ", " vs. ", " with ", " y "):
                if separator in sortname:
                    parts = sortname.split(separator)
                    break
            else:
                parts = [sortname]
                separator = ""
            return separator.join(map(_reverse_sortname, parts))
    return name


def find_existing_path(path):
    path = encode_filename(path)
    while path and not os.path.isdir(path):
        head, tail = os.path.split(path)
        if head == path:
            break
        path = head
    return decode_filename(path)


def find_executable(*executables):
    if sys.platform == 'win32':
        executables = [e + '.exe' for e in executables]
    paths = [os.path.dirname(sys.executable)] if sys.executable else []
    paths += os.environ.get('PATH', '').split(os.pathsep)
    for path in paths:
        for executable in executables:
            f = os.path.join(path, executable)
            if os.path.isfile(f):
                return f


_mbid_format = Template('$h{8}-$h$l-$h$l-$h$l-$h{12}').safe_substitute(h='[0-9a-fA-F]', l='{4}')
_re_mbid_val = re.compile(_mbid_format)
def mbid_validate(string):
    return _re_mbid_val.match(string)


def rot13(input):
    return u''.join(unichr(rot_13.encoding_map.get(ord(c), ord(c))) for c in input)


def parse_amazon_url(url):
    """Extract host and asin from an amazon url.
    It returns a dict with host and asin keys on success, None else
    """
    r = re.compile(r'^http://(?:www.)?(?P<host>.*?)(?:\:[0-9]+)?/.*/(?P<asin>[0-9B][0-9A-Z]{9})(?:[^0-9A-Z]|$)')
    match = r.match(url)
    if match is not None:
        return match.groupdict()
    return None


def throttle(interval):
    """
    Throttle a function so that it will only execute once per ``interval``
    (specified in milliseconds).
    """
    mutex = QtCore.QMutex()

    def decorator(func):
        def later():
            mutex.lock()
            func(*decorator.args, **decorator.kwargs)
            decorator.prev = time()
            decorator.is_ticking = False
            mutex.unlock()

        def throttled_func(*args, **kwargs):
            if decorator.is_ticking:
                mutex.lock()
                decorator.args = args
                decorator.kwargs = kwargs
                mutex.unlock()
                return
            mutex.lock()
            now = time()
            r = interval - (now-decorator.prev)*1000.0
            if r <= 0:
                func(*args, **kwargs)
                decorator.prev = now
            else:
                decorator.args = args
                decorator.kwargs = kwargs
                QtCore.QTimer.singleShot(r, later)
                decorator.is_ticking = True
            mutex.unlock()

        return throttled_func

    decorator.prev = 0
    decorator.is_ticking = False
    return decorator


def uniqify(seq):
    """Uniqify a list, preserving order"""
    # Courtesy of Dave Kirby
    # See http://www.peterbe.com/plog/uniqifiers-benchmark
    seen = set()
    add_seen = seen.add
    return [x for x in seq if x not in seen and not add_seen(x)]


# order is important
_tracknum_regexps = (
    # search for explicit track number (prefix "track")
    r"track[\s_-]*(?:no|nr)?[\s_-]*(\d+)",
    # search for 2-digit number at start of string
    r"^(\d{2})\D?",
    # search for 2-digit number at end of string
    r"\D?(\d{2})$",
)


def tracknum_from_filename(base_filename):
    """Guess and extract track number from filename
    Returns -1 if none found, the number as integer else
    """
    filename, _ = os.path.splitext(base_filename)
    for r in _tracknum_regexps:
        match = re.search(r, filename, re.I)
        if match:
            n = int(match.group(1))
            if n > 0:
                return n
    # find all numbers between 1 and 99
    # 4-digit or more numbers are very unlikely to be a track number
    # smaller number is preferred in any case
    numbers = sorted([int(n) for n in re.findall(r'\d+', filename) if
                      int(n) <= 99 and int(n) > 0])
    if numbers:
        return numbers[0]
    return -1


# Provide os.path.samefile equivalent which is missing in Python under Windows
if sys.platform == 'win32':
    def os_path_samefile(p1, p2):
        ap1 = os.path.abspath(p1)
        ap2 = os.path.abspath(p2)
        return ap1 == ap2
else:
    os_path_samefile = os.path.samefile


def is_hidden(filepath):
    """Test whether a file or directory is hidden.
    A file is considered hidden if it starts with a dot
    on non-Windows systems or if it has the "hidden" flag
    set on Windows."""
    name = os.path.basename(os.path.abspath(filepath))
    return (name.startswith('.') and sys.platform != 'win32') \
        or _has_hidden_attribute(filepath)


def _has_hidden_attribute(filepath):
    if sys.platform != 'win32':
        return False
    # FIXME: On OSX detecting hidden files involves more
    # than just checking for dot files, see
    # https://stackoverflow.com/questions/284115/cross-platform-hidden-file-detection
    try:
        attrs = windll.kernel32.GetFileAttributesW(unicode(filepath))
        assert attrs != -1
        return bool(attrs & 2)
    except (AttributeError, AssertionError):
        return False


def linear_combination_of_weights(parts):
    """Produces a probability as a linear combination of weights
    Parts should be a list of tuples in the form:
        [(v0, w0), (v1, w1), ..., (vn, wn)]
    where vn is a value between 0.0 and 1.0
    and wn corresponding weight as a positive number
    """
    total = 0.0
    sum_of_products = 0.0
    for value, weight in parts:
        if value < 0.0:
            raise ValueError, "Value must be greater than or equal to 0.0"
        if value > 1.0:
            raise ValueError, "Value must be lesser than or equal to 1.0"
        if weight < 0:
            raise ValueError, "Weight must be greater than or equal to 0.0"
        total += weight
        sum_of_products += value * weight
    if total == 0.0:
        return 0.0
    return sum_of_products / total


def album_artist_from_path(filename, album, artist):
    """If album is not set, try to extract album and artist from path
    """
    if not album:
        dirs = os.path.dirname(filename).replace('\\','/').lstrip('/').split('/')
        if len(dirs) == 0:
            return album, artist
        # Strip disc subdirectory from list
        if len(dirs) > 0:
            if re.search(r'(^|\s)(CD|DVD|Disc)\s*\d+(\s|$)', dirs[-1], re.I):
                del dirs[-1]
        if len(dirs) > 0:
            # For clustering assume %artist%/%album%/file or %artist% - %album%/file
            album = dirs[-1]
            if ' - ' in album:
                new_artist, album = album.split(' - ', 1)
                if not artist:
                    artist = new_artist
            elif not artist and len(dirs) >= 2:
                artist = dirs[-2]
    return album, artist
