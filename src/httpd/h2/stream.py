import logging
import re
from typing import Optional, List

from ..log import HttpdLogEntry


log = logging.getLogger(__name__)


class H2StreamEvents:
    """Statistics related to a particular HTTP/2 stream in httpd
    """

    @staticmethod
    def global_id(m: re.Match, e: HttpdLogEntry):
        return f"{e.pid}-{m.group('session')}-{m.group('stream')}"

    @staticmethod
    def split_gid(gid: str):
        pid, session, stream = gid.split('-')
        return int(pid), int(session), int(stream)

    def __init__(self, gid: str):
        self.gid = gid
        self.pid, self.session_id, self.stream_id = self.split_gid(gid)
        self._events = {}
        self.started = None
        self.ended = None
        self.cleanup = None
        self.destroyed = None
        self.reset = None

    def add_event(self, name: str, e: HttpdLogEntry):
        if name in self._events:
            x = self._events[name]
            if isinstance(x, HttpdLogEntry):
                self._events[name] = [x, e]
            else:
                x.append(e)
        else:
            self._events[name] = e

    def event(self, name: str) -> Optional[HttpdLogEntry]:
        if name not in self._events:
            return None
        e = self._events[name]
        return e if isinstance(e, HttpdLogEntry) else e[0]


class EventMatch:

    def __init__(self, event: str, pattern: re.Pattern, creating=False, aliasing=False):
        self.pattern = re.compile(pattern)
        self.event = event
        self.creating = creating
        self.aliasing = aliasing

    def match(self, e: HttpdLogEntry) -> Optional[str]:
        m = self.pattern.match(e.message)
        if m:
            return H2StreamEvents.global_id(m, e)
        return None


class H2StreamEventsCollector:

    RE_SSID = r'(?P<session>\d+)-(?P<stream>\d+)'
    RE_STREAM_CREATED = r'AH03082: h2_stream\(' + RE_SSID + r',IDLE\): created'
    RE_STREAM_SCHEDULE = r'h2_stream\(' + RE_SSID + r',.*\): schedule (?P<request>.*) chunked.*'
    RE_STREAM_STARTED = r'h2_task\(' + RE_SSID + r'\): process connection'
    RE_STREAM_ENDED = r'h2_mplx\(' + RE_SSID + r'\): request done, \d+.\d+ ms elapsed'
    RE_STREAM_CLEANUP = r'h2_stream\(' + RE_SSID + r',CLEANUP\): cleanup.*'
    RE_STREAM_DESTROYED = r'h2_stream\(' + RE_SSID + r',CLEANUP\): destroy.*'
    RE_STREAM_RESET = r'AH03067: h2_stream\(' + RE_SSID + r'\): RST_STREAM .*'
    RE_STREAM_FRAME = r'AH0306[68]: h2_session\((?P<session>\d+).*FRAME\[.*stream=(?P<stream>\d+).*'


    LIFETIME_MATCHER = [
        EventMatch(event='created', pattern=RE_STREAM_CREATED, creating=True),
        EventMatch(event='scheduled', pattern=RE_STREAM_SCHEDULE),
        EventMatch(event='started', pattern=RE_STREAM_STARTED, aliasing=True),
        EventMatch(event='ended', pattern=RE_STREAM_ENDED),
        EventMatch(event='cleanup', pattern=RE_STREAM_CLEANUP),
        EventMatch(event='destroyed', pattern=RE_STREAM_DESTROYED),
        EventMatch(event='reset', pattern=RE_STREAM_RESET),
    ]
    FRAME_MATCHER = EventMatch(event='frame', pattern=RE_STREAM_FRAME)

    def __init__(self, with_frames=False, for_streams: Optional[List[str]] = None):
        self._streams_by_gid = {}
        self._gid_by_alias = {}
        self._matcher = self.LIFETIME_MATCHER.copy()
        if with_frames:
            self._matcher.append(self.FRAME_MATCHER)
        self._for_streams = self._gid_patterns_for(for_streams)

    @staticmethod
    def _gid_patterns_for(identifier: Optional[List[str]]):
        if identifier is None or len(identifier) == 0:
            return None
        patterns = []
        for s in identifier:
            if re.match(r'^\d+-\d+-\d+$', s):
                patterns.append(re.compile(r'^' + s + r'$'))
            elif re.match(r'\d+-\d+', s):
                patterns.append(re.compile(r'^\d+-' + s + r'$'))
            else:
                patterns.append(re.compile(r'^\d+-\d+-' + s + r'$'))
        return patterns

    def _alias_git(self, gid: str) -> Optional[str]:
        # we have the problem that in 2.4.48 (and maybe earlier), the
        # connection ids seem to change in mpm_event and our h2_task ids
        # do not match the stream id used on the main connection.
        pid, session, stream_id = H2StreamEvents.split_gid(gid)
        candidates = list(s for s in self._streams_by_gid.values()
                          if s.stream_id == stream_id and s.pid == pid)
        if len(candidates) == 1:
            self._gid_by_alias[gid] = candidates[0].gid
            log.info(f"task {gid} attached to stream {candidates[0].gid}")
            return candidates[0].gid
        if len(candidates) == 0:
            log.info(f"stream {gid} unknown")
        else:
            log.warning(f"stream {gid} has {len(candidates)} possible matches, ignored")
        return None

    def _determine_gid(self, gid: str, m: EventMatch):
        if gid not in self._streams_by_gid:
            if gid in self._gid_by_alias:
                return self._gid_by_alias[gid]
            elif m.aliasing:
                real_gid = self._alias_git(gid)
                if real_gid:
                    return real_gid
        return gid

    def _is_interesting(self, gid: str):
        if self._for_streams:
            for pattern in self._for_streams:
                if pattern.match(gid):
                    return True
            return False
        return True

    def observe(self, e: HttpdLogEntry) -> bool:
        if e.module != 'http2':
            return False
        for m in self._matcher:
            gid = m.match(e)
            if gid is not None:
                gid = self._determine_gid(gid, m)
                stats = None
                if gid in self._streams_by_gid:
                    stats = self._streams_by_gid[gid]
                elif m.creating:
                    stats = H2StreamEvents(gid=gid)
                    self._streams_by_gid[gid] = stats
                if stats is not None:
                    stats.add_event(m.event, e)
                return self._is_interesting(gid)
        return False

    def get_streams(self) -> List[H2StreamEvents]:
        streams = list(s for s in self._streams_by_gid.values() if self._is_interesting(s.gid))
        return sorted(streams, key=lambda s: s.event('created').timedelta)

    def all_streams(self) -> List[H2StreamEvents]:
        return sorted(self._streams_by_gid.values(), key=lambda s: s.event('created').timedelta)
