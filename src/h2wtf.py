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

    def has_data(self):
        return len(self._changes) > 0

    def update(self):
        self.clear()
        for s in self.collector.all_streams():
            if s.stream_id == 0:
                continue
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
              f"{'response':^18} {'ended':^18} {'reset':^18} {'cleanup':^18} "
              f"{'error':>7} {'cclose':>12}")
        for s in streams:
            print(f"{s.gid:16} "
                  f"{self.tabs(s, 'created')}"
                  f"{self.stdelta(s, s.event('scheduled')):>18} "
                  f"{self.stdelta(s, s.event('started'), with_wstats=True):>18} "
                  f"{self._resp(s, s.event('response')):>18} "
                  f"{self.stdelta(s, s.event('ended'), with_wstats=True):>18} "
                  f"{self.stdelta(s, s.event('reset')):>18} "
                  f"{self.tdelta(s, s.event('cleanup')):>18} "
                  f"{self._error(s, s.event('error')):>7} "
                  f"{self._cclose(s, streams):>12} "
                  )

    def tabs(self, s: H2StreamEvents, name: str, with_wstats=False):
        e = s.event(name)
        if e is None:
            return '--'
        if with_wstats and self.wstats.has_data():
            return f"{str(e.timestamp)} {self.wstats.in_use_at(e.timedelta):2}w"
        else:
            return f"{str(e.timestamp)}"

    def stdelta(self, s: H2StreamEvents, e: HttpdLogEntry, with_wstats=False):
        if e is None:
            return '*' if s.is_conn else '--'
        return self.tdelta(s, e, with_wstats=with_wstats)

    def tdelta(self, s: H2StreamEvents, e: HttpdLogEntry, with_wstats=False):
        if e is None:
            return '     --     '
        d = e.timedelta - s.event('created').timedelta
        if with_wstats and self.wstats.has_data():
            return f"+{d.seconds:d}.{d.microseconds:06d} {self.wstats.in_use_at(e.timedelta):2}w"
        else:
            return f"+{d.seconds:d}.{d.microseconds:06d}"

    def _error(self, s: H2StreamEvents, e: HttpdLogEntry):
        err = 0
        if e is not None:
            m = re.match(r'.*error=(\d+),.*', e.message)
            err = int(m.group(1))
            if err != 0:
                d = e.timedelta - s.event('created').timedelta
                return f"{err} +{d.seconds:d}.{d.microseconds:06d}"
        return '--'

    def _cclose(self, s: H2StreamEvents, streams: List[H2StreamEvents]):
        err = 0
        if s.is_conn:
            return '*'
        chid, cid, sid = s.split_gid(s.gid)
        conn_gid = f'{chid}-{cid}-0'
        screated = s.event('created')
        if screated is not None:
            for cs in streams:
                if not cs.is_conn or cs.gid != conn_gid:
                    continue
                e = cs.event('cleanup')
                if e is not None:
                    d = e.timedelta - screated.timedelta
                    return f"{d.seconds:d}.{d.microseconds:06d}"
                break
        return '--'

    def _resp(self, s: H2StreamEvents, e: HttpdLogEntry):
        if e is None:
            return '*' if s.is_conn else '--'
        m = re.match(r'.*submit response (?P<status>\d+).*', e.message)
        status = m.group('status') if m else '???'
        d = e.timedelta - s.event('created').timedelta
        return f"{status} +{d.seconds:d}.{d.microseconds:06d}"


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
