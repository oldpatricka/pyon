#!/usr/bin/env python
from pyon.datastore.datastore import DatastoreManager

__author__ = 'Dave Foster <dfoster@asascience.com>, Michael Meisinger'
__license__ = 'Apache 2.0'

import time

from mock import Mock, sentinel, patch
from nose.plugins.attrib import attr
from gevent import event, queue
from unittest import SkipTest

from pyon.core import bootstrap
from pyon.event.event import EventPublisher, EventSubscriber, EventRepository
from pyon.util.async import spawn
from pyon.util.log import log
from pyon.util.containers import get_ion_ts, DotDict
from pyon.util.int_test import IonIntegrationTestCase
from pyon.util.unit_test import IonUnitTestCase

from interface.objects import Event, ResourceLifecycleEvent


@attr('INT',group='event')
class TestEvents(IonIntegrationTestCase):

    def setUp(self):
        self._listens = []
        self._start_container()

    def tearDown(self):
        for x in self._listens:
            x.kill()

    def _listen(self, sub):
        """
        Pass in a subscriber here, this will make it listen in a background greenlet.
        """
        gl = spawn(sub.listen)
        self._listens.append(gl)
        sub._ready_event.wait(timeout=5)

        return gl

    def test_pub_and_sub(self):
        ar = event.AsyncResult()
        def cb(*args, **kwargs):
            ar.set(args)
        sub = EventSubscriber(event_type="ResourceEvent", callback=cb, origin="specific")
        pub = EventPublisher(event_type="ResourceEvent")

        self._listen(sub)
        pub.publish_event(origin="specific", description="hello")

        evmsg, evheaders = ar.get(timeout=5)

        self.assertEquals(evmsg.description, "hello")
        self.assertAlmostEquals(int(evmsg.ts_created), int(get_ion_ts()), delta=5000)

    def test_pub_with_event_repo(self):
        pub = EventPublisher(event_type="ResourceEvent", node=self.container.node)
        pub.publish_event(origin="specifics", description="hallo")

        evs = self.container.event_repository.find_events(origin='specifics')
        self.assertEquals(len(evs), 1)

    def test_pub_on_different_origins(self):
        ar = event.AsyncResult()
        gq = queue.Queue()
        self.count = 0

        def cb(*args, **kwargs):
            self.count += 1
            gq.put(args[0])
            if self.count == 3:
                ar.set()

        sub = EventSubscriber(event_type="ResourceEvent", callback=cb)
        pub = EventPublisher(event_type="ResourceEvent")

        self._listen(sub)

        pub.publish_event(origin="one", description="1")
        pub.publish_event(origin="two", description="2")
        pub.publish_event(origin="three", description="3")

        ar.get(timeout=5)

        res = []
        for x in xrange(self.count):
            res.append(gq.get(timeout=5))

        self.assertEquals(len(res), 3)
        self.assertEquals(res[0].description, "1")
        self.assertEquals(res[1].description, "2")
        self.assertEquals(res[2].description, "3")

    def test_pub_on_different_subtypes(self):
        ar = event.AsyncResult()
        gq = queue.Queue()
        self.count = 0

        def cb(event, *args, **kwargs):
            self.count += 1
            gq.put(event)
            if event.description == "end":
                ar.set()

        sub = EventSubscriber(event_type="ResourceModifiedEvent", sub_type="st1", callback=cb)
        sub.activate()

        pub1 = EventPublisher(event_type="ResourceModifiedEvent")
        pub2 = EventPublisher(event_type="ContainerLifecycleEvent")

        pub1.publish_event(origin="two", sub_type="st2", description="2")
        pub2.publish_event(origin="three", sub_type="st1", description="3")
        pub1.publish_event(origin="one", sub_type="st1", description="1")
        pub1.publish_event(origin="four", sub_type="st1", description="end")

        ar.get(timeout=5)
        sub.deactivate()

        res = []
        for x in xrange(self.count):
            res.append(gq.get(timeout=5))

        self.assertEquals(len(res), 2)
        self.assertEquals(res[0].description, "1")

    def test_pub_on_different_subsubtypes(self):
        res_list = [DotDict(ar=event.AsyncResult(), gq=queue.Queue(), count=0) for i in xrange(4)]

        def cb_gen(num):
            def cb(event, *args, **kwargs):
                res_list[num].count += 1
                res_list[num].gq.put(event)
                if event.description == "end":
                    res_list[num].ar.set()
            return cb

        sub0 = EventSubscriber(event_type="ResourceModifiedEvent", sub_type="st1.*", callback=cb_gen(0))
        sub0.activate()

        sub1 = EventSubscriber(event_type="ResourceModifiedEvent", sub_type="st1.a", callback=cb_gen(1))
        sub1.activate()

        sub2 = EventSubscriber(event_type="ResourceModifiedEvent", sub_type="*.a", callback=cb_gen(2))
        sub2.activate()

        sub3 = EventSubscriber(event_type="ResourceModifiedEvent", sub_type="st1", callback=cb_gen(3))
        sub3.activate()

        pub1 = EventPublisher(event_type="ResourceModifiedEvent")

        pub1.publish_event(origin="one", sub_type="st1.a", description="1")
        pub1.publish_event(origin="two", sub_type="st1", description="2")
        pub1.publish_event(origin="three", sub_type="st1.b", description="3")

        pub1.publish_event(origin="four", sub_type="st2.a", description="4")
        pub1.publish_event(origin="five", sub_type="st2", description="5")

        pub1.publish_event(origin="six", sub_type="a", description="6")
        pub1.publish_event(origin="seven", sub_type="", description="7")

        pub1.publish_event(origin="end", sub_type="st1.a", description="end")
        pub1.publish_event(origin="end", sub_type="st1", description="end")

        [res_list[i].ar.get(timeout=5) for i in xrange(3)]

        sub0.deactivate()
        sub1.deactivate()
        sub2.deactivate()
        sub3.deactivate()

        for i in xrange(4):
            res_list[i].res = []
            for x in xrange(res_list[i].count):
                res_list[i].res.append(res_list[i].gq.get(timeout=5))

        self.assertEquals(len(res_list[0].res), 3)
        self.assertEquals(res_list[0].res[0].description, "1")

        self.assertEquals(len(res_list[1].res), 2)
        self.assertEquals(res_list[1].res[0].description, "1")

        self.assertEquals(len(res_list[2].res), 3)
        self.assertEquals(res_list[2].res[0].description, "1")

        self.assertEquals(len(res_list[3].res), 2)
        self.assertEquals(res_list[3].res[0].description, "2")


    def test_base_subscriber_as_catchall(self):
        ar = event.AsyncResult()
        gq = queue.Queue()
        self.count = 0

        def cb(*args, **kwargs):
            self.count += 1
            gq.put(args[0])
            if self.count == 2:
                ar.set()

        sub = EventSubscriber(callback=cb)
        pub1 = EventPublisher(event_type="ResourceEvent")
        pub2 = EventPublisher(event_type="ContainerLifecycleEvent")

        self._listen(sub)

        pub1.publish_event(origin="some", description="1")
        pub2.publish_event(origin="other", description="2")

        ar.get(timeout=5)

        res = []
        for x in xrange(self.count):
            res.append(gq.get(timeout=5))

        self.assertEquals(len(res), 2)
        self.assertEquals(res[0].description, "1")
        self.assertEquals(res[1].description, "2")

    def test_subscriber_listening_for_specific_origin(self):
        ar = event.AsyncResult()
        self.count = 0
        def cb(*args, **kwargs):
            self.count += 1
            ar.set(args[0])

        sub = EventSubscriber(event_type="ResourceEvent", origin="specific", callback=cb)
        pub = EventPublisher(event_type="ResourceEvent", node=self.container.node)

        self._listen(sub)

        pub.publish_event(origin="notspecific", description="1")
        pub.publish_event(origin="notspecific", description="2")
        pub.publish_event(origin="specific", description="3")
        pub.publish_event(origin="notspecific", description="4")

        evmsg = ar.get(timeout=5)
        self.assertEquals(self.count, 1)
        self.assertEquals(evmsg.description, "3")

@attr('UNIT',group='datastore')
class TestEventRepository(IonUnitTestCase):
    def test_event_repo(self):
        dsm = DatastoreManager()

        event_repo = EventRepository(dsm)
        event_repo1 = EventRepository(dsm)

        event1 = Event(origin="resource1")
        event_id, _ = event_repo.put_event(event1)

        event1r = event_repo.get_event(event_id)
        self.assertEquals(event1.origin, event1r.origin)

        ts = 1328680477138
        events2 = []
        for i in xrange(5):
            ev = Event(origin="resource2", ts_created=str(ts + i))
            event_id, _ = event_repo.put_event(ev)
            events2.append((ev,event_id))

        events_r = event_repo.find_events(origin='resource2')
        self.assertEquals(len(events_r), 5)

        events_r = event_repo.find_events(origin='resource2', descending=True)
        self.assertEquals(len(events_r), 5)

        events_r = event_repo.find_events(origin='resource2', limit=3)
        self.assertEquals(len(events_r), 3)

        events_r = event_repo.find_events(origin='resource2', start_ts=str(ts+3))
        self.assertEquals(len(events_r), 2)

        events_r = event_repo.find_events(origin='resource2', end_ts=str(ts+2))
        self.assertEquals(len(events_r), 3)

        events_r = event_repo.find_events(origin='resource2', start_ts=str(ts+3), end_ts=str(ts+4))
        self.assertEquals(len(events_r), 2)

        events_r = event_repo.find_events(start_ts=str(ts+3), end_ts=str(ts+4))
        self.assertEquals(len(events_r), 2)


        event3 = ResourceLifecycleEvent(origin="resource3")
        event_id, _ = event_repo.put_event(event3)

        events_r = event_repo.find_events(event_type="ResourceLifecycleEvent")
        self.assertEquals(len(events_r), 1)
