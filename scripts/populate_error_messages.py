"""
Send error messages to the sentry sdk
"""

import sentry_sdk
import sys
import random
import faker

sys.path.append('.')

from server.utils import app
from server.utils.models import ProjectPart, Error

fake = faker.Faker()

def error_stack_1():
    error_stack_2()

def error_stack_2():
    a = 10
    b = 5
    c = a / b
    error_stack_3()

def error_stack_3():
    return 1 / 0
    raise Exception(fake.sentence(nb_words=6))


def main():
    for part in ProjectPart.select():
        dsn=f"http://secretkey@localhost:5000/ingest/{part.id}"
        print(dsn)

        sentry_sdk.init(dsn)
        
        for _ in range(random.randint(5, 20)):
            try:
                error_stack_1()
            except:
                sentry_sdk.capture_exception()



if __name__ == '__main__':
    main()



