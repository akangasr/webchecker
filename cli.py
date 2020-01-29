import os
import re
import sys
import json
import time
import click
import threading
import datetime
import requests
from flask import Flask
from collections import defaultdict


@click.command()
@click.option('--configfile', default='./pages.json',
              help='File with pages to be checked.')
@click.option('--delay', default=-1, type=int,
              help='Repeat check periodically with delay of X seconds '
                   'between runs. Negative value indicates no repeat.')
@click.option('--logfile', default='./log.json',
              help='Output log file.')
@click.option('--verbose', is_flag=True,
              help='Verbose output.')
@click.option('--html', is_flag=True,
              help='Serve a status page on localhost:5000')
def run_check(configfile, delay, logfile, verbose, html):
    """Checks each web site in config for availability and content."""
    pages = load_config(configfile)
    log = Log(logfile, verbose)
    if html:
        thread = threading.Thread(target=run_flask_app, args=(logfile, ))
        thread.daemon = True
        thread.start()
    while True:
        if verbose:
            print("Starting check..")
        for page, config in pages.items():
            check_page(page, config, log)
            log.save()
        if delay < 0:
            break
        else:
            time.sleep(delay)
    if verbose:
        print("Finished")


def run_flask_app(logfile):
    print("Flask app starting")
    app = Flask(__name__)
    app.use_reloader = False

    @app.route('/')
    def status_page():
        log = Log(logfile, False)
        ret = []
        for page in log.get_pages():
            ret.append(f"<p>{page}</p><ul>")
            for event in reversed(log.get_events(page)[-10:]):
                ts = datetime.datetime.fromtimestamp(event['timestamp'])
                if event['type'] == 'response_failed':
                    ret.append(f"<li>{ts} Response failed</li>")
                elif event['type'] == 'response_received':
                    duration = event['duration']
                    ret.append(f"<li>{ts} Response received in "
                               f"{duration:.2f} s</li>")
                elif event['type'] == 'requirement_passed':
                    requirement = event['requirement']
                    ret.append(f"<li>{ts} Requirement {requirement} "
                               f"passed</li>")
                elif event['type'] == 'requirement_failed':
                    requirement = event['requirement']
                    ret.append(f"<li>{ts} Requirement {requirement} "
                               f"failed</li>")
            ret.append("</ul>")
        return "".join(ret)

    app.run()


def check_page(page, config, log):
    requirement_checkers = get_requirement_checkers()
    t_start = time.time()
    try:
        result = requests.get(config['url'])
    except Exception as e:
        log.add_event(page, {
            'type': 'response_failed',
            'error': str(e)
            })
        return
    duration = time.time() - t_start
    log.add_event(page, {
        'type': 'response_received',
        'duration': duration
        })
    text = result.text
    for requirement in config['requirements']:
        requirement_name = requirement[0]
        requirement_params = requirement[1:]
        matcher = requirement_checkers[requirement_name]
        is_valid = matcher(text, *requirement_params)
        if is_valid:
            log.add_event(page, {
                'type': 'requirement_passed',
                'requirement': requirement
                })
        else:
            log.add_event(page, {
                'type': 'requirement_failed',
                'requirement': requirement
                })


class Log:
    def __init__(self, logfile, verbose):
        self.logfile = logfile
        self.verbose = verbose
        self._log = defaultdict(list)
        if not os.path.exists(self.logfile):
            if self.verbose:
                print(f"Log file {self.logfile} does not exist, creating")
            self.save()
        else:
            if self.verbose:
                print(f"Checking log file {self.logfile}")
            with open(self.logfile, 'r') as f:
                self._log.update(json.load(f))

    def add_event(self, page, event):
        event['timestamp'] = time.time()
        self._log[page].append(event)
        if self.verbose:
            print(event)

    def get_pages(self):
        return self._log.keys()

    def get_events(self, page):
        return self._log[page]

    def save(self):
        with open(self.logfile, 'w') as f:
            json.dump(self._log, f)


def load_config(configfile):
    if not os.path.exists(configfile):
        print(f"Config file {configfile} not found.")
        sys.abort(-1)
    else:
        with open(configfile, 'r') as f:
            config = json.load(f)
        return config


def get_requirement_checkers():
    return {
        'content_includes': content_includes_checker,
        'content_does_not_include': content_does_not_include_checker,
    }


def content_includes_checker(content, *terms):
    for term in terms:
        if not re.search(term, content):
            print(content)
            return False
    return True


def content_does_not_include_checker(content, *terms):
    for term in terms:
        if re.search(term, content):
            return False
    return True


if __name__ == '__main__':
    run_check()
