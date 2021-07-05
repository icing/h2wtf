import argparse
import logging
import re
import sys
import traceback
from datetime import timedelta
from typing import Iterable, List

from httpd.log import HttpdLog, HttpdLogEntry
from httpd.h2.stream import H2StreamEvents, H2StreamEventsCollector

log = logging.getLogger(__name__)


class H2WorkerChange:

    def __init__(self, t: timedelta, change: int, e: HttpdLogEntry = None):
        self.timedelta = t
        self.change = change
        self.e = e


class H2WorkerStatistics:

    def __init__(self, collector: H2StreamEventsCollector):
        self.collector = collector
        self._changes = list()
        self.update()

    def clear(self):
        self._changes.clear()

    def update(self):
        self.clear()
        for s in self.collector.all_streams():
            started = s.event('started')
            ended = s.event('ended')
            if started:
                self._changes.append(H2WorkerChange(started.timedelta, +1, s.started))
            if ended:
                self._changes.append(H2WorkerChange(ended.timedelta, -1, s.ended))
        self._changes = sorted(self._changes, key=lambda c: c.timedelta)

    def in_use_at(self, t: timedelta):
        n = 0
        for c in [c for c in self._changes if c.timedelta <= t]:
            n += c.change
        return n


class H2SessionStatistics:

    def __init__(self):
        pass


class H2StreamLifetimeTable:

    def __init__(self, collector: H2StreamEventsCollector):
        self.collector = collector
        self.wstats = H2WorkerStatistics(collector=collector)

    def summary(self):
        streams = self.collector.get_streams()
        if len(streams):
            self.print_list(streams=streams, title=f"Streams (total={len(streams)})")
            return 0
        else:
            sys.stderr.write("no matching h2 streams found\n")
            return 1

    def print_list(self, streams: List[H2StreamEvents], title: str):
        print(title)
        print(f"{'id':16} {'created':<28} {'scheduled':^18} {'started':^18} "
              f"{'ended':^18} {'reset':^18} {'cleanup':^18} {'destroyed':^18}")
        for s in streams:
            print(f"{s.gid:16} {str(s.event('created').timestamp):24}"
                  f"{self.wstats.in_use_at(s.event('created').timedelta):>2}w "
                  f"{self.tdelta(s, s.event('scheduled')):>18} "
                  f"{self.tdelta(s, s.event('started')):>18} "
                  f"{self.tdelta(s, s.event('ended')):>18} "
                  f"{self.tdelta(s, s.event('reset')):>18} "
                  f"{self.tdelta(s, s.event('cleanup')):>18} "
                  f"{self.tdelta(s, s.event('destroyed')):>18} ")

    def tdelta(self, s: H2StreamEvents, e: HttpdLogEntry):
        if e is None:
            return '     --     '
        d = e.timedelta - s.event('created').timedelta
        return f"+{d.seconds:d}.{d.microseconds:06d} {self.wstats.in_use_at(e.timedelta):2}w"


class H2WTF:

    RE_STREAM_EVENTS = [
        re.compile(r'(AH\d+: )?(h2_mplx|h2_session|h2_stream|h2_task)\((?P<stream>\d+-\d+)(,\S+)?\).*'),
    ]

    @staticmethod
    def is_http2(entry: HttpdLogEntry):
        return entry.module == 'http2'

    @staticmethod
    def log_entry(e: HttpdLogEntry):
        print(f"[{str(e.timestamp):>15}] [pid:{e.pid} tid:{e.tid}] [{e.module:}:{e.level:}] [{e.source}] {e.message}")

    @classmethod
    def main(cls):
        # declare cmd line options/args
        parser = argparse.ArgumentParser(prog='h2wtf', description="""
            analyze h2 usage from apache httpd logs
            """)
        parser.add_argument("-f", "--frames", action='store_true', default=False,
                            help="show H2 frame related entries")
        parser.add_argument("-l", "--log", action='store_true', default=False,
                            help="show the relevant log entries, no summary")
        parser.add_argument("-S", "--streams", type=str,
                            help="only handle particular h2 streams")
        parser.add_argument("log_file", help="the httpd log file")
        args = parser.parse_args()

        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
        logging.getLogger('').addHandler(console)

        rv = 0
        try:
            httpd_log = HttpdLog(fpath=args.log_file)

            streams = None
            if args.streams:
                streams = args.streams.split(',')

            collector = H2StreamEventsCollector(
                with_frames=args.frames,
                for_streams=streams
            )

            for entry in httpd_log:
                if collector.observe(entry) and args.log:
                    cls.log_entry(entry)

            if not args.log:
                stats = H2StreamLifetimeTable(collector=collector)
                rv = stats.summary()

        except Exception as ex:
            log.error("unexpected exception: %s %s", ex, traceback.format_exc())
            rv = 1
        sys.exit(rv)


if __name__ == "__main__":
    H2WTF.main()
