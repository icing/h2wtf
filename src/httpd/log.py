import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Iterator, Iterable


log = logging.getLogger(__name__)


class HttpdLogEntry:

    def __init__(self, props: Dict[str, Any]):
        self._props = props

    def get(self, name: str, defval: Any = None) -> Any:
        return self._props[name] if name in self._props else defval

    @property
    def timestamp(self) -> datetime:
        return self.get('timestamp')

    @property
    def timedelta(self) -> timedelta:
        return self.get('timedelta')

    @property
    def module(self) -> str:
        return self.get('module')

    @property
    def level(self) -> str:
        return self.get('level')

    @property
    def pid(self) -> int:
        return self.get('pid', 0)

    @property
    def tid(self) -> int:
        return self.get('tid', 0)

    @property
    def source(self) -> str:
        return self.get('source')

    @property
    def client(self) -> str:
        return self.get('client')

    @property
    def message(self) -> str:
        return self.get('message')

    def __str__(self):
        mlevel = f""
        return f"+{self.timedelta} {self.pid}/{self.tid} {self.module}:{self.level} [{self.source}] {self.message}"


class HttpTimestampParser:
    """
    date/time parsing - the test of human ambition
    """
    ABR_MONTH_NAME = []

    def __init__(self):
        self._ts_pattern = re.compile(
            r'(?P<dname>\w+) (?P<mname>\w+) (?P<mday>\d\d) '
            '(?P<hour>\d\d):(?P<minute>\d\d):(?P<second>\d\d)'
            '.(?P<micros>\d+) (?P<year>\d+)')
        if len(self.ABR_MONTH_NAME) == 0:
            now = datetime.now()
            for i in range(12):
                dt = datetime(year=now.year, month=i+1, day=now.day)
                self.ABR_MONTH_NAME.append(dt.strftime("%b").lower())

    def parse(self, s: str) -> datetime:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
        m = self._ts_pattern.match(s)
        if m is None:
            raise ValueError(f"unrecognized timestamp: '{s}'")
        p = m.groupdict()
        if 'month' not in p and 'mname' in p:
            p['month'] = self.ABR_MONTH_NAME.index(p['mname'].lower()) + 1
        return datetime(year=int(p['year']), month=int(p['month']), day=int(p['mday']),
                        hour=int(p['hour']), minute=int(p['minute']), second=int(p['second']),
                        microsecond=int(p['micros']))


class HttpdLogParser:

    def __init__(self, pattern: re.Pattern):
        self._pattern = pattern
        self.started = None
        self._ts_parser = HttpTimestampParser()

    def parse_line(self, line: str) -> Optional[HttpdLogEntry]:
        m = self._pattern.match(line)
        if m is None:
            log.warning("not a recognized log line: %s", line)
            return None
        props = m.groupdict()
        self._convert_timestamp(props)
        if self.started:
            props['timedelta'] = props['timestamp'] - self.started
        else:
            self.started = props['timestamp']
            props['timedelta'] = timedelta(seconds=0)
        return HttpdLogEntry(props)

    def _convert_timestamp(self, props: Dict) -> None:
        ts = props['timestamp'] if 'timestamp' in props else None
        if isinstance(ts, datetime):
            return
        elif isinstance(ts, str):
            props['timestamp'] = self._ts_parser.parse(ts)
        else:
            raise Exception(f"unrecognized timestamp: {ts}")


class HttpdLogEntryIterator(Iterator):

    def __init__(self, parser: HttpdLogParser, fpath: str):
        self.parser = parser
        self.fpath = fpath
        self.fd = open(self.fpath)

    def __next__(self):
        while True:
            line = self.fd.readline()
            if len(line) == 0:
                self.fd.close()
                raise StopIteration
            entry = self.parser.parse_line(line)
            if entry:
                return entry

    def __iter__(self):
        return self


class HttpdLog(Iterable):

    RE_LINE = re.compile(
        r'\[(?P<timestamp>[^]]+)] '
        '\[(?P<module>\S+):(?P<level>\S+)] '
        '\[pid (?P<pid>\d+):tid (?P<tid>\d+)] '
        '((?P<source>\S+): )?'
        '(\[client (?P<client>\S+)] )?'
        '(?P<message>.*)')

    def __init__(self, fpath, pattern: re.Pattern = None):
        self._fpath = fpath
        self._pattern = pattern if pattern is not None else self.RE_LINE
        self._parser = HttpdLogParser(pattern=self._pattern)

    def read_all(self) -> List[HttpdLogEntry]:
        with open(self._fpath) as fd:
            return list(self._parser.parse_line(line)for line in fd)

    def __iter__(self) -> Iterator:
        return HttpdLogEntryIterator(parser=self._parser, fpath=self._fpath)
