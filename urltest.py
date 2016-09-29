#! /usr/bin/env python

import HTMLParser
import urllib2
import urllib
import re

debug=False

#base_url = 'http://archives.bassdrivearchive.com/2%20-%20Tuesday/'
base_url = 'http://archives.bassdrivearchive.com'
#results = []
blacklisted_labels = [ 'Parent Directory' ]

anchor_re = re.compile('<a href=\".*</a>')
hrefs = re.compile('(?<=href=\"(?!http)(?!/\")).*(?=\">)')
text = re.compile('(?<=\">).*(?=</a>)')

#'<a href="/1%20-%20Monday/"> Parent Directory</a></li>''

# undo html encoding.
# urllib.unquote('<string>') 

pars = HTMLParser.HTMLParser()


def fetch_shit(url):
    results = []
    url = pars.unescape(url)

    if debug: print("[+] Searching " + url)
    
    urlpath = urllib2.urlopen(url)

    req_data = urlpath.read().decode('utf-8')
    anchors = anchor_re.findall(req_data)

    if debug: print("[+] ANCHORS:")
    if debug: print(anchors)
    for item in anchors:

        try:
            # separate href value from the label of the anchor and strip all leading/trailing whitespace
            url_path = re.search(hrefs,item).group(0).strip()
            url_label = re.search(text,item).group(0).strip()

        except:
            continue

        if url_label in blacklisted_labels:
            continue

        if re.search('/$',url_path) is None:
            # if it doesn't end in a slash, it's a file.
            results.append(urllib.unquote(url_path))
        else:
            if debug: print("[+] New dir " + item + ", recursing")

            sanitized_dir_name = urllib.unquote(url_path).replace("/","")

            results.append( { sanitized_dir_name : fetch_shit(url + url_path)})
    
    #return req_data
    return results


archive_data = fetch_shit(base_url)