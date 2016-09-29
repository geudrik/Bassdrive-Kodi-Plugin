#! /usr/bin/env python

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

from ConfigParser import SafeConfigParser
from datetime import timedelta
from datetime import datetime
from urllib2 import urlopen

import HTMLParser
import test_data
import urlparse
import urllib2
import urllib
import random
import time
import sys
import os
import re

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

        # Gather some args for use later.
        self.base_url = sys.argv[0]
        self.bd_handle = int(sys.argv[1])
        self.args = urlparse.parse_qs(sys.argv[2][1:])
        self.mode = urlparse.parse_qs(sys.argv[2][1:]).get('mode',None)


        # Define cache bits, ensure our cachedir exists
        self.cachefile = self.bd_config.get('cachefiles', 'streams')
        self.cachedir = os.path.join(self.bd_ppath, 'cache')
        self.cache_streams_path = os.path.join(self.cachedir, self.cachefile)
        if not os.path.exists(self.cache_streams_path):
            os.makedirs(self.cachedir)

        self.arcachefile = self.bd_config.get('cachefiles', 'archives')
        self.arcachedir = os.path.join(self.bd_ppath, 'cache')
        self.arcache_streams_path = os.path.join(self.arcachedir, self.arcachefile)
        if not os.path.exists(self.arcache_streams_path):
            os.makedirs(self.arcachedir)

    def log(self, msg):
        xbmc.log("[Bassdrive Plugin] %s" % (msg), xbmc.LOGNOTICE)

    def puke(self, message):
        __addon__ = xbmcaddon.Addon()
        __addonname__ = __addon__.getAddonInfo('name')
        xbmcgui.Dialog().ok(__addonname__, message)

    def _build_url(self, query):
        return self.base_url + '?' + urllib.urlencode(query)

    def _cache_file_has_expired(self, days, filepath):
        """ Checks on a cache file to see if it's lived past its livable timeframe
        :param days: days (int) : Age in days this file is allowed to be
        :return True: If our cache file has expired
        :return False: If the cache file is still within its livable timefram
        """

        # Check to make sure the filepath exists (eg: it won't on first run)
        #   Return True, indicating that we need a cache update

        self.log("Checking to see if our cache file has expired")

        if not os.path.exists(filepath):
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
        tstamp = time.ctime(os.path.getmtime(filepath))

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
            json.dump(streams, handle)

        return True

    def _update_archives(self):
        """
        Return a multimensional dict of lists, of the paths of BD Archive Recordings
        """

        self.log("Building object of all archives from archives.bassdrive.com and writing cache file")

        def recursive_fetch(url)

            blacklisted_labels = [ 'Parent Directory' ]

            anchor_re = re.compile('<a href=\".*</a>')
            hrefs = re.compile('(?<=href=\"(?!http)(?!/\")).*(?=\">)')
            text = re.compile('(?<=\">).*(?=</a>)')

            pars = HTMLParser.HTMLParser()
            url = pars.unescape(url)

            results = []
            
            urlpath = urllib2.urlopen(url)

            req_data = urlpath.read().decode('utf-8')
            anchors = anchor_re.findall(req_data)

            # Traverse our anchors / web structure
            for item in anchors:

                # separate href value from the label of the anchor and strip all leading/trailing whitespace
                try:
                    url_path = re.search(hrefs,item).group(0).strip()
                    url_label = re.search(text,item).group(0).strip()

                except:
                    continue

                if url_label in blacklisted_labels:
                    continue

                # If the path doesn't end in a slash, it's a file
                if re.search('/$',url_path) is None:
                    results.append(urllib.unquote(url_path))

                else:
                    sanitized_dir_name = urllib.unquote(url_path).replace("/","")
                    results.append( { sanitized_dir_name : recursive_fetch(url + url_path)})
        
        results = recursive_fetch('http://archives.bassdrivearchive.com')
        with open(self.arcache_streams_path, 'w+') as handle:
            json.dump(results, handle)

        return True

    def _load_archive_data(self):
        """
        This function simply loads the cache file. 
        Note that if the archives get huge, the memory footprint of this could get massive
        """
        self.log("Loading up our archive data...")
        with open(self.arcache_streams_path) as handle:
            cache = json.load(handle)
        return cache

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

    def _fetch_nested_data(self, key_names, data_structure):
        """ Search through a nested datastructure for a dict with a given display_name
        :param key_names: a list of strings that represent different layers of the datastructure
        :param data_structure: the structure containing all directories and filenames available.
        """
        key = key_names[0]

        # If our first key is "Archives", then just get the next one.
        if key == "Archives":
            key = key_names[0]

        for item in data_structure:
            if isinstance(item, dict) and item.keys()[-1] == key:
                #If we're at the bottom of the datastructure, we have found our result.
                if len(key_names) == 0:
                    return item[key]
                else:
                    # if we are not at the bottom of the data strucutre, recurse!
                    return self._fetch_nested_data(key_names, item[key])

    def _build_archives_url(self, filename):
        """ Return a url to a file in the bassdrive archives.
        :param filename: string containing the filename.  This will be joined with the base URL
            as well as the directory as found from self.args['foldername']
        """
        directory = self.args['foldername'][0].replace("Archives/","")

        return 'http://archives.bassdrivearchive.com/{}/{}'.format(directory,filename)

    # Lets play some Fishdrive!
    def run(self):
        #debugging info, remove me later!
        self.log("running run()")
        self.log(self.args)
        self.log(self.base_url)
        self.log(self.bd_handle)
        self.log(self.mode)

        # Check to see if our cache has expired
        cachedays = int(self.bd_addon.getSetting("stream_cache_expiry_days"))
        if self._cache_file_has_expired(cachedays, self.cache_streams_path):
            self.log("Stream cache is expired. Requesting forced update")
            self._update_streams()
            self.bd_addon.setSetting(id="forceupdate", value="false")

        # Check to see if we're focing an update
        if self.bd_addon.getSetting("forceupdate") == "true":
            self.log("A force update been requested. Updating cache...")
            self._update_streams()

        directory_items = []

        # If we are not in 'folder' mode, just print the main menu.
        if self.mode is None:

            # Build playable bitrate menu items
            for key, _x in self.bd_config.items('streams'):

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

                isFolder=False

                directory_items.append((url,li,isFolder))

                xbmcplugin.addDirectoryItem(handle=self.bd_handle,url=url,listitem=li,isFolder=False)

            # Add in our 'Archives' folder menu item
            archive_url = self._build_url({'mode': 'folder', 'foldername': 'Archives'})
            test = xbmcgui.ListItem(label="Archives")
            xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=archive_url,listitem=test,isFolder=True)
            xbmcplugin.endOfDirectory(self.bd_handle, succeeded=True)

        # Are we in Folder mode? eg: Have we selected 'Archives' from the main menu?
        elif self.mode[0] == 'folder':

            # Check to see if our cache has expired
            cachedays = int(self.bd_addon.getSetting("archives_cache_expiry_days"))
            if self._cache_file_has_expired(cachedays, self.arcache_streams_path):
                self.log("Archive cache is expired. Requesting update")
                self._update_archives()
                self.bd_addon.setSetting(id="archives_forceupdate", value="false")

            # Check to see if we're focing an update
            if self.bd_addon.getSetting("archives_forceupdate") == "true":
                self.log("A force update been requested. Updating cache...")
                self._update_archives()

            # The name of the directory that called for this folder (eg: ../)
            calling_foldername = self.args['foldername'][0]

            # If our calling folder is 'Archives', we want to display the top-level archives info (eg: Monday...)
            if calling_foldername == "Archives":

                try:
                    archive_data = self._load_archive_data()
                except:
                    self.puke("No Archives cache file found. Open the settings, set cache to force-update, and restart the addon")
                    return

                for archive_item in archive_data:

                    item_name = archive_item.keys()[-1]

                    archive_url = self._build_url({'mode': 'folder', 'foldername': '{}/{}'.format(calling_foldername,item_name)})
                    test = xbmcgui.ListItem(label=item_name)
                    xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=archive_url,listitem=test,isFolder=True)
            else:

                # split out the calling foldername for use in searching the datastructure for the resquested directory
                key_names = calling_foldername.split('/')

                # collect data to display from the whole archive datastructure
                data_to_display = self._fetch_nested_data(key_names=key_names,data_structure=self.archive_data)

                # Begin to display menu items for this subfolder
                for item in data_to_display:

                    # If our item is a dict, it's a directory, so show it as such
                    if isinstance(item, dict):
                        item_name = item.keys()[-1]


                        archive_url = self._build_url({'mode': 'folder', 'foldername': '{}/{}'.format(calling_foldername,item_name)})
                        test = xbmcgui.ListItem(label=item_name)
                        xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=archive_url,listitem=test,isFolder=True)

                    # Item is a file, so make it playable
                    else:
                        #url = 'http://archives.bassdrivearchive.com/1%20-%20Monday/Fokuz%20Recordings%20Show/%5b2016.02.08%5d%20Fokuz%20Recordings%20Show%20-%20SATL.mp3'
                        url = self._build_archives_url(item)

                        # Generate a list item for Kodi
                        li = xbmcgui.ListItem(label=item, thumbnailImage="%s" % os.path.join(self.bd_ppath,'icon.png'))
                        # Set player info
                        li.setInfo(type="Music", infoLabels={"Genre": "Drum & Bass",
                                                             "Comment": "World Wide Drum & Bass" })

                        li.setProperty("IsPlayable", "true")

                        isFolder=False

                        directory_items.append((url, li, isFolder))

                        xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=url, listitem=li, isFolder=False)

            # when we're done adding items to the directory, finish drawing it.
            xbmcplugin.endOfDirectory(self.bd_handle, succeeded=True)

        # Success
        return True


MusicAddonInstance = BassDrive()
MusicAddonInstance.run()
