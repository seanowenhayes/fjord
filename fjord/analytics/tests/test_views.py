import json
import logging
from datetime import datetime, timedelta

from nose.tools import eq_
from pyelasticsearch.exceptions import Timeout
from pyquery import PyQuery

from django.contrib.auth.models import Group
from django.http import QueryDict

from fjord.analytics import views
from fjord.analytics.views import counts_to_options, _zero_fill
from fjord.base.tests import TestCase, LocalizingClient, profile, reverse, user
from fjord.base.util import epoch_milliseconds
from fjord.feedback.tests import response
from fjord.search.tests import ElasticTestCase


logger = logging.getLogger(__name__)


class TestCountsHelper(TestCase):
    def setUp(self):
        self.counts = [('apples', 5), ('bananas', 10), ('oranges', 6)]

    def test_basic(self):
        """Correct options should be set and values should be sorted.
        """
        options = counts_to_options(self.counts, 'fruit', 'Fruit')
        eq_(options['name'], 'fruit')
        eq_(options['display'], 'Fruit')

        eq_(options['options'][0], {
            'name': 'bananas',
            'display': 'bananas',
            'value': 'bananas',
            'count': 10,
            'checked': False,
        })
        eq_(options['options'][1], {
            'name': 'oranges',
            'display': 'oranges',
            'value': 'oranges',
            'count': 6,
            'checked': False,
        })
        eq_(options['options'][2], {
            'name': 'apples',
            'display': 'apples',
            'value': 'apples',
            'count': 5,
            'checked': False,
        })

    def test_map_dict(self):
        options = counts_to_options(self.counts, 'fruit', display_map={
            'apples': 'Apples',
            'bananas': 'Bananas',
            'oranges': 'Oranges',
        })
        # Note that options get sorted by count.
        eq_(options['options'][0]['display'], 'Bananas')
        eq_(options['options'][1]['display'], 'Oranges')
        eq_(options['options'][2]['display'], 'Apples')

    def test_map_func(self):
        options = counts_to_options(self.counts, 'fruit',
            value_map=lambda s: s.upper())
        # Note that options get sorted by count.
        eq_(options['options'][0]['value'], 'BANANAS')
        eq_(options['options'][1]['value'], 'ORANGES')
        eq_(options['options'][2]['value'], 'APPLES')

    def test_checked(self):
        options = counts_to_options(self.counts, 'fruit', checked='apples')
        # Note that options get sorted by count.
        assert not options['options'][0]['checked']
        assert not options['options'][1]['checked']
        assert options['options'][2]['checked']


class TestZeroFillHelper(TestCase):
    def test_zerofill(self):
        start = datetime(2012, 1, 1)
        end = datetime(2012, 1, 7)
        data1 = {
            epoch_milliseconds(datetime(2012, 1, 3)): 1,
            epoch_milliseconds(datetime(2012, 1, 5)): 1,
        }
        data2 = {
            epoch_milliseconds(datetime(2012, 1, 2)): 1,
            epoch_milliseconds(datetime(2012, 1, 5)): 1,
            epoch_milliseconds(datetime(2012, 1, 10)): 1,
        }
        _zero_fill(start, end, [data1, data2])

        for day in range(1, 8):
            millis = epoch_milliseconds(datetime(2012, 1, day))
            assert millis in data1, "Day %s was not zero filled." % day
            assert millis in data2, "Day %s was not zero filled." % day


class TestDashboardView(ElasticTestCase):
    client_class = LocalizingClient

    def setUp(self):
        super(TestDashboardView, self).setUp()
        # Set up some sample data
        # 4 happy, 3 sad.
        # 2 Windows XP, 2 Linux, 1 OS X, 2 Windows 7
        now = datetime.now()
        # The dashboard by default shows the last week of data, so
        # these need to be relative to today. The alternative is that
        # every test gives an explicit date range, and that is
        # annoying and verbose.
        items = [
            # happy, platform, locale, description, created
            (True, '', 'en-US', 'apple', now - timedelta(days=6)),
            (True, 'Windows 7', 'es', 'banana', now - timedelta(days=5)),
            (True, 'Linux', 'en-US', 'orange', now - timedelta(days=4)),
            (True, 'Linux', 'en-US', 'apple', now - timedelta(days=3)),
            (False, 'Windows XP', 'en-US', 'banana', now - timedelta(days=2)),
            (False, 'Windows 7', 'en-US', 'orange', now - timedelta(days=1)),
            (False, 'Linux', 'es', u'\u2713 apple', now - timedelta(days=0)),
        ]
        for happy, platform, locale, description, created in items:
            # We don't need to keep this around, just need to create it.
            response(happy=happy, platform=platform, locale=locale,
                     description=description, created=created, save=True)

        self.refresh()

    def test_front_page(self):
        url = reverse('dashboard')
        r = self.client.get(url)
        eq_(200, r.status_code)
        self.assertTemplateUsed(r, 'analytics/dashboard.html')

        pq = PyQuery(r.content)
        # Make sure that each opinion is shown and that the count is correct.
        eq_(pq('.block.count strong').text(), '7')
        eq_(len(pq('li.opinion')), 7)

    def test_dashboard_atom_links(self):
        """Test dashboard atom links are correct"""
        r = self.client.get(reverse('dashboard'))
        eq_(200, r.status_code)
        assert '/en-US/?format=atom' in r.content

        r = self.client.get(
            reverse('dashboard'),
            {'happy': 1})
        eq_(200, r.status_code)
        pq = PyQuery(r.content)
        pq = pq('link[type="application/atom+xml"]')
        qs = QueryDict(pq[0].attrib['href'].split('?')[1])
        eq_(qs['happy'], u'1')
        eq_(qs['format'], u'atom')

        r = self.client.get(
            reverse('dashboard'),
            {'product': 'Firefox', 'version': '20.0.0'})
        eq_(200, r.status_code)
        pq = PyQuery(r.content)
        pq = pq('link[type="application/atom+xml"]')
        qs = QueryDict(pq[0].attrib['href'].split('?')[1])
        eq_(qs['product'], u'Firefox')
        eq_(qs['version'], u'20.0.0')

    def test_truncated_description_on_dashboard(self):
        # Create a description that's 500 characters long (which is
        # the truncation length) plus a string that's easy to assert
        # non-existence of.
        desc = ('0' * 500) + 'OMGou812'
        response(description=desc, save=True)
        self.refresh()

        url = reverse('dashboard')
        r = self.client.get(url)
        assert 'OMGou812' not in r.content

    def test_search(self):
        url = reverse('dashboard')
        # Happy
        r = self.client.get(url, {'happy': 1})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 4)

        # Sad
        r = self.client.get(url, {'happy': 0})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 3)

        # Locale
        r = self.client.get(url, {'locale': 'es'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 2)

        # Platform and happy
        r = self.client.get(url, {'happy': 1, 'platform': 'Linux'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 2)

        # Product
        r = self.client.get(url, {'product': 'Firefox'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 7)

        # Product
        r = self.client.get(url, {'product': 'Firefox for Android'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 0)

        # Product version
        r = self.client.get(
            url, {'product': 'Firefox', 'version': '17.0.0'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 7)

        # Product version
        r = self.client.get(
            url, {'product': 'Firefox', 'version': '18.0.0'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 0)

        # Empty search
        r = self.client.get(url, {'platform': 'Atari'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 0)

    def test_empty_and_unknown(self):
        url = reverse('dashboard')

        # Empty value should work
        r = self.client.get(url, {'platform': ''})
        eq_(r.status_code, 200)
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 1)

        # "Unknown" value should also work
        r = self.client.get(url, {'platform': 'Unknown'})
        eq_(r.status_code, 200)
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 1)

    def test_version_noop(self):
        """version has no effect if product isn't set"""
        url = reverse('dashboard')

        # Filter on product and version--both filters affect the
        # results
        r = self.client.get(
            url, {'product': 'Firefox', 'version': '18.0.0'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 0)

        # Filter on version--filter has no effect on results
        r = self.client.get(
            url, {'version': '18.0.0'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 7)

    def test_text_search(self):
        url = reverse('dashboard')
        # Text search
        r = self.client.get(url, {'q': 'apple'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 3)
        # Text and filter
        r = self.client.get(url, {'q': 'apple', 'happy': 1, 'locale': 'en-US'})
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 2)

    def test_text_search_unicode(self):
        """Unicode in the search field shouldn't kick up errors"""
        url = reverse('dashboard')
        # Text search
        r = self.client.get(url, {'q': u'\u2713'})
        eq_(r.status_code, 200)

    def test_search_format_json(self):
        """JSON output works"""
        url = reverse('dashboard')
        # Text search
        r = self.client.get(url, {'q': u'apple', 'format': 'json'})
        eq_(r.status_code, 200)

        content = json.loads(r.content)
        eq_(content['total'], 3)
        eq_(len(content['results']), 3)

    def test_search_format_atom(self):
        """Atom output works"""
        url = reverse('dashboard')
        # Text search
        r = self.client.get(url, {'q': u'apple', 'format': 'atom'})
        eq_(r.status_code, 200)

        assert 'http://www.w3.org/2005/Atom' in r.content

    # FIXME - This was backed out. We can re-enable this test when urls are
    # re-added.
    # def test_search_format_atom_has_related_links(self):
    #     """Atom output works"""
    #     response(description='relatedlinks', url='http://example.com', save=True)
    #     self.refresh()

    #     url = reverse('dashboard')
    #     # Text search
    #     r = self.client.get(url, {'q': 'relatedlinks', 'format': 'atom'})
    #     eq_(r.status_code, 200)

    #     assert 'http://www.w3.org/2005/Atom' in r.content
    #     # FIXME: This is a lousy way to test for a single link with
    #     # both attributes.
    #     assert 'rel="related"' in r.content
    #     assert 'href="http://example.com"' in r.content

    def test_date_search(self):
        url = reverse('dashboard')
        # These start and end dates will give known slices of the data.
        # Silly relative dates.
        start = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d'),
        end = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d'),

        # Unspecified start => (-infin, end]
        r = self.client.get(url, {
                'date_end': end,
            })
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 5)

        # Unspecified end => [start, +infin)
        r = self.client.get(url, {
                'date_start': start
            })
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 6)

        # Both start and end => [start, end]
        r = self.client.get(url, {
                'date_start': start,
                'date_end': end,
            })
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 4)

    def test_date_start_valueerror(self):
        # https://bugzilla.mozilla.org/show_bug.cgi?id=898584
        url = reverse('dashboard')
        r = self.client.get(url, {
                'date_start': '0001-01-01',
            })
        eq_(r.status_code, 200)

    def test_invalid_search(self):
        url = reverse('dashboard')
        # Invalid values for happy shouldn't filter
        r = self.client.get(url, {'happy': 'fish'})
        eq_(r.status_code, 200)
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 7)
        # Unknown parameters should be ignored.
        r = self.client.get(url, {'apples': 'oranges'})
        eq_(r.status_code, 200)
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 7)
        # A broken date range search shouldn't affect anything
        # Why this? Because this is the thing the fuzzer found.
        r = self.client.get(url, {
                'date_end': '/etc/shadow\x00',
                'date_start': '/etc/passwd\x00'
                })
        eq_(r.status_code, 200)
        pq = PyQuery(r.content)
        eq_(len(pq('li.opinion')), 7)

    def test_frontpage_index_missing(self):
        """If index is missing, show es_down template."""
        self.teardown_indexes()
        resp = self.client.get(reverse('dashboard'))
        self.assertTemplateUsed(resp, 'analytics/es_down.html')

    def test_zero_fill(self):
        """If a day in a date range has no data, it should be zero filled."""
        # Note that we request a date range that includes 3 days without data.
        url = reverse('dashboard')
        start = (datetime.now() - timedelta(days=9))
        end = (datetime.now() - timedelta(days=3))

        r = self.client.get(url, {
                'date_start': start.strftime('%Y-%m-%d'),
                'date_end': end.strftime('%Y-%m-%d'),
            })
        # The histogram data is of the form [d, v], where d is a number of
        # milliseconds since the epoch, and v is the value at that time stamp.
        dates = [d[0] for d in r.context['histogram'][0]['data']]
        dates = [datetime.fromtimestamp(d / 1000) for d in dates]
        days = [d.day for d in dates]

        d = start
        while d <= end:
            assert d.day in days, "Day %s has no data." % d.day
            d += timedelta(days=1)

    def test_frontpage_es_down(self):
        """If can't connect to ES, show es_down template."""
        # TODO: Rewrite this with Mock.
        old_counts_to_options = views.counts_to_options
        try:
            def mock_counts_to_options(*args, **kwargs):
                raise Timeout()
            views.counts_to_options = mock_counts_to_options

            resp = self.client.get(reverse('dashboard'))
            self.assertTemplateUsed(resp, 'analytics/es_down.html')

        finally:
            views.counts_to_options = old_counts_to_options


class TestResponseview(ElasticTestCase):
    client_class = LocalizingClient

    def test_response_view(self):
        """Test dashboard link goes to response view"""
        resp = response(happy=True, description=u'the best!', save=True)

        self.refresh()

        url = reverse('dashboard')
        r = self.client.get(url)
        eq_(200, r.status_code)
        self.assertTemplateUsed(r, 'analytics/dashboard.html')

        pq = PyQuery(r.content)
        # Get the permalink
        permalink = pq('li.opinion a[href*="response"]').attr('href')

        r = self.client.get(permalink)
        eq_(200, r.status_code)
        self.assertTemplateUsed(r, 'analytics/response.html')
        assert str(resp.description) in r.content

    def test_response_view_mobile(self):
        """Test response mobile view doesn't die"""
        resp = response(happy=True, description=u'the best!', save=True)

        self.refresh()

        r = self.client.get(reverse('response_view', args=(resp.id,)),
                            {'mobile': 1})
        eq_(200, r.status_code)
        self.assertTemplateUsed(r, 'analytics/mobile/response.html')
        assert str(resp.description) in r.content


class TestAnalyticsDashboardView(ElasticTestCase):
    client_class = LocalizingClient

    def test_permissions(self):
        # Verifies that only analyzers can see the analytics dashboard
        # link
        resp = self.client.get(reverse('dashboard'))
        eq_(200, resp.status_code)
        assert 'adashboard' not in resp.content

        # Verifies that only analyzers can see the analytics dashboard
        resp = self.client.get(reverse('analytics_dashboard'))
        eq_(403, resp.status_code)

        # Verify analyzers can see analytics dashboard link
        jane = user(email='jane@example.com', save=True)
        profile(user=jane, save=True)
        jane.groups.add(Group.objects.get(name='analyzers'))

        self.client_login_user(jane)
        resp = self.client.get(reverse('dashboard'))
        eq_(200, resp.status_code)
        assert 'adashboard' in resp.content

        # Verify analyzers can see analytics dashboard
        resp = self.client.get(reverse('analytics_dashboard'))
        eq_(200, resp.status_code)


class TestOccurrencesReportView(ElasticTestCase):
    client_class = LocalizingClient

    def setUp(self):
        super(TestOccurrencesReportView, self).setUp()
        # Set up some sample data
        items = [
            # happy, locale, description
            (True, 'en-US', 'apple banana orange pear'),
            (True, 'en-US', 'orange pear kiwi'),
            (True, 'en-US', 'chocolate chocolate yum'),
            (False, 'en-US', 'apple banana grapefruit'),

            # This one doesn't create bigrams because there isn't enough words
            (False, 'en-US', 'orange'),

            # This one shouldn't show up
            (False, 'es', 'apple banana'),
        ]
        for happy, locale, description in items:
            response(
                happy=happy, locale=locale, description=description, save=True)

        self.refresh()

        # Create analyzer and log analyzer in
        jane = user(email='jane@example.com', save=True)
        profile(user=jane, save=True)
        jane.groups.add(Group.objects.get(name='analyzers'))

        self.client_login_user(jane)

    def test_occurrence_report(self):
        url = reverse('analytics_occurrences_comparison')

        # No results when you initially look at the page
        resp = self.client.get(url)
        eq_(200, resp.status_code)
        assert 'id="results"' not in resp.content

        # 'product' is a required field
        resp = self.client.get(url, {'product': ''})
        eq_(200, resp.status_code)
        # FIXME - this test is too loose
        assert 'This field is required' in resp.content

        # At least a version, search term or start date is required
        resp = self.client.get(url, {'product': 'Firefox'})
        eq_(200, resp.status_code)
        assert 'This field is required' not in resp.content
        assert 'Must specify at least one' in resp.content

        # Minimal required for results
        resp = self.client.get(url, {
            'product': 'Firefox',
            'first_version': '17.0.0'}
        )
        eq_(200, resp.status_code)
        assert 'This field is required' not in resp.content
        assert 'Must speicfy at least one' not in resp.content
        assert 'id="results"' in resp.content

        # FIXME - when things are less prototypy, add tests for
        # specific results


class TestSpamDashboardView(ElasticTestCase):
    client_class = LocalizingClient

    def test_permissions(self):
        # Verifies that only analyzers can see the spam dashboard link
        resp = self.client.get(reverse('dashboard'))
        eq_(200, resp.status_code)
        assert 'sdashboard' not in resp.content

        # Verifies that only analyzers can see the spam dashboard
        resp = self.client.get(reverse('spam_dashboard'))
        eq_(403, resp.status_code)

        # Verify analyzers can see spam dashboard link
        jane = user(email='jane@example.com', save=True)
        profile(user=jane, save=True)
        jane.groups.add(Group.objects.get(name='analyzers'))

        self.client_login_user(jane)
        resp = self.client.get(reverse('dashboard'))
        eq_(200, resp.status_code)
        assert 'sdashboard' in resp.content

        # Verify analyzers can see spam dashboard
        resp = self.client.get(reverse('spam_dashboard'))
        eq_(200, resp.status_code)
