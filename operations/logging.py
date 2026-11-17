import logging
import re

class RedactQueryFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        record.msg = re.sub(r'([A-Z]+ [^\s?]+)\?[^\s]*', r'\1?[redacted]', message)
        record.args = ()
        return True
