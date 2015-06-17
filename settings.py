import os

BASE_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'detailed': {
            'class': 'logging.Formatter',
            'format': '%(asctime)s %(name)-15s %(levelname)-8s %(processName)-10s %(message)s'
        },
        'simple': {
            'class': 'logging.Formatter',
            'format': '%(name)-15s %(levelname)-8s %(processName)-10s %(message)s'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'INFO',
            'formatter': 'detailed',
        },
    },
    'root': {
        'level': 'DEBUG',
        'handlers': ['console']
    },
}

# Technically this should only be the default and we should use the encoding specified in the http header
HTTP_HEADER_CHARSET = 'ISO-8859-8'
DEFAULT_JOB_TIMEOUT_SECONDS = 300