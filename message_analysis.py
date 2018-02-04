import re
import csv
import sys
import time
import locale
import hashlib
import logging
import argparse
import datetime
import calendar
import fileinput
from dateutil import parser
from os import path, makedirs
from collections import namedtuple, OrderedDict, Counter

# Thirt party libraries.
import pytz
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt
import numpy as np

# Setup logging, just for stdout fpr now.
LOG = logging.getLogger('MessageAnalyser')
LOG.setLevel(logging.DEBUG)
stdout_handler = logging.StreamHandler()
stdout_handler.setFormatter(
        logging.Formatter('%(asctime)-15s [%(levelname)s] %(message)s'))
LOG.addHandler(stdout_handler)

Message = namedtuple('Message', ['user', 'message', 'created'])

### DATE PARSING HACKS

# Terrible, terrible hack to get the correct timezone.
# Might be a way of getting around this without doing it this way, and
# removing the pytz dependency as this is not doing a lot at the moment.
tz = {
    'UTC+01': pytz.timezone('Europe/Stockholm'),
    'UTC': pytz.utc,
}

def parse_datetime(dt_str):
    parts = dt_str.split(' ')
    h, m = map(int, parts[5].split(':'))
    return datetime.datetime(
            int(parts[3]),
            list(calendar.month_name).index(parts[2].capitalize()),
            int(parts[1]),
            h, m,
            tzinfo=tz[parts[6]])

### END OF TERRIBLE DATE HACKS

def parse_message_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    user = soup.find_all(class_='user')[0].text
    message = soup.find_all('p')[0].text
    return Message(user, message,
            parse_datetime(soup.find_all(class_='meta')[0].text))

def parse_message_from_csv(csv):
    return (Message(
        line[0].decode('utf-8'),
        line[1].decode('utf-8'),
        parser.parse(line[2])) for line in csv)

if __name__ == '__main__':
    argparser = argparse.ArgumentParser()
    argparser.add_argument('--filename',
                        dest='filename',
                        required=True,
                        metavar="file name",
                        help="HTML file containing conversation.")
    argparser.add_argument('--src-locale',
                           dest='source_locale',
                           metavar='locale',
                           default="en_US")
    argparser.add_argument('--dst-locale',
                           dest='dest_locale',
                           metavar='locale',
                           default="en_US")

    args = argparser.parse_args()
    file_path = args.filename

    LOG.info('Starting up...')
    with open(file_path, 'rb') as html:
        hash_sum = hashlib.md5(html.read()).hexdigest()
    LOG.debug("Determined hash sum of file to be %s", hash_sum)

    # Set locale for source HTML file
    locale.setlocale(locale.LC_ALL, args.source_locale)

    file_dir = path.dirname(path.realpath(__file__))
    _id = path.splitext(path.basename(file_path))[0]
    cache_dir = path.join(file_dir, 'cache')

    # Create cache dir if it does not exist.
    if not path.exists(cache_dir):
        LOG.info("Cache directory does not exist, creating.")
        makedirs(cache_dir)

    cache_file = path.join(cache_dir, "{}_{}.csv".format(_id, hash_sum))
    if not path.isfile(cache_file):
        LOG.info("Building cache")
        start = time.time()
        _input = fileinput.input(file_path)

        # Most existing HTML parsers are keeping the entire tree in memory. As
        # chat histories tend to become quite long, it is undesireable in this
        # case. Here, we instead use a regular expression to fetch bite-sized
        # chunks iteratively, without keeping the entire HTMl contents in memory
        # at once.
        pattern = re.compile(r'<div class="message">.*?</p>')
        with open(cache_file, 'wb') as csvfile:
            csvwriter = csv.writer(csvfile, delimiter=',',
                            quotechar='"', quoting=csv.QUOTE_MINIMAL)

            for msg in re.finditer(pattern, '\n'.join(_input)):
                message = parse_message_from_html(msg.group())
                csvwriter.writerow([
                    message.user.encode('utf8'),
                    message.message.encode('utf8'),
                    message.created.isoformat()])
        LOG.info("Built cache in %s", time.time() - start)
    else:
        LOG.debug("Found cached CSV file")

    # Set locale for source HTML file
    locale.setlocale(locale.LC_ALL, args.dest_locale)

    User = namedtuple('User', ['weekdays', 'months', 'hours'])
    users = dict()
    LOG.info("Starting analysis...")
    start = time.time()
    with open(cache_file) as csvfile:
        csvreader = csv.reader(csvfile, delimiter=',', quotechar='"')
        for message in parse_message_from_csv(csvreader):
            user = users.setdefault(message.user, User([], [], []))
            user.weekdays.append(message.created.weekday())
            user.months.append(message.created.month)
            user.hours.append(message.created.hour)

    LOG.info("Finished in %s", time.time() - start)

    # Order users after amount of sent messages. Since all bins are added
    # to with each message found, it does not matter which one we choose.
    users = OrderedDict(sorted(users.items(), key=lambda u: len(u[1].hours)))
    labels = [u"{} [{} messages]".format(n, len(u.hours))
                for n, u in users.items()]

    fig = plt.figure()

    ax1 = fig.add_subplot(221)
    ax1.hist([np.array(u.weekdays) for u in users.values()],
             label=labels, stacked=True, bins=np.arange(0, 8)-0.5)
    ax1.set_xticks(map(lambda x: x, range(0, 8)))
    ax1.set_xticklabels(list(calendar.day_abbr),rotation=45)
    fig.legend()

    ax2 = fig.add_subplot(223)
    ax2.hist([np.array(u.months) for u in users.values()],
             label=labels, stacked=True, bins=np.arange(1, 14)-0.5)
    ax2.set_xticks(map(lambda x: x, range(0, 13)))
    ax2.set_xticklabels(list(calendar.month_abbr),rotation=45)

    ax3 = fig.add_subplot(224)
    ax3.hist([np.array(u.hours) for u in users.values()],
             label=labels, stacked=True, bins=np.arange(0, 25)-0.5)
    ax3.set_xticks(map(lambda x: x, range(0, 24)))
    ax3.set_xticklabels(["{:02d}:00".format(d) for d in range(24)],rotation=45)
    plt.show()
