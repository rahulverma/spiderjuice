# -*- coding: utf-8 -*-
import glob
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt5.QtWebKit import QWebSettings, QWebElement
from access_manager import AccessManager

from PyQt5.QtCore import QSize, QObject, pyqtSlot, pyqtProperty, QUrl, pyqtSignal, QVariant, Qt, QTimer
from PyQt5.QtWebKitWidgets import QWebPage

import logging
from job import Job
from settings import BASE_PROJECT_DIR, DEFAULT_JOB_TIMEOUT_SECONDS, HTTP_HEADER_CHARSET, MAX_RETRIES

logger = logging.getLogger(__name__)


class JSControllerObject(QObject):
    http_request_finished = pyqtSignal(int, int, str)

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.network_manager = QNetworkAccessManager()

    def http_response(self, callback_id, reply):
        if not self.job():
            return

        if reply.error() == 0:
            data_str = reply.readAll().data().decode(encoding='UTF-8')
            self.http_request_finished.emit(callback_id, reply.error(), data_str)
        else:
            self.http_request_finished.emit(callback_id, reply.error(), '')
        reply.deleteLater()

    def post_finished(self, network_reply):
        error = network_reply.error()
        url = network_reply.url()
        url_str = url.toString()
        if error != 0:
            request = network_reply.request()

            request_headers_string = 'Request:\n'
            for header in request.rawHeaderList():
                request_headers_string += '{}: {}\n'.format(header.data().decode(encoding=HTTP_HEADER_CHARSET), request.rawHeader(header).data().decode(encoding=HTTP_HEADER_CHARSET))

            response_headers_string = 'Response:\n'
            for header in network_reply.rawHeaderList():
                response_headers_string += '{}: {}\n'.format(header.data().decode(encoding=HTTP_HEADER_CHARSET), network_reply.rawHeader(header).data().decode(encoding=HTTP_HEADER_CHARSET))

            logger.error(self.prepend_id('e_id="{eid};{estr}" url="{url}"\n{req_h}\n{res_h}'.format(eid=error,
                                                                                                    estr=network_reply.errorString(),
                                                                                                    url=url_str,
                                                                                                    req_h=request_headers_string,
                                                                                                    res_h=response_headers_string)))
        else:
            logger.info('Post successful {}'.format(url_str))

    @pyqtSlot(str, str)
    def post_request(self, url, data):
        if not self.job():
            logger.error(self.prepend_id('Invalid State. post_request called when no current job'))
            return

        logger.info(self.prepend_id("Posting {} request to {}".format(self.job(), url)))
        req = QNetworkRequest(QUrl(url))
        req.setHeader(QNetworkRequest.ContentTypeHeader, 'application/json')
        network_reply = self.network_manager.post(req, data.encode('UTF-8'))
        network_reply.finished.connect(lambda: self.post_finished(network_reply))

    @pyqtSlot(QVariant)
    def log_message(self, message):
        logger.info(self.prepend_id('js: {}'.format(message)))

    @pyqtSlot(QVariant)
    def log_error(self, message):
        logger.error(self.prepend_id('js: {}'.format(message)))

    @pyqtProperty(QVariant)
    def job_dict(self):
        return self.parent.current_job.dict()

    def job(self):
        return self.parent.current_job

    @pyqtSlot(int, str)
    def http_request(self, callback_id, url):
        if not self.parent.current_job:
            logger.error(self.prepend_id('Invalid State. http_request called when no current job'))
            return

        qnetwork_reply = self.network_manager.get(QNetworkRequest(QUrl(url)))
        qnetwork_reply.finished.connect(lambda: self.http_response(callback_id, qnetwork_reply))

    @pyqtProperty(str)
    def current_state(self):
        if self.parent.current_job.state:
            return self.parent.current_job.state
        else:
            return 'main'

    @pyqtSlot()
    def done(self):
        if not self.parent.current_job:
            logger.error(self.prepend_id('Invalid State. done called when no current job'))
            return

        logger.info(self.prepend_id('Done Job {}'.format(self.job())))

        self.parent.reset()
        self.parent.job_finished.emit()

    @pyqtSlot()
    def abort(self, retry_after_sec=60):
        if not self.parent.current_job:
            logger.error(self.prepend_id('Invalid State. abort called when no current job'))
            return

        logger.error(self.prepend_id('Job aborting {}'.format(self.job())))
        retry_job = self.job().get_retry_job()
        if retry_job.retry <= MAX_RETRIES:
            logger.info(self.prepend_id('Retrying :{} after {}sec'.format(retry_job, retry_after_sec)))
            QTimer.singleShot(retry_after_sec * 1000, Qt.VeryCoarseTimer, lambda: self.parent.new_job_received.emit(retry_job))
        else:
            logger.error(self.prepend_id('Max Retries reached:{}'.format(retry_job)))

        self.parent.reset()
        self.parent.job_finished.emit()

    def prepend_id(self, message):
        return '[{}] {}'.format(self.parent.id, message)

    @pyqtSlot(QVariant)
    def load(self, job_dict):
        if not self.parent.current_job:
            logger.error(self.prepend_id('Invalid State. load called when no current job'))
            return

        self.parent.new_job_received.emit(self.parent.current_job.new_state(**job_dict))


class WebPageCustom(QWebPage):
    job_finished = pyqtSignal()
    new_job_received = pyqtSignal(Job)
    controller_js_file = 'controller.js'
    cache_directory_name = 'cache'
    js_lib_string_list = None
    global_settings_set = False
    id_gen = 0

    @staticmethod
    def setup_global_settings():
        if not WebPageCustom.global_settings_set:
            settings = QWebSettings.globalSettings()
            settings.enablePersistentStorage('{base}/{cache}'.format(base=BASE_PROJECT_DIR, cache=WebPageCustom.cache_directory_name))
            settings.setMaximumPagesInCache(0)
            settings.setAttribute(QWebSettings.DnsPrefetchEnabled, False)
            settings.setAttribute(QWebSettings.JavascriptEnabled, True)
            settings.setAttribute(QWebSettings.JavaEnabled, False)
            settings.setAttribute(QWebSettings.PluginsEnabled, False)
            settings.setAttribute(QWebSettings.JavascriptCanOpenWindows, False)
            settings.setAttribute(QWebSettings.JavascriptCanCloseWindows, False)
            settings.setAttribute(QWebSettings.JavascriptCanAccessClipboard, False)
            settings.setAttribute(QWebSettings.DeveloperExtrasEnabled, False)
            settings.setAttribute(QWebSettings.SpatialNavigationEnabled, False)
            settings.setAttribute(QWebSettings.OfflineStorageDatabaseEnabled, True)
            settings.setAttribute(QWebSettings.OfflineWebApplicationCacheEnabled, True)
            settings.setAttribute(QWebSettings.LocalStorageEnabled, True)
            settings.setAttribute(QWebSettings.AcceleratedCompositingEnabled, False)
            settings.setAttribute(QWebSettings.NotificationsEnabled, False)
            WebPageCustom.global_settings_set = True

    def userAgentForUrl(self, qurl):
        return 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 Safari/537.36'

    @staticmethod
    def get_js_lib_string():
        if WebPageCustom.js_lib_string_list is None:
            WebPageCustom.js_lib_string_list = []
            with open("{base}/{ctrl}".format(base=BASE_PROJECT_DIR, ctrl=WebPageCustom.controller_js_file)) as ctrl_lib:
                WebPageCustom.js_lib_string_list.append(ctrl_lib.read())
            for file in glob.glob("{base}/js_libs/*.js".format(base=BASE_PROJECT_DIR)):
                with open(file, encoding='utf-8', mode='r') as js_lib:
                    WebPageCustom.js_lib_string_list.append(js_lib.read())
        return WebPageCustom.js_lib_string_list

    def __init__(self, parent, size=QSize(1366, 768)):
        QWebPage.__init__(self, parent)
        WebPageCustom.id_gen += 1
        self.id = WebPageCustom.id_gen
        self.setup_global_settings()
        self.current_job = None
        self.injected = False
        self.setViewportSize(size)
        self.control = JSControllerObject(self)

        self.mainFrame().javaScriptWindowObjectCleared.connect(lambda: logger.debug(self.control.prepend_id('javaScriptWindowObjectCleared')))

        self.timeout_timer = QTimer(self)
        self.timeout_timer.setTimerType(Qt.VeryCoarseTimer)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.setInterval(DEFAULT_JOB_TIMEOUT_SECONDS * 1000)
        self.timeout_timer.timeout.connect(self.timeout)

        self.loadFinished.connect(self.on_load_finished)
        self.access_manager = AccessManager(self)
        self.setNetworkAccessManager(self.access_manager)

    def is_busy(self):
        return bool(self.current_job)

    def javaScriptConsoleMessage(self, message, line_number, source_id):
        logger.info(self.control.prepend_id('console:{}:{}:{}'.format(source_id, line_number, message)))

    def timeout(self):
        logger.error(self.control.prepend_id('Job timed out in {}sec - {}'.format(self.current_job.timeout or DEFAULT_JOB_TIMEOUT_SECONDS, self.current_job)))
        self.control.abort(retry_after_sec=10)

    def reset(self):
        self.current_job = None
        self.injected = False
        self.timeout_timer.stop()
        self.timeout_timer.setInterval(DEFAULT_JOB_TIMEOUT_SECONDS * 1000)
        self.access_manager.reset()
        self.mainFrame().setUrl(QUrl('file://' + BASE_PROJECT_DIR + '/blank.html'))
        self.settings().resetAttribute(QWebSettings.AutoLoadImages)

    def inject_job(self):
        if not self.current_job:
            return

        if self.injected:
            return

        self.injected = True

        logger.debug(self.control.prepend_id('Injecting Scripts'))
        self.mainFrame().addToJavaScriptWindowObject("SjCtrl", self.control)

        for js_lib in self.get_js_lib_string():
            self.mainFrame().evaluateJavaScript(js_lib)

        with open(self.current_job.file, 'r') as job_file:
            self.mainFrame().evaluateJavaScript(job_file.read())

    @pyqtSlot(bool)
    def on_load_finished(self, ok):
        if not self.current_job:
            return

        if not ok:
            logger.warning(self.control.prepend_id('The load was unsuccessful. Not Injecting: {}'.format(self.current_job)))
            return

        self.inject_job()

    def load_job(self, job):
        logger.info(self.control.prepend_id('Job Request {}'.format(job)))
        if not job.file:
            logger.error(self.control.prepend_id('No Job file specified {}'.format(job)))
        if job.timeout:
            self.timeout_timer.setInterval(job.timeout * 1000)

        self.timeout_timer.start()

        self.current_job = job

        if self.current_job.filter_list:
            self.access_manager.set_filter(self.current_job.filter_list)

        if self.current_job.block_images:
            self.settings().setAttribute(QWebSettings.AutoLoadImages, False)

        self.access_manager.set_page_proxy(self.current_job.proxy, self.current_job.proxy_auth)

        if self.current_job.url:
            qurl = QUrl(self.current_job.url)
            if not qurl.isValid():
                logger.error(self.control.prepend_id('Invalid URL {}'.format(self.current_job.url)))
                self.reset()
                self.job_finished.emit()
                return

            self.mainFrame().setUrl(qurl)
        else:
            self.inject_job()
