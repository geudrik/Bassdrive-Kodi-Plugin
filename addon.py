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

class BDBase(object):
    """
    Base class that outlines our BassDrive Plugin Components
    """

    def __init__(self):

        # Load config.ini
        self.bd_config = SafeConfigParser()
        self.bd_config.read(os.path.join(os.path.dirname(__file__), "config.ini"))

        # Plugin Constants & Profile Path
        self.bd_addon = xbmcaddon.Addon(id=self.bd_config.get('plugin', 'id'))
        self.bd_ppath = xbmc.translatePath(self.bd_addon.getAddonInfo('profile')).decode('utf-8')
        self.bd_handle = int(sys.argv[1])
        self.base_url = sys.argv[0]

        # Mode Arguments
        self.args = urlparse.parse_qs(sys.argv[2][1:])
        self.mode = urlparse.parse_qs(sys.argv[2][1:]).get('mode', None)

        # Ensure our Cache directory exists
        self.cachedir = os.path.join(self.bd_ppath, 'cache')
        if not os.path.exists(self.cachedir):
            os.makedirs(self.cachedir)

    def log(self, msg):
        xbmc.log("[Bassdrive Plugin] %s" % (msg), xbmc.LOGNOTICE)

    def error(self, message):
        adname = self.bd_addon.getAddonInfo('name')
        xbmcgui.Dialog().ok(adname, message)

    def cache_file_expired(self, filepath, days=7):
        """
        Super simple function that returns a boolean
        Args:
            days (int)      The number of days old the file can be before its considdered expired
            filepath (str)  Full filepath of our cache file
        Return:
            True if the cachefile is expired
            False if the cachefile is not expired, or file not exist
        """
        self.log("Checking to see if `%s` cache file has expired" % filepath)
        
        if os.path.exists(filepath):

            tstamp = time.ctime(os.path.getmtime(filepath))

            # There's an issue with .. I'm not 100% sure what. The datetime lib on stray versions of python?
            #   http://forum.kodi.tv/showthread.php?tid=112916&pid=1212394#pid1212394
            try:
                tstamp = datetime.strptime(tstamp, '%a %b %d %H:%M:%S %Y')
            except TypeError:
                tstamp = datetime.fromtimestamp(time.mktime(time.strptime(tstamp, '%a %b %d %H:%M:%S %Y')))

            if tstamp > datetime.utcnow() + timedelta(days=days):
                self.log("Cache file %s has expired" % filepath)
                return True

            self.log("Cache file %s has NOT expired" % filepath)
            return False

        self.log("Cache file %s does not exist! Returning as if expired" % filepath)
        return True

    def load_cache_file(self, filepath):
        """
        Load a json cache file and return its object
        Args:  
            file (str)      Full filepath of our cache file
        ReturnL
            object          Loaded object
            False           Error/Exception
        """
        self.log("Loading cache file %s" % filepath)
        try:
            with open(filepath) as handle:
                cache = json.load(handle)
            return cache
        except Exception as e:
            self.log(e.message)
            return False

        

class BassDrive(BDBase):

    def __init__(self):

        # Initialize our parent
        super(self.__class__, self).__init__()

        # Cache file infos
        self.cachefile = self.bd_config.get('cachefiles', 'streams')
        self.arcachefile = self.bd_config.get('cachefiles', 'archives')
        self.cache_streams_path = os.path.join(self.cachedir, self.cachefile)
        self.arcache_streams_path = os.path.join(self.cachedir, self.arcachefile)

    def build_xbmc_url(self, url):
        """
        Given a dict, urlencode it to give us a 'path' that XBMC will understand
        """
        return self.base_url + '?' + urllib.urlencode(url)

    def update_streams(self):
        """ 
        Get all of the m3u files from BassDrive
        parse them
        shove them into our json cache, with format
        {
            '32k'  : [ url1, url2, ... ],
            '56k'  : [ url1, url2, ... ],
            '128k' : [ url1, url2, ... ]
        }
        """

        def get_m3us(url):
            try:
                data = urlopen(url)
                return [line.strip() for line in data]
            except Exception as e:
                self.log(e.message)
                self.error(e.message)
                return False

        self.log("Pulling m3u's from bassdrive.com and building our stream cache")

        streams = {}
        for key, url in self.bd_config.items('streams'):
            urls = get_m3us(url)
            if not urls:
                continue
            streams[key] = urls

        self.log("Writing stream cache to file: %s" % self.cache_streams_path)
        with open(self.cache_streams_path, 'w+') as handle:
            json.dump(streams, handle)

        return True

    def update_archives(self):
        """
        - Parse bassdrive archives
        - Build dict of structure
        - Write json to disk

        The datastructure returned looks like this
        {
            u'1 - Monday': {
                u'Deep In The Jungle - Illusionist and Darm': {
                    '_files': [u'[2014.01.20] Deep In The Jungle - The Illusionist and Darm.mp3', ... ]
                },
                u'Fokuz Recordings Show': {
                    '_files': [u'[2016.01.11] Fokuz Recordings Show - SATL.mp3', ... ]
                ] ...
            u'2 - Tuesday': {
                ...
            ...
        }

        We opted to go with a data structure like this as it gives us quite a bit of flexibility
        Additionally, it allows us to track any level and mix of files and folders in a logical
        and easily accessed format. The tl;dr version is that _all_ key names are folder names, 
        with the exception of the '_files' keyname, which is an explicit list of files contained
        in that folder. In the example structure above, '_files' under the 'Deep In the Jungle' key
        are all of the files contained in the 'Deel In The Jungle' folder.
        """

        self.log("Building object of all archives from archives.bassdrive.com and writing cache file")

        def recursive_fetch(url):

            results = {}

            # We don't want to be going back upa level
            blacklisted_labels = [ 'Parent Directory' ]

            # Regex that we're searching for in our html
            anchor_re = re.compile('<a href=\".*</a>')
            hrefs = re.compile('(?<=href=\"(?!http)(?!/\")).*(?=\">)')
            text = re.compile('(?<=\">).*(?=</a>)')

            pars = HTMLParser.HTMLParser()
            url = pars.unescape(url)
            urlpath = urllib2.urlopen(url)
            req_data = urlpath.read().decode('utf-8')

            # Get all of our named anchors
            anchors = anchor_re.findall(req_data)

            # Traverse our anchors / web structure
            for item in anchors:

                # separate href value from the label of the anchor and strip all leading/trailing whitespace
                try:
                    url_path = re.search(hrefs, item).group(0).strip()
                    url_label = re.search(text, item).group(0).strip()

                # Handle edge cases, like when nothing matches
                except:
                    continue

                # Avoid infinite recursion
                if url_label in blacklisted_labels:
                    continue

                # If the path doesn't end in a slash, it's a file
                if re.search('/$', url_path) is None:
                    if not '_files' in results:
                        results['_files'] = []
                    results['_files'].append(url_label)

                else:

                    # Make our directory name .. not url encoded
                    dir_name = urllib.unquote(url_path).replace("/", "")

                    # Get this folders contents, and add a new folder to results if there is content in it
                    dir_contents = recursive_fetch(url + url_path)

                    if len(dir_contents) > 0:
                        results[dir_name] = dir_contents

            return results
                
        # Doing the whole structure under the 'Archive' key is a short-cut for us, so our fetch method is simple
        results = {'Archives':recursive_fetch('http://archives.bassdrivearchive.com')}
        with open(self.arcache_streams_path, 'w+') as handle:
            json.dump(results, handle)

    def get_archives_display_page(self, foldername):
        """
        Return a list that contains folders and files found in the foldername
        Params:
            foldername (list)    The result of self.args['foldername'].split('/')
                                    encountered during self.run() This list is the key tree
                                    that gets us to the current folder we're looking at
        Return:
            list, in format as follows
            [
                [file1, file2, file3],
                [foldername1, foldername2]
            ]
        """

        """
        Get the dict for the passed nested value
        eg: if we pass foldername = ['1 - Monday', 'Fokuz Recordings Show']
        we'll get a dictionary of {'_files':[...]} back
        """

        data = reduce(lambda d, k: d[k], foldername, self.load_cache_file(self.arcache_streams_path) )
        ret = [[]]
        if '_files' in data:
            ret[0] = data['_files']
            del(data['_files'])
        ret.append(data.keys())

        return ret

    def get_stream_to_play(self, quality):
        """ Return a random URL for a given bitrate requested to play
        :param quality: string of bitrate we're after, as a keyname in our json cachefile
        :return str: A URL to be played :D
        """
        self.log("Getting random %s stream to build 'playlist' with" % quality)
        cache = self.load_cache_file(self.cache_streams_path)
        return random.choice(cache[quality])

    def get_archive_url(self, foldername, filename):
        """
        Built a full URL to a file in the Archives
        Params:
            foldername (list)   The result of self.args['foldername'].split('/')
                                    encountered during self.run() This list is the key tree
                                    that gets us to the current folder we're looking at
            filename (str)      The actual filename we're after
        Return:
            str                 URL encoded string we can stream from directly
        """
        if foldername[0] == 'Archives':
            del(foldername[0])

        url = 'http://archives.bassdrivearchive.com/' + urllib.quote('/'.join(foldername) + '/' + filename)
        self.log('Built archive URL %s' % url)
        return url

    def maintenance_stream_cache(self):
        """
        Convienience function we call from run() to keep run tidy
        Checks if our stream cache exists, if it needs to be updated, etc
        """

        cachedays = int(self.bd_addon.getSetting("stream_cache_expiry_days"))

        # Ensure file exists / not expired. This returns as expired if the file doesn't exist!
        if self.cache_file_expired(filepath=self.cache_streams_path, days=cachedays) \
            or self.bd_addon.getSetting("forceupdate") == "true":
            self.bd_addon.setSetting(id="forceupdate", value="false")
            self.log("Maintenance request to update stream cache")
            self.update_streams()
            return

    def maintenance_archive_cache(self):
        """
        Convienience function we call from run() to keep run tidy
        Checks if our archives cache exists, if it needs to be updated, etc
        """

        cachedays = int(self.bd_addon.getSetting("archives_cache_expiry_days"))

        # Ensure file exists / not expired. This returns as expired if the file doesn't exist!
        if self.cache_file_expired(filepath=self.arcache_streams_path, days=cachedays) \
            or self.bd_addon.getSetting("archives_forceupdate") == "true":
            self.bd_addon.setSetting(id="archives_forceupdate", value="false")
            self.log("Maintenance request to update archive cache")
            self.update_archives()

    def run(self):

        self.log(self.args)

        # Check to see if our cache has expired
        self.maintenance_stream_cache()

        # List of values we're to display in the menu we're on
        directory_items = []

        # We're at the top level menu
        #   - Bassdrive @32k
        #   - Bassdrive @56k
        #   - Bassdrive @128k
        #   - Archives
        if self.mode is None:

            # Build playable bitrate menu items
            for key, _x in self.bd_config.items('streams'):

                # This currently displays a menu item with a bound URL behind it
                #   Ideally, we wouldn't generate a URL until the item was selected
                #   This would allow multiple clicks to get multiple stream URLs, 
                #   basically letting you cycle through streams without having to reload
                #   the bassdrive plugin
                url = self.get_stream_to_play(key)

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
                directory_items.append((url, li, isFolder))
                xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=url, listitem=li, isFolder=False)

            # Add in our 'Archives' folder menu item
            archive_url = self.build_xbmc_url({'mode': 'folder', 'foldername': 'Archives'})
            test = xbmcgui.ListItem(label="Archives")
            xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=archive_url, listitem=test, isFolder=True)
            xbmcplugin.endOfDirectory(self.bd_handle, succeeded=True)

        # We're in a sub-menu
        elif self.mode[0] == 'folder':

            # Handle our archive cache, since we're now in it
            self.maintenance_archive_cache()

            # The path of the directory that called for this folder relative to the pugins root (./)
            calling_folder = self.args['foldername'][0]

            # Create a list of the full filepath of our current run
            self.foldername = self.args['foldername'][0].split('/')

            # Get our files and folders to display
            display_data = self.get_archives_display_page(self.foldername)

            # Display files/streams to play
            for playable in sorted(display_data[0]):

                # Build our URL and add the item!
                url = self.get_archive_url(foldername=self.foldername, filename=playable)

                # Generate a list item for Kodi
                li = xbmcgui.ListItem(label=playable, thumbnailImage="%s" % os.path.join(self.bd_ppath,'icon.png'))

                # Set player info
                li.setInfo(type="Music", infoLabels={"Genre": "Drum & Bass",
                                                     "Comment": "World Wide Drum & Bass" })

                li.setProperty("IsPlayable", "true")
                directory_items.append((url, li, False))
                xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=url, listitem=li, isFolder=False)


            # Display folders
            for folder in sorted(display_data[1]):

                # Build the relative URL for this item (this is XBMC URL lingo)
                archive_url = self.build_xbmc_url({'mode': 'folder', 'foldername': '%s/%s' % (calling_folder, folder) })
                item = xbmcgui.ListItem(label=folder)
                xbmcplugin.addDirectoryItem(handle=self.bd_handle, url=archive_url, listitem=item, isFolder=True)

            # when we're done adding items to the directory, finish drawing it.
            xbmcplugin.endOfDirectory(self.bd_handle, succeeded=True)

        # Success
        return True


MusicAddonInstance = BassDrive()
MusicAddonInstance.run()
