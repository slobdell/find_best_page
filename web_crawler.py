import gevent.pool
import json
import requests
import sys

from bs4 import BeautifulSoup
from collections import OrderedDict
from gevent import monkey

IGNORED_FILE_EXTENSIONS = {
    ".eps",
    ".jpg",
    ".jpeg",
    ".JPG",
    ".JPEG",
    ".png",
    ".PNG",
    ".gif",
    ".GIF",
    ".pdf",
    ".PDF"
}

FACEBOOK_QUERY = "https://graph.facebook.com/v1.0/?ids=%s"
POOL_SIZE = 16


def chunks(iterable, total_size, n):
    for start in xrange(0, total_size, n):
        end = start + n
        yield iterable[start:end]


class FacebookContentFinder(object):
    def __init__(self, base_domain):
        self.base_domain = base_domain.strip("/")
        self.all_links = set()
        self.min_str_length, self.max_str_length = self._establish_min_max_ignorables()
        self.pool = gevent.pool.Pool(POOL_SIZE)
        self.greenlets = []

    def _establish_min_max_ignorables(self):
        min_str_length = 99999
        max_str_length = 0
        for str in IGNORED_FILE_EXTENSIONS:
            if len(str) > max_str_length:
                max_str_length = len(str)
            if len(str) < min_str_length:
                min_str_length = len(str)
        return min_str_length, max_str_length


    def _should_ignore_because_is_file(self, url):
        for length in xrange(self.min_str_length, self.max_str_length + 1):
            last_chars_of_url = url[length * -1:]
            if last_chars_of_url in IGNORED_FILE_EXTENSIONS:
                return True
        return False

    def _should_ignore_because_crawled(self, url):
        return url in self.all_links

    def _should_ignore_because_external_link(self, url):
        return self.base_domain not in url

    def _should_ignore(self, url):
        for func in (self._should_ignore_because_is_file,
                     self._should_ignore_because_crawled,
                     self._should_ignore_because_external_link):
            if func(url):
                return True
        return False

    def _reformat_url(self, url):
        # TODO handle ".." case...?
        if url.startswith("/"):
            url = "%s%s" % (self.base_domain, url)

        last_url_portion = url.split("/")[-1]
        for char in ('#', '?',):
            try:
                fragment_identifier_index = last_url_portion.index(char)
                last_url_portion = last_url_portion[0:fragment_identifier_index]
                # reconstruct the URL without any fragment identifiers
                url = "%s/%s" % ("/".join(url.split("/")[:-1]), last_url_portion)
            except ValueError:
                pass
        return url.strip("/")

    def find_links_in_url(self, url):
        if url is None:
            return
        url = self._reformat_url(url)
        if self._should_ignore(url):
            return
        self.all_links.add(url)
        print "Found %s" % url
        try:
            response = requests.get(url)
        except requests.exceptions.SSLError:
            print "SSL error on %s, skipping" % url
            return
        except requests.exceptions.ConnectionError:
            print "Connection error on %s, skipping" % url
            return
        data = response.text
        soup = BeautifulSoup(data)
        for link in soup.find_all('a'):
            url = link.get('href')
            self.find_links_in_url(url)
            self.greenlets.append(self.pool.spawn(self.find_links_in_url, url))

    def get_facebook_scores(self):
        site_to_shares = {}
        all_links = list(self.all_links)
        for list_of_links in chunks(all_links, len(all_links), 50):
            all_urls_str = ",".join(list_of_links)
            print "Making a call to Facebook..."
            response = requests.get(FACEBOOK_QUERY % all_urls_str)
            json_data = json.loads(response.text)
            for url in json_data.keys():
                site_data = json_data[url]
                shares = site_data.get("shares")
                if shares:
                    site_to_shares[url] = shares
        site_to_shares = OrderedDict(sorted(site_to_shares.items(), key=lambda t: t[1], reverse=True))
        return site_to_shares

    def crawl(self):
        self.greenlets.append(self.pool.spawn(self.find_links_in_url, self.base_domain))
        gevent.joinall(self.greenlets)
        return self.get_facebook_scores()

if __name__ == "__main__":
    monkey.patch_socket()
    monkey.patch_ssl()
    if len(sys.argv) > 1:
        url = sys.argv[1]
        domain_crawler = FacebookContentFinder(url)
        print domain_crawler.crawl()
    else:
        print "Pass in a website 2nd arg"
