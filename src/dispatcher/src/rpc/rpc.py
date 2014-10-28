__author__ = 'jceel'

import errno
import inspect
import logging

class RpcContext(object):
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.logger = logging.getLogger('RpcContext')
        self.services = {}
        self.instances = {}
        self.register_service('server', ManagementService)
        self.register_service('discovery', DiscoveryService)
        self.register_service('task', TaskService)
        self.register_service('event', EventService)

    def register_service(self, name, clazz):
        self.services[name] = clazz
        self.instances[name] = clazz()
        self.instances[name].initialize(self)

    def unregister_service(self, name):
        if not name in self.services.keys():
            return

        del self.instances[name]
        del self.services[name]

    def dispatch_call(self, method, args):
        service, sep, name = method.rpartition(".")
        self.logger.info('Call: service=%s, method=%s', service, method)

        if args is None:
            args = {}

        if not service:
            raise RpcException(errno.EINVAL, "Invalid function path")

        if service not in self.services.keys():
            raise RpcException(errno.ENOENT, "Service {0} not found".format(service))

        try:
            func = getattr(self.instances[service], name)
        except AttributeError:
            raise RpcException(errno.ENOENT, "Method not found")

        try:
            if type(args) is dict:
                return func(**args)
            elif type(args) is list:
                return func(*args)
            else:
                raise RpcException(errno.EINVAL, "Function parameters should be passed as dictionary or array")
        except TypeError:
            raise RpcException(errno.EINVAL, "Invalid function parameters")


class RpcService(object):
    def enumerate_methods(self):
        for i in inspect.getmembers(self, predicate=inspect.ismethod):
            method = i[0]

            if method.startswith('_'):
                continue

            if method in (
                "initialize",
                "enumerate_methods"):
                continue

            yield method


class RpcException(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return "{}: {}".format(errno.errorcode[self.code], self.message)


class DiscoveryService(RpcService):
    def __init__(self):
        self.__context = None

    def initialize(self, context):
        self.__context = context

    def get_services(self):
        return self.__context.services.keys()

    def get_tasks(self):
        return self.__context.dispatcher.tasks.keys()

    def get_methods(self, service):
        if not service in self.__context.services.keys():
            raise RpcException(errno.ENOENT, "Service not found")

        return list(self.__context.instances[service].enumerate_methods())


class ManagementService(RpcService):
    def initialize(self, context):
        self.__context = context

    def status(self):
        pass

    def reload_plugins(self):
        self.__context.dispatcher.discover_plugins()

    def restart(self):
        pass

    def get_connected_clients(self):
        return self.__context.dispatcher.ws_server.clients.keys()

    def die_you_gravy_sucking_pig_dog(self):
        self.__context.dispatcher.die()


class EventService(RpcService):
    def initialize(self, context):
        self.__datastore = context.dispatcher.datastore
        self.__dispatcher = context.dispatcher
        pass

    def query(self, mask, start=None, end=None, limit=None):
        where = []
        if start is not None:
            where.append(('timestamp', '>=', start))

        if end is not None:
            where.append(('timestamp', '<=', end))

        return list(self.__datastore.query('events', where, limit))


class TaskService(RpcService):
    def initialize(self, context):
        self.__datastore = context.dispatcher.datastore
        self.__balancer = context.dispatcher.balancer
        pass

    def submit(self, name, args):
        tid = self.__balancer.submit(name, args)
        return tid

    def status(self, id):
        t = self.__datastore.get_by_id('tasks', id)
        task = self.__balancer.get_task(id)

        if task:
            t['progress'] = task.progress.__getstate__()

        return t

    def abort(self, id):
        self.__balancer.abort(id)

    def list_queues(self):
        result = []
        for name, queue in self.__balancer.queues.items():
            result.append({
                "name": name,
                "type": queue.clazz,
                "status": queue.worker.state
            })

        return result

    def list_tasks(self, limit=None):
        result = []
        for t in self.__datastore.query('tasks', sort='created_at', dir='desc', limit=limit):
            result.append(t)

        return result

    def list_active(self):
        result = []
        for i in self.__balancer.get_active_tasks():
            result.append({
                "id": i.id,
                "type": i.name,
                "state": i.state
            })

        return result

    def list_failed(self):
        result = []
        from balancer import TaskState
        for i in self.__balancer.get_tasks(TaskState.FAILED):
            result.append({
                "id": i.id,
                "type": i.name,
                "state": i.state
            })

        return result