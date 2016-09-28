#! /usr/bin/env python

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

from ConfigParser import SafeConfigParser
from datetime import timedelta
from datetime import datetime
from urllib2 import urlopen

import random
import time
import sys
import os

try:
    import json
except ImportError:
    import simplejson as json

class BassDrive:

    def __init__(self):

        # Load our "config"
        self.bd_config = SafeConfigParser()
        self.bd_config.read(os.path.join(os.path.dirname(__file__), "config.ini"))
        
        # Plugin constants
        self.bd_addon = xbmcaddon.Addon(id=self.bd_config.get('plugin', 'id'))
        
        # Figure out where our profile path is for this plugin
        self.bd_ppath = xbmc.translatePath(self.bd_addon.getAddonInfo('profile')).decode('utf-8')

        # Define our handle
        self.bd_handle = int(sys.argv[1])

        # Define cache bits, ensure our cachedir exists
        self.cachefile = self.bd_config.get('cachefiles', 'streams')
        self.cachedir = os.path.join(self.bd_ppath, 'cache')
        self.cache_streams_path = os.path.join(self.cachedir, self.cachefile)
        if not os.path.exists(self.cache_streams_path):
            os.makedirs(self.cachedir)

    def log(self, msg):
        xbmc.log("[Bassdrive Plugin] %s" % (msg), xbmc.LOGNOTICE)

    def _cache_file_has_expired(self, days):
        """ Checks on a cache file to see if it's lived past its livable timeframe
        :param days: days (int) : Age in days this file is allowed to be
        :return True: If our cache file has expired
        :return False: If the cache file is still within its livable timefram
        """

        # Check to make sure the filepath exists (eg: it won't on first run)
        #   Return True, indicating that we need a cache update

        self.log("Checking to see if our cache file has expired")

        if not os.path.exists(self.cache_streams_path):
            self.log("Our cache path doesn't exist. Not bothering to check anything")
            return True

        if days == 0:
            self.log("Cache settings denote noexpire. Not checking, assuming still valid")
            return False

        if days > 28:
            self.log("Cache expiry set higher than 28 days. Ignoring, and defaulting to 7. Setting app settings to 7")
            self.bd_config.setSetting('streamcacheexpiredays', '7')
            days = 7

        # The epoch of lst modified timestamp of our cache file
        tstamp = time.ctime(os.path.getmtime(self.cache_streams_path))

        # There's an issue with .. I'm not 100% sure what. The datetime lib on stray versions of python?
        #   http://forum.kodi.tv/showthread.php?tid=112916&pid=1212394#pid1212394
        try:
            tstamp = datetime.strptime(tstamp, '%a %b %d %H:%M:%S %Y')
        except TypeError:
            tstamp = datetime.fromtimestamp(time.mktime(time.strptime(tstamp, '%a %b %d %H:%M:%S %Y')))

        if tstamp > datetime.utcnow() + timedelta(days=days):
            self.log("Cache file has expired")
            return True

        self.log("Cache file is still valid")
        return False

    def _urllib_get_m3us(self, url):
        """ Query a URL for an m3u file, iterate over it line by line, and build a list of lines to return
        :param url: the .m3u URL we're querying for
        :return False: Upon failure to get the specified file
        :return type(list): URLs on success

        TODO: There's more we can do here... for sanitization, but do we really need to?
        """

        try:
            data = urlopen(url)
            return [line.strip() for line in data]
        except Exception as e:
            self.log(e.message)
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
        self.log("Pulling m3u's from bassdrive.com and building our stream cache")

        streams = {}
        for key, url in self.bd_config.items('streams'):
            urls = self._urllib_get_m3us(url)
            if not urls:
                continue
            streams[key] = urls

        self.log("Writing stream cache to file: %s" % self.cache_streams_path)
        with open(self.cache_streams_path, 'w+') as handle:
            # TODO this has the potential to fail, but it's unlikely. Might want to try/catch ?
            json.dump(streams, handle)

        return True

    def _get_stream(self, quality):
        """ Return a random URL for a given bitrate requested to play
        :param quality: string of bitrate we're after, as a keyname in our json cachefile
        :return str: A URL to be played :D
        TODO: Should this have any potential error handling? /shrug
        """
        self.log("Getting random %s stream to build 'playlist' with" % quality)
        with open(self.cache_streams_path) as handle:
            cache = json.load(handle)
        return random.choice(cache[quality])

    # Lets play some Fishdrive!
    def run(self):

        # Check to see if our cache has expired
        cachedays = int(self.bd_addon.getSetting("stream_cache_expiry_days"))
        if self._cache_file_has_expired(cachedays):
            self.log("Stream cache is expired. Requesting forced update")
            self._update_streams()
            self.bd_addon.setSetting(id="forceupdate", value="false")

        # Check to see if we're focing an update
        if self.bd_addon.getSetting("forceupdate") == "true":
            self.log("Aforce update been requested. Updating cache...")
            self._update_streams()

        # Build "playlist", one quality per line
        total_items = 0
        for key, _x in self.bd_config.items('streams'):
            total_items += 1

            url = self._get_stream(key)

            # Generate a list item for Kodi
            li = xbmcgui.ListItem(label="Bassdrive @ %s" % key, thumbnailImage="%s" % os.path.join(self.bd_ppath,
                                                                                                   'icon.png'))
            
            # Set our stream quality, per Bassdrives website
            li.setProperty("mimetype", "audio/aac")
            if key == '128k':
                li.setProperty("mimetype", "audio/mpeg")

            # Set player info
            li.setInfo(type="Music", infoLabels={"Genre": "Drum & Bass",
                                                 "Comment": "World Wide Drum & Bass",
                                                 "Size": int(key[:-1]) * 1024})
            li.setProperty("IsPlayable", "true")
            xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=url, listitem=li, isFolder=False,
                                        totalItems=total_items)

        print total_items

        # tell XMBC there are no more items to list
        xbmcplugin.endOfDirectory(self.bd_handle, succeeded=True)

        # Success
        return True


MusicAddonInstance = BassDrive()
MusicAddonInstance.run()
