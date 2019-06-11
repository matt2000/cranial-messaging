from time import sleep

import requests

from cranial.messaging import base


class Notifier(base.Notifier):
    @staticmethod
    def send(address, message, endpoint, **kwargs):
        count = 0
        while count < 3:
            response = requests.get('http://{}/{}/{}'.format(
                address, endpoint, message.strip()))
            if response.status_code == requests.codes.ok:
                try:
                    return response.json()
                except ValueError:
                    return response.text
            count += 1
            sleep(5)

        return False
