#!/usr/bin/python
# -*- coding: utf-8 -*-
import locale
import dateparser
import scrapy
from scrapy import Request, Selector
import logging
logger = logging.getLogger(__name__)


class LiveTvRUSpider(scrapy.Spider):

    PARAM_LANG = 'fr_FR'
    PARAM_SPORT = 'Rugby à XV'
    PARAM_TIMEZONE = 'Europe/Paris'
    name = 'livetv'

    def start_requests(self):
        locale.setlocale(locale.LC_ALL, self.PARAM_LANG)
        # TODO adapt language tu user language (see how to use Scrapy settings object)
        urls = ['http://livetv.ru/?lng=%s' % self.PARAM_LANG]
        for url in urls:
            yield Request(url, callback=self.parse)

    def parse(self, response):

        # So we have the LiveTV page!
        # Let's find the diffusions link and click on it
        # Diffusions can be found with response.xpath("//a[@class='menu' and contains(@href, 'allupcoming')]").getall()

        allupcoming_element = response.xpath("//a[@class='menu' and contains(@href, 'allupcoming')]")
        allupcoming_text = allupcoming_element.get()
        logger.info('Found all upcoming events to be %s' % allupcoming_text)
        if allupcoming_text is not None:
            allupcoming_href = response.urljoin(allupcoming_element.css('a::attr(href)').get())
            logger.info('We will follow link %s' % allupcoming_href)
            yield Request(allupcoming_href, callback=self.parse_all_upcoming)

    def parse_all_upcoming(self, response):
        allsports = response.css("a[class='main']")
        for (index, sport_selector) in enumerate(allsports):
            sport = sport_selector.get()
            if self.PARAM_SPORT in sport:
                logger.info('Sport element is %s' % sport)
                url = sport_selector.css('a::attr(href)').get()
                url = response.urljoin(url)
                yield Request(url, callback=self.parse_all_upcoming_events_of_sport)

    def to_local_date(self, text):
        return dateparser.parse(text, settings={'TIMEZONE': self.PARAM_TIMEZONE})

    def extract_table_containing_events_of_sport(self, response):
        # We use the getall()[1] since the header is in a table itself in a table.
        # As we want the second, we haev to use that syntax
        page_title = response.xpath("//span[@class='sltitle' and text()='%s']" % self.PARAM_SPORT)
        logger.info('Page title container is %s' % page_title.get())
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
        page_center_table = self.extract_table_containing_events_of_sport(response)
        all_upcoming_lives = page_center_table.xpath(".//td[a[@class='live']]")
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
            logger.info('Details of %s' % live_details)
            yield Request(url, callback=self.parse_all_streams_of_event)

    def parse_all_streams_of_event(self, response):
        logger.info("We should get streams of %s" % response)
