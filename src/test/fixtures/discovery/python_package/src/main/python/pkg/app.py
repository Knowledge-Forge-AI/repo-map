from pkg.lib import helper
import json
from . import missing


class Service:
    def run(self):
        return helper.VALUE


def build():
    return json.dumps({"value": Service().run()})
