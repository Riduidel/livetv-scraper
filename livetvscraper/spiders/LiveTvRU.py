#!/usr/bin/python
# -*- coding: utf-8 -*-
import traceback
import inspect
import locale
import dateparser
import scrapy
from scrapy import Request, Selector
from urlextract import URLExtract

class LiveTvRUSpider(scrapy.Spider):

    PARAM_BROWSER_LINKS = {
        'fr_FR': 'Liens pour le navigateur'
    }

    name = 'livetv'

    def __init__(self,
                 lang='fr_FR',
                 sport='Rugby à XV',
                 timezone='Europe/Paris',
                 preferred='Clermont,Toulouse',
                 *args, **kwargs):
        """
        Build the spider

        lang: A classical locale
        sport: The sport you want to scrape, in the given lang
        timezone: TImezone used to scan results. It seems to depend upon the chosen lang, so dont use the timezone of your own country
        preferred: The preferred team. This should contain a comma separated list of team. These teams will be used to reorder lives, and the first in that list will be the scraped live
        """
        super(LiveTvRUSpider, self).__init__(*args, **kwargs)
        self.PARAM_LANG = lang
        locale.setlocale(locale.LC_ALL, lang)
        self.PARAM_SPORT = sport
        self.PARAM_TIMEZONE = timezone
        self.PARAM_PREFERRED = preferred.split(',')
        self.start_urls = ['http://livetv.ru/?lng=%s' % self.PARAM_LANG]

    def parse(self, response):

        # So we have the LiveTV page!
        # Let's find the diffusions link and click on it
        # Diffusions can be found with response.xpath("//a[@class='menu' and contains(@href, 'allupcoming')]").getall()

        allupcoming_element = response.xpath(
            "//a[@class='menu' and contains(@href, 'allupcoming')]")
        allupcoming_text = allupcoming_element.get()
        self.logger.info('#parse - Found all upcoming events to be %s' %
                         allupcoming_text)
        if allupcoming_text is not None:
            allupcoming_href = response.urljoin(
                allupcoming_element.css('a::attr(href)').get())
            self.logger.info('#parse - We will follow link %s' % allupcoming_href)
            yield Request(allupcoming_href, callback=self.parse_all_upcoming)

    def parse_all_upcoming(self, response):
        allsports = response.css("a[class='main']")
        for (index, sport_selector) in enumerate(allsports):
            sport = sport_selector.get()
            if self.PARAM_SPORT in sport:
                self.logger.info('#parse_all_upcoming - Sport element is %s' % sport)
                url = sport_selector.css('a::attr(href)').get()
                url = response.urljoin(url)
                yield Request(url, callback=self.parse_all_upcoming_events_of_sport)

    def to_local_date(self, text):
        return dateparser.parse(text, settings={'TIMEZONE': self.PARAM_TIMEZONE})

    def extract_table_containing_events_of_sport(self, response):
        # We use the getall()[1] since the header is in a table itself in a table.
        # As we want the second, we haev to use that syntax
        page_title_xpath = "//span[@class='sltitle' and text()='%s']" % self.PARAM_SPORT
        page_title = response.xpath(page_title_xpath)
        self.logger.info('#extract_table_containing_events_of_sport - For lookup %s Page title container is %s' %
                         (page_title_xpath, page_title.get()))
        page_title_table = page_title.xpath('../../..')
        page_title_table_tag = page_title_table.xpath('name()').get()
        assert page_title_table_tag == 'table', \
            'Three levels upper page title, we should find a table! (but is "%s")' \
            % page_title_table_tag
        page_center_table = page_title_table.xpath('../../..')
        page_center_table_tag = page_center_table.xpath('name()').get()
        assert page_center_table_tag == 'table', \
            'Three levels upper page title container table, we should find a table! (but is "%s")' \
            % page_center_table_tag
        return page_center_table

    def parse_all_upcoming_events_of_sport(self, response):
        page_center_table = self.extract_table_containing_events_of_sport(
            response)
        all_upcoming_lives = page_center_table.xpath(".//td[a[@class='live']]")
        lives = []
        for live in all_upcoming_lives:
            url = response.urljoin(live.css('a::attr(href)').get())
            live_details = {
                'url': url,
                'text': live.css('a::text').get(),
                'live': live.css('img').get() is not None,
                # BEWARE: It seems like russian use UTC time! So it has to be adjusted to local time
                'date': self.to_local_date(live.xpath("./span[@class='evdesc']/text()[1]"
                                                      ).get().strip()),
                'category': live.xpath("./span[@class='evdesc']/text()[2]"
                                       ).get().strip(),
            }
            if live_details['live']:
                lives.append(live_details)
        if lives:
            lives = self.reorder_according_to_preferences(lives)
            live_details = lives[0]
            yield Request(live_details['url'], callback=self.parse_all_streams_of_event, cb_kwargs=live_details)

    def reorder_according_to_preferences(self, lives):
        """
        Reorder lives according to preferred teams
        """
        NOT_PREFERRED = "none of these teams is a preferred one"
        teams_matches = {}
        teams_matches[NOT_PREFERRED] = []
        for item in lives:
            found = False
            for team in self.PARAM_PREFERRED:
                if team in item['text']:
                    found = True
                    teams_matches[team] = [item]
            if not found:
                teams_matches[NOT_PREFERRED].append(item)
        # Now they're sorted, let's assemble that
        returned = []
        for team in self.PARAM_PREFERRED:
            if team in teams_matches:
                returned += teams_matches[team]
        if not returned:
            returned = teams_matches[NOT_PREFERRED]
        return returned

    def parse_all_streams_of_event(self, response, url, text, live, date, category):
        if live:
            self.logger.info("#parse_all_streams_of_event - parsing event %s" % (url))
            lookup = "//span[text()='%s']" % (self.PARAM_BROWSER_LINKS[self.PARAM_LANG])
            browser_link = response.xpath(lookup)
            if not browser_link.get():
                path = 'no_stream.html'
                file = open(path, 'w')
                file.write(response.text)
                self.logger.error(
                    "#parse_all_streams_of_event - Unable to find the lookup %s in page loaded from %s" % (lookup, response.url))
                return
            self.logger.info("#parse_all_streams_of_event - lookup is %s, found browser link %s" % (lookup, browser_link.get()))
            browser_link_table = browser_link.xpath('../../..')
            stream_table = browser_link_table.xpath('../table[2]')
            stream_link_descriptors = stream_table.xpath(
                ".//table[@class='lnktbj']")
            stream_links = []
            for descriptor in stream_link_descriptors:
                try:
                    quality = int(descriptor.xpath(
                        ".//td[@class='rate']/div/text()").get())
                except ValueError:
                    # Unknown quality feeds are left with quality of 0
                    quality = 0
                link = response.urljoin(descriptor.xpath(".//a/@href").get())
                stream_links.append({'url': link, 'quality': quality})
            stream_links = sorted(stream_links, key=lambda k: -1*k['quality'])
            # Now, open the top quality link
            opened = stream_links[0]
            self.logger.info("#parse_all_streams_of_event - Opening %s" % (opened))
            yield Request(opened['url'], callback=self.open_webplayer_container, cb_kwargs={'event_name':text, 'event_date':date, 'event_url':response.url})

    def open_webplayer_container(self, response, event_url, event_name, event_date):
        """
        So, viewer is in an iframe. And that iframe will contain a redirect. Let's hope scrapy is able to handle that
        """
        self.logger.info("#open_webplayer_container - So we're now on %s"%(response.url))
        webplayer_url = response.urljoin(response.xpath("//iframe/@src").get())
        yield Request(webplayer_url, callback=self.open_webplayer_page, cb_kwargs={'event_name':event_name, 'event_date':event_date, 'event_url':event_url})

    def open_webplayer_page(self, response, event_url, event_name, event_date):
        """
        So we're on direct webplayer page, which should have a very weird URL
        Maybe I'm gonna be able to finally find that m3u8 file
        """
        self.logger.info("#open_webplayer_page - Let's see what we can get from %s"%(response.url))
        # So the first case we know is sports-stream.
        # If we're on that site, let's handle it correctly
        if "sports-stream.link" in response.url:
            self.read_stream_from_sports_stream(response, event_url, event_name, event_date)
        elif "assia.tv" in response.url:
            self.read_stream_from_assia_tv(response, event_url, event_name, event_date)
        else:
            self.logger.error("#open_webplayer_page - We don't know how to handle video stream coming from %s"%(response.url))
    
    def read_stream_from_assia_tv(self, response, event_url, event_name, event_date):
        scripts = response.css("script")
        extractor = URLExtract()
        for s in scripts:
            text = s.get()
            if extractor.has_urls(text):
                for url in extractor.gen_urls(text):
                    if "video.assia.tv" in url:
                        self.logger.info("#read_stream_from_assia_tv - found video stream url %s!"%(url))
                        if "m3u8" in url:
                            # This is the video playlist we're looking for! So let's download that periodically
                            # And save the .ts fragments (but this will require another spider)

    def read_stream_from_sports_stream(self, response, event_url, event_name, event_date):
        """
        This method is dedicated to reading stream from sports-stream
        """
        player_url = response.xpath("//iframe/@src")
        yield Request(player_url, callback=self.read_stream_from_sports_stream_iframe, cb_kwargs={'event_name':event_name, 'event_date':event_date, 'event_url':event_url})

    def read_stream_from_sports_stream_iframe(self, response, event_url, event_name, event_date):
        """
        Now let's check which script contains the feed description, and obtain the corresponding m3u8 file
        """
        scripts = response.css("script")
        for s in scripts:
            text = s.get()
            if "fid=" in text:
                self.logger.info("#read_stream_from_sports_stream_iframe - found the script containing script configuration %s"%(text))
                # This should be sent as parameter to embeddedWHATEVER


if __name__ == '__main__':
    import os
    from scrapy.cmdline import execute

    os.chdir(os.path.dirname(os.path.realpath(__file__)))

    SPIDER_NAME = LiveTvRUSpider.name
    try:
        execute(
            [
                'scrapy',
                'crawl',
                SPIDER_NAME,
                '-a',
                'sport=Football',
                '-a',
                'preferred=Majorque',
            ]
        )
    except SystemExit:
        traceback.print_exc() 