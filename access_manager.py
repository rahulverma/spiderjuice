import base64
from random import randint
from PyQt5.QtCore import QUrl, QTimer, Qt
from collections import namedtuple
import re
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkProxyFactory, QNetworkProxy, QNetworkRequest, QSslConfiguration, QNetworkReply, QNetworkCookieJar
from settings import HTTP_HEADER_CHARSET

import logging
logger = logging.getLogger(__name__)


class ProxyManager(QNetworkProxyFactory):
    no_proxy = (QNetworkProxy(),)

    def __init__(self, access_manager):
        super().__init__()

        self.control = access_manager.control
        self.access_manager = access_manager

    def queryProxy(self, query=None, *args, **kwargs):
        if self.access_manager.proxy is not None:
            return (self.access_manager.proxy,)
        return ProxyManager.no_proxy


class CookieManager(QNetworkCookieJar):
    def clear_all_cookies(self):
        self.setAllCookies([])


class AccessManager(QNetworkAccessManager):
    Rule = namedtuple('Rule', ['rule_type', 'rule'])
    _allow = 'allow'
    _reject = 'reject'

    def __init__(self, parent):
        super().__init__(parent)

        self.control = parent.control
        self.rule_list = []
        self.proxy = None
        self.proxy_factory = ProxyManager(self)
        self.setProxyFactory(self.proxy_factory)
        self.proxyAuthenticationRequired.connect(self.proxy_authenticate)
        self.authenticationRequired.connect(self.authenticate)
        self.cookie_manager = CookieManager()
        self.setCookieJar(self.cookie_manager)
        self.clear_cookie_timer = QTimer(self)
        self.clear_cookie_timer.setTimerType(Qt.VeryCoarseTimer)
        # Clear cookies every hour
        self.clear_cookie_timer.setInterval(3600 * 1000)
        self.clear_cookie_timer.timeout.connect(self.clear_cookies)
        self.clear_cookies()

    def clear_cookies(self):
        logger.error(self.control.prepend_id('clearing cookies'))
        self.cookie_manager.clear_all_cookies()

    def authenticate(self, network_proxy, authenticator):
        logger.error(self.control.prepend_id('Proxy Authenticate {}'.format(network_proxy.url())))
        self.control.abort()

    def proxy_authenticate(self, network_proxy, authenticator):
        if self.proxy:
            authenticator.setUser(self.proxy.user())
            authenticator.setPassword(self.proxy.password())
        else:
            logger.error(self.control.prepend_id('Asked for proxy when no proxy is present: {}'.format(network_proxy.url())))

    def set_page_proxy(self, proxy_string, auth_string):
        if not proxy_string:
            return

        pr = proxy_string.split(':', 1)
        if len(pr) != 2:
            logger.error(self.control.prepend_id('Invalid proxy string {}, auth {}'.format(proxy_string, auth_string)))
            return
        host = pr[0]
        port = int(pr[1])

        if not (host and port):
            logger.error(self.control.prepend_id('Invalid proxy string {}, auth {}'.format(proxy_string, auth_string)))
            return

        if auth_string:
            aus = auth_string.split(':', 1)
            if len(aus) != 2:
                logger.error(self.control.prepend_id('Invalid proxy string {}, auth {}'.format(proxy_string, auth_string)))
                return
            user = aus[0]
            password = aus[1]

            self.proxy = QNetworkProxy(QNetworkProxy.HttpProxy, host, port, user, password)
        else:
            self.proxy = QNetworkProxy(QNetworkProxy.HttpProxy, host, port)

    def reset(self):
        self.rule_list = []
        self.proxy = None

    def request_finished(self, network_reply):
        if not self.control.job():
            return

        error = network_reply.error()
        url = network_reply.url()
        url_str = url.toString()
        retry_after_sec = 60
        if error != 0:
            if error == QNetworkReply.OperationCanceledError:
                logger.debug(self.control.prepend_id('Operation cancelled for url {}'.format(url_str)))
                return

            request = network_reply.request()

            request_headers_string = 'Request:\n'
            for header in request.rawHeaderList():
                request_headers_string += '{}: {}\n'.format(header.data().decode(encoding=HTTP_HEADER_CHARSET), request.rawHeader(header).data().decode(encoding=HTTP_HEADER_CHARSET))

            response_headers_string = 'Response:\n'
            for header in network_reply.rawHeaderList():
                header_key = header.data().decode(encoding=HTTP_HEADER_CHARSET)
                header_value = network_reply.rawHeader(header).data().decode(encoding=HTTP_HEADER_CHARSET)
                if 'Retry-After' == header and header_value.isdigit():
                    retry_after_sec = int(header_value)
                response_headers_string += '{}: {}\n'.format(header_key, header_value)

            logger.error(self.control.prepend_id('e_id="{eid};{estr}" url="{url}"\n{req_h}\n{res_h}'.format(eid=error,
                                                                                                            estr=network_reply.errorString(),
                                                                                                            url=url_str,
                                                                                                            req_h=request_headers_string,
                                                                                                            res_h=response_headers_string)))
            ###############################################
            # Throttle the retries as lazily as possible
            ###############################################

            # We go slightly above the recommended value, randomize it a bit and double check the values just in case
            if retry_after_sec < 1:
                retry_after_sec = 2

            if retry_after_sec < 100:
                retry_after_sec = (retry_after_sec * 10) + randint(0, 30)

            # Restrict the retry sec to 1 hour
            if retry_after_sec > 3600:
                retry_after_sec = 3600

            self.control.abort(retry_after_sec)

    def createRequest(self, operation, request, device=None):
        if not self.control.job():
            return super().createRequest(operation, request, device)

        url = request.url()
        url_str = url.toString()

        if self.rule_list:
            for r in self.rule_list:
                if r.rule.search(url_str):
                    if r.rule_type == self._reject:
                        logger.debug(self.control.prepend_id('Blocking {}'.format(url_str)))
                        return super().createRequest(operation, QNetworkRequest(QUrl()), device)
                    else:
                        break

        if self.proxy and self.control.job() and self.control.job().is_crawlera:
            scheme = url.scheme()
            if scheme == 'https':
                url.setScheme('http')
                request.setRawHeader(b'X-Crawlera-Use-HTTPS', b'1')
                # TODO Check if this is needed
                request.setSslConfiguration(QSslConfiguration())
                request.setUrl(url)
            elif scheme == 'http':
                pass
            else:
                # We fail any request that is not http or https
                logger.warning(self.control.prepend_id('Unsupported Schema {}'.format(url_str)))
                return super().createRequest(operation, QNetworkRequest(QUrl()), device)

            key = bytes('{}:{}'.format(self.proxy.user(), self.proxy.password()), HTTP_HEADER_CHARSET)
            proxy_auth_value = b'Basic ' + base64.urlsafe_b64encode(key)
            request.setRawHeader(b'Proxy-Authorization', proxy_auth_value)
            request.setRawHeader(b'Proxy-Connection', b'Keep-Alive')
            request.setRawHeader(b'X-Crawlera-Cookies', b'disable')
            request.setRawHeader(b'X-Crawlera-UA', b'desktop')

        network_reply = super().createRequest(operation, request, device)
        network_reply.finished.connect(lambda: self.request_finished(network_reply))
        return network_reply

    def set_filter(self, filter_str_list):
        for filter_str in filter_str_list:
            filter_conf = filter_str.split(':', 1)

            if len(filter_conf) != 2:
                logger.error(self.control.prepend_id('Invalid filter string {}'.format(filter_str)))
                return

            rule_type = filter_conf[0]
            if not (rule_type == self._allow or rule_type == self._reject):
                logger.error(self.control.prepend_id('Invalid filter string {}'.format(filter_str)))
                return

            rule_str = filter_conf[1]
            if not rule_str:
                logger.error(self.control.prepend_id('Invalid filter string {}'.format(filter_str)))
                return

            self.rule_list.append(self.Rule(rule_type, re.compile(rule_str)))