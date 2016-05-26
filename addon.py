#! /usr/bin/env python

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

from ConfigParser import SafeConfigParser
from urllib2 import urlopen
from datetime import datetime
from datetime import timedelta
import random
import time
import sys
import os

#   We use JSON as cache files, so import as necessary
try:
    import json
except ImportError:
    import simplejson as json

# Load our "config"
pluginConfig = SafeConfigParser()
pluginConfig.read(os.path.join(os.path.dirname(__file__), "config.ini"))

# Plugin constants
bassdrive = xbmcaddon.Addon(id=pluginConfig.get('plugin', 'id'))

# Figure out where our profile path is for this plugin
pluginProfilePath = xbmc.translatePath(bassdrive.getAddonInfo('profile')).decode('utf-8')

__plugin__ = bassdrive.getAddonInfo('name')
__author__ = "Pat Litke"
__url__ = "https://github.com/geudrik/Bassdrive-Kodi-Plugin"
__platform__ = "xbmc media center, [LINUX, OS X, WIN32]"
__date__ = pluginConfig.get('plugin', 'date')
__version__ = bassdrive.getAddonInfo('version')

addon_handle = int(sys.argv[1])


# Define our Player Class / Manager
class BassDrive:

    def __init__(self):
        xbmc.log("[%s] v%s (%s) starting up..." % (__plugin__, __version__, __date__), xbmc.LOGNOTICE)

    def log(self, msg):
        xbmc.log("[%s] %s" % (__plugin__, msg), xbmc.LOGNOTICE)

    def _cache_file_has_expired(self, fpath, days):
        """ Checks on a cache file to see if it's lived past its livable timeframe

            Args:
                fpath (str) : The filepath we're checking on
                days (int) : Age in days this file is allowed to be

            Returns:
                True if our cache file has expired
                False if the cache file is still within its livable timefram
        """

        # Check to make sure the filepath exists (eg: it won't on first run)
        #   Return True, indicating that we need a cache update

        self.log("Checking to see if our cache has expired...")

        if not os.path.exists(fpath):
            self.log("Our cache patche doesn't exist. Not bothering to check anything")
            return True

        tstamp = time.ctime(os.path.getmtime(fpath))
        tstamp = datetime.strptime(tstamp, '%a %b %d %H:%M:%S %Y')
        if tstamp > datetime.utcnow() + timedelta(days=days):
            self.log("Cache has expired for %s".format(fpath))
            return True

        self.log("Cache is still valid")
        return False

    def _update_streams(self):
        """ Get all of the m3u files from BassDrive, parse them, and shove them into our json cache
        This wile ultimately write a JSON blob to our streams cache file with the following format
        {
            '32k'  : [ url1, url2, ... ],
            '56k'  : [ url1, url2, ... ],
            '128k' : [ url1, url2, ... ]
        }
        """

        streams = {}

        def get_streams(url, key):
            streams[key] = []
            data = urlopen(url)
            for line in data:
                streams[key].append(line.strip())

        for key, url in pluginConfig.items('streams'):
            get_streams(url, key)

        # Check to see if the cache file/folder exist. Create if necessary
        #   TODO: Move this out into a .. firstrun?
        cachefile = pluginConfig.get('cachefiles', 'streams')
        cachedir = os.path.split(cachefile)[0]
        if not os.path.exists(os.path.join(pluginProfilePath, cachedir)):
            os.makedirs(os.path.join(pluginProfilePath, cachedir))

        with open(os.path.join(pluginProfilePath, cachefile), 'w+') as handle:
            json.dump(streams, handle)

    def _get_stream(self, quality):
        """ Return a URL to be played, grabbed from our cache file"""

        with open(os.path.join(pluginProfilePath, pluginConfig.get('cachefiles', 'streams'))) as handle:
            cache = json.load(handle)

        print "Cache: ", cache
        print "Quality: ", quality
        print cache[quality]
        return random.choice(cache[quality])

    # Lets play some Fishdrive!
    def run(self):

        # Check to see if our cache has expired
        _cachepath = pluginConfig.get('cachefiles', 'streams')
        _cachedays = bassdrive.getSetting("cacheexpire_days")
        if self._cache_file_has_expired(_cachepath, _cachedays) and bassdrive.getSetting("forceupdate") != "true":
            bassdrive.setSetting(id="forceupdate", value="true")

        # Check to see if we're focing an update
        if bassdrive.getSetting("forceupdate") == "true":
            self._update_streams()

        # Build "playlist", one quality per line
        total_items = 0
        for key, _url in pluginConfig.items('streams'):
            total_items += 1

            url = self._get_stream(key)

            # Generate a list item for Kodi
            li = xbmcgui.ListItem(label="[COLOR FF007EFF]Bassdrive @ {0}[/COLOR]".format(key), thumbnailImage="")
            
            # Set our stream quality, per Bassdrives website
            if key == '128k':
                li.setProperty("mimetype", "audio/mpeg")
            else:
                li.setProperty("mimetype", "audio/aac")

            # Set player info
            li.setInfo(type="Music", infoLabels={"Genre": "Drum & Bass",
                                                 "Comment": "World Wide Drum & Bass",
                                                 "Size": int(key[:-1]) * 1024})
            li.setProperty("IsPlayable", "true")
            xbmcplugin.addDirectoryItem(handle=addon_handle, url=url, listitem=li, isFolder=False,
                                        totalItems=total_items)

        print total_items

        # tell XMBC there are no more items to list
        xbmcplugin.endOfDirectory(addon_handle, succeeded=True)

        # Success
        return True


MusicAddonInstance = BassDrive()
MusicAddonInstance.run()
