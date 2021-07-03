import argparse
import itertools
import logging
import re
import sys
import traceback
from datetime import timedelta
from typing import Iterable, List

from httpd.log import HttpdLog, HttpdLogEntry

log = logging.getLogger(__name__)


class H2StreamStats:

    @staticmethod
    def global_id(sid: str, e: HttpdLogEntry):
        return f"{e.pid}:{sid}"

    @staticmethod
    def h2id(sid: str):
        m = re.match(r'.+-(\d+)', sid)
        return int(m.group(1)) if m else None

    def __init__(self, gid: str, e: HttpdLogEntry):
        self.gid = gid
        self.gid_alias = gid
        self.h2id = self.h2id(gid)
        self.pid = e.pid
        self.created = e
        self.started = None
        self.ended = None
        self.cleanup = None
        self.destroyed = None
        self.reset = None

    def set_gid_alias(self, gid: str):
        self.gid_alias = gid

    def set_started(self, e: HttpdLogEntry):
        self.started = e

    def set_ended(self, e: HttpdLogEntry):
        self.ended = e

    def set_cleanup(self, e: HttpdLogEntry):
        self.cleanup = e

    def set_destroy(self, e: HttpdLogEntry):
        self.destroyed = e

    def set_reset(self, e: HttpdLogEntry):
        self.reset = e

    @property
    def complete(self) -> bool:
        return self.started and self.ended and self.cleanup and self.destroyed


class H2WorkerChange:

    def __init__(self, t: timedelta, change: int, e: HttpdLogEntry = None):
        self.timedelta = t
        self.change = change
        self.e = e


class H2WorkerStatistics:

    def __init__(self):
        self._changes = list()

    def add_streams(self, streams: List[H2StreamStats]):
        for s in streams:
            if s.started:
                self._changes.append(H2WorkerChange(s.started.timedelta, +1, s.started))
            if s.ended:
                self._changes.append(H2WorkerChange(s.ended.timedelta, -1, s.ended))
        self._changes = sorted(self._changes, key=lambda c: c.timedelta)

    def in_use_at(self, t: timedelta):
        n = 0
        for c in [c for c in self._changes if c.timedelta <= t]:
            n += c.change
        return n


class H2StreamStatistics:
    RE_STREAM_CREATED = re.compile(r'AH03082: h2_stream\((?P<stream>\d+-\d+),IDLE\): created')
    RE_STREAM_STARTED = re.compile(r'h2_task\((?P<stream>\d+-\d+)\): process connection')
    RE_STREAM_ENDED = re.compile(r'h2_mplx\((?P<stream>\d+-\d+)\): request done, \d+.\d+ ms elapsed')
    RE_STREAM_CLEANUP = re.compile(r'h2_stream\((?P<stream>\d+-\d+),CLEANUP\): cleanup.*')
    RE_STREAM_DESTROY = re.compile(r'h2_stream\((?P<stream>\d+-\d+),CLEANUP\): destroy.*')
    RE_STREAM_RESET = re.compile(r'AH03067: h2_stream\((?P<stream>\d+-\d+)\): RST_STREAM .*')

    RE_STREAMS_LIFETIME_EVENTS = [
        RE_STREAM_CREATED,
        RE_STREAM_STARTED,
        RE_STREAM_ENDED,
        RE_STREAM_CLEANUP,
        RE_STREAM_DESTROY,
        RE_STREAM_RESET,
    ]

    def __init__(self):
        self.streams = list()
        self.stream_by_gid = {}
        self.worker_stats = H2WorkerStatistics()

    def add_events(self, entries: Iterable):
        for e in entries:
            if not H2WTF.is_http2(e):
                continue
            m = self.RE_STREAM_CREATED.match(e.message)
            if m:
                gid = H2StreamStats.global_id(m.group('stream'), e)
                if gid in self.stream_by_gid:
                    log.error(f"stream {gid} already exists, ignoring: {e}")
                    continue
                stats = H2StreamStats(gid=gid, e=e)
                self.stream_by_gid[stats.gid] = stats
                continue
            m = self.RE_STREAM_DESTROY.match(e.message)
            if m:
                gid = H2StreamStats.global_id(m.group('stream'), e)
                if gid in self.stream_by_gid:
                    self.stream_by_gid[gid].set_destroy(e)
                else:
                    log.info(f"stream {gid} unknown, ignoring {e}")
                continue
            m = self.RE_STREAM_STARTED.match(e.message)
            if m:
                gid = H2StreamStats.global_id(m.group('stream'), e)
                if gid in self.stream_by_gid:
                    self.stream_by_gid[gid].set_started(e)
                else:
                    # we have the problem that in 2.4.48 (and maybe earlier), the
                    # connection ids seem to change in mpm_event and our h2_task ids
                    # do not match the stream id used on the main connection.
                    h2id = H2StreamStats.h2id(gid)
                    if h2id is None:
                        log.warning(f"unrecognized stream id '{gid}', ignoring {e}")
                        continue
                    candidates = list(s for s in self.stream_by_gid.values()
                                      if s.h2id == h2id and e.pid == s.pid)
                    if len(candidates) == 0:
                        log.info(f"stream {gid} unknown, ignoring {e}")
                    elif len(candidates) == 1:
                        candidates[0].set_gid_alias(gid)
                        candidates[0].set_started(e)
                        log.info(f"task {gid} attached to stream {candidates[0].gid}")
                    else:
                        log.warning(f"task {gid} has {len(candidates)} possible matches, ignoring {e}")
                continue
            m = self.RE_STREAM_ENDED.match(e.message)
            if m:
                gid = H2StreamStats.global_id(m.group('stream'), e)
                if gid in self.stream_by_gid:
                    self.stream_by_gid[gid].set_ended(e)
                else:
                    candidates = list(s for s in self.stream_by_gid.values()
                                      if s.gid_alias == gid)
                    if len(candidates) == 1:
                        candidates[0].set_ended(e)
                    else:
                        log.info(f"stream {gid} unknown, ignoring {e}")
                continue
            m = self.RE_STREAM_CLEANUP.match(e.message)
            if m:
                gid = H2StreamStats.global_id(m.group('stream'), e)
                if gid in self.stream_by_gid:
                    self.stream_by_gid[gid].set_cleanup(e)
                else:
                    log.info(f"stream {gid} unknown, ignoring {e}")
                continue
            m = self.RE_STREAM_RESET.match(e.message)
            if m:
                gid = H2StreamStats.global_id(m.group('stream'), e)
                if gid in self.stream_by_gid:
                    self.stream_by_gid[gid].set_reset(e)
                else:
                    log.info(f"stream {gid} unknown, ignoring {e}")
                continue
        self.streams = sorted(self.stream_by_gid.values(), key=lambda s: s.created.timedelta)
        self.worker_stats.add_streams(self.streams)

    def summary(self):
        self.print_list(streams=self.streams, title=f"Streams (total={len(self.streams)})")

    def print_list(self, streams: List[H2StreamStats], title: str):
        print(title)
        print(f"{'id':16} {'created':^20} {'started':^18} "
              f"{'ended':^18} {'reset':^18} {'cleanup':^18} {'destroyed':^18}")
        for s in streams:
            print(f"{s.gid:16} {str(s.created.timedelta):16}"
                  f"{self.worker_stats.in_use_at(s.created.timedelta):>2}w "
                  f"{self.tdelta(s, s.started):>18} "
                  f"{self.tdelta(s, s.ended):>18} "
                  f"{self.tdelta(s, s.reset):>18} "
                  f"{self.tdelta(s, s.cleanup):>18} "
                  f"{self.tdelta(s, s.destroyed):>18} ")

    def tdelta(self, s: H2StreamStats, e: HttpdLogEntry):
        if e is None:
            return '--'
        d = e.timedelta - s.created.timedelta
        return f"+{d.seconds:d}.{d.microseconds:06d} {self.worker_stats.in_use_at(e.timedelta):2}w"


class H2WTF:

    RE_STREAM_EVENTS = [
        re.compile(r'(AH\d+: )?(h2_mplx|h2_session|h2_stream|h2_task)\((?P<stream>\d+-\d+)(,\S+)?\).*'),
    ]

    @staticmethod
    def is_http2(entry: HttpdLogEntry):
        return entry.module == 'http2'

    @staticmethod
    def is_h2_frame(entry: HttpdLogEntry):
        return entry.module == 'http2' and re.match(r'.*FRAME\[.*', entry.message)

    @staticmethod
    def is_h2_streams_lifetime(entry: HttpdLogEntry):
        if entry.module == 'http2':
            for r in H2StreamStatistics.RE_STREAMS_LIFETIME_EVENTS:
                if r.match(entry.message):
                    return True
        return False

    @staticmethod
    def is_h2_stream_related(entry: HttpdLogEntry, stream_id: str):
        if entry.module == 'http2':
            for r in H2WTF.RE_STREAM_EVENTS:
                m = r.match(entry.message)
                if m and (m.group('stream') == stream_id or m.group('stream').endswith(stream_id)):
                    return True
        return False

    @staticmethod
    def fmt_line(e: HttpdLogEntry):
        mlevel = f"{e.module:8} {e.level:6} [{e.source}]"
        return f"+{str(e.timedelta):>15} {e.pid:>7}/{e.tid} {mlevel:40} {e.message}"

    @classmethod
    def main(cls):
        # declare cmd line options/args
        parser = argparse.ArgumentParser(prog='h2wtf', description="""
            analyze h2 usage from apache httpd logs
            """)
        parser.add_argument("-A", "--aggregate", action='store_true', default=False,
                            help="show H2 stream aggregated stats")
        parser.add_argument("-F", "--frames", action='store_true', default=False,
                            help="show H2 frame related entries")
        parser.add_argument("-L", "--lifetime", action='store_true', default=False,
                            help="show H2 stream lifetime events")
        parser.add_argument("-S", "--stream", type=str,
                            help="show events for a particular stream")
        parser.add_argument("log_file", help="the httpd log file")
        args = parser.parse_args()

        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(logging.BASIC_FORMAT))
        logging.getLogger('').addHandler(console)

        rv = 0
        accept_filter = lambda x: cls.is_http2(x)
        if args.frames:
            accept_filter = lambda x: cls.is_h2_frame(x)
        elif args.lifetime:
            accept_filter = lambda x: cls.is_h2_streams_lifetime(x)
        elif args.stream:
            accept_filter = lambda x: cls.is_h2_stream_related(x, args.stream)
        try:
            httpd_log = HttpdLog(fpath=args.log_file)
            if args.aggregate:
                stats = H2StreamStatistics()
                stats.add_events(httpd_log)
                stats.summary()
            else:
                for entry in itertools.filterfalse(lambda x: not accept_filter(x), httpd_log):
                    print(cls.fmt_line(entry))

        except Exception as ex:
            log.error("unexpected exception: %s %s", ex, traceback.format_exc())
            rv = 1
        sys.exit(rv)


if __name__ == "__main__":
    H2WTF.main()
