#!/usr/bin/env python

"""ION stream endpoints/registrars"""
from pyon.util import log

__author__ = 'Michael Meisinger, David Stuebe, Dave Foster <dfoster@asascience.com>'
__license__ = 'Apache 2.0'

from pyon.core.bootstrap import CFG, IonObject
from pyon.ion.endpoint import ProcessPublisher, ProcessSubscriber, PublisherError
from pyon.net.channel import PublisherChannel, SubscriberChannel, ChannelError
from pyon.util.async import  spawn
from interface.services.dm.ipubsub_management_service import PubsubManagementServiceProcessClient
from pyon.core import bootstrap
from pyon.util.log import log


class StreamPublisher(ProcessPublisher):
    """
    Data management abstraction of EndPoint layer for publishing messages to a stream
    """

    class NoDeclarePublisherChannel(PublisherChannel):

        """
        # Once EMS exists - remove the declare!
        def _declare_exchange(self, xp):
            log.debug("StreamPublisher passing on _declare_exchange: %s", xp)
        """
    channel_type = NoDeclarePublisherChannel

    '''
    def __init__(self, **kwargs):
        """
        @param stream_route is a stream_route object
        @param process is the publishing process
        @param node is cc.node
        """

        self._stream_route = stream_route


        ProcessPublisher.__init__(self, **kwargs)
    '''


class StreamPublisherRegistrar(object):
    """
    A Data Management level object for creating a publisher for a stream
    This object manages registration of publishers for different streams and creates the abstracted endpoint with the
    publish method
    """

    def __init__(self, process=None, node=None):
        """
        Use the process's exchange name to publish messages to a stream
        """
        self.process = process
        self.exchange_name = process.id
        self.node = node
        self.pubsub_client = PubsubManagementServiceProcessClient(process=process, node=node)

        xs_dot_xp = CFG.core_xps.science_data
        try:
            self.XS, xp_base = xs_dot_xp.split('.')
            self.XP = '.'.join([bootstrap.get_sys_name(), xp_base])
        except ValueError:
            raise PublisherError('Invalid CFG for core_xps.science_data: "%s"; must have "xs.xp" structure' % xs_dot_xp)


    def create_publisher(self, stream_id):
        """
        Call pubsub service to register this exchange name (endpoint) to publish on a particular stream
        Return a stream publisher object to publish (send) messages on a particular stream
        """
        log.debug('Creating publisher...')

        # Call the pubsub service to register the exchange name as a publisher for this stream
        stream_route = self.pubsub_client.register_producer(self.exchange_name, stream_id)

        # Create the Stream publisher, ready to publish messages to the stream
        return StreamPublisher(to_name=(self.XP, stream_route.routing_key), process=self.process, node=self.node)



class StreamSubscriber(ProcessSubscriber):
    """
    Data management abstraction of the subscriber endpoint
    """
    class NoBindSubscriberChannel(SubscriberChannel):

        def _bind(self, binding):
            log.debug("StreamSubscriber passing on _bind: %s", binding)

        """
        # Once EMS exists - remove the declare!
        def _declare_exchange(self, xp):
            log.debug("StreamSubscriber passing on _declare_exchange: %s", xp)
        """

    channel_type = NoBindSubscriberChannel


    def __init__(self, **kwargs):
        """
        @param name is a tuple (xp, exchange_name)
        @param callback is a call back function
        @param Process is the subscribing process
        @param node is cc.node
        """
        if not kwargs.get('callback', None):
            kwargs = kwargs.copy()
            kwargs['callback'] = self._callback

        self._routing_call = None

        ProcessSubscriber.__init__(self, **kwargs)

    @property
    def routing_call(self):
        return self._routing_call

    @routing_call.setter
    def routing_call(self, value):
        self._routing_call = value

    def _callback(self, m, h):
        """
        Built-in Subscriber callback to route a call into process context.
        """
        self._routing_call(self._process.call_process, {'packet':m})

    def start(self):
        """
        Start consuming from the queue
        """
        if self._chan is not None:
            try:
                self._chan.start_consume()
            except ChannelError:
                log.info('Subscriber is already started')

        else:
            self.gl = spawn(self.listen)


    def stop(self):
        """
        Stop consuming from the queue
        """

        if self._chan is not None:
            self._chan.stop_consume()
        else:

            raise SubscriberError('Can not stop the subscriber before it is started')

    def close(self):

        self.stop()
        if self._chan is not None:
            self._chan.close()

            # This does not work - it hangs - why?
            #if hasattr(self, 'gl'):
            #    self.gl.join()

class StreamSubscriberRegistrarError(StandardError):
    """
    Error class for the StreamSubscriberRegistrar
    """

class StreamSubscriberRegistrar(object):
    """
    Class to create and register subscriptions in the pubsub service, create a StreamSubscriber
    """

    def __init__(self, process=None, node=None):
        self.process = process
        self.node = node
        self._subscriber_cnt = 0

        xs_dot_xp = CFG.core_xps.science_data
        try:
            self.XS, xp_base = xs_dot_xp.split('.')
            self.XP = '.'.join([bootstrap.get_sys_name(), xp_base])

        except ValueError:
            raise PublisherError('Invalid CFG for core_xps.science_data: "%s"; must have "xs.xp" structure' % xs_dot_xp)


    def create_subscriber(self, exchange_name=None, callback=None):
        """
        This method creates a new subscriber, a new exchange_name if it does not already exist.
        """

        if not exchange_name:
            #@todo - remove this! it does not belong here!

            # if not create a new one based on the process id
            exchange_name =  '%s_subscriber_%d' % (self.process.id, self._subscriber_cnt)
            self._subscriber_cnt += 1

        return StreamSubscriber(from_name=(self.XP, exchange_name), process=self.process, callback=callback, node=self.node)


